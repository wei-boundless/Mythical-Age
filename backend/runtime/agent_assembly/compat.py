from __future__ import annotations

from typing import Any

from runtime.execution.node_execution_request import NodeExecutionRequest

from .models import HumanWorkOrder, SubRuntimeWorkOrder, WorkOrder


def work_order_from_node_execution_request(request: NodeExecutionRequest) -> WorkOrder:
    return WorkOrder.from_dict(
        {
            "work_order_id": request.request_id,
            "work_kind": "node" if str(request.stage_id or request.node_id or "").strip() else "direct",
            "task_ref": request.task_ref,
            "executor_type": request.executor_type,
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
            "executor_binding": dict(request.executor_binding),
            "current_turn_context": dict(request.dispatch_context),
            "artifact_policy": dict(request.artifact_policy),
            "stream_policy": dict(request.stream_policy),
            "artifact_root": str(request.artifact_root or ""),
            "artifact_targets": [dict(item) for item in request.artifact_targets],
            "output_contract_id": request.output_contract_id,
            "expected_outputs": [dict(item) for item in request.expected_outputs],
            "working_memory_refs": list(request.working_memory_refs),
            "dispatch_context": dict(request.dispatch_context),
            "memory_snapshot": dict(request.memory_snapshot),
            "artifact_context_packet": dict(request.artifact_context_packet),
            "revision_packet": dict(request.revision_packet),
            "handoff_packet_refs": list(request.handoff_packet_refs),
            "timeline_result_policy": dict(request.timeline_result_policy),
            "human_work_packet": dict(request.human_work_packet),
            "a2a_payload": dict(request.a2a_payload),
            "runtime_assembly": dict(request.runtime_assembly),
            "idempotency_key": request.idempotency_key,
        }
    )


def node_execution_request_payload_from_work_order(work_order: WorkOrder) -> dict[str, Any]:
    payload = work_order.to_dict()
    payload["request_id"] = payload.get("work_order_id", "")
    payload["standard_input_package"] = dict(payload.get("input_package") or {})
    payload["stage_id"] = str(payload.get("stage_id") or payload.get("node_id") or "")
    payload["node_id"] = str(payload.get("node_id") or payload.get("stage_id") or "")
    payload["dispatch_context"] = dict(payload.get("dispatch_context") or {})
    payload["runtime_assembly"] = dict(payload.get("runtime_assembly") or {})
    payload["authority"] = "task_graph.node_execution_request"
    return payload


def work_order_from_payload(payload: dict[str, Any]) -> WorkOrder:
    return WorkOrder.from_dict(dict(payload or {}))
