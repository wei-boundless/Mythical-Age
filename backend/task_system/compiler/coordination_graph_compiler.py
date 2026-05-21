from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from bootstrap.settings import AppSettingsService
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.models.model_profile_resolver import ModelProfileResolver
from runtime.contracts.length_budget_compiler import compile_length_budget, compiled_length_budget_preview
from task_system.compiler.coordination_graph_models import (
    TaskGraphModuleRuntimePlan,
    TaskGraphRuntimeEdge,
    TaskGraphRuntimeNode,
    TaskGraphRuntimeSpec,
    TaskGraphRuntimeValidationIssue,
)
from task_system.registry.flow_models import SpecificTaskRecord, TaskCommunicationProtocol
from task_system.compiler.layered_graph_normalizer import normalize_task_graph_layers
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphValidationIssue, validate_task_graph
from task_system.planning.task_split_plan_builder import build_static_split_plans_for_graph, split_merge_runtime_issues
from task_system.planning.task_split_merge_models import SplitMergeIssue
from task_system.runtime_semantics import compile_runtime_semantics_manifest


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
    graph_module_runtime_plans = _graph_module_runtime_plans_from_layered_graph(graph=graph, layered_graph=layered_graph)
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
            graph_task_family=graph.task_family,
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
    nodes = _merge_graph_module_runtime_nodes(
        explicit_nodes=nodes,
        graph_module_nodes=_runtime_nodes_from_graph_module_runtime_plans(graph_module_runtime_plans),
    )
    if not nodes:
        nodes = [
            TaskGraphRuntimeNode(
                node_id="coordinator",
                title="协调者",
                node_type="coordinator",
                role="coordinator",
                agent_id=coordinator_agent_id,
                task_family=graph.task_family,
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
        _runtime_issue_from_task_graph_issue(issue)
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
    scheduler_support = _scheduler_support_report(
        graph=graph,
        nodes=nodes,
        edges=edges,
    )
    working_memory_resource_steps = _working_memory_resource_steps(nodes=nodes, edges=edges)
    validation_issues.extend(_runtime_issues_from_scheduler_support(scheduler_support))
    validation_issues.extend(_runtime_issues_from_layered_graph(layered_graph))
    validation_issues.extend(_runtime_issues_from_graph_module_runtime_plans(graph_module_runtime_plans))
    split_merge_issues = split_merge_runtime_issues(split_plans)
    validation_issues.extend(_runtime_issues_from_split_merge_issues(split_merge_issues))
    validation_issues.extend(_runtime_issues_from_length_budget(length_budget))
    validation_issues.extend(_runtime_issues_from_runtime_semantics(runtime_semantics.to_dict()))
    return TaskGraphRuntimeSpec(
        graph_id=graph.graph_id,
        graph_ref=graph.graph_id,
        domain_id=graph.domain_id,
        task_family=graph.task_family,
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
    graph_task_family: str,
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
        projection_id="" if is_graph_module else str(raw_node.projection_id or raw_node.projection_overlay_id or "").strip(),
        task_id="" if is_graph_module else str(raw_node.task_id or "").strip(),
        task_family=str(getattr(raw_node, "task_family", "") or getattr(task, "task_family", "") or graph_task_family).strip(),
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
        runtime_lane=runtime_lane,
    )
    return resolved.to_public_dict()


def _graph_module_runtime_plans_from_layered_graph(
    *,
    graph: TaskGraphDefinition,
    layered_graph: dict[str, Any],
) -> list[TaskGraphModuleRuntimePlan]:
    plans: list[TaskGraphModuleRuntimePlan] = []
    seen: set[str] = set()
    for index, raw_block in enumerate(list(layered_graph.get("timeline_blocks") or []), start=1):
        if not isinstance(raw_block, dict):
            continue
        block = dict(raw_block)
        linked_graph_id = str(block.get("linked_graph_id") or "").strip()
        if not linked_graph_id:
            continue
        block_id = str(block.get("block_id") or f"timeline_block_{index}").strip() or f"timeline_block_{index}"
        plan_id = f"graph_module_runtime.{_safe_runtime_identifier(block_id)}"
        if plan_id in seen:
            plan_id = f"{plan_id}.{index}"
        seen.add(plan_id)
        runtime_node_id = f"graph_module.{_safe_runtime_identifier(block_id)}"
        plans.append(
            TaskGraphModuleRuntimePlan(
                plan_id=plan_id,
                importing_graph_id=graph.graph_id,
                unit_id=f"unit.graph.{_safe_runtime_identifier(block_id)}",
                runtime_node_id=runtime_node_id,
                linked_graph_id=linked_graph_id,
                version_ref=str(block.get("version_ref") or "").strip(),
                handoff_contract_id=_timeline_block_handoff_contract_id(block),
                input_port_id=str(block.get("input_port_id") or "input.default").strip() or "input.default",
                output_port_id=str(block.get("output_port_id") or "output.default").strip() or "output.default",
                isolation_policy=str(block.get("isolation_policy") or "isolated_per_graph_module_run").strip() or "isolated_per_graph_module_run",
                visibility_policy=str(block.get("visibility_policy") or "committed_only").strip() or "committed_only",
                detach_policy=str(block.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
                phase_id=str(block.get("phase_id") or "").strip(),
                sequence_index=int(block.get("sequence_index") or index),
                metadata={
                    "timeline_block_id": block_id,
                    "block_type": str(block.get("block_type") or "").strip(),
                    "entry_node_id": str(block.get("entry_node_id") or "").strip(),
                    "exit_node_id": str(block.get("exit_node_id") or "").strip(),
                    "source_authority": str(block.get("authority") or "task_system.timeline_block"),
                    "contract_bindings": dict(block.get("contract_bindings") or {}),
                    "legacy_contract_fields": dict(dict(block.get("metadata") or {}).get("legacy_contract_fields") or {}),
                    "raw_block": block,
                },
            )
        )
    return plans


def _runtime_nodes_from_graph_module_runtime_plans(plans: list[TaskGraphModuleRuntimePlan]) -> list[TaskGraphRuntimeNode]:
    return [
        TaskGraphRuntimeNode(
            node_id=plan.runtime_node_id,
            title=str(dict(plan.metadata or {}).get("raw_block", {}).get("title") or plan.linked_graph_id or plan.runtime_node_id),
            node_type="graph_module",
            role="graph_module",
            task_id=f"task_graph.node.{plan.importing_graph_id}.{plan.runtime_node_id}",
            executor_policy={
                "default_executor": "graph_module",
                "allowed_executors": ["graph_module"],
                "linked_graph_id": plan.linked_graph_id,
                "imported_graph_id": plan.linked_graph_id,
                "auto_start_imported_initial_stage": True,
                "source": "graph_module_runtime_plan",
            },
            execution_mode="async",
            wait_policy="wait_all_upstream_completed",
            join_policy="all_success",
            phase_id=plan.phase_id,
            sequence_index=plan.sequence_index,
            timeline_group_id=f"graph_module_runtime:{plan.unit_id}",
            blocks_phase_exit=True,
            context_visibility_policy={
                "graph_module_runtime_visibility": plan.visibility_policy,
            "importing_graph_visible_scope": "run_handle_and_committed_output",
            },
            artifact_policy={
                "visibility_policy": plan.visibility_policy,
                "source": "graph_module_commit",
            },
            metadata={
                "graph_module": True,
                "execution_mode": "graph_module_run",
                "graph_module_runtime_plan_id": plan.plan_id,
                "graph_module_runtime_plan": plan.to_dict(),
                "linked_graph_id": plan.linked_graph_id,
                "version_ref": plan.version_ref,
                "handoff_contract_id": plan.handoff_contract_id,
                "input_port_id": plan.input_port_id,
                "output_port_id": plan.output_port_id,
                "isolation_policy": plan.isolation_policy,
                "visibility_policy": plan.visibility_policy,
                "detach_policy": plan.detach_policy,
                "effective_policy_sources": {
                    "node_id": "graph.metadata.timeline_blocks[].linked_graph_id",
                    "execution_mode": "graph_module_runtime_plan",
                    "wait_policy": "graph_module_runtime_plan.default_wait_policy",
                    "join_policy": "graph_module_runtime_plan.default_join_policy",
                },
            },
        )
        for plan in plans
    ]


def _merge_graph_module_runtime_nodes(
    *,
    explicit_nodes: list[TaskGraphRuntimeNode],
    graph_module_nodes: list[TaskGraphRuntimeNode],
) -> list[TaskGraphRuntimeNode]:
    """Merge timeline-derived graph module runtime data into explicit graph_module nodes.

    A graph module import may be stored as a normal editable graph_module node
    while timeline blocks remain the module import authority. Both representations
    resolve to the same runtime node id, so the compiler produces one executable
    node with both editor-side configuration and imported module run handle.
    """
    graph_module_by_id = {node.node_id: node for node in graph_module_nodes if node.node_id}
    merged: list[TaskGraphRuntimeNode] = []
    for explicit in explicit_nodes:
        graph_module_runtime = graph_module_by_id.pop(explicit.node_id, None)
        if graph_module_runtime is None:
            merged.append(explicit)
            continue
        merged.append(_merge_explicit_graph_module_node(explicit=explicit, graph_module_runtime=graph_module_runtime))
    merged.extend(graph_module_by_id.values())
    return merged


def _merge_explicit_graph_module_node(
    *,
    explicit: TaskGraphRuntimeNode,
    graph_module_runtime: TaskGraphRuntimeNode,
) -> TaskGraphRuntimeNode:
    explicit_metadata = dict(explicit.metadata or {})
    graph_module_metadata = dict(graph_module_runtime.metadata or {})
    definition_metadata = {
        key: value
        for key, value in explicit_metadata.items()
        if key not in {"agent_group_id", "model_requirement", "model_resolution"}
    }
    return replace(
        explicit,
        title=explicit.title or graph_module_runtime.title,
        node_type="graph_module",
        role="graph_module",
        agent_id="",
        runtime_lane="",
        projection_id="",
        task_id=graph_module_runtime.task_id,
        task_family=explicit.task_family or graph_module_runtime.task_family,
        executor_policy={
            **dict(explicit.executor_policy or {}),
            **dict(graph_module_runtime.executor_policy or {}),
        },
        execution_mode=explicit.execution_mode or graph_module_runtime.execution_mode,
        wait_policy=explicit.wait_policy or graph_module_runtime.wait_policy,
        join_policy=explicit.join_policy or graph_module_runtime.join_policy,
        phase_id=explicit.phase_id or graph_module_runtime.phase_id,
        sequence_index=explicit.sequence_index or graph_module_runtime.sequence_index,
        timeline_group_id=explicit.timeline_group_id or graph_module_runtime.timeline_group_id,
        blocks_phase_exit=explicit.blocks_phase_exit or graph_module_runtime.blocks_phase_exit,
        context_visibility_policy={
            **dict(explicit.context_visibility_policy or {}),
            **dict(graph_module_runtime.context_visibility_policy or {}),
        },
        artifact_policy={
            **dict(explicit.artifact_policy or {}),
            **dict(graph_module_runtime.artifact_policy or {}),
        },
        metadata={
            **definition_metadata,
            **graph_module_metadata,
            "explicit_graph_module_node": True,
            "runtime_role": "graph_module_container",
            "model_visible": False,
            "definition_node_metadata": definition_metadata,
            "effective_policy_sources": {
                **dict(explicit_metadata.get("effective_policy_sources") or {}),
                **dict(graph_module_metadata.get("effective_policy_sources") or {}),
                "agent_id": "graph_module_container",
                "projection_id": "graph_module_container",
                "graph_module_merge": "graph.nodes[] + graph.metadata.timeline_blocks[]",
            },
        },
    )


def _runtime_issues_from_graph_module_runtime_plans(plans: list[TaskGraphModuleRuntimePlan]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for plan in plans:
        if not plan.version_ref:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="graph_module_version_anchor_missing",
                    message="图模块缺少 version_ref，导入方运行无法稳定锚定图模块版本。",
                    severity="warning",
                    node_id=plan.runtime_node_id,
                )
            )
        if not plan.handoff_contract_id:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="graph_module_handoff_contract_missing",
                    message="图模块缺少 handoff_contract_id，导入图模块提交包无法通过契约追溯。",
                    severity="warning",
                    node_id=plan.runtime_node_id,
                )
            )
    return issues


