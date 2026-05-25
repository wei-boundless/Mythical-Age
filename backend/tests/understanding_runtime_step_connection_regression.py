from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.assembly.runtime_chain import AgentRuntimeChainAssembler
from tests.support.runtime_stubs import QueryRuntimeMemoryFacadeStub, isolated_backend_root, model_turn_context


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
    selection = dict(task_selection or {})
    if "model_turn_decision" not in selection:
        goal_type = ""
        if "肉鸽游戏" in message or "游戏垂直切片" in message:
            goal_type = "game_vertical_slice_delivery"
        elif "前端" in message or "浏览器验证" in message:
            goal_type = "frontend_app_delivery"
        selection.update(
            model_turn_context(
                action_intent="edit_workspace",
                work_mode="implementation",
                interaction_intent="create",
                desired_outcome=message,
                deliverables=["runnable_artifact_refs", "verification_evidence"],
                planning_required=True,
                todo_required=True,
                task_goal_type=goal_type,
                task_domain="development" if goal_type else "",
            )
        )
    return assembler.build_runtime(
        session_id="session-understanding-runtime-steps",
        task_id="task-understanding-runtime-steps",
        turn_id="turn-understanding-runtime-steps",
        message=message,
        source="test",
        task_selection=selection,
        current_turn_context_override=selection,
    )


def _step_ids(recipe: dict[str, object]) -> list[str]:
    return [str(item.get("step_id") or "") for item in list(recipe.get("step_blueprints") or []) if isinstance(item, dict)]


def _model_plan(*, task_goal_type: str, contract_refs: list[str], deliverable_refs: list[str]) -> dict[str, object]:
    steps = []
    if "read_material" in contract_refs or "inspect_code" in contract_refs:
        steps.append(
            {
                "step_id": "inspect_project",
                "title": "Inspect project",
                "purpose": "Read project structure and entrypoints.",
                "required_operations": ["op.read_file", "op.search_text"],
                "contract_refs": [item for item in ("read_material", "inspect_code") if item in contract_refs],
                "evidence_expectations": ["source_tree_observation"],
            }
        )
    if "apply_real_change" in contract_refs:
        steps.append(
            {
                "step_id": "apply_change",
                "title": "Apply change",
                "purpose": "Make the requested real code or artifact changes.",
                "required_operations": ["op.write_file", "op.edit_file"],
                "contract_refs": ["apply_real_change", *deliverable_refs],
                "evidence_expectations": ["file_write"],
            }
        )
    if "integrate_asset" in contract_refs:
        steps.append(
            {
                "step_id": "integrate_visual_asset",
                "title": "Integrate visual asset",
                "purpose": "Create or connect real visual assets.",
                "required_operations": ["op.write_file", "op.edit_file"],
                "contract_refs": ["integrate_asset", "visual_asset_refs"],
                "evidence_expectations": ["asset_file", "asset_visible"],
            }
        )
    if "run_browser_verification" in contract_refs:
        steps.append(
            {
                "step_id": "run_browser_verification",
                "title": "Run browser verification",
                "purpose": "Open the app and verify the expected workflow.",
                "required_operations": ["op.shell", "op.browser_control"],
                "contract_refs": ["run_browser_verification", "verification_evidence"],
                "evidence_expectations": ["browser_open", "workflow_check"],
            }
        )
    elif "run_verification" in contract_refs:
        steps.append(
            {
                "step_id": "run_verification",
                "title": "Run verification",
                "purpose": "Run tests or report real verification limits.",
                "required_operations": ["op.shell"],
                "contract_refs": ["run_verification", "verification_result_or_limitation"],
                "evidence_expectations": ["command_run", "test_result"],
            }
        )
    if "validate_deliverables" in contract_refs:
        steps.append(
            {
                "step_id": "finalize_delivery",
                "title": "Finalize delivery",
                "purpose": "Report evidence, limitations, and final result.",
                "required_operations": ["op.model_response"],
                "contract_refs": ["validate_deliverables", "limitations", *deliverable_refs],
                "evidence_expectations": ["completion_judgment"],
            }
        )
    return {
        "authority": "runtime.agent_plan_draft",
        "plan_id": f"agent-plan:{task_goal_type}",
        "task_goal_type": task_goal_type,
        "steps": steps,
    }


