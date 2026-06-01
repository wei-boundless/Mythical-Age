from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.skills.contracts import (
    DEFAULT_SKILL_OUTPUT_RULE,
    SkillContract,
    SkillPromptContract,
    SkillRuntimeContract,
)
from capability_system.skills.paths import CapabilitySkillPaths

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
SECTION_HEADING_PATTERN = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)
FENCED_CODE_PATTERN = re.compile(r"```.*?```", re.DOTALL)


@dataclass
class SkillRecord:
    name: str
    title: str
    description: str
    path: str
    supported_modalities: list[str] = field(default_factory=list)
    supported_task_kinds: list[str] = field(default_factory=list)
    supported_source_kinds: list[str] = field(default_factory=list)
    capability_tags: list[str] = field(default_factory=list)
    preferred_route: str = ""
    forbidden_routes: list[str] = field(default_factory=list)
    not_for: list[str] = field(default_factory=list)
    routing_hints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    activation_policy: str = "model_visible"
    context_mode: str = "inline"
    route_authority: str = "candidate_only"
    reference_paths: list[str] = field(default_factory=list)
    requires_operations: list[str] = field(default_factory=list)
    requires_capabilities: list[str] = field(default_factory=list)
    prompt_use_when: str = ""
    prompt_subagent_handoff_protocol: str = ""
    prompt_return_protocol: str = ""
    prompt_output_rule: str = ""
    schema_version: int = 3
    validation_errors: list[str] = field(default_factory=list)


def _record_from_contract(contract: SkillContract) -> SkillRecord:
    runtime = contract.runtime
    return SkillRecord(
        name=runtime.name,
        title=runtime.title,
        description=runtime.description,
        path=runtime.path,
        supported_modalities=list(runtime.supported_modalities),
        supported_task_kinds=list(runtime.supported_task_kinds),
        supported_source_kinds=list(runtime.supported_source_kinds),
        capability_tags=list(runtime.capability_tags),
        preferred_route=runtime.preferred_route,
        forbidden_routes=list(runtime.forbidden_routes),
        not_for=list(runtime.not_for),
        routing_hints=list(runtime.routing_hints),
        examples=list(runtime.examples),
        activation_policy=runtime.activation_policy,
        context_mode=runtime.context_mode,
        route_authority=runtime.route_authority,
        reference_paths=list(runtime.reference_paths),
        requires_operations=list(runtime.requires_operations),
        requires_capabilities=list(runtime.requires_capabilities),
        prompt_use_when=contract.prompt.use_when,
        prompt_subagent_handoff_protocol=contract.prompt.subagent_handoff_protocol,
        prompt_return_protocol=contract.prompt.return_protocol,
        prompt_output_rule=contract.prompt.output_rule,
        validation_errors=list(contract.validation_errors),
    )


def _contract_from_record(record: SkillRecord, *, body: str = "") -> SkillContract:
    prompt = _prompt_payload_from_record(record, body)
    contract = SkillContract.from_runtime(
        SkillRuntimeContract(
            name=record.name,
            title=record.title,
            description=record.description,
            path=record.path,
            supported_modalities=record.supported_modalities,
            supported_task_kinds=record.supported_task_kinds,
            supported_source_kinds=record.supported_source_kinds,
            capability_tags=record.capability_tags,
            preferred_route=record.preferred_route,
            forbidden_routes=record.forbidden_routes,
            not_for=record.not_for,
            routing_hints=record.routing_hints,
            examples=record.examples,
            activation_policy=record.activation_policy,
            context_mode=record.context_mode,
            route_authority=record.route_authority,
            reference_paths=record.reference_paths,
            requires_operations=record.requires_operations,
            requires_capabilities=record.requires_capabilities,
        ),
        body=body,
        use_when=prompt.get("use_when", ""),
        subagent_handoff_protocol=prompt.get("subagent_handoff_protocol", ""),
        return_protocol=prompt.get("return_protocol", ""),
        output_rule=prompt.get("output_rule", ""),
    )
    return contract


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
    paths_helper = CapabilitySkillPaths.from_base_dir(base_dir)
    references_dir = skill_dir / "references"
    if not references_dir.exists():
        return []
    paths: list[str] = []
    for file in sorted(references_dir.rglob("*")):
        if not file.is_file():
            continue
        paths.append(paths_helper.to_relative_path(file))
    return paths


