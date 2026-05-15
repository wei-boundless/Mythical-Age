from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestration.runtime_loop.task_run_loop import TaskRunLoop


def test_task_run_loop_stop_can_write_checkpoint(tmp_path) -> None:
    loop = TaskRunLoop(root_dir=Path("storage/runtime_state").resolve(), backend_dir=Path("backend").resolve())
    task_run_id = "taskrun:writing_team_honghuang_20260515b:taskinst:turn:writing_team_honghuang_20260515b:1:world_design:4482b884"
    task_run = loop.state_index.get_task_run(task_run_id)
    assert task_run is not None
    checkpoint = loop.checkpoints.load_latest(task_run_id)
    assert checkpoint is not None
    loop_state = checkpoint.loop_state.with_status(
        "aborted",
        transition="stop_after_final_output",
        terminal_reason="user_aborted",
        diagnostics={
            **dict(checkpoint.loop_state.diagnostics),
            "stop_request": {"reason": "user_aborted", "message": "test"},
        },
    )
    checkpoint_event = loop._write_checkpoint_event(loop_state, event_offset=checkpoint.event_offset)
    assert checkpoint_event.refs["checkpoint_ref"]