def _runtime_issues_from_split_merge_issues(issues: tuple[SplitMergeIssue, ...]) -> list[TaskGraphRuntimeValidationIssue]:
    return [
        TaskGraphRuntimeValidationIssue(
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
            node_id=issue.node_id,
        )
        for issue in issues
    ]


def _runtime_issues_from_length_budget(length_budget: Any) -> list[TaskGraphRuntimeValidationIssue]:
    diagnostics = dict(getattr(length_budget, "diagnostics", {}) or {})
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for issue_code in list(diagnostics.get("issues") or []):
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=str(issue_code),
                message=f"长度预算校验失败：{issue_code}",
                severity="warning",
            )
        )
    return issues


def _runtime_issues_from_runtime_semantics(manifest: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in list(manifest.get("diagnostics") or []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning")
        if severity != "error":
            continue
        scope = str(item.get("scope") or "")
        ref_id = str(item.get("ref_id") or "")
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"runtime_semantics_{item.get('code') or 'issue'}",
                message=str(item.get("message") or "Runtime semantics issue"),
                severity=severity,
                node_id=ref_id if scope == "node" else "",
                edge_id=ref_id if scope == "edge" else "",
            )
        )
    return issues


def _safe_runtime_identifier(value: str) -> str:
    sanitized = str(value or "").strip().replace(":", ".").replace("/", ".").replace("\\", ".")
    sanitized = ".".join(part for part in sanitized.split(".") if part)
    return sanitized or "unknown"