def test_professional_game_goal_requires_agent_plan_before_execution_steps() -> None:
    bundle = _runtime_bundle(
        ROGUELIKE_PROMPT,
        task_selection={
            "interaction_mode": "professional_mode",
            "runtime_interaction_mode": "professional_mode",
            "mode_policy": {
                "execution_strategy": "professional_task_run",
                "interaction_mode": "professional_mode",
                "runtime_lane": "professional_task",
            },
        },
    )

    current_turn = dict(bundle["current_turn_context"])
    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    metadata = dict(recipe["metadata"])
    semantic_contract = dict(metadata["task_requirement_contract"])
    agent_plan = dict(metadata["agent_plan_draft"])
    coverage = dict(metadata["plan_coverage_review"])
    ids = _step_ids(recipe)

    assert current_turn["task_goal_spec"]["task_goal_type"] == "game_vertical_slice_delivery"
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
    assert metadata["agent_plan_requirement"]["authority"] == "runtime.agent_plan_requirement"
    assert agent_plan["source"] == "agent_plan_required"
    assert agent_plan["steps"] == []
    assert coverage["passed"] is False
    assert coverage["gate_status"] == "blocked_replan_required"
    assert "agent_plan_draft_missing_or_empty" in coverage["required_replan_reason"]
    assert not any(item.startswith("step_execution.") for item in ids)
    assert ids[-1] == "finalization"
    assert metadata["compiled_step_ids"] == ids


def test_frontend_goal_compiles_browser_verification_operations_from_agent_plan() -> None:
    bundle = _runtime_bundle(
        "请重构前端任务图编辑器，做成可运行的编辑器体验，并用浏览器验证关键工作流。",
        task_selection={
            "model_agent_plan_draft": _model_plan(
                task_goal_type="frontend_app_delivery",
                contract_refs=["inspect_code", "apply_real_change", "run_browser_verification", "validate_deliverables"],
                deliverable_refs=["runnable_artifact_refs", "workflow_acceptance", "verification_evidence", "limitations"],
            )
        },
    )

    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    metadata = dict(recipe["metadata"])
    agent_plan = dict(metadata["agent_plan_draft"])
    coverage = dict(metadata["plan_coverage_review"])
    ids = _step_ids(recipe)
    verification = next(item for item in list(recipe["step_blueprints"]) if item["step_id"] == "verification")

    assert recipe["recipe_id"] == "runtime.recipe.professional_task"
    assert recipe["execution_kind"] == "professional_mode"
    assert metadata["semantic_task_type"] == "frontend_app_delivery"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert metadata["agent_plan_requirement"] == {}
    assert agent_plan["task_goal_type"] == "frontend_app_delivery"
    assert agent_plan["source"] == "model_agent_plan_draft"
    assert coverage["passed"] is True
    assert "run_browser_verification" in coverage["covered_actions"]
    assert "step_execution.apply_change" in ids
    assert "step_execution.run_browser_verification" in ids
    assert "op.browser_control" in verification["optional_operations"]


def test_code_fix_goal_compiles_professional_recipe() -> None:
    task_selection = model_turn_context(
        action_intent="edit_workspace",
        work_mode="implementation",
        interaction_intent="modify",
        desired_outcome="修复代码并验证",
        deliverables=["change_summary", "changed_files", "verification_result_or_limitation"],
        planning_required=True,
        todo_required=True,
        task_goal_type="code_fix_execution",
        task_domain="development",
        model_agent_plan_draft=_model_plan(
            task_goal_type="code_fix_execution",
            contract_refs=["read_material", "inspect_code", "apply_real_change", "run_verification", "validate_deliverables"],
            deliverable_refs=["change_summary", "changed_files", "verification_result_or_limitation"],
        ),
    )
    bundle = _runtime_bundle(
        "请修复 backend/app.py 里的一个代码问题，然后运行 pytest 验证。",
        task_selection=task_selection,
    )

    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    metadata = dict(recipe["metadata"])
    ids = _step_ids(recipe)

    assert recipe["recipe_id"] == "runtime.recipe.professional_task"
    assert recipe["execution_kind"] == "professional_mode"
    assert metadata["interaction_mode"] == "professional_mode"
    assert metadata["runtime_lane_hint"] == "professional_task"
    assert metadata["requires_evidence_packet"] is True
    assert "step_execution.inspect_project" in ids
    assert "step_execution.apply_change" in ids
    assert "step_execution.finalize_delivery" in ids


def test_role_mode_uses_lightweight_understanding_steps_without_professional_domain_execution() -> None:
    bundle = _runtime_bundle(
        "陪我聊一下今天的状态。",
        task_selection={
            "interaction_mode": "role_mode",
            "runtime_interaction_mode": "role_mode",
            "mode_policy": {"interaction_mode": "role_mode", "runtime_lane": "role_interaction"},
            **model_turn_context(
                action_intent="answer_only",
                work_mode="conversation",
                interaction_intent="answer",
                desired_outcome="陪用户聊天",
                deliverables=["conversational_response"],
                task_goal_type="role_conversation",
                task_domain="general",
            ),
        },
    )

    recipe = dict(dict(bundle["task_operation"])["selected_recipe"])
    ids = _step_ids(recipe)

    assert recipe["metadata"]["interaction_mode"] == "role_mode"
    assert ids == ["turn_intake", "context_resolution", "prompt_assembly", "finalization"]
    assert not any(item.startswith("step_execution.") for item in ids)
