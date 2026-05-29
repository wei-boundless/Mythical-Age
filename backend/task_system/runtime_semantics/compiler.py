from __future__ import annotations

from collections import Counter
from typing import Any

from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition

from .models import (
    EdgeRuntimeSemantics,
    NodeRuntimeSemantics,
    RuntimeArtifactState,
    RuntimeSemanticsDiagnostic,
    RuntimeSemanticsManifest,
)


def compile_runtime_semantics_manifest(graph: TaskGraphDefinition) -> RuntimeSemanticsManifest:
    node_semantics = tuple(_node_semantics(node) for node in graph.nodes)
    node_role_by_id = {item.node_id: item.semantic_role for item in node_semantics}
    edge_semantics = tuple(_edge_semantics(edge=edge, node_role_by_id=node_role_by_id) for edge in graph.edges)
    diagnostics = [
        *_legacy_graph_diagnostics(graph),
        *_legacy_node_diagnostics(graph.nodes),
        *_legacy_edge_diagnostics(graph.edges),
        *_semantic_shape_diagnostics(graph=graph, node_semantics=node_semantics, edge_semantics=edge_semantics),
    ]
    legacy_fields = tuple(_legacy_field_payloads(graph=graph, diagnostics=diagnostics))
    role_counts = Counter(item.semantic_role for item in node_semantics)
    edge_role_counts = Counter(item.semantic_role for item in edge_semantics)
    return RuntimeSemanticsManifest(
        graph_id=graph.graph_id,
        node_semantics=node_semantics,
        edge_semantics=edge_semantics,
        step_policy={
            "editor_visible": False,
            "runtime_role": "dispatch_wave_checkpoint_boundary",
            "borrows_from_langgraph": [
                "dispatch wave accounting",
                "checkpoint boundary",
                "resume boundary",
                "debug snapshot",
            ],
            "not_graph_semantics": True,
            "authority": "task_system.runtime_step_policy",
        },
        legacy_fields=legacy_fields,
        diagnostics=tuple(diagnostics),
        summary={
            "node_count": len(node_semantics),
            "edge_count": len(edge_semantics),
            "node_role_counts": dict(role_counts),
            "edge_role_counts": dict(edge_role_counts),
            "legacy_field_count": len(legacy_fields),
            "diagnostic_count": len(diagnostics),
            "step_editor_visible": False,
        },
    )


def _node_semantics(node: TaskGraphNodeDefinition) -> NodeRuntimeSemantics:
    node_id = str(node.node_id or "").strip()
    node_type = str(node.node_type or "").strip()
    metadata = dict(node.metadata or {})
    explicit = str(
        metadata.get("runtime_semantic_role")
        or metadata.get("semantic_role")
        or dict(node.contract_bindings or {}).get("runtime_semantic_role")
        or ""
    ).strip()
    evidence: list[str] = []
    if explicit in {"producer", "validator", "approver", "publisher", "aggregator", "router", "resource", "monitor"}:
        evidence.append("metadata.runtime_semantic_role")
        role = explicit
    elif node_type in {"resource", "memory_repository", "artifact_repository"} or dict(node.resource_lifecycle_policy or {}):
        evidence.append("node.resource_lifecycle_policy")
        role = "resource"
    elif node_type in {"review_gate", "validator", "quality_gate"} or dict(node.review_gate_policy or {}):
        evidence.append("node.review_gate_policy")
        role = "validator"
    elif node_type in {"manual_gate", "human_gate", "approval_gate"} or dict(node.human_gate_policy or {}):
        evidence.append("node.human_gate_policy")
        role = "approver"
    elif node_type in {"router", "switch", "condition", "loop_router"} or dict(node.loop or {}).get("route_policy"):
        evidence.append("node.loop.route_policy")
        role = "router"
    elif node_type in {"barrier", "join", "merge", "aggregator"} or str(node.join_policy or "") in {"allow_partial_with_issues", "coordinator_decides"}:
        evidence.append("node.join_policy")
        role = "aggregator"
    elif node_type in {"monitor", "observer"} or dict(metadata.get("monitor_policy") or {}):
        evidence.append("metadata.monitor_policy")
        role = "monitor"
    elif _looks_like_publisher(node):
        evidence.append("node.memory_writeback_policy/artifact_policy")
        role = "publisher"
    else:
        evidence.append("default.execution_node")
        role = "producer"
    return NodeRuntimeSemantics(
        node_id=node_id,
        semantic_role=role,  # type: ignore[arg-type]
        produces_states=_produces_states_for_role(role),
        consumes_states=_consumes_states_for_role(role),
        lifecycle_coordinate={
            "phase_id": str(node.phase_id or "").strip(),
            "sequence_index": int(node.sequence_index or 0),
            "timeline_group_id": str(node.timeline_group_id or "").strip(),
            "authority": "task_system.graph_node_coordinate",
        },
        evidence=tuple(evidence),
    )


