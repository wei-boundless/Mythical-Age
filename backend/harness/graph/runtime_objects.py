from __future__ import annotations

from typing import Any

from .flow_packet import FlowPacket
from .models import GraphNodeWorkOrder, NodeResultEnvelope, stable_safe_id


WORK_ORDER_KIND = "graph_node_work_order"
NODE_RESULT_KIND = "graph_node_result"
FLOW_PACKET_KIND = "graph_flow_packet"


def store_work_order(services: Any, order: GraphNodeWorkOrder) -> str:
    store = _runtime_object_store(services)
    if store is None:
        raise RuntimeError("GraphLoop requires runtime_objects to persist GraphNodeWorkOrder payloads")
    return str(store.put_object(WORK_ORDER_KIND, stable_safe_id(order.work_order_id), order.to_dict()))


def store_node_result(services: Any, result: NodeResultEnvelope) -> str:
    store = _runtime_object_store(services)
    if store is None:
        raise RuntimeError("GraphLoop requires runtime_objects to persist NodeResultEnvelope payloads")
    return str(store.put_object(NODE_RESULT_KIND, stable_safe_id(result.result_id), result.to_dict()))


def store_flow_packet(services: Any, packet: FlowPacket) -> str:
    store = _runtime_object_store(services)
    if store is None:
        raise RuntimeError("GraphLoop requires runtime_objects to persist FlowPacket payloads")
    return str(store.put_object(FLOW_PACKET_KIND, stable_safe_id(packet.packet_id), packet.to_dict()))


def load_work_order(services: Any, entry: dict[str, Any]) -> GraphNodeWorkOrder | None:
    payload = _load_payload(services, entry, ref_key="work_order_ref")
    if not payload:
        return None
    return GraphNodeWorkOrder.from_dict(payload)


def load_node_result(services: Any, entry: dict[str, Any]) -> NodeResultEnvelope | None:
    payload = _load_payload(services, entry, ref_key="result_ref")
    if not payload:
        return None
    return NodeResultEnvelope.from_dict(payload)


def load_flow_packet(services: Any, entry: dict[str, Any]) -> FlowPacket | None:
    payload = _load_payload(services, entry, ref_key="packet_ref")
    if not payload:
        return None
    return FlowPacket.from_dict(payload)


def work_order_summary(order: GraphNodeWorkOrder, *, work_order_ref: str = "") -> dict[str, Any]:
    return {
        "authority": "harness.graph_node_work_order_summary",
        "work_order_id": order.work_order_id,
        "work_order_ref": work_order_ref,
        "work_kind": order.work_kind,
        "graph_run_id": order.graph_run_id,
        "task_run_id": order.task_run_id,
        "node_id": order.node_id,
        "config_id": order.config_id,
        "config_hash": order.config_hash,
        "executor_type": order.executor_type,
        "agent_id": order.agent_id,
        "agent_profile_id": order.agent_profile_id,
        "idempotency_key": order.idempotency_key,
        "input_package_ref": str(dict(order.input_package or {}).get("package_id") or ""),
        "inbound_context_count": len(list(dict(order.input_package or {}).get("inbound_context") or [])),
        "artifact_space_ref": order.artifact_space_ref,
        "memory_space_ref": order.memory_space_ref,
    }


def node_result_summary(result: NodeResultEnvelope, *, result_ref: str = "") -> dict[str, Any]:
    outputs = dict(result.outputs or {})
    return {
        "authority": "harness.graph_node_result_summary",
        "result_id": result.result_id,
        "result_ref": result_ref,
        "graph_run_id": result.graph_run_id,
        "task_run_id": result.task_run_id,
        "node_id": result.node_id,
        "work_order_id": result.work_order_id,
        "node_executor_task_run_id": str(outputs.get("node_executor_task_run_id") or ""),
        "executor_type": result.executor_type,
        "status": result.status,
        "artifact_refs": list(result.artifact_refs),
        "artifact_ref_count": len(result.artifact_refs),
        "memory_candidate_count": len(result.memory_candidates),
        "progress_receipt_count": len(result.progress_receipts),
        "artifact_materialization_receipt_count": len(result.artifact_materialization_receipts),
        "memory_commit_receipt_count": len(result.memory_commit_receipts),
        "handoff_summary": result.handoff_summary[:1200],
        "error": dict(result.error or {}),
        "created_at": result.created_at,
    }


def flow_packet_summary(packet: FlowPacket, *, packet_ref: str = "") -> dict[str, Any]:
    return {
        "authority": "harness.graph_flow_packet_summary",
        "packet_id": packet.packet_id,
        "packet_ref": packet_ref,
        "packet_type": packet.packet_type,
        "graph_run_id": packet.graph_run_id,
        "task_run_id": packet.task_run_id,
        "source_node_id": packet.source_unit_id,
        "target_node_id": packet.target_unit_id,
        "edge_id": packet.edge_id,
        "status": packet.status,
        "contract_id": packet.contract_id,
        "packet_contract_id": packet.packet_contract_id,
        "target_context_key": packet.target_context_key,
        "target_input_slot": packet.target_input_slot,
        "delivery_policy": str(dict(packet.visibility or {}).get("delivery_policy") or ""),
        "payload_summary": packet.payload_summary[:1200],
        "artifact_ref_count": len(packet.artifact_refs),
        "memory_ref_count": len(packet.memory_refs),
        "receipt_ref_count": len(packet.receipt_refs),
        "result_ref_count": len(packet.result_refs),
        "has_visible_payload": bool(packet.visible_payload),
        "created_at": packet.created_at,
    }


def _load_payload(services: Any, entry: dict[str, Any], *, ref_key: str) -> dict[str, Any]:
    payload = dict(entry or {})
    ref = str(payload.get(ref_key) or "").strip()
    store = _runtime_object_store(services)
    if ref and store is not None:
        stored = store.get_object(ref)
        if stored:
            return dict(stored)
    return payload if payload.get("authority") not in {
        "harness.graph_node_work_order_summary",
        "harness.graph_node_result_summary",
        "harness.graph_flow_packet_summary",
    } else {}


def _runtime_object_store(services: Any) -> Any | None:
    return getattr(services, "runtime_objects", None)
