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
    payload = dict(_as_mapping(understanding).get("capability_resolution") or {})
    route = str(payload.get("route") or _as_mapping(understanding).get("route") or _as_mapping(understanding).get("route_hint") or "").strip()
    execution_posture = str(payload.get("execution_posture") or _as_mapping(understanding).get("execution_posture") or "").strip()
    selected_candidate_type = str(payload.get("selected_candidate_type") or "").strip()
    selected_candidate_name = str(payload.get("selected_candidate_name") or "").strip()
    preferred_skill = str(_as_mapping(understanding).get("preferred_skill") or "").strip()
    if not preferred_skill and selected_candidate_type == "skill":
        preferred_skill = selected_candidate_name
    if not preferred_skill:
        preferred_skill = str(payload.get("preferred_skill") or "").strip()
    tool_name = str(_as_mapping(understanding).get("tool_name") or payload.get("tool_name") or "").strip()
    if not tool_name and selected_candidate_type == "tool":
        tool_name = selected_candidate_name
    mcp_route = str(payload.get("mcp_route") or "").strip()
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
