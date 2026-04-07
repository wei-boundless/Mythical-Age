from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from understanding.memory_intent import MemoryIntent
from understanding.task_understanding import TaskUnderstanding, analyze_task_understanding

if TYPE_CHECKING:
    from skill_system import SkillRegistry
    from tools.tool_registry import ToolRegistry


@dataclass(slots=True)
class QueryUnderstanding:
    intent: str = "general_query"
    source_kind: str = "knowledge_base"
    task_kind: str = "knowledge_lookup"
    target_object: str | None = None
    modality: str = "general"
    route: str = "rag"
    skill_name: str | None = None
    tool_name: str | None = None
    candidate_tools: list[str] = field(default_factory=list)
    tool_input: dict[str, Any] = field(default_factory=dict)
    should_skip_rag: bool = False
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def analyze_query_understanding(
    message: str,
    memory_intent: MemoryIntent | None = None,
    *,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> QueryUnderstanding:
    task = analyze_task_understanding(message, memory_intent)
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
        target_object=task.target_object,
        modality=task.modality,
        route=task.route_hint,
        skill_name=task.preferred_skill,
        candidate_tools=list(task.candidate_tools),
        tool_input=dict(task.parameters),
        should_skip_rag=task.should_skip_rag,
        confidence=task.confidence,
        reasons=list(task.reasons),
    )


def _apply_skill_tool_routing(
    understanding: QueryUnderstanding,
    message: str,
    *,
    skill_registry: SkillRegistry | None,
    tool_registry: ToolRegistry | None,
) -> None:
    if understanding.route == "memory":
        return

    if skill_registry is not None:
        matched_skill = (
            skill_registry.get_by_name(understanding.skill_name)
            if understanding.skill_name
            else None
        )
        if matched_skill is None:
            matched_skill = skill_registry.match_for_query(
                message=message,
                route=understanding.route,
                modality=understanding.modality,
                task_kind=understanding.task_kind,
                source_kind=understanding.source_kind,
                tool_name=understanding.tool_name,
                candidate_tools=understanding.candidate_tools,
            )
        if matched_skill is not None:
            understanding.skill_name = matched_skill.name
            if matched_skill.allowed_tools:
                understanding.candidate_tools = list(matched_skill.allowed_tools)
            if (
                understanding.route == "rag"
                and matched_skill.preferred_route == "tool"
                and matched_skill.allowed_tools
            ):
                understanding.route = "tool"
                understanding.should_skip_rag = True
                understanding.reasons.append("skill_promoted_tool_route")

    if understanding.route != "tool":
        return

    if tool_registry is None:
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
