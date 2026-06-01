from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
import pytest

from api.orchestration_harness import _assert_expected_active_turn
from harness.runtime import SingleAgentRuntimeHost
from harness.loop.task_lifecycle import TaskLifecycleRecord, TaskRunContract, finish_task_lifecycle, start_task_lifecycle
from harness.loop.model_action_protocol import ModelActionRequest
from runtime.shared.models import TaskRun


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


def test_active_turn_binds_task_and_steer_reuses_active_task_steer(tmp_path: Path) -> None:
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
    )

    active = host.active_turn_registry.snapshot("session:test")
    assert active is not None
    assert active.bound_task_run_id == task_run.task_run_id

    result = host.active_turn_registry.steer(
        session_id="session:test",
        expected_turn_id="turn:session:test:1",
        user_message="请把验收标准补充为必须有可运行产物。",
    )

    assert result.ok is True
    assert result.task_run_id == task_run.task_run_id
    assert str((result.steer or {}).get("steer_id") or "").startswith(f"steer:{task_run.task_run_id}:")
    updated = host.state_index.get_task_run(task_run.task_run_id)
    assert updated is not None
    assert int(dict(updated.diagnostics or {}).get("pending_user_steer_count") or 0) == 1


def test_active_turn_complete_releases_session(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")
    host.active_turn_registry.complete(
        session_id="session:test",
        expected_turn_id="turn:session:test:1",
        terminal_reason="assistant_message",
    )

    assert host.active_turn_registry.snapshot("session:test") is None


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


def test_active_turn_steer_requires_expected_turn_id(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=Path.cwd())
    host.active_turn_registry.start(session_id="session:test", turn_id="turn:session:test:1")

    result = host.active_turn_registry.steer(
        session_id="session:test",
        expected_turn_id="",
        user_message="补充要求",
    )

    assert result.ok is False
    assert result.status == "expected_turn_id_required"


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
