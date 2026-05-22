from __future__ import annotations

from typing import Any

from runtime.execution.node_execution_request import NodeExecutionRequest

from .compat import node_execution_request_payload_from_work_order, work_order_from_node_execution_request, work_order_from_payload
from .models import DirectWorkOrder, HumanWorkOrder, NodeWorkOrder, SubRuntimeWorkOrder, WorkOrder


def work_order_from_legacy_payload(payload: dict[str, Any]) -> WorkOrder:
    work_order = work_order_from_payload(payload)
    return _narrow_work_order(
        work_order,
        subruntime_kind=str(dict(payload or {}).get("subruntime_kind") or "").strip(),
    )


def work_order_from_node_execution_request_legacy(request: NodeExecutionRequest) -> WorkOrder:
    work_order = work_order_from_node_execution_request(request)
    return _narrow_work_order(
        work_order,
        subruntime_kind=str(dict(request.runtime_assembly or {}).get("subruntime_kind") or dict(request.executor_binding or {}).get("subruntime_kind") or "").strip(),
    )


def payload_from_work_order(work_order: WorkOrder) -> dict[str, Any]:
    return node_execution_request_payload_from_work_order(work_order)


def _narrow_work_order(work_order: WorkOrder, *, subruntime_kind: str = "") -> WorkOrder:
    executor_type = str(work_order.executor_type or "").strip().lower()
    if executor_type == "human":
        return HumanWorkOrder(**work_order.to_dict())
    if executor_type not in {"", "agent"}:
        narrowed = dict(work_order.to_dict())
        narrowed["subruntime_kind"] = subruntime_kind or executor_type
        return SubRuntimeWorkOrder(**narrowed)
    if work_order.work_kind == "direct" or not str(work_order.stage_id or work_order.node_id or "").strip():
        return DirectWorkOrder(**work_order.to_dict())
    if work_order.work_kind == "node":
        return NodeWorkOrder(**work_order.to_dict())
    return work_order
