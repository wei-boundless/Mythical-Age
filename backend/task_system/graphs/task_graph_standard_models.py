from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.graphs.composable_graph_builder import build_composable_graph_view
from task_system.graphs.composable_graph_models import ComposableUnit, GraphModuleRuntimePlan, UnitInterface, UnitPortEdge
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.runtime_semantics.length_budget import compiled_length_budget_preview, compile_length_budget
from task_system.registry.flow_models import SpecificTaskRecord, TaskCommunicationProtocol
from task_system.graphs.task_graph_models import TaskGraphDefinition, task_graph_from_dict


@dataclass(frozen=True, slots=True)
class TaskGraphStandardNodeSpec:
    node_id: str
    title: str
    node_type: str
    task_id: str = ""
    phase_id: str = ""
    sequence_index: int = 0
    timeline_group_id: str = ""
    main_chain: bool = True
    blocks_phase_exit: bool = True
    executor: dict[str, Any] = field(default_factory=dict)
    contracts: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    loop: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphStandardEdgeSpec:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    payload_contract_id: str = ""
    contract_bindings: dict[str, Any] = field(default_factory=dict)
    handoff: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    artifact_context: dict[str, Any] = field(default_factory=dict)
    revision: dict[str, Any] = field(default_factory=dict)
    temporal: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphStandardResourceSpec:
    node_id: str
    title: str
    resource_type: str
    repository_id: str = ""
    collections: tuple[str, ...] = ()
    collection_specs: tuple[dict[str, Any], ...] = ()
    lifecycle: dict[str, Any] = field(default_factory=dict)
    readable_by: tuple[str, ...] = ()
    write_owner_node_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["collections"] = list(self.collections)
        payload["collection_specs"] = [dict(item) for item in self.collection_specs]
        payload["readable_by"] = list(self.readable_by)
        payload["write_owner_node_ids"] = list(self.write_owner_node_ids)
        return payload


@dataclass(frozen=True, slots=True)
class TaskGraphStandardTimelineSpec:
    entry_node_id: str
    output_node_id: str
    temporal_edges: tuple[dict[str, Any], ...] = ()
    loop_frames: tuple[dict[str, Any], ...] = ()
    timeline_blocks: tuple[dict[str, Any], ...] = ()
    phases: tuple[dict[str, Any], ...] = ()
    scheduler: dict[str, Any] = field(default_factory=dict)
    runtime_semantics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_node_id": self.entry_node_id,
            "output_node_id": self.output_node_id,
            "temporal_edges": [dict(item) for item in self.temporal_edges],
            "loop_frames": [dict(item) for item in self.loop_frames],
            "timeline_blocks": [dict(item) for item in self.timeline_blocks],
            "phases": [dict(item) for item in self.phases],
            "scheduler": dict(self.scheduler),
            "runtime_semantics": dict(self.runtime_semantics),
        }


@dataclass(frozen=True, slots=True)
class TaskGraphRuntimeIsolationSpec:
    task_run_scope_policy: str = "isolated_per_task_run"
    memory_repositories: tuple[dict[str, Any], ...] = ()
    artifact_repositories: tuple[dict[str, Any], ...] = ()
    runtime_state_stores: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run_scope_policy": self.task_run_scope_policy,
            "memory_repositories": [dict(item) for item in self.memory_repositories],
            "artifact_repositories": [dict(item) for item in self.artifact_repositories],
            "runtime_state_stores": [dict(item) for item in self.runtime_state_stores],
        }