def scan_skills(base_dir: Path) -> list[SkillRecord]:
    paths = CapabilitySkillPaths.from_base_dir(base_dir)
    skills_dir = paths.skills_dir
    records: list[SkillRecord] = []
    if not skills_dir.exists():
        return records

    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
        body = _read_skill_body_without_frontmatter(text)
        metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
        prompt_meta = meta.get("prompt") if isinstance(meta.get("prompt"), dict) else meta.get("prompt_view")
        if not isinstance(prompt_meta, dict):
            prompt_meta = {}
        skill_dir = skill_file.parent

        title = (
            _coerce_str(metadata.get("display_name"))
            or _coerce_str(metadata.get("title"))
            or _coerce_str(meta.get("name"))
            or skill_dir.name
        )
        description = _extract_description(meta, body, skill_dir.name)

        record = SkillRecord(
            name=_coerce_str(meta.get("name"), skill_dir.name),
            title=title,
            description=description,
            path=paths.to_relative_path(skill_file),
            supported_modalities=_coerce_list(_lookup(meta, "metadata.supported_modalities")),
            supported_task_kinds=_coerce_list(_lookup(meta, "metadata.supported_task_kinds")),
            supported_source_kinds=_coerce_list(_lookup(meta, "metadata.supported_source_kinds")),
            capability_tags=_coerce_list(_lookup(meta, "metadata.capability_tags")),
            preferred_route=_coerce_str(_lookup(meta, "metadata.preferred_route")),
            forbidden_routes=_coerce_list(_lookup(meta, "metadata.forbidden_routes")),
            not_for=_coerce_list(_lookup(meta, "metadata.not_for") or _lookup(meta, "metadata.forbidden_uses")),
            routing_hints=_coerce_list(_lookup(meta, "metadata.routing_hints")),
            examples=_coerce_list(_lookup(meta, "metadata.examples")),
            activation_policy=_coerce_str(_lookup(meta, "metadata.activation_policy"), "model_visible") or "model_visible",
            context_mode=_coerce_str(_lookup(meta, "metadata.context_mode"), "inline") or "inline",
            route_authority=_coerce_str(_lookup(meta, "metadata.route_authority"), "candidate_only") or "candidate_only",
            reference_paths=_collect_reference_paths(base_dir, skill_dir),
            requires_operations=_coerce_list(_lookup(meta, "metadata.requires_operations")),
            requires_capabilities=_coerce_list(_lookup(meta, "metadata.requires_capabilities")),
            prompt_use_when=_coerce_str(prompt_meta.get("use_when")),
            prompt_subagent_handoff_protocol=_coerce_str(prompt_meta.get("subagent_handoff_protocol")),
            prompt_return_protocol=_coerce_str(prompt_meta.get("return_protocol")),
            prompt_output_rule=_coerce_str(prompt_meta.get("output_rule")),
        )
        records.append(_record_from_contract(_contract_from_record(record, body=body)))
    return records


def build_snapshot(skills: list[SkillRecord]) -> str:
    lines = [
        "<skills>",
        "  <summary>Skill registry snapshot for admin display. Runtime prompts should inject only the selected active skill.</summary>",
    ]
    for skill in skills:
        view = _build_prompt_view(skill)
        lines.extend(
            [
                f'  <skill name="{view.title}">',
                f"    <description>{view.capability}</description>",
            ]
        )
        if view.use_when:
            lines.append(f"    <use_when>{view.use_when}</use_when>")
        if view.subagent_handoff_protocol:
            lines.append(f"    <subagent_handoff_protocol>{view.subagent_handoff_protocol}</subagent_handoff_protocol>")
        if view.return_protocol:
            lines.append(f"    <return_protocol>{view.return_protocol}</return_protocol>")
        lines.append(f"    <output_rule>{view.output_rule}</output_rule>")
        lines.append("  </skill>")
    lines.append("</skills>")
    return "\n".join(lines) + "\n"


def _build_prompt_view(skill: SkillRecord) -> SkillPromptContract:
    prompt = _prompt_payload_from_record(skill, "")
    return SkillPromptContract(
        name=skill.name,
        title=skill.title,
        capability=skill.description,
        use_when=prompt.get("use_when", ""),
        subagent_handoff_protocol=prompt.get("subagent_handoff_protocol", ""),
        return_protocol=prompt.get("return_protocol", ""),
        output_rule=prompt.get("output_rule", "") or DEFAULT_SKILL_OUTPUT_RULE,
    )


def _prompt_payload_from_record(record: SkillRecord, body: str) -> dict[str, str]:
    cleaned_body = _strip_fenced_code(body)
    sections = _extract_markdown_sections(cleaned_body)
    return {
        "use_when": record.prompt_use_when
        or _first_section_text(sections, ("适用场景", "什么时候使用", "use when"))
        or _first_labeled_block(
            cleaned_body,
            ("适合被唤起的情况", "典型请求包括"),
            ("不适合被唤起的情况", "## ", "### ", "执行目标", "工作原则"),
        ),
        "subagent_handoff_protocol": record.prompt_subagent_handoff_protocol or _first_section_text(sections, ("子 Agent 交接协议", "subagent handoff protocol")),
        "return_protocol": record.prompt_return_protocol or _first_section_text(sections, ("回传协议", "return protocol", "输出结构", "输出要求")),
        "output_rule": record.prompt_output_rule or _first_section_text(sections, ("回答要求", "输出要求", "output rule")),
    }


def _extract_markdown_sections(body: str) -> dict[str, str]:
    matches = list(SECTION_HEADING_PATTERN.finditer(body or ""))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        if heading and text:
            sections[heading] = text
    return sections


def _strip_fenced_code(body: str) -> str:
    return FENCED_CODE_PATTERN.sub("", body or "")


def _first_section_text(sections: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        target = name.strip().lower()
        for heading, text in sections.items():
            if target == heading or target in heading:
                return text.strip()
    return ""


def _first_labeled_block(body: str, start_labels: tuple[str, ...], stop_labels: tuple[str, ...]) -> str:
    lines = (body or "").splitlines()
    capturing = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not capturing:
            if any(label in stripped for label in start_labels):
                capturing = True
            continue
        if not stripped and not collected:
            continue
        if any(stripped.startswith(label) for label in stop_labels):
            break
        if stripped:
            collected.append(stripped)
    return "\n".join(collected).strip()


def build_registry(skills: list[SkillRecord]) -> dict[str, Any]:
    contracts = [_contract_from_record(skill) for skill in skills]
    return {
        "version": 3,
        "skill_count": len(skills),
        "skills": [contract.to_registry_record() for contract in contracts],
    }


def refresh_snapshot(base_dir: Path) -> Path:
    paths = CapabilitySkillPaths.from_base_dir(base_dir)
    paths.ensure()
    skills = scan_skills(base_dir)
    snapshot_path = paths.skills_snapshot_path
    registry_path = paths.skills_registry_path
    snapshot_path.write_text(build_snapshot(skills), encoding="utf-8")
    registry_path.write_text(
        json.dumps(build_registry(skills), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot_path


if __name__ == "__main__":
    path = refresh_snapshot(BACKEND_DIR)
    print(f"refreshed {path}")


