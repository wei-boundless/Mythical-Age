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
from understanding.query_understanding import analyze_query_understanding


def test_universal_understanding_frame_preserves_user_flow_and_domain_playbook_boundary() -> None:
    message = "先读 backend/app.py，再检查路由，然后只改必要代码，最后跑 pytest 验证"
    query = analyze_query_understanding(message)
    frame = build_task_understanding_frame(message, query_understanding=asdict(query))
    payload = frame.to_dict()

    assert payload["task_domain_hint"] == "development"
    assert payload["communication_frame_ref"].startswith("communication:")
    assert payload["communication_frame"]["collaboration_mode"] == "long_task"
    assert payload["communication_frame"]["progress_policy"] == "todo_required"
    assert payload["action_intent"] in {"modify", "inspect"}
    assert payload["user_provided_flow"]
    assert payload["playbook_policy"]["user_flow_priority"] == "higher_than_domain_playbook"
    assert payload["playbook_policy"]["agent_generates_concrete_steps"] is True
    assert payload["understanding_arbitration"]["model_draft_status"] == "absent"
    assert payload["understanding_arbitration"]["diagnostics"]["model_draft_absent"] is True
    assert payload["understanding_arbitration"]["diagnostics"]["model_authority_used"] is False


def test_task_goal_frame_carries_task_understanding_frame() -> None:
    message = "请先为理解系统写方案，再实现必要代码"
    query = analyze_query_understanding(message)
    goal_frame = build_task_goal_frame(message, query_understanding=asdict(query)).to_dict()

    understanding = goal_frame["task_understanding_frame"]
    assert goal_frame["task_understanding_frame_ref"].startswith("understanding:")
    assert understanding["communication_frame"]["agent_posture"] in {"execute", "plan_first"}
    assert understanding["interaction_intent"] in {"plan", "execute"}
    assert understanding["task_domain_hint"] in {"development", "general", "conversation"}
    assert understanding["playbook_policy"]["domain_playbook_role"] == "mature_working_conventions"
    assert understanding["understanding_arbitration_ref"].startswith("understanding-arbitration:")


def test_prompt_contract_renders_task_understanding_section() -> None:
    understanding = {
        "frame_id": "understanding:test",
        "interaction_intent": "execute",
        "action_intent": "modify",
        "target_objects": ["理解系统"],
        "desired_outcomes": ["real_workspace_change"],
        "explicit_constraints": ["先", "最后"],
        "forbidden_actions": [],
        "user_provided_flow": ["先读代码", "最后验证"],
        "context_binding": {"kind": "current_turn", "source": "user_message"},
        "execution_mode_hint": "implementation",
        "task_domain_hint": "development",
        "task_goal_type_hint": "code_fix_execution",
        "evidence_requirements": ["workspace_observation", "verification_or_limitation"],
        "playbook_policy": {"user_flow_priority": "higher_than_domain_playbook"},
        "understanding_arbitration": {
            "arbitration_id": "understanding-arbitration:test",
            "model_draft_status": "absent",
            "diagnostics": {"model_draft_absent": True, "model_authority_used": False},
        },
        "communication_frame": {
            "frame_id": "communication:test",
            "user_posture": "execute",
            "agent_posture": "execute",
            "collaboration_mode": "implementation",
            "clarification_policy": "no_clarification_needed",
            "progress_policy": "brief_updates",
            "final_response_contract": "implementation_report",
        },
    }
    contract = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="task-understanding-test",
        user_goal="修正理解系统",
        task_contract={
            "user_goal": "修正理解系统",
            "semantic_task_contract": {
                "contract_id": "semantic-task:test",
                "task_goal_type": "code_fix_execution",
                "domain": "development",
                "diagnostics": {"task_understanding_frame": understanding},
            },
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

    section = contract["task_understanding_section"]
    assert "如何被承接" in section
    assert "交流承接" in section
    assert "用户真实目标" in section
    assert "用户明确流程" in section
    assert "任务域只提供成熟工作习惯" in section
    assert "没有真实模型理解草稿" in section
    assert "agent_todo" not in section
    assert "todo 是执行状态" not in section
    assert contract["metadata"]["task_understanding_frame"]["frame_id"] == "understanding:test"
    assert contract["metadata"]["understanding_arbitration"]["arbitration_id"] == "understanding-arbitration:test"
    assert contract["metadata"]["communication_frame"]["frame_id"] == "communication:test"


def test_agent_todo_guidance_lives_in_execution_plan_section() -> None:
    contract = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="task-understanding-test",
        user_goal="修正理解系统",
        task_contract={
            "user_goal": "修正理解系统",
            "semantic_task_contract": {
                "contract_id": "semantic-task:test",
                "task_goal_type": "code_fix_execution",
                "domain": "development",
            },
            "mode_policy": {"interaction_mode": "professional_mode"},
        },
        task_execution_assembly={"task_family": "runtime", "task_mode": "professional_mode", "metadata": {}},
        task_spec={"inputs": {}},
        selected_recipe={
            "recipe_id": "runtime.recipe.professional_task",
            "metadata": {
                "agent_plan_draft": {
                    "plan_id": "agent-plan:test",
                    "steps": [
                        {"step_id": "inspect", "title": "Inspect", "purpose": "Read current code"},
                        {"step_id": "change", "title": "Change", "purpose": "Patch required code"},
                    ],
                }
            },
        },
        task_workflow={},
        binding={},
        registered_task={},
        skill_runtime_views=[],
        projection_requirement={},
        operation_requirement={"optional_operations": ["op.agent_todo"]},
        active_skill={},
        agent_id="agent:0",
        current_turn_context={},
    )

    section = contract["agent_plan_section"]
    assert "agent_todo" in section
    assert "todo 只是执行状态" in section
