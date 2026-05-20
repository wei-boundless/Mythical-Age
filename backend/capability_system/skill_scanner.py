from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from capability_system.paths import CapabilitySystemPaths
from capability_system.skill_contracts import SkillContract, SkillPromptContract, SkillRuntimeContract

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


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
    preferred_route: str = "rag"
    forbidden_routes: list[str] = field(default_factory=list)
    routing_hints: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    activation_policy: str = "model_visible"
    context_mode: str = "inline"
    route_authority: str = "candidate_only"
    reference_paths: list[str] = field(default_factory=list)
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
        routing_hints=list(runtime.routing_hints),
        examples=list(runtime.examples),
        activation_policy=runtime.activation_policy,
        context_mode=runtime.context_mode,
        route_authority=runtime.route_authority,
        reference_paths=list(runtime.reference_paths),
        validation_errors=list(contract.validation_errors),
    )


def _contract_from_record(record: SkillRecord, *, body: str = "") -> SkillContract:
    return SkillContract.from_runtime(
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
            routing_hints=record.routing_hints,
            examples=record.examples,
            activation_policy=record.activation_policy,
            context_mode=record.context_mode,
            route_authority=record.route_authority,
            reference_paths=record.reference_paths,
        ),
        body=body,
        use_when=_build_skill_use_when(record),
        delegation_protocol=_build_skill_delegation_protocol(record),
        return_protocol=_build_skill_return_protocol(record),
    )


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
    paths_helper = CapabilitySystemPaths.from_base_dir(base_dir)
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
    paths = CapabilitySystemPaths.from_base_dir(base_dir)
    skills_dir = paths.skills_dir
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

        record = SkillRecord(
            name=_coerce_str(meta.get("name"), skill_dir.name),
            title=title,
            description=description,
            path=paths.to_relative_path(skill_file),
            supported_modalities=_coerce_list(_lookup(meta, "metadata.supported_modalities")),
            supported_task_kinds=_coerce_list(_lookup(meta, "metadata.supported_task_kinds")),
            supported_source_kinds=_coerce_list(_lookup(meta, "metadata.supported_source_kinds")),
            capability_tags=_coerce_list(_lookup(meta, "metadata.capability_tags")),
            preferred_route=_coerce_str(_lookup(meta, "metadata.preferred_route"), "rag") or "rag",
            forbidden_routes=_coerce_list(_lookup(meta, "metadata.forbidden_routes")),
            routing_hints=_coerce_list(_lookup(meta, "metadata.routing_hints")),
            examples=_coerce_list(_lookup(meta, "metadata.examples")),
            activation_policy=_coerce_str(_lookup(meta, "metadata.activation_policy"), "model_visible") or "model_visible",
            context_mode=_coerce_str(_lookup(meta, "metadata.context_mode"), "inline") or "inline",
            route_authority=_coerce_str(_lookup(meta, "metadata.route_authority"), "candidate_only") or "candidate_only",
            reference_paths=_collect_reference_paths(base_dir, skill_dir),
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
        if view.delegation_protocol:
            lines.append(f"    <delegation_protocol>{view.delegation_protocol}</delegation_protocol>")
        if view.return_protocol:
            lines.append(f"    <return_protocol>{view.return_protocol}</return_protocol>")
        lines.append(f"    <output_rule>{view.output_rule}</output_rule>")
        lines.append("  </skill>")
    lines.append("</skills>")
    return "\n".join(lines) + "\n"


def _build_skill_use_when(skill: SkillRecord) -> str:
    source_kinds = set(skill.supported_source_kinds)
    modalities = set(skill.supported_modalities)
    task_kinds = set(skill.supported_task_kinds)

    if "knowledge_base" in source_kinds:
        return "Use for local knowledge-base lookup, factual explanation, and questions that should be answered from local materials."
    if "document" in source_kinds or "pdf" in modalities or "document" in modalities:
        return "Use for reading local documents or PDFs, including whole-document, section-level, and page-level questions."
    if "dataset" in source_kinds or modalities & {"table", "spreadsheet", "csv", "json"}:
        return "Use for structured data questions such as filtering, ranking, grouping, summary statistics, and record lookup."
    if "external_web" in source_kinds or modalities & {"realtime", "web", "finance"}:
        return "Use when the user needs current external information, real-time lookup, or official web sources."
    if "workflow" in source_kinds or "workflow_lesson_capture" in task_kinds:
        return "Use for workflow reflection and reusable lesson capture after a failed-then-corrected attempt."
    return ""


def _build_skill_delegation_protocol(skill: SkillRecord) -> str:
    if skill.name == "skill-creator":
        return (
            "When the main agent delegates, ask for capability_design or skill_update; pass the target use case, "
            "expected trigger phrases, execution boundary, required tools, and whether the skill must coordinate with "
            "sub-agents. If the request is only a wording polish, keep scope narrow and avoid inventing new behavior."
        )
    if skill.name == "rag-skill":
        return (
            "When the main agent delegates, ask for evidence_lookup; pass query, exact answer scope, known knowledge-base "
            "anchors, follow-up constraints, and expected_output_contract. If the task is actually PDF reading, dataset "
            "analysis, or current web research, return a limitation naming the better specialist instead of expanding scope."
        )
    if skill.name == "pdf-analysis":
        return (
            "When the main agent delegates, ask for pdf_reading; pass query, path/active_pdf, page or section mode, "
            "follow-up constraints, and expected_output_contract. Return page/section anchors and extraction limits; if "
            "the task is knowledge-base lookup or data aggregation, report the better specialist."
        )
    if skill.name == "structured-data-analysis":
        return (
            "When the main agent delegates, ask for table_analysis; pass query, path/active_dataset, required columns, "
            "filter/grouping/ranking criteria, active result/subset handles, follow-up constraint policy, and expected_output_contract."
        )
    return ""


def _build_skill_return_protocol(skill: SkillRecord) -> str:
    if skill.name == "skill-creator":
        return (
            "Return a concrete skill draft or review notes with three parts: boundary, prompt structure, and validation "
            "gaps. Clearly separate what should be changed in metadata, what should be changed in the body, and what should "
            "remain untouched. If the skill is too broad, say how to split it."
        )
    if skill.name == "rag-skill":
        return (
            "Return summary, answer_candidate, evidence_refs, artifact_refs if any, confidence, limitations, consumed_handles, "
            "and produced_handles. Use conclusion/evidence/limitations wording and do not mention internal tool names."
        )
    if skill.name == "pdf-analysis":
        return (
            "Return summary, answer_candidate, page or section evidence_refs, artifact_refs if any, confidence, limitations, "
            "consumed_handles, and produced_handles. State OCR/extraction limits explicitly."
        )
    if skill.name == "structured-data-analysis":
        return (
            "Return summary, answer_candidate, calculation evidence_refs, artifact_refs if any, confidence, limitations, "
            "consumed_handles, and produced_handles. State field, sheet, or subset limits explicitly."
        )
    return ""


def _build_prompt_view(skill: SkillRecord) -> SkillPromptContract:
    return SkillPromptContract(
        name=skill.name,
        title=skill.title,
        capability=skill.description,
        use_when=_build_skill_use_when(skill),
        delegation_protocol=_build_skill_delegation_protocol(skill),
        return_protocol=_build_skill_return_protocol(skill),
    )


def build_registry(skills: list[SkillRecord]) -> dict[str, Any]:
    contracts = [_contract_from_record(skill) for skill in skills]
    return {
        "version": 3,
        "skill_count": len(skills),
        "skills": [contract.to_registry_record() for contract in contracts],
    }


def refresh_snapshot(base_dir: Path) -> Path:
    paths = CapabilitySystemPaths.from_base_dir(base_dir)
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