@dataclass(frozen=True, slots=True)
class TaskGraphStandardIssue:
    code: str
    message: str
    severity: str = "error"
    node_id: str = ""
    edge_id: str = ""
    unit_id: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskGraphModuleExpansionSpec:
    plan_id: str
    runtime_node_id: str
    unit_id: str
    linked_graph_id: str
    scope_prefix: str
    imported_graph: dict[str, Any] = field(default_factory=dict)
    entry_node_id: str = ""
    output_node_id: str = ""
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    resources: tuple[dict[str, Any], ...] = ()
    issues: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "runtime_node_id": self.runtime_node_id,
            "unit_id": self.unit_id,
            "linked_graph_id": self.linked_graph_id,
            "scope_prefix": self.scope_prefix,
            "imported_graph": dict(self.imported_graph),
            "entry_node_id": self.entry_node_id,
            "output_node_id": self.output_node_id,
            "nodes": [dict(item) for item in self.nodes],
            "edges": [dict(item) for item in self.edges],
            "resources": [dict(item) for item in self.resources],
            "issues": [dict(item) for item in self.issues],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TaskGraphStandardView:
    authority: str
    graph: dict[str, Any]
    nodes: tuple[TaskGraphStandardNodeSpec, ...]
    edges: tuple[TaskGraphStandardEdgeSpec, ...]
    resources: tuple[TaskGraphStandardResourceSpec, ...]
    units: tuple[ComposableUnit, ...]
    interfaces: tuple[UnitInterface, ...]
    port_edges: tuple[UnitPortEdge, ...]
    graph_module_runtime: tuple[GraphModuleRuntimePlan, ...]
    graph_module_expansions: tuple[TaskGraphModuleExpansionSpec, ...]
    timeline: TaskGraphStandardTimelineSpec
    runtime_isolation: TaskGraphRuntimeIsolationSpec
    memory_matrix: dict[str, Any]
    memory_protocol: dict[str, Any]
    diagnostics: dict[str, Any]
    issues: tuple[TaskGraphStandardIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "graph": dict(self.graph),
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "resources": [item.to_dict() for item in self.resources],
            "units": [item.to_dict() for item in self.units],
            "interfaces": [item.to_dict() for item in self.interfaces],
            "port_edges": [item.to_dict() for item in self.port_edges],
            "graph_module_runtime": [item.to_dict() for item in self.graph_module_runtime],
            "graph_module_expansions": [item.to_dict() for item in self.graph_module_expansions],
            "timeline": self.timeline.to_dict(),
            "runtime_isolation": self.runtime_isolation.to_dict(),
            "memory_matrix": dict(self.memory_matrix),
            "memory_protocol": dict(self.memory_protocol),
            "diagnostics": dict(self.diagnostics),
            "issues": [item.to_dict() for item in self.issues],
        }


