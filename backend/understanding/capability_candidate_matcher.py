from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from capability_system.local_mcp_registry import LocalMCPUnitRecord, default_local_mcp_units
from capability_system.skill_registry import SkillRegistry
from capability_system.tool_definitions import ToolDefinition, get_tool_definitions


_DEFAULT_BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    candidate_type: str
    name: str
    display_name: str
    operation_id: str = ""
    route: str = ""
    source_kind: str = ""
    score: float = 0.0
    match_reasons: tuple[str, ...] = ()
    capability_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    selected_candidate_type: str = ""
    selected_candidate_name: str = ""
    route: str = ""
    execution_posture: str = ""
    preferred_skill: str = ""
    tool_name: str = ""
    mcp_route: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_capability_candidates(
    *,
    message: str,
    route_hint: str,
    execution_posture: str,
    preferred_skill: str,
    candidate_tools: list[str] | None,
    capability_requests: list[str] | None,
    task_kind: str,
    source_kind: str,
    modality: str,
    base_dir: Path | None = None,
) -> list[CapabilityCandidate]:
    root = Path(base_dir) if base_dir is not None else _DEFAULT_BASE_DIR
    normalized_message = str(message or "").strip().lower()
    requested = {
        str(item or "").strip().lower()
        for item in list(capability_requests or [])
        if str(item or "").strip()
    }
    explicit_tool_names = {
        str(item or "").strip()
        for item in list(candidate_tools or [])
        if str(item or "").strip()
    }
    candidates: list[CapabilityCandidate] = []
    candidates.extend(
        _build_skill_candidates(
            normalized_message=normalized_message,
            route_hint=route_hint,
            preferred_skill=preferred_skill,
            requested=requested,
            task_kind=task_kind,
            source_kind=source_kind,
            modality=modality,
            root=root,
        )
    )
    candidates.extend(
        _build_tool_candidates(
            route_hint=route_hint,
            requested=requested,
            modality=modality,
            explicit_tool_names=explicit_tool_names,
        )
    )
    candidates.extend(
        _build_mcp_candidates(
            route_hint=route_hint,
            preferred_skill=preferred_skill,
            requested=requested,
            source_kind=source_kind,
        )
    )
    candidates.sort(key=lambda item: (-item.score, item.candidate_type, item.name))
    return candidates


def build_capability_resolution(
    *,
    route_hint: str,
    execution_posture: str,
    preferred_skill: str,
    candidate_tools: list[str] | None,
    capability_requests: list[str] | None = None,
    candidates: list[CapabilityCandidate],
) -> CapabilityResolution:
    selected: CapabilityCandidate | None = None
    requested = {
        str(item or "").strip().lower()
        for item in list(capability_requests or [])
        if str(item or "").strip()
    }
    diagnostics = {
        "candidate_count": len(candidates),
        "selection_source": "legacy_route_hint",
    }
    if execution_posture == "direct_rag" and preferred_skill:
        selected = _find_candidate(candidates, candidate_type="skill", name=preferred_skill)
    elif execution_posture == "builtin_tool_lane":
        for tool_name in list(candidate_tools or []):
            selected = _find_candidate(candidates, candidate_type="tool", name=tool_name)
            if selected is not None:
                break
    elif execution_posture == "direct_mcp":
        selected = _find_candidate(candidates, candidate_type="mcp", route=route_hint)
    elif execution_posture == "direct_memory":
        diagnostics["selection_source"] = "memory_direct"
    elif execution_posture == "bounded_agent":
        promoted = _promote_bounded_candidate(
            candidates,
            requested=requested,
            route_hint=route_hint,
            candidate_tools=tuple(candidate_tools or ()),
        )
        if promoted is not None:
            selected = promoted
            diagnostics["selection_source"] = "bounded_candidate_promotion"
    if selected is None and execution_posture != "bounded_agent" and candidates:
        selected = candidates[0]
        diagnostics["selection_source"] = "candidate_fallback"
    resolved_route = str(route_hint or "").strip()
    resolved_execution_posture = str(execution_posture or "").strip()
    resolved_preferred_skill = str(preferred_skill or "").strip()
    resolved_tool_name = ""
    resolved_mcp_route = ""
    if selected is not None:
        if selected.candidate_type == "skill":
            resolved_route = str(selected.route or resolved_route).strip()
            resolved_preferred_skill = selected.name
            resolved_execution_posture = "direct_rag"
        elif selected.candidate_type == "tool":
            resolved_tool_name = selected.name
            normalized_route = str(resolved_route or "").strip()
            if not normalized_route or normalized_route == "agent":
                normalized_route = str(selected.metadata.get("primary_route_hint") or "tool").strip()
            resolved_route = normalized_route
            resolved_execution_posture = "builtin_tool_lane"
        elif selected.candidate_type == "mcp":
            resolved_route = str(selected.route or resolved_route).strip()
            resolved_mcp_route = str(selected.route or "").strip()
            resolved_execution_posture = "direct_mcp"
            if not resolved_preferred_skill:
                linked_skill = str(selected.metadata.get("primary_skill_ref") or "").strip()
                if linked_skill:
                    resolved_preferred_skill = linked_skill
    return CapabilityResolution(
        selected_candidate_type=selected.candidate_type if selected is not None else "",
        selected_candidate_name=selected.name if selected is not None else "",
        route=resolved_route,
        execution_posture=resolved_execution_posture,
        preferred_skill=resolved_preferred_skill if resolved_execution_posture == "direct_rag" else resolved_preferred_skill,
        tool_name=resolved_tool_name,
        mcp_route=resolved_mcp_route,
        diagnostics=diagnostics,
    )


