from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from capability_system.skill_registry import SkillDefinition, SkillRegistry


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
    canonical_path: str = ""

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
    identity_anchor: str = ""
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
    skill_catalog_section: str = ""
    skill_detail_section: str = ""
    resource_section: str = ""
    projection_section: str = ""
    output_section: str = ""
    guardrail_section: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def skill_runtime_views_for_refs(skill_refs: tuple[str, ...]) -> list[SkillRuntimeView]:
    return [
        SkillRuntimeView(
            skill_id=str(skill_ref or "").strip(),
            title=str(skill_ref or "").strip(),
            task_reason="Selected by task binding.",
            method_summary="No expanded skill prompt is exposed by this runtime view.",
        )
        for skill_ref in skill_refs
        if str(skill_ref or "").strip()
    ]


def skill_runtime_views_from_registry(
    *,
    registry: SkillRegistry,
    skill_refs: tuple[str, ...] | list[str],
    task_reason: str = "Candidate capability available for this task.",
) -> list[SkillRuntimeView]:
    views: list[SkillRuntimeView] = []
    seen: set[str] = set()
    for skill_ref in list(skill_refs or []):
        normalized_ref = str(skill_ref or "").strip()
        if not normalized_ref:
            continue
        skill_name = normalized_ref.removeprefix("skill.")
        skill = registry.get_by_name(skill_name)
        if skill is None:
            continue
        skill_id = f"skill.{skill.name}"
        if skill_id in seen:
            continue
        seen.add(skill_id)
        views.append(skill_runtime_view_from_skill_definition(skill, task_reason=task_reason))
    return views


def skill_runtime_view_from_skill_definition(
    skill: SkillDefinition,
    *,
    task_reason: str = "Candidate capability available for this task.",
) -> SkillRuntimeView:
    use_when = str(skill.prompt_view.use_when or "").strip()
    capability = str(skill.prompt_view.capability or skill.description or "").strip()
    output_rule = str(skill.prompt_view.output_rule or "").strip()
    method_parts = [part for part in (capability, use_when, output_rule) if part]
    return SkillRuntimeView(
        skill_id=f"skill.{skill.name}",
        title=str(skill.title or skill.name).strip(),
        task_reason=task_reason,
        method_summary=" ".join(method_parts) or str(skill.description or skill.name).strip(),
        output_boundary=output_rule,
        forbidden_uses=tuple(
            str(item).strip()
            for item in list(skill.forbidden_routes or [])
            if str(item).strip()
        ),
        required_operations=tuple(
            str(item).strip()
            for item in list(skill.requires_operations or [])
            if str(item).strip()
        ),
        canonical_path=str(skill.path or "").strip(),
    )


def render_skill_candidate_cards(skill_runtime_views: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    cards: list[str] = []
    for item in skill_runtime_views or []:
        data = dict(item)
        skill_id = str(data.get("skill_id") or "").strip()
        if not skill_id:
            continue
        lines = [
            f"- skill_id: {skill_id}",
            f"  title: {str(data.get('title') or skill_id).strip()}",
        ]
        capability = str(data.get("method_summary") or "").strip()
        if capability:
            lines.append(f"  capability: {capability}")
        task_reason = str(data.get("task_reason") or "").strip()
        if task_reason:
            lines.append(f"  use_when: {task_reason}")
        input_boundary = str(data.get("input_boundary") or "").strip()
        if input_boundary:
            lines.append(f"  input_boundary: {input_boundary}")
        output_boundary = str(data.get("output_boundary") or "").strip()
        if output_boundary:
            lines.append(f"  output_boundary: {output_boundary}")
        forbidden = [
            str(value).strip()
            for value in list(data.get("forbidden_uses") or [])
            if str(value).strip()
        ]
        if forbidden:
            lines.append(f"  not_for: {', '.join(forbidden)}")
        operations = [
            str(value).strip()
            for value in list(data.get("required_operations") or [])
            if str(value).strip()
        ]
        if operations:
            lines.append(f"  requires_operations: {', '.join(operations)}")
        cards.append("\n".join(lines))
    if not cards:
        return ""
    return "\n".join(
        [
            "候选 Skills（第一阶段）：",
            "这些只是可选能力卡片，不代表已经启用。只有当你在当前轮决策中选择对应 skill_id 后，运行时才会展开完整技能说明。",
            *cards,
        ]
    )


def expand_selected_skill_bodies(
    *,
    base_dir: Path,
    skill_runtime_views: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    selected_skill_ids: list[str] | tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    visible_by_id = {
        str(dict(item).get("skill_id") or "").strip(): dict(item)
        for item in list(skill_runtime_views or [])
        if isinstance(item, dict) and str(dict(item).get("skill_id") or "").strip()
    }
    accepted: list[str] = []
    rejected: list[str] = []
    source_refs: list[str] = []
    blocks: list[str] = []
    for skill_id in _dedupe_skill_ids(selected_skill_ids):
        view = visible_by_id.get(skill_id)
        if view is None:
            rejected.append(skill_id)
            continue
        path = str(view.get("canonical_path") or "").strip()
        if not path:
            rejected.append(skill_id)
            continue
        skill_path = (Path(base_dir) / path).resolve()
        try:
            if not skill_path.is_file():
                rejected.append(skill_id)
                continue
            body = skill_path.read_text(encoding="utf-8").strip()
        except Exception:
            rejected.append(skill_id)
            continue
        accepted.append(skill_id)
        source_refs.append(path)
        blocks.append(
            "\n".join(
                [
                    f"## {skill_id}",
                    body,
                ]
            )
        )
    if not blocks:
        return "", {
            "accepted_skill_ids": accepted,
            "rejected_skill_ids": rejected,
            "source_refs": source_refs,
        }
    return "\n\n".join(
        [
            "已激活 Skills（第二阶段）：",
            "以下完整技能说明只适用于当前轮已选择的 skill_id。按技能说明行动，但不能覆盖用户目标、权限边界和证据要求。",
            *blocks,
        ]
    ), {
        "accepted_skill_ids": accepted,
        "rejected_skill_ids": rejected,
        "source_refs": source_refs,
    }


def _dedupe_skill_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        normalized = item if item.startswith("skill.") else f"skill.{item}"
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


