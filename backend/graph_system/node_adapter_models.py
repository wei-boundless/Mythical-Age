from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


GRAPH_NODE_KINDS = frozenset(
    {
        "agent_execution_node",
        "deterministic_system_node",
        "resource_node",
        "memory_repository_node",
        "artifact_repository_node",
        "control_router_node",
        "subgraph_node",
        "materialization_node",
        "external_service_node",
    }
)

GRAPH_NODE_EXECUTION_ADAPTER_KINDS = frozenset(
    {
        "agent_harness",
        "deterministic_system",
        "resource_projection",
        "repository_read",
        "repository_write",
        "control_router",
        "subgraph_runner",
        "materialization",
        "external_service",
    }
)

LEGACY_EXECUTOR_TYPES = frozenset({"agent", "resource", "review_gate", "tool"})
HUMAN_GATE_NODE_TYPES = frozenset({"human_gate", "manual_gate"})
HUMAN_GATE_EXECUTOR_TYPES = frozenset({"human", "human_gate", "manual_gate"})


@dataclass(frozen=True, slots=True)
class GraphNodePhysicalSpec:
    node_id: str
    node_kind: str
    spatial_role: str = ""
    state_role: str = ""
    input_ports: tuple[dict[str, Any], ...] = ()
    output_ports: tuple[dict[str, Any], ...] = ()
    control_ports: tuple[dict[str, Any], ...] = ()
    resource_ports: tuple[dict[str, Any], ...] = ()
    gate_attachments: tuple[dict[str, Any], ...] = ()
    visibility_policy: dict[str, Any] = field(default_factory=dict)
    lifecycle_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "graph_system.node_physical_spec"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.node_physical_spec":
            raise ValueError("GraphNodePhysicalSpec authority must be graph_system.node_physical_spec")
        if not self.node_id:
            raise ValueError("GraphNodePhysicalSpec requires node_id")
        if self.node_kind not in GRAPH_NODE_KINDS:
            raise ValueError(f"unsupported graph node_kind: {self.node_kind}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_ports"] = [dict(item) for item in self.input_ports]
        payload["output_ports"] = [dict(item) for item in self.output_ports]
        payload["control_ports"] = [dict(item) for item in self.control_ports]
        payload["resource_ports"] = [dict(item) for item in self.resource_ports]
        payload["gate_attachments"] = [dict(item) for item in self.gate_attachments]
        return _drop_empty(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GraphNodePhysicalSpec":
        return cls(
            node_id=str(payload.get("node_id") or ""),
            node_kind=str(payload.get("node_kind") or "agent_execution_node"),
            spatial_role=str(payload.get("spatial_role") or ""),
            state_role=str(payload.get("state_role") or ""),
            input_ports=_dict_tuple(payload.get("input_ports")),
            output_ports=_dict_tuple(payload.get("output_ports")),
            control_ports=_dict_tuple(payload.get("control_ports")),
            resource_ports=_dict_tuple(payload.get("resource_ports")),
            gate_attachments=_dict_tuple(payload.get("gate_attachments")),
            visibility_policy=dict(payload.get("visibility_policy") or {}),
            lifecycle_policy=dict(payload.get("lifecycle_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
            authority=str(payload.get("authority") or "graph_system.node_physical_spec"),
        )


@dataclass(frozen=True, slots=True)
class NodeExecutionAdapter:
    adapter_id: str
    adapter_kind: str
    node_id: str = ""
    admission_policy: dict[str, Any] = field(default_factory=dict)
    idempotency_policy: dict[str, Any] = field(default_factory=dict)
    side_effect_policy: dict[str, Any] = field(default_factory=dict)
    result_projection_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "graph_system.node_execution_adapter"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.node_execution_adapter":
            raise ValueError("NodeExecutionAdapter authority must be graph_system.node_execution_adapter")
        if not self.adapter_id:
            raise ValueError("NodeExecutionAdapter requires adapter_id")
        if self.adapter_kind not in GRAPH_NODE_EXECUTION_ADAPTER_KINDS:
            raise ValueError(f"unsupported node execution adapter_kind: {self.adapter_kind}")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NodeExecutionAdapter":
        return cls(
            adapter_id=str(payload.get("adapter_id") or ""),
            adapter_kind=str(payload.get("adapter_kind") or "agent_harness"),
            node_id=str(payload.get("node_id") or ""),
            admission_policy=dict(payload.get("admission_policy") or {}),
            idempotency_policy=dict(payload.get("idempotency_policy") or {}),
            side_effect_policy=dict(payload.get("side_effect_policy") or {}),
            result_projection_policy=dict(payload.get("result_projection_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
            authority=str(payload.get("authority") or "graph_system.node_execution_adapter"),
        )


@dataclass(frozen=True, slots=True)
class NodeActivationPlan:
    activation_id: str
    graph_run_id: str
    node_id: str
    node_kind: str
    adapter_kind: str
    graph_clock_seq: int = 0
    superstep_seq: int = 0
    node_dispatch_seq: int = 0
    activation_kind: str = "execute"
    work_order_ref: str = ""
    operation_ref: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "graph_system.node_activation_plan"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.node_activation_plan":
            raise ValueError("NodeActivationPlan authority must be graph_system.node_activation_plan")
        if not self.activation_id:
            raise ValueError("NodeActivationPlan requires activation_id")
        if not self.graph_run_id:
            raise ValueError("NodeActivationPlan requires graph_run_id")
        if not self.node_id:
            raise ValueError("NodeActivationPlan requires node_id")
        if self.node_kind not in GRAPH_NODE_KINDS:
            raise ValueError(f"unsupported NodeActivationPlan node_kind: {self.node_kind}")
        if self.adapter_kind not in GRAPH_NODE_EXECUTION_ADAPTER_KINDS:
            raise ValueError(f"unsupported NodeActivationPlan adapter_kind: {self.adapter_kind}")

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class NodeGateAttachment:
    gate_id: str
    gate_kind: str
    owner_node_id: str
    trigger: str = "post_node_result"
    policy: dict[str, Any] = field(default_factory=dict)
    allowed_human_actions: tuple[str, ...] = ()
    authority: str = "graph_system.node_gate_attachment"

    def __post_init__(self) -> None:
        if self.authority != "graph_system.node_gate_attachment":
            raise ValueError("NodeGateAttachment authority must be graph_system.node_gate_attachment")
        if not self.gate_id:
            raise ValueError("NodeGateAttachment requires gate_id")
        if not self.owner_node_id:
            raise ValueError("NodeGateAttachment requires owner_node_id")
        if not self.gate_kind:
            raise ValueError("NodeGateAttachment requires gate_kind")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_human_actions"] = list(self.allowed_human_actions)
        return _drop_empty(payload)


def node_physical_spec_from_node(node: dict[str, Any]) -> GraphNodePhysicalSpec:
    _assert_human_gate_is_attachment(node)
    payload = dict(node.get("physical") or node.get("node_physical") or {})
    node_id = str(node.get("node_id") or payload.get("node_id") or "")
    metadata = dict(node.get("metadata") or {})
    node_kind = str(
        payload.get("node_kind")
        or node.get("node_kind")
        or metadata.get("node_kind")
        or _infer_node_kind(node)
    ).strip()
    return GraphNodePhysicalSpec(
        node_id=node_id,
        node_kind=node_kind,
        spatial_role=str(payload.get("spatial_role") or metadata.get("spatial_role") or ""),
        state_role=str(payload.get("state_role") or metadata.get("state_role") or _infer_state_role(node_kind)),
        input_ports=_dict_tuple(payload.get("input_ports") or node.get("input_ports")),
        output_ports=_dict_tuple(payload.get("output_ports") or node.get("output_ports")),
        control_ports=_dict_tuple(payload.get("control_ports") or node.get("control_ports")),
        resource_ports=_dict_tuple(payload.get("resource_ports") or node.get("resource_ports")),
        gate_attachments=tuple(item.to_dict() for item in node_gate_attachments_from_node(node)),
        visibility_policy=dict(payload.get("visibility_policy") or metadata.get("visibility_policy") or {}),
        lifecycle_policy=dict(payload.get("lifecycle_policy") or metadata.get("lifecycle_policy") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def node_execution_adapter_from_node(node: dict[str, Any]) -> NodeExecutionAdapter:
    _assert_human_gate_is_attachment(node)
    payload = dict(node.get("execution_adapter") or node.get("adapter") or {})
    executor = dict(node.get("executor") or {})
    metadata = dict(node.get("metadata") or {})
    node_id = str(node.get("node_id") or "")
    adapter_kind = str(
        payload.get("adapter_kind")
        or executor.get("adapter_kind")
        or metadata.get("adapter_kind")
        or _adapter_kind_for_node(node)
    ).strip()
    adapter_id = str(payload.get("adapter_id") or f"adapter:{node_id}:{adapter_kind}").strip()
    return NodeExecutionAdapter(
        adapter_id=adapter_id,
        adapter_kind=adapter_kind,
        node_id=node_id,
        admission_policy=dict(payload.get("admission_policy") or executor.get("admission_policy") or {}),
        idempotency_policy=dict(payload.get("idempotency_policy") or executor.get("idempotency_policy") or {}),
        side_effect_policy=dict(payload.get("side_effect_policy") or executor.get("side_effect_policy") or {}),
        result_projection_policy=dict(payload.get("result_projection_policy") or executor.get("result_projection_policy") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def node_gate_attachments_from_node(node: dict[str, Any]) -> tuple[NodeGateAttachment, ...]:
    node_id = str(node.get("node_id") or "").strip()
    gates = dict(node.get("gates") or {})
    metadata = dict(node.get("metadata") or {})
    result: list[NodeGateAttachment] = []
    for gate_kind, source in (
        ("review_gate", dict(gates.get("review_gate_policy") or metadata.get("review_gate_policy") or {})),
        ("human_gate", dict(gates.get("human_gate_policy") or metadata.get("human_gate_policy") or {})),
        ("post_node_gate", dict(gates.get("post_node_gate_policy") or metadata.get("post_node_gate_policy") or {})),
    ):
        if not source or source.get("enabled") is False:
            continue
        gate_id = str(source.get("gate_id") or f"gate:{node_id}:{gate_kind}").strip()
        result.append(
            NodeGateAttachment(
                gate_id=gate_id,
                gate_kind=gate_kind,
                owner_node_id=node_id,
                trigger=str(source.get("trigger") or ("post_node_result" if gate_kind == "post_node_gate" else "edge_or_result")),
                policy=source,
                allowed_human_actions=_string_tuple(source.get("allowed_human_actions")),
            )
        )
    return tuple(result)


def work_kind_for_adapter(adapter_kind: str, *, legacy_executor_type: str = "") -> str:
    normalized = str(adapter_kind or "").strip()
    legacy = str(legacy_executor_type or "").strip()
    if legacy in HUMAN_GATE_EXECUTOR_TYPES:
        raise ValueError(
            "human gate is not a graph work order; attach human_gate_policy to a node or edge instead"
        )
    if normalized == "agent_harness":
        return "agent"
    if normalized == "external_service":
        return "tool"
    if normalized == "deterministic_system":
        return "tool"
    if normalized == "resource_projection":
        return "resource"
    if normalized in {"repository_read", "repository_write"}:
        return "repository"
    if normalized == "materialization":
        return "materialization"
    if normalized == "control_router":
        return "control_router"
    if normalized == "subgraph_runner":
        return "subgraph"
    if legacy == "tool":
        return "tool"
    if legacy == "resource":
        return "resource"
    return "agent"


def _infer_node_kind(node: dict[str, Any]) -> str:
    _assert_human_gate_is_attachment(node)
    executor = dict(node.get("executor") or {})
    metadata = dict(node.get("metadata") or {})
    node_type = str(node.get("node_type") or "").strip()
    node_id = str(node.get("node_id") or "").strip()
    executor_type = str(executor.get("executor_type") or metadata.get("executor_type") or "").strip()
    if node_type in {"graph_module", "subgraph"} or metadata.get("graph_module"):
        return "subgraph_node"
    if node_type == "review_gate" or executor_type == "review_gate":
        return "control_router_node"
    if node_type == "tool" or executor_type == "tool":
        return "external_service_node"
    if node_type in {"memory", "memory_repository"} or node_type.endswith("_memory") or node_id.startswith("memory."):
        return "memory_repository_node"
    if node_type in {"artifact", "artifact_repository"} or node_id.startswith("artifact."):
        return "artifact_repository_node"
    if node_type in {"materialization", "commit", "publish"}:
        return "materialization_node"
    if node_type in {"router", "control", "control_router", "join", "fanout"}:
        return "control_router_node"
    if executor_type == "resource" or node_type.endswith("_repository") or node_type.endswith("_ledger"):
        return "resource_node"
    return "agent_execution_node"


def _adapter_kind_for_node(node: dict[str, Any]) -> str:
    _assert_human_gate_is_attachment(node)
    executor = dict(node.get("executor") or {})
    executor_type = str(executor.get("executor_type") or "").strip()
    node_kind = _infer_node_kind(node)
    if node_kind == "agent_execution_node" or executor_type == "agent":
        return "agent_harness"
    if node_kind == "subgraph_node":
        return "subgraph_runner"
    if node_kind == "materialization_node":
        return "materialization"
    if node_kind == "control_router_node":
        return "control_router"
    if node_kind in {"memory_repository_node", "artifact_repository_node"}:
        return "repository_write" if _repository_write_enabled(node) else "repository_read"
    if node_kind == "resource_node":
        return "resource_projection"
    if executor_type == "tool":
        return "external_service"
    return "deterministic_system"


def _infer_state_role(node_kind: str) -> str:
    if node_kind == "agent_execution_node":
        return "observes_and_proposes_state"
    if node_kind in {"memory_repository_node", "artifact_repository_node"}:
        return "stores_state"
    if node_kind == "control_router_node":
        return "routes_state"
    if node_kind == "materialization_node":
        return "materializes_state"
    return "observes_state"


def _repository_write_enabled(node: dict[str, Any]) -> bool:
    memory = dict(node.get("memory") or {})
    artifacts = dict(node.get("artifacts") or {})
    metadata = dict(node.get("metadata") or {})
    return bool(
        memory.get("write_policy")
        or memory.get("writeback_policy")
        or artifacts.get("write_policy")
        or metadata.get("repository_write")
    )


def _assert_human_gate_is_attachment(node: dict[str, Any]) -> None:
    executor = dict(node.get("executor") or {})
    metadata = dict(node.get("metadata") or {})
    node_type = str(node.get("node_type") or metadata.get("node_type") or "").strip()
    executor_type = str(executor.get("executor_type") or metadata.get("executor_type") or "").strip()
    if node_type in HUMAN_GATE_NODE_TYPES or executor_type in HUMAN_GATE_EXECUTOR_TYPES:
        node_id = str(node.get("node_id") or "").strip()
        raise ValueError(
            "Human gate must be modeled as NodeGateAttachment or edge control, "
            f"not as a GraphNode or work order: {node_id or '<unnamed-node>'}"
        )


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in list(value or []) if str(item))


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ({}, [], (), "", None)}