def _timeline_block_handoff_contract_id(block: dict[str, Any]) -> str:
    bindings = dict(block.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(handoff.get("handoff_contract_id") or block.get("handoff_contract_id") or "").strip()


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


def _runtime_issue_from_task_graph_issue(issue: TaskGraphValidationIssue) -> TaskGraphRuntimeValidationIssue:
    return TaskGraphRuntimeValidationIssue(
        code=issue.code,
        message=issue.message,
        severity=issue.severity,
        node_id=issue.node_id,
        edge_id=issue.edge_id,
    )


def _scheduler_support_report(
    *,
    graph: TaskGraphDefinition,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
) -> dict[str, Any]:
    supported: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []

    def mark(
        *,
        scope: str,
        ref_id: str,
        field: str,
        value: Any,
        status: str,
        reason: str,
    ) -> None:
        item = {
            "scope": scope,
            "ref_id": ref_id,
            "field": field,
            "value": value,
            "status": status,
            "reason": reason,
        }
        if status == "supported":
            supported.append(item)
        elif status == "partial":
            partial.append(item)
        else:
            unsupported.append(item)

    metadata = dict(graph.metadata or {})
    if metadata.get("timeline_policy"):
        mark(
            scope="graph",
            ref_id=graph.graph_id,
            field="metadata.timeline_policy",
            value=dict(metadata.get("timeline_policy") or {}),
            status="unsupported",
            reason="当前 LangGraph runtime 仍按拓扑依赖推进，尚未按图级 timeline_policy 控制 phase/sequence。",
        )
    if metadata.get("phase_definitions"):
        mark(
            scope="graph",
            ref_id=graph.graph_id,
            field="metadata.phase_definitions",
            value="configured",
            status="partial",
            reason="阶段定义已进入 RuntimeSpec diagnostics 和前端预检，但运行调度尚未按 phase exit policy 推进。",
        )

    for node in nodes:
        if node.execution_mode in {"sync", "async", "background"}:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="supported", reason="该执行模式已由统一调度决策消费，并可按是否阻塞主链区分同步与后台执行。")
        elif node.execution_mode in {"parallel", "barrier", "manual_gate"}:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="supported", reason="该执行模式已有明确的运行语义，调度器可按节点等待与汇合策略消费。")
        else:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="unsupported", reason="当前调度器未实现该执行模式。")

        if node.wait_policy in {"wait_all_upstream_completed", "wait_required_contracts"}:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="supported", reason="运行层已按上游完成和输入绑定阻塞节点。")
        elif node.wait_policy in {"wait_any_upstream_completed", "wait_handoff_ack", "fire_and_continue", "manual_release"}:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="supported", reason="TaskGraphSchedulerState 已消费该等待策略并参与 ready/blocked 判断。")
        else:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="unsupported", reason="当前 ready/blocked 判断尚未完整消费该 wait_policy。")

        if node.join_policy == "all_success":
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="supported", reason="当前拓扑依赖等价于 all_success。")
        elif node.join_policy in {"allow_partial_with_issues", "coordinator_decides"}:
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="supported", reason="TaskGraphSchedulerState 已支持上游全部终态后的部分成功汇聚。")
        else:
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="unsupported", reason="当前调度器尚未实现该 join_policy。")

        if node.phase_id:
            mark(scope="node", ref_id=node.node_id, field="phase_id", value=node.phase_id, status="supported", reason="TaskGraphSchedulerState 已按 active phase gate 控制节点 ready/blocked。")
        if node.sequence_index:
            mark(scope="node", ref_id=node.node_id, field="sequence_index", value=node.sequence_index, status="supported", reason="TaskGraphSchedulerState 已按 phase 内 active sequence 控制节点 ready/blocked。")
        if node.timeline_group_id:
            mark(scope="node", ref_id=node.node_id, field="timeline_group_id", value=node.timeline_group_id, status="partial", reason="并行组已保留到 RuntimeSpec，但运行调度尚未按 timeline_group_id 同步启动。")
        if node.review_gate_policy:
            mark(scope="node", ref_id=node.node_id, field="review_gate_policy", value="configured", status="partial", reason="审核门策略已保留，但运行层仍主要依赖 stage contract / human gate 处理验收。")
        if node.loop_policy:
            mark(scope="node", ref_id=node.node_id, field="loop_policy", value="configured", status="partial", reason="节点循环策略已保留，但通用 TaskGraph loop 调度尚未实现。")

    for edge in edges:
        if edge.wait_policy:
            status, reason = _edge_wait_policy_support_status(edge.wait_policy)
            mark(scope="edge", ref_id=edge.edge_id, field="wait_policy", value=edge.wait_policy, status=status, reason=reason)
        if edge.ack_required or edge.ack_policy:
            status, reason = _edge_ack_policy_support_status(edge=edge)
            mark(scope="edge", ref_id=edge.edge_id, field="ack_policy", value=edge.ack_policy, status=status, reason=reason)
        temporal_bindings = dict(dict(edge.metadata or {}).get("contract_bindings") or {}).get("temporal")
        temporal_policy = dict(temporal_bindings or dict(edge.metadata or {}).get("temporal_semantics") or {})
        for field, value in temporal_policy.items():
            value = str(value or "").strip()
            if not value:
                continue
            status, reason = _edge_temporal_support_status(field=field, value=value)
            mark(scope="edge", ref_id=edge.edge_id, field=f"temporal.{field}", value=value, status=status, reason=reason)
        if edge.failure_propagation_policy in {"fail_downstream", "isolate_failure", "allow_partial", "coordinator_decides"}:
            mark(scope="edge", ref_id=edge.edge_id, field="failure_propagation_policy", value=edge.failure_propagation_policy, status="supported", reason="TaskGraphSchedulerState 已按边级失败传播策略计算有效节点状态，并由运行路由消费。")
        else:
            mark(scope="edge", ref_id=edge.edge_id, field="failure_propagation_policy", value=edge.failure_propagation_policy, status="unsupported", reason="当前调度器未实现该边级失败传播策略。")
        if edge.result_delivery_policy != "contract_payload_and_refs":
            mark(scope="edge", ref_id=edge.edge_id, field="result_delivery_policy", value=edge.result_delivery_policy, status="partial", reason="结果投递策略已保留，但运行视图和 handoff 状态尚未完整区分不同投递方式。")
        timeout_policy = str(dict(edge.metadata or {}).get("timeout_policy") or "")
        if timeout_policy and timeout_policy != "fail_closed":
            mark(scope="edge", ref_id=edge.edge_id, field="timeout_policy", value=timeout_policy, status="unsupported", reason="当前调度器尚未实现边级 timeout policy。")

    return {
        "authority": "task_system.scheduler_support_report",
        "runtime": "langgraph_coordination_runtime",
        "mode": "support_matrix",
        "supported": supported,
        "partial": partial,
        "unsupported": unsupported,
        "supported_count": len(supported),
        "partial_count": len(partial),
        "unsupported_count": len(unsupported),
    }