def build_task_graph_standard_view(
    *,
    graph: TaskGraphDefinition,
    specific_tasks: tuple[SpecificTaskRecord, ...] = (),
    communication_protocol: TaskCommunicationProtocol | None = None,
    graph_lookup: Any | None = None,
) -> TaskGraphStandardView:
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
        communication_protocol=communication_protocol,
    )
    length_budget = compile_length_budget(
        explicit=dict(dict(graph.contract_bindings or {}).get("runtime") or {}).get("length_budget"),
        inherited=dict(dict(graph.metadata or {}).get("length_budget") or {}),
        source_chain=("graph.contract_bindings.runtime.length_budget", "graph.metadata.length_budget"),
        source_ref=graph.graph_id,
    )
    layered = dict(runtime_spec.diagnostics.get("layered_graph") or {})
    composable = build_composable_graph_view(graph=graph, layered_graph=layered)
    graph_module_expansions = _graph_module_expansions(
        current_graph=graph,
        graph_module_runtime=tuple(composable.graph_module_runtime),
        graph_lookup=graph_lookup,
    )
    resource_nodes = [dict(item) for item in list(layered.get("resource_nodes") or []) if isinstance(item, dict)]
    memory_edges = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(layered.get("memory_edges") or [])
        if isinstance(item, dict)
    }
    artifact_edges = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(layered.get("artifact_context_edges") or [])
        if isinstance(item, dict)
    }
    revision_edges = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(layered.get("revision_edges") or [])
        if isinstance(item, dict)
    }
    temporal_edges = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(layered.get("temporal_edges") or [])
        if isinstance(item, dict)
    }
    resources = tuple(_resource_spec_from_payload(item) for item in resource_nodes)
    nodes = tuple(_node_spec_from_graph_node(node, resource_nodes=resource_nodes) for node in graph.nodes)
    edges = tuple(
        _edge_spec_from_graph_edge(
            edge,
            memory_payload=memory_edges.get(edge.edge_id, {}),
            artifact_payload=artifact_edges.get(edge.edge_id, {}),
            revision_payload=revision_edges.get(edge.edge_id, {}),
            temporal_payload=temporal_edges.get(edge.edge_id, {}),
        )
        for edge in graph.edges
    )
    timeline = TaskGraphStandardTimelineSpec(
        entry_node_id=graph.entry_node_id,
        output_node_id=graph.output_node_id,
        temporal_edges=tuple(dict(item) for item in list(layered.get("temporal_edges") or []) if isinstance(item, dict)),
        loop_frames=tuple(dict(item) for item in list(layered.get("loop_frames") or []) if isinstance(item, dict)),
        timeline_blocks=tuple(dict(item) for item in list(layered.get("timeline_blocks") or []) if isinstance(item, dict)),
        phases=_phase_specs(graph),
        scheduler=dict(runtime_spec.diagnostics.get("scheduler_support") or {}),
        runtime_semantics=dict(runtime_spec.diagnostics.get("runtime_semantics") or {}),
    )
    runtime_isolation = TaskGraphRuntimeIsolationSpec(
        task_run_scope_policy=str(dict(graph.runtime_policy or {}).get("task_run_scope_policy") or "isolated_per_task_run"),
        memory_repositories=tuple(
            {
                "repository_id": item.repository_id,
                "resource_node_id": item.node_id,
                "task_run_scope_policy": str(item.lifecycle.get("task_run_scope_policy") or "isolated_per_task_run"),
            }
            for item in resources
            if item.resource_type in {"memory_repository", "memory_collection", "working_memory_store", "thread_ledger", "progress_ledger", "issue_ledger"}
        ),
        artifact_repositories=tuple(
            {
                "repository_id": item.repository_id,
                "resource_node_id": item.node_id,
                "task_run_scope_policy": str(item.lifecycle.get("task_run_scope_policy") or "isolated_per_task_run"),
                "staging_policy": dict(item.lifecycle.get("staging_policy") or {}),
            }
            for item in resources
            if item.resource_type == "artifact_repository"
        ),
        runtime_state_stores=tuple(
            {
                "repository_id": item.repository_id,
                "resource_node_id": item.node_id,
            }
            for item in resources
            if item.resource_type == "runtime_state_store"
        ),
    )
    graph_module_expansion_issue_payloads = [
        dict(issue)
        for expansion in graph_module_expansions
        for issue in expansion.issues
        if isinstance(issue, dict)
    ]
    issues = tuple(
        _issue_from_payload(item)
        for item in [
            *[dict(issue) for issue in list(runtime_spec.issues or []) if isinstance(issue, dict)],
            *[dict(issue) for issue in list(layered.get("issues") or []) if isinstance(issue, dict)],
            *[dict(issue) for issue in list(composable.issues or []) if isinstance(issue, dict)],
            *graph_module_expansion_issue_payloads,
        ]
    )
    return TaskGraphStandardView(
        authority="task_system.task_graph_standard_view",
        graph={
            "graph_id": graph.graph_id,
            "title": graph.title,
            "domain_id": graph.domain_id,
            "task_family": graph.task_family,
            "graph_kind": graph.graph_kind,
            "graph_contract_id": graph.graph_contract_id,
            "contract_bindings": dict(graph.contract_bindings or {}),
            "default_protocol_id": graph.default_protocol_id,
            "publish_state": graph.publish_state,
            "enabled": graph.enabled,
            "metadata": dict(graph.metadata or {}),
        },
        nodes=nodes,
        edges=edges,
        resources=resources,
        units=composable.units,
        interfaces=composable.interfaces,
        port_edges=composable.port_edges,
        graph_module_runtime=composable.graph_module_runtime,
        graph_module_expansions=tuple(graph_module_expansions),
        timeline=timeline,
        runtime_isolation=runtime_isolation,
        memory_matrix=dict(layered.get("memory_matrix") or {}),
        memory_protocol=dict(layered.get("memory_protocol") or {}),
        diagnostics={
            "runtime_spec": runtime_spec.to_dict(),
            "length_budget": length_budget.to_dict(),
            "length_budget_preview": compiled_length_budget_preview(length_budget),
            "layered_graph": layered,
            "composable_graph": composable.to_dict(),
            "graph_module_expansion_count": len(graph_module_expansions),
            "graph_module_expansion_issue_count": sum(len(item.issues) for item in graph_module_expansions),
        },
        issues=issues,
    )


