from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TaskGraphKind = Literal["single_agent", "multi_agent", "coordination"]
TaskGraphPublishState = Literal["draft", "published", "archived"]
NODE_EXECUTION_MODES = {"sync", "async", "parallel", "background", "barrier", "manual_gate"}
NODE_WAIT_POLICIES = {
    "wait_all_upstream_completed",
    "wait_any_upstream_completed",
    "wait_required_contracts",
    "wait_handoff_ack",
    "fire_and_continue",
    "manual_release",
}
NODE_JOIN_POLICIES = {
    "all_success",
    "any_success",
    "quorum",
    "coordinator_decides",
    "allow_partial_with_issues",
    "fail_on_any_error",
}
EDGE_FAILURE_PROPAGATION_POLICIES = {"fail_downstream", "isolate_failure", "coordinator_decides", "allow_partial"}
EDGE_RESULT_DELIVERY_POLICIES = {"contract_payload_and_refs", "refs_only", "summary_and_refs", "notification_only"}


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
    projection_id: str = ""
    projection_overlay_id: str = ""
    failure_policy: dict[str, Any] = field(default_factory=dict)
    human_gate_policy: dict[str, Any] = field(default_factory=dict)
    memory_read_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    dynamic_memory_read_policy: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "sync"
    dispatch_group: str = ""
    wait_policy: str = "wait_all_upstream_completed"
    join_policy: str = "all_success"
    background_policy: dict[str, Any] = field(default_factory=dict)
    notification_policy: dict[str, Any] = field(default_factory=dict)
    resource_lifecycle_policy: dict[str, Any] = field(default_factory=dict)
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
    working_memory_handoff_policy: dict[str, Any] = field(default_factory=dict)
    ack_policy: str = "explicit_ack"
    timeout_policy: str = "fail_closed"
    wait_policy: str = ""
    ack_required: bool = True
    failure_propagation_policy: str = "fail_downstream"
    result_delivery_policy: str = "contract_payload_and_refs"
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
    working_memory_policy_profile_id: str = ""
    working_memory_policy: dict[str, Any] = field(default_factory=dict)
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
        projection_id=str(payload.get("projection_id") or payload.get("projection_overlay_id") or "").strip(),
        projection_overlay_id=str(payload.get("projection_overlay_id") or "").strip(),
        failure_policy=dict(payload.get("failure_policy") or {}),
        human_gate_policy=dict(payload.get("human_gate_policy") or {}),
        memory_read_policy=dict(payload.get("memory_read_policy") or {}),
        memory_writeback_policy=dict(payload.get("memory_writeback_policy") or {}),
        dynamic_memory_read_policy=dict(payload.get("dynamic_memory_read_policy") or {}),
        execution_mode=str(payload.get("execution_mode") or "sync").strip() or "sync",
        dispatch_group=str(payload.get("dispatch_group") or "").strip(),
        wait_policy=str(payload.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed",
        join_policy=str(payload.get("join_policy") or "all_success").strip() or "all_success",
        background_policy=dict(payload.get("background_policy") or {}),
        notification_policy=dict(payload.get("notification_policy") or {}),
        resource_lifecycle_policy=dict(payload.get("resource_lifecycle_policy") or {}),
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
        working_memory_handoff_policy=dict(payload.get("working_memory_handoff_policy") or {}),
        ack_policy=str(payload.get("ack_policy") or "explicit_ack").strip(),
        timeout_policy=str(payload.get("timeout_policy") or "fail_closed").strip(),
        wait_policy=str(payload.get("wait_policy") or "").strip(),
        ack_required=bool(payload.get("ack_required", True)),
        failure_propagation_policy=str(payload.get("failure_propagation_policy") or "fail_downstream").strip() or "fail_downstream",
        result_delivery_policy=str(payload.get("result_delivery_policy") or "contract_payload_and_refs").strip() or "contract_payload_and_refs",
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
    runtime_policy = dict(payload.get("runtime_policy") or {})
    working_memory_policy_profile_id = str(
        payload.get("working_memory_policy_profile_id")
        or runtime_policy.get("working_memory_profile_id")
        or ""
    ).strip()
    if working_memory_policy_profile_id and "working_memory_profile_id" not in runtime_policy:
        runtime_policy["working_memory_profile_id"] = working_memory_policy_profile_id
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
        working_memory_policy_profile_id=working_memory_policy_profile_id,
        working_memory_policy=dict(payload.get("working_memory_policy") or {}),
        runtime_policy=runtime_policy,
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
        if node.execution_mode not in NODE_EXECUTION_MODES:
            issues.append(TaskGraphValidationIssue(code="node_execution_mode_invalid", message="节点 execution_mode 不受支持", node_id=node.node_id))
        if node.wait_policy not in NODE_WAIT_POLICIES:
            issues.append(TaskGraphValidationIssue(code="node_wait_policy_invalid", message="节点 wait_policy 不受支持", node_id=node.node_id))
        if node.join_policy not in NODE_JOIN_POLICIES:
            issues.append(TaskGraphValidationIssue(code="node_join_policy_invalid", message="节点 join_policy 不受支持", node_id=node.node_id))
        if node.execution_mode == "background":
            if not bool(node.background_policy.get("enabled")):
                issues.append(TaskGraphValidationIssue(code="background_node_policy_disabled", message="后台节点必须显式启用 background_policy.enabled", node_id=node.node_id))
            if not _positive_int_policy(node.background_policy, "max_runtime_seconds"):
                issues.append(TaskGraphValidationIssue(code="background_node_timeout_missing", message="后台节点必须配置 max_runtime_seconds", node_id=node.node_id))
            if not node.notification_policy:
                issues.append(TaskGraphValidationIssue(code="background_node_notification_policy_missing", message="后台节点必须配置 notification_policy", node_id=node.node_id))
        if node.execution_mode == "parallel" and not node.dispatch_group:
            issues.append(TaskGraphValidationIssue(code="parallel_node_dispatch_group_missing", message="并行节点必须配置 dispatch_group", node_id=node.node_id))
        if node.execution_mode == "barrier":
            if node.wait_policy == "fire_and_continue":
                issues.append(TaskGraphValidationIssue(code="barrier_node_wait_policy_invalid", message="汇合节点不能使用 fire_and_continue 等待策略", node_id=node.node_id))
            incoming = [edge for edge in graph.edges if edge.target_node_id == node.node_id]
            if not incoming:
                issues.append(TaskGraphValidationIssue(code="barrier_node_missing_upstream", message="汇合节点必须存在上游边", node_id=node.node_id))
        if node.execution_mode == "manual_gate" and not node.human_gate_policy:
            issues.append(TaskGraphValidationIssue(code="manual_gate_policy_missing", message="人工门控节点必须配置 human_gate_policy", node_id=node.node_id))
        if node.memory_read_policy and not _listish_policy(node.memory_read_policy, ("readable_kinds", "readable_scopes")):
            issues.append(TaskGraphValidationIssue(code="node_memory_read_policy_shape", message="节点工作记忆读取策略缺少 readable_kinds 或 readable_scopes", severity="warning", node_id=node.node_id))
        if node.memory_writeback_policy and not _listish_policy(node.memory_writeback_policy, ("writable_kinds", "writable_scopes")):
            issues.append(TaskGraphValidationIssue(code="node_memory_write_policy_shape", message="节点工作记忆写入策略缺少 writable_kinds 或 writable_scopes", severity="warning", node_id=node.node_id))
        if node.dynamic_memory_read_policy:
            if bool(node.dynamic_memory_read_policy.get("allow_temporal_expansion")) and not _positive_int_policy(node.dynamic_memory_read_policy, "max_temporal_expansion_depth"):
                issues.append(TaskGraphValidationIssue(code="node_temporal_expansion_limit_missing", message="节点允许 temporal 扩展时需要配置 max_temporal_expansion_depth", severity="warning", node_id=node.node_id))
            if not _positive_int_policy(node.dynamic_memory_read_policy, "max_dynamic_reads_per_node_run"):
                issues.append(TaskGraphValidationIssue(code="node_dynamic_read_limit_missing", message="节点动态读取策略缺少 max_dynamic_reads_per_node_run", severity="warning", node_id=node.node_id))
    for edge in graph.edges:
        if not edge.edge_id:
            issues.append(TaskGraphValidationIssue(code="edge_missing_id", message="边缺少 edge_id"))
        if edge.source_node_id not in node_id_set:
            issues.append(TaskGraphValidationIssue(code="edge_missing_source", message="边的源节点不存在", edge_id=edge.edge_id, node_id=edge.source_node_id))
        if edge.target_node_id not in node_id_set:
            issues.append(TaskGraphValidationIssue(code="edge_missing_target", message="边的目标节点不存在", edge_id=edge.edge_id, node_id=edge.target_node_id))
        if edge.wait_policy and edge.wait_policy not in NODE_WAIT_POLICIES:
            issues.append(TaskGraphValidationIssue(code="edge_wait_policy_invalid", message="边 wait_policy 不受支持", edge_id=edge.edge_id))
        if edge.failure_propagation_policy not in EDGE_FAILURE_PROPAGATION_POLICIES:
            issues.append(TaskGraphValidationIssue(code="edge_failure_propagation_policy_invalid", message="边 failure_propagation_policy 不受支持", edge_id=edge.edge_id))
        if edge.result_delivery_policy not in EDGE_RESULT_DELIVERY_POLICIES:
            issues.append(TaskGraphValidationIssue(code="edge_result_delivery_policy_invalid", message="边 result_delivery_policy 不受支持", edge_id=edge.edge_id))
        if (edge.wait_policy == "wait_handoff_ack" or edge.ack_required) and not edge.ack_policy:
            issues.append(TaskGraphValidationIssue(code="edge_ack_policy_missing", message="要求 ack 的边必须配置 ack_policy", edge_id=edge.edge_id))
        if edge.working_memory_handoff_policy and not _listish_policy(edge.working_memory_handoff_policy, ("carry_kinds", "carry_scopes", "working_memory_refs")):
            issues.append(TaskGraphValidationIssue(code="edge_working_memory_handoff_policy_shape", message="边工作记忆交接策略缺少 carry_kinds、carry_scopes 或 working_memory_refs", severity="warning", edge_id=edge.edge_id))
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


def _listish_policy(policy: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = policy.get(key)
        if isinstance(value, (list, tuple)) and any(str(item).strip() for item in value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _positive_int_policy(policy: dict[str, Any], key: str) -> bool:
    try:
        return int(policy.get(key) or 0) > 0
    except (TypeError, ValueError):
        return False
