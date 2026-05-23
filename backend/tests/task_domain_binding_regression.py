from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intent.task_goal_interpreter import build_task_goal_frame
from agent_system.assembly.runtime_bundle_builder import build_orchestration_runtime_bundle
from prompt_library.assembler import assemble_runtime_prompt_contract
from task_system.services.assembly_builder import build_task_execution_assembly_bundle
from task_system.services.assembly_support import build_runtime_task_intent_contract
from understanding.query_understanding import analyze_query_understanding


def test_semantic_contract_carries_task_domain_binding_without_deciding_goal() -> None:
    message = "请先读 backend/app.py，再只改必要代码，最后跑 pytest 验证"
    query = analyze_query_understanding(message)
    goal_frame = build_task_goal_frame(message, query_understanding=asdict(query)).to_dict()
    contract = build_runtime_task_intent_contract(
        session_id="domain-binding-session",
        task_id="domain-binding-task",
        user_goal=message,
        query_understanding=asdict(query),
        current_turn_context={
            "interaction_mode": "professional_mode",
            "task_goal_frame": goal_frame,
        },
    )

    semantic = contract.semantic_task_contract
    binding = semantic["diagnostics"]["task_domain_binding"]

    assert binding["authority"] == "task_system.task_domain_binding"
    assert binding["playbook_role"] == "mature_working_conventions"
    assert binding["user_flow_priority"] == "higher_than_domain_playbook"
    assert binding["diagnostics"]["domain_binding_does_not_decide_goal"] is True
    assert binding["diagnostics"]["domain_binding_must_not_override_user_flow"] is True
    assert semantic["task_goal_type"] == goal_frame["task_goal_type"]


def test_prompt_contract_renders_domain_playbook_as_separate_section() -> None:
    domain_binding = {
        "binding_id": "taskdomainbind:test:domain.development",
        "requested_domain": "development",
        "bound_domain_id": "domain.development",
        "task_family": "development",
        "title": "开发任务域",
        "binding_source": "domain_id",
        "playbook_role": "mature_working_conventions",
        "user_flow_priority": "higher_than_domain_playbook",
        "forbidden_actions_priority": "absolute",
        "default_practices": ["先观察真实代码和项目结构", "保持变更范围受控"],
        "validation_practices": ["能运行测试时运行相关测试"],
        "risk_controls": ["用户禁令优先于开发默认流程"],
        "diagnostics": {"domain_binding_does_not_decide_goal": True},
        "authority": "task_system.task_domain_binding",
    }
    contract = assemble_runtime_prompt_contract(
        base_dir=ROOT.parent,
        task_id="domain-playbook-test",
        user_goal="修正理解系统",
        task_contract={
            "user_goal": "修正理解系统",
            "semantic_task_contract": {
                "contract_id": "semantic-task:test",
                "task_goal_type": "code_fix_execution",
                "domain": "development",
                "diagnostics": {"task_domain_binding": domain_binding},
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

    assert contract["task_understanding_section"] == ""
    section = contract["domain_playbook_section"]
    assert "任务域当作成熟工作制式" in section
    assert "不是用户目标裁判" in section
    assert "先观察真实代码和项目结构" in section
    assert contract["metadata"]["task_domain_binding"]["binding_id"] == "taskdomainbind:test:domain.development"


def test_domain_playbook_section_reaches_soul_runtime_view() -> None:
    message = "请先读 backend/app.py，再只改必要代码，最后跑 pytest 验证"
    query = analyze_query_understanding(message)
    bundle = build_task_execution_assembly_bundle(
        base_dir=ROOT,
        session_id="domain-runtime-session",
        task_id="domain-runtime-task",
        user_goal=message,
        source="test",
        query_understanding=asdict(query),
        current_turn_context={},
    )
    runtime = build_orchestration_runtime_bundle(
        base_dir=ROOT,
        session_id="domain-runtime-session",
        task_id="domain-runtime-task",
        user_goal=message,
        task_assembly_bundle=bundle,
        current_turn_context=bundle["current_turn_context"],
    )
    sections = {
        section["section_id"]: section
        for section in runtime["task_body_orchestration"]["soul_runtime_view"]["sections"]
    }

    assert "domain_playbook_section" in sections
    assert sections["domain_playbook_section"]["source_type"] == "task_domain_binding"
    assert "任务域当作成熟工作制式" in sections["domain_playbook_section"]["content"]