def _promote_bounded_candidate(
    candidates: list[CapabilityCandidate],
    *,
    requested: set[str],
    route_hint: str,
    candidate_tools: tuple[str, ...],
) -> CapabilityCandidate | None:
    if not candidates:
        return None
    for candidate in candidates:
        if candidate.candidate_type == "mcp" and candidate.score >= 18.0:
            return candidate
    tool_route_families = {
        "tool",
        "workspace_read",
        "workspace_path_search",
        "workspace_text_search",
        "workspace_write",
        "workspace_edit",
        "realtime_network",
    }
    if route_hint in tool_route_families or candidate_tools:
        tool_candidates = [candidate for candidate in candidates if candidate.candidate_type == "tool"]
        if tool_candidates:
            explicit_tool_names = {
                str(item or "").strip()
                for item in candidate_tools
                if str(item or "").strip()
            }
            for candidate in tool_candidates:
                if candidate.name in explicit_tool_names:
                    return candidate
            top_tool = tool_candidates[0]
            if top_tool.score >= 20.0:
                return top_tool
    if "latest_information" in requested:
        return None
    top = candidates[0]
    if top.candidate_type != "skill":
        return None
    if top.score < 20.0:
        return None
    return top


def _find_candidate(
    candidates: list[CapabilityCandidate],
    *,
    candidate_type: str,
    name: str = "",
    route: str = "",
) -> CapabilityCandidate | None:
    normalized_name = str(name or "").strip()
    normalized_route = str(route or "").strip()
    for candidate in candidates:
        if candidate.candidate_type != candidate_type:
            continue
        if normalized_name and candidate.name == normalized_name:
            return candidate
        if normalized_route and candidate.route == normalized_route:
            return candidate
    return None


@lru_cache(maxsize=1)
def _skill_records(base_dir_text: str) -> tuple[Any, ...]:
    registry = SkillRegistry(Path(base_dir_text))
    return tuple(registry.skills)


def _build_skill_candidates(
    *,
    normalized_message: str,
    route_hint: str,
    preferred_skill: str,
    requested: set[str],
    task_kind: str,
    source_kind: str,
    modality: str,
    root: Path,
) -> list[CapabilityCandidate]:
    results: list[CapabilityCandidate] = []
    for skill in _skill_records(str(root)):
        reasons: list[str] = []
        score = 0.0
        if preferred_skill and skill.name == preferred_skill:
            score += 100.0
            reasons.append("preferred_skill")
        overlap = requested & {str(item or "").strip().lower() for item in skill.capability_tags}
        if overlap:
            score += 20.0 * len(overlap)
            reasons.append("capability_tags")
        if task_kind and task_kind in set(skill.supported_task_kinds):
            score += 12.0
            reasons.append("task_kind")
        if source_kind and source_kind in set(skill.supported_source_kinds):
            score += 8.0
            reasons.append("source_kind")
        if modality and modality in set(skill.supported_modalities):
            score += 6.0
            reasons.append("modality")
        if route_hint and str(skill.preferred_route or "").strip() == route_hint:
            score += 4.0
            reasons.append("preferred_route")
        if normalized_message and _message_matches(normalized_message, skill.routing_hints):
            score += 3.0
            reasons.append("routing_hints")
        if normalized_message and _message_matches(normalized_message, skill.examples):
            score += 2.0
            reasons.append("examples")
        if score <= 0.0:
            continue
        results.append(
            CapabilityCandidate(
                candidate_type="skill",
                name=skill.name,
                display_name=skill.title,
                route=str(skill.preferred_route or ""),
                source_kind="skill_registry",
                score=score,
                match_reasons=tuple(reasons),
                capability_tags=tuple(skill.capability_tags),
                metadata={
                    "supported_task_kinds": list(skill.supported_task_kinds),
                    "supported_source_kinds": list(skill.supported_source_kinds),
                    "supported_modalities": list(skill.supported_modalities),
                },
            )
        )
    return results


