from __future__ import annotations

from typing import Any

from runtime.agent_assembly.models import GraphModuleWorkOrder, HumanWorkOrder, NodeWorkOrder, WorkOrder
from harness.execution.node_protocol.node_execution_request import NodeExecutionRequest


def build_node_work_order_from_request(
    request: NodeExecutionRequest,
    *,
    state: dict[str, Any] | None = None,
) -> WorkOrder:
    """Build the typed coordination-to-assembly work order shadow contract."""
    payload = _base_work_order_payload(request, state=state)
    executor_type = _normalize_work_order_executor(request.executor_type, request.executor_binding, request.runtime_assembly)
    payload["executor_type"] = executor_type
    if executor_type == "human":
        payload["work_kind"] = "human"
        return HumanWorkOrder(**payload)
    if executor_type == "graph_module":
        payload["work_kind"] = "graph_module"
        return GraphModuleWorkOrder(**payload)
    payload["work_kind"] = "node"
    return NodeWorkOrder(**payload)


def node_work_order_payload_from_request(
    request: NodeExecutionRequest,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_node_work_order_from_request(request, state=state).to_dict()


def _base_work_order_payload(
    request: NodeExecutionRequest,
    *,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "work_order_id": request.request_id,
        "work_kind": "node",
        "task_ref": request.task_ref,
        "coordination_run_id": request.coordination_run_id,
        "thread_id": request.thread_id,
        "root_task_run_id": request.root_task_run_id,
        "stage_id": request.stage_id,
        "node_id": request.node_id,
        "agent_id": request.agent_id,
        "agent_profile_id": request.agent_profile_id,
        "runtime_lane": request.runtime_lane,
        "message": request.message,
        "explicit_inputs": dict(request.explicit_inputs),
        "input_package": dict(request.standard_input_package),
        "graph_state": _graph_state_snapshot(state, request=request),
        "executor_binding": dict(request.executor_binding),
        "current_turn_context": {},
        "artifact_policy": dict(request.artifact_policy),
        "stream_policy": dict(request.stream_policy),
        "artifact_root": request.artifact_root,
        "artifact_targets": tuple(dict(item) for item in request.artifact_targets),
        "output_contract_id": request.output_contract_id,
        "expected_outputs": tuple(dict(item) for item in request.expected_outputs),
        "working_memory_refs": tuple(request.working_memory_refs),
        "dispatch_context": dict(request.dispatch_context),
        "memory_snapshot": dict(request.memory_snapshot),
        "artifact_context_packet": dict(request.artifact_context_packet),
        "revision_packet": dict(request.revision_packet),
        "handoff_packet_refs": tuple(request.handoff_packet_refs),
        "timeline_result_policy": dict(request.timeline_result_policy),
        "human_work_packet": dict(request.human_work_packet),
        "a2a_payload": dict(request.a2a_payload),
        "runtime_assembly": dict(request.runtime_assembly),
        "idempotency_key": request.idempotency_key,
    }


def _normalize_work_order_executor(
    executor_type: str,
    executor_binding: dict[str, Any],
    runtime_assembly: dict[str, Any],
) -> str:
    raw = str(executor_type or dict(executor_binding or {}).get("selected_executor") or "").strip()
    if raw in {"graph_module", "imported_graph"}:
        return "graph_module"
    if raw in {"human", "manual", "operator"}:
        return "human"
    if raw in {"tool"}:
        return "tool"
    if dict(runtime_assembly or {}).get("graph_module_runtime_handle"):
        return "graph_module"
    return "agent"


def _graph_state_snapshot(state: dict[str, Any] | None, *, request: NodeExecutionRequest) -> dict[str, Any]:
    raw = dict(state or {})
    diagnostics = dict(raw.get("diagnostics") or {})
    scheduler_state = dict(diagnostics.get("task_graph_scheduler_state") or {})
    contract_manifest = dict(raw.get("contract_manifest") or {})
    return {
        "coordination_run_id": str(raw.get("coordination_run_id") or request.coordination_run_id),
        "root_task_run_id": str(raw.get("root_task_run_id") or request.root_task_run_id),
        "active_stage_id": str(raw.get("active_stage_id") or request.stage_id),
        "active_node_id": str(raw.get("active_node_id") or request.node_id),
        "active_task_ref": str(raw.get("active_task_ref") or request.task_ref),
        "stage_order": [str(item) for item in list(raw.get("stage_order") or []) if str(item)],
        "node_statuses": dict(raw.get("node_statuses") or {}),
        "ready_nodes": list(raw.get("ready_nodes") or []),
        "blocked_nodes": list(raw.get("blocked_nodes") or []),
        "running_nodes": list(raw.get("running_nodes") or []),
        "completed_nodes": list(raw.get("completed_nodes") or []),
        "failed_nodes": list(raw.get("failed_nodes") or []),
        "contract_manifest_ref": str(contract_manifest.get("manifest_id") or diagnostics.get("contract_manifest_ref") or ""),
        "graph_ref": str(diagnostics.get("graph_ref") or ""),
        "scheduler_state_ref": str(scheduler_state.get("scheduler_state_id") or scheduler_state.get("state_id") or ""),
        "authority": "task_graph.node_work_order_graph_state_snapshot",
    }

