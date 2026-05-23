from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from request_intent.memory_intent import analyze_memory_intent
from request_intent.request_signals import build_request_signals


def test_request_signals_are_facts_not_intent_or_route() -> None:
    frame = build_request_signals("修改 backend/foo.py，修复这个问题").to_dict()

    assert frame["authority"] == "request_facts.frame"
    assert "primary_intent" not in frame
    assert "route_hint" not in frame["capability_intent"]
    assert "write_requested" not in frame["turn_signals"]
    assert "verification_requested" not in frame["turn_signals"]
    assert frame["capability_intent"]["tool_selection_allowed"] is False
    assert "backend/foo.py" in frame["turn_signals"]["explicit_paths"]
    assert ".py" in frame["turn_signals"]["material_suffixes"]


def test_memory_recall_marker_stays_candidate_only() -> None:
    memory_intent = analyze_memory_intent("你还记得我的回答方式偏好吗？")
    frame = build_request_signals("你还记得我的回答方式偏好吗？", memory_intent).to_dict()

    assert frame["turn_signals"]["memory_recall_marker"] is True
    assert "memory_candidate" in frame["capability_intent"]["capability_needs"]
    assert "route_hint" not in frame["capability_intent"]
    assert "tool_name" not in frame
    assert "candidate_tools" not in frame
