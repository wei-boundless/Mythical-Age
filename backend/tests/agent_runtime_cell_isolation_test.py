from __future__ import annotations

import asyncio
from dataclasses import replace
import threading
import time
from types import SimpleNamespace

from harness.loop.task_run_execution_control import request_executor_stop
from harness.loop.task_executor_controller import TaskExecutorController
from harness.runtime.agent_scope import build_agent_run_scope
from harness.runtime.control_events import RuntimeSignalScope
from harness.runtime.agent_worker_backend import AgentWorkerHandle
from harness.runtime.agent_runtime_cell import AgentRuntimeCell
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.shared.models import TaskRun
from runtime.tool_runtime.tool_invocation_control import (
    ToolInvocationControlRegistry,
    build_tool_invocation_id,
    build_tool_invocation_idempotency_key,
    registry_for,
)


def test_runtime_control_bus_drains_by_scope_and_consumes_once(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope_a = RuntimeSignalScope(session_id="session:bus", task_run_id="taskrun:a", agent_run_id="agent:a", run_cell_id="cell:a")
    scope_b = RuntimeSignalScope(session_id="session:bus", task_run_id="taskrun:b", agent_run_id="agent:b", run_cell_id="cell:b")

    signal_a = host.control_bus.publish(
        "taskrun:a",
        signal_type="agent_runtime_cell_cancel_requested",
        scope=scope_a,
        source_authority="test",
        payload={"reason": "stop_a"},
    )
    host.control_bus.publish(
        "taskrun:b",
        signal_type="agent_runtime_cell_cancel_requested",
        scope=scope_b,
        source_authority="test",
        payload={"reason": "stop_b"},
    )

    snapshot_a = host.control_bus.drain("taskrun:a", scope=scope_a)
    assert [signal.signal_type for signal in snapshot_a.pending_signals] == ["agent_runtime_cell_cancel_requested"]
    assert snapshot_a.pending_signals[0].scope.run_cell_id == "cell:a"

    host.control_bus.mark_consumed("taskrun:a", signal=snapshot_a.pending_signals[0], consumed_by="test")
    consumed = host.control_bus.drain("taskrun:a", scope=scope_a)
    assert consumed.pending_signals == ()
    assert signal_a.refs["signal_ref"] == snapshot_a.pending_signals[0].signal_id


def test_runtime_control_bus_publish_is_idempotent_for_explicit_signal_id(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:bus", task_run_id="taskrun:idempotent", agent_run_id="agent:idempotent", run_cell_id="cell:idempotent")

    first = host.control_bus.publish(
        "taskrun:idempotent",
        signal_type="control.signal.requested",
        signal_id="rtsig:test:idempotent",
        scope=scope,
        source_authority="test",
        payload={"reason": "first"},
    )
    second = host.control_bus.publish(
        "taskrun:idempotent",
        signal_type="control.signal.requested",
        signal_id="rtsig:test:idempotent",
        scope=scope,
        source_authority="test",
        payload={"reason": "second"},
    )
    snapshot = host.control_bus.drain("taskrun:idempotent", scope=scope)

    assert second.event_id == first.event_id
    assert second.offset == first.offset
    assert len(host.event_log.list_events("taskrun:idempotent")) == 1
    assert [signal.signal_id for signal in snapshot.pending_signals] == ["rtsig:test:idempotent"]
    assert snapshot.pending_signals[0].payload["reason"] == "first"


def test_runtime_control_bus_observed_signal_is_not_drained_again(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:bus", task_run_id="taskrun:observed", agent_run_id="agent:observed", run_cell_id="cell:observed")
    event = host.control_bus.publish(
        "taskrun:observed",
        signal_type="control.signal.requested",
        scope=scope,
        source_authority="test",
        payload={"signal_kind": "stop"},
    )
    signal_id = str(dict(dict(event.payload or {}).get("signal") or {}).get("signal_id") or "")

    observed = host.control_bus.mark_observed_by_id(
        "taskrun:observed",
        signal_id=signal_id,
        observed_by="test.safe_boundary",
        payload={"observation_ref": "rtobs:observed"},
    )
    drained = host.control_bus.drain("taskrun:observed", scope=scope, signal_types={"control.signal.requested"})

    assert observed is not None
    assert dict(dict(observed.payload or {}).get("signal") or {})["consumption_state"] == "observed"
    assert drained.pending_signals == ()


def test_runtime_control_bus_marks_observed_signal_consumed_once(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:bus", task_run_id="taskrun:consumed", agent_run_id="agent:consumed", run_cell_id="cell:consumed")
    event = host.control_bus.publish(
        "taskrun:consumed",
        signal_type="control.signal.requested",
        scope=scope,
        source_authority="test",
        payload={"signal_kind": "stop"},
    )
    signal_id = str(dict(dict(event.payload or {}).get("signal") or {}).get("signal_id") or "")

    observed = host.control_bus.mark_observed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        observed_by="test.safe_boundary",
        payload={"observation_ref": "rtobs:consumed"},
    )
    consumed = host.control_bus.mark_consumed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        consumed_by="test.closeout",
        payload={"terminal_reason": "user_aborted"},
    )
    duplicate = host.control_bus.mark_consumed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        consumed_by="test.closeout",
        payload={"terminal_reason": "duplicate"},
    )

    assert observed is not None
    assert consumed is not None
    assert duplicate is None
    assert dict(dict(consumed.payload or {}).get("signal") or {})["consumption_state"] == "consumed"
    assert dict(dict(dict(consumed.payload or {}).get("signal") or {}).get("payload") or {})["terminal_reason"] == "user_aborted"


def test_worker_cancel_request_does_not_relabel_already_done_task_as_cancelled() -> None:
    handle = AgentWorkerHandle(
        worker_id="agent-worker:done",
        run_cell_id="cell:done",
        thread=threading.Thread(),
        started_at=time.time(),
        task=SimpleNamespace(done=lambda: True),
    )

    assert handle.request_cancel("late_stop") is False
    assert handle.cancel_requested is True
    assert handle.cancel_reason == "late_stop"
    assert handle.cancel_delivered is False
    assert handle.cancelled is False


def test_cell_terminal_status_treats_delivered_cancel_as_cancelled_even_if_work_returns() -> None:
    scope = build_agent_run_scope(
        session_id="session:cancel-delivered",
        invocation_kind="task_run",
        task_run_id="taskrun:cancel-delivered",
        agent_run_id="agent:cancel-delivered",
        run_cell_id="cell:cancel-delivered",
    )
    cell = AgentRuntimeCell(scope=scope, worker_backend=SimpleNamespace(backend_name="test"))
    handle = AgentWorkerHandle(
        worker_id="agent-worker:cancel-delivered",
        run_cell_id=scope.run_cell_id,
        thread=threading.Thread(),
        started_at=time.time(),
        done_at=time.time(),
        result={"status": "completed"},
        cancel_requested=True,
        cancel_delivered=True,
    )
    cell.worker_handle = handle

    cell.mark_done(handle)
    snapshot = cell.to_dict()

    assert cell.status == "cancelled"
    assert snapshot["worker"]["cancel_requested"] is True
    assert snapshot["worker"]["cancel_delivered"] is True
    assert snapshot["worker"]["cancelled"] is False


def test_tool_invocation_identity_includes_agent_run_and_cell_scope() -> None:
    common = {
        "caller_ref": "taskrun:same",
        "action_request_ref": "action:same",
        "tool_name": "read_file",
        "tool_call_id": "call:same",
        "agent_run_id": "agent:same",
    }

    id_a = build_tool_invocation_id(**common, run_cell_id="cell:a")
    id_b = build_tool_invocation_id(**common, run_cell_id="cell:b")
    key_a = build_tool_invocation_idempotency_key(**common, tool_invocation_id=id_a, run_cell_id="cell:a")
    key_b = build_tool_invocation_idempotency_key(**common, tool_invocation_id=id_b, run_cell_id="cell:b")

    assert id_a != id_b
    assert key_a != key_b


def test_cell_local_tool_registry_cancels_only_matching_scope() -> None:
    registry_a = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    registry_b = ToolInvocationControlRegistry(agent_run_id="agent:b", run_cell_id="cell:b")
    registry_a.start(
        tool_invocation_id="toolinv:a",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    registry_a.start(
        tool_invocation_id="toolinv:foreign",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        agent_run_id="agent:b",
        run_cell_id="cell:b",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    registry_b.start(
        tool_invocation_id="toolinv:b",
        caller_kind="task_run",
        caller_ref="taskrun:b",
        task_run_id="taskrun:b",
        tool_name="read_file",
    )

    cancelled = registry_a.cancel_by_caller(
        task_run_id="taskrun:a",
        kind="stop",
        reason="cancel_a_only",
    )

    assert cancelled == 1
    assert registry_a.record("toolinv:a").status == "cancelled"
    assert registry_a.record("toolinv:foreign").status == "running"
    assert registry_b.record("toolinv:b").status == "running"


def test_cancelled_tool_invocation_record_is_terminal() -> None:
    registry = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    registry.start(
        tool_invocation_id="toolinv:terminal",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )

    assert registry.request_cancel(tool_invocation_id="toolinv:terminal", reason="stop_a") is True
    completed = registry.complete("toolinv:terminal", result_ref="late-result")
    failed = registry.fail("toolinv:terminal", error="late-error")

    assert completed.status == "cancelled"
    assert failed.status == "cancelled"
    assert registry.record("toolinv:terminal").result_ref == ""
    assert registry.record("toolinv:terminal").error == "stop_a"


def test_control_signal_without_live_cell_cancels_only_target_scope(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:scoped-stop"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session:scoped-stop",
            task_id="task:scoped-stop",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={
                "agent_run_scope": {
                    "session_id": "session:scoped-stop",
                    "task_run_id": task_run_id,
                    "agent_run_id": "agent:target",
                    "run_cell_id": "cell:target",
                },
                "agent_run_id": "agent:target",
                "run_cell_id": "cell:target",
            },
        )
    )
    registry = registry_for(host)
    assert registry is not None
    registry.start(
        tool_invocation_id="toolinv:target",
        caller_kind="task_run",
        caller_ref=task_run_id,
        agent_run_id="agent:target",
        run_cell_id="cell:target",
        task_run_id=task_run_id,
        tool_name="read_file",
    )
    registry.start(
        tool_invocation_id="toolinv:other-cell",
        caller_kind="task_run",
        caller_ref=task_run_id,
        agent_run_id="agent:other",
        run_cell_id="cell:other",
        task_run_id=task_run_id,
        tool_name="read_file",
    )

    assert request_executor_stop(host, task_run_id=task_run_id, reason="scope_stop", requested_by="test") is True

    assert registry.record("toolinv:target").status == "cancelled"
    assert registry.record("toolinv:other-cell").status == "running"
    unavailable = _control_signal_payloads(host, task_run_id, "control.signal.target_unavailable")
    assert unavailable
    assert unavailable[-1]["target_agent_run_id"] == "agent:target"
    assert unavailable[-1]["target_run_cell_id"] == "cell:target"
    assert unavailable[-1]["host_registry_cancel_count"] == 1


def test_active_cell_control_signal_uses_bus_not_mailbox_shadow_route(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:active-cell-stop"
    _insert_task_run(host, task_run_id)
    started = threading.Event()
    release = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    scheduled = controller.schedule(task_run_id, scheduler="test", max_steps=1)
    cell = None
    try:
        assert scheduled["scheduled"] is True
        assert _wait_until(started.is_set)
        assert _wait_until(lambda: host.agent_run_supervisor.active_cell_for_task_run(task_run_id) is not None)
        cell = host.agent_run_supervisor.active_cell_for_task_run(task_run_id)
        assert cell is not None
        cell.mailbox.drain()
        cell.tool_invocation_registry.start(
            tool_invocation_id="toolinv:active-cell-target",
            caller_kind="task_run",
            caller_ref=task_run_id,
            task_run_id=task_run_id,
            tool_name="read_file",
        )

        assert request_executor_stop(host, task_run_id=task_run_id, reason="active_cell_stop", requested_by="test") is True

        requested = [
            dict(dict(event.payload or {}).get("signal") or {})
            for event in host.event_log.list_events(task_run_id)
            if event.event_type == "runtime_control_signal_published"
            and dict(dict(event.payload or {}).get("signal") or {}).get("signal_type") == "control.signal.requested"
        ]
        scope = RuntimeSignalScope(
            session_id="session:cell-isolation",
            task_run_id=task_run_id,
            agent_run_id=str(scheduled["agent_run_id"]),
            run_cell_id=str(scheduled["run_cell_id"]),
        )
        drained = host.control_bus.drain(
            task_run_id,
            scope=scope,
            signal_types={"control.signal.requested"},
        )
        mailbox_items = cell.mailbox.drain()

        assert len(requested) == 1
        assert dict(requested[0]["scope"])["agent_run_id"] == scheduled["agent_run_id"]
        assert dict(requested[0]["scope"])["run_cell_id"] == scheduled["run_cell_id"]
        assert [signal.signal_id for signal in drained.pending_signals] == [requested[0]["signal_id"]]
        assert drained.pending_signals[0].payload["signal_kind"] == "stop"
        assert drained.pending_signals[0].payload["reason"] == "active_cell_stop"
        assert cell.tool_invocation_registry.record("toolinv:active-cell-target").status == "cancelled"
        assert all(item.item_type != "control.signal.requested" for item in mailbox_items)
    finally:
        release.set()
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=3)


def test_task_executor_controller_schedules_task_runs_in_isolated_cells(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:a")
    _insert_task_run(host, "taskrun:b")
    started: set[str] = set()
    release = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        started.add(task_run_id)
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result_a = controller.schedule("taskrun:a", scheduler="test", max_steps=1)
    result_b = controller.schedule("taskrun:b", scheduler="test", max_steps=1)

    assert result_a["scheduled"] is True
    assert result_b["scheduled"] is True
    assert result_a["agent_run_id"] != result_b["agent_run_id"]
    assert result_a["run_cell_id"] != result_b["run_cell_id"]

    cell_a = host.agent_run_supervisor.active_cell_for_task_run("taskrun:a")
    cell_b = host.agent_run_supervisor.active_cell_for_task_run("taskrun:b")
    assert cell_a is not None
    assert cell_b is not None
    assert cell_a.mailbox is not cell_b.mailbox
    assert cell_a.cancellation_token is not cell_b.cancellation_token
    assert cell_a.tool_invocation_registry is not cell_b.tool_invocation_registry
    assert cell_a.tool_invocation_registry.run_cell_id == result_a["run_cell_id"]
    assert cell_b.tool_invocation_registry.run_cell_id == result_b["run_cell_id"]
    cell_a.tool_invocation_registry.start(
        tool_invocation_id="toolinv:cell-a",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    cell_b.tool_invocation_registry.start(
        tool_invocation_id="toolinv:cell-b",
        caller_kind="task_run",
        caller_ref="taskrun:b",
        task_run_id="taskrun:b",
        tool_name="read_file",
    )

    assert _wait_until(lambda: started == {"taskrun:a", "taskrun:b"})
    assert host.agent_run_supervisor.cancel_task_run("taskrun:a", reason="test_cancel_a") is True
    assert cell_a.cancellation_token.cancelled is True
    assert cell_b.cancellation_token.cancelled is False
    assert cell_a.tool_invocation_registry.record("toolinv:cell-a").status == "cancelled"
    assert cell_b.tool_invocation_registry.record("toolinv:cell-b").status == "running"
    assert cell_b.is_running()

    release.set()
    assert cell_a.worker_handle.join(timeout=3)
    assert cell_b.worker_handle.join(timeout=3)

    diagnostics_a = host.state_index.get_task_run("taskrun:a").diagnostics
    diagnostics_b = host.state_index.get_task_run("taskrun:b").diagnostics
    assert diagnostics_a["executor_status"] == "scheduled"
    assert diagnostics_a["agent_run_scope"]["run_cell_id"] == result_a["run_cell_id"]
    assert diagnostics_b["executor_status"] == "scheduled"
    assert diagnostics_b["agent_run_scope"]["run_cell_id"] == result_b["run_cell_id"]


def test_cell_mailbox_overflow_publishes_scoped_backpressure_event(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:mailbox-a")
    _insert_task_run(host, "taskrun:mailbox-b")
    release = threading.Event()

    async def work() -> dict[str, str]:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    scheduled_a = host.agent_run_supervisor.schedule_task_run(
        task_run_id="taskrun:mailbox-a",
        work_factory=work,
        scheduler="test",
        max_steps=1,
    )
    scheduled_b = host.agent_run_supervisor.schedule_task_run(
        task_run_id="taskrun:mailbox-b",
        work_factory=work,
        scheduler="test",
        max_steps=1,
    )
    cell_a = host.agent_run_supervisor.cell_by_id(scheduled_a["run_cell_id"])
    cell_b = host.agent_run_supervisor.cell_by_id(scheduled_b["run_cell_id"])
    try:
        assert cell_a is not None
        assert cell_b is not None
        cell_a.mailbox.drain()

        for index in range(cell_a.mailbox.maxsize + 1):
            cell_a.mailbox.put("test.mailbox.item", {"index": index})

        overload_events_a = [
            event
            for event in host.event_log.list_events("taskrun:mailbox-a")
            if event.event_type == "agent_runtime_cell_mailbox_overloaded"
        ]
        overload_events_b = [
            event
            for event in host.event_log.list_events("taskrun:mailbox-b")
            if event.event_type == "agent_runtime_cell_mailbox_overloaded"
        ]
        bus_overload_a = [
            signal
            for signal in host.control_bus.drain(
                "taskrun:mailbox-a",
                scope=RuntimeSignalScope(
                    session_id="session:cell-isolation",
                    task_run_id="taskrun:mailbox-a",
                    agent_run_id=scheduled_a["agent_run_id"],
                    run_cell_id=scheduled_a["run_cell_id"],
                ),
                signal_types={"agent_runtime_cell_mailbox_overloaded"},
            ).pending_signals
        ]
        bus_overload_b = [
            signal
            for signal in host.control_bus.drain(
                "taskrun:mailbox-b",
                scope=RuntimeSignalScope(
                    session_id="session:cell-isolation",
                    task_run_id="taskrun:mailbox-b",
                    agent_run_id=scheduled_b["agent_run_id"],
                    run_cell_id=scheduled_b["run_cell_id"],
                ),
                signal_types={"agent_runtime_cell_mailbox_overloaded"},
            ).pending_signals
        ]

        assert len(overload_events_a) == 1
        assert overload_events_b == []
        assert dict(overload_events_a[0].payload)["agent_scope"]["run_cell_id"] == scheduled_a["run_cell_id"]
        assert dict(overload_events_a[0].payload)["reason"] == "mailbox_full"
        assert dict(overload_events_a[0].payload)["dropped_item_type"] == "test.mailbox.item"
        assert dict(overload_events_a[0].payload)["maxsize"] == cell_a.mailbox.maxsize
        assert dict(overload_events_a[0].payload)["dropped_count"] == 1
        assert cell_a.mailbox.dropped_count == 1
        assert cell_b.mailbox.dropped_count == 0
        assert len(bus_overload_a) == 1
        assert bus_overload_a[0].scope.run_cell_id == scheduled_a["run_cell_id"]
        assert bus_overload_a[0].payload["reason"] == "mailbox_full"
        assert bus_overload_b == []
    finally:
        release.set()
        if cell_a is not None and cell_a.worker_handle is not None:
            cell_a.worker_handle.join(timeout=3)
        if cell_b is not None and cell_b.worker_handle is not None:
            cell_b.worker_handle.join(timeout=3)


def test_cancel_requested_cell_does_not_block_other_agent_slot(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    host.agent_run_supervisor.max_active_cells = 1
    _insert_task_run(host, "taskrun:a")
    _insert_task_run(host, "taskrun:b")
    started: set[str] = set()
    release = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        started.add(task_run_id)
        while not release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                if task_run_id == "taskrun:a":
                    continue
                raise
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result_a = controller.schedule("taskrun:a", scheduler="test", max_steps=1)
    assert result_a["scheduled"] is True
    assert _wait_until(lambda: started == {"taskrun:a"})

    cell_a = host.agent_run_supervisor.active_cell_for_task_run("taskrun:a")
    assert cell_a is not None
    assert host.agent_run_supervisor.cancel_task_run("taskrun:a", reason="cancel_a") is True
    assert _wait_until(lambda: cell_a.status == "cancel_requested")
    assert cell_a.is_running()

    result_b = controller.schedule("taskrun:b", scheduler="test", max_steps=1)
    cell_b = host.agent_run_supervisor.active_cell_for_task_run("taskrun:b")

    assert result_b["scheduled"] is True
    assert cell_b is not None
    assert result_b["run_cell_id"] != result_a["run_cell_id"]
    assert _wait_until(lambda: started == {"taskrun:a", "taskrun:b"})

    release.set()
    assert cell_a.worker_handle.join(timeout=3)
    assert cell_b.worker_handle.join(timeout=3)
    assert cell_a.status == "cancelled"
    assert cell_b.status == "completed"
    assert any(event.event_type == "agent_runtime_cell_cancelled" for event in host.event_log.list_events("taskrun:a"))
    assert any(event.event_type == "agent_runtime_cell_completed" for event in host.event_log.list_events("taskrun:b"))


def test_supervisor_cancels_terminal_task_run_cell(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:terminal-cell")
    release = threading.Event()

    async def work() -> dict[str, str]:
        while not release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                continue
        return {"status": "completed"}

    scheduled = host.agent_run_supervisor.schedule_task_run(
        task_run_id="taskrun:terminal-cell",
        work_factory=work,
        scheduler="test",
        max_steps=1,
    )
    assert scheduled["scheduled"] is True
    assert _wait_until(lambda: host.agent_run_supervisor.active_cell_for_task_run("taskrun:terminal-cell") is not None)
    task_run = host.state_index.get_task_run("taskrun:terminal-cell")
    host.state_index.upsert_task_run(replace(task_run, status="completed", updated_at=time.time()))

    supervision = host.agent_run_supervisor.supervise_cells()
    cell = host.agent_run_supervisor.cell_by_id(scheduled["run_cell_id"])

    assert supervision["cancelled_count"] == 1
    assert supervision["cancelled"][0]["reason"] == "task_run_terminal:completed"
    assert cell is not None
    assert cell.status == "cancel_requested"

    release.set()
    assert cell.worker_handle.join(timeout=3)
    assert cell.status == "cancelled"


def _insert_task_run(host: SingleAgentRuntimeHost, task_run_id: str) -> None:
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session:cell-isolation",
            task_id=f"task:{task_run_id}",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={},
        )
    )


def _wait_until(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _control_signal_payloads(host: SingleAgentRuntimeHost, run_id: str, signal_type: str) -> list[dict]:
    payloads: list[dict] = []
    for event in host.event_log.list_events(run_id):
        signal = dict(dict(event.payload or {}).get("signal") or {})
        if str(signal.get("signal_type") or "") != signal_type:
            continue
        payloads.append(dict(signal.get("payload") or {}))
    return payloads
