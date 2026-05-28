from __future__ import annotations

from pathlib import Path
from typing import Any
import time

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from harness.graph.models import GraphHarnessConfig, safe_id, stable_hash
from runtime.contracts.compiler import compile_coordination_contract_manifest
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.registry.flow_registry import TaskFlowRegistry


def publish_graph_harness_config_for_graph(
    *,
    base_dir: Path,
    graph_id: str,
    publish_version: str = "published",
    _visited: set[str] | None = None,
) -> Any:
    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise ValueError(f"TaskGraph not found: {graph_id}")
    visited = set(_visited or set())
    if graph.graph_id in visited:
        raise ValueError(f"cyclic graph module publication detected: {graph.graph_id}")
    visited.add(graph.graph_id)
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
    )
    runtime_registry = AgentRuntimeRegistry(base_dir)
    agent_profiles = tuple(
        profile
        for profile in (
            runtime_registry.get_profile(str(node.agent_id or "").strip())
            for node in runtime_spec.nodes
            if str(node.agent_id or "").strip()
        )
        if profile is not None
    )
    manifest = compile_coordination_contract_manifest(
        contract_registry=TaskContractRegistry(base_dir),
        coordination_task=registry.derive_coordination_task_view_from_graph(graph),
        graph_spec=runtime_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    linked_config_ids = _publish_linked_graph_module_configs(
        base_dir=Path(base_dir),
        registry=registry,
        runtime_spec=runtime_spec,
        publish_version=publish_version,
        visited=visited,
    )
    config = build_graph_harness_config_from_runtime_spec(
        graph=graph,
        runtime_spec=runtime_spec,
        contract_manifest=manifest.to_dict(),
        publish_version=publish_version,
        linked_module_config_ids=linked_config_ids,
    )
    return registry.upsert_graph_harness_config(config, publish=True)


def build_graph_harness_config_from_runtime_spec(
    *,
    graph: Any,
    runtime_spec: Any,
    contract_manifest: dict[str, Any] | None = None,
    publish_version: str = "published",
    linked_module_config_ids: dict[str, str] | None = None,
) -> GraphHarnessConfig:
    runtime_payload = runtime_spec.to_dict()
    graph_metadata = dict(getattr(graph, "metadata", {}) or {})
    graph_runtime_policy = dict(getattr(graph, "runtime_policy", {}) or {})
    graph_context_policy = dict(getattr(graph, "context_policy", {}) or {})
    linked_configs = dict(linked_module_config_ids or {})
    nodes = tuple(_node_config(node, graph_id=str(graph.graph_id or "")) for node in runtime_payload.get("nodes") or [])
    edges = tuple(_edge_config(edge) for edge in runtime_payload.get("edges") or [])
    modules = tuple(
        _module_config(plan, linked_config_ids=linked_configs)
        for plan in list(runtime_payload.get("graph_module_runtime_plans") or runtime_payload.get("graph_modules") or [])
        if isinstance(plan, dict)
    )
    split_plans = [
        dict(item)
        for item in list(dict(getattr(runtime_spec, "diagnostics", {}) or {}).get("split_plans") or [])
        if isinstance(item, dict)
    ]
    control = {
        "start_node_ids": list(runtime_payload.get("start_node_ids") or []),
        "terminal_node_ids": list(runtime_payload.get("terminal_node_ids") or []),
        "scheduling_policy": {
            "mode": str(graph_runtime_policy.get("scheduling_mode") or "topology"),
            "max_active_nodes": int(graph_runtime_policy.get("max_active_nodes") or 1),
        },
        "max_active_nodes": int(graph_runtime_policy.get("max_active_nodes") or 1),
        "completion_policy": _policy_dict(graph_runtime_policy.get("completion_policy")),
        "failure_policy": _policy_dict(graph_runtime_policy.get("failure_policy")),
        "retry_policy": _policy_dict(graph_runtime_policy.get("retry_policy")),
        "checkpoint_policy": _policy_dict(graph_runtime_policy.get("checkpoint_policy")),
        "resume_policy": {"mode": "config_id_locked"},
        "human_gate_policy": _policy_dict(graph_metadata.get("human_gate_policy")),
        "graph_loop_policy": _policy_dict(graph_metadata.get("graph_loop_policy")),
        "batch_policy": {
            "enabled": bool(split_plans),
            "split_plans": split_plans,
        },
        "temporal_edges": [dict(item) for item in list(runtime_payload.get("temporal_edges") or []) if isinstance(item, dict)],
        "revision_edges": [dict(item) for item in list(runtime_payload.get("revision_edges") or []) if isinstance(item, dict)],
        "communication_protocol_id": str(getattr(graph, "default_protocol_id", "") or graph_metadata.get("protocol_id") or ""),
        "handoff_policy": str((runtime_payload.get("communication_modes") or ["handoff"])[0] or graph_metadata.get("handoff_policy") or "handoff"),
        "merge_policy": str(graph_runtime_policy.get("merge_policy") or graph_metadata.get("output_merge_policy") or ""),
    }
    contracts = {
        "manifest": dict(contract_manifest or {}),
        "node_contracts": list(dict(contract_manifest or {}).get("node_contracts") or []),
        "edge_contracts": list(dict(contract_manifest or {}).get("edge_handoff_contracts") or []),
        "graph_module_handoff_contracts": list(dict(contract_manifest or {}).get("graph_module_handoff_contracts") or []),
        "runtime_contracts": list(dict(contract_manifest or {}).get("runtime_contracts") or []),
        "acceptance_contracts": list(dict(contract_manifest or {}).get("acceptance_contracts") or []),
    }
    provisional = {
        "graph_id": graph.graph_id,
        "graph_title": graph.title,
        "publish_version": publish_version,
        "task_environment_id": str(graph_runtime_policy.get("task_environment_id") or graph_context_policy.get("task_environment_id") or graph.domain_id or ""),
        "root_task_ref": str(graph.graph_contract_id or graph.graph_id),
        "control": control,
        "nodes": [dict(item) for item in nodes],
        "edges": [dict(item) for item in edges],
        "loop_frames": [dict(item) for item in list(runtime_payload.get("loop_frames") or []) if isinstance(item, dict)],
        "resources": {
            "resource_nodes": [dict(item) for item in list(runtime_payload.get("resource_nodes") or []) if isinstance(item, dict)],
        },
        "memory": {
            "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
            "working_memory_policy": dict(graph.working_memory_policy or {}),
            "memory_matrix": dict(runtime_payload.get("memory_matrix") or {}),
            "read_rules": [dict(item) for item in list(runtime_payload.get("memory_edges") or []) if isinstance(item, dict)],
        },
        "artifacts": {
            "context_edges": [dict(item) for item in list(runtime_payload.get("artifact_context_edges") or []) if isinstance(item, dict)],
        },
        "permissions": dict(graph_runtime_policy.get("permissions") or graph_metadata.get("permissions") or {}),
        "tools": dict(graph_runtime_policy.get("tools") or graph_metadata.get("tools") or {}),
        "agents": {
            "coordinator_agent_id": str(runtime_spec.coordinator_agent_id or "agent:0"),
            "agent_group_id": str(runtime_spec.agent_group_id or ""),
            "runtime_lane": str(graph_runtime_policy.get("runtime_lane") or "task_graph"),
        },
        "contracts": contracts,
        "modules": [dict(item) for item in modules],
        "diagnostics": {
            "source": "task_system.graph_harness_config_publisher",
            "compiler_diagnostics": dict(getattr(runtime_spec, "diagnostics", {}) or {}),
            "runtime_spec_summary": {
                "node_count": len(runtime_payload.get("nodes") or []),
                "edge_count": len(runtime_payload.get("edges") or []),
                "graph_module_count": len(runtime_payload.get("graph_module_runtime_plans") or []),
                "issue_count": len(runtime_payload.get("issues") or []),
            },
            "issues": list(runtime_payload.get("issues") or []),
        },
        "authority_map": {
            "compile": "task_system.graph_harness_config_publisher",
            "assemble": "harness.graph.runtime",
            "decide": "harness.graph.loop",
            "execute_agent": "harness.agent_loop",
        },
        "source_refs": {
            "graph_id": graph.graph_id,
            "publish_state": graph.publish_state,
            "graph_contract_id": graph.graph_contract_id,
            "default_protocol_id": graph.default_protocol_id,
        },
    }
    content_hash = stable_hash(
        {
            "config_schema_version": "graph_harness_config.v1",
            "authority": "harness.graph_harness_config",
            "status": "published",
            **provisional,
        }
    )
    config_id = f"ghcfg:{safe_id(str(graph.graph_id or 'graph'))}:{content_hash[:16]}"
    return GraphHarnessConfig(
        config_id=config_id,
        content_hash=content_hash,
        published_at=time.time(),
        status="published",
        **provisional,
    )


def _node_config(node: dict[str, Any], *, graph_id: str) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    contract_bindings = dict(metadata.get("contract_bindings") or {})
    prompt_contract = dict(metadata.get("prompt_contract") or {})
    node_id = str(node.get("node_id") or "").strip()
    node_type = str(node.get("node_type") or "agent").strip() or "agent"
    task_ref = str(node.get("task_id") or metadata.get("task_ref") or f"task_graph.node.{graph_id}.{node_id}").strip()
    return {
        "node_id": node_id,
        "title": str(node.get("title") or node_id),
        "node_type": node_type,
        "task_ref": task_ref,
        "agent_id": str(node.get("agent_id") or ""),
        "agent_profile_id": str(metadata.get("agent_profile_id") or metadata.get("agent_profile_ref") or ""),
        "runtime_lane": str(node.get("runtime_lane") or ""),
        "executor": {
            "executor_type": _executor_type_for_node(node),
            "executor_policy": dict(node.get("executor_policy") or metadata.get("executor_policy") or {}),
        },
        "execution": {
            "execution_mode": str(node.get("execution_mode") or "sync"),
            "wait_policy": str(node.get("wait_policy") or "wait_all_upstream_completed"),
            "join_policy": str(node.get("join_policy") or "all_success"),
            "dispatch_group": str(node.get("dispatch_group") or ""),
        },
        "contracts": {
            "node_contract_id": str(metadata.get("node_contract_id") or ""),
            "input_contract_id": str(metadata.get("input_contract_id") or ""),
            "output_contract_id": str(metadata.get("output_contract_id") or ""),
            "contract_bindings": contract_bindings,
        },
        "prompt": {
            "role_prompt": str(prompt_contract.get("role_prompt") or metadata.get("role_prompt") or ""),
            "task_instruction": str(prompt_contract.get("task_instruction") or metadata.get("task_instruction") or ""),
            "output_instruction": str(prompt_contract.get("output_instruction") or metadata.get("output_instruction") or ""),
        },
        "context": dict(node.get("context_visibility_policy") or {}),
        "memory": {
            "read_policy": dict(node.get("memory_read_policy") or {}),
            "writeback_policy": dict(node.get("memory_writeback_policy") or {}),
            "dynamic_read_policy": dict(node.get("dynamic_memory_read_policy") or {}),
        },
        "artifacts": dict(node.get("artifact_policy") or {}),
        "stream": dict(node.get("stream_policy") or {}),
        "gates": {
            "review_gate_policy": dict(node.get("review_gate_policy") or {}),
            "human_gate_policy": dict(metadata.get("human_gate_policy") or {}),
        },
        "retry": dict(metadata.get("quality_retry_policy") or {}),
        "permissions": dict(metadata.get("permissions") or {}),
        "tools": dict(metadata.get("tools") or {}),
        "metadata": metadata,
    }


def _edge_config(edge: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(edge.get("metadata") or {})
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": str(edge.get("mode") or edge.get("edge_type") or "handoff"),
        "wait_policy": str(edge.get("wait_policy") or ""),
        "ack_policy": str(edge.get("ack_policy") or "explicit_ack"),
        "ack_required": bool(edge.get("ack_required", True)),
        "failure_propagation_policy": str(edge.get("failure_propagation_policy") or "fail_downstream"),
        "result_delivery_policy": str(edge.get("result_delivery_policy") or "contract_payload_and_refs"),
        "payload_contract_id": str(edge.get("payload_contract_id") or ""),
        "context_filter_policy": dict(edge.get("context_filter_policy") or {}),
        "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
        "working_memory_handoff_policy": dict(edge.get("working_memory_handoff_policy") or {}),
        "temporal_policy": dict(metadata.get("temporal_policy") or {}),
        "revision_policy": dict(metadata.get("revision_policy") or {}),
        "metadata": metadata,
    }


def _module_config(plan: dict[str, Any], *, linked_config_ids: dict[str, str]) -> dict[str, Any]:
    linked_graph_id = str(plan.get("linked_graph_id") or "").strip()
    return {
        "plan_id": str(plan.get("plan_id") or ""),
        "runtime_node_id": str(plan.get("runtime_node_id") or ""),
        "unit_id": str(plan.get("unit_id") or ""),
        "linked_graph_id": linked_graph_id,
        "linked_config_id": linked_config_ids.get(linked_graph_id, ""),
        "version_ref": str(plan.get("version_ref") or ""),
        "handoff_contract_id": str(plan.get("handoff_contract_id") or ""),
        "input_port_id": str(plan.get("input_port_id") or "input.default"),
        "output_port_id": str(plan.get("output_port_id") or "output.default"),
        "isolation_policy": str(plan.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(plan.get("visibility_policy") or "committed_only"),
        "metadata": dict(plan.get("metadata") or {}),
    }


def _publish_linked_graph_module_configs(
    *,
    base_dir: Path,
    registry: TaskFlowRegistry,
    runtime_spec: Any,
    publish_version: str,
    visited: set[str],
) -> dict[str, str]:
    linked: dict[str, str] = {}
    for plan in list(getattr(runtime_spec, "graph_module_runtime_plans", ()) or ()):
        linked_graph_id = str(getattr(plan, "linked_graph_id", "") or "").strip()
        if not linked_graph_id or linked_graph_id in visited:
            continue
        if registry.get_task_graph(linked_graph_id) is None:
            continue
        child = publish_graph_harness_config_for_graph(
            base_dir=base_dir,
            graph_id=linked_graph_id,
            publish_version=publish_version,
            _visited=set(visited),
        )
        linked[linked_graph_id] = str(getattr(child, "config_id", "") or "")
    return linked


def _executor_type_for_node(node: dict[str, Any]) -> str:
    node_type = str(node.get("node_type") or "").strip()
    metadata = dict(node.get("metadata") or {})
    executor_policy = dict(node.get("executor_policy") or metadata.get("executor_policy") or {})
    raw = str(executor_policy.get("default_executor") or executor_policy.get("executor") or "").strip()
    if raw:
        return "graph_module" if raw in {"imported_graph", "graph_module"} else raw
    if node_type == "graph_module" or bool(metadata.get("graph_module")):
        return "graph_module"
    if node_type in {"manual_gate", "human_gate"}:
        return "human"
    if node_type == "tool":
        return "tool"
    return "agent"


def _policy_dict(value: Any, *, string_key: str = "mode") -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        return {string_key: text} if text else {}
    return {}
