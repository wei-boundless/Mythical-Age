from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.messages import ToolMessage

from agent_system.models.model_profile_resolver import ModelProfileResolver
from capability_system.search_policy import normalize_search_policy
from permissions import (
    OperationGatePipelineContext,
    build_model_response_runtime_admission,
    build_runtime_capability_state,
)
from task_system.planning.execution_recipe_models import ExecutionRecipe, TaskValidationRule
from task_system.tasks.run_models import (
    TaskRunLedger,
    build_task_run_ledger,
    current_task_step_run,
    start_task_run_step,
    task_run_step_count,
)
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import StepInputBinding, TaskStepBlueprint

from ..agent_assembly import DirectWorkOrder, build_agent_invocation, build_model_context_payload
from ..capabilities import build_current_turn_capability_plan
from ..context_management.system_retrieval import SystemRetrievalStage, build_context_policy_with_retrieval
from ..execution.node_execution_request import build_node_execution_idempotency_key
from ..execution_engine import (
    ModelToolCallAccumulator,
    build_initial_followup_messages,
    build_next_followup_messages,
)
from ..execution_permit import tool_instances_for_policy_and_permit
from ..memory.observation_aggregator import ObservationAggregator
from ..shared.loop_control import RuntimeLoopLimits, check_runtime_loop_control
from ..shared.dispatch_plan_compiler import _normalize_runtime_graph_payload
from ..shared.models import RuntimeLoopState
from ..shared.runtime_object_store import RuntimeObjectStore
from ..shared.safety import build_task_safety_validators
from ..shared.stage_projection import StageProjectionCycle
from ..shared.tool_repetition_guard import ToolRepetitionGuard
from ..shared.artifact_paths import (
    validate_required_artifact_file,
    workspace_root_from_runtime_root,
)
from .runtime_policy import (
    artifact_policy_from_task_execution_assembly,
    model_stream_policy_from_task_execution_assembly,
)
from .config import build_agent_runtime_config
from .environment.file_management_policy import prepare_runtime_file_management_policy_for_turn
from .environment.sandbox_policy import prepare_runtime_sandbox_policy_for_turn
from .environment.tool_capability_policy import (
    apply_tool_capability_table_to_turn_plan,
    capability_table_to_runtime_plan_overlay,
    prepare_runtime_tool_capability_table_for_turn,
)
from .event_application import ModelTurnApplicationState
from .execution_permit import (
    execution_permit_diagnostics as _execution_permit_diagnostics,
    resolve_agent_execution_permit,
)
from .finalization import (
    AgentRunFinalizationInput,
    AgentRunFinalizationResult,
    dedupe_refs as _dedupe_refs,
    finalize_agent_run,
)
from .model_turn import AgentModelTurnInput, run_agent_model_turn
from .phase_pipeline import append_pre_model_phase_events, apply_post_model_phases
from .request import AgentRunRequest
from .turn_context import build_agent_turn_context


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
    stage_projection_cycle = request.stage_projection_cycle
    memory_intent = request.memory_intent
    task_selection = dict(request.task_selection or {})
    assistant_message_committer = request.assistant_message_committer
    tool_runtime_executor = request.tool_runtime_executor
    tool_instances = list(request.tool_instances or [])
    agent_runtime_profile = request.agent_runtime_profile
    search_policy = list(request.search_policy) if request.search_policy is not None else None
    model_selection = dict(request.model_selection or {})
    agent_invocation = dict(request.agent_invocation or {})
    task_order_ref = dict(request.task_order_ref or {}) if request.task_order_ref is not None else None
    task_order_run_ref = dict(request.task_order_run_ref or {}) if request.task_order_run_ref is not None else None
    execution_channel_ref = (
        dict(request.execution_channel_ref or {}) if request.execution_channel_ref is not None else None
    )
    task_execution_envelope_ref = (
        dict(request.task_execution_envelope_ref or {})
        if request.task_execution_envelope_ref is not None
        else None
    )
    task_order_binding = _task_order_runtime_binding_diagnostics(
        task_order_ref=task_order_ref,
        task_order_run_ref=task_order_run_ref,
        execution_channel_ref=execution_channel_ref,
        task_execution_envelope_ref=task_execution_envelope_ref,
    )
    invocation_payload = _agent_invocation_payload(
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
        runtime_chain_task_selection = _merge_invocation_identity_into_task_selection(
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
    allowed_search_sources = _resolve_runtime_search_sources(
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
        task_order_binding=task_order_binding,
        model_response_executor=model_response_executor,
    )
    request_facts = agent_turn_context.request_facts
    boundary_policy = agent_turn_context.boundary_policy
    context_candidates = agent_turn_context.context_candidates
    model_turn_decision = agent_turn_context.model_turn_decision
    model_turn_diagnostics = agent_turn_context.model_turn_diagnostics
    action_permit = agent_turn_context.action_permit
    runtime_start_packet = agent_turn_context.runtime_start_packet
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
                "runtime_start_packet": runtime_start_packet,
            },
        )
        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
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
        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
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
    chain_runtime = agent_runtime_chain.build_runtime(
        session_id=session_id,
        task_id=task_id,
        turn_id=str(dict(runtime_chain_task_selection or {}).get("turn_id") or ""),
        message=user_message,
        source=source,
        current_turn_context_override=runtime_context_override,
        task_selection={
            **dict(runtime_chain_task_selection or {}),
            "search_policy": sorted(allowed_search_sources),
        },
        agent_runtime_profile=agent_runtime_profile,
    )
    task_operation = dict(chain_runtime.get("task_operation") or {})
    if stream_policy:
        task_operation["runtime_stream_policy"] = stream_policy
    if artifact_policy:
        task_operation["runtime_artifact_policy"] = artifact_policy
    task_contract = dict(task_operation.get("task_contract") or {})
    task_intent_contract = dict(task_operation.get("task_intent_contract") or {})
    selected_recipe_payload = dict(task_operation.get("selected_recipe") or {})
    bundle_spec_payload = dict(task_operation.get("bundle_spec") or {})
    task_spec_payload = dict(task_operation.get("task_spec") or {})
    task_execution_assembly_payload = dict(task_operation.get("task_execution_assembly") or {})
    task_projection_binding_payload = dict(task_operation.get("task_projection_binding") or {})
    task_flow_contract_binding_payload = dict(task_operation.get("task_flow_contract_binding") or {})
    task_execution_policy_payload = dict(task_operation.get("task_execution_policy") or {})
    task_memory_request_profile_payload = dict(task_operation.get("task_memory_request_profile") or {})
    task_communication_protocol_payload = dict(task_operation.get("task_communication_protocol") or {})
    raw_graph_payload = dict(task_operation.get("graph_record") or {})
    task_graph_payload = dict(task_operation.get("task_graph_record") or task_operation.get("graph_record") or {})
    runtime_spec_payload = dict(task_operation.get("task_graph_runtime_spec") or {})
    graph_payload = _normalize_runtime_graph_payload(
        raw_graph_payload=raw_graph_payload,
        task_graph_payload=task_graph_payload,
        runtime_spec_payload=runtime_spec_payload,
    )
    task_body_orchestration_payload = dict(chain_runtime.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {})
    agent_runtime_spec_payload = dict(chain_runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
    if not invocation_is_explicit:
        direct_selection = {
            **dict(runtime_chain_task_selection or {}),
            "agent_id": str(agent_runtime_spec_payload.get("agent_id") or ""),
            "agent_profile_id": str(
                agent_runtime_spec_payload.get("agent_profile_id")
                or _agent_profile_id_for_runtime_spec(
                    runtime_host.agent_runtime_registry,
                    agent_runtime_spec_payload,
                )
                or ""
            ),
            "runtime_lane": str(agent_runtime_spec_payload.get("runtime_lane") or ""),
        }
        invocation_payload = _build_direct_agent_invocation_payload(
            base_dir=runtime_host.backend_dir,
            task_id=task_id,
            user_message=user_message,
            task_selection=direct_selection,
            agent_runtime_profile=agent_runtime_profile,
        )
        assembly_contract = dict(invocation_payload.get("assembly_contract") or {})
        if not assembly_contract:
            raise RuntimeError("AgentRuntime invocation could not build direct AgentInvocation assembly contract")
        stream_policy = dict(assembly_contract.get("stream_policy") or stream_policy)
        artifact_policy = dict(assembly_contract.get("artifact_policy") or artifact_policy)
    if assembly_contract:
        _assert_agent_runtime_spec_matches_invocation(
            agent_runtime_spec_payload,
            assembly_contract,
            strict_runtime_lane=invocation_is_explicit,
        )
    effective_agent_runtime_profile = agent_runtime_profile or runtime_host.agent_runtime_registry.get_profile(
        str(agent_runtime_spec_payload.get("agent_id") or "").strip()
    )
    effective_agent_profile_id = str(agent_runtime_spec_payload.get("agent_profile_id") or "").strip()
    if not effective_agent_profile_id:
        effective_agent_profile_id = str(
            getattr(effective_agent_runtime_profile, "agent_profile_id", "")
            or _agent_profile_id_for_runtime_spec(
                runtime_host.agent_runtime_registry,
                agent_runtime_spec_payload,
            )
            or "main_interactive_agent"
        )
    agent_runtime_config = build_agent_runtime_config(
        selected_recipe_payload=selected_recipe_payload,
        task_operation=task_operation,
        agent_runtime_spec=agent_runtime_spec_payload,
    )
    execution_permit = resolve_agent_execution_permit(
        assembly_contract,
        task_operation=task_operation,
        task_id=task_id,
        agent_id=str(agent_runtime_spec_payload.get("agent_id") or "agent:0"),
        agent_profile_id=effective_agent_profile_id,
        agent_runtime_config=agent_runtime_config,
    )
    if execution_permit:
        task_operation["execution_permit"] = execution_permit
        agent_runtime_config = build_agent_runtime_config(
            selected_recipe_payload=selected_recipe_payload,
            task_operation=task_operation,
            agent_runtime_spec=agent_runtime_spec_payload,
            execution_permit=execution_permit,
    )
    task_operation["agent_runtime_config"] = agent_runtime_config.to_dict()
    agent_runtime_enabled_phases = set(agent_runtime_config.enabled_phases)
    memory_view = dict(chain_runtime.get("memory_runtime_view") or {})
    context_policy = dict(chain_runtime.get("context_policy_result") or {})
    execution_mode = str(task_execution_policy_payload.get("execution_mode") or "single_agent")
    effective_limits = _runtime_limits_from_task_operation(task_operation, fallback=runtime_host.limits)
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
            "agent_assembly_contract": _assembly_contract_diagnostics(assembly_contract),
            "execution_permit": _execution_permit_diagnostics(execution_permit),
            "agent_runtime_config": agent_runtime_config.to_dict(),
            "task_order_binding": dict(task_order_binding),
            **{
                key: value
                for key, value in dict(task_order_binding).items()
                if key
                in {
                    "task_order_id",
                    "task_order_run_id",
                    "execution_channel_id",
                    "task_execution_envelope_id",
                    "task_order_kind",
                }
                and value
            },
            **_stage_execution_request_diagnostics(dict(task_selection or {})),
        },
    )
    state = start.loop_state
    sandbox_policy = prepare_runtime_sandbox_policy_for_turn(
        root_dir=runtime_host.root_dir,
        session_id=session_id,
        task_run_id=state.task_run_id,
        task_contract=task_contract,
        user_message=user_message,
        selected_recipe_payload=selected_recipe_payload,
        task_selection={**dict(task_selection or {}), **dict(runtime_context_override or {})},
        state_index=runtime_host.state_index,
        event_log=runtime_host.event_log,
    )
    file_management_policy = prepare_runtime_file_management_policy_for_turn(
        root_dir=runtime_host.root_dir,
        task_run_id=state.task_run_id,
        selected_recipe_payload=selected_recipe_payload,
        task_selection={**dict(task_selection or {}), **dict(runtime_context_override or {})},
        sandbox_policy=sandbox_policy,
    )
    if sandbox_policy.get("enabled") is True:
        sandbox_event = runtime_host.event_log.append(
            state.task_run_id,
            "runtime_sandbox_prepared",
            payload={
                "sandbox_policy": sandbox_policy,
                "scope": "tool_layer_side_effect_isolation",
                "real_workspace_access": str(sandbox_policy.get("real_workspace_access") or "read_only"),
            },
            refs={
                "sandbox_root_ref": str(sandbox_policy.get("sandbox_root") or ""),
                "task_contract_ref": str(task_contract.get("task_id") or task_id),
            },
        )
        yield {"type": "runtime_loop_event", "event": sandbox_event.to_dict()}
    if file_management_policy.get("enabled") is True:
        file_management_event = runtime_host.event_log.append(
            state.task_run_id,
            "runtime_file_management_prepared",
            payload={
                "file_management_policy": file_management_policy,
                "scope": "system_owned_file_environment",
                "profile_id": str(file_management_policy.get("profile_id") or ""),
                "environment_id": str(file_management_policy.get("environment_id") or ""),
            },
            refs={
                "task_contract_ref": str(task_contract.get("task_id") or task_id),
                "file_profile_ref": str(file_management_policy.get("profile_id") or ""),
            },
        )
        yield {"type": "runtime_loop_event", "event": file_management_event.to_dict()}
    search_policy_event = runtime_host.event_log.append(
        state.task_run_id,
        "search_policy_resolved",
        payload={
            "search_policy": list(search_policy) if search_policy is not None else None,
            "allowed_sources": sorted(allowed_search_sources),
            "sandbox_policy": sandbox_policy,
            "file_management_policy": file_management_policy,
        },
    )
    yield {"type": "runtime_loop_event", "event": search_policy_event.to_dict()}
    yield {
        "type": "runtime_loop_started",
        "task_run": start.task_run.to_dict(),
        "agent_run": start.agent_run.to_dict(),
        "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
        "checkpoint": start.checkpoint.to_dict(),
        "events": [dict(item) for item in start.events],
    }
    for event in start.events:
        yield {"type": "runtime_loop_event", "event": dict(event)}
    
    task_contract_ref = str(task_contract.get("task_id") or task_id)
    runtime_task_ledger = _build_initial_task_run_ledger(
        task_run_id=state.task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec_payload=task_spec_payload,
        selected_recipe_payload=selected_recipe_payload,
    )
    if runtime_task_ledger is not None:
        runtime_task_ledger = start_task_run_step(
            runtime_task_ledger,
            started_at=time.time(),
            diagnostics={"transition_reason": "task_contract_built"},
        )
    runtime_boundary_refs = _persist_agent_invocation_boundary_objects(
        runtime_host.runtime_objects,
        task_run_id=state.task_run_id,
        agent_invocation=invocation_payload,
        assembly_contract=assembly_contract,
        execution_permit=execution_permit,
    )
    task_event = runtime_host.event_log.append(
        state.task_run_id,
        "task_contract_built",
        payload={
            "task_contract": task_contract,
            "task_intent_contract": task_intent_contract,
            "selected_recipe": selected_recipe_payload,
            "bundle_spec": bundle_spec_payload,
            "task_spec": task_spec_payload,
            "task_execution_assembly": task_execution_assembly_payload,
            "task_projection_binding": task_projection_binding_payload,
            "task_flow_contract_binding": task_flow_contract_binding_payload,
            "task_execution_policy": task_execution_policy_payload,
            "task_memory_request_profile": task_memory_request_profile_payload,
            "task_communication_protocol": task_communication_protocol_payload,
            "graph_record": graph_payload,
            "task_graph_record": task_graph_payload,
            "task_graph_runtime_spec": runtime_spec_payload,
            "task_body_orchestration": task_body_orchestration_payload,
            "agent_runtime_spec": agent_runtime_spec_payload,
            "agent_runtime_config": agent_runtime_config.to_dict(),
            "agent_invocation": _agent_invocation_diagnostics(invocation_payload),
            "agent_assembly_contract": _assembly_contract_diagnostics(assembly_contract),
            "execution_permit": _execution_permit_diagnostics(execution_permit),
            "runtime_boundary_objects": dict(runtime_boundary_refs),
            "task_run_ledger": runtime_task_ledger.to_dict() if runtime_task_ledger is not None else {},
            "sandbox_policy": sandbox_policy,
            "source": source,
        },
        refs={
            "task_contract_ref": task_contract_ref,
            "task_intent_ref": str(task_intent_contract.get("task_intent_id") or ""),
            "task_template_id": str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
            "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
            "task_execution_assembly_ref": str(task_execution_assembly_payload.get("assembly_id") or ""),
            "task_projection_binding_ref": str(task_projection_binding_payload.get("binding_id") or ""),
            "task_flow_contract_binding_ref": str(task_flow_contract_binding_payload.get("binding_id") or ""),
            "task_execution_policy_ref": str(
                task_execution_policy_payload.get("policy_id") or ""
            ),
            "task_memory_request_profile_ref": str(task_memory_request_profile_payload.get("profile_id") or ""),
            "task_communication_protocol_ref": str(task_communication_protocol_payload.get("protocol_id") or ""),
            "graph_ref": str(
                task_graph_payload.get("graph_id")
                or graph_payload.get("graph_id")
                or graph_payload.get("task_graph_id")
                or ""
            ),
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            "agent_invocation_ref": str(invocation_payload.get("invocation_id") or ""),
            "agent_assembly_contract_ref": str(assembly_contract.get("assembly_id") or ""),
            "work_order_ref": str(assembly_contract.get("work_order_id") or ""),
            "execution_permit_ref": str(execution_permit.get("permit_id") or ""),
            "agent_invocation_object_ref": str(runtime_boundary_refs.get("agent_invocation_object_ref") or ""),
            "agent_assembly_object_ref": str(runtime_boundary_refs.get("agent_assembly_object_ref") or ""),
            "execution_permit_object_ref": str(runtime_boundary_refs.get("execution_permit_object_ref") or ""),
            "bundle_spec_ref": str(bundle_spec_payload.get("bundle_id") or ""),
            "task_run_ledger_ref": runtime_task_ledger.ledger_id if runtime_task_ledger is not None else "",
        },
    )
    yield {"type": "runtime_loop_event", "event": task_event.to_dict()}
    runtime_object_events = runtime_host._sync_runtime_objects_after_task_contract(
        start_result=start,
        event_offset=task_event.offset,
        execution_mode=execution_mode,
        task_agent_binding_ref=str(task_execution_assembly_payload.get("task_agent_binding_ref") or ""),
        graph_payload=graph_payload,
        task_graph_payload=task_graph_payload,
        communication_protocol_payload=task_communication_protocol_payload,
        task_execution_policy_payload=task_execution_policy_payload,
        effective_limits=effective_limits,
        task_spec_payload=task_spec_payload,
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
        item
        for item in runtime_host.state_index.list_task_agent_runs(state.task_run_id)
        if str(item.spawn_mode or "") == "worker_spawn"
    ]
    runtime_execution_facts = {
        "worker_spawn_summary": {
            "spawn_request_count": len(runtime_host.state_index.list_task_worker_spawn_requests(state.task_run_id)),
            "spawn_result_count": len(current_worker_spawn_results),
            "spawned_agent_ids": [
                str(item.spawned_agent_id or "")
                for item in current_worker_spawn_results
                if str(item.status or "") == "spawned" and str(item.spawned_agent_id or "")
            ],
            "blocked_spawn_count": sum(
                1 for item in current_worker_spawn_results if str(item.status or "") == "blocked"
            ),
            "worker_agent_run_ids": [
                str(item.agent_run_id or "")
                for item in current_worker_agent_runs
                if str(item.agent_run_id or "")
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
    current_turn_context = dict(task_operation.get("current_turn_context") or {})
    model_stream_policy = model_stream_policy_from_task_execution_assembly(
        task_execution_assembly_payload,
        current_turn_context=current_turn_context,
        agent_assembly_contract=assembly_contract,
        runtime_policy=dict(task_operation.get("runtime_stream_policy") or {}),
    )
    artifact_policy_for_validation = artifact_policy_from_task_execution_assembly(
        selected_recipe_payload=selected_recipe_payload,
        task_execution_assembly=task_execution_assembly_payload,
        current_turn_context=current_turn_context,
        agent_assembly_contract=assembly_contract,
        runtime_policy=dict(task_operation.get("runtime_artifact_policy") or {}),
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
        for trace_event in _intent_continuation_trace_events(current_turn_context):
            trace_record = runtime_host.event_log.append(
                state.task_run_id,
                trace_event["event_type"],
                payload=dict(trace_event.get("payload") or {}),
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": trace_record.to_dict()}
    query_understanding = dict(task_operation.get("query_understanding") or {})
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
        selected_recipe_payload=selected_recipe_payload,
        task_operation=task_operation,
        allowed_search_sources=allowed_search_sources,
        evidence_phase_required="evidence" in agent_runtime_enabled_phases,
    ):
        retrieval_outcome = await system_retrieval_stage.run(
            task_run_id=state.task_run_id,
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            current_turn_context=current_turn_context,
            query_understanding=query_understanding,
            selected_recipe_payload=selected_recipe_payload,
            task_spec_payload=task_spec_payload,
            task_contract_ref=task_contract_ref,
            runtime_task_ledger=runtime_task_ledger,
            state=state,
            allowed_search_sources=allowed_search_sources,
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
            "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
            "conversation_candidate_count": _diagnostic_int(memory_view, "conversation_candidate_count"),
            "state_candidate_count": _diagnostic_int(memory_view, "state_candidate_count"),
            "long_term_candidate_count": _diagnostic_int(memory_view, "long_term_candidate_count"),
        },
        refs={"memory_runtime_view_ref": str(memory_view.get("view_id") or "")},
    )
    yield {"type": "runtime_loop_event", "event": memory_event.to_dict()}
    directive, resource_policy = build_model_response_runtime_admission(
        task_operation,
        operation_registry=runtime_host.operation_gate.registry,
        agent_runtime_profile=effective_agent_runtime_profile,
        sandbox_policy=sandbox_policy,
    )
    current_turn_capability_plan = build_current_turn_capability_plan(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=runtime_host.tool_authorization_index.definitions_by_name,
        normalize_operation_id=runtime_host.operation_gate.registry.normalize_id,
        task_operation=task_operation,
        allowed_search_sources=allowed_search_sources,
        execution_permit=execution_permit,
    )
    tool_capability_table = prepare_runtime_tool_capability_table_for_turn(
        task_operation={**dict(task_operation), "resource_policy": resource_policy, "task_id": task_id},
        file_management_policy=file_management_policy,
        execution_permit=execution_permit,
        runtime_available_operations=current_turn_capability_plan.allowed_operations,
    )
    if tool_capability_table is not None:
        task_operation["tool_capability_table"] = tool_capability_table
        current_turn_capability_plan = apply_tool_capability_table_to_turn_plan(
            current_turn_capability_plan,
            tool_capability_table,
        )
    current_turn_capability_plan_payload = current_turn_capability_plan.to_dict()
    tool_capability_overlay = capability_table_to_runtime_plan_overlay(tool_capability_table)
    if tool_capability_overlay:
        current_turn_capability_plan_payload["tool_capability_table"] = tool_capability_overlay
    task_operation["current_turn_capability_plan"] = current_turn_capability_plan_payload
    resolved_model_spec = None
    model_resolution: dict[str, Any] = {}
    settings_service = getattr(getattr(model_response_executor, "model_runtime", None), "settings_service", None)
    if settings_service is not None:
        model_requirement = _model_requirement_for_model_resolution(
            task_execution_assembly=task_execution_assembly_payload,
            current_turn_context=current_turn_context,
            agent_assembly_contract=assembly_contract,
        )
        graph_runtime_defaults = _chat_model_selection_runtime_defaults(model_selection)
        resolved_model_spec = ModelProfileResolver(settings_service).resolve_model_spec(
            agent_runtime_profile=effective_agent_runtime_profile,
            model_requirement=dict(model_requirement) if isinstance(model_requirement, dict) else {},
            runtime_lane=str(agent_runtime_spec_payload.get("runtime_lane") or ""),
            graph_runtime_defaults=graph_runtime_defaults,
        )
        model_resolution = resolved_model_spec.to_public_dict()
        model_resolution_event = runtime_host.event_log.append(
            state.task_run_id,
            "model_profile_resolved",
            payload={"model_resolution": model_resolution},
            refs={
                "task_contract_ref": task_contract_ref,
                "agent_profile_ref": str(getattr(effective_agent_runtime_profile, "agent_profile_id", "") or ""),
            },
        )
        yield {"type": "runtime_loop_event", "event": model_resolution_event.to_dict()}
    task_safety_envelope = dict(dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}).get(
        "safety_envelope",
        {},
    )
    task_safety_validators = build_task_safety_validators(
        root_dir=runtime_host.root_dir,
        safety_envelope=task_safety_envelope,
        sandbox_policy=sandbox_policy,
    )
    runtime_tool_instances = tool_instances_for_policy_and_permit(
        tool_instances=tool_instances,
        resource_policy=resource_policy,
        definitions_by_name=runtime_host.tool_authorization_index.definitions_by_name,
        normalize_operation_id=runtime_host.operation_gate.registry.normalize_id,
        allowed_search_sources=allowed_search_sources,
        sandbox_policy=sandbox_policy,
        execution_permit=execution_permit,
        task_operation=task_operation,
        capability_plan=current_turn_capability_plan,
    )
    runtime_capability_state = build_runtime_capability_state(
        task_operation,
        resource_policy=resource_policy,
        agent_runtime_profile=effective_agent_runtime_profile,
        visible_tool_names=list(current_turn_capability_plan.model_visible_tools),
        sandbox_policy=sandbox_policy,
    )
    effective_runtime_execution_facts = {
        **dict(runtime_execution_facts or {}),
        "runtime_capability_state": runtime_capability_state,
    }
    projection_cycle = stage_projection_cycle or StageProjectionCycle()
    stage_projection = projection_cycle.build_from_orchestration(
        task_id=task_id,
        task_body_orchestration=task_body_orchestration_payload,
        agent_runtime_spec=agent_runtime_spec_payload,
    )
    projection_event = runtime_host.event_log.append(
        state.task_run_id,
        "stage_projection_built",
        payload={
            "stage_projection": stage_projection.to_dict(),
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
        },
        refs={
            "projection_ref": stage_projection.projection_ref,
            "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
        },
    )
    yield {"type": "runtime_loop_event", "event": projection_event.to_dict()}
    
    effective_context_policy = (
        build_context_policy_with_retrieval(
            agent_runtime_chain=agent_runtime_chain,
            session_id=session_id,
            user_message=user_message,
            memory_intent=memory_intent,
            task_operation=task_operation,
            retrieval_results=retrieval_results,
            allowed_search_sources=allowed_search_sources,
        )
        if retrieval_results
        else context_policy
    )
    context_snapshot = runtime_context_manager.prepare_model_context(
        session_id=session_id,
        task_id=task_id,
        user_message=user_message,
        history=history,
        memory_intent=memory_intent,
        memory_runtime_view=memory_view,
        context_policy_result=effective_context_policy,
        stage_projection_snapshot=stage_projection,
        runtime_execution_facts=effective_runtime_execution_facts,
        runtime_assembly=dict(assembly_contract.get("runtime_assembly") or dict(current_turn_context or {}).get("runtime_assembly") or {}),
        agent_assembly_contract=assembly_contract,
    )
    context_event = runtime_host.event_log.append(
        state.task_run_id,
        "context_snapshot_built",
        payload={
            "context_snapshot": context_snapshot.to_dict(),
            "context_policy_result": effective_context_policy,
        },
        refs={
            "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
            "context_snapshot_ref": context_snapshot.snapshot_id,
            "context_policy_ref": context_snapshot.context_policy_ref,
            "projection_ref": stage_projection.projection_ref,
            "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
        },
    )
    yield {"type": "runtime_loop_event", "event": context_event.to_dict()}
    invariant_report = runtime_context_manager.check_invariants(context_snapshot)
    invariant_event = runtime_host.event_log.append(
        state.task_run_id,
        "context_invariant_checked",
        payload={"invariant_report": invariant_report.to_dict()},
        refs={
            "context_snapshot_ref": context_snapshot.snapshot_id,
            "invariant_report_ref": invariant_report.report_id,
        },
    )
    yield {"type": "runtime_loop_event", "event": invariant_event.to_dict()}
    yield {"type": "runtime_context_invariant", "report": invariant_report.to_dict()}
    
    state = RuntimeLoopState(
        task_run_id=state.task_run_id,
        status="running",
        transition="start",
        turn_count=1,
        step_count=task_run_step_count(runtime_task_ledger),
        current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else "",
        agent_id=state.agent_id,
        agent_profile_id=state.agent_profile_id,
        runtime_lane=state.runtime_lane,
        task_agent_binding_ref=state.task_agent_binding_ref,
        task_template_id=str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
        task_spec_ref=str(task_spec_payload.get("task_spec_ref") or ""),
        task_result_ref="",
        skill_workflow_ref=state.skill_workflow_ref,
        health_issue_ref=state.health_issue_ref,
        memory_state_ref=str(memory_view.get("view_id") or ""),
        context_snapshot_ref=context_snapshot.snapshot_id,
        projection_ref=stage_projection.projection_ref,
        prompt_manifest_ref=stage_projection.prompt_manifest_ref,
        token_pressure=dict(context_snapshot.token_pressure),
        diagnostics={
            **dict(state.diagnostics),
            "task_contract_ref": task_contract_ref,
            "runtime_chain_built": True,
            "effective_loop_limits": effective_limits.to_dict(),
            "runtime_context_manager_applied": True,
            "stage_projection_cycle_applied": True,
            "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
            "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            "context_invariant_checked": True,
            "context_needs_compaction": invariant_report.needs_compaction,
            "task_template_id": str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
            "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
        },
    )
    checkpoint = runtime_host._write_checkpoint_event(state, event_offset=invariant_event.offset)
    yield {"type": "runtime_loop_event", "event": checkpoint.to_dict()}
    
    control_decision = check_runtime_loop_control(
        state,
        limits=effective_limits,
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
        return
    
    directive_event = runtime_host.event_log.append(
        state.task_run_id,
        "runtime_directive_issued",
        payload={
            "directive": directive.to_dict(),
            "resource_policy": resource_policy.to_dict(),
            "search_policy": list(search_policy) if search_policy is not None else None,
            "allowed_search_sources": sorted(allowed_search_sources),
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
        "search_policy": list(search_policy) if search_policy is not None else None,
        "allowed_search_sources": sorted(allowed_search_sources),
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
        error_event = {
            "type": "error",
            "error": gate_result.reason,
            "content": "OperationGate 未放行模型回答，本轮停止执行。",
            "answer_channel": "orchestration_fail_closed",
            "answer_source": "operation_gate",
        }
        yield error_event
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
        return
    
    final_content = ""
    final_answer_metadata: dict[str, Any] = {}
    run_outcome: dict[str, Any] = {}
    terminal_reason = "completed"
    preserve_final_answer_metadata = bool(final_content and final_answer_metadata)
    
    final_bundle_summary_refs: list[dict[str, Any]] = []
    observation_aggregator = ObservationAggregator()
    current_bundle_items = _bundle_items_from_runtime_contract(
        task_spec_payload=task_spec_payload,
    )
    tool_call_accumulator = ModelToolCallAccumulator()
    tool_messages: list[ToolMessage] = []
    tool_observation_count = 0
    executed_bundle_ordinals: list[int] = []
    tool_repetition_guard = ToolRepetitionGuard()
    repeated_tool_halt = False
    for phase_event in append_pre_model_phase_events(
        runtime_host=runtime_host,
        task_run_id=state.task_run_id,
        task_contract_ref=task_contract_ref,
        task_id=task_id,
        selected_recipe_payload=selected_recipe_payload,
        agent_runtime_config=agent_runtime_config,
    ):
        yield phase_event
    if not final_content:
        executor_event = runtime_host.event_log.append(
            state.task_run_id,
            "executor_started",
            payload={"executor_type": "model", "runtime_channel": "agent_runtime"},
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}
        turn_application = ModelTurnApplicationState(
            loop_state=state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_content=final_content,
            final_answer_metadata=final_answer_metadata,
            terminal_reason=terminal_reason,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            final_bundle_summary_refs=final_bundle_summary_refs,
            tool_observation_count=tool_observation_count,
            executed_bundle_ordinals=executed_bundle_ordinals,
            repeated_tool_halt=repeated_tool_halt,
        )
        async for emitted_event in run_agent_model_turn(
            AgentModelTurnInput(
                runtime_host=runtime_host,
                execution_engine=runtime_host.execution_engine,
                application=turn_application,
                task_run_id=state.task_run_id,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                resource_policy=resource_policy,
                current_step_id_provider=lambda: (
                    turn_application.runtime_task_ledger.current_step_id
                    if turn_application.runtime_task_ledger is not None
                    else turn_application.loop_state.current_step_id
                ),
                runtime_context_manager=runtime_context_manager,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                model_messages=list(context_snapshot.model_messages),
                directive=directive,
                runtime_tool_instances=runtime_tool_instances,
                model_stream_policy=model_stream_policy,
                resolved_model_spec=resolved_model_spec,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
                file_management_policy=file_management_policy,
                start_task_run=start.task_run,
                tool_call_accumulator=tool_call_accumulator,
                collected_tool_messages=tool_messages,
                observation_aggregator=observation_aggregator,
                current_bundle_items=current_bundle_items,
                tool_repetition_guard=tool_repetition_guard,
                selected_recipe_payload=selected_recipe_payload,
                preserve_answer_metadata=preserve_final_answer_metadata,
                apply_tool_call_transition=True,
                apply_projection_only_when_present=True,
            )
        ):
            yield emitted_event
        if turn_application.approval_waiting:
            return
        state = turn_application.loop_state
        runtime_task_ledger = turn_application.runtime_task_ledger
        result_refs = turn_application.result_refs
        final_content = turn_application.final_content
        final_answer_metadata = dict(turn_application.final_answer_metadata)
        run_outcome = dict(final_answer_metadata.get("run_outcome") or final_answer_metadata.get("completion") or {})
        terminal_reason = turn_application.terminal_reason
        final_main_context = dict(turn_application.final_main_context)
        final_task_summary_refs = [dict(item) for item in turn_application.final_task_summary_refs]
        final_bundle_summary_refs = [dict(item) for item in turn_application.final_bundle_summary_refs]
        tool_observation_count = turn_application.tool_observation_count
        executed_bundle_ordinals = list(turn_application.executed_bundle_ordinals)
        repeated_tool_halt = turn_application.repeated_tool_halt
    
    turn_count = 1
    model_call_count = 1
    followup_messages: list[Any] = []
    retrieval_followup_observed = False
    if len(tool_call_accumulator.pending_tool_calls) > 1 and terminal_reason == "completed":
        final_content = ""
        final_answer_metadata = {}
        preserve_final_answer_metadata = False
    if tool_call_accumulator.pending_tool_calls and tool_messages and terminal_reason == "completed":
        followup_messages = build_initial_followup_messages(
            context_model_messages=list(context_snapshot.model_messages),
            tool_call_accumulator=tool_call_accumulator,
            tool_messages=tool_messages,
            user_message=user_message,
            aggregation=observation_aggregator.snapshot(),
            current_bundle_items=current_bundle_items,
            remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
        )
    while followup_messages and terminal_reason == "completed":
        turn_count += 1
        model_call_count += 1
        loop_state_for_control = RuntimeLoopState(
            task_run_id=state.task_run_id,
            status="running",
            transition="continue_after_tool_result",
            turn_count=turn_count,
            step_count=task_run_step_count(runtime_task_ledger),
            current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
            agent_id=state.agent_id,
            agent_profile_id=state.agent_profile_id,
            runtime_lane=state.runtime_lane,
            task_agent_binding_ref=state.task_agent_binding_ref,
            task_template_id=state.task_template_id,
            task_spec_ref=state.task_spec_ref,
            task_result_ref=state.task_result_ref,
            skill_workflow_ref=state.skill_workflow_ref,
            health_issue_ref=state.health_issue_ref,
            memory_state_ref=state.memory_state_ref,
            context_snapshot_ref=state.context_snapshot_ref,
            projection_ref=state.projection_ref,
            prompt_manifest_ref=state.prompt_manifest_ref,
            token_pressure=dict(state.token_pressure),
            diagnostics=dict(state.diagnostics),
        )
        followup_control = check_runtime_loop_control(
            loop_state_for_control,
            limits=effective_limits,
            started_at=start.task_run.created_at,
            model_call_count=model_call_count - 1,
            event_count=len(runtime_host.event_log.list_events(state.task_run_id)),
        )
        followup_control_event = runtime_host.event_log.append(
            state.task_run_id,
            "loop_control_checked",
            payload={"control": followup_control.to_dict()},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": followup_control_event.to_dict()}
        yield {"type": "runtime_loop_control", "control": followup_control.to_dict()}
        if not followup_control.allowed:
            terminal_reason = followup_control.reason
            if not final_content:
                final_answer_metadata = {
                    "answer_channel": "orchestration_fail_closed",
                    "answer_source": "runtime_loop_control",
                    "answer_canonical_state": "no_agent_final_answer",
                    "answer_persist_policy": "persist_debug_only",
                    "answer_finalization_policy": "none",
                    "answer_fallback_reason": str(followup_control.reason or "runtime_loop_control"),
                }
            break
        followup_event = runtime_host.event_log.append(
            state.task_run_id,
            "loop_iteration_started",
            payload={
                "transition": "continue_after_tool_result",
                "turn_count": turn_count,
                "step_count": task_run_step_count(runtime_task_ledger),
                "tool_result_count": len([item for item in followup_messages if isinstance(item, ToolMessage)]),
            },
        )
        yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
        state = runtime_host._state_with_task_run_ledger(
            state,
            runtime_task_ledger,
            transition="continue_after_tool_result",
            result_refs=result_refs,
        )
        next_tool_call_accumulator = ModelToolCallAccumulator()
        next_tool_messages: list[ToolMessage] = []
        turn_application = ModelTurnApplicationState(
            loop_state=state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_content=final_content,
            final_answer_metadata=final_answer_metadata,
            terminal_reason=terminal_reason,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            final_bundle_summary_refs=final_bundle_summary_refs,
            tool_observation_count=tool_observation_count,
            executed_bundle_ordinals=executed_bundle_ordinals,
            repeated_tool_halt=repeated_tool_halt,
        )
        async for emitted_event in run_agent_model_turn(
            AgentModelTurnInput(
                runtime_host=runtime_host,
                execution_engine=runtime_host.execution_engine,
                application=turn_application,
                task_run_id=state.task_run_id,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                resource_policy=resource_policy,
                current_step_id_provider=lambda: (
                    turn_application.runtime_task_ledger.current_step_id
                    if turn_application.runtime_task_ledger is not None
                    else turn_application.loop_state.current_step_id
                ),
                runtime_context_manager=runtime_context_manager,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                model_messages=followup_messages,
                directive=directive,
                runtime_tool_instances=runtime_tool_instances,
                model_stream_policy=model_stream_policy,
                resolved_model_spec=resolved_model_spec,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
                file_management_policy=file_management_policy,
                start_task_run=start.task_run,
                tool_call_accumulator=next_tool_call_accumulator,
                collected_tool_messages=next_tool_messages,
                observation_aggregator=observation_aggregator,
                current_bundle_items=current_bundle_items,
                tool_repetition_guard=tool_repetition_guard,
                selected_recipe_payload=selected_recipe_payload,
                preserve_answer_metadata=preserve_final_answer_metadata,
                fail_running_step_on_executor_error=True,
                fail_running_step_on_loop_error=True,
            )
        ):
            yield emitted_event
        if turn_application.approval_waiting:
            return
        state = turn_application.loop_state
        runtime_task_ledger = turn_application.runtime_task_ledger
        result_refs = turn_application.result_refs
        final_content = turn_application.final_content
        final_answer_metadata = dict(turn_application.final_answer_metadata)
        terminal_reason = turn_application.terminal_reason
        final_main_context = dict(turn_application.final_main_context)
        final_task_summary_refs = [dict(item) for item in turn_application.final_task_summary_refs]
        final_bundle_summary_refs = [dict(item) for item in turn_application.final_bundle_summary_refs]
        tool_observation_count = turn_application.tool_observation_count
        executed_bundle_ordinals = list(turn_application.executed_bundle_ordinals)
        repeated_tool_halt = turn_application.repeated_tool_halt
        if (
            next_tool_call_accumulator.pending_tool_calls
            and next_tool_messages
            and terminal_reason == "completed"
            and tool_observation_count > 0
            and _is_retrieval_task_mode(str(task_spec_payload.get("task_mode") or ""))
        ):
            retrieval_followup_observed = True
        if next_tool_call_accumulator.pending_tool_calls and next_tool_messages and terminal_reason == "completed":
            if repeated_tool_halt:
                terminal_reason = "repeated_tool_halt"
                if not final_content:
                    final_answer_metadata = {
                        "answer_channel": "orchestration_fail_closed",
                        "answer_source": "runtime_loop_control",
                        "answer_canonical_state": "no_agent_final_answer",
                        "answer_persist_policy": "persist_debug_only",
                        "answer_finalization_policy": "none",
                        "answer_fallback_reason": "repeated_tool_halt",
                    }
                followup_messages = []
                break
            followup_messages = build_next_followup_messages(
                previous_messages=followup_messages,
                tool_call_accumulator=next_tool_call_accumulator,
                tool_messages=next_tool_messages,
                user_message=user_message,
                aggregation=observation_aggregator.snapshot(),
                current_bundle_items=current_bundle_items,
                remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
            )
            continue
        followup_messages = []
    
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
        tool_call_count=len(tool_call_accumulator.pending_tool_calls),
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
    yield {"type": "runtime_loop_event", "event": artifact_validation_event.to_dict()}
    
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


def _build_initial_task_run_ledger(
    *,
    task_run_id: str,
    task_contract_ref: str,
    task_spec_payload: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
) -> TaskRunLedger | None:
    task_spec = _task_spec_from_payload(task_spec_payload)
    selected_recipe = _recipe_from_payload(selected_recipe_payload)
    if task_spec is None or selected_recipe is None:
        return None
    return build_task_run_ledger(
        task_run_id=task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec=task_spec,
        selected_recipe=selected_recipe,
        status="running",
    )


def _is_retrieval_task_mode(task_mode: str) -> bool:
    normalized = str(task_mode or "").strip().lower()
    return "retrieval" in normalized or "knowledge" in normalized


def _task_spec_from_payload(payload: dict[str, Any]) -> TaskSpec | None:
    if not payload:
        return None
    try:
        return TaskSpec(
            task_id=str(payload.get("task_id") or ""),
            task_spec_ref=str(payload.get("task_spec_ref") or ""),
            recipe_id=str(payload.get("recipe_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_goal=str(payload.get("user_goal") or ""),
            inputs=dict(payload.get("inputs") or {}),
            bindings=dict(payload.get("bindings") or {}),
            constraints=dict(payload.get("constraints") or {}),
            current_turn_context_ref=str(payload.get("current_turn_context_ref") or ""),
            task_intent_ref=str(payload.get("task_intent_ref") or ""),
            bundle_spec_ref=str(payload.get("bundle_spec_ref") or ""),
            bundle_item_ref=str(payload.get("bundle_item_ref") or ""),
            requested_outputs=tuple(str(item) for item in list(payload.get("requested_outputs") or [])),
            step_input_bindings=tuple(
                _step_input_binding_from_payload(item)
                for item in list(payload.get("step_input_bindings") or [])
            ),
            selected_skill_ids=tuple(str(item) for item in list(payload.get("selected_skill_ids") or [])),
            operation_requirement_ref=str(payload.get("operation_requirement_ref") or ""),
            safety_envelope=dict(payload.get("safety_envelope") or {}),
            status=str(payload.get("status") or "selected"),
        )
    except ValueError:
        return None


def _recipe_from_payload(payload: dict[str, Any]) -> ExecutionRecipe | None:
    if not payload:
        return None
    try:
        return ExecutionRecipe(
            recipe_id=str(payload.get("recipe_id") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            execution_kind=str(payload.get("execution_kind") or ""),
            task_mode=str(payload.get("task_mode") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
            allowed_agent_ids=tuple(str(item) for item in list(payload.get("allowed_agent_ids") or ["agent:0"])),
            required_capability_tags=tuple(str(item) for item in list(payload.get("required_capability_tags") or [])),
            required_operations=tuple(str(item) for item in list(payload.get("required_operations") or [])),
            optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or [])),
            step_blueprints=tuple(_task_step_blueprint_from_payload(item) for item in list(payload.get("step_blueprints") or [])),
            validation_rules=tuple(_task_validation_rule_from_payload(item) for item in list(payload.get("validation_rules") or [])),
            safety_policy=dict(payload.get("safety_policy") or {}),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
            finalization_policy=dict(payload.get("finalization_policy") or {}),
            ui_manifest=dict(payload.get("ui_manifest") or {}),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )
    except ValueError:
        return None


def _task_step_blueprint_from_payload(payload: Any) -> TaskStepBlueprint:
    data = dict(payload or {})
    return TaskStepBlueprint(
        step_id=str(data.get("step_id") or ""),
        title=str(data.get("title") or ""),
        step_kind=str(data.get("step_kind") or ""),
        executor_type=str(data.get("executor_type") or ""),
        required_operations=tuple(str(item) for item in list(data.get("required_operations") or [])),
        optional_operations=tuple(str(item) for item in list(data.get("optional_operations") or [])),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        output_contract_id=str(data.get("output_contract_id") or ""),
        stop_policy=str(data.get("stop_policy") or "on_success"),
        retry_policy=dict(data.get("retry_policy") or {}),
    )


def _step_input_binding_from_payload(payload: Any) -> StepInputBinding:
    data = dict(payload or {})
    return StepInputBinding(
        step_id=str(data.get("step_id") or ""),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        inherited_parent_refs=tuple(str(item) for item in list(data.get("inherited_parent_refs") or [])),
        private_state_refs=tuple(str(item) for item in list(data.get("private_state_refs") or [])),
        output_writebacks=dict(data.get("output_writebacks") or {}),
        binding_policy=str(data.get("binding_policy") or "inherit_parent_context"),
    )


def _bundle_items_from_runtime_contract(
    *,
    task_spec_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    bundle_spec = dict(dict(task_spec_payload.get("inputs") or {}).get("bundle_spec") or {})
    bundle_spec_items = [
        dict(item)
        for item in list(bundle_spec.get("items") or [])
        if isinstance(item, dict)
    ]
    return [
        {
            **item,
            "bundle_id": str(bundle_spec.get("bundle_id") or item.get("bundle_id") or ""),
        }
        for item in bundle_spec_items
    ]


def _task_validation_rule_from_payload(payload: Any) -> TaskValidationRule:
    data = dict(payload or {})
    return TaskValidationRule(
        rule_id=str(data.get("rule_id") or ""),
        title=str(data.get("title") or ""),
        validation_kind=str(data.get("validation_kind") or ""),
        severity=str(data.get("severity") or "warning"),
        parameters=dict(data.get("parameters") or {}),
        message=str(data.get("message") or ""),
    )


def _runtime_limits_from_task_operation(
    task_operation: dict[str, Any],
    *,
    fallback: RuntimeLoopLimits,
) -> RuntimeLoopLimits:
    task_spec = dict(task_operation.get("task_spec") or {})
    task_assembly = dict(task_operation.get("task_execution_assembly") or {})
    execution_policy = dict(task_operation.get("task_execution_policy") or {})
    metadata = dict(task_assembly.get("metadata") or {})
    constraints = dict(task_spec.get("constraints") or {})
    policy_metadata = dict(execution_policy.get("metadata") or {})
    limits = {
        **dict(metadata.get("runtime_limits") or {}),
        **dict(policy_metadata.get("runtime_limits") or {}),
        **dict(constraints.get("runtime_limits") or {}),
    }
    if not limits:
        return fallback
    return RuntimeLoopLimits.from_policy(limits, fallback=fallback)


def _resolve_runtime_search_sources(
    *,
    search_policy: list[str] | tuple[str, ...] | set[str] | None,
    task_selection: dict[str, Any] | None,
) -> set[str]:
    if search_policy is not None:
        return normalize_search_policy(search_policy)
    selection = dict(task_selection or {})
    if _selection_is_coordination_task(selection):
        explicit_policy = _extract_task_search_policy(selection)
        if explicit_policy is not None:
            return normalize_search_policy(explicit_policy)
        return set()
    return normalize_search_policy(None)


def _selection_is_coordination_task(selection: dict[str, Any]) -> bool:
    if str(selection.get("continuation_stage_id") or "").strip():
        return True
    if str(selection.get("coordination_run_id") or "").strip():
        return True
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    if str(runtime_assembly.get("runtime_lane") or "").strip() == "coordination_task":
        return True
    return str(selection.get("runtime_lane") or "").strip() == "coordination_task"


def _intent_continuation_trace_events(current_turn_context: dict[str, Any]) -> list[dict[str, Any]]:
    context = dict(current_turn_context or {})
    continuation_candidates = [
        dict(item)
        for item in list(context.get("continuation_candidates") or [])
        if isinstance(item, dict)
    ]
    continuation_decision = dict(context.get("continuation_decision") or {})
    events: list[dict[str, Any]] = []
    if continuation_candidates:
        events.append(
            {
                "event_type": "continuation_candidates_built",
                "payload": {
                    "continuation_candidates": continuation_candidates,
                    "candidate_count": len(continuation_candidates),
                    "compatible_candidate_count": sum(1 for item in continuation_candidates if item.get("compatible") is True),
                },
            }
        )
    if continuation_decision:
        events.append(
            {
                "event_type": "continuation_decision_made",
                "payload": {
                    "continuation_decision": continuation_decision,
                    "selected_candidate_id": str(continuation_decision.get("selected_candidate_id") or ""),
                    "decision_kind": str(continuation_decision.get("decision_kind") or ""),
                },
            }
        )
    return events


def _stage_execution_request_diagnostics(selection: dict[str, Any]) -> dict[str, Any]:
    request = dict(selection.get("stage_execution_request") or {})
    request_ref = str(selection.get("stage_execution_request_ref") or "").strip()
    if not request and request_ref:
        return {
            "stage_request_ref": request_ref,
            "continuation_stage_id": str(selection.get("continuation_stage_id") or ""),
        }
    if not request:
        return {}
    stage_id = str(request.get("stage_id") or request.get("node_id") or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=str(request.get("coordination_run_id") or ""),
            node_id=str(request.get("node_id") or stage_id),
            explicit_inputs=dict(request.get("explicit_inputs") or {}),
            dispatch_context=dict(request.get("dispatch_context") or {}),
        )
    return {
        "stage_execution_request": request,
        "coordination_run_id": str(request.get("coordination_run_id") or ""),
        "coordination_stage_id": stage_id,
        "stage_id": stage_id,
        "node_id": str(request.get("node_id") or stage_id),
        "stage_request_id": str(request.get("request_id") or ""),
        "stage_idempotency_key": idempotency_key,
        "stage_dispatch_event_id": str(dict(request.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
        "continuation_stage_id": str(selection.get("continuation_stage_id") or stage_id),
    }


def _task_order_runtime_binding_diagnostics(
    *,
    task_order_ref: dict[str, Any] | None,
    task_order_run_ref: dict[str, Any] | None,
    execution_channel_ref: dict[str, Any] | None,
    task_execution_envelope_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    order = dict(task_order_ref or {})
    run = dict(task_order_run_ref or {})
    channel = dict(execution_channel_ref or {})
    envelope = dict(task_execution_envelope_ref or {})
    order_id = str(order.get("order_id") or run.get("order_id") or channel.get("order_id") or envelope.get("order_id") or "")
    run_id = str(run.get("run_id") or channel.get("order_run_id") or envelope.get("order_run_id") or "")
    channel_id = str(channel.get("channel_id") or run.get("primary_execution_channel_id") or envelope.get("execution_channel_id") or "")
    envelope_id = str(envelope.get("envelope_id") or "")
    if not any((order_id, run_id, channel_id, envelope_id)):
        return {
            "binding_kind": "unbound_chat_turn_runtime",
            "task_order_bound": False,
            "authority": "task_system.task_order_runtime_binding",
        }
    return {
        "projection_kind": "task_order",
        "task_order_bound": True,
        "task_order_id": order_id,
        "task_order_run_id": run_id,
        "execution_channel_id": channel_id,
        "task_execution_envelope_id": envelope_id,
        "task_order_kind": str(order.get("order_kind") or ""),
        "task_order_source": str(order.get("source") or ""),
        "task_order_source_ref": str(order.get("source_ref") or ""),
        "task_order_task_id": str(order.get("task_id") or ""),
        "task_order_status": str(order.get("status") or ""),
        "task_order_run_status": str(run.get("status") or ""),
        "execution_channel_status": str(channel.get("status") or ""),
        "authority": "task_system.task_order_runtime_binding",
    }


def _extract_task_search_policy(selection: dict[str, Any]) -> list[str] | tuple[str, ...] | set[str] | None:
    for key in ("search_policy", "allowed_search_sources"):
        value = selection.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    operation_policy = dict(selection.get("operation_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = operation_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    permission_policy = dict(runtime_assembly.get("permission_policy") or runtime_assembly.get("resource_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = permission_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    return None


def _agent_profile_id_for_runtime_spec(registry: Any, runtime_spec_payload: dict[str, Any]) -> str:
    agent_id = str(runtime_spec_payload.get("agent_id") or "").strip()
    if not agent_id:
        return ""
    getter = getattr(registry, "get_profile", None)
    if not callable(getter):
        return ""
    profile = getter(agent_id)
    return str(getattr(profile, "agent_profile_id", "") or "").strip()


def _diagnostic_int(payload: dict[str, Any], key: str) -> int:
    diagnostics = dict(payload.get("diagnostics") or {})
    try:
        return int(diagnostics.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _build_direct_agent_invocation_payload(
    *,
    base_dir: Path,
    task_id: str,
    user_message: str,
    task_selection: dict[str, Any] | None = None,
    agent_runtime_profile: Any | None = None,
) -> dict[str, Any]:
    selection = dict(task_selection or {})
    work_order = DirectWorkOrder(
        work_order_id="",
        task_ref=str(
            selection.get("selected_task_id")
            or selection.get("task_id")
            or selection.get("specific_task_id")
            or task_id
            or "task.runtime.direct"
        ),
        coordination_run_id=str(selection.get("coordination_run_id") or ""),
        thread_id=str(selection.get("thread_id") or selection.get("coordination_run_id") or ""),
        root_task_run_id=str(selection.get("root_task_run_id") or ""),
        agent_id=str(selection.get("agent_id") or getattr(agent_runtime_profile, "agent_id", "") or ""),
        agent_profile_id=str(selection.get("agent_profile_id") or getattr(agent_runtime_profile, "agent_profile_id", "") or ""),
        runtime_lane=str(selection.get("runtime_lane") or ""),
        message=user_message,
        explicit_inputs=dict(selection.get("explicit_inputs") or {}),
        input_package=dict(selection.get("input_package") or selection.get("standard_input_package") or {}),
        current_turn_context=build_model_context_payload(current_turn_context=selection),
        artifact_policy=dict(selection.get("artifact_policy") or {}),
        stream_policy=dict(selection.get("stream_policy") or {}),
        artifact_root=str(selection.get("artifact_root") or ""),
        runtime_assembly=_direct_runtime_assembly_from_selection(selection),
    )
    return build_agent_invocation(
        work_order,
        base_dir=base_dir,
        agent_runtime_profile=agent_runtime_profile,
    ).to_dict()


def _direct_runtime_assembly_from_selection(selection: dict[str, Any]) -> dict[str, Any]:
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    operation_policy = dict(selection.get("operation_policy") or {})
    if operation_policy:
        runtime_assembly["operation_policy"] = operation_policy
    return runtime_assembly


def _model_requirement_for_model_resolution(
    *,
    task_execution_assembly: dict[str, Any] | None,
    current_turn_context: dict[str, Any] | None,
    agent_assembly_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    task_assembly = dict(task_execution_assembly or {})
    current_turn = dict(current_turn_context or {})
    assembly = dict(agent_assembly_contract or {})
    candidates = [
        dict(dict(task_assembly.get("contract_bindings") or {}).get("runtime") or {}).get("model_requirement"),
        dict(assembly.get("metadata") or {}).get("model_requirement"),
        dict(dict(assembly.get("prompt_assembly") or {}).get("metadata") or {}).get("model_requirement"),
        dict(dict(dict(assembly.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings") or {}).get("runtime", {}).get("model_requirement")
        if isinstance(dict(dict(assembly.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings"), dict)
        else {},
        dict(dict(dict(current_turn.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings") or {}).get("runtime", {}).get("model_requirement")
        if isinstance(dict(dict(current_turn.get("runtime_assembly") or {}).get("metadata") or {}).get("contract_bindings"), dict)
        else {},
        dict(dict(current_turn.get("contract_bindings") or {}).get("runtime") or {}).get("model_requirement"),
        dict(current_turn.get("model_requirement") or {}),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    return {}


def _merge_invocation_identity_into_task_selection(
    *,
    task_selection: dict[str, Any] | None,
    invocation_payload: dict[str, Any] | None,
    assembly_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    selection = dict(task_selection or {})
    invocation = dict(invocation_payload or {})
    invocation_selection = dict(invocation.get("task_selection") or {})
    assembly = dict(assembly_contract or {})
    work_order = dict(invocation.get("work_order") or assembly.get("work_order") or {})

    task_ref = str(
        invocation.get("task_ref")
        or assembly.get("task_ref")
        or work_order.get("task_ref")
        or invocation_selection.get("selected_task_id")
        or invocation_selection.get("task_id")
        or ""
    ).strip()
    if task_ref:
        selection["selected_task_id"] = task_ref
        selection["task_id"] = task_ref
        selection["specific_task_id"] = task_ref

    for key in ("stage_execution_request_ref", "continuation_stage_id", "coordination_run_id"):
        value = invocation_selection.get(key)
        if _has_runtime_value(value):
            selection[key] = value
    for key in ("work_order_id", "assembly_id", "executor_type", "agent_id", "agent_profile_id", "runtime_lane"):
        value = assembly.get(key) or invocation_selection.get(key)
        if _has_runtime_value(value):
            selection[key] = value
    projection_id = assembly.get("projection_id") or invocation_selection.get("projection_id")
    if _has_runtime_value(projection_id):
        selection["projection_id"] = projection_id
        selection["selected_projection_id"] = projection_id
    if _has_runtime_value(invocation.get("invocation_id")):
        selection["agent_invocation_id"] = str(invocation.get("invocation_id") or "")
    selection.pop("agent_invocation", None)
    return selection


def _has_runtime_value(value: Any) -> bool:
    return value not in ("", None, [], {})


def _assert_agent_runtime_spec_matches_invocation(
    agent_runtime_spec: dict[str, Any],
    assembly_contract: dict[str, Any],
    *,
    strict_runtime_lane: bool,
) -> None:
    spec = dict(agent_runtime_spec or {})
    assembly = dict(assembly_contract or {})
    expected_agent_id = str(assembly.get("agent_id") or "").strip()
    actual_agent_id = str(spec.get("agent_id") or "").strip()
    if expected_agent_id and actual_agent_id and expected_agent_id != actual_agent_id:
        raise ValueError(
            "AgentRuntimeSpec agent_id does not match AgentInvocation: "
            f"expected {expected_agent_id}, got {actual_agent_id}"
        )
    expected_runtime_lane = str(assembly.get("runtime_lane") or "").strip()
    actual_runtime_lane = str(spec.get("runtime_lane") or "").strip()
    if strict_runtime_lane and expected_runtime_lane and actual_runtime_lane and expected_runtime_lane != actual_runtime_lane:
        raise ValueError(
            "AgentRuntimeSpec runtime_lane does not match AgentInvocation: "
            f"expected {expected_runtime_lane}, got {actual_runtime_lane}"
        )


def _assembly_contract_diagnostics(assembly_contract: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(assembly_contract or {})
    if not assembly:
        return {}
    return {
        "assembly_id": str(assembly.get("assembly_id") or ""),
        "work_order_id": str(assembly.get("work_order_id") or ""),
        "work_kind": str(assembly.get("work_kind") or ""),
        "agent_id": str(assembly.get("agent_id") or ""),
        "agent_profile_id": str(assembly.get("agent_profile_id") or ""),
        "runtime_lane": str(assembly.get("runtime_lane") or ""),
        "executor_type": str(assembly.get("executor_type") or ""),
    }


def _agent_invocation_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _agent_invocation_diagnostics(invocation: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(invocation or {})
    if not payload:
        return {}
    return {
        "invocation_id": str(payload.get("invocation_id") or ""),
        "work_order_id": str(payload.get("work_order_id") or ""),
        "assembly_id": str(payload.get("assembly_id") or ""),
        "task_ref": str(payload.get("task_ref") or ""),
        "executor_type": str(payload.get("executor_type") or ""),
        "agent_id": str(payload.get("agent_id") or ""),
        "agent_profile_id": str(payload.get("agent_profile_id") or ""),
        "runtime_lane": str(payload.get("runtime_lane") or ""),
    }


def _persist_agent_invocation_boundary_objects(
    runtime_objects: RuntimeObjectStore,
    *,
    task_run_id: str,
    agent_invocation: dict[str, Any] | None,
    assembly_contract: dict[str, Any] | None,
    execution_permit: dict[str, Any] | None,
) -> dict[str, str]:
    invocation = dict(agent_invocation or {})
    assembly = dict(assembly_contract or {})
    permit = dict(execution_permit or {})
    refs: dict[str, str] = {}
    invocation_id = str(invocation.get("invocation_id") or "").strip()
    assembly_id = str(assembly.get("assembly_id") or "").strip()
    permit_id = str(permit.get("permit_id") or "").strip()
    if invocation_id:
        refs["agent_invocation_object_ref"] = runtime_objects.put_json_once(
            "agent_invocation",
            invocation_id,
            {
                "task_run_id": task_run_id,
                "agent_invocation": invocation,
                "agent_invocation_summary": _agent_invocation_diagnostics(invocation),
            },
        )
    if assembly_id:
        refs["agent_assembly_object_ref"] = runtime_objects.put_json_once(
            "agent_assembly_contract",
            assembly_id,
            {
                "task_run_id": task_run_id,
                "agent_assembly_contract": assembly,
                "agent_assembly_summary": _assembly_contract_diagnostics(assembly),
            },
        )
    if permit_id:
        refs["execution_permit_object_ref"] = runtime_objects.put_json_once(
            "execution_permit",
            permit_id,
            {
                "task_run_id": task_run_id,
                "execution_permit": permit,
                "execution_permit_summary": _execution_permit_diagnostics(permit),
            },
        )
    return refs


def _chat_model_selection_runtime_defaults(model_selection: dict[str, Any] | None) -> dict[str, Any]:
    selection = dict(model_selection or {})
    provider = str(selection.get("provider") or "").strip().lower()
    model = str(selection.get("model") or "").strip()
    base_url = str(selection.get("base_url") or "").strip()
    if not provider or not model:
        return {}
    defaults: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "credential_ref": str(selection.get("credential_ref") or f"provider:{provider}:primary").strip(),
    }
    if base_url:
        defaults["base_url"] = base_url
    thinking_mode = str(selection.get("thinking_mode") or "").strip().lower()
    if thinking_mode in {"enabled", "disabled"}:
        defaults["thinking_mode"] = thinking_mode
    reasoning_effort = str(selection.get("reasoning_effort") or "").strip().lower()
    if reasoning_effort in {"high", "max"}:
        defaults["reasoning_effort"] = reasoning_effort
    return defaults
