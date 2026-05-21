from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agent_system.identity import normalize_agent_id
from agent_system.models.model_profile_models import contains_raw_secret, sanitize_model_profile_payload


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
TASK_GRAPH_NODE_TYPES = {
    "agent",
    "agent_role",
    "coordinator",
    "subtask",
    "review_gate",
    "memory",
    "input",
    "output",
    "tool",
    "barrier",
    "manual_gate",
    "runtime_monitor",
    "memory_resource",
    "memory_read",
    "memory_write",
    "memory_handoff",
    "memory_commit",
    "memory_finalize",
    "memory_repository",
    "memory_collection",
    "artifact_repository",
    "thread_ledger",
    "progress_ledger",
    "issue_ledger",
    "runtime_state_store",
    "working_memory_store",
    "loop_frame",
    "graph_module",
}
MEMORY_RESOURCE_OPERATIONS = {"read", "write", "handoff", "commit", "finalize"}
CONTRACT_BINDING_SECTIONS = {
    "schema",
    "execution",
    "unit_batch",
    "artifact",
    "memory",
    "handoff",
    "acceptance",
    "runtime",
    "governance",
    "temporal",
}


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
    contract_bindings: dict[str, Any] = field(default_factory=dict)
    runtime_lane: str = ""
    context_visibility_policy: dict[str, Any] = field(default_factory=dict)
    projection_id: str = ""
    projection_overlay_id: str = ""
    executor_policy: dict[str, Any] = field(default_factory=dict)
    failure_policy: dict[str, Any] = field(default_factory=dict)
    human_gate_policy: dict[str, Any] = field(default_factory=dict)
    memory_read_policy: dict[str, Any] = field(default_factory=dict)
    memory_writeback_policy: dict[str, Any] = field(default_factory=dict)
    dynamic_memory_read_policy: dict[str, Any] = field(default_factory=dict)
    phase_id: str = ""
    sequence_index: int = 0
    timeline_group_id: str = ""
    main_chain: bool = True
    blocks_phase_exit: bool = True
    loop_policy: dict[str, Any] = field(default_factory=dict)
    loop_kind: str = ""
    loop_scope_id: str = ""
    title_template: str = ""
    loop_route_policy: dict[str, Any] = field(default_factory=dict)
    review_gate_policy: dict[str, Any] = field(default_factory=dict)
    artifact_context_policy: dict[str, Any] = field(default_factory=dict)
    revision_context_policy: dict[str, Any] = field(default_factory=dict)
    quality_retry_policy: dict[str, Any] = field(default_factory=dict)
    progress_commit_policy: dict[str, Any] = field(default_factory=dict)
    artifact_policy: dict[str, Any] = field(default_factory=dict)
    stream_policy: dict[str, Any] = field(default_factory=dict)
    artifact_target: str = ""
    output_path: str = ""
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
    contract_bindings: dict[str, Any] = field(default_factory=dict)
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
    contract_bindings: dict[str, Any] = field(default_factory=dict)
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
        payload["graph_nodes"] = payload["nodes"]
        payload["graph_edges"] = payload["edges"]
        payload["issues"] = [item.to_dict() for item in validate_task_graph(self)]
        payload["valid"] = self.valid
        payload["subtask_refs"] = _subtask_refs_from_graph_payload(self)
        return payload


