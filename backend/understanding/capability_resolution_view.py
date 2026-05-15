from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityResolutionView:
    route: str = ""
    execution_posture: str = ""
    preferred_skill: str = ""
    selected_candidate_type: str = ""
    selected_candidate_name: str = ""
    tool_name: str = ""
    mcp_route: str = ""


def capability_resolution_view(understanding: Any) -> CapabilityResolutionView:
    mapping = _as_mapping(understanding)
    payload = dict(mapping.get("capability_resolution") or {})
    signals = dict(mapping.get("structural_signals") or {})
    explicit_task_owner = bool(signals.get("understanding_aligned_to_explicit_task"))
    should_skip_rag = bool(mapping.get("should_skip_rag"))
    top_route = str(mapping.get("route") or mapping.get("route_hint") or "").strip()
    top_execution_posture = str(mapping.get("execution_posture") or "").strip()
    if explicit_task_owner:
        payload_route = ""
        payload_execution_posture = ""
    elif should_skip_rag and (
        str(payload.get("route") or "").strip() == "rag"
        or str(payload.get("execution_posture") or "").strip() == "direct_rag"
        or str(payload.get("preferred_skill") or "").strip() == "rag-skill"
    ):
        payload_route = ""
        payload_execution_posture = ""
    else:
        payload_route = str(payload.get("route") or "").strip()
        payload_execution_posture = str(payload.get("execution_posture") or "").strip()
    route = str(payload_route or top_route).strip()
    execution_posture = str(payload_execution_posture or top_execution_posture).strip()
    selected_candidate_type = str(payload.get("selected_candidate_type") or "").strip()
    selected_candidate_name = str(payload.get("selected_candidate_name") or "").strip()
    if explicit_task_owner or (should_skip_rag and selected_candidate_name == "rag-skill"):
        selected_candidate_type = ""
        selected_candidate_name = ""
    preferred_skill = str(mapping.get("preferred_skill") or "").strip()
    if not preferred_skill and selected_candidate_type == "skill":
        preferred_skill = selected_candidate_name
    if not preferred_skill:
        preferred_skill = str(payload.get("preferred_skill") or "").strip()
    if explicit_task_owner or (should_skip_rag and preferred_skill == "rag-skill"):
        preferred_skill = ""
    tool_name = str(mapping.get("tool_name") or payload.get("tool_name") or "").strip()
    if not tool_name and selected_candidate_type == "tool":
        tool_name = selected_candidate_name
    mcp_route = str(payload.get("mcp_route") or "").strip()
    if explicit_task_owner:
        tool_name = str(mapping.get("tool_name") or "").strip()
        mcp_route = ""
    return CapabilityResolutionView(
        route=route,
        execution_posture=execution_posture,
        preferred_skill=preferred_skill,
        selected_candidate_type=selected_candidate_type,
        selected_candidate_name=selected_candidate_name,
        tool_name=tool_name,
        mcp_route=mcp_route,
    )


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return dict(getattr(value, "__dict__", {}) or {})
