from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from runtime.shared.artifact_paths import validate_required_artifact_file
from harness.runtime.context import (
    agent_invocation_payload,
    assembly_contract_diagnostics,
    merge_invocation_identity_into_task_selection,
    resolve_runtime_search_sources,
    stage_execution_request_diagnostics,
)
from harness.runtime.execution_policy import (
    execution_permit_diagnostics,
)
from .agent_finalization import (
    AgentRunFinalizationInput,
    AgentRunFinalizationResult,
    finalize_agent_run,
)
from .agent_phase_pipeline import apply_post_model_phases
from harness.runtime import AgentRunRequest
from harness.runtime.agent_assembly import build_agent_runtime_assembly
from .agent_preflight import (
    AgentRuntimePreflightInput,
    AgentRuntimePreflightResult,
    run_agent_runtime_preflight,
)
from harness.runtime.turn_context import build_agent_turn_context
from .agent_turn_loop import AgentTurnLoopInput, AgentTurnLoopResult, run_agent_turn_loop


async def run_agent_invocation_stream(
    runtime_host: Any,
    request: AgentRunRequest,
) -> AsyncIterator[dict[str, Any]]:
    """Run one single-agent invocation through the AgentRuntime control chain."""

    session_id = request.session_id
    task_id = request.task_id
    user_message = request.user_message
    history = [dict(item) for item in request.history]
    source = request.source
    agent_runtime_chain = request.agent_runtime_chain
    model_response_executor = request.model_response_executor
    runtime_context_manager = request.runtime_context_manager
    memory_intent = request.memory_intent
    task_selection = dict(request.task_selection or {})
    assistant_message_committer = request.assistant_message_committer
    tool_runtime_executor = request.tool_runtime_executor
    tool_instances = list(request.tool_instances or [])
    agent_runtime_profile = request.agent_runtime_profile
    search_policy = list(request.search_policy) if request.search_policy is not None else None
    model_selection = dict(request.model_selection or {})
    agent_invocation = dict(request.agent_invocation or {})
    invocation_payload = agent_invocation_payload(
        agent_invocation
        or dict(dict(task_selection or {}).get("agent_invocation") or {})
    )
    invocation_is_explicit = bool(invocation_payload)
    assembly_contract = (
        dict(invocation_payload.get("assembly_contract") or {})
    )
    invocation_model_context = dict(
        invocation_payload.get("model_context")
        or invocation_payload.get("current_turn_context")
        or {}
    )
    runtime_chain_task_selection = dict(task_selection or {})
    if invocation_is_explicit:
        runtime_chain_task_selection = merge_invocation_identity_into_task_selection(
            task_selection=runtime_chain_task_selection,
            invocation_payload=invocation_payload,
            assembly_contract=assembly_contract,
        )
        runtime_chain_task_selection["agent_id"] = str(assembly_contract.get("agent_id") or "")
        runtime_chain_task_selection["agent_profile_id"] = str(assembly_contract.get("agent_profile_id") or "")
        runtime_chain_task_selection["runtime_lane"] = str(assembly_contract.get("runtime_lane") or "")
        runtime_chain_task_selection["assembly_id"] = str(assembly_contract.get("assembly_id") or "")
        runtime_chain_task_selection["work_order_id"] = str(assembly_contract.get("work_order_id") or "")
        runtime_chain_task_selection["executor_type"] = str(assembly_contract.get("executor_type") or "")
        runtime_chain_task_selection["agent_invocation_id"] = str(invocation_payload.get("invocation_id") or "")
        runtime_chain_task_selection.pop("agent_invocation", None)
    stream_policy = dict(runtime_chain_task_selection.get("stream_policy") or {})
    artifact_policy = dict(runtime_chain_task_selection.get("artifact_policy") or {})
    allowed_search_sources = resolve_runtime_search_sources(
        search_policy=search_policy,
        task_selection=runtime_chain_task_selection,
    )
    agent_turn_context = await build_agent_turn_context(
        session_id=session_id,
        task_id=task_id,
        user_message=user_message,
        source=source,
        task_selection=runtime_chain_task_selection,
        invocation_model_context=invocation_model_context,
        model_response_executor=model_response_executor,
    )
    request_facts = agent_turn_context.request_facts
    boundary_policy = agent_turn_context.boundary_policy
    context_candidates = agent_turn_context.context_candidates
    model_turn_decision = agent_turn_context.model_turn_decision
    model_turn_diagnostics = agent_turn_context.model_turn_diagnostics
    action_permit = agent_turn_context.action_permit
    runtime_start_packet = agent_turn_context.runtime_start_packet
    runtime_start_packet_payload = runtime_start_packet.to_dict()
    runtime_context_override = agent_turn_context.runtime_context_override
    if not agent_turn_context.action_allowed:
        denied_reasons = [
            str(item).strip()
            for item in list(action_permit.get("denied_reasons") or [])
            if str(item).strip()
        ]
        blocked_event = runtime_host.event_log.append(
            f"task-run:{task_id}",
            "runtime_blocked_before_assembly",
            payload={
                "reason": "action_permit_denied",
                "denied_reasons": denied_reasons,
                "model_turn_decision": model_turn_decision,
                "action_permit": action_permit,
                "runtime_start_packet": runtime_start_packet_payload,
            },
        )
        yield {"type": "harness_loop_event", "event": blocked_event.to_dict()}
        yield {
            "type": "error",
            "error": "Action permit denied before runtime assembly.",
            "code": "action_permit_denied",
            "terminal_reason": "action_permit_denied",
            "content": "本轮请求被运行许可策略阻止，未进入执行阶段。",
            "denied_reasons": denied_reasons,
            "action_permit": action_permit,
        }
        return
    if agent_turn_context.model_turn_blocked:
        blocked_event = runtime_host.event_log.append(
            f"task-run:{task_id}",
            "runtime_blocked_before_assembly",
            payload={
                "reason": "model_turn_decision_unavailable_or_blocked",
                "model_turn_decision": model_turn_decision,
                "diagnostics": model_turn_diagnostics,
            },
        )
        yield {"type": "harness_loop_event", "event": blocked_event.to_dict()}
        yield {
            "type": "error",
            "error": "Model turn decision blocked runtime execution.",
            "code": "model_turn_decision_blocked",
            "terminal_reason": "model_turn_decision_unavailable_or_blocked",
            "content": "本轮请求没有获得可执行的模型决策，未进入执行阶段。",
            "model_turn_decision": model_turn_decision,
            "diagnostics": model_turn_diagnostics,
        }
        return
    assembly = build_agent_runtime_assembly(
        runtime_host=runtime_host,
        agent_runtime_chain=agent_runtime_chain,
        session_id=session_id,
        task_id=task_id,
        user_message=user_message,
        source=source,
        runtime_chain_task_selection=runtime_chain_task_selection,
        runtime_context_override=runtime_context_override,
        allowed_search_sources=allowed_search_sources,
        agent_runtime_profile=agent_runtime_profile,
        invocation_payload=invocation_payload,
        invocation_is_explicit=invocation_is_explicit,
        assembly_contract=assembly_contract,
        stream_policy=stream_policy,
        artifact_policy=artifact_policy,
    )
    task_operation = assembly.task_operation
    task_contract = assembly.task_contract
    task_intent_contract = assembly.task_intent_contract
    selected_recipe_payload = assembly.selected_recipe_payload
    bundle_spec_payload = assembly.bundle_spec_payload
    task_spec_payload = assembly.task_spec_payload
    task_execution_assembly_payload = assembly.task_execution_assembly_payload
    task_flow_contract_binding_payload = assembly.task_flow_contract_binding_payload
    task_execution_policy_payload = assembly.task_execution_policy_payload
    task_memory_request_profile_payload = assembly.task_memory_request_profile_payload
    task_communication_protocol_payload = assembly.task_communication_protocol_payload
    task_graph_payload = assembly.task_graph_payload
    runtime_spec_payload = assembly.runtime_spec_payload
    graph_payload = assembly.graph_payload
    task_body_orchestration_payload = assembly.task_body_orchestration_payload
    agent_runtime_spec_payload = assembly.agent_runtime_spec_payload
    invocation_payload = assembly.invocation_payload
    assembly_contract = assembly.assembly_contract
    effective_agent_runtime_profile = assembly.effective_agent_runtime_profile
    effective_agent_profile_id = assembly.effective_agent_profile_id
    agent_runtime_config = assembly.agent_runtime_config
    execution_permit = assembly.execution_permit
    agent_runtime_enabled_phases = assembly.agent_runtime_enabled_phases
    memory_view = assembly.memory_view
    context_policy = assembly.context_policy
    execution_mode = assembly.execution_mode
    effective_limits = assembly.effective_limits
    result_refs: list[str] = []
    final_main_context: dict[str, Any] = {}
    final_task_summary_refs: list[dict[str, Any]] = []
    start = runtime_host.start(
        session_id=session_id,
        task_id=task_id,
        task_contract_ref=str(task_contract.get("task_id") or task_id),
        agent_id=str(agent_runtime_spec_payload.get("agent_id") or "agent:0"),
        agent_profile_id=effective_agent_profile_id,
        runtime_lane=str(agent_runtime_spec_payload.get("runtime_lane") or "standard_task"),
        task_agent_binding_ref=str(task_execution_assembly_payload.get("task_agent_binding_ref") or ""),
        execution_mode=execution_mode,
        graph_ref=str(
            task_graph_payload.get("graph_id")
            or graph_payload.get("graph_id")
            or graph_payload.get("task_graph_id")
            or ""
        ),
        coordinator_agent_id=str(graph_payload.get("coordinator_agent_id") or ""),
        topology_template_id=str(graph_payload.get("topology_template_id") or ""),
        communication_protocol_id=str(task_communication_protocol_payload.get("protocol_id") or ""),
        handoff_policy=str(graph_payload.get("handoff_policy") or ""),
        failure_policy=str(graph_payload.get("conflict_resolution_policy") or ""),
        merge_policy=str(graph_payload.get("output_merge_policy") or ""),
        diagnostics={
            "runtime_channel": "agent_runtime",
            "search_policy": list(search_policy) if search_policy is not None else None,
            "allowed_search_sources": sorted(allowed_search_sources),
            "agent_invocation_id": str(invocation_payload.get("invocation_id") or ""),
            "agent_assembly_contract": assembly_contract_diagnostics(assembly_contract),
            "execution_permit": execution_permit_diagnostics(execution_permit),
            "agent_runtime_config": agent_runtime_config.to_dict(),
            **stage_execution_request_diagnostics(dict(task_selection or {})),
        },
    )
    preflight_result: AgentRuntimePreflightResult | None = None
    async for preflight_event in run_agent_runtime_preflight(
        AgentRuntimePreflightInput(
            runtime_host=runtime_host,
            start=start,
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            history=history,
            source=source,
            task_selection=task_selection,
            runtime_context_override=runtime_context_override,
            search_policy=search_policy,
            allowed_search_sources=allowed_search_sources,
            agent_runtime_chain=agent_runtime_chain,
            model_response_executor=model_response_executor,
            runtime_context_manager=runtime_context_manager,
            memory_intent=memory_intent,
            model_selection=model_selection,
            tool_instances=tool_instances,
            task_operation=task_operation,
            task_contract=task_contract,
            task_intent_contract=task_intent_contract,
            selected_recipe_payload=selected_recipe_payload,
            bundle_spec_payload=bundle_spec_payload,
            task_spec_payload=task_spec_payload,
            task_execution_assembly_payload=task_execution_assembly_payload,
            task_flow_contract_binding_payload=task_flow_contract_binding_payload,
            task_execution_policy_payload=task_execution_policy_payload,
            task_memory_request_profile_payload=task_memory_request_profile_payload,
            task_communication_protocol_payload=task_communication_protocol_payload,
            task_graph_payload=task_graph_payload,
            runtime_spec_payload=runtime_spec_payload,
            graph_payload=graph_payload,
            task_body_orchestration_payload=task_body_orchestration_payload,
            agent_runtime_spec_payload=agent_runtime_spec_payload,
            invocation_payload=invocation_payload,
            assembly_contract=assembly_contract,
            effective_agent_runtime_profile=effective_agent_runtime_profile,
            execution_permit=execution_permit,
            agent_runtime_config=agent_runtime_config,
            agent_runtime_enabled_phases=agent_runtime_enabled_phases,
            memory_view=memory_view,
            context_policy=context_policy,
            execution_mode=execution_mode,
            effective_limits=effective_limits,
        )
    ):
        if isinstance(preflight_event, AgentRuntimePreflightResult):
            preflight_result = preflight_event
            continue
        yield preflight_event
    if preflight_result is None:
        raise RuntimeError("AgentRuntime preflight did not produce a result")
    if preflight_result.terminal:
        return

    state = preflight_result.state
    runtime_task_ledger = preflight_result.runtime_task_ledger
    result_refs = preflight_result.result_refs
    final_main_context = preflight_result.final_main_context
    final_task_summary_refs = preflight_result.final_task_summary_refs
    task_contract_ref = preflight_result.task_contract_ref
    current_turn_context = preflight_result.current_turn_context
    model_stream_policy = preflight_result.model_stream_policy
    artifact_policy_for_validation = preflight_result.artifact_policy_for_validation
    sandbox_policy = preflight_result.sandbox_policy
    file_management_policy = preflight_result.file_management_policy
    directive = preflight_result.directive
    resource_policy = preflight_result.resource_policy
    runtime_tool_instances = preflight_result.runtime_tool_instances
    resolved_model_spec = preflight_result.resolved_model_spec
    context_snapshot = preflight_result.context_snapshot

    turn_loop_result: AgentTurnLoopResult | None = None
    async for turn_loop_event in run_agent_turn_loop(
        AgentTurnLoopInput(
            runtime_host=runtime_host,
            state=state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            initial_final_main_context=final_main_context,
            initial_final_task_summary_refs=final_task_summary_refs,
            task_id=task_id,
            user_message=user_message,
            task_operation=task_operation,
            resource_policy=resource_policy,
            runtime_context_manager=runtime_context_manager,
            model_response_executor=model_response_executor,
            tool_runtime_executor=tool_runtime_executor,
            context_model_messages=list(context_snapshot.model_messages),
            directive=directive,
            runtime_tool_instances=runtime_tool_instances,
            model_stream_policy=model_stream_policy,
            resolved_model_spec=resolved_model_spec,
            allowed_search_sources=allowed_search_sources,
            sandbox_policy=sandbox_policy,
            file_management_policy=file_management_policy,
            start_task_run=start.task_run,
            selected_recipe_payload=selected_recipe_payload,
            task_spec_payload=task_spec_payload,
            effective_limits=effective_limits,
            task_contract_ref=task_contract_ref,
        )
    ):
        if isinstance(turn_loop_event, AgentTurnLoopResult):
            turn_loop_result = turn_loop_event
            continue
        yield turn_loop_event
    if turn_loop_result is None:
        raise RuntimeError("AgentRuntime turn loop did not produce a result")
    if turn_loop_result.approval_waiting:
        return
    state = turn_loop_result.state
    runtime_task_ledger = turn_loop_result.runtime_task_ledger
    result_refs = turn_loop_result.result_refs
    final_content = turn_loop_result.final_content
    final_answer_metadata = turn_loop_result.final_answer_metadata
    run_outcome = turn_loop_result.run_outcome
    terminal_reason = turn_loop_result.terminal_reason
    final_main_context = turn_loop_result.final_main_context
    final_task_summary_refs = turn_loop_result.final_task_summary_refs
    final_bundle_summary_refs = turn_loop_result.final_bundle_summary_refs
    current_bundle_items = turn_loop_result.current_bundle_items
    executed_bundle_ordinals = turn_loop_result.executed_bundle_ordinals
    observation_aggregator = turn_loop_result.observation_aggregator
    tool_observation_count = turn_loop_result.tool_observation_count
    turn_count = turn_loop_result.turn_count
    tool_call_count = turn_loop_result.tool_call_count
    
    phase_outcome, phase_events = apply_post_model_phases(
        runtime_host=runtime_host,
        task_run_id=state.task_run_id,
        task_id=task_id,
        user_message=user_message,
        task_contract_ref=task_contract_ref,
        selected_recipe_payload=selected_recipe_payload,
        agent_runtime_config=agent_runtime_config,
        final_content=final_content,
        final_answer_metadata=final_answer_metadata,
        terminal_reason=terminal_reason,
        tool_call_count=tool_call_count,
        tool_observation_count=tool_observation_count,
    )
    for phase_event in phase_events:
        yield phase_event
    final_content = phase_outcome.final_content
    final_answer_metadata = phase_outcome.final_answer_metadata
    run_outcome = phase_outcome.run_outcome or run_outcome
    terminal_reason = phase_outcome.terminal_reason
    
    artifact_validation = validate_required_artifact_file(
        root_dir=runtime_host.root_dir,
        selected_recipe_payload=selected_recipe_payload,
        artifact_policy=artifact_policy_for_validation,
        final_content=final_content,
        result_refs=tuple(result_refs),
        event_log_events=[item.to_dict() for item in runtime_host.event_log.list_events(state.task_run_id)],
    )
    if not artifact_validation["passed"] and terminal_reason == "completed":
        rejected_final_content = str(final_content or "")
        terminal_reason = "artifact_validation_failed"
        final_answer_metadata = {
            **dict(final_answer_metadata),
            "answer_channel": "orchestration_fail_closed",
            "answer_source": "task_artifact_validation",
            "answer_canonical_state": "artifact_validation_failed",
            "answer_persist_policy": "do_not_persist",
            "answer_finalization_policy": "none",
            "answer_fallback_reason": str(artifact_validation.get("reason") or "artifact_validation_failed"),
        }
        artifact_validation["rejected_final_content_chars"] = len(rejected_final_content)
        final_content = ""
    
    artifact_validation_event = runtime_host.event_log.append(
        state.task_run_id,
        "task_artifact_validation_checked",
        payload={"validation": artifact_validation},
        refs={"task_contract_ref": task_contract_ref},
    )
    yield {"type": "harness_loop_event", "event": artifact_validation_event.to_dict()}
    
    partial_terminal_reasons = {
        "partially_completed",
        "model_response_timeout_after_partial_output",
    }
    blocked_terminal_reasons = {
        "agent_plan_required",
    }
    terminal_status = (
        "completed"
        if terminal_reason == "completed"
        else "completed"
        if terminal_reason in partial_terminal_reasons and final_content
        else "blocked"
        if terminal_reason in blocked_terminal_reasons
        else "failed"
    )
    terminal_state = state.with_status(
        terminal_status,
        transition="stop_after_final_output",
        terminal_reason=terminal_reason,
        diagnostics={"final_content_chars": len(final_content), "artifact_validation": artifact_validation},
    )
    finalization_result: AgentRunFinalizationResult | None = None
    async for finalization_event in finalize_agent_run(
        runtime_host,
        AgentRunFinalizationInput(
            session_id=session_id,
            task_id=task_id,
            history=history,
            source=source,
            start=start,
            terminal_state=terminal_state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_content=final_content,
            final_answer_metadata=final_answer_metadata,
            run_outcome=run_outcome,
            terminal_reason=terminal_reason,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            final_bundle_summary_refs=final_bundle_summary_refs,
            current_bundle_items=current_bundle_items,
            executed_bundle_ordinals=executed_bundle_ordinals,
            observation_aggregator=observation_aggregator,
            current_turn_context=current_turn_context,
            selected_recipe_payload=selected_recipe_payload,
            task_contract_ref=task_contract_ref,
            task_spec_payload=task_spec_payload,
            user_message=user_message,
            tool_observation_count=tool_observation_count,
            turn_count=turn_count,
            assistant_message_committer=assistant_message_committer,
        ),
    ):
        if isinstance(finalization_event, AgentRunFinalizationResult):
            finalization_result = finalization_event
            continue
        yield finalization_event
    if finalization_result is None:
        raise RuntimeError("AgentRuntime finalization did not produce a terminal result")
    yield finalization_result.done_event
    return