def apply_task_graph_standard_view_update(
    *,
    graph: TaskGraphDefinition,
    payload: dict[str, Any],
) -> TaskGraphDefinition:
    graph_payload = dict(payload.get("graph") or {})
    node_payloads = [dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)]
    edge_payloads = [dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)]
    return task_graph_from_dict(
        {
            "graph_id": str(graph_payload.get("graph_id") or graph.graph_id).strip() or graph.graph_id,
            "title": str(graph_payload.get("title") or graph.title).strip() or graph.title,
            "domain_id": str(graph_payload.get("domain_id") or graph.domain_id).strip(),
            "task_family": str(graph_payload.get("task_family") or graph.task_family).strip(),
            "graph_kind": str(graph_payload.get("graph_kind") or graph.graph_kind).strip() or graph.graph_kind,
            "entry_node_id": str(graph_payload.get("entry_node_id") or payload.get("timeline", {}).get("entry_node_id") or graph.entry_node_id).strip(),
            "output_node_id": str(graph_payload.get("output_node_id") or payload.get("timeline", {}).get("output_node_id") or graph.output_node_id).strip(),
            "nodes": [_graph_node_payload_from_standard_node(item) for item in node_payloads],
            "edges": [_graph_edge_payload_from_standard_edge(item) for item in edge_payloads],
            "graph_contract_id": str(graph_payload.get("graph_contract_id") or graph.graph_contract_id).strip(),
            "contract_bindings": dict(graph_payload.get("contract_bindings") or graph.contract_bindings or {}),
            "default_protocol_id": str(graph_payload.get("default_protocol_id") or graph.default_protocol_id).strip(),
            "working_memory_policy_profile_id": str(graph_payload.get("working_memory_policy_profile_id") or graph.working_memory_policy_profile_id).strip(),
            "working_memory_policy": dict(graph_payload.get("working_memory_policy") or graph.working_memory_policy or {}),
            "runtime_policy": dict(graph_payload.get("runtime_policy") or graph.runtime_policy or {}),
            "context_policy": dict(graph_payload.get("context_policy") or graph.context_policy or {}),
            "publish_state": str(graph_payload.get("publish_state") or graph.publish_state).strip() or graph.publish_state,
            "enabled": bool(graph_payload.get("enabled", graph.enabled)),
            "metadata": dict(graph_payload.get("metadata") or graph.metadata or {}),
        }
    )


def _node_spec_from_graph_node(node: Any, *, resource_nodes: list[dict[str, Any]]) -> TaskGraphStandardNodeSpec:
    metadata = dict(node.metadata or {})
    resource_info = next((item for item in resource_nodes if str(item.get("node_id") or "") == node.node_id), {})
    return TaskGraphStandardNodeSpec(
        node_id=node.node_id,
        title=node.title,
        node_type=node.node_type,
        task_id=node.task_id,
        phase_id=node.phase_id,
        sequence_index=int(node.sequence_index or 0),
        timeline_group_id=node.timeline_group_id,
        main_chain=bool(node.main_chain),
        blocks_phase_exit=bool(node.blocks_phase_exit),
        executor={
            "agent_id": node.agent_id,
            "agent_group_id": node.agent_group_id,
            "agent_selection_policy": node.agent_selection_policy,
            "work_posture": node.work_posture,
            "human_gate_policy": dict(node.human_gate_policy or {}),
            "executor_policy": dict(node.executor_policy or {}),
        },
        contracts={
            "node_contract_id": node.node_contract_id,
            "input_contract_id": node.input_contract_id,
            "output_contract_id": node.output_contract_id,
            "contract_bindings": dict(getattr(node, "contract_bindings", {}) or {}),
        },
        context={
            "context_visibility_policy": dict(node.context_visibility_policy or {}),
        },
        runtime={
            "runtime_lane": node.runtime_lane,
            "execution_mode": node.execution_mode,
            "wait_policy": node.wait_policy,
            "join_policy": node.join_policy,
            "dispatch_group": node.dispatch_group,
            "background_policy": dict(node.background_policy or {}),
            "notification_policy": dict(node.notification_policy or {}),
            "failure_policy": dict(node.failure_policy or {}),
        },
        artifacts={
            "artifact_policy": dict(node.artifact_policy or {}),
            "artifact_target": node.artifact_target,
            "output_path": node.output_path,
            "stream_policy": dict(node.stream_policy or {}),
            "review_gate_policy": dict(node.review_gate_policy or {}),
        },
        loop=dict(node.loop_policy or {}),
        resource={
            "resource_lifecycle_policy": dict(node.resource_lifecycle_policy or {}),
            "resource_repository": dict(resource_info),
        },
        metadata=metadata,
    )


