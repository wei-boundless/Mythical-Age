from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time
from types import SimpleNamespace
from typing import get_args

from harness.loop.task_run_execution_control import _latest_requested_control_signal, request_executor_stop
from harness.loop.task_executor_controller import TaskExecutorController
from harness.loop.single_agent_turn import _start_turn_runtime
from harness.runtime.agent_scope import build_agent_run_scope
from harness.runtime.control_events import RuntimeSignalScope, build_runtime_signal_envelope
from harness.runtime.agent_worker_backend import AgentWorkerHandle
from harness.runtime.agent_runtime_cell import AgentRuntimeCell
from harness.runtime.output_commit_authority import OutputCommitAuthority, OutputCommitRequest
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from runtime.shared.models import TaskRun
from runtime.tool_runtime.tool_invocation_control import (
    ToolInvocationAlreadyStartedError,
    ToolInvocationControlRegistry,
    build_tool_invocation_id,
    build_tool_invocation_idempotency_key,
    registry_for,
)
from runtime.shared.event_log import _RUNTIME_EVENT_FACT_TYPES
from runtime.shared.events import RuntimeEventType


AGENT_RUNTIME_CELL_EVENT_TYPES = {
    "agent_runtime_cell_backpressure",
    "agent_runtime_cell_cancel_requested",
    "agent_runtime_cell_cancelled",
    "agent_runtime_cell_completed",
    "agent_runtime_cell_created",
    "agent_runtime_cell_failed",
    "agent_runtime_cell_late_event_rejected",
    "agent_runtime_cell_mailbox_overloaded",
    "agent_runtime_cell_start_failed",
    "agent_runtime_cell_started",
    "agent_runtime_cell_supervision_cancel_requested",
}


def test_agent_runtime_cell_event_contract_is_registered() -> None:
    runtime_event_types = set(get_args(RuntimeEventType))

    assert AGENT_RUNTIME_CELL_EVENT_TYPES <= runtime_event_types
    assert AGENT_RUNTIME_CELL_EVENT_TYPES <= _RUNTIME_EVENT_FACT_TYPES


def test_agent_runtime_cell_event_facts_preserve_scope_and_cell_refs(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:cell-facts"
    turn_id = "turn:cell-facts"
    _insert_task_run(host, task_run_id)
    release = threading.Event()

    async def work() -> dict[str, str]:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    scheduled = host.agent_run_supervisor.schedule_task_run(
        task_run_id=task_run_id,
        work_factory=work,
        scheduler="test",
        max_steps=1,
        turn_id=turn_id,
    )
    cell = host.agent_run_supervisor.cell_by_id(scheduled["run_cell_id"])
    try:
        assert scheduled["scheduled"] is True
        assert cell is not None

        runtime_facts = host.fact_ledger.list_records(
            task_run_id=task_run_id,
            fact_type="runtime_event",
            limit=50,
        )
        cell_facts = host.fact_ledger.list_records(
            run_cell_ref=scheduled["run_cell_id"],
            fact_type="runtime_event",
            limit=50,
        )
        created_fact = _runtime_event_fact(runtime_facts, "agent_runtime_cell_created")
        started_fact = _runtime_event_fact(runtime_facts, "agent_runtime_cell_started")
        cell_fact_types = {
            str(dict(fact.attributes or {}).get("event_type") or "")
            for fact in cell_facts
        }

        for fact in (created_fact, started_fact):
            assert fact.scope["session_id"] == "session:cell-isolation"
            assert fact.scope["task_run_id"] == task_run_id
            assert fact.scope["turn_id"] == turn_id
            assert fact.refs["agent_run_ref"] == scheduled["agent_run_id"]
            assert fact.refs["run_cell_ref"] == scheduled["run_cell_id"]
            assert fact.refs["runtime_event_id"]
        assert {"agent_runtime_cell_created", "agent_runtime_cell_started"} <= cell_fact_types
    finally:
        release.set()
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=3)


