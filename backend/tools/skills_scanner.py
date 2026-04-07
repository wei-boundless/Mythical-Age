from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


@dataclass
class SkillRecord:
    name: str
    title: str
    description: str
    path: str
    allowed_tools: list[str] = field(default_factory=list)
    supported_modalities: list[str] = field(default_factory=list)
    supported_task_kinds: list[str] = field(default_factory=list)
    supported_source_kinds: list[str] = field(default_factory=list)
    capability_tags: list[str] = field(default_factory=list)
    preferred_route: str = "rag"
    forbidden_routes: list[str] = field(default_factory=list)
    routing_hints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    reference_paths: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1)) or {}
    return data if isinstance(data, dict) else {}


def _coerce_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_coerce_str(item) for item in value if _coerce_str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _lookup(meta: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = meta
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return default
        current = current[segment]
    return current


def _read_skill_body_without_frontmatter(text: str) -> str:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return text
    return text[match.end() :].strip()


def _extract_description(meta: dict[str, Any], body: str, skill_dir_name: str) -> str:
    description = _coerce_str(meta.get("description"))
    if description:
        return description
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if lines:
        return lines[0].lstrip("# ").strip()
    return f"{skill_dir_name} skill"


def _collect_reference_paths(base_dir: Path, skill_dir: Path) -> list[str]:
    references_dir = skill_dir / "references"
    if not references_dir.exists():
        return []
    paths: list[str] = []
    for file in sorted(references_dir.rglob("*")):
        if not file.is_file():
            continue
        paths.append(str(file.relative_to(base_dir)).replace("\\", "/"))
    return paths


def scan_skills(base_dir: Path) -> list[SkillRecord]:
    skills_dir = base_dir / "skills"
    records: list[SkillRecord] = []
    if not skills_dir.exists():
        return records

    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
        body = _read_skill_body_without_frontmatter(text)
        metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        skill_dir = skill_file.parent

        title = (
            _coerce_str(metadata.get("display_name"))
            or _coerce_str(metadata.get("title"))
            or _coerce_str(meta.get("name"))
            or skill_dir.name
        )
        description = _extract_description(meta, body, skill_dir.name)

        records.append(
            SkillRecord(
                name=_coerce_str(meta.get("name"), skill_dir.name),
                title=title,
                description=description,
                path=str(skill_file.relative_to(base_dir)).replace("\\", "/"),
                allowed_tools=_coerce_list(_lookup(meta, "metadata.allowed_tools")),
                supported_modalities=_coerce_list(_lookup(meta, "metadata.supported_modalities")),
                supported_task_kinds=_coerce_list(_lookup(meta, "metadata.supported_task_kinds")),
                supported_source_kinds=_coerce_list(_lookup(meta, "metadata.supported_source_kinds")),
                capability_tags=_coerce_list(_lookup(meta, "metadata.capability_tags")),
                preferred_route=_coerce_str(_lookup(meta, "metadata.preferred_route"), "rag") or "rag",
                forbidden_routes=_coerce_list(_lookup(meta, "metadata.forbidden_routes")),
                routing_hints=_coerce_list(_lookup(meta, "metadata.routing_hints")),
                examples=_coerce_list(_lookup(meta, "metadata.examples")),
                reference_paths=_collect_reference_paths(base_dir, skill_dir),
            )
        )
    return records


def build_snapshot(skills: list[SkillRecord]) -> str:
    lines = [
        "<skills>",
        "  <summary>Available local workflow contracts. Skills constrain which task kinds they serve and which tools they may invoke.</summary>",
    ]
    for skill in skills:
        lines.extend(
            [
                f'  <skill name="{skill.title}" id="{skill.name}" path="{skill.path}">',
                f"    <description>{skill.description}</description>",
                f"    <preferred_route>{skill.preferred_route}</preferred_route>",
            ]
        )
        if skill.supported_modalities:
            lines.append(f"    <modalities>{', '.join(skill.supported_modalities)}</modalities>")
        if skill.supported_source_kinds:
            lines.append(f"    <source_kinds>{', '.join(skill.supported_source_kinds)}</source_kinds>")
        if skill.supported_task_kinds:
            lines.append(f"    <task_kinds>{', '.join(skill.supported_task_kinds)}</task_kinds>")
        if skill.allowed_tools:
            lines.append(f"    <allowed_tools>{', '.join(skill.allowed_tools)}</allowed_tools>")
        if skill.capability_tags:
            lines.append(f"    <capability_tags>{', '.join(skill.capability_tags)}</capability_tags>")
        if skill.routing_hints:
            lines.append(f"    <routing_hints>{', '.join(skill.routing_hints[:6])}</routing_hints>")
        if skill.forbidden_routes:
            lines.append(f"    <forbidden_routes>{', '.join(skill.forbidden_routes)}</forbidden_routes>")
        if skill.reference_paths:
            lines.append(f"    <references>{', '.join(skill.reference_paths)}</references>")
        lines.append("  </skill>")
    lines.append("</skills>")
    return "\n".join(lines) + "\n"


def build_registry(skills: list[SkillRecord]) -> dict[str, Any]:
    return {
        "version": 2,
        "skill_count": len(skills),
        "skills": [asdict(skill) for skill in skills],
    }


def refresh_snapshot(base_dir: Path) -> Path:
    skills = scan_skills(base_dir)
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"
    registry_path = base_dir / "SKILLS_REGISTRY.json"
    snapshot_path.write_text(build_snapshot(skills), encoding="utf-8")
    registry_path.write_text(
        json.dumps(build_registry(skills), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot_path
