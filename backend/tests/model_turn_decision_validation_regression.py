from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_runtime.understanding.model_turn_decision import model_turn_decision_from_payload
from agent_runtime.understanding.model_turn_decision_runtime import (
    canonical_model_turn_decision_payload as _canonical_model_turn_decision_payload,
    fallback_model_turn_decision as _fallback_model_turn_decision,
    main_model_owned_turn_decision as _main_model_owned_turn_decision,
)


class _FailingDecisionModelRuntime:
    async def invoke_messages(self, _messages):
        raise RuntimeError("provider_unavailable")


def _base_decision_payload(**overrides):
    payload = {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "请用专业模式完成浏览器小游戏工程。",
        "interaction_intent": "create",
        "action_intent": "edit_workspace",
        "work_mode": "implementation",
        "task_goal_type": "game_vertical_slice_delivery",
        "domain_mismatch_signal": {},
        "confidence": 0.91,
        "target_objects": ["frontend/public/games/arcane_dungeon_studio/"],
        "desired_outcome": "交付可验收的浏览器小游戏第一版。",
        "deliverables": ["index.html", "styles.css", "game.js", "README.md"],
        "constraints": ["sandbox overlay"],
        "forbidden_actions": [],
        "selected_skill_ids": [],
        "resource_contract": {},
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
    assert "task_domain" not in decision.to_dict()
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


def test_model_turn_decision_accepts_resource_contract() -> None:
    decision, validation = model_turn_decision_from_payload(
        _base_decision_payload(
            resource_contract={
                "source_projects": [{"path": "output/sandbox_runs/source/workspace/frontend/public/games/demo/"}],
                "target_projects": [{"path": "frontend/public/games/demo/"}],
                "required_read_files": ["index.html", "game.js"],
                "required_read_dirs": ["assets/"],
                "required_write_files": ["index.html", "game.js"],
                "required_write_dirs": ["assets/"],
                "asset_policy": {"must_preserve_existing_assets": True},
            }
        ),
        user_message="接手旧游戏并增加第二层。",
    )

    assert decision is not None
    contract = decision.resource_contract
    assert contract["source_projects"][0]["path"] == "output/sandbox_runs/source/workspace/frontend/public/games/demo/"
    assert contract["target_projects"][0]["path"] == "frontend/public/games/demo/"
    assert contract["required_read_dirs"] == ["assets"]
    assert contract["required_write_dirs"] == ["assets"]
    assert contract["asset_policy"]["must_preserve_existing_assets"] is True
    assert validation["decision_status"] == "accepted"


def test_fallback_model_turn_decision_blocks_without_system_authored_plan() -> None:
    message = (
        "请接手这个已有浏览器肉鸽游戏项目，扩展成一个完整的五关剧情战役版本，并加入成长机制和 Boss 战。\n\n"
        "只读源项目在：\n"
        "D:/AI应用/langchain-agent/output/sandbox_runs/source/workspace/frontend/public/games/arcane_dungeon_studio\n\n"
        "目标输出目录仍然是：\n"
        "frontend/public/games/arcane_dungeon_studio\n\n"
        "要求：必须先读取源项目的 index.html、styles.css、game.js、README.md。"
        "必须继承源项目 assets/ 目录里的全部美术资源。"
        "必须更新 README，说明五关剧情流程、成长机制、Boss 战机制和验证方式。"
    )

    decision, diagnostics = _fallback_model_turn_decision(
        user_message=message,
        reason="model_turn_decision_invalid_after_repair",
        task_selection={"interaction_mode": "professional_mode"},
        request_facts={
            "explicit_paths": [
                "D:/AI应用/langchain-agent/output/sandbox_runs/source/workspace/frontend/public/games/arcane_dungeon_studio",
                "frontend/public/games/arcane_dungeon_studio",
            ]
        },
        diagnostics={"validation_errors": ["interaction_intent_required"]},
    )

    assert diagnostics["decision_status"] == "blocked"
    assert diagnostics["fallback_understanding_removed"] is True
    assert decision["action_intent"] == "block"
    assert decision["task_goal_type"] == "blocked"
    assert decision["resource_contract"] == {}
    assert "task_domain" not in decision


def test_unregistered_goal_type_is_not_rewritten_by_runtime_keywords() -> None:
    payload = _canonical_model_turn_decision_payload(
        _base_decision_payload(task_goal_type="game_expansion_with_narrative_and_mechanics"),
        user_message="请扩展浏览器肉鸽游戏，加入五关战役、成长机制和 Boss 战。",
        task_selection={"interaction_mode": "professional_mode"},
    )

    assert payload["task_goal_type"] == "game_expansion_with_narrative_and_mechanics"
    assert payload["diagnostics"]["unsupported_task_goal_type"] == "game_expansion_with_narrative_and_mechanics"
    assert payload["diagnostics"]["supported_task_goal_types_required"] is True


def test_model_turn_decision_provider_failure_blocks_without_executable_fallback() -> None:
    message = (
        "请接手已有浏览器游戏项目，目标输出目录 frontend/public/games/arcane_dungeon_studio，"
        "必须写入 index.html、styles.css、game.js、README.md，并加入五关、成长和 Boss。"
    )

    decision, diagnostics = asyncio.run(
        _main_model_owned_turn_decision(
            user_message=message,
            request_facts={"explicit_paths": ["frontend/public/games/arcane_dungeon_studio"]},
            task_selection={"interaction_mode": "professional_mode"},
            model_runtime=_FailingDecisionModelRuntime(),
        )
    )

    assert diagnostics["decision_status"] == "blocked"
    assert diagnostics["fallback_understanding_removed"] is True
    assert decision["action_intent"] == "block"
    assert decision["resource_contract"] == {}