def test_runtime_gateway_drains_by_scope_and_consumes_once(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope_a = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:a", agent_run_id="agent:a", run_cell_id="cell:a")
    scope_b = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:b", agent_run_id="agent:b", run_cell_id="cell:b")

    signal_a = host.runtime_gateway.publish(
        "taskrun:a",
        signal_type="agent_runtime_cell_cancel_requested",
        scope=scope_a,
        source_authority="test",
        payload={"reason": "stop_a"},
    )
    host.runtime_gateway.publish(
        "taskrun:b",
        signal_type="agent_runtime_cell_cancel_requested",
        scope=scope_b,
        source_authority="test",
        payload={"reason": "stop_b"},
    )

    snapshot_a = host.runtime_gateway.drain("taskrun:a", scope=scope_a)
    assert [signal.signal_type for signal in snapshot_a.pending_signals] == ["agent_runtime_cell_cancel_requested"]
    assert snapshot_a.pending_signals[0].scope.run_cell_id == "cell:a"

    host.runtime_gateway.mark_consumed("taskrun:a", signal=snapshot_a.pending_signals[0], consumed_by="test")
    consumed = host.runtime_gateway.drain("taskrun:a", scope=scope_a)
    assert consumed.pending_signals == ()
    assert signal_a.refs["signal_ref"] == snapshot_a.pending_signals[0].signal_id


def test_runtime_gateway_task_scoped_signal_drains_into_current_cell_scope(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_scope = RuntimeSignalScope(session_id="session:gateway-task-scope", task_run_id="taskrun:gateway-task-scope")
    current_cell_scope = RuntimeSignalScope(
        session_id="session:gateway-task-scope",
        task_run_id="taskrun:gateway-task-scope",
        agent_run_id="agent:current",
        run_cell_id="cell:current",
    )
    other_cell_scope = RuntimeSignalScope(
        session_id="session:gateway-task-scope",
        task_run_id="taskrun:gateway-task-scope",
        agent_run_id="agent:other",
        run_cell_id="cell:other",
    )

    host.runtime_gateway.publish(
        "taskrun:gateway-task-scope",
        signal_type="control.signal.requested",
        scope=task_scope,
        source_authority="test",
        payload={"signal_kind": "stop", "reason": "task_scope"},
    )
    host.runtime_gateway.publish(
        "taskrun:gateway-task-scope",
        signal_type="control.signal.requested",
        scope=other_cell_scope,
        source_authority="test",
        payload={"signal_kind": "stop", "reason": "other_cell"},
    )
    host.runtime_gateway.publish(
        "taskrun:gateway-task-scope",
        signal_type="tool.execution.started",
        scope=task_scope,
        source_authority="test",
        payload={"tool_invocation_id": "tool:task-scope", "reason": "tool_task_scope"},
    )

    control_snapshot = host.runtime_gateway.drain(
        "taskrun:gateway-task-scope",
        scope=current_cell_scope,
        signal_types={"control.signal.requested"},
    )
    tool_snapshot = host.runtime_gateway.drain(
        "taskrun:gateway-task-scope",
        scope=current_cell_scope,
        signal_types={"tool.execution.started"},
    )

    assert [signal.payload["reason"] for signal in control_snapshot.pending_signals] == ["task_scope"]
    assert tool_snapshot.pending_signals == ()


def test_runtime_gateway_publish_is_idempotent_for_explicit_signal_id(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:idempotent", agent_run_id="agent:idempotent", run_cell_id="cell:idempotent")

    first = host.runtime_gateway.publish(
        "taskrun:idempotent",
        signal_type="control.signal.requested",
        signal_id="rtsig:test:idempotent",
        scope=scope,
        source_authority="test",
        payload={"reason": "first"},
    )
    second = host.runtime_gateway.publish(
        "taskrun:idempotent",
        signal_type="control.signal.requested",
        signal_id="rtsig:test:idempotent",
        scope=scope,
        source_authority="test",
        payload={"reason": "second"},
    )
    snapshot = host.runtime_gateway.drain("taskrun:idempotent", scope=scope)

    assert second.event_id == first.event_id
    assert second.offset == first.offset
    assert len(host.event_log.list_events("taskrun:idempotent")) == 1
    assert [signal.signal_id for signal in snapshot.pending_signals] == ["rtsig:test:idempotent"]
    assert snapshot.pending_signals[0].payload["reason"] == "first"


def test_runtime_gateway_publish_is_atomic_for_explicit_signal_id(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:atomic", agent_run_id="agent:atomic", run_cell_id="cell:atomic")
    barrier = threading.Barrier(8)

    def publish(attempt: int):
        barrier.wait(timeout=3)
        return host.runtime_gateway.publish(
            "taskrun:atomic",
            signal_type="tool.execution.started",
            signal_id="toolexec:atomic:started",
            scope=scope,
            source_authority="test.concurrent_publish",
            payload={"attempt": attempt},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(publish, range(8)))

    stored_events = host.event_log.list_events("taskrun:atomic")
    snapshot = host.runtime_gateway.drain("taskrun:atomic", scope=scope)

    assert len({event.event_id for event in events}) == 1
    assert len(stored_events) == 1
    assert [signal.signal_id for signal in snapshot.pending_signals] == ["toolexec:atomic:started"]
    assert snapshot.pending_signals[0].payload["attempt"] in set(range(8))


def test_runtime_gateway_rejects_signal_id_reuse_across_signal_types(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:id-conflict", agent_run_id="agent:id-conflict", run_cell_id="cell:id-conflict")
    host.runtime_gateway.publish(
        "taskrun:id-conflict",
        signal_type="tool.permission.decided",
        signal_id="rtsig:test:conflict",
        scope=scope,
        source_authority="test",
        payload={"phase": "permission"},
    )

    try:
        host.runtime_gateway.publish(
            "taskrun:id-conflict",
            signal_type="tool.execution.started",
            signal_id="rtsig:test:conflict",
            scope=scope,
            source_authority="test",
            payload={"phase": "started"},
        )
    except ValueError as error:
        assert "signal_id conflict" in str(error)
    else:
        raise AssertionError("RuntimeGateway accepted one signal_id for two signal types")


def test_runtime_gateway_ignores_derived_signal_events_without_published_source(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:derived-only", agent_run_id="agent:derived-only", run_cell_id="cell:derived-only")
    signal_id = "rtsig:test:derived-only"
    for event_type, state, actor in (
        ("runtime_control_signal_observed", "observed", "test.observer"),
        ("runtime_control_signal_consumed", "consumed", "test.consumer"),
    ):
        derived = build_runtime_signal_envelope(
            signal_type="control.signal.requested",
            signal_id=signal_id,
            scope=scope,
            source_authority="test",
            payload={"signal_kind": "stop", "origin": event_type},
            consumption_state=state,
            consumed_by=actor,
        )
        host.event_log.append(
            "taskrun:derived-only",
            event_type,  # type: ignore[arg-type]
            payload={"signal": derived.to_dict()},
            refs={"signal_ref": signal_id},
        )

    assert host.runtime_gateway.signal_by_id("taskrun:derived-only", signal_id=signal_id) is None
    assert host.runtime_gateway.can_consume_by_id("taskrun:derived-only", signal_id=signal_id) is False
    assert (
        host.runtime_gateway.mark_observed_by_id(
            "taskrun:derived-only",
            signal_id=signal_id,
            observed_by="test.safe_boundary",
        )
        is None
    )
    assert (
        host.runtime_gateway.mark_consumed_by_id(
            "taskrun:derived-only",
            signal_id=signal_id,
            consumed_by="test.closeout",
        )
        is None
    )


def test_runtime_gateway_signal_lookup_and_consumption_use_published_source(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:published-source", agent_run_id="agent:published-source", run_cell_id="cell:published-source")
    signal_id = "rtsig:test:published-source"
    for event_type, state, actor in (
        ("runtime_control_signal_observed", "observed", "test.observer"),
        ("runtime_control_signal_consumed", "consumed", "test.consumer"),
    ):
        derived_first = build_runtime_signal_envelope(
            signal_type="control.signal.requested",
            signal_id=signal_id,
            scope=scope,
            source_authority="test",
            payload={"signal_kind": "stop", "origin": event_type},
            consumption_state=state,
            consumed_by=actor,
        )
        host.event_log.append(
            "taskrun:published-source",
            event_type,  # type: ignore[arg-type]
            payload={"signal": derived_first.to_dict()},
            refs={"signal_ref": signal_id},
        )
    host.runtime_gateway.publish(
        "taskrun:published-source",
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=scope,
        source_authority="test",
        payload={"signal_kind": "stop", "origin": "published"},
    )

    signal = host.runtime_gateway.signal_by_id("taskrun:published-source", signal_id=signal_id)
    drained = host.runtime_gateway.drain(
        "taskrun:published-source",
        scope=scope,
        signal_types={"control.signal.requested"},
    )
    assert host.runtime_gateway.can_consume_by_id("taskrun:published-source", signal_id=signal_id) is True
    consumed = host.runtime_gateway.mark_consumed_by_id(
        "taskrun:published-source",
        signal_id=signal_id,
        consumed_by="test.closeout",
        payload={"terminal_reason": "done"},
    )

    assert signal is not None
    assert signal.payload["origin"] == "published"
    assert [item.signal_id for item in drained.pending_signals] == [signal_id]
    assert drained.pending_signals[0].payload["origin"] == "published"
    assert consumed is not None
    consumed_payload = dict(dict(dict(consumed.payload or {}).get("signal") or {}).get("payload") or {})
    assert consumed_payload["origin"] == "published"
    assert consumed_payload["terminal_reason"] == "done"


def test_runtime_gateway_direct_mark_requires_published_source(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:direct-missing", agent_run_id="agent:direct-missing", run_cell_id="cell:direct-missing")
    signal = build_runtime_signal_envelope(
        signal_type="control.signal.requested",
        signal_id="rtsig:test:direct-missing",
        scope=scope,
        source_authority="test",
        payload={"origin": "unpublished"},
    )

    try:
        host.runtime_gateway.mark_observed("taskrun:direct-missing", signal=signal, observed_by="test.observer")
    except ValueError as error:
        assert "canonical published source" in str(error)
    else:
        raise AssertionError("RuntimeGateway observed an unpublished signal")

    try:
        host.runtime_gateway.mark_consumed("taskrun:direct-missing", signal=signal, consumed_by="test.consumer")
    except ValueError as error:
        assert "canonical published source" in str(error)
    else:
        raise AssertionError("RuntimeGateway consumed an unpublished signal")

    assert host.event_log.list_events("taskrun:direct-missing") == []


def test_runtime_gateway_direct_mark_uses_published_source_payload(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:direct-source", agent_run_id="agent:direct-source", run_cell_id="cell:direct-source")
    signal_id = "rtsig:test:direct-source"
    host.runtime_gateway.publish(
        "taskrun:direct-source",
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=scope,
        source_authority="test.published",
        payload={"origin": "published"},
    )
    forged = build_runtime_signal_envelope(
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=scope,
        source_authority="test.forged",
        payload={"origin": "forged"},
    )

    observed = host.runtime_gateway.mark_observed(
        "taskrun:direct-source",
        signal=forged,
        observed_by="test.observer",
        payload={"observation_ref": "rtobs:direct-source"},
    )
    consumed = host.runtime_gateway.mark_consumed(
        "taskrun:direct-source",
        signal=forged,
        consumed_by="test.consumer",
        payload={"terminal_reason": "done"},
    )
    duplicate = host.runtime_gateway.mark_consumed(
        "taskrun:direct-source",
        signal=forged,
        consumed_by="test.consumer",
        payload={"terminal_reason": "duplicate"},
    )

    observed_signal = dict(dict(observed.payload or {}).get("signal") or {})
    consumed_signal = dict(dict(consumed.payload or {}).get("signal") or {})
    consumed_payload = dict(consumed_signal.get("payload") or {})
    consumed_events = [
        event
        for event in host.event_log.list_events("taskrun:direct-source")
        if event.event_type == "runtime_control_signal_consumed"
    ]

    assert observed_signal["source_authority"] == "test.published"
    assert dict(observed_signal["payload"])["origin"] == "published"
    assert dict(observed_signal["payload"])["observation_ref"] == "rtobs:direct-source"
    assert consumed_signal["source_authority"] == "test.published"
    assert consumed_payload["origin"] == "published"
    assert consumed_payload["terminal_reason"] == "done"
    assert duplicate.event_id == consumed.event_id
    assert len(consumed_events) == 1


def test_runtime_gateway_observed_signal_is_not_drained_again(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:observed", agent_run_id="agent:observed", run_cell_id="cell:observed")
    event = host.runtime_gateway.publish(
        "taskrun:observed",
        signal_type="control.signal.requested",
        scope=scope,
        source_authority="test",
        payload={"signal_kind": "stop"},
    )
    signal_id = str(dict(dict(event.payload or {}).get("signal") or {}).get("signal_id") or "")

    observed = host.runtime_gateway.mark_observed_by_id(
        "taskrun:observed",
        signal_id=signal_id,
        observed_by="test.safe_boundary",
        payload={"observation_ref": "rtobs:observed"},
    )
    drained = host.runtime_gateway.drain("taskrun:observed", scope=scope, signal_types={"control.signal.requested"})

    assert observed is not None
    assert dict(dict(observed.payload or {}).get("signal") or {})["consumption_state"] == "observed"
    assert drained.pending_signals == ()


def test_runtime_gateway_marks_observed_signal_consumed_once(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    scope = RuntimeSignalScope(session_id="session:gateway", task_run_id="taskrun:consumed", agent_run_id="agent:consumed", run_cell_id="cell:consumed")
    event = host.runtime_gateway.publish(
        "taskrun:consumed",
        signal_type="control.signal.requested",
        scope=scope,
        source_authority="test",
        payload={"signal_kind": "stop"},
    )
    signal_id = str(dict(dict(event.payload or {}).get("signal") or {}).get("signal_id") or "")

    observed = host.runtime_gateway.mark_observed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        observed_by="test.safe_boundary",
        payload={"observation_ref": "rtobs:consumed"},
    )
    assert host.runtime_gateway.can_consume_by_id("taskrun:consumed", signal_id=signal_id) is True
    consumed = host.runtime_gateway.mark_consumed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        consumed_by="test.closeout",
        payload={"terminal_reason": "user_aborted"},
    )
    duplicate = host.runtime_gateway.mark_consumed_by_id(
        "taskrun:consumed",
        signal_id=signal_id,
        consumed_by="test.closeout",
        payload={"terminal_reason": "duplicate"},
    )

    assert observed is not None
    assert consumed is not None
    assert duplicate is None
    assert host.runtime_gateway.can_consume_by_id("taskrun:consumed", signal_id=signal_id) is False
    latest_requested = _latest_requested_control_signal(
        host,
        task_run_id="taskrun:consumed",
        kind="stop",
    )
    assert latest_requested is not None
    assert latest_requested["control_event_ref"] == event.event_id
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
    try:
        registry_a.start(
            tool_invocation_id="toolinv:foreign",
            caller_kind="task_run",
            caller_ref="taskrun:a",
            agent_run_id="agent:b",
            run_cell_id="cell:b",
            task_run_id="taskrun:a",
            tool_name="read_file",
        )
    except ValueError as exc:
        assert str(exc) == "tool_invocation_agent_run_scope_mismatch"
    else:
        raise AssertionError("cell-local tool registry must reject foreign agent/cell scope")
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
    assert registry_a.record("toolinv:foreign") is None
    assert registry_b.record("toolinv:b").status == "running"


def test_completed_tool_invocation_record_is_terminal_for_late_cancel() -> None:
    registry = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    registry.start(
        tool_invocation_id="toolinv:completed",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    completed = registry.complete("toolinv:completed", result_ref="result:done")

    cancelled = registry.request_cancel(tool_invocation_id="toolinv:completed", reason="late_stop")
    record = registry.record("toolinv:completed")

    assert completed.status == "completed"
    assert cancelled is False
    assert record.status == "completed"
    assert record.result_ref == "result:done"
    assert record.error == ""


def test_completed_tool_invocation_record_is_terminal_for_late_failure() -> None:
    registry = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    registry.start(
        tool_invocation_id="toolinv:completed-fail",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    completed = registry.complete("toolinv:completed-fail", result_ref="result:done")

    failed = registry.fail("toolinv:completed-fail", error="late-error")
    record = registry.record("toolinv:completed-fail")

    assert completed.status == "completed"
    assert failed.status == "completed"
    assert record.status == "completed"
    assert record.result_ref == "result:done"
    assert record.error == ""


def test_failed_tool_invocation_record_is_terminal_for_late_completion() -> None:
    registry = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    registry.start(
        tool_invocation_id="toolinv:failed-complete",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="read_file",
    )
    failed = registry.fail("toolinv:failed-complete", error="first-error")

    completed = registry.complete("toolinv:failed-complete", result_ref="late-result")
    record = registry.record("toolinv:failed-complete")

    assert failed.status == "failed"
    assert completed.status == "failed"
    assert record.status == "failed"
    assert record.error == "first-error"
    assert record.result_ref == ""


def test_tool_invocation_registry_rejects_duplicate_start_without_rewriting_record() -> None:
    registry = ToolInvocationControlRegistry(agent_run_id="agent:a", run_cell_id="cell:a")
    first = registry.start(
        tool_invocation_id="toolinv:duplicate",
        caller_kind="task_run",
        caller_ref="taskrun:a",
        task_run_id="taskrun:a",
        tool_name="write_file",
        tool_args={"path": "a.txt"},
        idempotency_key="idem:first",
    )

    try:
        registry.start(
            tool_invocation_id="toolinv:duplicate",
            caller_kind="task_run",
            caller_ref="taskrun:a",
            task_run_id="taskrun:a",
            tool_name="write_file",
            tool_args={"path": "b.txt"},
            idempotency_key="idem:second",
        )
    except ToolInvocationAlreadyStartedError as exc:
        assert exc.tool_invocation_id == "toolinv:duplicate"
        assert exc.status == "running"
    else:
        raise AssertionError("duplicate tool invocation start must fail closed")

    current = registry.record("toolinv:duplicate")
    assert current.status == "running"
    assert current.started_at == first.started_at
    assert current.tool_args == {"path": "a.txt"}
    assert current.idempotency_key == "idem:first"


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


def test_active_cell_control_signal_uses_gateway_not_mailbox_shadow_route(tmp_path) -> None:
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
        assert _wait_until(
            lambda: host.agent_run_supervisor.active_cell_for_task_run(
                task_run_id,
                session_id="session:cell-isolation",
            )
            is not None
        )
        cell = host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:cell-isolation")
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
        drained = host.runtime_gateway.drain(
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


def test_single_turn_chat_run_enters_primary_runtime_cell_and_blocks_same_session_primary_work(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    run = host.run_registry.create_run(session_id="session:cell-isolation")
    second_run = host.run_registry.create_run(session_id="session:cell-isolation")
    _insert_task_run(host, "taskrun:blocked-by-chat")
    started = threading.Event()
    release = threading.Event()
    task_executed = threading.Event()

    async def chat_work() -> dict[str, str]:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    async def execute_task(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        del task_run_id, max_steps
        task_executed.set()
        return {"status": "completed"}

    scheduled = host.agent_run_supervisor.schedule_single_turn(
        session_id="session:cell-isolation",
        stream_run_id=run.stream_run_id,
        work_factory=chat_work,
        scheduler="test-chat-run",
    )
    cell = host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation")
    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute_task)
    try:
        assert scheduled["scheduled"] is True
        assert scheduled["stream_run_id"] == run.stream_run_id
        assert cell is not None
        assert cell.scope.invocation_kind == "single_turn"
        assert cell.scope.turn_run_id == f"turnrun:{run.stream_run_id}"
        assert started.wait(timeout=3)

        blocked_turn = host.agent_run_supervisor.schedule_single_turn(
            session_id="session:cell-isolation",
            stream_run_id=second_run.stream_run_id,
            work_factory=chat_work,
            scheduler="test-chat-run",
        )
        blocked_task = controller.schedule("taskrun:blocked-by-chat", scheduler="test", max_steps=1)

        assert blocked_turn["scheduled"] is False
        assert blocked_turn["reason"] == "session_primary_task_active"
        assert blocked_turn["run_cell_id"]
        assert host.agent_run_supervisor.active_cell_for_stream_run(second_run.stream_run_id, session_id="session:cell-isolation") is None
        assert blocked_task["scheduled"] is False
        assert blocked_task["reason"] == "session_primary_task_active"
        assert task_executed.is_set() is False

        backpressure_events = [
            event
            for event in host.event_log.list_events(f"turnrun:{second_run.stream_run_id}")
            if event.event_type == "agent_runtime_cell_backpressure"
        ]
        assert len(backpressure_events) == 1
        assert dict(backpressure_events[0].payload)["active_turn_run_id"] == f"turnrun:{run.stream_run_id}"
    finally:
        release.set()
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=3)


def test_runtime_run_cell_cancel_requires_session_scope(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    run = host.run_registry.create_run(session_id="session:cell-isolation")
    started = threading.Event()

    async def chat_work() -> dict[str, str]:
        started.set()
        while True:
            await asyncio.sleep(0.01)

    scheduled = host.agent_run_supervisor.schedule_single_turn(
        session_id="session:cell-isolation",
        stream_run_id=run.stream_run_id,
        work_factory=chat_work,
        scheduler="test-chat-run",
    )
    cell = host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation")
    try:
        assert scheduled["scheduled"] is True
        assert cell is not None
        assert started.wait(timeout=3)

        wrong_session = host.cancel_runtime_run_cells(
            runtime_run_sessions={run.stream_run_id: "session:other"},
            reason="test_wrong_session",
        )
        assert wrong_session["cancelled_count"] == 0
        assert wrong_session["rejected"][0]["reason"] == "active_cell_missing_or_session_mismatch"
        assert cell.is_running()

        correct_session = host.cancel_runtime_run_cells(
            runtime_run_sessions={run.stream_run_id: "session:cell-isolation"},
            reason="test_cancel",
        )
        assert correct_session["cancelled_count"] == 1
        assert correct_session["cancelled_stream_run_ids"] == [run.stream_run_id]
        assert _wait_until(lambda: cell.status in {"cancel_requested", "cancelled"})
    finally:
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.request_cancel("test_cleanup")
            cell.worker_handle.join(timeout=3)


def test_single_turn_start_binds_turn_run_to_active_runtime_cell_scope(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    run = host.run_registry.create_run(session_id="session:cell-isolation")
    release = threading.Event()

    async def chat_work() -> dict[str, str]:
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    scheduled = host.agent_run_supervisor.schedule_single_turn(
        session_id="session:cell-isolation",
        stream_run_id=run.stream_run_id,
        work_factory=chat_work,
        scheduler="test-chat-run",
    )
    cell = host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation")
    try:
        assert scheduled["scheduled"] is True
        assert cell is not None

        turn_run, start_event = _start_turn_runtime(
            host,
            session_id="session:cell-isolation",
            turn_id="turn:cell-bound",
            agent_profile_ref="main_interactive_agent",
            stream_run_id=run.stream_run_id,
        )
        refreshed_run = host.run_registry.get_run(run.stream_run_id)
        diagnostics = dict(turn_run.diagnostics or {})
        agent_scope = dict(diagnostics.get("agent_run_scope") or {})
        refs = dict(start_event.get("refs") or {})

        assert agent_scope["agent_run_id"] == scheduled["agent_run_id"]
        assert agent_scope["run_cell_id"] == scheduled["run_cell_id"]
        assert agent_scope["turn_id"] == "turn:cell-bound"
        assert agent_scope["turn_run_id"] == f"turnrun:{run.stream_run_id}"
        assert refs["agent_run_ref"] == scheduled["agent_run_id"]
        assert refs["run_cell_ref"] == scheduled["run_cell_id"]
        assert dict(refreshed_run.diagnostics or {})["runtime_turn_run_id"] == turn_run.turn_run_id
        assert dict(refreshed_run.diagnostics or {})["run_cell_id"] == scheduled["run_cell_id"]
    finally:
        release.set()
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=3)


def test_single_turn_old_cell_final_commit_is_rejected_before_session_write(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    run = host.run_registry.create_run(session_id="session:cell-isolation")
    old_release = threading.Event()
    new_release = threading.Event()
    old_started = threading.Event()
    new_started = threading.Event()
    committed_payloads: list[dict[str, object]] = []

    async def old_chat_work() -> dict[str, str]:
        old_started.set()
        while not old_release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    async def new_chat_work() -> dict[str, str]:
        new_started.set()
        while not new_release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    async def commit_assistant_message(session_id: str, payload: dict[str, object]) -> dict[str, object]:
        committed_payloads.append({"session_id": session_id, **payload})
        return {"appended_messages": [{"id": "assistant:late-final"}]}

    old_scheduled = host.agent_run_supervisor.schedule_single_turn(
        session_id="session:cell-isolation",
        stream_run_id=run.stream_run_id,
        work_factory=old_chat_work,
        scheduler="test-chat-run",
    )
    old_cell = host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation")
    new_cell = None
    try:
        assert old_scheduled["scheduled"] is True
        assert old_cell is not None
        assert old_started.wait(timeout=3)
        old_turn_run, _ = _start_turn_runtime(
            host,
            session_id="session:cell-isolation",
            turn_id="turn:old-cell-final",
            agent_profile_ref="main_interactive_agent",
            stream_run_id=run.stream_run_id,
        )
        old_scope = dict(dict(old_turn_run.diagnostics or {}).get("agent_run_scope") or {})

        old_release.set()
        assert old_cell.worker_handle is not None
        assert old_cell.worker_handle.join(timeout=3)
        assert _wait_until(lambda: host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation") is None)

        new_scheduled = host.agent_run_supervisor.schedule_single_turn(
            session_id="session:cell-isolation",
            stream_run_id=run.stream_run_id,
            work_factory=new_chat_work,
            scheduler="test-chat-run",
        )
        new_cell = host.agent_run_supervisor.active_cell_for_stream_run(run.stream_run_id, session_id="session:cell-isolation")
        assert new_scheduled["scheduled"] is True
        assert new_cell is not None
        assert new_started.wait(timeout=3)
        assert new_scheduled["run_cell_id"] != old_scheduled["run_cell_id"]

        result = asyncio.run(
            OutputCommitAuthority(host).commit_async(
                OutputCommitRequest(
                    run_id=old_turn_run.turn_run_id,
                    session_id="session:cell-isolation",
                    stream_run_id=run.stream_run_id,
                    turn_id="turn:old-cell-final",
                    turn_run_id=old_turn_run.turn_run_id,
                    agent_run_id=str(old_scope.get("agent_run_id") or ""),
                    run_cell_id=str(old_scope.get("run_cell_id") or ""),
                    content="late final from old cell",
                    execution_posture="single_agent_turn",
                    refs={
                        "turn_ref": "turn:old-cell-final",
                        "turn_run_ref": old_turn_run.turn_run_id,
                        "agent_run_ref": str(old_scope.get("agent_run_id") or ""),
                        "run_cell_ref": str(old_scope.get("run_cell_id") or ""),
                    },
                ),
                committer=commit_assistant_message,
            )
        )

        assert committed_payloads == []
        assert result.receipt["event_type"] == "session_output_commit_skipped"
        assert result.receipt["reason"] == "agent_cell_stale_run_cell"
        assert dict(result.receipt["commit_gate"])["scope_status"]["reason"] == "stale_run_cell"
        events = host.event_log.list_events(old_turn_run.turn_run_id)
        assert not any(event.event_type == "session_output_commit_checked" for event in events)
        late_event = next(event for event in events if event.event_type == "agent_runtime_cell_late_event_rejected")
        assert dict(late_event.payload)["stream_run_id"] == run.stream_run_id
        assert dict(late_event.payload)["event_kind"] == "output_commit"
    finally:
        old_release.set()
        new_release.set()
        if old_cell is not None and old_cell.worker_handle is not None:
            old_cell.worker_handle.join(timeout=3)
        if new_cell is not None and new_cell.worker_handle is not None:
            new_cell.worker_handle.join(timeout=3)


def test_task_executor_controller_schedules_task_runs_in_isolated_cells(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:a")
    _insert_task_run(host, "taskrun:b", session_id="session:cell-isolation-b")
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

    cell_a = host.agent_run_supervisor.active_cell_for_task_run("taskrun:a", session_id="session:cell-isolation")
    cell_b = host.agent_run_supervisor.active_cell_for_task_run("taskrun:b", session_id="session:cell-isolation-b")
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
    assert host.agent_run_supervisor.cancel_task_run(
        "taskrun:a",
        session_id="session:cell-isolation",
        reason="test_cancel_a",
    ) is True
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


def test_task_executor_controller_commits_schedule_with_claimed_cell_identity(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:claimed-schedule"
    _insert_task_run(host, task_run_id)
    started = threading.Event()
    release = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result = controller.schedule(task_run_id, scheduler="test", turn_id="turn:claimed-schedule", max_steps=3)
    cell = host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:cell-isolation")
    try:
        assert result["scheduled"] is True
        assert result["agent_run_id"]
        assert result["run_cell_id"]
        assert cell is not None
        assert cell.scope.agent_run_id == result["agent_run_id"]
        assert cell.scope.run_cell_id == result["run_cell_id"]
        assert cell.scope.turn_id == "turn:claimed-schedule"
        assert started.wait(timeout=3)

        task_run = host.state_index.get_task_run(task_run_id)
        diagnostics = dict(task_run.diagnostics or {})
        scheduled_events = [
            event for event in host.event_log.list_events(task_run_id)
            if event.event_type == "task_run_executor_scheduled"
        ]

        assert len(scheduled_events) == 1
        scheduled_payload = dict(scheduled_events[0].payload or {})
        scheduled_scope = dict(scheduled_payload.get("agent_scope") or {})
        assert scheduled_payload["agent_run_id"] == result["agent_run_id"]
        assert scheduled_payload["run_cell_id"] == result["run_cell_id"]
        assert scheduled_scope["turn_id"] == "turn:claimed-schedule"
        assert scheduled_events[0].refs["agent_run_ref"] == result["agent_run_id"]
        assert scheduled_events[0].refs["run_cell_ref"] == result["run_cell_id"]
        assert diagnostics["executor_status"] == "scheduled"
        assert diagnostics["executor_lease_state"] == "scheduled"
        assert diagnostics["latest_interaction_turn_id"] == "turn:claimed-schedule"
        assert diagnostics["agent_run_id"] == result["agent_run_id"]
        assert diagnostics["run_cell_id"] == result["run_cell_id"]
        assert dict(diagnostics["agent_run_scope"])["run_cell_id"] == result["run_cell_id"]
    finally:
        release.set()
        if cell is not None and cell.worker_handle is not None:
            cell.worker_handle.join(timeout=3)


def test_task_executor_controller_does_not_mark_backpressured_task_scheduled(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    host.agent_run_supervisor.max_active_cells = 1
    _insert_task_run(host, "taskrun:active")
    _insert_task_run(host, "taskrun:backpressured")
    started = threading.Event()
    release = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result_active = controller.schedule("taskrun:active", scheduler="test", max_steps=1)
    cell_active = host.agent_run_supervisor.active_cell_for_task_run("taskrun:active", session_id="session:cell-isolation")
    try:
        assert result_active["scheduled"] is True
        assert cell_active is not None
        assert started.wait(timeout=3)

        result_blocked = controller.schedule("taskrun:backpressured", scheduler="test", max_steps=1)
        blocked_task_run = host.state_index.get_task_run("taskrun:backpressured")
        blocked_diagnostics = dict(blocked_task_run.diagnostics or {})
        scheduled_events = [
            event for event in host.event_log.list_events("taskrun:backpressured")
            if event.event_type == "task_run_executor_scheduled"
        ]
        backpressure_events = [
            event for event in host.event_log.list_events("taskrun:backpressured")
            if event.event_type == "agent_runtime_cell_backpressure"
        ]
        drained = host.runtime_gateway.drain(
            "taskrun:backpressured",
            scope=RuntimeSignalScope(
                session_id="session:cell-isolation",
                task_run_id="taskrun:backpressured",
                agent_run_id=result_blocked["agent_run_id"],
                run_cell_id=result_blocked["run_cell_id"],
            ),
            signal_types={"agent_runtime_cell_backpressure"},
        )

        assert result_blocked["scheduled"] is False
        assert result_blocked["ok"] is False
        assert result_blocked["reason"] == "session_primary_task_active"
        assert result_blocked["agent_run_id"]
        assert result_blocked["run_cell_id"]
        assert host.agent_run_supervisor.active_cell_for_task_run(
            "taskrun:backpressured",
            session_id="session:cell-isolation",
        ) is None
        assert scheduled_events == []
        assert blocked_diagnostics.get("executor_status") in {None, ""}
        assert blocked_diagnostics.get("executor_lease_state") in {None, ""}
        assert "agent_run_scope" not in blocked_diagnostics
        assert len(backpressure_events) == 1
        assert dict(backpressure_events[0].payload)["reason"] == "session_primary_task_active"
        assert dict(backpressure_events[0].payload)["active_task_run_id"] == "taskrun:active"
        assert dict(dict(backpressure_events[0].payload)["agent_scope"])["run_cell_id"] == result_blocked["run_cell_id"]
        assert len(drained.pending_signals) == 1
        assert drained.pending_signals[0].scope.run_cell_id == result_blocked["run_cell_id"]
        assert drained.pending_signals[0].payload["reason"] == "session_primary_task_active"
    finally:
        release.set()
        if cell_active is not None and cell_active.worker_handle is not None:
            cell_active.worker_handle.join(timeout=3)


def test_same_session_can_hold_multiple_tasks_but_only_one_active_primary_cell(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:first")
    _insert_task_run(host, "taskrun:second")
    started: set[str] = set()
    release_first = threading.Event()
    release_second = threading.Event()

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        del max_steps
        started.add(task_run_id)
        release = release_first if task_run_id == "taskrun:first" else release_second
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    first = controller.schedule("taskrun:first", scheduler="test", max_steps=1)
    cell_first = host.agent_run_supervisor.active_cell_for_task_run("taskrun:first", session_id="session:cell-isolation")
    try:
        assert first["scheduled"] is True
        assert cell_first is not None
        assert _wait_until(lambda: started == {"taskrun:first"})

        blocked = controller.schedule("taskrun:second", scheduler="test", max_steps=1)
        second_before_release = host.state_index.get_task_run("taskrun:second")
        second_diagnostics = dict(second_before_release.diagnostics or {})

        assert blocked["scheduled"] is False
        assert blocked["reason"] == "session_primary_task_active"
        assert host.agent_run_supervisor.active_cell_for_task_run("taskrun:second", session_id="session:cell-isolation") is None
        assert second_before_release is not None
        assert second_before_release.status == "created"
        assert second_diagnostics.get("executor_status") in {None, ""}
        assert second_diagnostics.get("executor_lease_state") in {None, ""}

        release_first.set()
        assert cell_first.worker_handle is not None
        assert cell_first.worker_handle.join(timeout=3)
        assert _wait_until(
            lambda: host.agent_run_supervisor.active_cell_for_task_run("taskrun:first", session_id="session:cell-isolation") is None
        )

        second = controller.schedule("taskrun:second", scheduler="test", max_steps=1)
        cell_second = host.agent_run_supervisor.active_cell_for_task_run("taskrun:second", session_id="session:cell-isolation")

        assert second["scheduled"] is True
        assert cell_second is not None
        assert second["run_cell_id"] != first["run_cell_id"]
        assert _wait_until(lambda: started == {"taskrun:first", "taskrun:second"})
    finally:
        release_first.set()
        release_second.set()
        cell_first = host.agent_run_supervisor.cell_by_id(str(first.get("run_cell_id") or ""))
        if cell_first is not None and cell_first.worker_handle is not None:
            cell_first.worker_handle.join(timeout=3)
        second_cell = host.agent_run_supervisor.active_cell_for_task_run("taskrun:second", session_id="session:cell-isolation")
        if second_cell is not None and second_cell.worker_handle is not None:
            second_cell.worker_handle.join(timeout=3)


def test_task_executor_controller_cleans_cell_claim_when_worker_start_fails(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:worker-start-fails"
    _insert_task_run(host, task_run_id)
    executed = threading.Event()

    class FailingWorkerBackend:
        backend_name = "failing-worker"

        def start(self, *, run_cell_id: str, work_factory, on_done=None):
            raise RuntimeError("worker backend offline")

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        executed.set()
        return {"status": "completed"}

    host.agent_run_supervisor.worker_backend = FailingWorkerBackend()
    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result = controller.schedule(task_run_id, scheduler="test", max_steps=1)
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(task_run.diagnostics or {})
    events = host.event_log.list_events(task_run_id)
    event_types = [event.event_type for event in events]
    schedule_failed = [
        event for event in events
        if event.event_type == "task_run_executor_schedule_failed"
    ]
    start_failed = [
        event for event in events
        if event.event_type == "agent_runtime_cell_start_failed"
    ]

    assert result["ok"] is False
    assert result["scheduled"] is False
    assert result["reason"] == "worker_start_failed"
    assert result["error"] == "worker backend offline"
    assert result["run_cell_id"]
    assert executed.is_set() is False
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:cell-isolation") is None
    assert host.agent_run_supervisor.cell_by_id(result["run_cell_id"]) is None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "task_executor_schedule_failed"
    assert diagnostics["executor_status"] == "blocked"
    assert diagnostics["executor_lease_state"] == "blocked"
    assert "agent_run_scope" not in diagnostics
    assert "agent_run_id" not in diagnostics
    assert "run_cell_id" not in diagnostics
    assert "agent_runtime_cell_created" in event_types
    assert "task_run_executor_scheduled" in event_types
    assert "agent_runtime_cell_started" not in event_types
    assert len(start_failed) == 1
    assert dict(start_failed[0].payload)["error"] == "worker backend offline"
    assert len(schedule_failed) == 1
    assert schedule_failed[0].refs["run_cell_ref"] == result["run_cell_id"]


def test_task_executor_controller_recover_scheduled_closes_worker_start_failure(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:recover-worker-start-fails"
    _insert_task_run(host, task_run_id)
    task_run = host.state_index.get_task_run(task_run_id)
    host.state_index.upsert_task_run(
        replace(
            task_run,
            diagnostics={
                "executor_status": "scheduled",
                "executor_lease_state": "scheduled",
                "agent_run_scope": {
                    "session_id": "session:cell-isolation",
                    "task_run_id": task_run_id,
                    "agent_run_id": "agentrun:old",
                    "run_cell_id": "runcell:old",
                },
                "agent_run_id": "agentrun:old",
                "run_cell_id": "runcell:old",
                "agent_cell_status": "scheduled",
                "agent_cell_worker_backend": "old-worker",
            },
        )
    )
    executed = threading.Event()

    class FailingWorkerBackend:
        backend_name = "recover-failing-worker"

        def start(self, *, run_cell_id: str, work_factory, on_done=None):
            raise RuntimeError("recovered worker backend offline")

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        executed.set()
        return {"status": "completed"}

    host.agent_run_supervisor.worker_backend = FailingWorkerBackend()
    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result = controller.recover_scheduled(task_run_id, scheduler="test-recovery", max_steps=1)
    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(task_run.diagnostics or {})
    events = host.event_log.list_events(task_run_id)
    event_types = [event.event_type for event in events]
    schedule_failed = [
        event for event in events
        if event.event_type == "task_run_executor_schedule_failed"
    ]
    start_failed = [
        event for event in events
        if event.event_type == "agent_runtime_cell_start_failed"
    ]

    assert result["ok"] is False
    assert result["scheduled"] is False
    assert result["reason"] == "worker_start_failed"
    assert result["error"] == "recovered worker backend offline"
    assert result["run_cell_id"]
    assert result["run_cell_id"] != "runcell:old"
    assert executed.is_set() is False
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:cell-isolation") is None
    assert host.agent_run_supervisor.cell_by_id(result["run_cell_id"]) is None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "task_executor_schedule_failed"
    assert diagnostics["executor_status"] == "blocked"
    assert diagnostics["executor_lease_state"] == "blocked"
    assert "agent_run_scope" not in diagnostics
    assert "agent_run_id" not in diagnostics
    assert "run_cell_id" not in diagnostics
    assert "agent_cell_status" not in diagnostics
    assert "agent_cell_worker_backend" not in diagnostics
    assert "agent_runtime_cell_created" in event_types
    assert "agent_runtime_cell_started" not in event_types
    assert "task_run_executor_scheduled" not in event_types
    assert len(start_failed) == 1
    assert dict(start_failed[0].payload)["error"] == "recovered worker backend offline"
    assert len(schedule_failed) == 1
    assert schedule_failed[0].refs["run_cell_ref"] == result["run_cell_id"]
    assert dict(schedule_failed[0].payload)["run_cell_id"] == result["run_cell_id"]


def test_task_executor_controller_marks_cell_failed_when_execute_callback_raises(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    task_run_id = "taskrun:execute-raises"
    _insert_task_run(host, task_run_id)

    async def execute(task_run_id: str, *, max_steps: int) -> dict[str, str]:
        raise RuntimeError("executor exploded")

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result = controller.schedule(task_run_id, scheduler="test", max_steps=1)
    cell = host.agent_run_supervisor.cell_by_id(result["run_cell_id"])

    assert result["ok"] is True
    assert result["scheduled"] is True
    assert cell is not None
    assert cell.worker_handle is not None
    assert cell.worker_handle.join(timeout=3)

    task_run = host.state_index.get_task_run(task_run_id)
    diagnostics = dict(task_run.diagnostics or {})
    events = host.event_log.list_events(task_run_id)
    event_types = [event.event_type for event in events]
    executor_failed = [
        event for event in events
        if event.event_type == "task_run_executor_failed"
    ]
    cell_failed = [
        event for event in events
        if event.event_type == "agent_runtime_cell_failed"
    ]

    assert cell.status == "failed"
    assert cell.worker_handle.error is not None
    assert "executor exploded" in str(cell.worker_handle.error)
    assert host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:cell-isolation") is None
    assert task_run.status == "blocked"
    assert task_run.terminal_reason == "executor_failed"
    assert diagnostics["executor_status"] == "blocked"
    assert diagnostics["executor_lease_state"] == "blocked"
    assert diagnostics["latest_step"] == "task_run_executor_failed"
    assert diagnostics["recoverable_error"]["error_code"] == "executor_failed"
    assert "agent_run_scope" not in diagnostics
    assert "agent_run_id" not in diagnostics
    assert "run_cell_id" not in diagnostics
    assert "task_run_executor_scheduled" in event_types
    assert "agent_runtime_cell_started" in event_types
    assert "task_run_executor_schedule_failed" not in event_types
    assert "agent_runtime_cell_completed" not in event_types
    assert len(executor_failed) == 1
    assert executor_failed[0].refs["run_cell_ref"] == result["run_cell_id"]
    assert dict(executor_failed[0].payload)["run_cell_id"] == result["run_cell_id"]
    assert dict(executor_failed[0].payload)["error"] == "executor exploded"
    assert len(cell_failed) == 1
    assert cell_failed[0].refs["run_cell_ref"] == result["run_cell_id"]
    assert dict(cell_failed[0].payload)["error"] == "executor exploded"


def test_cell_mailbox_overflow_publishes_scoped_backpressure_event(tmp_path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=tmp_path / "backend")
    _insert_task_run(host, "taskrun:mailbox-a")
    _insert_task_run(host, "taskrun:mailbox-b", session_id="session:cell-isolation-b")
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
        gateway_overload_a = [
            signal
            for signal in host.runtime_gateway.drain(
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
        gateway_overload_b = [
            signal
            for signal in host.runtime_gateway.drain(
                "taskrun:mailbox-b",
                scope=RuntimeSignalScope(
                    session_id="session:cell-isolation-b",
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
        assert len(gateway_overload_a) == 1
        assert gateway_overload_a[0].scope.run_cell_id == scheduled_a["run_cell_id"]
        assert gateway_overload_a[0].payload["reason"] == "mailbox_full"
        assert gateway_overload_b == []
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
    _insert_task_run(host, "taskrun:b", session_id="session:cell-isolation-b")
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

    cell_a = host.agent_run_supervisor.active_cell_for_task_run("taskrun:a", session_id="session:cell-isolation")
    assert cell_a is not None
    assert host.agent_run_supervisor.cancel_task_run(
        "taskrun:a",
        session_id="session:cell-isolation",
        reason="cancel_a",
    ) is True
    assert _wait_until(lambda: cell_a.status == "cancel_requested")
    assert cell_a.is_running()

    result_b = controller.schedule("taskrun:b", scheduler="test", max_steps=1)
    cell_b = host.agent_run_supervisor.active_cell_for_task_run("taskrun:b", session_id="session:cell-isolation-b")

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
    assert _wait_until(
        lambda: host.agent_run_supervisor.active_cell_for_task_run(
            "taskrun:terminal-cell",
            session_id="session:cell-isolation",
        )
        is not None
    )
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


def _insert_task_run(
    host: SingleAgentRuntimeHost,
    task_run_id: str,
    *,
    session_id: str = "session:cell-isolation",
    execution_runtime_kind: str = "single_agent_task",
    status: str = "created",
    diagnostics: dict | None = None,
) -> None:
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:{task_run_id}",
            execution_runtime_kind=execution_runtime_kind,
            status=status,
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics=dict(diagnostics or {}),
        )
    )


def _wait_until(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _runtime_event_fact(facts, event_type: str):
    return next(
        fact
        for fact in facts
        if str(dict(fact.attributes or {}).get("event_type") or "") == event_type
    )


def _control_signal_payloads(host: SingleAgentRuntimeHost, run_id: str, signal_type: str) -> list[dict]:
    payloads: list[dict] = []
    for event in host.event_log.list_events(run_id):
        signal = dict(dict(event.payload or {}).get("signal") or {})
        if str(signal.get("signal_type") or "") != signal_type:
            continue
        payloads.append(dict(signal.get("payload") or {}))
    return payloads