def _edge_spec_from_graph_edge(
    edge: Any,
    *,
    memory_payload: dict[str, Any],
    artifact_payload: dict[str, Any],
    revision_payload: dict[str, Any],
    temporal_payload: dict[str, Any],
) -> TaskGraphStandardEdgeSpec:
    return TaskGraphStandardEdgeSpec(
        edge_id=edge.edge_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        edge_type=edge.edge_type,
        payload_contract_id=edge.payload_contract_id,
        contract_bindings=dict(getattr(edge, "contract_bindings", {}) or {}),
        handoff={
            "a2a_message_type": edge.a2a_message_type,
            "ack_policy": edge.ack_policy,
            "timeout_policy": edge.timeout_policy,
            "wait_policy": edge.wait_policy,
            "ack_required": bool(edge.ack_required),
            "failure_propagation_policy": edge.failure_propagation_policy,
            "result_delivery_policy": edge.result_delivery_policy,
            "context_filter_policy": dict(edge.context_filter_policy or {}),
            "working_memory_handoff_policy": dict(edge.working_memory_handoff_policy or {}),
            "failure_policy": dict(edge.failure_policy or {}),
        },
        memory=memory_payload,
        artifact_context=artifact_payload,
        revision=revision_payload,
        temporal=temporal_payload,
        metadata=dict(edge.metadata or {}),
    )


def _resource_spec_from_payload(payload: dict[str, Any]) -> TaskGraphStandardResourceSpec:
    collection_specs = _collection_specs_from_resource_payload(payload)
    return TaskGraphStandardResourceSpec(
        node_id=str(payload.get("node_id") or ""),
        title=str(payload.get("title") or payload.get("node_id") or ""),
        resource_type=str(payload.get("resource_type") or ""),
        repository_id=str(payload.get("repository_id") or payload.get("node_id") or ""),
        collections=tuple(str(item.get("collection_id") or "").strip() for item in collection_specs if str(item.get("collection_id") or "").strip()),
        collection_specs=tuple(collection_specs),
        lifecycle=dict(payload.get("lifecycle_policy") or {}),
        readable_by=tuple(str(item).strip() for item in list(payload.get("readable_by") or []) if str(item).strip()),
        write_owner_node_ids=tuple(str(item).strip() for item in list(payload.get("write_owner_node_ids") or []) if str(item).strip()),
        metadata=dict(payload.get("metadata") or {}),
    )


def _collection_specs_from_resource_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_specs = [dict(item) for item in list(payload.get("collection_specs") or []) if isinstance(item, dict)]
    if not raw_specs:
        raw_specs = []
        for index, raw in enumerate(list(payload.get("collections") or []), start=1):
            if isinstance(raw, dict):
                raw_specs.append(dict(raw))
            elif str(raw).strip():
                raw_specs.append({"collection_id": str(raw).strip(), "title": str(raw).strip()})
    specs: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_specs, start=1):
        collection_id = str(raw.get("collection_id") or raw.get("id") or raw.get("name") or f"collection_{index}").strip()
        if not collection_id:
            continue
        specs.append(
            {
                **raw,
                "collection_id": collection_id,
                "title": str(raw.get("title") or raw.get("label") or collection_id),
                "schema_id": str(raw.get("schema_id") or raw.get("schema_ref") or ""),
                "record_kinds": [str(item).strip() for item in list(raw.get("record_kinds") or raw.get("kinds") or []) if str(item).strip()],
                "content_requirement": dict(raw.get("content_requirement") or {}),
                "snapshot_budget": dict(raw.get("snapshot_budget") or {}),
            }
        )
    return specs


def _phase_specs(graph: TaskGraphDefinition) -> tuple[dict[str, Any], ...]:
    phase_nodes: dict[str, list[Any]] = {}
    for node in graph.nodes:
        phase_id = str(node.phase_id or "phase.unassigned").strip() or "phase.unassigned"
        phase_nodes.setdefault(phase_id, []).append(node)
    payloads: list[dict[str, Any]] = []
    for phase_id, nodes in sorted(phase_nodes.items(), key=lambda item: item[0]):
        ordered = sorted(nodes, key=lambda node: (int(node.sequence_index or 0), node.node_id))
        payloads.append(
            {
                "phase_id": phase_id,
                "node_ids": [node.node_id for node in ordered],
                "main_chain_node_ids": [node.node_id for node in ordered if bool(node.main_chain)],
                "blocking_node_ids": [node.node_id for node in ordered if bool(node.blocks_phase_exit)],
            }
        )
    return tuple(payloads)


def _issue_from_payload(payload: dict[str, Any]) -> TaskGraphStandardIssue:
    return TaskGraphStandardIssue(
        code=str(payload.get("code") or "unknown"),
        message=str(payload.get("message") or ""),
        severity=str(payload.get("severity") or "error"),
        node_id=str(payload.get("node_id") or ""),
        edge_id=str(payload.get("edge_id") or ""),
        unit_id=str(payload.get("unit_id") or ""),
        source=str(payload.get("authority") or payload.get("source") or ""),
    )


