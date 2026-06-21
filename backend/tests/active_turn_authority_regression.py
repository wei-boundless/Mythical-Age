from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

import api.orchestration_harness as orchestration_harness
from api.orchestration_harness import _assert_expected_active_turn, _schedule_result_allows_progress
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime import SingleAgentRuntimeHost
from harness.runtime.control_events import runtime_signal_from_event_payload
from harness.loop.task_executor import append_user_work_instruction, is_task_run_executable, request_task_run_pause, resume_paused_task_run
from harness.loop.task_executor_controller import TaskExecutorController
from harness.loop.task_lifecycle import (
    TaskLifecycleRecord,
    TaskRunContract,
    finish_task_lifecycle,
    start_task_lifecycle,
    wait_task_launch_supervision,
)
from harness.loop.model_action_protocol import ModelActionRequest
from runtime.shared.models import TaskRun
from tests.support.runtime_stubs import build_harness_runtime


class LiveExecutorClaim:
    def __init__(self, host: SingleAgentRuntimeHost, task_run_id: str, run_cell_id: str, release: threading.Event) -> None:
        self.host = host
        self.task_run_id = task_run_id
        self.run_cell_id = run_cell_id
        self.release = release

    def close(self) -> None:
        self.release.set()
        cell = self.host.agent_run_supervisor.cell_by_id(self.run_cell_id)
        worker_handle = getattr(cell, "worker_handle", None) if cell is not None else None
        if worker_handle is not None:
            worker_handle.join(timeout=3)


def _start_live_task_run_executor(
    host: SingleAgentRuntimeHost,
    task_run_id: str,
    *,
    turn_id: str = "turn:session:test:old",
) -> LiveExecutorClaim:
    release = threading.Event()
    started = threading.Event()

    async def execute(_task_run_id: str, *, max_steps: int) -> dict[str, str]:
        del max_steps
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return {"status": "completed"}

    controller = TaskExecutorController(runtime_host=host, execute_task_run_callback=execute)
    result = controller.schedule(
        task_run_id,
        scheduler="test-live-executor",
        turn_id=turn_id,
        max_steps=1,
    )
    assert result["ok"] is True
    assert result["scheduled"] is True
    run_cell_id = str(result.get("run_cell_id") or "")
    assert run_cell_id
    assert _wait_until(
        lambda: started.is_set()
        and host.agent_run_supervisor.active_cell_for_task_run(task_run_id, session_id="session:test") is not None
    )
    return LiveExecutorClaim(host, task_run_id, run_cell_id, release)