def _edge_semantics(*, edge: TaskGraphEdgeDefinition, node_role_by_id: dict[str, str]) -> EdgeRuntimeSemantics:
    edge_type = str(edge.edge_type or "").strip()
    metadata = dict(edge.metadata or {})
    explicit = str(
        metadata.get("runtime_semantic_role")
        or metadata.get("semantic_role")
        or dict(edge.contract_bindings or {}).get("runtime_semantic_role")
        or ""
    ).strip()
    evidence: list[str] = []
    if explicit in {
        "activation",
        "data_input",
        "validation_input",
        "approval_input",
        "publish_input",
        "resource_read",
        "resource_write",
        "reference",
        "retry",
        "failure_route",
    }:
        role = explicit
        evidence.append("metadata.runtime_semantic_role")
    elif edge_type in {"memory_read", "artifact_read", "resource_read"}:
        role = "resource_read"
        evidence.append("edge.edge_type")
    elif edge_type in {"memory_write", "memory_commit", "artifact_write", "resource_write"}:
        role = "resource_write"
        evidence.append("edge.edge_type")
    elif edge_type in {"revision", "retry", "feedback"}:
        role = "retry"
        evidence.append("edge.edge_type")
    elif str(edge.failure_propagation_policy or "") in {"isolate_failure", "coordinator_decides"} or edge_type in {"failure_route", "error_route"}:
        role = "failure_route"
        evidence.append("edge.failure_propagation_policy")
    elif edge_type in {"reference", "non_blocking_reference"} or bool(dict(edge.context_filter_policy or {}).get("non_blocking")):
        role = "reference"
        evidence.append("edge.context_filter_policy")
    else:
        target_role = node_role_by_id.get(str(edge.target_node_id or "").strip(), "")
        source_role = node_role_by_id.get(str(edge.source_node_id or "").strip(), "")
        if target_role == "validator":
            role = "validation_input"
            evidence.append("target.semantic_role")
        elif target_role == "approver":
            role = "approval_input"
            evidence.append("target.semantic_role")
        elif target_role == "publisher":
            role = "publish_input"
            evidence.append("target.semantic_role")
        elif source_role == "resource":
            role = "resource_read"
            evidence.append("source.semantic_role")
        else:
            role = "activation" if not _edge_carries_data(edge) else "data_input"
            evidence.append("edge.default")
    blocks_activation = role not in {"reference", "resource_write", "failure_route"} and str(edge.wait_policy or "") != "fire_and_continue"
    return EdgeRuntimeSemantics(
        edge_id=str(edge.edge_id or "").strip(),
        source_node_id=str(edge.source_node_id or "").strip(),
        target_node_id=str(edge.target_node_id or "").strip(),
        semantic_role=role,  # type: ignore[arg-type]
        required_source_state=_required_source_state(role),
        blocks_activation=blocks_activation,
        carries_data=_edge_carries_data(edge) or role not in {"activation", "failure_route"},
        evidence=tuple(evidence),
    )


