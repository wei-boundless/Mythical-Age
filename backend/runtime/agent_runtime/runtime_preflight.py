from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from permissions import OperationGatePipelineContext
from task_system.tasks.run_models import (
    current_task_step_run,
    start_task_run_step,
)

from ..context_management.system_retrieval import SystemRetrievalStage
from ..shared.loop_control import check_runtime_loop_control
from ..shared.models import RuntimeLoopState
from .admission_preflight import prepare_agent_runtime_admission
from .context import (
    agent_invocation_diagnostics,
    assembly_contract_diagnostics,
    build_initial_task_run_ledger,
    diagnostic_int,
    intent_continuation_trace_events,
    persist_agent_invocation_boundary_objects,
)
from .context_preflight import prepare_agent_runtime_context
from .environment_preflight import prepare_agent_runtime_environment
from .execution_permit import execution_permit_diagnostics
from .phase_pipeline import append_pre_model_phase_events
from .runtime_policy import (
    artifact_policy_from_task_execution_assembly,
    model_stream_policy_from_task_execution_assembly,
)


@dataclass(slots=True)
class AgentRuntimePreflightInput:
    runtime_host: Any
    start: Any
    session_id: str
    task_id: str
    user_message: str
    history: list[dict[str, Any]]
    source: str
    task_selection: dict[str, Any]
    runtime_context_override: dict[str, Any]
    search_policy: list[str] | None
    allowed_search_sources: set[str]
    agent_runtime_chain: Any
    model_response_executor: Any
    runtime_context_manager: Any
    memory_intent: Any
    model_selection: dict[str, Any]
    tool_instances: list[Any]
    task_operation: dict[str, Any]
    task_contract: dict[str, Any]
    task_intent_contract: dict[str, Any]
    selected_recipe_payload: dict[str, Any]
    bundle_spec_payload: dict[str, Any]
    task_spec_payload: dict[str, Any]
    task_execution_assembly_payload: dict[str, Any]
    task_flow_contract_binding_payload: dict[str, Any]
    task_execution_policy_payload: dict[str, Any]
    task_memory_request_profile_payload: dict[str, Any]
    task_communication_protocol_payload: dict[str, Any]
    task_graph_payload: dict[str, Any]
    runtime_spec_payload: dict[str, Any]
    graph_payload: dict[str, Any]
    task_body_orchestration_payload: dict[str, Any]
    agent_runtime_spec_payload: dict[str, Any]
    invocation_payload: dict[str, Any]
    assembly_contract: dict[str, Any]
    effective_agent_runtime_profile: Any
    execution_permit: dict[str, Any]
    agent_runtime_config: Any
    agent_runtime_enabled_phases: set[str]
    memory_view: dict[str, Any]
    context_policy: dict[str, Any]
    execution_mode: str
    effective_limits: Any


@dataclass(slots=True)
class AgentRuntimePreflightResult:
    state: RuntimeLoopState
    runtime_task_ledger: Any
    result_refs: list[str]
    final_main_context: dict[str, Any]
    final_task_summary_refs: list[dict[str, Any]]
    task_contract_ref: str
    current_turn_context: dict[str, Any]
    model_stream_policy: dict[str, Any]
    artifact_policy_for_validation: dict[str, Any]
    sandbox_policy: dict[str, Any]
    file_management_policy: dict[str, Any]
    directive: Any
    resource_policy: Any
    runtime_tool_instances: list[Any]
    resolved_model_spec: Any | None
    context_snapshot: Any
    terminal: bool = False


