from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from skill_system import SkillDefinition, SkillPolicyResolver, SkillRegistry
from tools.runtime import ToolRuntime
from understanding import (
    QueryUnderstanding,
    analyze_memory_intent,
    analyze_query_understanding,
)

from query.binding_resolver import StructuredBindingResolver
from query.bundle_planner import BundlePlanner
from query.capability_dispatch import CapabilityDispatchScheduler
from query.continuation_resolver import QueryContinuationResolver
from query.models import BundleItemPlan, BundlePlan, QueryExecutionPlan, QueryPlan, SubtaskPlan
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
        self.bundle_planner = BundlePlanner()
        self.subtask_planner = QuerySubtaskPlanner()
        self.dispatch_scheduler = CapabilityDispatchScheduler()
        self.tool_input_resolver = ToolInputResolver(base_dir=base_dir)
        self.binding_resolver = StructuredBindingResolver(base_dir=base_dir)
        self.skill_policy_resolver = SkillPolicyResolver(skill_registry) if skill_registry is not None else None

    def build_plan(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
        ephemeral_system_messages: list[str] | None = None,
        authority_context: dict[str, Any] | None = None,
        explicit_subtasks: list[dict[str, Any]] | None = None,
    ) -> QueryPlan:
        root_execution = self._build_execution(
            message=message,
            history=history,
            ephemeral_system_messages=ephemeral_system_messages,
            authority_context=authority_context,
        )
        memory_intent = root_execution.memory_intent
        query_understanding = root_execution.query_understanding
        bundle_plan = None
        execution_mode = "single_execution"
        subtasks = self.subtask_planner.plan_structured(
            message=message,
            understanding=query_understanding,
            explicit_subtasks=explicit_subtasks,
        )
        if explicit_subtasks:
            execution_mode = "explicit_fanout"
        elif not explicit_subtasks:
            bundle_plan = self.bundle_planner.plan(
                session_id=session_id,
                message=message,
                understanding=query_understanding,
                authority_context=authority_context,
            )
            if bundle_plan is not None:
                execution_mode = "bundle_execution"

        if bundle_plan is not None:
            executions = self._build_bundle_executions(
                history=history,
                bundle_plan=bundle_plan,
                root_execution=root_execution,
                authority_context=authority_context,
            )
            subqueries = [item.execution_message for item in bundle_plan.items]
            subtasks = []
            query_understanding = QueryUnderstanding(
                intent="bundle_query",
                source_kind="orchestration",
                task_kind="bundle_query",
                modality="multi",
                route="bundle",
                execution_posture="bundle_execution",
                direct_route_reason="strong_anchor_bundle",
                reasons=["strong_anchor_bundle"],
            )
            active_skill = None
            tool_input = {}
            structured_binding = None
            execution_kind = "agent"
        elif len(subtasks) <= 1:
            subqueries = [subtask.execution_message for subtask in subtasks]
            executions = [self._attach_subtask_metadata(root_execution, subtasks[0] if subtasks else SubtaskPlan.single(message))]
            query_understanding = root_execution.query_understanding
            active_skill = root_execution.active_skill
            tool_input = dict(root_execution.tool_input)
            structured_binding = root_execution.structured_binding
            execution_kind = root_execution.execution_kind
        else:
            subqueries = [subtask.execution_message for subtask in subtasks]
            executions = self._build_compound_executions(
                history=history,
                subtasks=subtasks,
                root_execution=root_execution,
                authority_context=authority_context,
            )
            query_understanding = QueryUnderstanding(
                intent="explicit_fanout_query",
                source_kind="orchestration",
                task_kind="explicit_fanout_query",
                modality="multi",
                route="explicit_fanout",
                execution_posture="explicit_fanout",
                direct_route_reason="explicit_structured_plan",
                reasons=["explicit_structured_plan"],
            )
            active_skill = None
            tool_input = {}
            structured_binding = None
            execution_kind = "agent"
            execution_mode = "explicit_fanout"
        return QueryPlan(
            session_id=session_id,
            message=message,
            history=history,
            subqueries=subqueries,
            subtasks=subtasks,
            bundle_plan=bundle_plan,
            memory_intent=memory_intent,
            query_understanding=query_understanding,
            execution_mode=execution_mode,
            active_skill=active_skill,
            tool_input=tool_input,
            structured_binding=structured_binding,
            execution_kind=execution_kind,
            executions=executions,
            ephemeral_system_messages=list(ephemeral_system_messages or []),
            dispatch_plan=getattr(root_execution, "dispatch_plan", None),
        )

    def _build_compound_executions(
        self,
        *,
        history: list[dict[str, Any]],
        subtasks: list[SubtaskPlan],
        root_execution: QueryExecutionPlan,
        authority_context: dict[str, Any] | None = None,
    ) -> list[QueryExecutionPlan]:
        executions: list[QueryExecutionPlan] = []
        authority_context = self._merge_authoritative_context(
            authority_context,
            self._authoritative_context_from_execution(root_execution),
        )
        for subtask in subtasks:
            execution = self._build_execution(
                message=subtask.execution_message,
                history=history,
                ephemeral_system_messages=root_execution.ephemeral_system_messages,
                authority_context=authority_context,
            )
            executions.append(self._attach_subtask_metadata(execution, subtask))
            authority_context = self._merge_authoritative_context(
                authority_context,
                self._authoritative_context_from_execution(execution),
            )
        return executions

    def _build_bundle_executions(
        self,
        *,
        history: list[dict[str, Any]],
        bundle_plan: BundlePlan,
        root_execution: QueryExecutionPlan,
        authority_context: dict[str, Any] | None = None,
    ) -> list[QueryExecutionPlan]:
        executions: list[QueryExecutionPlan] = []
        authority_context = self._merge_authoritative_context(
            authority_context,
            self._authoritative_context_from_execution(root_execution),
        )
        for item in bundle_plan.items:
            execution = self._build_execution(
                message=item.execution_message,
                history=history,
                ephemeral_system_messages=root_execution.ephemeral_system_messages,
                authority_context=authority_context,
            )
            execution = self._attach_bundle_metadata(execution, bundle_plan, item)
            executions.append(execution)
            authority_context = self._merge_authoritative_context(
                authority_context,
                self._authoritative_context_from_execution(execution),
            )
        return executions

    def _attach_subtask_metadata(
        self,
        execution: QueryExecutionPlan,
        subtask: SubtaskPlan,
    ) -> QueryExecutionPlan:
        execution.subtask_id = subtask.subtask_id
        execution.subtask_goal = subtask.goal
        execution.subtask_title = subtask.user_visible_title
        execution.subtask_refs = dict(subtask.refs)
        execution.subtask_depends_on = list(subtask.depends_on)
        execution.subtask_origin = subtask.origin
        return execution

    def _attach_bundle_metadata(
        self,
        execution: QueryExecutionPlan,
        bundle_plan: BundlePlan,
        item: BundleItemPlan,
    ) -> QueryExecutionPlan:
        execution.bundle_id = bundle_plan.bundle_id
        execution.bundle_item_id = item.item_id
        execution.bundle_item_index = item.index
        execution.bundle_origin = item.origin
        return execution

    def _resolve_active_skill(
        self,
        message: str,
        query_understanding: QueryUnderstanding,
    ) -> SkillDefinition | None:
        # Planning carries the full SkillDefinition so later phases can use the
        # runtime contract. SkillPolicyResolver consumes only structured task
        # fields; prompt text and routing hints are not execution authority.
        if self.skill_policy_resolver is None:
            return None
        frame = self.skill_policy_resolver.resolve(task_frame=query_understanding)
        if frame is None:
            return None
        query_understanding.skill_name = frame.name
        query_understanding.reasons.append("skill_policy_resolved")
        return frame.skill

    def _build_execution(
        self,
        *,
        message: str,
        history: list[dict[str, Any]],
        ephemeral_system_messages: list[str] | None = None,
        authority_context: dict[str, Any] | None = None,
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
        query_understanding = self.continuation_resolver.apply_authoritative_context(
            message=message,
            understanding=query_understanding,
            authority_context=authority_context,
        )
        active_skill = self._resolve_active_skill(message, query_understanding)
        dispatch_plan = self.dispatch_scheduler.resolve(
            task_frame=query_understanding,
            active_skill=active_skill,
            tool_registry=self.tool_runtime.registry,
        )
        structured_binding = self.binding_resolver.resolve(
            message=message,
            understanding=query_understanding,
            history=history,
        )
        if (
            structured_binding is not None
            and "compound_authoritative_dataset_context" in list(getattr(query_understanding, "reasons", []) or [])
            and structured_binding.source == "prebound_tool_input"
            and not structured_binding.explicit_switch
        ):
            structured_binding.source = "compound_authority"
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
            execution_posture=str(getattr(query_understanding, "execution_posture", "") or ""),
            dispatch_plan=dispatch_plan,
            ephemeral_system_messages=list(ephemeral_system_messages or []),
        )

    def _authoritative_context_from_execution(
        self,
        execution: QueryExecutionPlan,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        tool_name = str(getattr(execution.query_understanding, "tool_name", "") or "").strip()
        tool_input = dict(getattr(execution, "tool_input", {}) or getattr(execution.query_understanding, "tool_input", {}) or {})
        pdf_path = str(tool_input.get("path", "") or "").strip()
        if tool_name == "pdf_analysis" and pdf_path:
            context["active_pdf"] = pdf_path
        binding = getattr(execution, "structured_binding", None)
        dataset_path = str(getattr(binding, "dataset_path", "") or "").strip()
        if dataset_path:
            binding_source = str(getattr(binding, "source", "") or "").strip()
            if binding_source in {"prebound_tool_input", "explicit_path", "compound_authority"}:
                context["active_dataset"] = dataset_path
        return context

    def _merge_authoritative_context(
        self,
        existing: dict[str, Any] | None,
        latest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(existing or {})
        for key, value in dict(latest or {}).items():
            if value:
                merged[key] = value
        return merged