def _edge_wait_policy_support_status(value: str) -> tuple[str, str]:
    value = str(value or "").strip()
    if value == "wait_handoff_ack":
        return "supported", "edge.wait_policy=wait_handoff_ack 已由 scheduler 消费，会要求 handoff ack 后才释放下游。"
    if value in {"wait_all_upstream_completed", "wait_required_contracts", "wait_any_upstream_completed"}:
        return "partial", "等价节点等待策略已支持，但 edge.wait_policy 目前只作为边级元数据保留；实际 ready 主要由目标节点 wait_policy 决定。"
    if value in {"fire_and_continue", "manual_release"}:
        return "unsupported", "当前 scheduler 尚未把该 edge.wait_policy 作为边级放行算子消费。"
    return "unsupported", "当前 scheduler 未实现该 edge.wait_policy。"


def _edge_ack_policy_support_status(*, edge: TaskGraphRuntimeEdge) -> tuple[str, str]:
    value = str(edge.ack_policy or "").strip()
    if bool(edge.ack_required) is False:
        return "supported", "ack_required=false 时 scheduler 不再要求 handoff ack；ack_policy 仅作为审计字段保留。"
    if value == "explicit_ack":
        return "supported", "显式 ack 已由 wait_handoff_ack / handoff envelope 状态参与下游 ready 判断。"
    if value in {"implicit_ack", "none"}:
        return "partial", "该 ack_policy 会被保存，但 scheduler 不会仅凭该值自动视为确认；若不需要确认，应设置 ack_required=false。"
    if value == "manual_ack":
        return "partial", "handoff envelope 可记录人工确认状态，但独立人工确认工作流尚未完整实现。"
    return "unsupported", "当前 scheduler 未声明支持该 ack_policy。"


