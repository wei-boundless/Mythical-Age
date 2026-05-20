from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from understanding.memory_intent import MemoryIntent
from understanding.task_understanding import TaskUnderstanding, analyze_task_understanding

if TYPE_CHECKING:
    from capability_system.skill_registry import SkillRegistry
    from capability_system.tool_registry import ToolRegistry


_DIRECT_TOOL_ROUTE_FAMILIES = {
    "tool",
    "workspace_read",
    "workspace_path_search",
    "workspace_text_search",
    "realtime_network",
}


@dataclass(slots=True)
class QueryUnderstanding:
    intent: str = "general_query"
    source_kind: str = "knowledge_base"
    task_kind: str = "knowledge_lookup"
    target_object: str | None = None
    modality: str = "general"
    route: str = "rag"
    execution_posture: str = "direct_rag"
    direct_route_reason: str = ""
    preferred_skill: str | None = None
    skill_name: str | None = None
    tool_name: str | None = None
    capability_requests: list[str] = field(default_factory=list)
    candidate_tools: list[str] = field(default_factory=list)
    tool_input: dict[str, Any] = field(default_factory=dict)
    should_skip_rag: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    structural_signals: dict[str, Any] = field(default_factory=dict)
    candidate_capabilities: list[dict[str, Any]] = field(default_factory=list)
    capability_resolution: dict[str, Any] = field(default_factory=dict)


def analyze_query_understanding(
    message: str,
    memory_intent: MemoryIntent | None = None,
    *,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> QueryUnderstanding:
    task = analyze_task_understanding(
        message,
        memory_intent,
    )
    understanding = _from_task(task)
    _apply_skill_tool_routing(
        understanding,
        message,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    return understanding


def _from_task(task: TaskUnderstanding) -> QueryUnderstanding:
    return QueryUnderstanding(
        intent=task.intent,
        source_kind=task.source_kind,
        task_kind=task.task_kind,
        target_object=None,
        modality=task.modality,
        route=task.route_hint,
        execution_posture=task.execution_posture,
        direct_route_reason=task.direct_route_reason,
        preferred_skill=task.preferred_skill,
        skill_name=None,
        capability_requests=list(task.capability_requests),
        candidate_tools=list(task.candidate_tools),
        tool_input=dict(task.parameters),
        should_skip_rag=task.should_skip_rag,
        confidence=task.confidence,
        reasons=list(task.reasons),
        structural_signals=dict(task.structural_signals),
        candidate_capabilities=list(task.candidate_capabilities),
        capability_resolution=dict(task.capability_resolution),
    )


def _apply_skill_tool_routing(
    understanding: QueryUnderstanding,
    message: str,
    *,
    skill_registry: SkillRegistry | None,
    tool_registry: ToolRegistry | None,
) -> None:
    _apply_capability_resolution_state(understanding)

    # Understanding only exposes a TaskFrame-like structure plus structural tool
    # candidates. Skill policy is resolved later by the planner/dispatch layer
    # so skill scope cannot overwrite candidate tools here.
    if understanding.route == "memory":
        return

    if understanding.route in {"rag", "pdf", "structured_data"}:
        understanding.candidate_tools = []
        understanding.tool_name = None
        if not understanding.tool_input:
            understanding.tool_input = {"query": message}
        return

    if (
        tool_registry is not None
        and not understanding.candidate_tools
        and understanding.capability_requests
    ):
        understanding.candidate_tools = tool_registry.resolve_candidate_names(
            capability_requests=understanding.capability_requests,
            route=understanding.route,
            modality=understanding.modality,
            safe_only=True,
        )

    if understanding.execution_posture == "bounded_agent":
        return

    if understanding.route not in _DIRECT_TOOL_ROUTE_FAMILIES:
        return

    if tool_registry is None:
        if not understanding.tool_name and len(understanding.candidate_tools) == 1:
            understanding.tool_name = understanding.candidate_tools[0]
            understanding.reasons.append("single_candidate_tool")
        if not understanding.tool_input:
            understanding.tool_input = {"query": message}
        return

    if understanding.tool_name:
        tool = tool_registry.get_by_name(understanding.tool_name)
        if tool is None or (
            understanding.candidate_tools and tool.name not in understanding.candidate_tools
        ):
            understanding.tool_name = None

    if not understanding.tool_name and understanding.candidate_tools:
        selected = tool_registry.select_best(
            message,
            candidate_names=understanding.candidate_tools,
            modality=understanding.modality,
            route=understanding.route,
            capability_requests=understanding.capability_requests,
            safe_only=True,
        )
        if selected is not None:
            understanding.tool_name = selected.name
            understanding.reasons.append("tool_registry_selected")

    if not understanding.tool_name and len(understanding.candidate_tools) == 1:
        understanding.tool_name = understanding.candidate_tools[0]
        understanding.reasons.append("single_candidate_tool")

    if understanding.tool_name and not understanding.tool_input:
        understanding.tool_input = {"query": message}


def _apply_capability_resolution_state(understanding: QueryUnderstanding) -> None:
    resolution = dict(understanding.capability_resolution or {})
    if not resolution:
        return
    selected_candidate_type = str(resolution.get("selected_candidate_type") or "").strip()
    selected_candidate_name = str(resolution.get("selected_candidate_name") or "").strip()
    resolved_route = str(resolution.get("route") or "").strip()
    resolved_execution_posture = str(resolution.get("execution_posture") or "").strip()
    resolved_tool_name = str(resolution.get("tool_name") or "").strip()
    resolved_preferred_skill = str(resolution.get("preferred_skill") or "").strip()

    if resolved_route:
        understanding.route = resolved_route
    if resolved_execution_posture:
        understanding.execution_posture = resolved_execution_posture

    if selected_candidate_type == "skill" and selected_candidate_name:
        understanding.skill_name = selected_candidate_name
        if not understanding.preferred_skill:
            understanding.preferred_skill = resolved_preferred_skill or selected_candidate_name
    elif selected_candidate_type == "mcp":
        if resolved_preferred_skill:
            understanding.preferred_skill = resolved_preferred_skill
            understanding.skill_name = resolved_preferred_skill
    elif selected_candidate_type == "tool":
        tool_name = resolved_tool_name or selected_candidate_name
        if tool_name:
            if tool_name not in understanding.candidate_tools:
                understanding.candidate_tools = [tool_name, *list(understanding.candidate_tools)]
            understanding.tool_name = tool_name
