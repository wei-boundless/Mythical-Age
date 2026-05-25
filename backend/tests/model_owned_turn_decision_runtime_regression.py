from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.unit_runtime.loop import _main_model_owned_turn_decision


def _decision_payload() -> dict[str, object]:
    return {
        "authority": "agent_runtime.model_turn_decision",
        "decision_id": "model-turn-decision:test",
        "user_message": "基于源项目继续开发，并继承 assets。",
        "interaction_intent": "modify",
        "action_intent": "edit_workspace",
        "work_mode": "implementation",
        "task_goal_type": "game_vertical_slice_delivery",
        "domain_mismatch_signal": {},
        "target_objects": ["frontend/public/games/demo"],
        "desired_outcome": "增加关卡并保留美术资产。",
        "deliverables": ["updated_game"],
        "constraints": ["preserve existing assets"],
        "forbidden_actions": [],
        "selected_skill_ids": [],
        "resource_contract": {
            "source_projects": [{"path": "source/game", "role": "source", "required": True}],
            "target_projects": [{"path": "target/game", "role": "target", "required": True}],
            "required_read_files": ["index.html", "styles.css", "game.js", "README.md"],
            "required_read_dirs": ["assets"],
            "required_write_files": ["index.html", "styles.css", "game.js", "README.md"],
            "required_write_dirs": ["assets"],
            "asset_policy": {
                "must_preserve_existing_assets": True,
                "referenced_assets_must_exist": True,
            },
        },
        "context_binding_decision": {"mode": "current_turn"},
        "planning_required": True,
        "todo_required": True,
        "completion_criteria": ["assets directory is preserved"],
        "needs_clarification": False,
        "clarification_question": "",
        "confidence": 0.93,
        "ambiguity": [],
        "diagnostics": {},
    }


class _ModelRuntime:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, str]]] = []

    async def invoke_messages(self, messages):
        self.calls.append(list(messages))
        return SimpleNamespace(content=self.outputs.pop(0))


def test_main_model_turn_decision_uses_model_payload_not_code_guesses() -> None:
    runtime = _ModelRuntime([json.dumps(_decision_payload(), ensure_ascii=False)])

    decision, diagnostics = asyncio.run(
        _main_model_owned_turn_decision(
            user_message="基于源项目继续开发，并继承 assets。",
            request_facts={"explicit_paths": []},
            task_selection={"interaction_mode": "professional_mode"},
            model_runtime=runtime,
        )
    )

    assert len(runtime.calls) == 1
    assert diagnostics["model_call_performed"] is True
    assert diagnostics["model_authority_used"] is True
    assert decision["task_goal_type"] == "game_vertical_slice_delivery"
    assert "task_domain" not in decision
    assert decision["resource_contract"]["required_read_dirs"] == ["assets"]
    assert decision["resource_contract"]["required_write_dirs"] == ["assets"]


def test_main_model_turn_decision_does_not_send_task_domain_binding_to_model() -> None:
    runtime = _ModelRuntime([json.dumps(_decision_payload(), ensure_ascii=False)])

    asyncio.run(
        _main_model_owned_turn_decision(
            user_message="请继续完成代码重构。",
            request_facts={
                "explicit_selection": {
                    "task_domain_binding": {"binding_id": "taskdomainbind:facts"},
                    "domain": "development",
                    "selected_task_id": "task.dev.refactor",
                }
            },
            task_selection={
                "interaction_mode": "professional_mode",
                "task_domain_binding": {
                    "binding_id": "taskdomainbind:selection",
                    "bound_domain_id": "domain.development",
                    "default_practices": ["先观察真实代码和项目结构"],
                },
                "active_domain_binding": {"binding_id": "active:domain"},
                "domain": "development",
                "runtime_control": {"raw": True},
                "agent_invocation": {"invocation_id": "agent-invocation:raw"},
                "selected_task_id": "task.dev.refactor",
            },
            model_runtime=runtime,
        )
    )

    user_payload = json.loads(runtime.calls[0][1]["content"])
    serialized = json.dumps(user_payload, ensure_ascii=False)

    assert "task_domain_binding" not in serialized
    assert "active_domain_binding" not in serialized
    assert "domain.development" not in serialized
    assert "先观察真实代码和项目结构" not in serialized
    assert "runtime_control" not in serialized
    assert "agent_invocation" not in serialized
    assert user_payload["task_selection"]["selected_task_id"] == "task.dev.refactor"


def test_main_model_turn_decision_repairs_invalid_model_json_once() -> None:
    runtime = _ModelRuntime(["不是 JSON", json.dumps(_decision_payload(), ensure_ascii=False)])

    decision, diagnostics = asyncio.run(
        _main_model_owned_turn_decision(
            user_message="继续开发游戏。",
            request_facts={},
            task_selection={},
            model_runtime=runtime,
        )
    )

    assert len(runtime.calls) == 2
    assert "不能作为 ModelTurnDecision 使用" in runtime.calls[1][-1]["content"]
    assert diagnostics["decision_status"] == "accepted"
    assert diagnostics["understanding_attempts"] == 2
    assert decision["action_intent"] == "edit_workspace"

