from __future__ import annotations

from pathlib import Path
from typing import Any

from bootstrap.settings import AppSettingsService
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.models.model_profile_resolver import ModelProfileResolver
from task_system.compiler.coordination_graph_models import (
    TaskGraphRuntimeEdge,
    TaskGraphRuntimeNode,
    TaskGraphRuntimeSpec,
    TaskGraphRuntimeValidationIssue,
)
from task_system.registry.flow_models import SpecificTaskRecord, TaskCommunicationProtocol
from task_system.compiler.layered_graph_normalizer import normalize_task_graph_layers
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphValidationIssue, validate_task_graph
from task_system.planning.task_split_plan_builder import build_static_split_plans_for_graph, split_merge_runtime_issues
from task_system.runtime_semantics import compile_runtime_semantics_manifest
from task_system.runtime_semantics.length_budget import compile_length_budget, compiled_length_budget_preview
from task_system.compiler.diagnostics import (
    runtime_issue_from_task_graph_issue,
    runtime_issues_from_layered_graph,
    runtime_issues_from_length_budget,
    runtime_issues_from_runtime_semantics,
    runtime_issues_from_scheduler_support,
    runtime_issues_from_split_merge_issues,
    scheduler_support_report,
)
from task_system.compiler.graph_module_compiler import (
    graph_module_runtime_plan_issues,
    graph_module_runtime_plans_from_layered_graph,
    merge_graph_module_runtime_nodes,
    runtime_nodes_from_graph_module_runtime_plans,
)