def _wait_until(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class RuntimeAssemblyStub:
    def to_dict(self) -> dict[str, object]:
        return {
            "permission_mode": "plan",
            "task_environment": {"environment_id": "env.general.workspace"},
        }


def test_active_turn_does_not_derive_from_historical_task_run(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    historical = TaskRun(
        task_run_id="taskrun:historical",
        session_id="session:test",
        task_id="task:historical",
        status="waiting_executor",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(historical)

    assert host.active_turn_registry.snapshot("session:test") is None


def test_active_turn_resolve_clears_stopped_bound_task_run(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    stopped = TaskRun(
        task_run_id="taskrun:stopped",
        session_id="session:test",
        task_id="task:stopped",
        execution_runtime_kind="single_agent_task",
        status="aborted",
        terminal_reason="user_aborted",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(stopped)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id=stopped.task_run_id,
        state="running_task",
    )

    assert host.active_turn_registry.resolve_current("session:test") is None
    assert host.active_turn_registry.snapshot("session:test") is None


def test_schedule_progress_accepts_already_running_executor() -> None:
    assert _schedule_result_allows_progress({"ok": True, "scheduled": True, "reason": "scheduled"}) is True
    assert _schedule_result_allows_progress({"ok": True, "scheduled": False, "reason": "already_running"}) is True
    assert _schedule_result_allows_progress({"ok": False, "scheduled": False, "reason": "not_executable:completed"}) is False


def test_active_turn_binds_task_without_owning_steer_queue(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    action_request = ModelActionRequest(
        request_id="model-action:test",
        turn_id="turn:session:test:1",
        action_type="request_task_run",
        task_contract_seed={},
    )
    contract = TaskRunContract(
        contract_id="contract:test",
        contract_source="test",
        user_visible_goal="做一个测试任务",
        task_run_goal="完成测试任务",
        completion_criteria=("产生结果",),
    )

    task_run, _agent_run, _lifecycle, _events = start_task_lifecycle(
        host,
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_id="task:test",
        action_request=action_request,
        contract=contract,
        agent_profile_ref="main_interactive_agent",
        runtime_assembly=RuntimeAssemblyStub(),
    )

    active = host.active_turn_registry.snapshot("session:test")
    assert active is not None
    assert active.bound_task_run_id == task_run.task_run_id
    assert "pending_input_refs" not in active.to_dict()
    assert task_run.diagnostics["runtime_permission_mode"] == "plan"
    updated = host.state_index.get_task_run(task_run.task_run_id)
    assert updated is not None
    assert int(dict(updated.diagnostics or {}).get("pending_user_steer_count") or 0) == 0


def test_active_turn_pause_request_enters_waiting_safe_boundary(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="created",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    claim = _start_live_task_run_executor(host, task_run.task_run_id)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id=task_run.task_run_id,
        state="running_task",
    )

    try:
        result = request_task_run_pause(host, task_run.task_run_id, reason="test_pause", requested_by="user")

        active = host.active_turn_registry.snapshot("session:test")
        assert result["ok"] is True
        assert active is not None
        assert active.bound_task_run_id == task_run.task_run_id
        assert active.state == "waiting_safe_boundary"
    finally:
        claim.close()


def test_active_turn_launch_supervision_enters_waiting_approval(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:approval",
        session_id="session:test",
        task_id="task:approval",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        created_at=1,
        updated_at=2,
        diagnostics={"turn_id": "turn:session:test:1"},
    )
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run.task_run_id,
        contract_ref="rtobj:task_run_contract:approval",
        status="waiting_executor",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id=task_run.task_run_id,
        state="waiting_executor",
    )

    wait_task_launch_supervision(
        host,
        task_run=task_run,
        lifecycle=lifecycle,
        gate_policy={"enabled": True, "user_prompt": "请确认是否启动。"},
    )

    active = host.active_turn_registry.snapshot("session:test")
    assert active is not None
    assert active.bound_task_run_id == task_run.task_run_id
    assert active.state == "waiting_approval"


def test_active_turn_complete_releases_session(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.complete(
        session_id="session:test",
        expected_turn_id="turn:session:test:1",
        terminal_reason="assistant_message",
    )

    assert host.active_turn_registry.snapshot("session:test") is None


def test_active_turn_from_previous_runtime_instance_does_not_block_new_host(tmp_path: Path) -> None:
    previous_host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    previous_host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:old")

    new_host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())

    assert new_host.active_turn_registry.snapshot("session:test") is None
    current = new_host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:new")
    assert current.turn_id == "turn:session:test:new"


def test_historical_task_finish_does_not_release_current_active_turn(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:current")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:current",
        task_run_id="taskrun:current",
    )
    historical = TaskRun(
        task_run_id="taskrun:historical",
        session_id="session:test",
        task_id="task:historical",
        status="running",
        created_at=1,
        updated_at=2,
        diagnostics={"turn_id": "turn:session:test:old"},
    )
    lifecycle = TaskLifecycleRecord(
        task_run_id=historical.task_run_id,
        contract_ref="rtobj:task_run_contract:historical",
        status="running",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(historical)

    finish_task_lifecycle(
        host,
        task_run=historical,
        lifecycle=lifecycle,
        status="completed",
        terminal_reason="historical_finished",
    )

    active = host.active_turn_registry.snapshot("session:test")
    assert active is not None
    assert active.turn_id == "turn:session:test:current"
    assert active.bound_task_run_id == "taskrun:current"


def test_task_run_control_accepts_matching_active_turn(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        status="running",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id="taskrun:current",
    )

    _assert_expected_active_turn(host, "taskrun:current", "turn:session:test:1")


def test_task_run_control_rejects_mismatched_active_turn(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        status="running",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id="taskrun:current",
    )

    with pytest.raises(HTTPException) as exc:
        _assert_expected_active_turn(host, "taskrun:current", "turn:session:test:old")

    assert exc.value.status_code == 409
    assert exc.value.detail == "active_turn_mismatch"


def test_task_run_control_rejects_missing_active_turn_when_expected_id_present(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        status="running",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)

    with pytest.raises(HTTPException) as exc:
        _assert_expected_active_turn(host, "taskrun:current", "turn:session:test:1")

    assert exc.value.status_code == 409
    assert exc.value.detail == "active_turn_unavailable"


def test_execute_task_run_rejects_mismatched_active_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id="taskrun:current",
    )
    harness_runtime = SimpleNamespace(
        single_agent_runtime_host=host,
        schedule_or_recover_task_run_executor=lambda *_args, **_kwargs: pytest.fail("execute scheduled despite active turn mismatch"),
    )
    monkeypatch.setattr(
        orchestration_harness,
        "require_runtime",
        lambda: SimpleNamespace(harness_runtime=harness_runtime),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            orchestration_harness.execute_harness_task_run(
                "taskrun:current",
                orchestration_harness.TaskRunExecuteRequest(expected_active_turn_id="turn:session:test:old"),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "active_turn_mismatch"


def test_waiting_executor_without_explicit_recovery_boundary_is_not_executable(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:ambiguous-waiting",
        session_id="session:test",
        task_id="task:ambiguous-waiting",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)

    resume = resume_paused_task_run(host, task_run.task_run_id, requested_by="user")

    assert is_task_run_executable(task_run) is False
    assert resume["ok"] is False
    assert resume["error"] == "task_run_not_resumable:waiting_executor"


def test_append_user_work_instruction_rejects_terminal_task_run(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    task_run = TaskRun(
        task_run_id="taskrun:terminal",
        session_id="session:test",
        task_id="task:terminal",
        execution_runtime_kind="single_agent_task",
        status="aborted",
        terminal_reason="user_aborted",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)

    result = append_user_work_instruction(
        host,
        task_run.task_run_id,
        content="继续补充一个已经结束的任务。",
        turn_id="turn:session:test:2",
    )

    assert result["ok"] is False
    assert result["error"] == "task_run_terminal:user_aborted"
    assert "active_task_steer_recorded" not in [event.event_type for event in host.event_log.list_events(task_run.task_run_id)]


def test_active_turn_steer_records_lifecycle_without_model_decision(tmp_path: Path) -> None:
    class ActiveWorkAppendModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("explicit active-turn steer must not be routed through model decision")

    model = ActiveWorkAppendModelRuntime()
    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="created",
        created_at=1,
        updated_at=2,
        diagnostics={"turn_id": "turn:session:test:old"},
    )
    host.state_index.upsert_task_run(task_run)
    claim = _start_live_task_run_executor(host, task_run.task_run_id)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:old")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:old",
        task_run_id="taskrun:current",
        state="running_task",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session:test",
                message="等一下 task runtime 为什么必须有 task_environment？",
                active_turn_input_policy="steer",
                expected_active_turn_id="turn:session:test:old",
            )
        ):
            events.append(event)
        return events

    try:
        events = asyncio.run(_collect())
        updated = host.state_index.get_task_run("taskrun:current")
        event_types = [event.event_type for event in host.event_log.list_events("taskrun:current")]

        assert model.calls == 0
        assert any(
            event.get("type") == "runtime_branch_decided"
            and dict(event.get("runtime_branch") or {}).get("branch_kind") == "active_turn_steer"
            for event in events
        )
        assert any(event.get("type") == "active_task_steer_accepted" for event in events)
        assert any(event.get("type") == "done" and event.get("terminal_reason") == "active_task_steer_recorded" for event in events)
        assert not any(event.get("terminal_reason") == "pause_active_work" for event in events)
        assert updated is not None
        assert updated.status == "running"
        assert int(dict(updated.diagnostics or {}).get("pending_user_steer_count") or 0) >= 1
        assert "user_submission_recorded" in event_types
        assert "active_task_steer_recorded" in event_types
        steer_signal_events = [
            event
            for event in host.event_log.list_events("taskrun:current")
            if event.event_type == "runtime_control_signal_published"
        ]
        steer_signals = [
            runtime_signal_from_event_payload(dict(event.payload or {}))
            for event in steer_signal_events
        ]
        steer_signal = next(signal for signal in steer_signals if signal is not None and signal.signal_type == "control.steer.recorded")
        assert steer_signal.scope.session_id == "session:test"
        assert steer_signal.scope.task_run_id == "taskrun:current"
        assert steer_signal.scope.turn_id == "turn:session:test:1"
        assert steer_signal.payload["signal_kind"] == "active_task_steer"
        assert steer_signal.payload["steer_ref"]
        assert steer_signal.payload["submission_ref"]
        assert "task_run_pause_requested" not in event_types
        messages = runtime.session_manager.load_session("session:test")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["turn_id"] == "turn:session:test:1"
    finally:
        claim.close()


def test_active_turn_auto_input_records_steer_without_model_decision(tmp_path: Path) -> None:
    class ActiveWorkAppendModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("active work input must be routed through current-work boundary before model decision")

    model = ActiveWorkAppendModelRuntime()
    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="created",
        created_at=1,
        updated_at=2,
        diagnostics={"turn_id": "turn:session:test:old"},
    )
    host.state_index.upsert_task_run(task_run)
    claim = _start_live_task_run_executor(host, task_run.task_run_id)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:old")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:old",
        task_run_id="taskrun:current",
        state="running_task",
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session:test",
                message="主题还应该加入字体",
            )
        ):
            events.append(event)
        return events

    try:
        events = asyncio.run(_collect())
        updated = host.state_index.get_task_run("taskrun:current")
        event_types = [event.event_type for event in host.event_log.list_events("taskrun:current")]

        assert model.calls == 0
        assert any(
            event.get("type") == "current_work_boundary_decided"
            and dict(event.get("decision") or {}).get("action") == "current_work_control_required"
            for event in events
        )
        assert any(event.get("type") == "active_task_steer_accepted" for event in events)
        assert any(event.get("type") == "done" and event.get("terminal_reason") == "active_task_steer_recorded" for event in events)
        assert updated is not None
        assert updated.status == "running"
        assert int(dict(updated.diagnostics or {}).get("pending_user_steer_count") or 0) >= 1
        assert "active_task_steer_recorded" in event_types
        messages = runtime.session_manager.load_session("session:test")
        assert len(messages) == 1
        assert messages[0]["content"] == "主题还应该加入字体"
    finally:
        claim.close()


def test_current_work_boundary_receipt_revalidates_before_append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class StaleBoundaryModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("explicit active-turn steer must revalidate without asking the model")

    model = StaleBoundaryModelRuntime()
    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="created",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    claim = _start_live_task_run_executor(host, task_run.task_run_id)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:old")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:old",
        task_run_id="taskrun:current",
        state="running_task",
    )
    original_compare = host.active_turn_registry.compare_and_update_current_turn
    compare_calls = {"count": 0}

    def compare_and_stale_on_receipt(*args, **kwargs):
        compare_calls["count"] += 1
        if compare_calls["count"] == 1:
            return original_compare(*args, **kwargs)
        return {
            "accepted": False,
            "denied_reason": "active_turn_unavailable",
            "expected_turn_id": str(kwargs.get("expected_turn_id") or ""),
            "actual_turn_id": "",
            "expected_task_run_id": str(kwargs.get("expected_task_run_id") or ""),
            "actual_task_run_id": "",
            "owner_instance_id": "",
            "terminal_reason": "active_turn_unavailable",
            "authority": "harness.runtime.active_turn.compare_and_update_current_turn",
        }

    monkeypatch.setattr(host.active_turn_registry, "compare_and_update_current_turn", compare_and_stale_on_receipt)

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session:test",
                message="接着加一条要求。",
                active_turn_input_policy="steer",
                expected_active_turn_id="turn:session:test:old",
            )
        ):
            events.append(event)
        return events

    try:
        events = asyncio.run(_collect())
        event_types = [event.event_type for event in host.event_log.list_events("taskrun:current")]

        assert not any(event.get("type") == "active_task_steer_accepted" for event in events)
        assert any(event.get("type") == "runtime_status" and event.get("terminal_reason") == "active_turn_unavailable" for event in events)
        assert any(event.get("type") == "error" and event.get("terminal_reason") == "active_turn_unavailable" for event in events)
        assert "active_task_steer_recorded" not in event_types
        assert compare_calls["count"] >= 2
        assert model.calls == 0
    finally:
        claim.close()


def test_active_turn_steer_does_not_promote_latest_task_when_active_turn_missing(tmp_path: Path) -> None:
    class BoundaryObservationModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "authority": "harness.loop.model_action_request",
                        "action_type": "respond",
                        "final_answer": "当前没有可控制的进行中任务，这条继续请求没有接入旧任务。",
                    },
                    ensure_ascii=False,
                )
            )

    model = BoundaryObservationModelRuntime()
    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=model)
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:old-waiting",
            session_id="session:test",
            task_id="task:old-waiting",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            created_at=1,
            updated_at=2,
            diagnostics={"recovery_action": "rerun_task_executor", "recoverable_error": {"retryable": True}},
        )
    )

    async def _collect() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime.astream(
            HarnessRuntimeRequest(
                session_id="session:test",
                message="继续刚才那个任务。",
                active_turn_input_policy="steer",
                expected_active_turn_id="turn:session:test:old",
            )
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert host.active_turn_registry.snapshot("session:test") is None
    assert model.calls >= 1
    assert not any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert any(event.get("type") == "done" and event.get("terminal_reason") == "respond" for event in events)