def _produces_states_for_role(role: str) -> tuple[RuntimeArtifactState, ...]:
    if role == "validator":
        return ("validated", "rejected")
    if role == "approver":
        return ("validated", "rejected")
    if role == "publisher":
        return ("published",)
    if role == "resource":
        return ()
    if role == "monitor":
        return ()
    return ("produced",)


def _consumes_states_for_role(role: str) -> tuple[RuntimeArtifactState, ...]:
    if role == "validator":
        return ("produced", "pending_validation")
    if role == "approver":
        return ("validated",)
    if role == "publisher":
        return ("validated",)
    if role == "aggregator":
        return ("produced", "validated", "published")
    if role == "router":
        return ("produced", "validated", "rejected", "quarantined")
    return ("published", "produced")


def _required_source_state(role: str) -> RuntimeArtifactState:
    if role == "publish_input":
        return "validated"
    if role == "approval_input":
        return "validated"
    if role == "validation_input":
        return "produced"
    if role == "reference":
        return "published"
    if role == "resource_read":
        return "published"
    return "produced"


def _edge_carries_data(edge: TaskGraphEdgeDefinition) -> bool:
    if str(edge.payload_contract_id or "").strip():
        return True
    if dict(edge.artifact_ref_policy or {}):
        return True
    if dict(edge.working_memory_handoff_policy or {}):
        return True
    if dict(edge.context_filter_policy or {}):
        return True
    return str(edge.edge_type or "").strip() in {"handoff", "data", "artifact", "memory_handoff"}


def _looks_like_publisher(node: TaskGraphNodeDefinition) -> bool:
    memory_policy = dict(node.memory_writeback_policy or {})
    artifact_policy = dict(node.artifact_policy or {})
    metadata = dict(node.metadata or {})
    if str(memory_policy.get("write_mode") or "").strip() in {"commit", "publish", "memory_commit"}:
        return True
    if bool(memory_policy.get("commit")) or bool(memory_policy.get("publish")):
        return True
    if str(artifact_policy.get("lifecycle") or "").strip() in {"published", "committed"}:
        return True
    return bool(metadata.get("publisher") or metadata.get("committer"))


def _legacy_graph_diagnostics(graph: TaskGraphDefinition) -> list[RuntimeSemanticsDiagnostic]:
    metadata = dict(graph.metadata or {})
    diagnostics: list[RuntimeSemanticsDiagnostic] = []
    if metadata.get("timeline_policy"):
        diagnostics.append(
            RuntimeSemanticsDiagnostic(
                code="legacy_timeline_policy_not_runtime_semantics",
                message="timeline_policy 不是通用运行语义权威；它只能作为旧配置或展示输入，不能表示 step 或调度边界。",
                scope="graph",
                ref_id=graph.graph_id,
                field="metadata.timeline_policy",
                value=dict(metadata.get("timeline_policy") or {}),
            )
        )
    if metadata.get("phase_definitions"):
        diagnostics.append(
            RuntimeSemanticsDiagnostic(
                code="phase_definitions_are_lifecycle_metadata",
                message="phase_definitions 只能表达生命周期坐标，不应作为默认阻塞链或 step 分组。",
                scope="graph",
                ref_id=graph.graph_id,
                field="metadata.phase_definitions",
                value="configured",
            )
        )
    return diagnostics


def _legacy_node_diagnostics(nodes: tuple[TaskGraphNodeDefinition, ...]) -> list[RuntimeSemanticsDiagnostic]:
    diagnostics: list[RuntimeSemanticsDiagnostic] = []
    for node in nodes:
        node_id = str(node.node_id or "").strip()
        phase_id = str(node.phase_id or "").strip()
        sequence_index = int(node.sequence_index or 0)
        timeline_group_id = str(node.timeline_group_id or "").strip()
        if sequence_index:
            diagnostics.append(
                RuntimeSemanticsDiagnostic(
                    code="sequence_index_legacy_lifecycle_coordinate",
                    message="sequence_index 只是生命周期坐标/展示排序，不是通用因果依赖；需要阻塞关系时必须使用显式边和边语义。",
                    scope="node",
                    ref_id=node_id,
                    field="sequence_index",
                    value=sequence_index,
                )
            )
        if timeline_group_id:
            code = "timeline_group_legacy_display"
            message = "timeline_group_id 不是真并发组；运行时不会按它自动同步启动或汇合。"
            if phase_id and timeline_group_id == phase_id:
                code = "timeline_group_duplicates_phase"
                message = "timeline_group_id 与 phase_id 相同，这是重复生命周期坐标，不应被解释为并发组。"
            diagnostics.append(
                RuntimeSemanticsDiagnostic(
                    code=code,
                    message=message,
                    scope="node",
                    ref_id=node_id,
                    field="timeline_group_id",
                    value=timeline_group_id,
                )
            )
    return diagnostics


