from __future__ import annotations

import json

from runtime.shared.event_log import RuntimeEventLog
from runtime.shared import event_index


def test_runtime_event_log_uses_cursor_after_initial_index_build(tmp_path, monkeypatch) -> None:
    log = RuntimeEventLog(tmp_path)
    path = log._event_path("taskrun:test")
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "event_id": f"evt:{index}",
                    "task_run_id": "taskrun:test",
                    "event_type": "step_summary_recorded",
                    "offset": index,
                    "created_at": float(index),
                    "payload": {"summary": f"step {index}"},
                    "refs": {},
                    "authority": "orchestration.runtime_event",
                }
            )
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )

    assert log.next_offset("taskrun:test") == 3

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("cursor-backed next_offset must not rebuild from full event file")

    monkeypatch.setattr(event_index, "rebuild_event_index", fail_rebuild)
    event = log.append("taskrun:test", "step_summary_recorded", payload={"summary": "step 3"})

    assert event.offset == 3
    assert log.next_offset("taskrun:test") == 4


def test_runtime_event_log_recent_events_and_count_use_index(tmp_path) -> None:
    log = RuntimeEventLog(tmp_path)
    for index in range(5):
        log.append("taskrun:test", "step_summary_recorded", payload={"summary": f"step {index}"})

    recent = log.list_recent_events("taskrun:test", limit=2)

    assert [item.offset for item in recent] == [3, 4]
    assert log.event_count("taskrun:test") == 5