def _edge_temporal_support_status(*, field: str, value: str) -> tuple[str, str]:
    field = str(field or "").strip()
    value = str(value or "").strip()
    if field == "trigger_timing":
        if value in {"after_source_success", "after_source_commit"}:
            return "supported", "调度器以源节点完成和有效结果记录作为边触发条件。"
        if value == "after_required_contracts":
            return "partial", "契约引用已进入 RuntimeSpec/Manifest，但 ready 判断仍主要按上游完成和输入绑定处理。"
        if value in {"manual_release", "phase_entry", "phase_exit", "phase_gate_passed"}:
            return "unsupported", "当前运行层尚未实现边级手动释放或 phase 事件触发。"
    if field == "visibility_timing":
        if value in {"after_commit", "next_clock"}:
            return "supported", "timeline gate 使用 accepted result record 和 effective clock 控制下游可见。"
        if value in {"same_clock", "after_ack"}:
            return "partial", "运行层可记录 handoff/ack 状态，但模型输入可见性仍未按该值单独分层。"
        if value in {"next_iteration", "manual_release"}:
            return "unsupported", "当前调度器尚未实现迭代级或边级人工可见性释放。"
    if field == "acknowledgement_timing":
        if value in {"explicit_ack", "ack_before_downstream", "before_downstream_ready"}:
            return "supported", "wait_handoff_ack 和 handoff ack envelope 会阻塞下游 ready。"
        if value in {"no_ack", "none", "implicit_ack"}:
            return "supported", "关闭 ack 或隐式确认时不会额外阻塞下游。"
        if value in {"manual_ack", "ack_before_phase_exit"}:
            return "partial", "ack envelope 可记录确认状态，但 phase exit 级确认尚未成为独立运行门。"
    if field == "propagation_timing":
        if value in {"buffer_until_commit", "blocked_on_failure"}:
            return "supported", "运行层按 accepted result packet 和失败传播策略控制下游释放。"
        if value in {"refs_only", "immediate_refs_only", "summary_only"}:
            return "partial", "结果包和引用可保留，但下游输入装配尚未完整区分该投递方式。"
        if value in {"immediate", "manual_release", "block_until_ack"}:
            return "partial", "调度器有 ack/结果门控，但尚未把该传播值作为独立时序算子。"
    if field in {"phase_timing", "dependency_gate"}:
        if field == "dependency_gate" and value == "handoff_ack":
            return "supported", "dependency_gate=handoff_ack 已由 scheduler 转换为 handoff ack 阻塞。"
        return "partial", "该时序字段会被保留到契约绑定，但运行层只兑现其中一部分门控语义。"
    return "unsupported", "当前调度器未声明支持该边时序字段。"


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