def _graph_module_expansions(
    *,
    current_graph: TaskGraphDefinition,
    graph_module_runtime: tuple[GraphModuleRuntimePlan, ...],
    graph_lookup: Any | None,
) -> list[TaskGraphModuleExpansionSpec]:
    expansions: list[TaskGraphModuleExpansionSpec] = []
    for plan in graph_module_runtime:
        linked_graph_id = str(plan.linked_graph_id or "").strip()
        runtime_node_id = _runtime_node_id_for_expansion(plan)
        scope_prefix = f"{runtime_node_id}::"
        issues: list[dict[str, Any]] = []
        imported_graph = _lookup_imported_graph(graph_lookup, linked_graph_id)
        if not linked_graph_id:
            issues.append(_graph_module_expansion_issue(plan=plan, runtime_node_id=runtime_node_id, code="graph_module_linked_graph_id_missing", message="图模块缺少 linked_graph_id，无法展开导入图模块拓扑。", severity="error"))
        elif linked_graph_id == current_graph.graph_id:
            imported_graph = None
            issues.append(_graph_module_expansion_issue(plan=plan, runtime_node_id=runtime_node_id, code="graph_module_self_reference", message="图模块不能引用当前图自身作为导入图模块，否则会形成递归拓扑。", severity="error"))
        elif graph_lookup is None:
            issues.append(_graph_module_expansion_issue(plan=plan, runtime_node_id=runtime_node_id, code="graph_module_lookup_unavailable", message="当前标准视图没有可用图注册表，无法解析导入图模块拓扑。", severity="warning"))
        elif imported_graph is None:
            issues.append(_graph_module_expansion_issue(plan=plan, runtime_node_id=runtime_node_id, code="graph_module_linked_graph_not_found", message=f"图模块引用的导入图模块不存在：{linked_graph_id}", severity="error"))
        if imported_graph is None:
            expansions.append(
                TaskGraphModuleExpansionSpec(
                    plan_id=plan.plan_id,
                    runtime_node_id=runtime_node_id,
                    unit_id=plan.unit_id,
                    linked_graph_id=linked_graph_id,
                    scope_prefix=scope_prefix,
                    issues=tuple(issues),
                    metadata={"expansion_status": "unavailable"},
                )
            )
            continue

        imported_resources = [
            _expanded_imported_resource_payload(payload=item, scope_prefix=scope_prefix)
            for item in _resource_node_payloads(imported_graph)
        ]
        imported_resource_ids = {str(item.get("node_id") or "").strip() for item in imported_resources}
        imported_nodes = tuple(
            _expanded_imported_node_payload(node=node, scope_prefix=scope_prefix)
            for node in imported_graph.nodes
            if str(node.node_id or "").strip() not in imported_resource_ids
        )
        imported_edges = tuple(
            _expanded_imported_edge_payload(edge=edge, scope_prefix=scope_prefix)
            for edge in imported_graph.edges
        )
        expansions.append(
            TaskGraphModuleExpansionSpec(
                plan_id=plan.plan_id,
                runtime_node_id=runtime_node_id,
                unit_id=plan.unit_id,
                linked_graph_id=linked_graph_id,
                scope_prefix=scope_prefix,
                imported_graph={
                    "graph_id": imported_graph.graph_id,
                    "title": imported_graph.title,
                    "domain_id": imported_graph.domain_id,
                    "task_family": imported_graph.task_family,
                    "graph_kind": imported_graph.graph_kind,
                    "publish_state": imported_graph.publish_state,
                    "enabled": imported_graph.enabled,
                },
                entry_node_id=imported_graph.entry_node_id,
                output_node_id=imported_graph.output_node_id,
                nodes=imported_nodes,
                edges=imported_edges,
                resources=tuple(imported_resources),
                issues=tuple(issues),
                metadata={
                    "expansion_status": "expanded",
                    "node_count": len(imported_nodes),
                    "edge_count": len(imported_edges),
                    "resource_count": len(imported_resources),
                },
            )
        )
    return expansions


