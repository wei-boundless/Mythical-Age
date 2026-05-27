from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import HarnessServiceHost
from harness.loop.state import HarnessLoopState
from runtime.shared.models import TaskRun


def test_harness_service_host_stop_can_write_checkpoint(tmp_path) -> None:
    host = HarnessServiceHost(root_dir=tmp_path / "runtime_state", backend_dir=Path("backend").resolve())
    task_run_id = "taskrun:test-stop-checkpoint"
    timestamp = time.time()
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session:test-stop-checkpoint",
            task_id="task.test.stop_checkpoint",
            status="running",
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    initial_event = host.event_log.append(
        task_run_id,
        "loop_iteration",
        payload={"seed": "test"},
    )
    host.checkpoints.write(
        HarnessLoopState(
            task_run_id=task_run_id,
            status="running",
            transition="loop_iteration",
            diagnostics={"seed": "test"},
        ),
        event_offset=initial_event.offset,
    )

    checkpoint = host.checkpoints.load_latest(task_run_id)
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
    stop_event = host.event_log.append(
        task_run_id,
        "task_run_stopped",
        payload={"reason": "user_aborted"},
    )
    checkpoint_event = host._write_checkpoint_event(loop_state, event_offset=stop_event.offset)
    refreshed = host.checkpoints.load_latest(task_run_id)

    assert checkpoint_event.refs["checkpoint_ref"]
    assert refreshed is not None
    assert refreshed.event_offset == stop_event.offset
    assert refreshed.event_offset != checkpoint.event_offset


