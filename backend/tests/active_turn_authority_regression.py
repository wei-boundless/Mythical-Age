from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

import api.orchestration_harness as orchestration_harness
from api.orchestration_harness import _assert_expected_active_turn, _schedule_result_allows_progress
from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime import SingleAgentRuntimeHost
from harness.loop.task_executor import is_task_run_executable, request_task_run_pause, resume_paused_task_run
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
        status="running",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.bind_task_run(
        session_id="session:test",
        turn_id="turn:session:test:1",
        task_run_id=task_run.task_run_id,
        state="running_task",
    )

    result = request_task_run_pause(host, task_run.task_run_id, reason="test_pause", requested_by="user")

    active = host.active_turn_registry.snapshot("session:test")
    assert result["ok"] is True
    assert active is not None
    assert active.bound_task_run_id == task_run.task_run_id
    assert active.state == "waiting_safe_boundary"


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
        import asyncio

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
        terminal_reason="waiting_executor",
        created_at=1,
        updated_at=2,
    )
    host.state_index.upsert_task_run(task_run)

    resume = resume_paused_task_run(host, task_run.task_run_id, requested_by="user")

    assert is_task_run_executable(task_run) is False
    assert resume["ok"] is False
    assert resume["error"] == "task_run_not_resumable:waiting_executor"


def test_active_turn_plain_instruction_uses_model_decision_without_keyword_pause(tmp_path: Path) -> None:
    import asyncio

    class ActiveWorkAppendModelRuntime:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke_messages(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "action": "append_instruction_to_active_work",
                            "relation_to_current_work": "current_work",
                            "appended_instruction": "等一下 task runtime 为什么必须有 task_environment？",
                            "response": "我会先把这个问题接入当前工作判断。",
                            "reason": "用户正在向当前 active turn 补充约束。",
                        },
                        ensure_ascii=False,
                    )
                )
            return SimpleNamespace(content="已接入当前工作。")

    model = ActiveWorkAppendModelRuntime()
    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=model)
    host = runtime.single_agent_runtime_host
    task_run = TaskRun(
        task_run_id="taskrun:current",
        session_id="session:test",
        task_id="task:current",
        execution_runtime_kind="single_agent_task",
        status="running",
        created_at=1,
        updated_at=2,
        diagnostics={"turn_id": "turn:session:test:old"},
    )
    host.state_index.upsert_task_run(task_run)
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

    events = asyncio.run(_collect())
    updated = host.state_index.get_task_run("taskrun:current")
    event_types = [event.event_type for event in host.event_log.list_events("taskrun:current")]

    assert model.calls >= 1
    assert any(event.get("type") == "active_task_steer_accepted" for event in events)
    assert not any(event.get("terminal_reason") == "pause_active_work" for event in events)
    assert updated is not None
    assert updated.status == "running"
    assert int(dict(updated.diagnostics or {}).get("pending_user_steer_count") or 0) >= 1
    assert "task_run_pause_requested" not in event_types
    messages = runtime.session_manager.load_session("session:test")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["turn_id"] == "turn:session:test:1"


def test_active_turn_steer_does_not_promote_latest_task_when_active_turn_missing(tmp_path: Path) -> None:
    import asyncio

    class FailingModelRuntime:
        async def invoke_messages(self, *_args, **_kwargs):
            raise AssertionError("missing active turn steer should block before model")

    runtime = build_harness_runtime(base_dir=tmp_path, model_runtime=FailingModelRuntime())
    host = runtime.single_agent_runtime_host
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:old-waiting",
            session_id="session:test",
            task_id="task:old-waiting",
            execution_runtime_kind="single_agent_task",
            status="waiting_executor",
            terminal_reason="waiting_executor",
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
    assert any(event.get("type") == "done" and event.get("terminal_reason") == "active_turn_steer_not_running" for event in events)
