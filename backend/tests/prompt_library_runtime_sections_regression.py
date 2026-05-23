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


def test_runtime_sections_hide_projection_section_outside_role_mode() -> None:
    sections = assemble_runtime_prompt_sections(
        base_dir=Path("backend"),
        contract={
            "contract_id": "orchprompt:task-runtime",
            "task_id": "task-runtime",
            "task_section": "任务契约",
            "semantic_task_section": "语义任务契约",
            "goal_understanding_section": "",
            "domain_playbook_section": "你是一名前端产品交付负责人。",
            "node_professional_prompt_section": "你只负责当前节点实现。",
            "professional_profile_section": "你需要真实完成执行义务。",
            "agent_plan_section": "执行计划草案",
            "plan_coverage_section": "计划覆盖审查",
            "completion_judgment_section": "完成裁决",
            "mode_policy_section": "当前交互模式：professional_mode。",
            "workflow_section": "工作流",
            "projection_section": "当前表达姿态：task_default。",
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
    assert "domain_playbook_section" in ids
    assert "mode_policy_section" in ids


def test_runtime_sections_keep_projection_section_in_role_mode() -> None:
    sections = assemble_runtime_prompt_sections(
        base_dir=Path("backend"),
        contract={
            "contract_id": "orchprompt:task-runtime",
            "task_id": "task-runtime",
            "task_section": "任务契约",
            "semantic_task_section": "",
            "goal_understanding_section": "",
            "domain_playbook_section": "",
            "node_professional_prompt_section": "",
            "professional_profile_section": "",
            "agent_plan_section": "",
            "plan_coverage_section": "",
            "completion_judgment_section": "",
            "mode_policy_section": "当前交互模式：role_mode。",
            "workflow_section": "",
            "projection_section": "当前表达姿态：chapter_drafting。",
            "output_section": "输出边界",
            "metadata": {
                "prompt_selection_context": {"interaction_mode": "role_mode"},
                "mode_policy": {"interaction_mode": "role_mode"},
            },
        },
        projection={"task_id": "task-runtime", "identity_anchor": "你是长篇正文执行投影。"},
        request=_request(),
        soul_skill_views=(),
        soul_tool_views=(),
        use_shared_contract=False,
    )

    projection_section = next(section for section in sections if section.section_id == "projection_section")
    assert projection_section.owner_layer == "projection"
    assert "你是长篇正文执行投影。" in projection_section.content