def _legacy_edge_diagnostics(edges: tuple[TaskGraphEdgeDefinition, ...]) -> list[RuntimeSemanticsDiagnostic]:
    diagnostics: list[RuntimeSemanticsDiagnostic] = []
    for edge in edges:
        metadata = dict(edge.metadata or {})
        temporal = dict(metadata.get("temporal_semantics") or {})
        if temporal:
            diagnostics.append(
                RuntimeSemanticsDiagnostic(
                    code="edge_temporal_semantics_legacy_projection",
                    message="edge temporal_semantics 是旧时序投影；通用图阻塞、可见性和恢复应由 edge semantic role 与产物状态表达。",
                    scope="edge",
                    ref_id=str(edge.edge_id or "").strip(),
                    field="metadata.temporal_semantics",
                    value=temporal,
                )
            )
    return diagnostics


def _semantic_shape_diagnostics(
    *,
    graph: TaskGraphDefinition,
    node_semantics: tuple[NodeRuntimeSemantics, ...],
    edge_semantics: tuple[EdgeRuntimeSemantics, ...],
) -> list[RuntimeSemanticsDiagnostic]:
    diagnostics: list[RuntimeSemanticsDiagnostic] = []
    node_ids = {item.node_id for item in node_semantics}
    for edge in edge_semantics:
        if edge.source_node_id not in node_ids:
            diagnostics.append(
                RuntimeSemanticsDiagnostic(
                    code="semantic_edge_missing_source",
                    message="边语义引用了不存在的源节点。",
                    severity="error",
                    scope="edge",
                    ref_id=edge.edge_id,
                    field="source_node_id",
                    value=edge.source_node_id,
                )
            )
        if edge.target_node_id not in node_ids:
            diagnostics.append(
                RuntimeSemanticsDiagnostic(
                    code="semantic_edge_missing_target",
                    message="边语义引用了不存在的目标节点。",
                    severity="error",
                    scope="edge",
                    ref_id=edge.edge_id,
                    field="target_node_id",
                    value=edge.target_node_id,
                )
            )
    if len(graph.nodes) > 1 and not graph.edges:
        diagnostics.append(
            RuntimeSemanticsDiagnostic(
                code="semantic_multi_node_graph_without_edges",
                message="多节点图没有边，运行语义无法表达依赖、并发、汇合或数据传递。",
                severity="error",
                scope="graph",
                ref_id=graph.graph_id,
            )
        )
    return diagnostics


def _legacy_field_payloads(*, graph: TaskGraphDefinition, diagnostics: list[RuntimeSemanticsDiagnostic]) -> list[dict[str, Any]]:
    return [
        {
            "scope": item.scope,
            "ref_id": item.ref_id,
            "field": item.field,
            "value": item.value,
            "code": item.code,
            "authority": "task_system.runtime_semantics_legacy_field",
        }
        for item in diagnostics
        if item.code
        in {
            "legacy_timeline_policy_not_runtime_semantics",
            "phase_definitions_are_lifecycle_metadata",
            "sequence_index_legacy_lifecycle_coordinate",
            "timeline_group_legacy_display",
            "timeline_group_duplicates_phase",
            "edge_temporal_semantics_legacy_projection",
        }
    ]


