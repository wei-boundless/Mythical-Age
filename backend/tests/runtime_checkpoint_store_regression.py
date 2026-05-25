from __future__ import annotations

import os
from pathlib import Path

from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.checkpoint import RuntimeCheckpointStore
from runtime.shared.execution_record import RuntimeExecutionStore
from runtime.shared.models import RuntimeLoopState


def test_runtime_checkpoint_write_retries_windows_permission_error(tmp_path: Path, monkeypatch) -> None:
    store = RuntimeCheckpointStore(tmp_path)
    state = RuntimeLoopState(task_run_id="taskrun:checkpoint-lock", status="completed")
    original_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("simulated windows file lock")
        return original_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    checkpoint = store.write(state, event_offset=3)
    loaded = store.load_latest(state.task_run_id)

    assert calls["count"] == 2
    assert loaded is not None
    assert loaded.checkpoint_id == checkpoint.checkpoint_id
    assert loaded.event_offset == 3


def test_runtime_checkpoint_persists_resume_state(tmp_path: Path) -> None:
    store = RuntimeCheckpointStore(tmp_path)
    state = RuntimeLoopState(
        task_run_id="taskrun:checkpoint-resume",
        status="waiting_approval",
        terminal_reason="waiting_approval",
        pending_approval_state={"status": "pending", "stage_id": "stage:a"},
    )

    checkpoint = store.write(state, event_offset=8)
    loaded = store.load_latest(state.task_run_id)

    assert checkpoint.resume_state["decision"] == "wait_for_human"
    assert checkpoint.resume_state["reason"] == "human_gate_pending"
    assert loaded is not None
    assert loaded.resume_state["decision"] == "wait_for_human"


def test_runtime_checkpoint_uses_bounded_storage_path_for_long_task_run_id(tmp_path: Path) -> None:
    store = RuntimeCheckpointStore(tmp_path)
    task_run_id = (
        "taskrun:writing-modular-novel-honghuang-20260525-060137-full-brief-domain-names:"
        "taskinst:turn:writing-modular-novel-honghuang-20260525-060137-full-brief-domain-names:"
        "324b00664488:project_brief:project_brief:8f64c4c7"
    )
    state = RuntimeLoopState(
        task_run_id=task_run_id,
        status="running",
        agent_id="agent:writer",
        agent_profile_id="writing_profile",
        runtime_lane="coordination_task",
    )

    checkpoint = store.write(state, event_offset=4)
    loaded = store.load_latest(task_run_id)
    filenames = [path.name for path in (tmp_path / "checkpoints").glob("*.json")]

    assert loaded is not None
    assert loaded.checkpoint_id == checkpoint.checkpoint_id
    assert loaded.loop_state.agent_id == "agent:writer"
    assert loaded.loop_state.agent_profile_id == "writing_profile"
    assert loaded.loop_state.runtime_lane == "coordination_task"
    assert len(filenames) == 1
    assert len(filenames[0]) < 200


def test_runtime_execution_store_uses_bounded_storage_path_for_long_task_run_id(tmp_path: Path) -> None:
    store = RuntimeExecutionStore(tmp_path)
    task_run_id = (
        "taskrun:writing-modular-novel-honghuang-20260525-060137-full-brief-domain-names:"
        "taskinst:turn:writing-modular-novel-honghuang-20260525-060137-full-brief-domain-names:"
        "324b00664488:project_brief:project_brief:8f64c4c7"
    )
    request = RuntimeActionRequest(
        request_id="request:model",
        task_run_id=task_run_id,
        request_type="model_response",
    )

    record = store.create_record(
        task_run_id=task_run_id,
        step_id="model",
        action_request=request,
        directive_ref="directive:model",
        operation_id="op.model_response",
        executor_type="model",
        replay_policy="deny_auto_replay",
        request_fingerprint="fingerprint",
        idempotency_token="token",
    )
    loaded = store.list_task_run_records(task_run_id)
    filenames = [path.name for path in (tmp_path / "executions").glob("*.json")]

    assert [item.execution_id for item in loaded] == [record.execution_id]
    assert len(filenames) == 1
    assert len(filenames[0]) < 200
