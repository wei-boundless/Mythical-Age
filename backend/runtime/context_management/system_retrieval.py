from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from capability_system.local_mcp_registry import get_local_mcp_unit, get_local_mcp_unit_for_source_kind
from capability_system.search_policy import operation_allowed_by_search_policy
from evidence import MCPExecutionPlan, MCPRequest
from request_intent.frame_access import explicit_paths, turn_signals
from task_system.tasks.run_models import (
    TaskRunLedger,
    advance_task_run_ledger,
    complete_task_run_step,
    current_task_step_run,
    find_task_step_run,
    step_supports_operation,
)


@dataclass(slots=True)
class SystemRetrievalOutcome:
    events: list[dict[str, Any]] = field(default_factory=list)
    ledger: TaskRunLedger | None = None
    state: Any | None = None
    result_refs: list[str] = field(default_factory=list)
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    retrieval_results: list[dict[str, Any]] = field(default_factory=list)


class SystemRetrievalStage:
    """System-owned evidence retrieval before the agent model turn executes."""

    def __init__(
        self,
        *,
        evidence_orchestrator: Any,
        event_log: Any,
        record_task_run_step_event: Any,
        record_task_run_ledger_updated: Any,
        state_with_task_run_ledger: Any,
        write_checkpoint_event: Any,
    ) -> None:
        self.evidence_orchestrator = evidence_orchestrator
        self.event_log = event_log
        self.record_task_run_step_event = record_task_run_step_event
        self.record_task_run_ledger_updated = record_task_run_ledger_updated
        self.state_with_task_run_ledger = state_with_task_run_ledger
        self.write_checkpoint_event = write_checkpoint_event

    def should_run(
        self,
        *,
        query_understanding: dict[str, Any],
        selected_recipe_payload: dict[str, Any],
        task_operation: dict[str, Any],
        allowed_search_sources: set[str],
        professional_task: bool,
    ) -> bool:
        operation_requirement = dict(task_operation.get("operation_requirement") or {})
        resolution = dict(dict(operation_requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})
        if str(resolution.get("execution_mode") or "").strip() == "delegate":
            return False
        if professional_task:
            return False
        source_kind = system_retrieval_source_kind(
            selected_recipe_payload=selected_recipe_payload,
            query_understanding=query_understanding,
        )
        unit = get_local_mcp_unit_for_source_kind(source_kind)
        if unit is not None:
            return operation_allowed_by_search_policy(
                str(getattr(unit, "operation_id", "") or ""),
                allowed_search_sources,
            )
        return (
            source_kind in {"knowledge", "knowledge_base", "retrieval"}
            and operation_allowed_by_search_policy("op.mcp_retrieval", allowed_search_sources)
        )

    async def run(
        self,
        *,
        task_run_id: str,
        session_id: str,
        task_id: str,
        user_message: str,
        current_turn_context: dict[str, Any],
        query_understanding: dict[str, Any],
        selected_recipe_payload: dict[str, Any],
        task_spec_payload: dict[str, Any],
        task_contract_ref: str,
        runtime_task_ledger: TaskRunLedger | None,
        state: Any,
        allowed_search_sources: set[str],
    ) -> SystemRetrievalOutcome:
        outcome = SystemRetrievalOutcome(ledger=runtime_task_ledger, state=state)
        if self.evidence_orchestrator is None:
            return outcome

        mcp_route, operation_id, bindings, constraints, answer_source = build_system_retrieval_request_parts(
            user_message=user_message,
            current_turn_context=current_turn_context,
            query_understanding=query_understanding,
            selected_recipe_payload=selected_recipe_payload,
            task_spec_payload=task_spec_payload,
        )
        if not operation_allowed_by_search_policy(operation_id, allowed_search_sources):
            blocked_event = self.event_log.append(
                task_run_id,
                "system_retrieval_blocked_by_search_policy",
                payload={
                    "mcp_route": mcp_route,
                    "operation_id": operation_id,
                    "allowed_sources": sorted(allowed_search_sources),
                },
                refs={"task_contract_ref": task_contract_ref, "operation_id": operation_id},
            )
            outcome.events.append({"type": "runtime_loop_event", "event": blocked_event.to_dict()})
            return outcome

        retrieval_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={"executor_type": "mcp", "runtime_channel": "system_retrieval", "mcp_route": mcp_route},
            refs={"task_contract_ref": task_contract_ref, "operation_id": operation_id},
        )
        outcome.events.append({"type": "runtime_loop_event", "event": retrieval_event.to_dict()})

        mcp_request = MCPRequest(
            request_id=f"mcpreq:{task_id}:{mcp_route}",
            session_id=session_id,
            query=str(user_message),
            mcp_route=mcp_route,
            task_frame={
                "task_id": task_id,
                "authority": str(query_understanding.get("authority") or ""),
                "model_turn_decision": dict(query_understanding.get("model_turn_decision") or {}),
            },
            bindings=bindings,
            constraints=constraints,
            owner_task_id=task_id,
            arbitration_reason=f"system_{mcp_route}_pre_execution",
            message_id=f"{task_id}:{mcp_route}",
        )
        mcp_plan = MCPExecutionPlan(
            mcp_route=mcp_route,
            request=mcp_request,
            expected_result="canonical",
            fallback_execution_kind="none",
            cutover_mode="primary",
        )

        done_event: dict[str, Any] | None = None
        async for event in self.evidence_orchestrator.stream_execution(
            session_id=session_id,
            execution=None,
            mcp_plan=mcp_plan,
            main_context={},
            trace=None,
        ):
            if event.get("type") == "retrieval":
                outcome.retrieval_results = [dict(item) for item in list(event.get("results") or [])]
            if event.get("type") == "done":
                done_event = dict(event)
                continue
            outcome.events.append(dict(event))

        if done_event is None:
            return outcome

        result_ref = f"mcp_result:{mcp_request.request_id}"
        outcome.result_refs.append(result_ref)
        outcome.main_context = dict(done_event.get("main_context") or {})
        outcome.task_summary_refs = [dict(item) for item in list(done_event.get("task_summary_refs") or [])]
        current_step = current_task_step_run(outcome.ledger)
        if (
            outcome.ledger is not None
            and current_step is not None
            and current_step.status == "running"
            and current_step.executor_type == "mcp"
            and step_supports_operation(current_step, operation_id)
        ):
            outcome.ledger = complete_task_run_step(
                outcome.ledger,
                step_id=current_step.step_id,
                completed_at=time.time(),
                observation_refs=(result_ref,),
                output_refs=(result_ref,),
                step_result_ref=result_ref,
                executor_ref=operation_id,
                diagnostics={"transition_reason": f"{mcp_route}_system_retrieval_completed"},
            )
            completed_step = find_task_step_run(outcome.ledger, current_step.step_id)
            if completed_step is not None:
                step_completed_event = self.record_task_run_step_event(
                    task_run_id,
                    event_type="step_completed",
                    step_run=completed_step,
                    ledger=outcome.ledger,
                    reason=f"{mcp_route}_system_retrieval_completed",
                    refs={"operation_id": operation_id},
                )
                outcome.events.append({"type": "runtime_loop_event", "event": step_completed_event.to_dict()})
            outcome.ledger = advance_task_run_ledger(
                outcome.ledger,
                started_at=time.time(),
                diagnostics={"transition_reason": f"{mcp_route}_system_retrieval_completed"},
            )
            ledger_event = self.record_task_run_ledger_updated(
                task_run_id,
                ledger=outcome.ledger,
                reason=f"{mcp_route}_system_retrieval_completed",
                refs={"operation_id": operation_id},
            )
            outcome.events.append({"type": "runtime_loop_event", "event": ledger_event.to_dict()})
            entered_step = current_task_step_run(outcome.ledger)
            if entered_step is not None and entered_step.step_id != current_step.step_id:
                step_entered_event = self.record_task_run_step_event(
                    task_run_id,
                    event_type="step_entered",
                    step_run=entered_step,
                    ledger=outcome.ledger,
                    reason=f"{mcp_route}_system_retrieval_completed",
                    refs={"operation_id": operation_id},
                )
                outcome.events.append({"type": "runtime_loop_event", "event": step_entered_event.to_dict()})
            outcome.state = self.state_with_task_run_ledger(
                outcome.state,
                outcome.ledger,
                result_refs=outcome.result_refs,
                diagnostics={"last_step_transition": f"{mcp_route}_system_retrieval_completed"},
            )
            checkpoint_event = self.write_checkpoint_event(outcome.state, event_offset=ledger_event.offset)
            outcome.events.append({"type": "runtime_loop_event", "event": checkpoint_event.to_dict()})

        if outcome.main_context:
            outcome.main_context.setdefault("answer_source", answer_source)
        return outcome


