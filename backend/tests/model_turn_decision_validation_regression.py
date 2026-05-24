from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_runtime.understanding.model_turn_decision import model_turn_decision_from_payload


def _base_decision_payload(**overrides):
    payload = {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "请用专业模式完成浏览器小游戏工程。",
        "interaction_intent": "create",
        "action_intent": "edit_workspace",
        "work_mode": "implementation",
        "task_goal_type": "game_vertical_slice_delivery",
        "task_domain": "software_engineering",
        "confidence": 0.91,
        "target_objects": ["frontend/public/games/arcane_dungeon_studio/"],
        "desired_outcome": "交付可验收的浏览器小游戏第一版。",
        "deliverables": ["index.html", "styles.css", "game.js", "README.md"],
        "constraints": ["sandbox overlay"],
        "forbidden_actions": [],
        "selected_skill_ids": [],
        "context_binding_decision": {},
        "planning_required": True,
        "todo_required": True,
        "completion_criteria": ["核心文件存在", "terminal 验证通过"],
        "needs_clarification": False,
        "clarification_question": "",
        "ambiguity": [],
    }
    payload.update(overrides)
    return payload


def test_model_turn_decision_non_numeric_confidence_does_not_block_valid_decision() -> None:
    decision, validation = model_turn_decision_from_payload(
        _base_decision_payload(confidence="high"),
        user_message="请用专业模式完成浏览器小游戏工程。",
    )

    assert decision is not None
    assert decision.action_intent == "edit_workspace"
    assert decision.task_goal_type == "game_vertical_slice_delivery"
    assert decision.confidence == 0.0
    assert validation["decision_status"] == "accepted"
    assert validation["validation_errors"] == []
    assert "confidence_defaulted_from_non_numeric" in validation["validation_warnings"]


def test_model_turn_decision_rejects_behavioral_intent_errors() -> None:
    decision, validation = model_turn_decision_from_payload(
        _base_decision_payload(action_intent="write_everything_now", confidence="high"),
        user_message="请用专业模式完成浏览器小游戏工程。",
    )

    assert decision is None
    assert validation["decision_status"] == "rejected_invalid"
    assert "action_intent_unsupported:write_everything_now" in validation["validation_errors"]


def test_model_turn_decision_normalizes_selected_skill_ids() -> None:
    decision, validation = model_turn_decision_from_payload(
        _base_decision_payload(selected_skill_ids=["structured-data-analysis", "skill.structured-data-analysis"]),
        user_message="请分析表格。",
    )

    assert decision is not None
    assert decision.selected_skill_ids == ("skill.structured-data-analysis",)
    assert validation["decision_status"] == "accepted"
