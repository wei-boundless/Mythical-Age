from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from capability_system.skills.registry import SkillDefinition, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillRuntimeView:
    skill_id: str
    title: str
    capability: str
    use_when: str = ""
    not_for: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    capability_tags: tuple[str, ...] = ()
    preferred_capability_group: str = ""
    activation_mode: str = "candidate"
    selection_hint: str = ""
    supported_task_kinds: tuple[str, ...] = ()
    supported_source_kinds: tuple[str, ...] = ()
    canonical_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def skill_runtime_views_for_refs(skill_refs: tuple[str, ...]) -> list[SkillRuntimeView]:
    return [
        SkillRuntimeView(
            skill_id=str(skill_ref or "").strip(),
            title=str(skill_ref or "").strip(),
            capability="该 skill 由任务合同显式绑定；运行时只展示候选卡片，完整说明在激活后展开。",
        )
        for skill_ref in skill_refs
        if str(skill_ref or "").strip()
    ]


def skill_runtime_views_from_registry(
    *,
    registry: SkillRegistry,
    skill_refs: tuple[str, ...] | list[str],
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
        views.append(skill_runtime_view_from_skill_definition(skill))
    return views


def skill_runtime_view_from_skill_definition(skill: SkillDefinition) -> SkillRuntimeView:
    use_when = str(skill.prompt_view.use_when or "").strip()
    capability = str(skill.prompt_view.capability or skill.description or "").strip()
    capability_tags = tuple(
        str(item).strip()
        for item in list(getattr(skill.runtime, "capability_tags", ()) or [])
        if str(item).strip()
    )
    required_operations = tuple(
        str(item).strip()
        for item in list(skill.requires_operations or [])
        if str(item).strip()
    )
    return SkillRuntimeView(
        skill_id=f"skill.{skill.name}",
        title=str(skill.title or skill.name).strip(),
        capability=capability or str(skill.description or skill.name).strip(),
        use_when=use_when,
        not_for=tuple(
            str(item).strip()
            for item in list(getattr(skill, "not_for", ()) or [])
            if str(item).strip()
        ),
        required_operations=required_operations,
        capability_tags=capability_tags,
        preferred_capability_group=_preferred_capability_group(
            capability_tags=capability_tags,
            required_operations=required_operations,
            preferred_route=str(getattr(skill.runtime, "preferred_route", "") or ""),
        ),
        activation_mode="candidate",
        selection_hint="选择后运行时才会展开完整 skill 说明。",
        supported_task_kinds=tuple(
            str(item).strip()
            for item in list(getattr(skill.runtime, "supported_task_kinds", ()) or [])
            if str(item).strip()
        ),
        supported_source_kinds=tuple(
            str(item).strip()
            for item in list(getattr(skill.runtime, "supported_source_kinds", ()) or [])
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
        capability = str(data.get("capability") or "").strip()
        if capability:
            lines.append(f"  capability: {capability}")
        use_when = str(data.get("use_when") or "").strip()
        if use_when:
            lines.append(f"  use_when: {use_when}")
        forbidden = [
            str(value).strip()
            for value in list(data.get("not_for") or [])
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
        group = str(data.get("preferred_capability_group") or "").strip()
        if group:
            lines.append(f"  capability_group: {group}")
        tags = [
            str(value).strip()
            for value in list(data.get("capability_tags") or [])
            if str(value).strip()
        ]
        if tags:
            lines.append(f"  capability_tags: {', '.join(tags)}")
        selection_hint = str(data.get("selection_hint") or "").strip()
        if selection_hint:
            lines.append(f"  selection_hint: {selection_hint}")
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
            body = _model_visible_skill_body(skill_path.read_text(encoding="utf-8"))
        except Exception:
            rejected.append(skill_id)
            continue
        if not body:
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


def _preferred_capability_group(
    *,
    capability_tags: tuple[str, ...],
    required_operations: tuple[str, ...],
    preferred_route: str,
) -> str:
    tokens = {
        *(item.lower() for item in capability_tags),
        *(item.lower() for item in required_operations),
        str(preferred_route or "").strip().lower(),
    }
    if {"browser", "browser_control", "web_automation", "op.browser_control"}.intersection(tokens):
        return "browser_use"
    if {"web_research", "deep_search", "source_verification", "op.web_search", "op.fetch_url"}.intersection(tokens):
        return "web_research"
    if {"image_generation", "visual_prompt", "op.image_generate"}.intersection(tokens):
        return "artifact_generation"
    if {"subagent", "subagent_delegation", "op.subagent_spawn"}.intersection(tokens):
        return "subagent_delegation"
    if {"file_work", "code", "op.read_file", "op.search_text", "op.write_file", "op.edit_file"}.intersection(tokens):
        return "file_work"
    return "general_task"


def _model_visible_skill_body(text: str) -> str:
    content = str(text or "").strip()
    if not content.startswith("---"):
        return content
    lines = content.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return content


