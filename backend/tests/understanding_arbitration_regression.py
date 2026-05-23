from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intent.task_goal_interpreter import build_task_goal_frame
from intent.task_understanding_frame import build_task_understanding_frame
from prompt_library.assembler import assemble_runtime_prompt_contract
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from task_system.services.assembly_support import build_runtime_task_intent_contract
from understanding.query_understanding import analyze_query_understanding


def test_absent_model_draft_is_recorded_without_model_authority() -> None:
    frame = build_task_understanding_frame(
        "请先读代码，再只改必要部分，最后验证。",
        query_understanding=asdict(analyze_query_understanding("请先读代码，再只改必要部分，最后验证。")),
    ).to_dict()

    arbitration = frame["understanding_arbitration"]
    assert frame["model_understanding_draft_ref"] == ""
    assert arbitration["model_draft_status"] == "absent"
    assert arbitration["diagnostics"]["model_draft_absent"] is True
    assert arbitration["diagnostics"]["model_authority_used"] is False
    assert arbitration["diagnostics"]["deterministic_signals_are_fallback"] is True
    request = frame["model_understanding_request"]
    assert request["authority"] == "intent.model_understanding_request"
    assert request["diagnostics"]["request_contract_only"] is True
    assert request["diagnostics"]["model_call_performed"] is False
    assert "你是一名请求理解裁决员" in request["role_prompt"]
    assert "不负责生成执行步骤" in request["role_prompt"]
    assert frame["conflict_set"] == []


def test_user_forbidden_actions_override_conflicting_model_draft() -> None:
    message = "只分析这个问题，不要修改代码，也不要联网。"
    model_draft = {
        "authority": "intent.model_understanding_draft",
        "draft_id": "modeldraft:conflicting-action",
        "action_intent": "modify",
        "execution_mode_hint": "implementation",
        "task_domain_hint": "development",
        "target_objects": ["代码"],
        "assumption_set": ["用户想要我直接修复代码"],
        "confidence": 0.91,
    }

    frame = build_task_understanding_frame(
        message,
        query_understanding=asdict(analyze_query_understanding(message)),
        model_understanding_draft=model_draft,
    ).to_dict()

    conflicts = frame["conflict_set"]
    assert frame["action_intent"] == "answer"
    assert frame["execution_mode_hint"] == "analysis_only"
    assert "modify_workspace" in frame["forbidden_actions"]
    assert "network_lookup" in frame["forbidden_actions"]
    assert frame["understanding_arbitration"]["model_draft_status"] == "accepted"
    assert frame["understanding_arbitration"]["diagnostics"]["model_authority_used"] is True
    assert any(item["reason"] == "model_action_conflicts_with_user_forbidden_workspace_change" for item in conflicts)
    assert frame["assumption_set"] == ["用户想要我直接修复代码"]


def test_goal_domain_hints_override_model_draft_and_record_conflict() -> None:
    message = "请继续推进理解系统。"
    model_draft = {
        "authority": "intent.model_understanding_draft",
        "draft_id": "modeldraft:wrong-domain",
        "task_domain_hint": "writing",
        "task_goal_type_hint": "material_synthesis",
        "interaction_intent": "continue_task",
        "action_intent": "modify",
        "confidence": 0.8,
    }

    frame = build_task_understanding_frame(
        message,
        query_understanding=asdict(analyze_query_understanding(message)),
        task_domain_hint="development",
        task_goal_type_hint="code_fix_execution",
        model_understanding_draft=model_draft,
    ).to_dict()

    conflicts = frame["conflict_set"]
    assert frame["task_domain_hint"] == "development"
    assert frame["task_goal_type_hint"] == "code_fix_execution"
    assert any(
        item["field"] == "task_domain_hint"
        and item["reason"] == "model_conflicts_with_authoritative_hint"
        for item in conflicts
    )
    assert any(
        item["field"] == "task_goal_type_hint"
        and item["reason"] == "model_conflicts_with_authoritative_hint"
        for item in conflicts
    )


def test_semantic_contract_and_prompt_carry_understanding_arbitration() -> None:
    message = "只分析理解系统，不要修改代码。"
    model_draft = {
        "authority": "intent.model_understanding_draft",
        "draft_id": "modeldraft:semantic-contract",
        "action_intent": "modify",
        "execution_mode_hint": "implementation",
        "confidence": 0.74,
    }
    query = analyze_query_understanding(message)
    goal_frame = build_task_goal_frame(
        message,
        query_understanding=asdict(query),
        model_understanding_draft=model_draft,
    ).to_dict()
    contract = build_runtime_task_intent_contract(
        session_id="understanding-arbitration-session",
        task_id="understanding-arbitration-task",
        user_goal=message,
        query_understanding=asdict(query),
        current_turn_context={"task_goal_frame": goal_frame},
    )

    semantic = contract.semantic_task_contract
    arbitration = semantic["diagnostics"]["understanding_arbitration"]
    model_request = semantic["diagnostics"]["model_understanding_request"]
    assert arbitration["model_draft_ref"] == "modeldraft:semantic-contract"
    assert arbitration["conflict_set"]
    assert model_request["diagnostics"]["model_call_performed"] is False

    prompt = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="understanding-arbitration-task",
        user_goal=message,
        task_contract={
            "user_goal": message,
            "semantic_task_contract": semantic,
            "mode_policy": {"interaction_mode": "professional_mode"},
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "metadata": {}},
        task_spec={"inputs": {}},
        selected_recipe={"recipe_id": "runtime.recipe.professional_task", "metadata": {}},
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        projection_requirement={},
        operation_requirement={},
        active_skill={},
        agent_id="agent:0",
        current_turn_context={},
    )

    assert prompt["metadata"]["understanding_arbitration"]["model_draft_ref"] == "modeldraft:semantic-contract"
    assert prompt["metadata"]["model_understanding_request"]["diagnostics"]["request_contract_only"] is True
    assert "理解冲突已记录" in prompt["task_understanding_section"]


def test_assembly_builder_passes_model_understanding_draft_into_goal_frame() -> None:
    message = "只分析理解系统，不要修改代码。"
    bundle = build_task_execution_assembly_bundle(
        base_dir=ROOT,
        session_id="understanding-arbitration-bundle",
        task_id="understanding-arbitration-bundle-task",
        user_goal=message,
        source="test",
        query_understanding=asdict(analyze_query_understanding(message)),
        current_turn_context={
            "model_understanding_draft": {
                "authority": "intent.model_understanding_draft",
                "draft_id": "modeldraft:assembly-builder",
                "action_intent": "modify",
                "execution_mode_hint": "implementation",
                "confidence": 0.76,
            },
        },
    )

    goal_frame = dict(bundle["current_turn_context"]["task_goal_frame"])
    understanding = dict(goal_frame["task_understanding_frame"])
    assert understanding["understanding_arbitration"]["model_draft_ref"] == "modeldraft:assembly-builder"
    assert understanding["conflict_set"]
