from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillRuntimeView:
    skill_id: str
    title: str
    task_reason: str
    method_summary: str
    input_boundary: str = ""
    output_boundary: str = ""
    forbidden_uses: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProjectionRequirement:
    task_id: str
    role_type: str
    posture_tags: tuple[str, ...] = ()
    expression_density: str = "normal"
    attention_focus: tuple[str, ...] = ()
    projection_id: str = ""
    soul_id: str = ""
    projection_title: str = ""
    projection_prompt: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskPromptContract:
    contract_id: str
    task_id: str
    definition_id: str
    binding_id: str
    task_section: str
    workflow_section: str
    resource_section: str
    projection_section: str
    output_section: str
    guardrail_section: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def skill_runtime_views_for_refs(skill_refs: tuple[str, ...]) -> list[SkillRuntimeView]:
    views = []
    for skill_ref in skill_refs:
        views.append(_skill_view(skill_ref))
    return views


def _skill_view(skill_ref: str) -> SkillRuntimeView:
    mapping = {
        "skill.web_search": SkillRuntimeView(
            skill_id="skill.web_search",
            title="Web source search",
            task_reason="The task asks for external or current information.",
            method_summary="Search, fetch, compare sources, and keep source traceability.",
            output_boundary="Evidence summaries and source gaps.",
            required_operations=("op.web_search", "op.fetch_url"),
        ),
        "skill.evidence_summary": SkillRuntimeView(
            skill_id="skill.evidence_summary",
            title="Evidence summary",
            task_reason="Search results need traceable synthesis.",
            method_summary="Separate claims, evidence, dates, and uncertainty.",
        ),
        "skill.local_read": SkillRuntimeView(
            skill_id="skill.local_read",
            title="Local material reading",
            task_reason="The task depends on local files or docs.",
            method_summary="Read only task-relevant local material and preserve file boundaries.",
            required_operations=("op.read_file", "op.search_files"),
        ),
        "skill.synthesis": SkillRuntimeView(
            skill_id="skill.synthesis",
            title="Structured synthesis",
            task_reason="Read material must be condensed into an answer.",
            method_summary="Summarize grounded facts without expanding beyond supplied material.",
            required_operations=("op.search_text",),
        ),
        "skill.implementation": SkillRuntimeView(
            skill_id="skill.implementation",
            title="Bounded implementation",
            task_reason="The task asks for a change or staged edit.",
            method_summary="Prepare scoped implementation steps and keep side effects gated.",
            required_operations=("op.read_file", "op.search_text", "op.edit_file"),
        ),
        "skill.review": SkillRuntimeView(
            skill_id="skill.review",
            title="Risk review",
            task_reason="The task requires inspection and contradiction checks.",
            method_summary="Check consistency, risk, missing tests, and boundary violations.",
            required_operations=("op.read_file", "op.search_text"),
        ),
    }
    return mapping.get(
        skill_ref,
        SkillRuntimeView(
            skill_id=skill_ref,
            title=skill_ref,
            task_reason="Selected by task binding.",
            method_summary="No expanded skill prompt is exposed by this runtime view.",
        ),
    )
