from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskGraphKind = Literal["single_agent", "multi_agent", "coordination"]
TaskGraphPublishState = Literal["draft", "published", "archived"]


@dataclass(frozen=True, slots=True)
class TaskGraphNodeDefinition:
    node_id: str
    node_type: str
    title: str
    task_id: str = ""
    agent_id: str = ""
    agent_selection_policy: str = "explicit_agent"
    agent_group_id: str = ""
    work_posture: str = ""
    node_contract_id: str = ""
    input_contract_id: str = ""
    output_contract_id: str = ""
    runtime_lane: str = ""
    context_visibility_policy: dict[str, Any] = field(default_factory=dict)
    projection_overlay_id: str = ""
    failure_policy: dict[str, Any] = field(default_factory=dict)
    human_gate_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphEdgeDefinition:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str = "handoff"
    a2a_message_type: str = "message/send"
    payload_contract_id: str = ""
    context_filter_policy: dict[str, Any] = field(default_factory=dict)
    artifact_ref_policy: dict[str, Any] = field(default_factory=dict)
    ack_policy: str = "explicit_ack"
    timeout_policy: str = "fail_closed"
    failure_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphValidationIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: str = ""
    edge_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphDefinition:
    graph_id: str
    title: str
    domain_id: str = ""
    task_family: str = ""
    graph_kind: TaskGraphKind = "single_agent"
    entry_node_id: str = ""
    output_node_id: str = ""
    nodes: tuple[TaskGraphNodeDefinition, ...] = ()
    edges: tuple[TaskGraphEdgeDefinition, ...] = ()
    graph_contract_id: str = ""
    default_protocol_id: str = ""
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    publish_state: TaskGraphPublishState = "draft"
    enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "task_system.task_graph_definition"

    def __post_init__(self) -> None:
        if self.authority != "task_system.task_graph_definition":
            raise ValueError("TaskGraphDefinition authority must be task_system.task_graph_definition")
        if not self.graph_id:
            raise ValueError("TaskGraphDefinition requires graph_id")
        if self.graph_kind not in {"single_agent", "multi_agent", "coordination"}:
            raise ValueError("unsupported graph_kind")
        if self.publish_state not in {"draft", "published", "archived"}:
            raise ValueError("unsupported publish_state")

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in validate_task_graph(self))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [item.to_dict() for item in self.nodes]
        payload["edges"] = [item.to_dict() for item in self.edges]
        payload["issues"] = [item.to_dict() for item in validate_task_graph(self)]
        payload["valid"] = self.valid
        return payload


