from __future__ import annotations

from pathlib import Path
from typing import Any

from skill_system import SkillDefinition, SkillRegistry
from tools.runtime import ToolRuntime
from understanding import (
    QueryUnderstanding,
    analyze_memory_intent,
    analyze_query_understanding,
)

from query.continuation_resolver import QueryContinuationResolver
from query.models import QueryPlan
from query.subtask_planner import QuerySubtaskPlanner
from query.tool_input_resolver import ToolInputResolver


class QueryPlanner:
    def __init__(
        self,
        *,
        base_dir: Path,
        skill_registry: SkillRegistry | None,
        tool_runtime: ToolRuntime,
    ) -> None:
        self.base_dir = base_dir
        self.skill_registry = skill_registry
        self.tool_runtime = tool_runtime
        self.continuation_resolver = QueryContinuationResolver(base_dir=base_dir)
        self.subtask_planner = QuerySubtaskPlanner()
        self.tool_input_resolver = ToolInputResolver(base_dir=base_dir)

    def build_plan(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
    ) -> QueryPlan:
        memory_intent = analyze_memory_intent(message)
        query_understanding = analyze_query_understanding(
            message,
            memory_intent,
            skill_registry=self.skill_registry,
            tool_registry=self.tool_runtime.registry,
        )
        query_understanding = self.continuation_resolver.resolve(
            message=message,
            history=history,
            understanding=query_understanding,
        )
        active_skill = self._resolve_active_skill(message, query_understanding)
        return QueryPlan(
            session_id=session_id,
            message=message,
            history=history,
            subqueries=self.subtask_planner.plan(message=message, understanding=query_understanding),
            memory_intent=memory_intent,
            query_understanding=query_understanding,
            active_skill=active_skill,
        )

    def resolve_tool_input_from_history(
        self,
        plan: QueryPlan,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.tool_input_resolver.resolve(plan=plan, history=history)

    def _resolve_active_skill(
        self,
        message: str,
        query_understanding: QueryUnderstanding,
    ) -> SkillDefinition | None:
        if self.skill_registry is None:
            return None
        if query_understanding.skill_name:
            existing = self.skill_registry.get_by_name(query_understanding.skill_name)
            if existing is not None:
                return existing
        skill = self.skill_registry.match_for_query(
            message=message,
            route=query_understanding.route,
            modality=query_understanding.modality,
            tool_name=query_understanding.tool_name,
        )
        if skill is not None:
            query_understanding.skill_name = skill.name
        return skill

    def _promote_contextual_pdf_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        query_understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        return self.continuation_resolver.promote_pdf_query(message, history, query_understanding)

    def _promote_contextual_structured_query(
        self,
        message: str,
        history: list[dict[str, Any]],
        query_understanding: QueryUnderstanding,
    ) -> QueryUnderstanding:
        return self.continuation_resolver.promote_structured_query(message, history, query_understanding)

    def _looks_like_pdf_followup(self, message: str) -> bool:
        return self.continuation_resolver._looks_like_pdf_followup(message)

    def _looks_like_structured_followup(self, message: str) -> bool:
        return self.continuation_resolver._looks_like_structured_followup(message)
