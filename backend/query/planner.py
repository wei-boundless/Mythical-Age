from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from skill_system import SkillDefinition, SkillRegistry
from tools.runtime import ToolRuntime
from understanding import (
    QueryUnderstanding,
    analyze_memory_intent,
    analyze_query_understanding,
)

from query.binding_resolver import StructuredBindingResolver
from query.continuation_resolver import QueryContinuationResolver
from query.models import QueryExecutionPlan, QueryPlan
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
        self.binding_resolver = StructuredBindingResolver(base_dir=base_dir)

    def build_plan(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
    ) -> QueryPlan:
        root_execution = self._build_execution(message=message, history=history)
        memory_intent = root_execution.memory_intent
        query_understanding = root_execution.query_understanding
        subqueries = self.subtask_planner.plan(message=message, understanding=query_understanding)
        if len(subqueries) <= 1:
            executions = [root_execution]
            query_understanding = root_execution.query_understanding
            active_skill = root_execution.active_skill
            tool_input = dict(root_execution.tool_input)
            structured_binding = root_execution.structured_binding
            execution_kind = root_execution.execution_kind
        else:
            executions = [
                self._build_execution(message=subquery, history=history)
                for subquery in subqueries
            ]
            query_understanding = QueryUnderstanding(
                intent="compound_query",
                source_kind="orchestration",
                task_kind="compound_query",
                modality="multi",
                route="compound",
                reasons=["compound_query_fanout"],
            )
            active_skill = None
            tool_input = {}
            structured_binding = None
            execution_kind = "agent"
        return QueryPlan(
            session_id=session_id,
            message=message,
            history=history,
            subqueries=subqueries,
            memory_intent=memory_intent,
            query_understanding=query_understanding,
            active_skill=active_skill,
            tool_input=tool_input,
            structured_binding=structured_binding,
            execution_kind=execution_kind,
            executions=executions,
        )

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

    def _build_execution(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
    ) -> QueryExecutionPlan:
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
        structured_binding = self.binding_resolver.resolve(
            message=message,
            understanding=query_understanding,
            history=history,
        )
        tool_input = {}
        execution_kind = "agent"
        if query_understanding.route == "tool" and query_understanding.tool_name:
            tool_input = self.tool_input_resolver.resolve(
                plan=SimpleNamespace(
                    message=message,
                    query_understanding=query_understanding,
                    structured_binding=structured_binding,
                ),
                history=history,
            )
            query_understanding.tool_input = dict(tool_input)
            execution_kind = "direct_tool"
        return QueryExecutionPlan(
            message=message,
            history=list(history),
            memory_intent=memory_intent,
            query_understanding=query_understanding,
            active_skill=active_skill,
            tool_input=tool_input,
            structured_binding=structured_binding,
            execution_kind=execution_kind,
        )