def task_graph_node_from_dict(payload: dict[str, Any]) -> TaskGraphNodeDefinition:
    return TaskGraphNodeDefinition(
        node_id=str(payload.get("node_id") or payload.get("id") or "").strip(),
        node_type=str(payload.get("node_type") or payload.get("type") or "agent").strip(),
        title=str(payload.get("title") or payload.get("label") or payload.get("node_id") or "未命名节点").strip(),
        task_id=str(payload.get("task_id") or "").strip(),
        agent_id=str(payload.get("agent_id") or "").strip(),
        agent_selection_policy=str(payload.get("agent_selection_policy") or "explicit_agent").strip(),
        agent_group_id=str(payload.get("agent_group_id") or "").strip(),
        work_posture=str(payload.get("work_posture") or payload.get("role") or "").strip(),
        node_contract_id=str(payload.get("node_contract_id") or "").strip(),
        input_contract_id=str(payload.get("input_contract_id") or "").strip(),
        output_contract_id=str(payload.get("output_contract_id") or "").strip(),
        runtime_lane=str(payload.get("runtime_lane") or "").strip(),
        context_visibility_policy=dict(payload.get("context_visibility_policy") or {}),
        projection_overlay_id=str(payload.get("projection_overlay_id") or "").strip(),
        failure_policy=dict(payload.get("failure_policy") or {}),
        human_gate_policy=dict(payload.get("human_gate_policy") or {}),
        memory_writeback_policy=dict(payload.get("memory_writeback_policy") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def task_graph_edge_from_dict(payload: dict[str, Any]) -> TaskGraphEdgeDefinition:
    return TaskGraphEdgeDefinition(
        edge_id=str(payload.get("edge_id") or payload.get("id") or "").strip(),
        source_node_id=str(payload.get("source_node_id") or payload.get("from") or payload.get("source") or "").strip(),
        target_node_id=str(payload.get("target_node_id") or payload.get("to") or payload.get("target") or "").strip(),
        edge_type=str(payload.get("edge_type") or payload.get("mode") or payload.get("policy") or "handoff").strip(),
        a2a_message_type=str(payload.get("a2a_message_type") or "message/send").strip(),
        payload_contract_id=str(payload.get("payload_contract_id") or "").strip(),
        context_filter_policy=dict(payload.get("context_filter_policy") or {}),
        artifact_ref_policy=dict(payload.get("artifact_ref_policy") or {}),
        ack_policy=str(payload.get("ack_policy") or "explicit_ack").strip(),
        timeout_policy=str(payload.get("timeout_policy") or "fail_closed").strip(),
        failure_policy=dict(payload.get("failure_policy") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def task_graph_from_dict(payload: dict[str, Any]) -> TaskGraphDefinition:
    nodes = tuple(
        task_graph_node_from_dict(item)
        for item in list(payload.get("nodes") or payload.get("graph_nodes") or [])
        if isinstance(item, dict)
    )
    edges = tuple(
        task_graph_edge_from_dict(item)
        for item in list(payload.get("edges") or payload.get("graph_edges") or [])
        if isinstance(item, dict)
    )
    graph_id = str(payload.get("graph_id") or payload.get("coordination_task_id") or "").strip()
    return TaskGraphDefinition(
        graph_id=graph_id,
        title=str(payload.get("title") or graph_id or "未命名任务图").strip(),
        domain_id=str(payload.get("domain_id") or "").strip(),
        task_family=str(payload.get("task_family") or "").strip(),
        graph_kind=_normalize_graph_kind(payload.get("graph_kind") or payload.get("coordination_mode"), nodes),
        entry_node_id=str(payload.get("entry_node_id") or _first_start_node(nodes, edges) or "").strip(),
        output_node_id=str(payload.get("output_node_id") or _first_terminal_node(nodes, edges) or "").strip(),
        nodes=nodes,
        edges=edges,
        graph_contract_id=str(payload.get("graph_contract_id") or "").strip(),
        default_protocol_id=str(payload.get("default_protocol_id") or payload.get("protocol_id") or "").strip(),
        runtime_policy=dict(payload.get("runtime_policy") or {}),
        context_policy=dict(payload.get("context_policy") or {}),
        publish_state=_normalize_publish_state(payload.get("publish_state"), bool(payload.get("enabled", False))),
        enabled=bool(payload.get("enabled", False)),
        metadata=dict(payload.get("metadata") or {}),
    )


def validate_task_graph(graph: TaskGraphDefinition) -> tuple[TaskGraphValidationIssue, ...]:
    issues: list[TaskGraphValidationIssue] = []
    node_ids = [node.node_id for node in graph.nodes if node.node_id]
    node_id_set = set(node_ids)
    if not graph.nodes:
        issues.append(TaskGraphValidationIssue(code="empty_graph", message="任务图没有节点"))
    if len(node_ids) != len(node_id_set):
        issues.append(TaskGraphValidationIssue(code="duplicate_node_id", message="任务图存在重复节点 ID"))
    if graph.entry_node_id and graph.entry_node_id not in node_id_set:
        issues.append(TaskGraphValidationIssue(code="missing_entry_node", message="入口节点不存在", node_id=graph.entry_node_id))
    if graph.output_node_id and graph.output_node_id not in node_id_set:
        issues.append(TaskGraphValidationIssue(code="missing_output_node", message="输出节点不存在", node_id=graph.output_node_id))
    for node in graph.nodes:
        if not node.node_id:
            issues.append(TaskGraphValidationIssue(code="node_missing_id", message="节点缺少 node_id"))
        if node.node_type == "agent" and not node.agent_id and not node.agent_group_id:
            issues.append(TaskGraphValidationIssue(code="agent_node_missing_agent_ref", message="Agent 节点缺少 agent_id 或 agent_group_id", node_id=node.node_id))
    for edge in graph.edges:
        if not edge.edge_id:
            issues.append(TaskGraphValidationIssue(code="edge_missing_id", message="边缺少 edge_id"))
        if edge.source_node_id not in node_id_set:
            issues.append(TaskGraphValidationIssue(code="edge_missing_source", message="边的源节点不存在", edge_id=edge.edge_id, node_id=edge.source_node_id))
        if edge.target_node_id not in node_id_set:
            issues.append(TaskGraphValidationIssue(code="edge_missing_target", message="边的目标节点不存在", edge_id=edge.edge_id, node_id=edge.target_node_id))
    return tuple(issues)


def _normalize_graph_kind(value: Any, nodes: tuple[TaskGraphNodeDefinition, ...]) -> TaskGraphKind:
    raw = str(value or "").strip()
    if raw in {"single_agent", "multi_agent", "coordination"}:
        return raw  # type: ignore[return-value]
    if raw:
        return "coordination"
    agent_nodes = [node for node in nodes if node.node_type == "agent"]
    return "single_agent" if len(agent_nodes) <= 1 else "multi_agent"


def _normalize_publish_state(value: Any, enabled: bool) -> TaskGraphPublishState:
    raw = str(value or "").strip()
    if raw in {"draft", "published", "archived"}:
        return raw  # type: ignore[return-value]
    return "published" if enabled else "draft"


def _first_start_node(nodes: tuple[TaskGraphNodeDefinition, ...], edges: tuple[TaskGraphEdgeDefinition, ...]) -> str:
    targets = {edge.target_node_id for edge in edges}
    explicit = next((node.node_id for node in nodes if node.node_type == "input"), "")
    return explicit or next((node.node_id for node in nodes if node.node_id not in targets), "")


def _first_terminal_node(nodes: tuple[TaskGraphNodeDefinition, ...], edges: tuple[TaskGraphEdgeDefinition, ...]) -> str:
    sources = {edge.source_node_id for edge in edges}
    explicit = next((node.node_id for node in nodes if node.node_type == "output"), "")
    return explicit or next((node.node_id for node in nodes if node.node_id not in sources), "")
