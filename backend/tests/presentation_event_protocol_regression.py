from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.loop.presentation import error_event


def test_error_event_accepts_structured_runtime_refs() -> None:
    event = error_event(
        content="当前有正在运行的任务，需要携带 expected_active_turn_id。",
        code="expected_turn_id_required",
        reason="expected_turn_id_required",
        extra={
            "active_turn_id": "turn:session:test:1",
            "active_turn": {"turn_id": "turn:session:test:1"},
        },
    )

    assert event["type"] == "error"
    assert event["code"] == "expected_turn_id_required"
    assert event["active_turn_id"] == "turn:session:test:1"
    assert event["active_turn"]["turn_id"] == "turn:session:test:1"
