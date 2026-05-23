from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from tests.support.runtime_stubs import QueryRuntimeMemoryFacadeStub, isolated_backend_root


ROGUELIKE_PROMPT = """你是一名独立游戏原型开发负责人。

你的目标是在当前项目中完成一个可运行、可测试、可迭代的浏览器端 2D 肉鸽游戏垂直切片。
你必须按阶段推进：项目简报、玩法设计、技术设计、资产清单、生图提示词与资源生成、MVP 实现、资源接入、运行验证、最终报告。
最低产品范围：俯视角移动、玩家攻击、三类敌人、波次推进、奖励拾取、升级三选一、Boss、死亡或胜利状态、可见 HUD。
你需要真实修改代码、真实生成或接入至少一个图像资产、真实启动项目并验证。
请把阶段产物写入 docs/experiments/roguelike_long_task/，最终报告写入 docs/experiments/roguelike_long_task/final_report.md。"""


def _runtime_bundle(message: str, *, task_selection: dict[str, object] | None = None) -> dict[str, object]:
    assembler = AgentRuntimeChainAssembler(
        base_dir=isolated_backend_root("understanding-runtime-steps-"),
        memory_facade=QueryRuntimeMemoryFacadeStub(),
    )
    return assembler.build_runtime(
        session_id="session-understanding-runtime-steps",
        task_id="task-understanding-runtime-steps",
        turn_id="turn-understanding-runtime-steps",
        message=message,
        source="test",
        task_selection=task_selection,
    )


def _step_ids(recipe: dict[str, object]) -> list[str]:
    return [str(item.get("step_id") or "") for item in list(recipe.get("step_blueprints") or []) if isinstance(item, dict)]


def test_professional_game_goal_compiles_understanding_and_domain_steps_into_recipe() -> None:
    bundle = _runtime_bundle(
        ROGUELIKE_PROMPT,
        task_selection={
            "interaction_mode": "professional_mode",
            "runtime_interaction_mode": "professional_mode",
            "intent_decision": {"execution_strategy": "professional_task_run", "interaction_mode": "professional_mode"},
            "runtime_assembly_hint": {
                "execution_strategy": "professional_task_run",
                "interaction_mode": "professional_mode",
                "runtime_mode": "professional_task",
            },
        },
    )

    current_turn = dict(bundle["current_turn_context"])
    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    metadata = dict(recipe["metadata"])
    semantic_contract = dict(metadata["semantic_task_contract"])
    agent_plan = dict(metadata["agent_plan_draft"])
    coverage = dict(metadata["plan_coverage_review"])
    ids = _step_ids(recipe)

    assert current_turn["task_goal_frame"]["task_goal_type"] == "game_vertical_slice_delivery"
    assert semantic_contract["task_goal_type"] == "game_vertical_slice_delivery"
    assert metadata["understanding_step_compiler"] == "task_system.planning.understanding_step_compiler"
    assert ids[:8] == [
        "turn_intake",
        "context_resolution",
        "task_goal_understanding",
        "domain_flow_matching",
        "contract_compilation",
        "prompt_assembly",
        "execution_planning",
        "plan_coverage_review",
    ]
    assert agent_plan["task_goal_type"] == "game_vertical_slice_delivery"
    assert any(step["step_id"] == "integrate_visual_asset" for step in agent_plan["steps"])
    assert coverage["passed"] is True
    assert "integrate_asset" in coverage["covered_actions"]
    assert "step_execution.plan_vertical_slice" in ids
    assert "step_execution.implement_core_gameplay" in ids
    assert "step_execution.integrate_visual_asset" in ids
    assert "step_execution.run_browser_verification" in ids
    assert ids[-2:] == ["verification", "finalization"]
    assert metadata["compiled_step_ids"] == ids


def test_frontend_goal_compiles_browser_verification_operations() -> None:
    bundle = _runtime_bundle(
        "请重构前端任务图编辑器，做成可运行的编辑器体验，并用浏览器验证关键工作流。",
        task_selection={
            "interaction_mode": "professional_mode",
            "runtime_interaction_mode": "professional_mode",
            "intent_decision": {"execution_strategy": "professional_task_run", "interaction_mode": "professional_mode"},
            "runtime_assembly_hint": {
                "execution_strategy": "professional_task_run",
                "interaction_mode": "professional_mode",
                "runtime_mode": "professional_task",
            },
        },
    )

    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    metadata = dict(recipe["metadata"])
    agent_plan = dict(metadata["agent_plan_draft"])
    coverage = dict(metadata["plan_coverage_review"])
    ids = _step_ids(recipe)
    verification = next(item for item in list(recipe["step_blueprints"]) if item["step_id"] == "verification")

    assert metadata["semantic_task_type"] == "frontend_app_delivery"
    assert agent_plan["task_goal_type"] == "frontend_app_delivery"
    assert coverage["passed"] is True
    assert "run_browser_verification" in coverage["covered_actions"]
    assert "step_execution.plan_user_workflow" in ids
    assert "step_execution.implement_frontend_changes" in ids
    assert "step_execution.run_browser_verification" in ids
    assert "op.browser" in verification["optional_operations"]


def test_role_mode_uses_lightweight_understanding_steps_without_professional_domain_execution() -> None:
    bundle = _runtime_bundle(
        "陪我聊一下今天的状态。",
        task_selection={
            "interaction_mode": "role_mode",
            "runtime_interaction_mode": "role_mode",
            "runtime_assembly_hint": {"interaction_mode": "role_mode", "runtime_mode": "role_interaction"},
        },
    )

    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    ids = _step_ids(recipe)

    assert recipe["metadata"]["interaction_mode"] == "role_mode"
    assert ids == ["turn_intake", "context_resolution", "prompt_assembly", "finalization"]
    assert not any(item.startswith("step_execution.") for item in ids)