def _lookup_imported_graph(graph_lookup: Any | None, graph_id: str) -> TaskGraphDefinition | None:
    graph_id = str(graph_id or "").strip()
    if not graph_lookup or not graph_id:
        return None
    if hasattr(graph_lookup, "get_task_graph"):
        return graph_lookup.get_task_graph(graph_id)
    if callable(graph_lookup):
        return graph_lookup(graph_id)
    if isinstance(graph_lookup, dict):
        value = graph_lookup.get(graph_id)
        return value if isinstance(value, TaskGraphDefinition) else None
    return None


def _runtime_node_id_for_expansion(plan: GraphModuleRuntimePlan) -> str:
    metadata = dict(plan.metadata or {})
    runtime_node_id = str(metadata.get("runtime_node_id") or "").strip()
    if runtime_node_id:
        return runtime_node_id
    unit_id = str(plan.unit_id or "").strip()
    if unit_id.startswith("unit.graph."):
        return f"graph_module.{unit_id.removeprefix('unit.graph.')}"
    plan_id = str(plan.plan_id or "graph_module").strip()
    return f"graph_module.{plan_id.removeprefix('graph_module_runtime.')}"


def _resource_node_payloads(graph: TaskGraphDefinition) -> list[dict[str, Any]]:
    resource_types = {
        "memory",
        "memory_resource",
        "memory_repository",
        "memory_collection",
        "artifact_repository",
        "thread_ledger",
        "progress_ledger",
        "issue_ledger",
        "runtime_state_store",
        "working_memory_store",
    }
    payloads: list[dict[str, Any]] = []
    for node in graph.nodes:
        if str(node.node_type or "").strip() not in resource_types:
            continue
        metadata = dict(node.metadata or {})
        payloads.append(
            {
                "node_id": node.node_id,
                "title": node.title,
                "resource_type": node.node_type,
                "repository_id": str(metadata.get("repository_id") or node.node_id),
                "collections": list(metadata.get("collections") or []),
                "lifecycle_policy": dict(node.resource_lifecycle_policy or {}),
                "readable_by": list(metadata.get("readable_by") or []),
                "write_owner_node_ids": list(metadata.get("write_owner_node_ids") or []),
                "metadata": metadata,
            }
        )
    return payloads


def _expanded_imported_node_payload(*, node: Any, scope_prefix: str) -> dict[str, Any]:
    return {
        "scoped_node_id": f"{scope_prefix}{node.node_id}",
        "node_id": node.node_id,
        "title": node.title,
        "node_type": node.node_type,
        "task_id": node.task_id,
        "phase_id": node.phase_id,
        "sequence_index": int(node.sequence_index or 0),
        "timeline_group_id": node.timeline_group_id,
        "main_chain": bool(node.main_chain),
        "blocks_phase_exit": bool(node.blocks_phase_exit),
        "metadata": dict(node.metadata or {}),
    }


def _expanded_imported_edge_payload(*, edge: Any, scope_prefix: str) -> dict[str, Any]:
    return {
        "scoped_edge_id": f"{scope_prefix}{edge.edge_id}",
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "scoped_source_node_id": f"{scope_prefix}{edge.source_node_id}",
        "scoped_target_node_id": f"{scope_prefix}{edge.target_node_id}",
        "edge_type": edge.edge_type,
        "payload_contract_id": edge.payload_contract_id,
        "metadata": dict(edge.metadata or {}),
    }


def _expanded_imported_resource_payload(*, payload: dict[str, Any], scope_prefix: str) -> dict[str, Any]:
    resource = _resource_spec_from_payload(payload).to_dict()
    node_id = str(resource.get("node_id") or "").strip()
    resource["scoped_node_id"] = f"{scope_prefix}{node_id}" if node_id else ""
    return resource


def _graph_module_expansion_issue(
    *,
    plan: GraphModuleRuntimePlan,
    runtime_node_id: str,
    code: str,
    message: str,
    severity: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "node_id": runtime_node_id,
        "unit_id": plan.unit_id,
        "plan_id": plan.plan_id,
        "linked_graph_id": plan.linked_graph_id,
        "authority": "task_system.graph_module_expansion",
    }