def compile_task_graph_definition_runtime_spec(
    *,
    graph: TaskGraphDefinition,
    specific_tasks: tuple[SpecificTaskRecord, ...] = (),
    communication_protocol: TaskCommunicationProtocol | None = None,
) -> TaskGraphRuntimeSpec:
    """Compile the first-class TaskGraphDefinition without deriving a legacy coordination view."""
    task_by_id = {item.task_id: item for item in specific_tasks}
    runtime_policy = dict(graph.runtime_policy or {})
    context_policy = dict(graph.context_policy or {})
    graph_metadata = dict(graph.metadata or {})
    length_budget = compile_length_budget(
        explicit=dict(dict(graph.contract_bindings or {}).get("runtime") or {}).get("length_budget"),
        inherited=dict(graph_metadata.get("length_budget") or {}),
        source_chain=("graph.contract_bindings.runtime.length_budget", "graph.metadata.length_budget"),
        source_ref=graph.graph_id,
    )
    coordinator_agent_id = str(runtime_policy.get("coordinator_agent_id") or "agent:0").strip() or "agent:0"
    agent_group_id = str(runtime_policy.get("agent_group_id") or "").strip()
    default_execution_mode = str(runtime_policy.get("default_execution_mode") or "sync").strip() or "sync"
    default_wait_policy = str(runtime_policy.get("default_wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed"
    default_join_policy = str(runtime_policy.get("default_join_policy") or "all_success").strip() or "all_success"
    layered_graph = normalize_task_graph_layers(graph)
    graph_module_runtime_plans = graph_module_runtime_plans_from_layered_graph(graph=graph, layered_graph=layered_graph)
    split_plans = build_static_split_plans_for_graph(graph=graph)
    backend_dir = Path(__file__).resolve().parents[1]
    model_resolver = ModelProfileResolver(AppSettingsService(backend_dir))
    runtime_registry = AgentRuntimeRegistry(backend_dir)
    resource_node_ids = {
        str(item.get("node_id") or "").strip()
        for item in list(layered_graph.get("resource_nodes") or [])
        if isinstance(item, dict) and str(item.get("node_id") or "").strip()
    }
    execution_graph_nodes = [
        node
        for node in graph.nodes
        if str(getattr(node, "node_id", "") or "").strip() not in resource_node_ids
    ]
    nodes = [
        _runtime_node_from_task_graph_node(
            raw_node=node,
            coordinator_agent_id=coordinator_agent_id,
            graph_agent_group_id=agent_group_id,
            task_by_id=task_by_id,
            default_execution_mode=default_execution_mode,
            default_wait_policy=default_wait_policy,
            default_join_policy=default_join_policy,
            context_policy=context_policy,
            model_resolver=model_resolver,
            runtime_registry=runtime_registry,
            graph_model_requirement=_graph_model_requirement(graph),
        )
        for node in execution_graph_nodes
    ]
    nodes = merge_graph_module_runtime_nodes(
        explicit_nodes=nodes,
        graph_module_nodes=runtime_nodes_from_graph_module_runtime_plans(graph_module_runtime_plans),
    )
    if not nodes:
        nodes = [
            TaskGraphRuntimeNode(
                node_id="coordinator",
                title="协调者",
                node_type="coordinator",
                role="coordinator",
                agent_id=coordinator_agent_id,
                metadata={
                    "effective_policy_sources": {
                        "agent_id": "graph.runtime_policy.coordinator_agent_id",
                    },
                },
            )
        ]
    resource_context_edge_ids = {
        str(item.get("edge_id") or "").strip()
        for layer_key in ("memory_edges", "artifact_context_edges")
        for item in list(layered_graph.get(layer_key) or [])
        if isinstance(item, dict) and str(item.get("edge_id") or "").strip()
    }
    revision_edge_ids = {
        str(item.get("edge_id") or "").strip()
        for item in list(layered_graph.get("revision_edges") or [])
        if isinstance(item, dict) and str(item.get("edge_id") or "").strip()
    }
    edges = [
        _runtime_edge_from_task_graph_edge(raw_edge=edge)
        for edge in graph.edges
        if _is_execution_runtime_edge(
            raw_edge=edge,
            resource_node_ids=resource_node_ids,
            non_execution_edge_ids=resource_context_edge_ids,
        )
    ]
    if not edges and len(nodes) > 1:
        edges = _default_edges(nodes, default_mode=_default_communication_mode(graph, communication_protocol))
    runtime_semantics = compile_runtime_semantics_manifest(graph)
    node_ids = [node.node_id for node in nodes]
    main_dependency_edges = _main_dependency_edges(nodes=nodes, edges=edges)
    node_order = {node.node_id: index for index, node in enumerate(nodes)}
    source_ids = {edge.source_node_id for edge in main_dependency_edges}
    target_ids = {
        edge.target_node_id
        for edge in edges
        if not _is_backward_edge(edge=edge, node_order=node_order)
    }
    start_node_ids = tuple(
        dict.fromkeys(
            [
                *([graph.entry_node_id] if graph.entry_node_id else []),
                *(node_id for node_id in node_ids if node_id not in target_ids),
            ]
        )
    )
    terminal_node_ids = tuple(
        dict.fromkeys(
            [
                *([graph.output_node_id] if graph.output_node_id else []),
                *(node_id for node_id in node_ids if node_id not in source_ids),
            ]
        )
    )
    subtask_refs = tuple(
        dict.fromkeys(
            [
                *[str(value).strip() for value in list(graph_metadata.get("subtask_refs") or []) if str(value).strip()],
                *[node.task_id for node in nodes if node.task_id and node.node_type != "graph_module"],
            ]
        )
    )
    subtask_refs = tuple(ref for ref in subtask_refs if ref.startswith("task."))
    communication_modes = tuple(
        dict.fromkeys(
            value
            for value in [
                *[str(item).strip() for item in list(graph_metadata.get("business_communication_modes") or graph_metadata.get("communication_modes") or [])],
                *[edge.mode for edge in edges],
                *([str(item).strip() for item in communication_protocol.message_types] if communication_protocol is not None else []),
            ]
            if value
        )
    )
    validation_issues = [
        runtime_issue_from_task_graph_issue(issue)
        for issue in validate_task_graph(graph)
    ]
    validation_issues.extend(
        _validate_runtime_graph_for_tasks(
            graph=graph,
            nodes=nodes,
            edges=edges,
            task_by_id=task_by_id,
        )
    )
    scheduler_support = scheduler_support_report(
        graph=graph,
        nodes=nodes,
        edges=edges,
    )
    working_memory_resource_steps = _working_memory_resource_steps(nodes=nodes, edges=edges)
    validation_issues.extend(runtime_issues_from_scheduler_support(scheduler_support))
    validation_issues.extend(runtime_issues_from_layered_graph(layered_graph))
    validation_issues.extend(graph_module_runtime_plan_issues(graph_module_runtime_plans))
    split_merge_issues = split_merge_runtime_issues(split_plans)
    validation_issues.extend(runtime_issues_from_split_merge_issues(split_merge_issues))
    validation_issues.extend(runtime_issues_from_length_budget(length_budget))
    validation_issues.extend(runtime_issues_from_runtime_semantics(runtime_semantics.to_dict()))
    return TaskGraphRuntimeSpec(
        graph_id=graph.graph_id,
        graph_ref=graph.graph_id,
        domain_id=graph.domain_id,
        coordinator_agent_id=coordinator_agent_id,
        agent_group_id=agent_group_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        subtask_refs=subtask_refs,
        communication_modes=communication_modes,
        start_node_ids=start_node_ids,
        terminal_node_ids=terminal_node_ids,
        resource_nodes=tuple(dict(item) for item in list(layered_graph.get("resource_nodes") or []) if isinstance(item, dict)),
        temporal_edges=tuple(dict(item) for item in list(layered_graph.get("temporal_edges") or []) if isinstance(item, dict)),
        memory_edges=tuple(dict(item) for item in list(layered_graph.get("memory_edges") or []) if isinstance(item, dict)),
        artifact_context_edges=tuple(dict(item) for item in list(layered_graph.get("artifact_context_edges") or []) if isinstance(item, dict)),
        revision_edges=tuple(dict(item) for item in list(layered_graph.get("revision_edges") or []) if isinstance(item, dict)),
        loop_frames=tuple(dict(item) for item in list(layered_graph.get("loop_frames") or []) if isinstance(item, dict)),
        graph_module_runtime_plans=tuple(graph_module_runtime_plans),
        memory_matrix=dict(layered_graph.get("memory_matrix") or {}),
        issues=tuple(validation_issues),
        diagnostics={
            "source": "task_system.task_graph_definition_runtime_compiler",
            "graph_contract_id": graph.graph_contract_id,
            "contract_bindings": dict(graph.contract_bindings or {}),
            "length_budget": length_budget.to_dict(),
            "length_budget_preview": compiled_length_budget_preview(length_budget),
            "default_protocol_id": graph.default_protocol_id,
            "communication_protocol_id": str(getattr(communication_protocol, "protocol_id", "") or ""),
            "runtime_policy": runtime_policy,
            "context_policy": context_policy,
            "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
            "working_memory_policy": dict(graph.working_memory_policy or {}),
            "artifact_policy": dict(graph_metadata.get("artifact_policy") or {}),
            "timeline_policy": dict(graph_metadata.get("timeline_policy") or {}),
            "phase_definitions": list(graph_metadata.get("phase_definitions") or []),
            "scheduler_support": scheduler_support,
            "runtime_semantics": runtime_semantics.to_dict(),
            "working_memory_resource_steps": working_memory_resource_steps,
            "layered_graph": layered_graph,
            "resource_node_ids_excluded_from_execution": sorted(resource_node_ids),
            "non_execution_edge_ids_excluded_from_execution": sorted(resource_context_edge_ids),
            "revision_edge_ids_preserved_for_routing": sorted(revision_edge_ids),
            "graph_module_runtime_plans": [item.to_dict() for item in graph_module_runtime_plans],
            "split_plans": [item.to_dict() for item in split_plans],
            "split_merge_issues": [item.to_dict() for item in split_merge_issues],
        },
    )


def _is_execution_runtime_edge(
    *,
    raw_edge: Any,
    resource_node_ids: set[str],
    non_execution_edge_ids: set[str],
) -> bool:
    edge_id = str(getattr(raw_edge, "edge_id", "") or "").strip()
    source = str(getattr(raw_edge, "source_node_id", "") or "").strip()
    target = str(getattr(raw_edge, "target_node_id", "") or "").strip()
    edge_type = str(getattr(raw_edge, "edge_type", "") or "").strip()
    if source in resource_node_ids or target in resource_node_ids:
        return False
    if edge_type in {
        "memory_read",
        "memory_write",
        "memory_write_candidate",
        "memory_commit",
        "memory_handoff",
        "artifact_read",
        "artifact_write",
        "artifact_context",
    }:
        return False
    if edge_id in non_execution_edge_ids and edge_type not in {"handoff", "structured_handoff"}:
        return False
    return True


def _runtime_node_from_task_graph_node(
    *,
    raw_node: Any,
    coordinator_agent_id: str,
    graph_agent_group_id: str,
    task_by_id: dict[str, SpecificTaskRecord],
    default_execution_mode: str,
    default_wait_policy: str,
    default_join_policy: str,
    context_policy: dict[str, Any],
    model_resolver: ModelProfileResolver | None = None,
    runtime_registry: AgentRuntimeRegistry | None = None,
    graph_model_requirement: dict[str, Any] | None = None,
) -> TaskGraphRuntimeNode:
    task = task_by_id.get(str(raw_node.task_id or "").strip())
    raw_node_type = str(getattr(raw_node, "node_type", "") or "agent").strip()
    node_metadata = dict(getattr(raw_node, "metadata", {}) or {})
    is_graph_module = raw_node_type == "graph_module" or bool(node_metadata.get("graph_module"))
    node_type = "graph_module" if is_graph_module else raw_node_type
    node_agent_group_id = "" if is_graph_module else str(getattr(raw_node, "agent_group_id", "") or graph_agent_group_id).strip()
    agent_id = str(getattr(raw_node, "agent_id", "") or "").strip()
    if is_graph_module:
        agent_id = ""
    if not is_graph_module and not agent_id and str(getattr(raw_node, "work_posture", "") or "") == "coordinator":
        agent_id = coordinator_agent_id
    if not is_graph_module and not agent_id and not node_agent_group_id:
        agent_id = coordinator_agent_id
    raw_execution_mode = str(getattr(raw_node, "execution_mode", "") or "").strip()
    raw_wait_policy = str(getattr(raw_node, "wait_policy", "") or "").strip()
    raw_join_policy = str(getattr(raw_node, "join_policy", "") or "").strip()
    execution_mode = _effective_node_policy(raw_execution_mode, default_execution_mode, dataclass_default="sync")
    wait_policy = _effective_node_policy(raw_wait_policy, default_wait_policy, dataclass_default="wait_all_upstream_completed")
    join_policy = _effective_node_policy(raw_join_policy, default_join_policy, dataclass_default="all_success")
    artifact_policy = {
        **dict(getattr(raw_node, "artifact_policy", {}) or {}),
    }
    artifact_target = str(getattr(raw_node, "artifact_target", "") or getattr(raw_node, "output_path", "") or "").strip()
    if artifact_target and "artifact_target" not in artifact_policy:
        artifact_policy["artifact_target"] = artifact_target
    contract_bindings = dict(getattr(raw_node, "contract_bindings", {}) or {})
    if is_graph_module:
        contract_bindings = _graph_module_container_contract_bindings(contract_bindings)
    runtime_bindings = dict(contract_bindings.get("runtime") or {})
    model_requirement = {
        **dict(graph_model_requirement or {}),
        **dict(runtime_bindings.get("model_requirement") or {}),
    }
    if is_graph_module:
        model_requirement = {}
    model_resolution = _model_resolution_for_node(
        agent_id=agent_id,
        runtime_lane=str(raw_node.runtime_lane or "").strip(),
        model_requirement=model_requirement,
        model_resolver=model_resolver,
        runtime_registry=runtime_registry,
    )
    return TaskGraphRuntimeNode(
        node_id=str(raw_node.node_id or "").strip(),
        title=str(raw_node.title or raw_node.node_id or "").strip(),
        node_type=node_type,
        role=("graph_module" if is_graph_module else str(raw_node.work_posture or node_metadata.get("role") or ("coordinator" if agent_id == coordinator_agent_id else "participant")).strip()),
        agent_id=agent_id,
        runtime_lane="" if is_graph_module else str(raw_node.runtime_lane or "").strip(),
        task_id="" if is_graph_module else str(raw_node.task_id or "").strip(),
        executor_policy=dict(getattr(raw_node, "executor_policy", {}) or node_metadata.get("executor_policy") or {}),
        execution_mode=execution_mode,
        wait_policy=wait_policy,
        join_policy=join_policy,
        dispatch_group=str(raw_node.dispatch_group or "").strip(),
        phase_id=str(getattr(raw_node, "phase_id", "") or "").strip(),
        sequence_index=int(getattr(raw_node, "sequence_index", 0) or 0),
        timeline_group_id=str(getattr(raw_node, "timeline_group_id", "") or "").strip(),
        blocks_phase_exit=bool(getattr(raw_node, "blocks_phase_exit", True)),
        context_visibility_policy=dict(raw_node.context_visibility_policy or context_policy or {}),
        memory_read_policy=dict(raw_node.memory_read_policy or {}),
        memory_writeback_policy=dict(raw_node.memory_writeback_policy or {}),
        dynamic_memory_read_policy=dict(raw_node.dynamic_memory_read_policy or {}),
        artifact_policy=artifact_policy,
        stream_policy=dict(getattr(raw_node, "stream_policy", {}) or {}),
        review_gate_policy=dict(getattr(raw_node, "review_gate_policy", {}) or {}),
        loop_policy=dict(getattr(raw_node, "loop_policy", {}) or {}),
        monitor_policy=dict(node_metadata.get("monitor_policy") or {}),
        metadata={
            **node_metadata,
            "loop_kind": str(getattr(raw_node, "loop_kind", "") or node_metadata.get("loop_kind") or "").strip(),
            "loop_scope_id": str(getattr(raw_node, "loop_scope_id", "") or node_metadata.get("loop_scope_id") or "").strip(),
            "title_template": str(getattr(raw_node, "title_template", "") or node_metadata.get("title_template") or "").strip(),
            "loop_route_policy": dict(getattr(raw_node, "loop_route_policy", {}) or node_metadata.get("loop_route_policy") or {}),
            "artifact_context_policy": dict(getattr(raw_node, "artifact_context_policy", {}) or node_metadata.get("artifact_context_policy") or {}),
            "revision_context_policy": dict(getattr(raw_node, "revision_context_policy", {}) or node_metadata.get("revision_context_policy") or {}),
            "quality_retry_policy": dict(getattr(raw_node, "quality_retry_policy", {}) or node_metadata.get("quality_retry_policy") or {}),
            "progress_commit_policy": dict(getattr(raw_node, "progress_commit_policy", {}) or node_metadata.get("progress_commit_policy") or {}),
            **({"runtime_role": "graph_module_container", "model_visible": False} if is_graph_module else {}),
            **({} if is_graph_module else {"agent_group_id": node_agent_group_id}),
            "node_contract_id": str(raw_node.node_contract_id or "").strip(),
            "input_contract_id": str(raw_node.input_contract_id or "").strip(),
            "output_contract_id": str(raw_node.output_contract_id or "").strip(),
            "contract_bindings": contract_bindings,
            **({} if is_graph_module else {"model_requirement": model_requirement, "model_resolution": model_resolution}),
            "executor_policy": dict(getattr(raw_node, "executor_policy", {}) or node_metadata.get("executor_policy") or {}),
            "failure_policy": dict(raw_node.failure_policy or {}),
            "human_gate_policy": dict(raw_node.human_gate_policy or {}),
            "background_policy": dict(raw_node.background_policy or {}),
            "notification_policy": dict(raw_node.notification_policy or {}),
            "resource_lifecycle_policy": dict(raw_node.resource_lifecycle_policy or {}),
            "effective_policy_sources": {
                "agent_id": "graph_module_container" if is_graph_module else ("node.agent_id" if str(getattr(raw_node, "agent_id", "") or "").strip() else "graph.runtime_policy.coordinator_agent_id"),
                "execution_mode": "node.execution_mode" if raw_execution_mode and raw_execution_mode != "sync" else "graph.runtime_policy.default_execution_mode",
                "wait_policy": "node.wait_policy" if raw_wait_policy and raw_wait_policy != "wait_all_upstream_completed" else "graph.runtime_policy.default_wait_policy",
                "join_policy": "node.join_policy" if raw_join_policy and raw_join_policy != "all_success" else "graph.runtime_policy.default_join_policy",
            },
        },
    )


def _graph_module_container_contract_bindings(bindings: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in dict(bindings or {}).items():
        if not isinstance(value, dict):
            normalized[key] = value
            continue
        normalized[key] = dict(value)
    runtime = dict(normalized.get("runtime") or {})
    runtime.pop("model_requirement", None)
    if runtime:
        normalized["runtime"] = runtime
    else:
        normalized.pop("runtime", None)
    return normalized


def _runtime_edge_from_task_graph_edge(*, raw_edge: Any) -> TaskGraphRuntimeEdge:
    return TaskGraphRuntimeEdge(
        edge_id=str(raw_edge.edge_id or "").strip(),
        source_node_id=str(raw_edge.source_node_id or "").strip(),
        target_node_id=str(raw_edge.target_node_id or "").strip(),
        mode=str(raw_edge.edge_type or "handoff").strip(),
        payload_contract_id=str(raw_edge.payload_contract_id or "").strip(),
        a2a_message_type=str(raw_edge.a2a_message_type or "message/send").strip(),
        ack_required=bool(raw_edge.ack_required),
        ack_policy=str(raw_edge.ack_policy or "explicit_ack").strip(),
        wait_policy=str(raw_edge.wait_policy or "").strip(),
        failure_propagation_policy=str(raw_edge.failure_propagation_policy or "fail_downstream").strip(),
        result_delivery_policy=str(raw_edge.result_delivery_policy or "contract_payload_and_refs").strip(),
        context_filter_policy=dict(raw_edge.context_filter_policy or {}),
        artifact_ref_policy=dict(raw_edge.artifact_ref_policy or {}),
        working_memory_handoff_policy=dict(raw_edge.working_memory_handoff_policy or {}),
        metadata={
            **dict(raw_edge.metadata or {}),
            "contract_bindings": dict(getattr(raw_edge, "contract_bindings", {}) or {}),
            "timeout_policy": str(raw_edge.timeout_policy or "fail_closed").strip(),
            "failure_policy": dict(raw_edge.failure_policy or {}),
            "effective_policy_sources": {
                "mode": "edge.edge_type",
                "payload_contract_id": "edge.payload_contract_id" if str(raw_edge.payload_contract_id or "").strip() else "unset",
                "ack_policy": "edge.ack_policy",
                "wait_policy": "edge.wait_policy" if str(raw_edge.wait_policy or "").strip() else "target_node.wait_policy",
            },
        },
    )


def _graph_model_requirement(graph: TaskGraphDefinition) -> dict[str, Any]:
    bindings = dict(getattr(graph, "contract_bindings", {}) or {})
    runtime = dict(bindings.get("runtime") or {})
    requirement = runtime.get("model_requirement")
    return dict(requirement) if isinstance(requirement, dict) else {}


def _model_resolution_for_node(
    *,
    agent_id: str,
    runtime_lane: str,
    model_requirement: dict[str, Any],
    model_resolver: ModelProfileResolver | None,
    runtime_registry: AgentRuntimeRegistry | None,
) -> dict[str, Any]:
    if model_resolver is None:
        return {}
    profile = runtime_registry.get_profile(agent_id) if runtime_registry is not None and agent_id else None
    resolved = model_resolver.resolve_model_spec(
        agent_runtime_profile=profile,
        model_requirement=model_requirement,
        graph_runtime_defaults={"runtime_lane": runtime_lane} if runtime_lane else None,
    )
    return resolved.to_public_dict()


def _default_communication_mode(
    graph: TaskGraphDefinition,
    communication_protocol: TaskCommunicationProtocol | None,
) -> str:
    metadata = dict(graph.metadata or {})
    modes = [
        *[str(item).strip() for item in list(metadata.get("business_communication_modes") or metadata.get("communication_modes") or [])],
        *([str(item).strip() for item in communication_protocol.message_types] if communication_protocol is not None else []),
    ]
    return next((item for item in modes if item), "handoff")


def _main_dependency_edges(
    *,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
) -> list[TaskGraphRuntimeEdge]:
    node_order = {node.node_id: index for index, node in enumerate(nodes)}
    return [
        edge
        for edge in edges
        if not _is_feedback_or_backward_edge(edge=edge, node_order=node_order)
    ]


def _is_feedback_or_backward_edge(*, edge: TaskGraphRuntimeEdge, node_order: dict[str, int]) -> bool:
    metadata = dict(edge.metadata or {})
    mode = str(edge.mode or "").strip()
    dependency_role = str(metadata.get("dependency_role") or "").strip()
    loop_role = str(metadata.get("loop_role") or "").strip()
    if mode in {"review_feedback", "repair_feedback", "conditional_feedback"}:
        return True
    if dependency_role in {"feedback", "conditional_feedback", "repair_feedback", "non_blocking_feedback"}:
        return True
    if loop_role in {"repair", "feedback"}:
        return True
    return _is_backward_edge(edge=edge, node_order=node_order)


def _is_backward_edge(*, edge: TaskGraphRuntimeEdge, node_order: dict[str, int]) -> bool:
    source_index = node_order.get(str(edge.source_node_id or "").strip())
    target_index = node_order.get(str(edge.target_node_id or "").strip())
    return source_index is not None and target_index is not None and source_index > target_index


def _effective_node_policy(raw_value: str, graph_default: str, *, dataclass_default: str) -> str:
    if raw_value and raw_value != dataclass_default:
        return raw_value
    return graph_default or raw_value or dataclass_default


def _working_memory_resource_steps(
    *,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for node in nodes:
        if node.memory_read_policy:
            steps.append(
                {
                    "step_id": f"memory_read:{node.node_id}",
                    "operation": "read",
                    "owner_node_id": node.node_id,
                    "before_node_id": node.node_id,
                    "memory_read_policy": dict(node.memory_read_policy),
                    "dynamic_memory_read_policy": dict(node.dynamic_memory_read_policy),
                    "authority": "task_system.working_memory_resource_step",
                }
            )
        if node.memory_writeback_policy:
            steps.append(
                {
                    "step_id": f"memory_write:{node.node_id}",
                    "operation": "write",
                    "owner_node_id": node.node_id,
                    "after_node_id": node.node_id,
                    "memory_writeback_policy": dict(node.memory_writeback_policy),
                    "authority": "task_system.working_memory_resource_step",
                }
            )
    for edge in edges:
        if edge.working_memory_handoff_policy:
            steps.append(
                {
                    "step_id": f"memory_handoff:{edge.edge_id}",
                    "operation": "handoff",
                    "edge_id": edge.edge_id,
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "working_memory_handoff_policy": dict(edge.working_memory_handoff_policy),
                    "authority": "task_system.working_memory_resource_step",
                }
            )
    return steps


def _validate_runtime_graph_for_tasks(
    *,
    graph: TaskGraphDefinition,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
    task_by_id: dict[str, SpecificTaskRecord],
) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    if len(nodes) > 1 and not edges:
        issues.append(TaskGraphRuntimeValidationIssue(code="missing_edges", message="多节点任务图必须配置交接边"))
    for node in nodes:
        if not node.task_id:
            continue
        if str(node.task_id or "").startswith("task_graph.node."):
            continue
        task = task_by_id.get(node.task_id)
        if task is None:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="missing_subtask",
                    message=f"节点引用的特定任务不存在：{node.task_id}",
                    node_id=node.node_id,
                )
            )
            continue
    return issues


def _normalize_nodes(
    *,
    raw_nodes: list[Any],
    coordination_task: CoordinationTaskDefinition,
    task_by_id: dict[str, SpecificTaskRecord],
) -> list[TaskGraphRuntimeNode]:
    normalized: list[TaskGraphRuntimeNode] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("node_id") or raw.get("id") or f"node_{index}").strip()
        if not node_id or node_id in seen:
            continue
        task_id = str(raw.get("task_id") or raw.get("subtask_ref") or "").strip()
        task = task_by_id.get(task_id)
        agent_id = str(raw.get("agent_id") or "").strip()
        if not agent_id and str(raw.get("role") or "") == "coordinator":
            agent_id = coordination_task.coordinator_agent_id
        title = str(raw.get("title") or raw.get("label") or "").strip()
        if not title and task is not None:
            title = task.task_title
        normalized.append(
            TaskGraphRuntimeNode(
                node_id=node_id,
                title=title or node_id,
                node_type=str(raw.get("node_type") or ("subtask" if task_id else "agent_role")).strip(),
                role=str(raw.get("role") or ("coordinator" if agent_id == coordination_task.coordinator_agent_id else "participant")).strip(),
                agent_id=agent_id or coordination_task.coordinator_agent_id,
                runtime_lane=str(raw.get("lane") or raw.get("runtime_lane") or "").strip(),
                task_id=task_id,
                execution_mode=str(raw.get("execution_mode") or "sync").strip() or "sync",
                wait_policy=str(raw.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed",
                join_policy=str(raw.get("join_policy") or "all_success").strip() or "all_success",
                dispatch_group=str(raw.get("dispatch_group") or "").strip(),
                phase_id=str(raw.get("phase_id") or "").strip(),
                sequence_index=int(raw.get("sequence_index") or 0),
                timeline_group_id=str(raw.get("timeline_group_id") or "").strip(),
                blocks_phase_exit=bool(raw.get("blocks_phase_exit", True)),
                context_visibility_policy=dict(raw.get("context_visibility_policy") or {}),
                memory_read_policy=dict(raw.get("memory_read_policy") or {}),
                memory_writeback_policy=dict(raw.get("memory_writeback_policy") or {}),
                dynamic_memory_read_policy=dict(raw.get("dynamic_memory_read_policy") or {}),
                artifact_policy=dict(raw.get("artifact_policy") or {}),
                review_gate_policy=dict(raw.get("review_gate_policy") or {}),
                loop_policy=dict(raw.get("loop_policy") or {}),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key not in {
                        "node_id", "id", "title", "label", "node_type", "role", "agent_id", "lane", "runtime_lane",
                        "task_id", "subtask_ref",
                        "execution_mode", "wait_policy", "join_policy", "dispatch_group", "phase_id", "sequence_index",
                        "timeline_group_id", "blocks_phase_exit", "context_visibility_policy", "memory_read_policy",
                        "memory_writeback_policy", "dynamic_memory_read_policy", "artifact_policy", "review_gate_policy",
                        "loop_policy",
                    }
                },
            )
        )
        seen.add(node_id)
    if not normalized:
        normalized.append(
            TaskGraphRuntimeNode(
                node_id="coordinator",
                title="协调者",
                node_type="coordinator",
                role="coordinator",
                agent_id=coordination_task.coordinator_agent_id,
            )
        )
    return normalized


def _prefer_topology_nodes(
    *,
    raw_nodes: list[Any],
    topology_template: TopologyTemplate | None,
) -> bool:
    if topology_template is None or not topology_template.nodes:
        return False
    node_types = {
        str(dict(item).get("node_type") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    }
    task_refs = [
        str(dict(item).get("task_id") or dict(item).get("subtask_ref") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    ]
    node_ids = {
        str(dict(item).get("node_id") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    }
    if any(task_refs):
        return False
    generic_ids = all(node_id == "coordinator" or node_id.startswith("agent_") for node_id in node_ids if node_id)
    generic_types = node_types.issubset({"", "coordinator", "agent_role"})
    return generic_ids and generic_types


def _normalize_edges(
    *,
    raw_edges: list[Any],
    nodes: list[TaskGraphRuntimeNode],
    default_mode: str,
) -> list[TaskGraphRuntimeEdge]:
    node_ids = {node.node_id for node in nodes}
    normalized: list[TaskGraphRuntimeEdge] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_edges, start=1):
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or raw.get("source") or raw.get("source_node_id") or "").strip()
        target = str(raw.get("to") or raw.get("target") or raw.get("target_node_id") or "").strip()
        if not source or not target or source not in node_ids or target not in node_ids:
            continue
        if (source, target) in seen:
            continue
        normalized.append(
            TaskGraphRuntimeEdge(
                edge_id=str(raw.get("edge_id") or raw.get("id") or f"edge_{index}").strip(),
                source_node_id=source,
                target_node_id=target,
                mode=str(raw.get("mode") or raw.get("policy") or raw.get("message_type") or default_mode).strip(),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key not in {"edge_id", "id", "from", "to", "source", "target", "source_node_id", "target_node_id", "mode", "policy", "message_type"}
                },
            )
        )
        seen.add((source, target))
    return normalized


def _prefer_topology_edges(
    *,
    raw_edges: list[Any],
    topology_template: TopologyTemplate | None,
) -> bool:
    if topology_template is None or not topology_template.edges:
        return False
    pairs = [
        (
            str(dict(item).get("from") or dict(item).get("source") or dict(item).get("source_node_id") or "").strip(),
            str(dict(item).get("to") or dict(item).get("target") or dict(item).get("target_node_id") or "").strip(),
        )
        for item in raw_edges
        if isinstance(item, dict)
    ]
    if not pairs:
        return True
    generic_pairs = all(
        (source == "coordinator" and target.startswith("agent_"))
        or (target == "coordinator" and source.startswith("agent_"))
        for source, target in pairs
        if source and target
    )
    return generic_pairs


def _default_edges(nodes: list[TaskGraphRuntimeNode], *, default_mode: str) -> list[TaskGraphRuntimeEdge]:
    coordinator = next((node.node_id for node in nodes if node.role == "coordinator"), nodes[0].node_id)
    return [
        TaskGraphRuntimeEdge(
            edge_id=f"edge_{index}",
            source_node_id=node.node_id,
            target_node_id=coordinator,
            mode=default_mode,
        )
        for index, node in enumerate(nodes, start=1)
        if node.node_id != coordinator
    ]


def _communication_modes(
    *,
    coordination_task: CoordinationTaskDefinition,
    raw_edges: list[Any],
    protocol: TaskCommunicationProtocol | None,
) -> tuple[str, ...]:
    values: list[str] = []
    values.extend(str(item).strip() for item in coordination_task.communication_modes if str(item).strip())
    for edge in raw_edges:
        if isinstance(edge, dict):
            values.append(str(edge.get("mode") or edge.get("policy") or edge.get("message_type") or "").strip())
    if protocol is not None:
        values.extend(str(item).strip() for item in protocol.message_types if str(item).strip())
    return tuple(dict.fromkeys(value for value in values if value))


def _validate_graph(
    *,
    coordination_task: CoordinationTaskDefinition,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
    task_by_id: dict[str, SpecificTaskRecord],
) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    if not nodes:
        issues.append(TaskGraphRuntimeValidationIssue(code="empty_graph", message="协调任务图不能为空"))
        return issues
    node_ids = {node.node_id for node in nodes}
    if not any(node.role == "coordinator" for node in nodes):
        issues.append(TaskGraphRuntimeValidationIssue(code="missing_coordinator", message="协调任务图必须有协调者节点"))
    if len(nodes) > 1 and not edges:
        issues.append(TaskGraphRuntimeValidationIssue(code="missing_edges", message="多节点协调任务必须配置通信边"))
    for edge in edges:
        if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="invalid_edge_endpoint",
                    message="通信边引用了不存在的节点",
                    edge_id=edge.edge_id,
                )
            )
    for node in nodes:
        if not node.task_id:
            continue
        task = task_by_id.get(node.task_id)
        if task is None:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="missing_subtask",
                    message=f"节点引用的特定任务不存在：{node.task_id}",
                    node_id=node.node_id,
                )
            )
            continue
    return issues