def _build_tool_candidates(
    *,
    route_hint: str,
    requested: set[str],
    modality: str,
    explicit_tool_names: set[str],
) -> list[CapabilityCandidate]:
    results: list[CapabilityCandidate] = []
    for tool in get_tool_definitions():
        reasons: list[str] = []
        score = 0.0
        has_structural_signal = False
        if tool.name in explicit_tool_names:
            score += 100.0
            reasons.append("legacy_candidate_tools")
            has_structural_signal = True
        overlap = requested & {str(item or "").strip().lower() for item in tool.capability_tags}
        if overlap:
            score += 20.0 * len(overlap)
            reasons.append("capability_tags")
            has_structural_signal = True
        tool_route_hints = {
            str(item or "").strip().lower()
            for item in tool.route_hints
        }
        if route_hint and route_hint in tool_route_hints:
            score += 8.0
            reasons.append("route_hints")
            has_structural_signal = True
        if modality and modality in set(tool.supported_modalities) and has_structural_signal:
            score += 5.0
            reasons.append("modality")
        if score <= 0.0 or not has_structural_signal:
            continue
        primary_route_hint = _primary_tool_route_hint(tool)
        results.append(
            CapabilityCandidate(
                candidate_type="tool",
                name=tool.name,
                display_name=tool.display_name,
                operation_id=tool.operation_id,
                route="tool",
                source_kind="tool_registry",
                score=score,
                match_reasons=tuple(reasons),
                capability_tags=tuple(tool.capability_tags),
                metadata={
                    "supported_modalities": list(tool.supported_modalities),
                    "runtime_visibility": tool.runtime_visibility,
                    "safe_for_auto_route": tool.safe_for_auto_route,
                    "primary_route_hint": primary_route_hint,
                },
            )
        )
    return results


def _primary_tool_route_hint(tool: ToolDefinition) -> str:
    route_hints = [
        str(item or "").strip()
        for item in tool.route_hints
        if str(item or "").strip()
    ]
    for hint in route_hints:
        if hint != "tool":
            return hint
    return route_hints[0] if route_hints else "tool"


def _build_mcp_candidates(
    *,
    route_hint: str,
    preferred_skill: str,
    requested: set[str],
    source_kind: str,
) -> list[CapabilityCandidate]:
    results: list[CapabilityCandidate] = []
    for unit in default_local_mcp_units():
        reasons: list[str] = []
        score = 0.0
        normalized_tags = {str(item or "").strip().lower() for item in unit.tags}
        normalized_requested = set(requested)
        if route_hint and route_hint == unit.route:
            score += 100.0
            reasons.append("route_hint")
        if preferred_skill and preferred_skill in set(unit.skill_refs):
            score += 25.0
            reasons.append("preferred_skill_ref")
        alias_map = {
            "structured_data": {"dataset_analysis"},
            "pdf": {"document_analysis"},
            "retrieval": {"knowledge_lookup", "faq"},
        }
        overlap = normalized_requested & normalized_tags
        overlap |= normalized_requested & alias_map.get(unit.route, set())
        if overlap:
            score += 18.0 * len(overlap)
            reasons.append("tag_overlap")
        if unit.route == "retrieval":
            continue
        if source_kind and source_kind == unit.source_kind:
            score += 10.0
            reasons.append("source_kind")
        if score <= 0.0:
            continue
        results.append(
            CapabilityCandidate(
                candidate_type="mcp",
                name=unit.name,
                display_name=unit.title,
                operation_id=unit.operation_id,
                route=unit.route,
                source_kind="local_mcp_registry",
                score=score,
                match_reasons=tuple(reasons),
                capability_tags=tuple(unit.tags),
                metadata={
                    "unit_id": unit.unit_id,
                    "capability_kinds": list(unit.capability_kinds),
                    "skill_refs": list(unit.skill_refs),
                    "source_kind": unit.source_kind,
                    "primary_skill_ref": str(unit.skill_refs[0] if unit.skill_refs else "").strip(),
                },
            )
        )
    return results


def _message_matches(message: str, patterns: list[str] | tuple[str, ...]) -> bool:
    for pattern in patterns:
        normalized = str(pattern or "").strip().lower()
        if normalized and normalized in message:
            return True
    return False