def _graph_node_payload_from_standard_node(payload: dict[str, Any]) -> dict[str, Any]:
    executor = dict(payload.get("executor") or {})
    contracts = dict(payload.get("contracts") or {})
    context = dict(payload.get("context") or {})
    runtime = dict(payload.get("runtime") or {})
    artifacts = dict(payload.get("artifacts") or {})
    resource = dict(payload.get("resource") or {})
    return {
        "node_id": str(payload.get("node_id") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "node_type": str(payload.get("node_type") or "agent").strip() or "agent",
        "task_id": str(payload.get("task_id") or "").strip(),
        "phase_id": str(payload.get("phase_id") or "").strip(),
        "sequence_index": int(payload.get("sequence_index") or 0),
        "timeline_group_id": str(payload.get("timeline_group_id") or "").strip(),
        "main_chain": bool(payload.get("main_chain", True)),
        "blocks_phase_exit": bool(payload.get("blocks_phase_exit", True)),
        "agent_id": str(executor.get("agent_id") or "").strip(),
        "agent_group_id": str(executor.get("agent_group_id") or "").strip(),
        "agent_selection_policy": str(executor.get("agent_selection_policy") or "explicit_agent").strip() or "explicit_agent",
        "work_posture": str(executor.get("work_posture") or "").strip(),
        "human_gate_policy": dict(executor.get("human_gate_policy") or {}),
        "executor_policy": dict(executor.get("executor_policy") or {}),
        "node_contract_id": str(contracts.get("node_contract_id") or "").strip(),
        "input_contract_id": str(contracts.get("input_contract_id") or "").strip(),
        "output_contract_id": str(contracts.get("output_contract_id") or "").strip(),
        "contract_bindings": dict(contracts.get("contract_bindings") or payload.get("contract_bindings") or {}),
        "context_visibility_policy": dict(context.get("context_visibility_policy") or {}),
        "runtime_lane": str(runtime.get("runtime_lane") or "").strip(),
        "execution_mode": str(runtime.get("execution_mode") or "sync").strip() or "sync",
        "wait_policy": str(runtime.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed",
        "join_policy": str(runtime.get("join_policy") or "all_success").strip() or "all_success",
        "dispatch_group": str(runtime.get("dispatch_group") or "").strip(),
        "background_policy": dict(runtime.get("background_policy") or {}),
        "notification_policy": dict(runtime.get("notification_policy") or {}),
        "failure_policy": dict(runtime.get("failure_policy") or {}),
        "artifact_policy": dict(artifacts.get("artifact_policy") or {}),
        "artifact_target": str(artifacts.get("artifact_target") or "").strip(),
        "output_path": str(artifacts.get("output_path") or "").strip(),
        "stream_policy": dict(artifacts.get("stream_policy") or {}),
        "review_gate_policy": dict(artifacts.get("review_gate_policy") or {}),
        "loop_policy": dict(payload.get("loop") or {}),
        "resource_lifecycle_policy": dict(resource.get("resource_lifecycle_policy") or {}),
        "metadata": dict(payload.get("metadata") or {}),
    }


def _graph_edge_payload_from_standard_edge(payload: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(payload.get("handoff") or {})
    metadata = dict(payload.get("metadata") or {})
    for extra in ("memory", "artifact_context", "revision", "temporal"):
        extra_payload = dict(payload.get(extra) or {})
        if extra_payload:
            metadata.setdefault(f"{extra}_standard_view", extra_payload)
    return {
        "edge_id": str(payload.get("edge_id") or "").strip(),
        "source_node_id": str(payload.get("source_node_id") or "").strip(),
        "target_node_id": str(payload.get("target_node_id") or "").strip(),
        "edge_type": str(payload.get("edge_type") or "handoff").strip() or "handoff",
        "payload_contract_id": str(payload.get("payload_contract_id") or "").strip(),
        "contract_bindings": dict(payload.get("contract_bindings") or {}),
        "a2a_message_type": str(handoff.get("a2a_message_type") or "message/send").strip() or "message/send",
        "ack_policy": str(handoff.get("ack_policy") or "explicit_ack").strip() or "explicit_ack",
        "timeout_policy": str(handoff.get("timeout_policy") or "fail_closed").strip() or "fail_closed",
        "wait_policy": str(handoff.get("wait_policy") or "").strip(),
        "ack_required": bool(handoff.get("ack_required", True)),
        "failure_propagation_policy": str(handoff.get("failure_propagation_policy") or "fail_downstream").strip() or "fail_downstream",
        "result_delivery_policy": str(handoff.get("result_delivery_policy") or "contract_payload_and_refs").strip() or "contract_payload_and_refs",
        "context_filter_policy": dict(handoff.get("context_filter_policy") or {}),
        "working_memory_handoff_policy": dict(handoff.get("working_memory_handoff_policy") or {}),
        "failure_policy": dict(handoff.get("failure_policy") or {}),
        "metadata": metadata,
    }
