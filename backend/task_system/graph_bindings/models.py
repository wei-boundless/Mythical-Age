from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


GraphNodeTaskBindingStatus = Literal["created", "bound", "leased", "waiting_resume", "completed", "completed_with_failure", "aborted"]


@dataclass(frozen=True, slots=True)
class GraphNodeTaskBinding:
    binding_id: str
    graph_run_id: str
    graph_id: str
    config_id: str
    structure_hash: str
    node_id: str
    work_order_id: str
    node_task_environment_id: str
    task_instance_id: str
    task_ref: str
    parent_task_environment_id: str = ""
    agent_profile_id: str = ""
    input_package_ref: str = ""
    expected_result_contract_ref: str = ""
    lease_policy: dict[str, Any] = field(default_factory=dict)
    result_projection_policy: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    status: GraphNodeTaskBindingStatus = "created"
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.graph_node_task_binding"

    def __post_init__(self) -> None:
        if self.authority != "task_system.graph_node_task_binding":
            raise ValueError("GraphNodeTaskBinding authority must be task_system.graph_node_task_binding")
        _require_text(self.binding_id, "GraphNodeTaskBinding requires binding_id")
        _require_text(self.graph_run_id, "GraphNodeTaskBinding requires graph_run_id")
        _require_text(self.config_id, "GraphNodeTaskBinding requires config_id")
        _require_text(self.node_id, "GraphNodeTaskBinding requires node_id")
        _require_text(self.work_order_id, "GraphNodeTaskBinding requires work_order_id")
        _require_text(self.node_task_environment_id, "GraphNodeTaskBinding requires node_task_environment_id")
        _require_text(self.task_instance_id, "GraphNodeTaskBinding requires task_instance_id")
        _require_text(self.task_ref, "GraphNodeTaskBinding requires task_ref")
        _require_text(self.idempotency_key, "GraphNodeTaskBinding requires idempotency_key")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphNodeTaskBinding":
        data = dict(payload or {})
        return cls(
            binding_id=str(data.get("binding_id") or ""),
            graph_run_id=str(data.get("graph_run_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
            config_id=str(data.get("config_id") or ""),
            structure_hash=str(data.get("structure_hash") or ""),
            node_id=str(data.get("node_id") or ""),
            work_order_id=str(data.get("work_order_id") or ""),
            node_task_environment_id=str(data.get("node_task_environment_id") or ""),
            task_instance_id=str(data.get("task_instance_id") or ""),
            task_ref=str(data.get("task_ref") or ""),
            parent_task_environment_id=str(data.get("parent_task_environment_id") or ""),
            agent_profile_id=str(data.get("agent_profile_id") or ""),
            input_package_ref=str(data.get("input_package_ref") or ""),
            expected_result_contract_ref=str(data.get("expected_result_contract_ref") or ""),
            lease_policy=dict(data.get("lease_policy") or {}),
            result_projection_policy=dict(data.get("result_projection_policy") or {}),
            idempotency_key=str(data.get("idempotency_key") or ""),
            status=str(data.get("status") or "created"),  # type: ignore[arg-type]
            created_at=_float(data.get("created_at")),
            updated_at=_float(data.get("updated_at")),
            metadata=dict(data.get("metadata") or {}),
            authority=str(data.get("authority") or "task_system.graph_node_task_binding"),
        )


def binding_from_work_order_payload(
    work_order: dict[str, Any],
    *,
    binding_id: str = "",
    node_task_environment_id: str = "",
    task_instance_id: str = "",
    parent_task_environment_id: str = "",
    status: GraphNodeTaskBindingStatus = "created",
) -> GraphNodeTaskBinding:
    dispatch_context = dict(work_order.get("dispatch_context") or {})
    hint = dict(dispatch_context.get("graph_node_task_binding_hint") or {})
    expected_contract = dict(work_order.get("expected_result_contract") or {})
    input_package = dict(work_order.get("input_package") or {})
    return GraphNodeTaskBinding(
        binding_id=binding_id or str(hint.get("binding_id") or ""),
        graph_run_id=str(hint.get("graph_run_id") or work_order.get("graph_run_id") or ""),
        graph_id=str(hint.get("graph_id") or dispatch_context.get("graph_id") or ""),
        config_id=str(hint.get("config_id") or work_order.get("config_id") or ""),
        structure_hash=str(hint.get("structure_hash") or work_order.get("structure_hash") or dispatch_context.get("graph_structure_hash") or ""),
        node_id=str(hint.get("node_id") or work_order.get("node_id") or ""),
        work_order_id=str(hint.get("work_order_id") or work_order.get("work_order_id") or ""),
        parent_task_environment_id=parent_task_environment_id or str(hint.get("parent_task_environment_id") or dispatch_context.get("parent_task_environment_id") or ""),
        node_task_environment_id=node_task_environment_id or str(hint.get("node_task_environment_id") or ""),
        task_instance_id=task_instance_id or str(hint.get("task_instance_id") or ""),
        task_ref=str(hint.get("task_ref") or work_order.get("task_ref") or ""),
        agent_profile_id=str(hint.get("agent_profile_id") or work_order.get("agent_profile_id") or ""),
        input_package_ref=str(hint.get("input_package_ref") or input_package.get("package_ref") or input_package.get("input_package_ref") or ""),
        expected_result_contract_ref=str(hint.get("expected_result_contract_ref") or expected_contract.get("contract_ref") or expected_contract.get("contract_id") or ""),
        lease_policy=dict(hint.get("lease_policy") or work_order.get("async_policy") or {}),
        result_projection_policy=dict(hint.get("result_projection_policy") or dispatch_context.get("result_projection_policy") or {}),
        idempotency_key=str(hint.get("idempotency_key") or work_order.get("idempotency_key") or ""),
        status=status,
        metadata={"source": "graph_node_work_order", "hint_authority": str(hint.get("authority") or "")},
    )


def _require_text(value: str, message: str) -> None:
    if not str(value or "").strip():
        raise ValueError(message)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {}, ())}