def _runtime_issues_from_scheduler_support(report: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in [*list(report.get("partial") or []), *list(report.get("unsupported") or [])]:
        scope = str(item.get("scope") or "")
        ref_id = str(item.get("ref_id") or "")
        field = str(item.get("field") or "")
        status = str(item.get("status") or "")
        reason = str(item.get("reason") or "")
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"scheduler_policy_{status}",
                message=f"{field} 当前调度支持状态为 {status}：{reason}",
                severity="warning",
                node_id=ref_id if scope == "node" else "",
                edge_id=ref_id if scope == "edge" else "",
            )
        )
    return issues


def _runtime_issues_from_layered_graph(layered_graph: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in list(layered_graph.get("issues") or []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning")
        if severity == "info":
            continue
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"layered_graph_{item.get('code') or 'issue'}",
                message=str(item.get("message") or "Layered graph issue"),
                severity=severity,
                node_id=str(item.get("node_id") or ""),
                edge_id=str(item.get("edge_id") or ""),
            )
        )
    return issues


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
        if graph.task_family and task.task_family != graph.task_family:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="cross_domain_subtask",
                    message=f"节点引用了跨域特定任务：{node.task_id}",
                    node_id=node.node_id,
                )
            )
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
                projection_id=str(raw.get("projection_id") or raw.get("projection_overlay_id") or "").strip(),
                task_id=task_id,
                task_family=str(raw.get("task_family") or getattr(task, "task_family", "") or coordination_task.task_family).strip(),
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
                        "projection_id", "projection_overlay_id", "task_id", "subtask_ref", "task_family",
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
                task_family=coordination_task.task_family,
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
        if coordination_task.domain_id and task.task_family != coordination_task.task_family:
            issues.append(
                TaskGraphRuntimeValidationIssue(
                    code="cross_domain_subtask",
                    message=f"节点引用了跨域特定任务：{node.task_id}",
                    node_id=node.node_id,
                )
            )
    return issues
