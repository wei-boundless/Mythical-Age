from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..shared.dispatch_plan_compiler import _normalize_runtime_graph_payload
from .config import build_agent_runtime_config
from .context import (
    agent_profile_id_for_runtime_spec,
    assert_agent_runtime_spec_matches_invocation,
    build_direct_agent_invocation_payload,
    runtime_limits_from_task_operation,
)
from .execution_permit import resolve_agent_execution_permit


@dataclass(frozen=True, slots=True)
class AgentRuntimeAssembly:
    chain_runtime: dict[str, Any]
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
    raw_graph_payload: dict[str, Any]
    task_graph_payload: dict[str, Any]
    runtime_spec_payload: dict[str, Any]
    graph_payload: dict[str, Any]
    task_body_orchestration_payload: dict[str, Any]
    agent_runtime_spec_payload: dict[str, Any]
    invocation_payload: dict[str, Any]
    assembly_contract: dict[str, Any]
    stream_policy: dict[str, Any]
    artifact_policy: dict[str, Any]
    effective_agent_runtime_profile: Any
    effective_agent_profile_id: str
    agent_runtime_config: Any
    execution_permit: dict[str, Any]
    agent_runtime_enabled_phases: set[str]
    memory_view: dict[str, Any]
    context_policy: dict[str, Any]
    execution_mode: str
    effective_limits: Any


def build_agent_runtime_assembly(
    *,
    runtime_host: Any,
    agent_runtime_chain: Any,
    session_id: str,
    task_id: str,
    user_message: str,
    source: str,
    runtime_chain_task_selection: dict[str, Any],
    runtime_context_override: dict[str, Any],
    allowed_search_sources: set[str],
    agent_runtime_profile: Any | None,
    invocation_payload: dict[str, Any],
    invocation_is_explicit: bool,
    assembly_contract: dict[str, Any],
    stream_policy: dict[str, Any],
    artifact_policy: dict[str, Any],
) -> AgentRuntimeAssembly:
    """Assemble the runtime packet after model-owned turn admission.

    This function normalizes system-provided task and agent assembly inputs. It
    must not run model turns, dispatch tools, perform finalization, or reinterpret
    the user's semantic intent.
    """

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
        task_operation["runtime_stream_policy"] = dict(stream_policy)
    if artifact_policy:
        task_operation["runtime_artifact_policy"] = dict(artifact_policy)

    task_contract = dict(task_operation.get("task_contract") or {})
    task_intent_contract = dict(task_operation.get("task_intent_contract") or {})
    selected_recipe_payload = dict(task_operation.get("selected_recipe") or {})
    bundle_spec_payload = dict(task_operation.get("bundle_spec") or {})
    task_spec_payload = dict(task_operation.get("task_spec") or {})
    task_execution_assembly_payload = dict(task_operation.get("task_execution_assembly") or {})
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
    task_body_orchestration_payload = dict(
        chain_runtime.get("task_body_orchestration")
        or task_operation.get("task_body_orchestration")
        or {}
    )
    agent_runtime_spec_payload = dict(
        chain_runtime.get("agent_runtime_spec")
        or task_operation.get("agent_runtime_spec")
        or {}
    )

    effective_invocation_payload = dict(invocation_payload or {})
    effective_assembly_contract = dict(assembly_contract or {})
    effective_stream_policy = dict(stream_policy or {})
    effective_artifact_policy = dict(artifact_policy or {})
    if not invocation_is_explicit:
        direct_selection = {
            **dict(runtime_chain_task_selection or {}),
            "agent_id": str(agent_runtime_spec_payload.get("agent_id") or ""),
            "agent_profile_id": str(
                agent_runtime_spec_payload.get("agent_profile_id")
                or agent_profile_id_for_runtime_spec(
                    runtime_host.agent_runtime_registry,
                    agent_runtime_spec_payload,
                )
                or ""
            ),
            "runtime_lane": str(agent_runtime_spec_payload.get("runtime_lane") or ""),
        }
        effective_invocation_payload = build_direct_agent_invocation_payload(
            base_dir=runtime_host.backend_dir,
            task_id=task_id,
            user_message=user_message,
            task_selection=direct_selection,
            agent_runtime_profile=agent_runtime_profile,
        )
        effective_assembly_contract = dict(effective_invocation_payload.get("assembly_contract") or {})
        if not effective_assembly_contract:
            raise RuntimeError("AgentRuntime invocation could not build direct AgentInvocation assembly contract")
        effective_stream_policy = dict(effective_assembly_contract.get("stream_policy") or effective_stream_policy)
        effective_artifact_policy = dict(effective_assembly_contract.get("artifact_policy") or effective_artifact_policy)

    if effective_assembly_contract:
        assert_agent_runtime_spec_matches_invocation(
            agent_runtime_spec_payload,
            effective_assembly_contract,
            strict_runtime_lane=invocation_is_explicit,
        )

    effective_agent_runtime_profile = agent_runtime_profile or runtime_host.agent_runtime_registry.get_profile(
        str(agent_runtime_spec_payload.get("agent_id") or "").strip()
    )
    effective_agent_profile_id = str(agent_runtime_spec_payload.get("agent_profile_id") or "").strip()
    if not effective_agent_profile_id:
        effective_agent_profile_id = str(
            getattr(effective_agent_runtime_profile, "agent_profile_id", "")
            or agent_profile_id_for_runtime_spec(
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
        effective_assembly_contract,
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

    return AgentRuntimeAssembly(
        chain_runtime=dict(chain_runtime),
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
        raw_graph_payload=raw_graph_payload,
        task_graph_payload=task_graph_payload,
        runtime_spec_payload=runtime_spec_payload,
        graph_payload=graph_payload,
        task_body_orchestration_payload=task_body_orchestration_payload,
        agent_runtime_spec_payload=agent_runtime_spec_payload,
        invocation_payload=effective_invocation_payload,
        assembly_contract=effective_assembly_contract,
        stream_policy=effective_stream_policy,
        artifact_policy=effective_artifact_policy,
        effective_agent_runtime_profile=effective_agent_runtime_profile,
        effective_agent_profile_id=effective_agent_profile_id,
        agent_runtime_config=agent_runtime_config,
        execution_permit=dict(execution_permit or {}),
        agent_runtime_enabled_phases=set(agent_runtime_config.enabled_phases),
        memory_view=dict(chain_runtime.get("memory_runtime_view") or {}),
        context_policy=dict(chain_runtime.get("context_policy_result") or {}),
        execution_mode=str(task_execution_policy_payload.get("execution_mode") or "single_agent"),
        effective_limits=runtime_limits_from_task_operation(task_operation, fallback=runtime_host.limits),
    )