def task_graph_node_from_dict(payload: dict[str, Any]) -> TaskGraphNodeDefinition:
    _reject_raw_contract_binding_secrets(
        payload.get("contract_bindings"),
        scope="TaskGraph node contract_bindings",
    )
    explicit_bindings = _contract_bindings_payload(payload.get("contract_bindings"))
    explicit_schema_bindings = dict(explicit_bindings.get("schema") or {})
    explicit_execution_bindings = dict(explicit_bindings.get("execution") or {})
    legacy_node_contract_id = str(payload.get("node_contract_id") or payload.get("contract_id") or "").strip()
    legacy_input_contract_id = str(payload.get("input_contract_id") or "").strip()
    legacy_output_contract_id = str(payload.get("output_contract_id") or "").strip()
    node_contract_id = str(explicit_execution_bindings.get("node_contract_id") or legacy_node_contract_id or "").strip()
    input_contract_id = str(explicit_schema_bindings.get("input_contract_id") or legacy_input_contract_id or "").strip()
    output_contract_id = str(explicit_schema_bindings.get("output_contract_id") or legacy_output_contract_id or "").strip()
    runtime_lane = str(payload.get("runtime_lane") or "").strip()
    executor_policy = dict(payload.get("executor_policy") or {})
    memory_read_policy = dict(payload.get("memory_read_policy") or {})
    memory_writeback_policy = dict(payload.get("memory_writeback_policy") or {})
    dynamic_memory_read_policy = dict(payload.get("dynamic_memory_read_policy") or {})
    artifact_policy = dict(payload.get("artifact_policy") or {})
    stream_policy = dict(payload.get("stream_policy") or {})
    review_gate_policy = dict(payload.get("review_gate_policy") or {})
    human_gate_policy = dict(payload.get("human_gate_policy") or {})
    failure_policy = dict(payload.get("failure_policy") or {})
    background_policy = dict(payload.get("background_policy") or {})
    notification_policy = dict(payload.get("notification_policy") or {})
    resource_lifecycle_policy = dict(payload.get("resource_lifecycle_policy") or {})
    loop_kind = str(payload.get("loop_kind") or "").strip()
    loop_scope_id = str(payload.get("loop_scope_id") or "").strip()
    title_template = str(payload.get("title_template") or "").strip()
    loop_route_policy = dict(payload.get("loop_route_policy") or {})
    artifact_context_policy = dict(payload.get("artifact_context_policy") or {})
    revision_context_policy = dict(payload.get("revision_context_policy") or {})
    quality_retry_policy = dict(payload.get("quality_retry_policy") or {})
    progress_commit_policy = dict(payload.get("progress_commit_policy") or {})
    execution_mode = str(payload.get("execution_mode") or "sync").strip() or "sync"
    wait_policy = str(payload.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed"
    join_policy = str(payload.get("join_policy") or "all_success").strip() or "all_success"
    metadata = _legacy_contract_metadata(
        dict(payload.get("metadata") or {}),
        {
            "node_contract_id": legacy_node_contract_id,
            "input_contract_id": legacy_input_contract_id,
            "output_contract_id": legacy_output_contract_id,
        },
    )
    return TaskGraphNodeDefinition(
        node_id=str(payload.get("node_id") or payload.get("id") or "").strip(),
        node_type=str(payload.get("node_type") or payload.get("type") or "agent").strip(),
        title=str(payload.get("title") or payload.get("label") or payload.get("node_id") or "未命名节点").strip(),
        task_id=str(payload.get("task_id") or "").strip(),
        agent_id=normalize_agent_id(str(payload.get("agent_id") or "").strip()),
        agent_selection_policy=str(payload.get("agent_selection_policy") or "explicit_agent").strip(),
        agent_group_id=str(payload.get("agent_group_id") or "").strip(),
        work_posture=str(payload.get("work_posture") or payload.get("role") or "").strip(),
        node_contract_id=node_contract_id,
        input_contract_id=input_contract_id,
        output_contract_id=output_contract_id,
        contract_bindings=normalize_node_contract_bindings(
            explicit=explicit_bindings,
            node_contract_id=node_contract_id,
            input_contract_id=input_contract_id,
            output_contract_id=output_contract_id,
            executor_policy=executor_policy,
            artifact_policy=artifact_policy,
            stream_policy=stream_policy,
            review_gate_policy=review_gate_policy,
            human_gate_policy=human_gate_policy,
            memory_read_policy=memory_read_policy,
            memory_writeback_policy=memory_writeback_policy,
            dynamic_memory_read_policy=dynamic_memory_read_policy,
            runtime_lane=runtime_lane,
            execution_mode=execution_mode,
            wait_policy=wait_policy,
            join_policy=join_policy,
            failure_policy=failure_policy,
            background_policy=background_policy,
            notification_policy=notification_policy,
            resource_lifecycle_policy=resource_lifecycle_policy,
            metadata=metadata,
        ),
        runtime_lane=runtime_lane,
        context_visibility_policy=dict(payload.get("context_visibility_policy") or {}),
        projection_id=str(payload.get("projection_id") or payload.get("projection_overlay_id") or "").strip(),
        projection_overlay_id=str(payload.get("projection_overlay_id") or "").strip(),
        executor_policy=executor_policy,
        failure_policy=failure_policy,
        human_gate_policy=human_gate_policy,
        memory_read_policy=memory_read_policy,
        memory_writeback_policy=memory_writeback_policy,
        dynamic_memory_read_policy=dynamic_memory_read_policy,
        phase_id=str(payload.get("phase_id") or "").strip(),
        sequence_index=_int_value(payload.get("sequence_index"), 0),
        timeline_group_id=str(payload.get("timeline_group_id") or "").strip(),
        main_chain=bool(payload.get("main_chain", True)),
        blocks_phase_exit=bool(payload.get("blocks_phase_exit", True)),
        loop_policy=dict(payload.get("loop_policy") or {}),
        loop_kind=loop_kind,
        loop_scope_id=loop_scope_id,
        title_template=title_template,
        loop_route_policy=loop_route_policy,
        review_gate_policy=review_gate_policy,
        artifact_context_policy=artifact_context_policy,
        revision_context_policy=revision_context_policy,
        quality_retry_policy=quality_retry_policy,
        progress_commit_policy=progress_commit_policy,
        artifact_policy=artifact_policy,
        stream_policy=stream_policy,
        artifact_target=str(payload.get("artifact_target") or "").strip(),
        output_path=str(payload.get("output_path") or "").strip(),
        execution_mode=execution_mode,
        dispatch_group=str(payload.get("dispatch_group") or "").strip(),
        wait_policy=wait_policy,
        join_policy=join_policy,
        background_policy=background_policy,
        notification_policy=notification_policy,
        resource_lifecycle_policy=resource_lifecycle_policy,
        metadata=metadata,
    )


def task_graph_edge_from_dict(payload: dict[str, Any]) -> TaskGraphEdgeDefinition:
    _reject_raw_contract_binding_secrets(
        payload.get("contract_bindings"),
        scope="TaskGraph edge contract_bindings",
    )
    explicit_bindings = _contract_bindings_payload(payload.get("contract_bindings"))
    explicit_schema_bindings = dict(explicit_bindings.get("schema") or {})
    legacy_payload_contract_id = str(payload.get("payload_contract_id") or payload.get("contract_id") or "").strip()
    payload_contract_id = str(explicit_schema_bindings.get("payload_contract_id") or legacy_payload_contract_id or "").strip()
    context_filter_policy = dict(payload.get("context_filter_policy") or {})
    artifact_ref_policy = dict(payload.get("artifact_ref_policy") or {})
    working_memory_handoff_policy = dict(payload.get("working_memory_handoff_policy") or {})
    ack_policy = str(payload.get("ack_policy") or "explicit_ack").strip()
    timeout_policy = str(payload.get("timeout_policy") or "fail_closed").strip()
    wait_policy = str(payload.get("wait_policy") or "").strip()
    failure_propagation_policy = str(payload.get("failure_propagation_policy") or "fail_downstream").strip() or "fail_downstream"
    result_delivery_policy = str(payload.get("result_delivery_policy") or "contract_payload_and_refs").strip() or "contract_payload_and_refs"
    failure_policy = dict(payload.get("failure_policy") or {})
    metadata = _legacy_contract_metadata(
        dict(payload.get("metadata") or {}),
        {
            "payload_contract_id": legacy_payload_contract_id,
        },
    )
    return TaskGraphEdgeDefinition(
        edge_id=str(payload.get("edge_id") or payload.get("id") or "").strip(),
        source_node_id=str(payload.get("source_node_id") or payload.get("from") or payload.get("source") or "").strip(),
        target_node_id=str(payload.get("target_node_id") or payload.get("to") or payload.get("target") or "").strip(),
        edge_type=str(payload.get("edge_type") or payload.get("mode") or payload.get("policy") or "handoff").strip(),
        a2a_message_type=str(payload.get("a2a_message_type") or "message/send").strip(),
        payload_contract_id=payload_contract_id,
        contract_bindings=normalize_edge_contract_bindings(
            explicit=explicit_bindings,
            payload_contract_id=payload_contract_id,
            context_filter_policy=context_filter_policy,
            artifact_ref_policy=artifact_ref_policy,
            working_memory_handoff_policy=working_memory_handoff_policy,
            ack_policy=ack_policy,
            timeout_policy=timeout_policy,
            wait_policy=wait_policy,
            ack_required=bool(payload.get("ack_required", True)),
            failure_propagation_policy=failure_propagation_policy,
            result_delivery_policy=result_delivery_policy,
            failure_policy=failure_policy,
            metadata=metadata,
        ),
        context_filter_policy=context_filter_policy,
        artifact_ref_policy=artifact_ref_policy,
        working_memory_handoff_policy=working_memory_handoff_policy,
        ack_policy=ack_policy,
        timeout_policy=timeout_policy,
        wait_policy=wait_policy,
        ack_required=bool(payload.get("ack_required", True)),
        failure_propagation_policy=failure_propagation_policy,
        result_delivery_policy=result_delivery_policy,
        failure_policy=failure_policy,
        metadata=metadata,
    )


def task_graph_from_dict(payload: dict[str, Any]) -> TaskGraphDefinition:
    _reject_raw_contract_binding_secrets(
        payload.get("contract_bindings"),
        scope="TaskGraph graph contract_bindings",
    )
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
    graph_id = str(payload.get("graph_id") or payload.get("task_graph_id") or "").strip()
    runtime_policy = dict(payload.get("runtime_policy") or {})
    working_memory_policy_profile_id = str(
        payload.get("working_memory_policy_profile_id")
        or runtime_policy.get("working_memory_profile_id")
        or ""
    ).strip()
    if working_memory_policy_profile_id and "working_memory_profile_id" not in runtime_policy:
        runtime_policy["working_memory_profile_id"] = working_memory_policy_profile_id
    explicit_bindings = _contract_bindings_payload(payload.get("contract_bindings"))
    explicit_schema_bindings = dict(explicit_bindings.get("schema") or {})
    legacy_graph_contract_id = str(payload.get("graph_contract_id") or "").strip()
    graph_contract_id = str(explicit_schema_bindings.get("graph_contract_id") or legacy_graph_contract_id or "").strip()
    working_memory_policy = dict(payload.get("working_memory_policy") or {})
    context_policy = dict(payload.get("context_policy") or {})
    metadata = _legacy_contract_metadata(
        dict(payload.get("metadata") or {}),
        {
            "graph_contract_id": legacy_graph_contract_id,
        },
    )
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
        graph_contract_id=graph_contract_id,
        contract_bindings=normalize_graph_contract_bindings(
            explicit=explicit_bindings,
            graph_contract_id=graph_contract_id,
            working_memory_policy=working_memory_policy,
            runtime_policy=runtime_policy,
            context_policy=context_policy,
            metadata=metadata,
        ),
        default_protocol_id=str(payload.get("default_protocol_id") or payload.get("protocol_id") or "").strip(),
        working_memory_policy_profile_id=working_memory_policy_profile_id,
        working_memory_policy=working_memory_policy,
        runtime_policy=runtime_policy,
        context_policy=context_policy,
        publish_state=_normalize_publish_state(payload.get("publish_state"), bool(payload.get("enabled", False))),
        enabled=bool(payload.get("enabled", False)),
        metadata=metadata,
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
        if node.node_type not in TASK_GRAPH_NODE_TYPES:
            issues.append(TaskGraphValidationIssue(code="node_type_invalid", message="节点 node_type 不受支持", node_id=node.node_id))
        if node.node_type == "agent" and not node.agent_id and not node.agent_group_id:
            issues.append(TaskGraphValidationIssue(code="agent_node_missing_agent_ref", message="Agent 节点缺少 agent_id 或 agent_group_id", node_id=node.node_id))
        if node.node_type == "runtime_monitor":
            if node.execution_mode != "background":
                issues.append(TaskGraphValidationIssue(code="monitor_node_execution_mode_invalid", message="监测节点必须使用 background execution_mode", node_id=node.node_id))
            monitor_policy = dict(node.metadata.get("monitor_policy") or {})
            if not monitor_policy:
                issues.append(TaskGraphValidationIssue(code="monitor_node_policy_missing", message="监测节点缺少 metadata.monitor_policy", severity="warning", node_id=node.node_id))
        if node.node_type in {"memory_resource", "memory_read", "memory_write", "memory_handoff", "memory_commit", "memory_finalize"}:
            operation = str(node.metadata.get("operation") or node.node_type.replace("memory_", "")).strip()
            if operation not in MEMORY_RESOURCE_OPERATIONS:
                issues.append(TaskGraphValidationIssue(code="memory_resource_operation_invalid", message="工作记忆资源节点 operation 不受支持", node_id=node.node_id))
            if operation == "read" and not node.memory_read_policy:
                issues.append(TaskGraphValidationIssue(code="memory_resource_read_policy_missing", message="工作记忆读取资源节点缺少 memory_read_policy", severity="warning", node_id=node.node_id))
            if operation == "write" and not node.memory_writeback_policy:
                issues.append(TaskGraphValidationIssue(code="memory_resource_write_policy_missing", message="工作记忆写入资源节点缺少 memory_writeback_policy", severity="warning", node_id=node.node_id))
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
        issues.extend(_contract_binding_conflict_issues_for_node(node))
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
        issues.extend(_contract_binding_conflict_issues_for_edge(edge))
    issues.extend(_contract_binding_conflict_issues_for_graph(graph))
    return tuple(issues)


def normalize_graph_contract_bindings(
    *,
    explicit: Any,
    graph_contract_id: str = "",
    working_memory_policy: dict[str, Any] | None = None,
    runtime_policy: dict[str, Any] | None = None,
    context_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_contract_id = str(graph_contract_id or "").strip()
    derived: dict[str, Any] = {}
    if graph_contract_id:
        derived.setdefault("schema", {})["graph_contract_id"] = graph_contract_id
    if working_memory_policy:
        derived.setdefault("memory", {})["working_memory_policy"] = dict(working_memory_policy)
    if runtime_policy:
        derived.setdefault("runtime", {})["runtime_policy"] = dict(runtime_policy)
    if context_policy:
        derived.setdefault("handoff", {})["context_policy"] = dict(context_policy)
    metadata = dict(metadata or {})
    for section in ("unit_batch", "governance", "acceptance"):
        value = metadata.get(f"{section}_contract") or metadata.get(f"{section}_policy")
        if isinstance(value, dict):
            derived.setdefault(section, {}).update(dict(value))
    length_budget = metadata.get("length_budget_contract") or metadata.get("length_budget_policy")
    if isinstance(length_budget, dict):
        derived.setdefault("runtime", {})["length_budget"] = _normalize_length_budget_payload(length_budget)
    return _merge_contract_bindings(derived, explicit)


def normalize_node_contract_bindings(
    *,
    explicit: Any,
    node_contract_id: str = "",
    input_contract_id: str = "",
    output_contract_id: str = "",
    executor_policy: dict[str, Any] | None = None,
    artifact_policy: dict[str, Any] | None = None,
    stream_policy: dict[str, Any] | None = None,
    review_gate_policy: dict[str, Any] | None = None,
    human_gate_policy: dict[str, Any] | None = None,
    memory_read_policy: dict[str, Any] | None = None,
    memory_writeback_policy: dict[str, Any] | None = None,
    dynamic_memory_read_policy: dict[str, Any] | None = None,
    runtime_lane: str = "",
    execution_mode: str = "",
    wait_policy: str = "",
    join_policy: str = "",
    failure_policy: dict[str, Any] | None = None,
    background_policy: dict[str, Any] | None = None,
    notification_policy: dict[str, Any] | None = None,
    resource_lifecycle_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if contains_raw_secret(explicit):
        raise ValueError("TaskGraph node contract_bindings must not contain raw model secrets; use runtime.model_requirement and AgentRuntimeProfile.model_profile.credential_ref")
    derived: dict[str, Any] = {}
    if input_contract_id:
        derived.setdefault("schema", {})["input_contract_id"] = str(input_contract_id).strip()
    if output_contract_id:
        derived.setdefault("schema", {})["output_contract_id"] = str(output_contract_id).strip()
    if node_contract_id:
        derived.setdefault("execution", {})["node_contract_id"] = str(node_contract_id).strip()
    if executor_policy:
        derived.setdefault("execution", {})["executor_policy"] = dict(executor_policy)
    if artifact_policy:
        derived.setdefault("artifact", {})["artifact_policy"] = dict(artifact_policy)
    if stream_policy:
        derived.setdefault("artifact", {})["stream_policy"] = dict(stream_policy)
    if review_gate_policy:
        derived.setdefault("acceptance", {})["review_gate_policy"] = dict(review_gate_policy)
    if human_gate_policy:
        derived.setdefault("acceptance", {})["human_gate_policy"] = dict(human_gate_policy)
    memory: dict[str, Any] = {}
    if memory_read_policy:
        memory["memory_read_policy"] = dict(memory_read_policy)
    if dynamic_memory_read_policy:
        memory["dynamic_memory_read_policy"] = dict(dynamic_memory_read_policy)
    if memory_writeback_policy:
        memory["memory_writeback_policy"] = dict(memory_writeback_policy)
    if memory:
        derived["memory"] = memory
    runtime: dict[str, Any] = {}
    for key, value in (
        ("runtime_lane", runtime_lane),
        ("execution_mode", execution_mode),
        ("wait_policy", wait_policy),
        ("join_policy", join_policy),
    ):
        if str(value or "").strip():
            runtime[key] = str(value or "").strip()
    if failure_policy:
        runtime["failure_policy"] = dict(failure_policy)
    if background_policy:
        runtime["background_policy"] = dict(background_policy)
    if notification_policy:
        runtime["notification_policy"] = dict(notification_policy)
    if resource_lifecycle_policy:
        runtime["resource_lifecycle_policy"] = dict(resource_lifecycle_policy)
    explicit_payload = _contract_bindings_payload(explicit)
    explicit_runtime = explicit_payload.get("runtime")
    if isinstance(explicit_runtime, dict) and isinstance(explicit_runtime.get("model_requirement"), dict):
        runtime["model_requirement"] = _normalize_model_requirement_payload(explicit_runtime.get("model_requirement"))
    if isinstance(explicit_runtime, dict) and isinstance(explicit_runtime.get("length_budget"), dict):
        runtime["length_budget"] = _normalize_length_budget_payload(explicit_runtime.get("length_budget"))
    if runtime:
        derived["runtime"] = runtime
    metadata = dict(metadata or {})
    for section in ("unit_batch", "governance"):
        value = metadata.get(f"{section}_contract") or metadata.get(f"{section}_policy")
        if isinstance(value, dict):
            derived.setdefault(section, {}).update(dict(value))
    length_budget = metadata.get("length_budget_contract") or metadata.get("length_budget_policy")
    if isinstance(length_budget, dict):
        derived.setdefault("runtime", {})["length_budget"] = _normalize_length_budget_payload(length_budget)
    return _merge_contract_bindings(derived, explicit)


def normalize_edge_contract_bindings(
    *,
    explicit: Any,
    payload_contract_id: str = "",
    context_filter_policy: dict[str, Any] | None = None,
    artifact_ref_policy: dict[str, Any] | None = None,
    working_memory_handoff_policy: dict[str, Any] | None = None,
    ack_policy: str = "",
    timeout_policy: str = "",
    wait_policy: str = "",
    ack_required: bool = True,
    failure_propagation_policy: str = "",
    result_delivery_policy: str = "",
    failure_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    derived: dict[str, Any] = {}
    if payload_contract_id:
        derived.setdefault("schema", {})["payload_contract_id"] = str(payload_contract_id).strip()
    handoff: dict[str, Any] = {
        "ack_required": bool(ack_required),
    }
    for key, value in (
        ("ack_policy", ack_policy),
        ("timeout_policy", timeout_policy),
        ("wait_policy", wait_policy),
        ("failure_propagation_policy", failure_propagation_policy),
        ("result_delivery_policy", result_delivery_policy),
    ):
        if str(value or "").strip():
            handoff[key] = str(value or "").strip()
    if context_filter_policy:
        handoff["context_filter_policy"] = dict(context_filter_policy)
    if failure_policy:
        handoff["failure_policy"] = dict(failure_policy)
    if handoff:
        derived["handoff"] = handoff
    if artifact_ref_policy:
        derived.setdefault("artifact", {})["artifact_ref_policy"] = dict(artifact_ref_policy)
    if working_memory_handoff_policy:
        derived.setdefault("memory", {})["working_memory_handoff_policy"] = dict(working_memory_handoff_policy)
    metadata = dict(metadata or {})
    temporal = dict(metadata.get("temporal_semantics") or {})
    for key in ("trigger_timing", "visibility_timing", "acknowledgement_timing", "propagation_timing", "phase_timing"):
        if str(metadata.get(key) or "").strip() and key not in temporal:
            temporal[key] = str(metadata.get(key) or "").strip()
    if temporal:
        derived["temporal"] = temporal
    return _merge_contract_bindings(derived, explicit)


def _merge_contract_bindings(derived: dict[str, Any], explicit: Any) -> dict[str, Any]:
    if contains_raw_secret(explicit):
        raise ValueError("contract_bindings must use credential_ref and must not contain raw model secrets")
    explicit_payload = _contract_bindings_payload(explicit)
    merged: dict[str, Any] = {
        key: dict(value)
        for key, value in derived.items()
        if isinstance(value, dict) and (key in CONTRACT_BINDING_SECTIONS or key)
    }
    for key, value in explicit_payload.items():
        if isinstance(value, dict):
            merged[key] = {**dict(merged.get(key) or {}), **dict(value)}
        else:
            merged[key] = value
    return _prune_empty_contract_bindings(merged)


def _reject_raw_contract_binding_secrets(value: Any, *, scope: str) -> None:
    if contains_raw_secret(value):
        raise ValueError(f"{scope} must use credential_ref and must not contain raw model secrets")


def _contract_bindings_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = {str(key).strip(): value for key, value in value.items() if str(key).strip()}
    runtime = payload.get("runtime")
    runtime_payload = dict(runtime) if isinstance(runtime, dict) else {}
    if isinstance(runtime, dict) and isinstance(runtime.get("model_requirement"), dict):
        runtime_payload["model_requirement"] = _normalize_model_requirement_payload(runtime.get("model_requirement"))
    if isinstance(runtime, dict) and isinstance(runtime.get("length_budget"), dict):
        runtime_payload["length_budget"] = _normalize_length_budget_payload(runtime.get("length_budget"))
    if runtime_payload:
        payload["runtime"] = runtime_payload
    return payload


def _normalize_model_requirement_payload(value: Any) -> dict[str, Any]:
    payload = sanitize_model_profile_payload(value)
    allowed = {
        "profile_ref",
        "provider_family",
        "model_family",
        "capability_tags",
        "min_context_tokens",
        "min_output_tokens",
        "preferred_output_tokens",
        "thinking_mode",
        "reasoning_required",
        "streaming_required",
        "temperature_profile",
        "fallback_allowed",
        "metadata",
    }
    return {key: item for key, item in payload.items() if key in allowed}


def _normalize_length_budget_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(item, dict):
            payload[normalized_key] = _normalize_length_budget_payload(item)
        elif isinstance(item, list):
            payload[normalized_key] = [
                _normalize_length_budget_payload(child) if isinstance(child, dict) else child
                for child in item
            ]
        else:
            payload[normalized_key] = item
    return payload


def _legacy_contract_metadata(metadata: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    legacy_values = {
        key: str(value or "").strip()
        for key, value in values.items()
        if str(value or "").strip()
    }
    if not legacy_values:
        return metadata
    legacy_contract_fields = dict(metadata.get("legacy_contract_fields") or {})
    legacy_contract_fields.update(legacy_values)
    metadata["legacy_contract_fields"] = legacy_contract_fields
    return metadata


def _legacy_contract_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    return dict((metadata or {}).get("legacy_contract_fields") or {})


def _prune_empty_contract_bindings(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, section in value.items():
        if isinstance(section, dict):
            pruned = {
                str(item_key): item_value
                for item_key, item_value in section.items()
                if item_value not in ("", None, [], {})
            }
            if pruned:
                result[key] = pruned
        elif section not in ("", None, [], {}):
            result[key] = section
    return result


def _binding_value(bindings: dict[str, Any], section: str, key: str) -> Any:
    payload = dict(bindings.get(section) or {})
    return payload.get(key)


def _contract_binding_conflict_issues_for_graph(graph: TaskGraphDefinition) -> list[TaskGraphValidationIssue]:
    issues: list[TaskGraphValidationIssue] = []
    legacy_fields = _legacy_contract_fields(graph.metadata)
    _append_binding_conflict_issue(
        issues,
        scope="graph",
        legacy_field="graph_contract_id",
        legacy_value=legacy_fields.get("graph_contract_id", graph.graph_contract_id),
        binding_path="schema.graph_contract_id",
        binding_value=_binding_value(graph.contract_bindings, "schema", "graph_contract_id"),
    )
    return issues


def _contract_binding_conflict_issues_for_node(node: TaskGraphNodeDefinition) -> list[TaskGraphValidationIssue]:
    issues: list[TaskGraphValidationIssue] = []
    legacy_fields = _legacy_contract_fields(node.metadata)
    for legacy_field, section, key, legacy_value in (
        ("node_contract_id", "execution", "node_contract_id", legacy_fields.get("node_contract_id", node.node_contract_id)),
        ("input_contract_id", "schema", "input_contract_id", legacy_fields.get("input_contract_id", node.input_contract_id)),
        ("output_contract_id", "schema", "output_contract_id", legacy_fields.get("output_contract_id", node.output_contract_id)),
    ):
        _append_binding_conflict_issue(
            issues,
            scope="node",
            legacy_field=legacy_field,
            legacy_value=legacy_value,
            binding_path=f"{section}.{key}",
            binding_value=_binding_value(node.contract_bindings, section, key),
            node_id=node.node_id,
        )
    return issues


def _contract_binding_conflict_issues_for_edge(edge: TaskGraphEdgeDefinition) -> list[TaskGraphValidationIssue]:
    issues: list[TaskGraphValidationIssue] = []
    legacy_fields = _legacy_contract_fields(edge.metadata)
    _append_binding_conflict_issue(
        issues,
        scope="edge",
        legacy_field="payload_contract_id",
        legacy_value=legacy_fields.get("payload_contract_id", edge.payload_contract_id),
        binding_path="schema.payload_contract_id",
        binding_value=_binding_value(edge.contract_bindings, "schema", "payload_contract_id"),
        edge_id=edge.edge_id,
    )
    return issues


def _append_binding_conflict_issue(
    issues: list[TaskGraphValidationIssue],
    *,
    scope: str,
    legacy_field: str,
    legacy_value: Any,
    binding_path: str,
    binding_value: Any,
    node_id: str = "",
    edge_id: str = "",
) -> None:
    legacy = str(legacy_value or "").strip()
    binding = str(binding_value or "").strip()
    if not legacy or not binding or legacy == binding:
        return
    issues.append(
        TaskGraphValidationIssue(
            code="contract_binding_conflict",
            message=f"{scope} 的历史字段 {legacy_field} 与 contract_bindings.{binding_path} 冲突：{legacy} != {binding}",
            severity="error",
            node_id=node_id,
            edge_id=edge_id,
        )
    )


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


def _int_value(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _subtask_refs_from_graph_payload(graph: TaskGraphDefinition) -> list[str]:
    metadata = dict(graph.metadata or {})
    refs = [
        *[str(value).strip() for value in list(metadata.get("subtask_refs") or []) if str(value).strip()],
        *[
            str(node.task_id or "").strip()
            for node in graph.nodes
            if str(node.node_type or "").strip() != "graph_module" and str(node.task_id or "").strip()
        ],
    ]
    return list(dict.fromkeys(value for value in refs if value.startswith("task.")))