async def run_agent_runtime_preflight(
    preflight_input: AgentRuntimePreflightInput,
) -> AsyncIterator[dict[str, Any] | AgentRuntimePreflightResult]:
    """Prepare the system-owned runtime environment before model/tool execution."""

    item = preflight_input
    runtime_host = item.runtime_host
    start = item.start
    state = start.loop_state
    result_refs: list[str] = []
    final_main_context: dict[str, Any] = {}
    final_task_summary_refs: list[dict[str, Any]] = []

    environment_preflight = prepare_agent_runtime_environment(
        runtime_host=runtime_host,
        session_id=item.session_id,
        task_run_id=state.task_run_id,
        task_id=item.task_id,
        task_contract=item.task_contract,
        user_message=item.user_message,
        selected_recipe_payload=item.selected_recipe_payload,
        task_selection=item.task_selection,
        runtime_context_override=item.runtime_context_override,
        search_policy=item.search_policy,
        allowed_search_sources=item.allowed_search_sources,
    )
    sandbox_policy = environment_preflight.sandbox_policy
    file_management_policy = environment_preflight.file_management_policy
    for environment_event in environment_preflight.events:
        yield environment_event
    yield {
        "type": "runtime_loop_started",
        "task_run": start.task_run.to_dict(),
        "agent_run": start.agent_run.to_dict(),
        "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
        "checkpoint": start.checkpoint.to_dict(),
        "events": [dict(event) for event in start.events],
    }
    for event in start.events:
        yield {"type": "runtime_loop_event", "event": dict(event)}

    task_contract_ref = str(item.task_contract.get("task_id") or item.task_id)
    runtime_task_ledger = build_initial_task_run_ledger(
        task_run_id=state.task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec_payload=item.task_spec_payload,
        selected_recipe_payload=item.selected_recipe_payload,
    )
    if runtime_task_ledger is not None:
        runtime_task_ledger = start_task_run_step(
            runtime_task_ledger,
            started_at=time.time(),
            diagnostics={"transition_reason": "task_contract_built"},
        )
    runtime_boundary_refs = persist_agent_invocation_boundary_objects(
        runtime_host.runtime_objects,
        task_run_id=state.task_run_id,
        agent_invocation=item.invocation_payload,
        assembly_contract=item.assembly_contract,
        execution_permit=item.execution_permit,
    )
    task_event = runtime_host.event_log.append(
        state.task_run_id,
        "task_contract_built",
        payload={
            "task_contract": item.task_contract,
            "task_intent_contract": item.task_intent_contract,
            "selected_recipe": item.selected_recipe_payload,
            "bundle_spec": item.bundle_spec_payload,
            "task_spec": item.task_spec_payload,
            "task_execution_assembly": item.task_execution_assembly_payload,
            "task_flow_contract_binding": item.task_flow_contract_binding_payload,
            "task_execution_policy": item.task_execution_policy_payload,
            "task_memory_request_profile": item.task_memory_request_profile_payload,
            "task_communication_protocol": item.task_communication_protocol_payload,
            "graph_record": item.graph_payload,
            "task_graph_record": item.task_graph_payload,
            "task_graph_runtime_spec": item.runtime_spec_payload,
            "task_body_orchestration": item.task_body_orchestration_payload,
            "agent_runtime_spec": item.agent_runtime_spec_payload,
            "agent_runtime_config": item.agent_runtime_config.to_dict(),
            "agent_invocation": agent_invocation_diagnostics(item.invocation_payload),
            "agent_assembly_contract": assembly_contract_diagnostics(item.assembly_contract),
            "execution_permit": execution_permit_diagnostics(item.execution_permit),
            "runtime_boundary_objects": dict(runtime_boundary_refs),
            "task_run_ledger": runtime_task_ledger.to_dict() if runtime_task_ledger is not None else {},
            "sandbox_policy": sandbox_policy,
            "source": item.source,
        },
        refs={
            "task_contract_ref": task_contract_ref,
            "task_intent_ref": str(item.task_intent_contract.get("task_intent_id") or ""),
            "task_template_id": str(
                item.selected_recipe_payload.get("template_id")
                or item.selected_recipe_payload.get("recipe_id")
                or ""
            ),
            "task_spec_ref": str(item.task_spec_payload.get("task_spec_ref") or ""),
            "task_execution_assembly_ref": str(item.task_execution_assembly_payload.get("assembly_id") or ""),
            "task_flow_contract_binding_ref": str(item.task_flow_contract_binding_payload.get("binding_id") or ""),
            "task_execution_policy_ref": str(item.task_execution_policy_payload.get("policy_id") or ""),
            "task_memory_request_profile_ref": str(item.task_memory_request_profile_payload.get("profile_id") or ""),
            "task_communication_protocol_ref": str(item.task_communication_protocol_payload.get("protocol_id") or ""),
            "graph_ref": str(
                item.task_graph_payload.get("graph_id")
                or item.graph_payload.get("graph_id")
                or item.graph_payload.get("task_graph_id")
                or ""
            ),
            "task_body_orchestration_ref": str(item.task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(item.agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            "agent_invocation_ref": str(item.invocation_payload.get("invocation_id") or ""),
            "agent_assembly_contract_ref": str(item.assembly_contract.get("assembly_id") or ""),
            "work_order_ref": str(item.assembly_contract.get("work_order_id") or ""),
            "execution_permit_ref": str(item.execution_permit.get("permit_id") or ""),
            "agent_invocation_object_ref": str(runtime_boundary_refs.get("agent_invocation_object_ref") or ""),
            "agent_assembly_object_ref": str(runtime_boundary_refs.get("agent_assembly_object_ref") or ""),
            "execution_permit_object_ref": str(runtime_boundary_refs.get("execution_permit_object_ref") or ""),
            "bundle_spec_ref": str(item.bundle_spec_payload.get("bundle_id") or ""),
            "task_run_ledger_ref": runtime_task_ledger.ledger_id if runtime_task_ledger is not None else "",
        },
    )
    yield {"type": "runtime_loop_event", "event": task_event.to_dict()}
    runtime_object_events = runtime_host._sync_runtime_objects_after_task_contract(
        start_result=start,
        event_offset=task_event.offset,
        execution_mode=item.execution_mode,
        task_agent_binding_ref=str(item.task_execution_assembly_payload.get("task_agent_binding_ref") or ""),
        graph_payload=item.graph_payload,
        task_graph_payload=item.task_graph_payload,
        communication_protocol_payload=item.task_communication_protocol_payload,
        task_execution_policy_payload=item.task_execution_policy_payload,
        effective_limits=item.effective_limits,
        task_spec_payload=item.task_spec_payload,
    )
    for runtime_event in runtime_object_events:
        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
    latest_streamed_offset = max(
        [task_event.offset, *[int(getattr(event, "offset", -1)) for event in runtime_object_events]],
        default=task_event.offset,
    )
    for logged_event in runtime_host.event_log.list_events(state.task_run_id):
        if logged_event.offset > latest_streamed_offset:
            yield {"type": "runtime_loop_event", "event": logged_event.to_dict()}
            latest_streamed_offset = max(latest_streamed_offset, logged_event.offset)

    current_worker_spawn_results = runtime_host.state_index.list_task_worker_spawn_results(state.task_run_id)
    current_worker_agent_runs = [
        run
        for run in runtime_host.state_index.list_task_agent_runs(state.task_run_id)
        if str(run.spawn_mode or "") == "worker_spawn"
    ]
    runtime_execution_facts = {
        "worker_spawn_summary": {
            "spawn_request_count": len(runtime_host.state_index.list_task_worker_spawn_requests(state.task_run_id)),
            "spawn_result_count": len(current_worker_spawn_results),
            "spawned_agent_ids": [
                str(result.spawned_agent_id or "")
                for result in current_worker_spawn_results
                if str(result.status or "") == "spawned" and str(result.spawned_agent_id or "")
            ],
            "blocked_spawn_count": sum(
                1 for result in current_worker_spawn_results if str(result.status or "") == "blocked"
            ),
            "worker_agent_run_ids": [
                str(run.agent_run_id or "")
                for run in current_worker_agent_runs
                if str(run.agent_run_id or "")
            ],
        }
    }
    if runtime_task_ledger is not None:
        current_step = current_task_step_run(runtime_task_ledger)
        if current_step is not None:
            step_event = runtime_host._record_task_run_step_event(
                state.task_run_id,
                event_type="step_entered",
                step_run=current_step,
                ledger=runtime_task_ledger,
                reason="task_contract_built",
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
            ledger_event = runtime_host._record_task_run_ledger_updated(
                state.task_run_id,
                ledger=runtime_task_ledger,
                reason="task_contract_built",
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}

    current_turn_context = dict(item.task_operation.get("current_turn_context") or {})
    model_stream_policy = model_stream_policy_from_task_execution_assembly(
        item.task_execution_assembly_payload,
        current_turn_context=current_turn_context,
        agent_assembly_contract=item.assembly_contract,
        runtime_policy=dict(item.task_operation.get("runtime_stream_policy") or {}),
    )
    artifact_policy_for_validation = artifact_policy_from_task_execution_assembly(
        selected_recipe_payload=item.selected_recipe_payload,
        task_execution_assembly=item.task_execution_assembly_payload,
        current_turn_context=current_turn_context,
        agent_assembly_contract=item.assembly_contract,
        runtime_policy=dict(item.task_operation.get("runtime_artifact_policy") or {}),
    )
    if current_turn_context:
        current_turn_event = runtime_host.event_log.append(
            state.task_run_id,
            "current_turn_context_resolved",
            payload={
                "current_turn_context": current_turn_context,
                "execution_mode": str(current_turn_context.get("execution_mode") or ""),
                "stream_policy": model_stream_policy,
                "bundle_id": str(current_turn_context.get("bundle_id") or ""),
                "bundle_item_count": len(list(current_turn_context.get("bundle_items") or [])),
                "followup_target_count": len(list(current_turn_context.get("followup_target_refs") or [])),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": current_turn_event.to_dict()}
        for trace_event in intent_continuation_trace_events(current_turn_context):
            trace_record = runtime_host.event_log.append(
                state.task_run_id,
                trace_event["event_type"],
                payload=dict(trace_event.get("payload") or {}),
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": trace_record.to_dict()}

    query_understanding = dict(item.task_operation.get("query_understanding") or {})
    retrieval_results: list[dict[str, Any]] | None = None
    system_retrieval_stage = SystemRetrievalStage(
        evidence_orchestrator=runtime_host.evidence_orchestrator,
        event_log=runtime_host.event_log,
        record_task_run_step_event=runtime_host._record_task_run_step_event,
        record_task_run_ledger_updated=runtime_host._record_task_run_ledger_updated,
        state_with_task_run_ledger=runtime_host._state_with_task_run_ledger,
        write_checkpoint_event=runtime_host._write_checkpoint_event,
    )
    if system_retrieval_stage.should_run(
        query_understanding=query_understanding,
        selected_recipe_payload=item.selected_recipe_payload,
        task_operation=item.task_operation,
        allowed_search_sources=item.allowed_search_sources,
        evidence_phase_required="evidence" in item.agent_runtime_enabled_phases,
    ):
        retrieval_outcome = await system_retrieval_stage.run(
            task_run_id=state.task_run_id,
            session_id=item.session_id,
            task_id=item.task_id,
            user_message=item.user_message,
            current_turn_context=current_turn_context,
            query_understanding=query_understanding,
            selected_recipe_payload=item.selected_recipe_payload,
            task_spec_payload=item.task_spec_payload,
            task_contract_ref=task_contract_ref,
            runtime_task_ledger=runtime_task_ledger,
            state=state,
            allowed_search_sources=item.allowed_search_sources,
        )
        runtime_task_ledger = retrieval_outcome.ledger
        state = retrieval_outcome.state
        retrieval_results = retrieval_outcome.retrieval_results
        result_refs.extend(list(retrieval_outcome.result_refs))
        final_main_context.update(dict(retrieval_outcome.main_context))
        final_task_summary_refs.extend(list(retrieval_outcome.task_summary_refs))
        for event in retrieval_outcome.events:
            yield event

    memory_event = runtime_host.event_log.append(
        state.task_run_id,
        "memory_runtime_view_built",
        payload={
            "memory_runtime_view_ref": str(item.memory_view.get("view_id") or ""),
            "conversation_candidate_count": diagnostic_int(item.memory_view, "conversation_candidate_count"),
            "state_candidate_count": diagnostic_int(item.memory_view, "state_candidate_count"),
            "long_term_candidate_count": diagnostic_int(item.memory_view, "long_term_candidate_count"),
        },
        refs={"memory_runtime_view_ref": str(item.memory_view.get("view_id") or "")},
    )
    yield {"type": "runtime_loop_event", "event": memory_event.to_dict()}
    admission_preflight = prepare_agent_runtime_admission(
        runtime_host=runtime_host,
        task_run_id=state.task_run_id,
        task_id=item.task_id,
        task_contract_ref=task_contract_ref,
        task_operation=item.task_operation,
        task_execution_assembly_payload=item.task_execution_assembly_payload,
        current_turn_context=current_turn_context,
        assembly_contract=item.assembly_contract,
        agent_runtime_spec_payload=item.agent_runtime_spec_payload,
        effective_agent_runtime_profile=item.effective_agent_runtime_profile,
        model_response_executor=item.model_response_executor,
        model_selection=item.model_selection,
        tool_instances=item.tool_instances,
        allowed_search_sources=item.allowed_search_sources,
        execution_permit=item.execution_permit,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_management_policy,
    )
    for admission_event in admission_preflight.events:
        yield admission_event
    directive = admission_preflight.directive
    resource_policy = admission_preflight.resource_policy
    current_turn_capability_plan_payload = admission_preflight.current_turn_capability_plan_payload
    tool_capability_overlay = admission_preflight.tool_capability_overlay
    resolved_model_spec = admission_preflight.resolved_model_spec
    task_safety_validators = admission_preflight.task_safety_validators
    runtime_tool_instances = admission_preflight.runtime_tool_instances
    runtime_capability_state = admission_preflight.runtime_capability_state
    pre_model_phase_result = append_pre_model_phase_events(
        runtime_host=runtime_host,
        task_run_id=state.task_run_id,
        task_contract_ref=task_contract_ref,
        task_id=item.task_id,
        selected_recipe_payload=item.selected_recipe_payload,
        agent_runtime_config=item.agent_runtime_config,
    )
    for phase_event in pre_model_phase_result.events:
        yield phase_event
    effective_runtime_execution_facts = {
        **dict(runtime_execution_facts or {}),
        **dict(pre_model_phase_result.runtime_execution_facts or {}),
        "runtime_capability_state": runtime_capability_state,
    }
    context_preflight = prepare_agent_runtime_context(
        runtime_host=runtime_host,
        state=state,
        runtime_task_ledger=runtime_task_ledger,
        session_id=item.session_id,
        task_id=item.task_id,
        user_message=item.user_message,
        history=item.history,
        memory_intent=item.memory_intent,
        memory_view=item.memory_view,
        context_policy=item.context_policy,
        retrieval_results=retrieval_results,
        agent_runtime_chain=item.agent_runtime_chain,
        task_operation=item.task_operation,
        allowed_search_sources=item.allowed_search_sources,
        task_contract_ref=task_contract_ref,
        task_body_orchestration_payload=item.task_body_orchestration_payload,
        agent_runtime_spec_payload=item.agent_runtime_spec_payload,
        assembly_contract=item.assembly_contract,
        runtime_context_manager=item.runtime_context_manager,
        effective_runtime_execution_facts=effective_runtime_execution_facts,
        selected_recipe_payload=item.selected_recipe_payload,
        task_spec_payload=item.task_spec_payload,
        effective_limits=item.effective_limits,
    )
    state = context_preflight.state
    context_snapshot = context_preflight.context_snapshot
    for context_event in context_preflight.events:
        yield context_event

    control_decision = check_runtime_loop_control(
        state,
        limits=item.effective_limits,
        started_at=start.task_run.created_at,
        model_call_count=0,
        event_count=len(runtime_host.event_log.list_events(state.task_run_id)),
    )
    control_event = runtime_host.event_log.append(
        state.task_run_id,
        "loop_control_checked",
        payload={"control": control_decision.to_dict()},
        refs={"task_contract_ref": task_contract_ref},
    )
    yield {"type": "runtime_loop_event", "event": control_event.to_dict()}
    yield {"type": "runtime_loop_control", "control": control_decision.to_dict()}
    if not control_decision.allowed:
        yield {
            "type": "error",
            "error": control_decision.reason,
            "content": control_decision.message or "RuntimeLoop 控制策略终止了本轮任务。",
            "answer_channel": "orchestration_fail_closed",
            "answer_source": "runtime_loop_control",
        }
        if runtime_task_ledger is not None and current_task_step_run(runtime_task_ledger) is not None:
            state, runtime_task_ledger, transition_events = runtime_host._apply_failed_step_transition(
                state=state,
                runtime_task_ledger=runtime_task_ledger,
                reason="runtime_loop_control",
                failure_reason=control_decision.reason,
                ledger_diagnostics={"terminal_reason": control_decision.reason},
            )
            for transition_event in transition_events:
                yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
        terminal_state = state.with_status(
            "failed",
            transition="stop_after_final_output",
            terminal_reason=control_decision.reason,
            diagnostics={"runtime_loop_control": control_decision.to_dict()},
        )
        terminal_event = runtime_host.event_log.append(
            terminal_state.task_run_id,
            "loop_terminal",
            payload={
                "terminal_reason": terminal_state.terminal_reason,
                "status": terminal_state.status,
                "runtime_loop_control": control_decision.to_dict(),
            },
        )
        yield {"type": "runtime_loop_event", "event": terminal_event.to_dict()}
        checkpoint_event = runtime_host._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
        finished = runtime_host.task_run_finalizer.upsert_finished_task_run(
            start_task_run=start.task_run,
            start_agent_run=start.agent_run,
            start_coordination_run=start.coordination_run,
            task_contract_ref=task_contract_ref,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            final_content="",
            diagnostics={"runtime_loop_control_reason": control_decision.reason},
        )
        for runtime_event in finished.events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        yield AgentRuntimePreflightResult(
            state=terminal_state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            task_contract_ref=task_contract_ref,
            current_turn_context=current_turn_context,
            model_stream_policy=model_stream_policy,
            artifact_policy_for_validation=artifact_policy_for_validation,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_management_policy,
            directive=directive,
            resource_policy=resource_policy,
            runtime_tool_instances=runtime_tool_instances,
            resolved_model_spec=resolved_model_spec,
            context_snapshot=context_snapshot,
            terminal=True,
        )
        return

    directive_event = runtime_host.event_log.append(
        state.task_run_id,
        "runtime_directive_issued",
        payload={
            "directive": directive.to_dict(),
            "resource_policy": resource_policy.to_dict(),
            "search_policy": list(item.search_policy) if item.search_policy is not None else None,
            "allowed_search_sources": sorted(item.allowed_search_sources),
            "current_turn_capability_plan": current_turn_capability_plan_payload,
            "tool_capability_table": tool_capability_overlay,
            "runtime_capability_state": runtime_capability_state,
            "sandbox_policy": sandbox_policy,
            "file_management_policy": file_management_policy,
            "effective_tool_names": [
                str(getattr(tool, "name", "") or "")
                for tool in list(runtime_tool_instances)
                if str(getattr(tool, "name", "") or "")
            ],
        },
        refs={
            "directive_ref": directive.directive_id,
            "resource_policy_ref": resource_policy.policy_id,
        },
    )
    yield {"type": "runtime_loop_event", "event": directive_event.to_dict()}
    yield {
        "type": "runtime_directive",
        "directive": directive.to_dict(),
        "resource_policy": resource_policy.to_dict(),
        "search_policy": list(item.search_policy) if item.search_policy is not None else None,
        "allowed_search_sources": sorted(item.allowed_search_sources),
        "current_turn_capability_plan": current_turn_capability_plan_payload,
        "tool_capability_table": tool_capability_overlay,
        "runtime_capability_state": runtime_capability_state,
        "sandbox_policy": sandbox_policy,
        "file_management_policy": file_management_policy,
        "effective_tool_names": [
            str(getattr(tool, "name", "") or "")
            for tool in list(runtime_tool_instances)
            if str(getattr(tool, "name", "") or "")
        ],
    }
    gate_result = runtime_host.operation_gate.check(
        "op.model_response",
        resource_policy=resource_policy,
        directive_ref=directive.directive_id,
        context=OperationGatePipelineContext(
            permission_mode=runtime_host._current_permission_mode(),
            operation_input={"operation_id": "op.model_response"},
            validators=task_safety_validators,
        ),
    )
    gate_event = runtime_host.event_log.append(
        state.task_run_id,
        "operation_gate_checked",
        payload={"gate": gate_result.to_dict()},
        refs={
            "operation_id": gate_result.operation_id,
            "directive_ref": directive.directive_id,
        },
    )
    yield {"type": "runtime_loop_event", "event": gate_event.to_dict()}
    yield {"type": "operation_gate", "gate": gate_result.to_dict()}
    if not gate_result.allowed:
        yield {
            "type": "error",
            "error": gate_result.reason,
            "content": "OperationGate 未放行模型回答，本轮停止执行。",
            "answer_channel": "orchestration_fail_closed",
            "answer_source": "operation_gate",
        }
        if runtime_task_ledger is not None and current_task_step_run(runtime_task_ledger) is not None:
            state, runtime_task_ledger, transition_events = runtime_host._apply_failed_step_transition(
                state=state,
                runtime_task_ledger=runtime_task_ledger,
                reason="operation_gate",
                refs={"operation_id": gate_result.operation_id},
                failure_reason="blocked_by_gate",
                diagnostics={"operation_id": gate_result.operation_id},
                ledger_diagnostics={"terminal_reason": "blocked_by_gate"},
            )
            for transition_event in transition_events:
                yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
        terminal_state = state.with_status(
            "blocked",
            transition="stop_after_final_output",
            terminal_reason="blocked_by_gate",
            diagnostics={"operation_gate_reason": gate_result.reason},
        )
        terminal_event = runtime_host.event_log.append(
            terminal_state.task_run_id,
            "loop_terminal",
            payload={
                "terminal_reason": terminal_state.terminal_reason,
                "status": terminal_state.status,
                "operation_gate_reason": gate_result.reason,
            },
        )
        yield {"type": "runtime_loop_event", "event": terminal_event.to_dict()}
        checkpoint_event = runtime_host._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
        finished = runtime_host.task_run_finalizer.upsert_finished_task_run(
            start_task_run=start.task_run,
            start_agent_run=start.agent_run,
            start_coordination_run=start.coordination_run,
            task_contract_ref=task_contract_ref,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            final_content="",
            diagnostics={"operation_gate_reason": gate_result.reason},
        )
        for runtime_event in finished.events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        yield AgentRuntimePreflightResult(
            state=terminal_state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            task_contract_ref=task_contract_ref,
            current_turn_context=current_turn_context,
            model_stream_policy=model_stream_policy,
            artifact_policy_for_validation=artifact_policy_for_validation,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_management_policy,
            directive=directive,
            resource_policy=resource_policy,
            runtime_tool_instances=runtime_tool_instances,
            resolved_model_spec=resolved_model_spec,
            context_snapshot=context_snapshot,
            terminal=True,
        )
        return

    yield AgentRuntimePreflightResult(
        state=state,
        runtime_task_ledger=runtime_task_ledger,
        result_refs=result_refs,
        final_main_context=final_main_context,
        final_task_summary_refs=final_task_summary_refs,
        task_contract_ref=task_contract_ref,
        current_turn_context=current_turn_context,
        model_stream_policy=model_stream_policy,
        artifact_policy_for_validation=artifact_policy_for_validation,
        sandbox_policy=sandbox_policy,
        file_management_policy=file_management_policy,
        directive=directive,
        resource_policy=resource_policy,
        runtime_tool_instances=runtime_tool_instances,
        resolved_model_spec=resolved_model_spec,
        context_snapshot=context_snapshot,
    )
