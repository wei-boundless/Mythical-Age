from __future__ import annotations

import os
from pathlib import Path

from runtime.shared.checkpoint import RuntimeCheckpointStore
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
