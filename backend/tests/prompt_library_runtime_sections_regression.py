from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_library.runtime_sections import assemble_runtime_prompt_sections


def _request() -> SimpleNamespace:
    return SimpleNamespace(task_id="task-runtime")


def test_runtime_sections_never_emit_projection_section() -> None:
    sections = assemble_runtime_prompt_sections(
        base_dir=Path("backend"),
        contract={
            "contract_id": "orchprompt:task-runtime",
            "task_id": "task-runtime",
            "task_section": "任务契约",
            "semantic_task_section": "语义任务契约",
            "goal_understanding_section": "",
            "task_goal_role_prompt_section": "你是一名前端产品交付负责人。",
            "node_professional_prompt_section": "你只负责当前节点实现。",
            "professional_profile_section": "你需要真实完成执行义务。",
            "agent_plan_section": "执行计划草案",
            "plan_coverage_section": "计划覆盖审查",
            "completion_judgment_section": "完成裁决",
            "mode_policy_section": "当前交互模式：professional_mode。",
            "workflow_section": "工作流",
            "output_section": "输出边界",
            "metadata": {
                "prompt_selection_context": {"interaction_mode": "professional_mode"},
                "mode_policy": {"interaction_mode": "professional_mode"},
            },
        },
        projection={"task_id": "task-runtime", "identity_anchor": "你是执行投影。"},
        request=_request(),
        soul_skill_views=(),
        soul_tool_views=(),
        use_shared_contract=False,
    )

    ids = {section.section_id for section in sections}
    assert "projection_section" not in ids
    assert "task_goal_role_prompt_section" in ids
    assert "domain_playbook_section" not in ids
    assert "mode_policy_section" in ids


def test_runtime_sections_emit_skill_catalog_and_detail_separately() -> None:
    skill_view = SimpleNamespace(skill_id="skill.image-prompt-design")
    sections = assemble_runtime_prompt_sections(
        base_dir=Path("backend"),
        contract={
            "contract_id": "orchprompt:task-runtime",
            "task_id": "task-runtime",
            "task_section": "任务契约",
            "semantic_task_section": "",
            "goal_understanding_section": "",
            "task_goal_role_prompt_section": "",
            "node_professional_prompt_section": "",
            "professional_profile_section": "",
            "agent_plan_section": "",
            "plan_coverage_section": "",
            "completion_judgment_section": "",
            "mode_policy_section": "当前交互模式：professional_mode。",
            "workflow_section": "",
            "skill_catalog_section": "候选 Skills（第一阶段）\n- skill_id: skill.image-prompt-design",
            "skill_detail_section": "已激活 Skills（第二阶段）\n## skill.image-prompt-design",
            "output_section": "输出边界",
            "metadata": {
                "prompt_selection_context": {"interaction_mode": "professional_mode"},
                "mode_policy": {"interaction_mode": "professional_mode"},
                "activated_skill_ids": ["skill.image-prompt-design"],
                "skill_detail_source_refs": ["capability_system/units/skills/image-prompt-design/SKILL.md"],
            },
        },
        projection={"task_id": "task-runtime"},
        request=_request(),
        soul_skill_views=(skill_view,),
        soul_tool_views=(),
        use_shared_contract=False,
    )

    by_id = {section.section_id: section for section in sections}
    assert by_id["skill_catalog_section"].candidate_refs == ("skill.image-prompt-design",)
    assert by_id["skill_detail_section"].candidate_refs == ("skill.image-prompt-design",)
    assert by_id["skill_detail_section"].source_refs == ("capability_system/units/skills/image-prompt-design/SKILL.md",)


def test_runtime_sections_ignore_legacy_domain_playbook_even_when_present() -> None:
    sections = assemble_runtime_prompt_sections(
        base_dir=Path("backend"),
        contract={
            "contract_id": "orchprompt:task-runtime",
            "task_id": "task-runtime",
            "task_section": "任务契约",
            "semantic_task_section": "",
            "goal_understanding_section": "",
            "domain_playbook_section": "你在该任务领域中的职责是：旧域制式。",
            "task_goal_role_prompt_section": "你是一名前端产品交付负责人。",
            "node_professional_prompt_section": "",
            "professional_profile_section": "",
            "agent_plan_section": "",
            "plan_coverage_section": "",
            "completion_judgment_section": "",
            "mode_policy_section": "当前交互模式：professional_mode。",
            "workflow_section": "",
            "output_section": "输出边界",
            "metadata": {
                "prompt_selection_context": {"interaction_mode": "professional_mode"},
                "mode_policy": {"interaction_mode": "professional_mode"},
                "task_domain_binding": {"binding_id": "taskdomainbind:legacy"},
            },
        },
        projection={"task_id": "task-runtime"},
        request=_request(),
        soul_skill_views=(),
        soul_tool_views=(),
        use_shared_contract=False,
    )

    by_id = {section.section_id: section for section in sections}
    rendered = "\n".join(section.content for section in sections)

    assert "domain_playbook_section" not in by_id
    assert "task_domain_binding" not in rendered
    assert "旧域制式" not in rendered
    assert "你是一名前端产品交付负责人。" in by_id["task_goal_role_prompt_section"].content