def build_context_policy_with_retrieval(
    *,
    agent_runtime_chain: Any,
    session_id: str,
    user_message: str,
    memory_intent: Any | None,
    task_operation: dict[str, Any],
    retrieval_results: list[dict[str, Any]] | None,
    allowed_search_sources: set[str],
) -> dict[str, Any]:
    memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
    retrieval_allowed = task_operation_allows_context_retrieval(
        task_operation=task_operation,
        allowed_search_sources=allowed_search_sources,
    )
    context_policy_result = agent_runtime_chain.build_context_policy_result(
        session_id=session_id,
        message=user_message,
        memory_intent=memory_intent,
        memory_request_profile=memory_request_profile,
        retrieval_results=retrieval_results if retrieval_allowed else None,
        retrieval_allowed=retrieval_allowed,
    )
    if context_policy_result is None:
        return {}
    if hasattr(context_policy_result, "to_dict"):
        return dict(context_policy_result.to_dict())
    return dict(context_policy_result)


def build_system_retrieval_request_parts(
    *,
    user_message: str,
    current_turn_context: dict[str, Any],
    query_understanding: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
    task_spec_payload: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
    source_kind = system_retrieval_source_kind(
        selected_recipe_payload=selected_recipe_payload,
        query_understanding=query_understanding,
    )
    unit = get_local_mcp_unit_for_source_kind(source_kind)
    parameters: dict[str, Any] = {}
    paths = explicit_paths(query_understanding)
    if paths:
        parameters["path"] = paths[0]
    bindings: dict[str, Any] = {}
    constraints: dict[str, Any] = {}
    if unit is not None:
        path_key = str(unit.request_path_parameter or "").strip()
        binding_key = str(unit.followup_binding_key or "").strip()
        if path_key and binding_key and binding_key != "current_turn_context":
            path = str(
                parameters.get(path_key)
                or path_from_context_recall(
                    current_turn_context,
                    source_kind=str(unit.source_kind or source_kind or ""),
                    binding_key=binding_key,
                )
                or ""
            ).strip()
            bindings = {binding_key: path} if path else {}
            constraints = {path_key: path} if path else {}
        if unit.request_mode_parameter:
            mode_key = str(unit.request_mode_parameter).strip()
            mode = str(parameters.get(mode_key) or unit.request_default_mode or "").strip()
            if mode:
                constraints[mode_key] = mode
        if binding_key == "current_turn_context":
            bindings = {"current_turn_context": dict(current_turn_context or {})}
        return unit.route, unit.operation_id, bindings, constraints, unit.answer_source
    bindings = {"current_turn_context": dict(current_turn_context or {})}
    retrieval_unit = get_local_mcp_unit("retrieval")
    if retrieval_unit is not None:
        return retrieval_unit.route, retrieval_unit.operation_id, bindings, {}, retrieval_unit.answer_source
    return "retrieval", "op.mcp_retrieval", bindings, {}, "runtime_rag_mcp"


def final_main_context_can_finalize(
    *,
    selected_recipe_payload: dict[str, Any],
    retrieval_results: list[dict[str, Any]] | None,
) -> bool:
    source_kind = str(
        selected_recipe_payload.get("source_kind")
        or dict(selected_recipe_payload.get("metadata") or {}).get("source_kind")
        or ""
    ).strip()
    unit = get_local_mcp_unit_for_source_kind(source_kind)
    if unit is not None and unit.route != "retrieval":
        return True
    return bool(retrieval_results)


def path_from_context_recall(
    current_turn_context: dict[str, Any],
    *,
    source_kind: str,
    binding_key: str,
) -> str:
    source = str(source_kind or "").strip()
    key = str(binding_key or "").strip()
    for candidate in list(dict(current_turn_context or {}).get("context_recall_candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if source and str(candidate.get("source_kind") or "").strip() != source:
            continue
        payload = dict(candidate.get("recall_payload") or {})
        constraints = dict(payload.get("active_constraints") or {})
        for candidate_key in (key, "path", "file_path"):
            path = str(payload.get(candidate_key) or constraints.get(candidate_key) or "").strip()
            if path:
                return path
    return ""


def task_operation_allows_context_retrieval(
    *,
    task_operation: dict[str, Any],
    allowed_search_sources: set[str],
) -> bool:
    if not operation_allowed_by_search_policy("op.mcp_retrieval", allowed_search_sources):
        return False
    return task_operation_requests_context_retrieval(task_operation)


def task_operation_requests_context_retrieval(task_operation: dict[str, Any]) -> bool:
    query_understanding = dict(task_operation.get("query_understanding") or {})
    context_binding = dict(query_understanding.get("context_binding") or {})
    if str(context_binding.get("kind") or "") == "explicit_task_selection":
        return False
    signals = turn_signals(query_understanding)
    if bool(signals.get("memory_recall_required")):
        return False
    current_turn = dict(task_operation.get("current_turn_context") or {})
    if _selection_is_coordination_task(current_turn):
        return False
    assembly = dict(task_operation.get("task_execution_assembly") or {})
    if str(assembly.get("runtime_lane") or "").strip() == "coordination_task":
        return False
    operation_requirement = dict(task_operation.get("operation_requirement") or {})
    operations = {
        str(item or "").strip()
        for item in [
            *list(operation_requirement.get("required_operations") or []),
            *list(operation_requirement.get("optional_operations") or []),
        ]
        if str(item or "").strip()
    }
    if "op.mcp_retrieval" in operations:
        return True
    recipe = dict(task_operation.get("selected_recipe") or {})
    return str(recipe.get("source_kind") or "").strip() in {"knowledge", "retrieval", "knowledge_base"}


def system_retrieval_source_kind(
    *,
    selected_recipe_payload: dict[str, Any],
    query_understanding: dict[str, Any],
) -> str:
    return str(
        selected_recipe_payload.get("source_kind")
        or dict(selected_recipe_payload.get("metadata") or {}).get("source_kind")
        or _source_kind_from_model_decision(query_understanding)
        or ""
    ).strip()


def _source_kind_from_model_decision(query_understanding: dict[str, Any]) -> str:
    decision = dict(dict(query_understanding or {}).get("model_turn_decision") or {})
    action_intent = str(decision.get("action_intent") or "").strip()
    targets = [str(item).strip().lower() for item in list(decision.get("target_objects") or []) if str(item).strip()]
    if action_intent == "search_external":
        return "external_web"
    if any(target.endswith(".pdf") for target in targets):
        return "pdf"
    if any(target.endswith((".csv", ".tsv", ".xlsx", ".xls", ".parquet")) for target in targets):
        return "dataset"
    if any(target.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".md", ".txt", ".json", ".yaml", ".yml", ".toml")) for target in targets):
        return "workspace"
    if action_intent in {"read_context", "edit_workspace", "run_command", "start_service"}:
        return "workspace"
    return ""


def _selection_is_coordination_task(selection: dict[str, Any]) -> bool:
    return bool(
        str(selection.get("coordination_run_id") or "").strip()
        or str(selection.get("continuation_stage_id") or "").strip()
        or str(selection.get("stage_execution_request_id") or "").strip()
        or dict(selection.get("stage_execution_request") or {})
    )
