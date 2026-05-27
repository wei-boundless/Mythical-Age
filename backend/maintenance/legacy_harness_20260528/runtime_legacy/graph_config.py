from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from task_system.registry.flow_models import CoordinationTaskDefinition

GRAPH_HARNESS_CONFIG_SCHEMA_VERSION = "graph_harness_config.v1"
GRAPH_HARNESS_CONFIG_AUTHORITY = "harness.graph_harness_config"


@dataclass(frozen=True, slots=True)
class GraphHarnessConfig:
    config_id: str
    graph_id: str
    graph_title: str
    publish_version: str
    config_schema_version: str = GRAPH_HARNESS_CONFIG_SCHEMA_VERSION
    authority: str = GRAPH_HARNESS_CONFIG_AUTHORITY
    task_environment_id: str = ""
    root_task_ref: str = ""
    control: dict[str, Any] = field(default_factory=dict)
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()
    loop_frames: tuple[dict[str, Any], ...] = ()
    resources: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    permissions: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    contracts: dict[str, Any] = field(default_factory=dict)
    modules: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority_map: dict[str, Any] = field(default_factory=dict)
    source_refs: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    published_at: float = 0.0
    status: str = "published"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [dict(item) for item in self.nodes]
        payload["edges"] = [dict(item) for item in self.edges]
        payload["loop_frames"] = [dict(item) for item in self.loop_frames]
        payload["modules"] = [dict(item) for item in self.modules]
        return payload


def graph_harness_config_from_dict(payload: dict[str, Any]) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id=str(payload.get("config_id") or ""),
        graph_id=str(payload.get("graph_id") or ""),
        graph_title=str(payload.get("graph_title") or payload.get("title") or ""),
        publish_version=str(payload.get("publish_version") or "published"),
        config_schema_version=str(payload.get("config_schema_version") or GRAPH_HARNESS_CONFIG_SCHEMA_VERSION),
        authority=str(payload.get("authority") or GRAPH_HARNESS_CONFIG_AUTHORITY),
        task_environment_id=str(payload.get("task_environment_id") or ""),
        root_task_ref=str(payload.get("root_task_ref") or ""),
        control=dict(payload.get("control") or {}),
        nodes=tuple(dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)),
        edges=tuple(dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)),
        loop_frames=tuple(dict(item) for item in list(payload.get("loop_frames") or []) if isinstance(item, dict)),
        resources=dict(payload.get("resources") or {}),
        memory=dict(payload.get("memory") or {}),
        artifacts=dict(payload.get("artifacts") or {}),
        permissions=dict(payload.get("permissions") or {}),
        tools=dict(payload.get("tools") or {}),
        agents=dict(payload.get("agents") or {}),
        contracts=dict(payload.get("contracts") or {}),
        modules=tuple(dict(item) for item in list(payload.get("modules") or []) if isinstance(item, dict)),
        diagnostics=dict(payload.get("diagnostics") or {}),
        authority_map=dict(payload.get("authority_map") or {}),
        source_refs=dict(payload.get("source_refs") or {}),
        content_hash=str(payload.get("content_hash") or ""),
        published_at=float(payload.get("published_at") or 0.0),
        status=str(payload.get("status") or "published"),
    )


def _policy_dict(value: Any, *, string_key: str = "mode") -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        return {string_key: text} if text else {}
    return {}


def build_graph_harness_config_from_runtime_spec(
    *,
    graph: Any,
    runtime_spec: Any,
    contract_manifest: dict[str, Any] | None = None,
    config_id: str = "",
    publish_version: str = "published",
    linked_module_config_ids: dict[str, str] | None = None,
) -> GraphHarnessConfig:
    runtime_payload = runtime_spec.to_dict()
    graph_payload = graph.to_dict()
    linked_config_ids = dict(linked_module_config_ids or {})
    nodes = tuple(_node_config_from_runtime_node(node, graph=graph) for node in runtime_payload.get("nodes") or [])
    edges = tuple(_edge_config_from_runtime_edge(edge) for edge in runtime_payload.get("edges") or [])
    modules = tuple(
        _module_config_from_runtime_plan(plan, linked_config_ids=linked_config_ids)
        for plan in runtime_payload.get("graph_module_runtime_plans") or runtime_payload.get("graph_modules") or []
        if isinstance(plan, dict)
    )
    loop_frames = tuple(
        dict(item)
        for item in list(runtime_payload.get("loop_frames") or dict(graph.metadata or {}).get("loop_frames") or [])
        if isinstance(item, dict)
    )
    graph_metadata = dict(graph.metadata or {})
    graph_runtime_policy = dict(graph.runtime_policy or {})
    graph_context_policy = dict(graph.context_policy or {})
    graph_loop_policy = _policy_dict(graph_metadata.get("graph_loop_policy"))
    split_plans = [dict(item) for item in list(dict(runtime_spec.diagnostics or {}).get("split_plans") or []) if isinstance(item, dict)]
    control = {
        "start_node_ids": list(runtime_payload.get("start_node_ids") or []),
        "terminal_node_ids": list(runtime_payload.get("terminal_node_ids") or []),
        "scheduling_mode": str(graph_runtime_policy.get("scheduling_mode") or "topology"),
        "max_active_nodes": int(graph_runtime_policy.get("max_active_nodes") or 1),
        "completion_policy": _policy_dict(graph_runtime_policy.get("completion_policy")),
        "failure_policy": _policy_dict(graph_runtime_policy.get("failure_policy")),
        "retry_policy": _policy_dict(graph_runtime_policy.get("retry_policy")),
        "human_gate_policy": _policy_dict(graph_metadata.get("human_gate_policy")),
        "checkpoint_policy": _policy_dict(graph_runtime_policy.get("checkpoint_policy")),
        "resume_policy": {"mode": "config_id_locked"},
        "result_commit_policy": _policy_dict(graph_runtime_policy.get("result_commit_policy")),
        "loop_policy": graph_loop_policy,
        "continuation_policy": _policy_dict(graph_metadata.get("continuation_policy")),
        "coordination_mode": str(graph_runtime_policy.get("coordination_mode") or graph_metadata.get("coordination_mode") or "review_merge"),
        "communication_protocol_id": str(graph.default_protocol_id or graph_metadata.get("protocol_id") or ""),
        "handoff_policy": str((runtime_payload.get("communication_modes") or ["handoff"])[0] or graph_metadata.get("handoff_policy") or "handoff"),
        "merge_policy": str(graph_runtime_policy.get("merge_policy") or graph_metadata.get("output_merge_policy") or ""),
        "temporal_edges": [dict(item) for item in list(runtime_payload.get("temporal_edges") or []) if isinstance(item, dict)],
        "revision_edges": [dict(item) for item in list(runtime_payload.get("revision_edges") or []) if isinstance(item, dict)],
        "batch_policy": {
            "source": "GraphHarnessConfig.control.batch_policy.split_plans",
            "enabled": bool(split_plans),
            "split_plans": split_plans,
        },
    }
    manifest = dict(contract_manifest or {})
    stage_contracts = _graph_stage_contracts(
        graph=graph,
        graph_id=str(graph.graph_id or ""),
        runtime_payload=runtime_payload,
        nodes=[dict(item) for item in nodes],
        edges=[dict(item) for item in edges],
        modules=[dict(item) for item in modules],
    )
    contracts = {
        "manifest": manifest,
        "stage_contracts": stage_contracts,
        "stage_sequence": [{"stage_id": str(item.get("stage_id") or item.get("node_id") or "")} for item in stage_contracts],
        "node_contracts": list(manifest.get("node_contracts") or []),
        "edge_contracts": list(manifest.get("edge_handoff_contracts") or []),
        "prompt_contracts": [
            {
                "prompt_contract_ref": str(node.get("prompt_contract_ref") or f"prompt:{node.get('node_id', '')}"),
                "node_id": str(node.get("node_id") or ""),
                "role_prompt": str(dict(node.get("prompt_contract") or {}).get("role_prompt") or ""),
            }
            for node in nodes
            if str(dict(node.get("prompt_contract") or {}).get("role_prompt") or "")
        ],
        "acceptance_contracts": list(manifest.get("acceptance_contracts") or []),
        "runtime_contracts": list(manifest.get("runtime_contracts") or []),
    }
    diagnostics = {
        "source": "task_system.graph_harness_config_publisher",
        "compiled_adapter_summary": {
            "adapter_kind": "TaskGraphRuntimeSpec",
            "adapter_scope": "publication_only",
            "node_count": len(runtime_payload.get("nodes") or []),
            "edge_count": len(runtime_payload.get("edges") or []),
            "graph_module_count": len(runtime_payload.get("graph_module_runtime_plans") or []),
            "split_plan_count": len(split_plans),
        },
        "compiler_diagnostics": dict(runtime_spec.diagnostics or {}),
        "graph_payload_summary": {
            "node_count": len(runtime_payload.get("nodes") or []),
            "edge_count": len(runtime_payload.get("edges") or []),
            "graph_module_count": len(runtime_payload.get("graph_module_runtime_plans") or []),
        },
        "coordination_task": _coordination_task_payload_from_graph_payload(
            graph_payload=graph_payload,
            runtime_payload=runtime_payload,
        ),
    }
    source_refs = {
        "graph_id": graph.graph_id,
        "publish_state": graph.publish_state,
        "graph_contract_id": graph.graph_contract_id,
        "default_protocol_id": graph.default_protocol_id,
    }
    provisional = {
        "config_schema_version": GRAPH_HARNESS_CONFIG_SCHEMA_VERSION,
        "graph_id": graph.graph_id,
        "graph_title": graph.title,
        "publish_version": publish_version,
        "control": control,
        "nodes": [dict(item) for item in nodes],
        "edges": [dict(item) for item in edges],
        "loop_frames": [dict(item) for item in loop_frames],
        "modules": [dict(item) for item in modules],
        "contracts": contracts,
        "diagnostics": diagnostics,
        "source_refs": source_refs,
    }
    content_hash = _content_hash(provisional)
    resolved_config_id = config_id or f"ghcfg:{_safe_id(graph.graph_id)}:{content_hash[:16]}"
    return GraphHarnessConfig(
        config_id=resolved_config_id,
        graph_id=graph.graph_id,
        graph_title=graph.title,
        publish_version=publish_version,
        task_environment_id=str(graph.domain_id or ""),
        root_task_ref=str(graph.graph_contract_id or graph.graph_id),
        control=control,
        nodes=nodes,
        edges=edges,
        loop_frames=loop_frames,
        resources={
            "resource_nodes": [dict(item) for item in list(runtime_payload.get("resource_nodes") or []) if isinstance(item, dict)],
        },
        memory={
            "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
            "working_memory_policy": dict(graph.working_memory_policy or {}),
            "memory_matrix": dict(runtime_payload.get("memory_matrix") or {}),
            "read_rules": [dict(item) for item in list(runtime_payload.get("memory_edges") or []) if isinstance(item, dict)],
            "commit_rules": [
                dict(item)
                for item in list(runtime_payload.get("memory_edges") or [])
                if isinstance(item, dict) and str(item.get("edge_type") or item.get("mode") or "").endswith("commit")
            ],
        },
        artifacts={
            "context_edges": [dict(item) for item in list(runtime_payload.get("artifact_context_edges") or []) if isinstance(item, dict)],
        },
        permissions={},
        tools={},
        agents={
            "coordinator_agent_id": runtime_spec.coordinator_agent_id,
            "agent_group_id": runtime_spec.agent_group_id,
            "coordinator_agent_profile_id": str(graph_runtime_policy.get("coordinator_agent_profile_id") or "task_graph_coordinator"),
            "runtime_lane": str(graph_runtime_policy.get("runtime_lane") or "task_graph_coordination"),
        },
        contracts=contracts,
        modules=modules,
        diagnostics=diagnostics,
        authority_map={
            "observe": "TaskGraphDefinition",
            "compile": "GraphHarnessConfigPublisher",
            "decide": "GraphLoop",
            "execute_agent": "AgentLoop",
            "record": "GraphLoopState",
        },
        source_refs=source_refs,
        content_hash=content_hash,
        published_at=time.time(),
    )


def _graph_stage_contracts(
    *,
    graph: Any,
    graph_id: str,
    runtime_payload: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    derived = _stage_contracts_from_runtime_payload(
        graph_id=graph_id,
        runtime_payload=runtime_payload,
        nodes=nodes,
        edges=edges,
        modules=modules,
    )
    explicit = _explicit_stage_contracts_from_graph(graph=graph, topology_nodes=nodes)
    if not explicit:
        return derived
    explicit_by_stage = {
        str(item.get("stage_id") or item.get("node_id") or "").strip(): dict(item)
        for item in explicit
        if str(item.get("stage_id") or item.get("node_id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for item in derived:
        stage_id = str(item.get("stage_id") or item.get("node_id") or "").strip()
        if stage_id in explicit_by_stage:
            merged.append(_merge_stage_contracts(base=item, explicit=explicit_by_stage[stage_id]))
            emitted.add(stage_id)
        else:
            merged.append(dict(item))
    for item in explicit:
        stage_id = str(item.get("stage_id") or item.get("node_id") or "").strip()
        if stage_id and stage_id not in emitted:
            merged.append(dict(item))
            emitted.add(stage_id)
    return merged


def _explicit_stage_contracts_from_graph(*, graph: Any, topology_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metadata = dict(getattr(graph, "metadata", {}) or {})
    raw_contracts = metadata.get("stage_contracts")
    if not isinstance(raw_contracts, list):
        return []
    node_by_stage = {
        str(item.get("node_id") or item.get("id") or "").strip(): dict(item)
        for item in topology_nodes
        if str(item.get("node_id") or item.get("id") or "").strip()
    }
    contracts: list[dict[str, Any]] = []
    for raw in raw_contracts:
        if not isinstance(raw, dict):
            continue
        stage_id = str(raw.get("stage_id") or raw.get("node_id") or "").strip()
        if not stage_id:
            continue
        node = dict(node_by_stage.get(stage_id) or {})
        payload = {
            "stage_id": stage_id,
            "task_ref": str(raw.get("task_ref") or node.get("task_id") or node.get("task_ref") or f"task_graph.node.{getattr(graph, 'graph_id', '') or 'graph'}.{stage_id}"),
            "node_id": str(raw.get("node_id") or node.get("node_id") or stage_id),
            "required_inputs": [str(item) for item in list(raw.get("required_inputs") or []) if str(item)],
            "optional_inputs": [str(item) for item in list(raw.get("optional_inputs") or []) if str(item)],
            "input_bindings": [dict(item) for item in list(raw.get("input_bindings") or []) if isinstance(item, dict)],
            "output_mappings": [dict(item) for item in list(raw.get("output_mappings") or []) if isinstance(item, dict)],
            "gate_policy": str(raw.get("gate_policy") or ""),
            "on_success": str(raw.get("on_success") or "advance"),
            "on_failure": str(raw.get("on_failure") or "fail_closed"),
            "retry_policy": dict(raw.get("retry_policy") or {}),
            "agent_id": str(raw.get("agent_id") or node.get("agent_id") or node.get("agent_binding_ref") or ""),
            "runtime_lane": str(raw.get("runtime_lane") or node.get("runtime_lane") or node.get("runtime_profile_ref") or ""),
            "role": str(raw.get("role") or node.get("role") or ""),
            "title": str(raw.get("title") or node.get("title") or stage_id),
            "input_contract_id": str(raw.get("input_contract_id") or node.get("input_contract_id") or node.get("input_contract_ref") or ""),
            "output_contract_id": str(raw.get("output_contract_id") or node.get("output_contract_id") or node.get("output_contract_ref") or node.get("node_contract_id") or ""),
            "node_type": str(raw.get("node_type") or node.get("node_type") or node.get("node_kind") or ""),
            "executor_policy": dict(raw.get("executor_policy") or node.get("executor_policy") or {}),
            "memory_read_policy": dict(raw.get("memory_read_policy") or node.get("memory_read_policy") or {}),
            "memory_writeback_policy": dict(raw.get("memory_writeback_policy") or node.get("memory_writeback_policy") or {}),
            "dynamic_memory_read_policy": dict(raw.get("dynamic_memory_read_policy") or node.get("dynamic_memory_read_policy") or {}),
            "review_gate_policy": dict(raw.get("review_gate_policy") or node.get("review_gate_policy") or {}),
            "human_gate_policy": dict(raw.get("human_gate_policy") or node.get("human_gate_policy") or dict(node.get("metadata") or {}).get("human_gate_policy") or {}),
            "artifact_policy": dict(raw.get("artifact_policy") or node.get("artifact_policy") or {}),
            "stream_policy": dict(raw.get("stream_policy") or node.get("stream_policy") or {}),
            "artifact_context_policy": dict(raw.get("artifact_context_policy") or node.get("artifact_context_policy") or {}),
            "revision_context_policy": dict(raw.get("revision_context_policy") or node.get("revision_context_policy") or {}),
            "quality_retry_policy": dict(raw.get("quality_retry_policy") or node.get("quality_retry_policy") or {}),
            "artifact_targets": [dict(item) for item in list(raw.get("artifact_targets") or node.get("artifact_targets") or []) if isinstance(item, dict)],
            "length_budget": dict(raw.get("length_budget") or dict(node.get("execution_policy") or {}).get("length_budget") or {}),
            "metadata": dict(raw.get("metadata") or {}),
        }
        contracts.append(payload)
    return contracts


def _merge_stage_contracts(*, base: dict[str, Any], explicit: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in dict(explicit).items():
        if value in ("", None, [], {}):
            continue
        merged[key] = value
    base_metadata = dict(base.get("metadata") or {})
    explicit_metadata = dict(explicit.get("metadata") or {})
    merged_metadata = {**base_metadata, **explicit_metadata}
    if merged_metadata:
        merged["metadata"] = merged_metadata
    for key in (
        "human_gate_policy",
        "review_gate_policy",
        "memory_read_policy",
        "memory_writeback_policy",
        "dynamic_memory_read_policy",
        "artifact_policy",
        "stream_policy",
        "artifact_context_policy",
        "revision_context_policy",
        "quality_retry_policy",
    ):
        base_value = base.get(key)
        explicit_value = explicit.get(key)
        metadata_value = merged_metadata.get(key)
        if explicit_value not in ("", None, [], {}):
            merged[key] = explicit_value
        elif metadata_value not in ("", None, [], {}):
            merged[key] = metadata_value
        elif base_value not in ("", None, [], {}):
            merged[key] = base_value
    merged.setdefault("executor_policy", dict(base.get("executor_policy") or {}))
    base_executor_policy = dict(base.get("executor_policy") or {})
    explicit_executor_policy = dict(explicit.get("executor_policy") or {})
    executor_policy = dict(merged.get("executor_policy") or {})
    for key in (
        "linked_config_id",
        "linked_graph_id",
        "imported_graph_id",
        "graph_module_runtime_handle",
    ):
        base_value = base.get(key) or base_executor_policy.get(key)
        if base_value not in ("", None, [], {}) and merged.get(key) in ("", None, [], {}):
            merged[key] = base_value
        if base_value not in ("", None, [], {}) and executor_policy.get(key) in ("", None, [], {}):
            executor_policy[key] = base_value
    for key, value in explicit_executor_policy.items():
        if value not in ("", None, [], {}):
            executor_policy[key] = value
    if executor_policy:
        merged["executor_policy"] = executor_policy
    return merged


def graph_harness_config_runtime_spec_payload(config: GraphHarnessConfig | dict[str, Any]) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, GraphHarnessConfig) else dict(config or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    control = dict(payload.get("control") or {})
    memory = dict(payload.get("memory") or {})
    artifacts = dict(payload.get("artifacts") or {})
    resources = dict(payload.get("resources") or {})
    agents = dict(payload.get("agents") or {})
    modules = [dict(item) for item in list(payload.get("modules") or []) if isinstance(item, dict)]
    batch_policy = dict(control.get("batch_policy") or {})
    graph_module_plans = [
        {
            "plan_id": str(item.get("plan_id") or ""),
            "importing_graph_id": str(payload.get("graph_id") or ""),
            "unit_id": str(item.get("module_id") or ""),
            "runtime_node_id": str(item.get("runtime_node_id") or ""),
            "linked_graph_id": str(item.get("linked_graph_id") or ""),
            "version_ref": str(item.get("version_ref") or ""),
            "handoff_contract_id": str(dict(item.get("handoff_policy") or {}).get("handoff_contract_id") or ""),
            "input_port_id": str(item.get("input_port_contract_ref") or "input.default"),
            "output_port_id": str(item.get("output_port_contract_ref") or "output.default"),
            "isolation_policy": str(item.get("isolation_policy") or "isolated_per_graph_module_run"),
            "visibility_policy": str(item.get("visibility_policy") or "committed_only"),
            "metadata": {"linked_config_id": str(item.get("linked_config_id") or "")},
        }
        for item in modules
    ]
    return {
        "graph_id": str(payload.get("graph_id") or ""),
        "graph_ref": str(payload.get("graph_id") or ""),
        "domain_id": str(payload.get("task_environment_id") or ""),
        "coordinator_agent_id": str(agents.get("coordinator_agent_id") or ""),
        "agent_group_id": str(agents.get("agent_group_id") or ""),
        "nodes": [dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)],
        "edges": [dict(item) for item in list(payload.get("edges") or []) if isinstance(item, dict)],
        "start_node_ids": list(control.get("start_node_ids") or []),
        "terminal_node_ids": list(control.get("terminal_node_ids") or []),
        "communication_modes": [str(control.get("handoff_policy") or "handoff")],
        "resource_nodes": [dict(item) for item in list(resources.get("resource_nodes") or []) if isinstance(item, dict)],
        "temporal_edges": [dict(item) for item in list(control.get("temporal_edges") or []) if isinstance(item, dict)],
        "memory_edges": [dict(item) for item in list(memory.get("read_rules") or []) if isinstance(item, dict)],
        "artifact_context_edges": [dict(item) for item in list(artifacts.get("context_edges") or []) if isinstance(item, dict)],
        "revision_edges": [dict(item) for item in list(control.get("revision_edges") or []) if isinstance(item, dict)],
        "loop_frames": [dict(item) for item in list(payload.get("loop_frames") or []) if isinstance(item, dict)],
        "graph_module_runtime_plans": graph_module_plans,
        "graph_modules": graph_module_plans,
        "memory_matrix": dict(memory.get("memory_matrix") or {}),
        "diagnostics": {
            "source": "harness.graph_harness_config_runtime_adapter",
            "graph_harness_config_id": str(payload.get("config_id") or ""),
            "split_plans": [dict(item) for item in list(batch_policy.get("split_plans") or []) if isinstance(item, dict)],
            "working_memory_policy_profile_id": str(memory.get("working_memory_policy_profile_id") or ""),
            "working_memory_policy": dict(memory.get("working_memory_policy") or {}),
            "compiler_summary": dict(diagnostics.get("compiled_adapter_summary") or diagnostics.get("graph_payload_summary") or {}),
        },
    }


def graph_harness_config_dispatch_payload(config: GraphHarnessConfig | dict[str, Any]) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, GraphHarnessConfig) else dict(config or {})
    runtime_payload = graph_harness_config_runtime_spec_payload(payload)
    control = dict(payload.get("control") or {})
    agents = dict(payload.get("agents") or {})
    return {
        "authority": "harness.graph_harness_config_dispatch_payload",
        "graph_id": str(payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
        "task_graph_id": str(payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
        "title": str(payload.get("graph_title") or payload.get("title") or ""),
        "domain_id": str(payload.get("task_environment_id") or runtime_payload.get("domain_id") or ""),
        "graph_kind": "coordination",
        "coordinator_agent_id": str(agents.get("coordinator_agent_id") or runtime_payload.get("coordinator_agent_id") or "agent:0"),
        "agent_group_id": str(agents.get("agent_group_id") or runtime_payload.get("agent_group_id") or ""),
        "topology_template_id": "",
        "handoff_policy": str(control.get("handoff_policy") or "handoff"),
        "conflict_resolution_policy": str(dict(control.get("failure_policy") or {}).get("mode") or ""),
        "output_merge_policy": str(control.get("merge_policy") or ""),
        "shared_context_policy": "",
        "memory_sharing_policy": str(dict(payload.get("memory") or {}).get("working_memory_policy", {}).get("memory_sharing_policy") or ""),
        "graph_nodes": [dict(item) for item in list(runtime_payload.get("nodes") or payload.get("nodes") or []) if isinstance(item, dict)],
        "graph_edges": [
            {**dict(item), "edge_type": str(dict(item).get("mode") or dict(item).get("edge_type") or "")}
            for item in list(runtime_payload.get("edges") or payload.get("edges") or [])
            if isinstance(item, dict)
        ],
        "metadata": {
            "config_id": str(payload.get("config_id") or ""),
            "runtime_payload_source": "GraphHarnessConfig",
            "start_node_ids": list(control.get("start_node_ids") or runtime_payload.get("start_node_ids") or []),
            "terminal_node_ids": list(control.get("terminal_node_ids") or runtime_payload.get("terminal_node_ids") or []),
            "communication_modes": list(runtime_payload.get("communication_modes") or []),
        },
    }


def graph_harness_config_coordination_task(config: GraphHarnessConfig | dict[str, Any]) -> CoordinationTaskDefinition:
    payload = config.to_dict() if isinstance(config, GraphHarnessConfig) else dict(config or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    task_payload = dict(diagnostics.get("coordination_task") or {})
    runtime_payload = graph_harness_config_runtime_spec_payload(payload)
    control = dict(payload.get("control") or {})
    agents = dict(payload.get("agents") or {})
    metadata = dict(task_payload.get("metadata") or {})
    metadata.update(
        {
            "graph_id": str(payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
            "task_graph_id": str(payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
            "continuation_policy": dict(control.get("continuation_policy") or metadata.get("continuation_policy") or {}),
            "graph_loop_policy": dict(control.get("loop_policy") or metadata.get("graph_loop_policy") or {}),
        }
    )
    nodes = tuple(dict(item) for item in list(task_payload.get("graph_nodes") or runtime_payload.get("nodes") or payload.get("nodes") or []) if isinstance(item, dict))
    edges = tuple(dict(item) for item in list(task_payload.get("graph_edges") or runtime_payload.get("edges") or payload.get("edges") or []) if isinstance(item, dict))
    subtask_refs = tuple(str(item) for item in list(task_payload.get("subtask_refs") or runtime_payload.get("subtask_refs") or []) if str(item))
    return CoordinationTaskDefinition(
        graph_id=str(payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
        title=str(payload.get("graph_title") or task_payload.get("title") or ""),
        coordination_mode=str(control.get("coordination_mode") or task_payload.get("coordination_mode") or "review_merge"),
        coordinator_agent_id=str(agents.get("coordinator_agent_id") or runtime_payload.get("coordinator_agent_id") or "agent:0"),
        domain_id=str(payload.get("task_environment_id") or runtime_payload.get("domain_id") or ""),
        agent_group_id=str(agents.get("agent_group_id") or runtime_payload.get("agent_group_id") or ""),
        participant_agent_ids=tuple(str(item) for item in list(task_payload.get("participant_agent_ids") or []) if str(item)),
        topology_template_id=str(task_payload.get("topology_template_id") or ""),
        shared_context_policy=str(task_payload.get("shared_context_policy") or ""),
        memory_sharing_policy=str(task_payload.get("memory_sharing_policy") or ""),
        handoff_policy=str(control.get("handoff_policy") or task_payload.get("handoff_policy") or "handoff"),
        conflict_resolution_policy=str(task_payload.get("conflict_resolution_policy") or ""),
        output_merge_policy=str(control.get("merge_policy") or task_payload.get("output_merge_policy") or ""),
        stop_conditions=tuple(str(item) for item in list(task_payload.get("stop_conditions") or []) if str(item)),
        subtask_refs=subtask_refs,
        graph_nodes=nodes,
        graph_edges=edges,
        communication_modes=tuple(str(item) for item in list(task_payload.get("communication_modes") or runtime_payload.get("communication_modes") or []) if str(item)),
        enabled=True,
        metadata=metadata,
    )


def graph_harness_config_from_run_diagnostics(
    diagnostics: dict[str, Any],
    *,
    registry: Any | None = None,
) -> GraphHarnessConfig | None:
    payload = dict(diagnostics or {})
    embedded = dict(payload.get("graph_harness_config") or payload.get("graph_harness_config_payload") or {})
    if embedded:
        return graph_harness_config_from_dict(embedded)
    config_id = str(payload.get("graph_harness_config_id") or payload.get("graph_harness_config_ref") or "").strip()
    if config_id and registry is not None:
        getter = getattr(registry, "get_graph_harness_config", None)
        if callable(getter):
            return getter(config_id)
    return None


def _node_config_from_runtime_node(node: dict[str, Any], *, graph: Any) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "")
    source_node = next((item for item in graph.nodes if item.node_id == node_id), None)
    source_metadata = dict(getattr(source_node, "metadata", {}) or {}) if source_node is not None else {}
    contract_bindings = dict(source_metadata.get("contract_bindings") or node.get("metadata", {}).get("contract_bindings") or {})
    runtime_bindings = dict(contract_bindings.get("runtime") or {})
    return {
        **dict(node),
        "node_kind": str(node.get("node_type") or "agent"),
        "task_ref": str(node.get("task_id") or ""),
        "agent_binding_ref": str(node.get("agent_id") or ""),
        "runtime_profile_ref": str(node.get("runtime_lane") or ""),
        "input_contract_ref": str(source_metadata.get("input_contract_id") or ""),
        "output_contract_ref": str(source_metadata.get("output_contract_id") or ""),
        "prompt_contract": {
            "prompt_contract_ref": f"prompt:{node_id}",
            "role_prompt": str(source_metadata.get("role_prompt") or dict(node.get("metadata") or {}).get("role_prompt") or ""),
            "task_instruction_template": str(source_metadata.get("task_instruction_template") or ""),
            "boundary_instruction": str(source_metadata.get("boundary_instruction") or ""),
            "quality_instruction": str(source_metadata.get("quality_instruction") or ""),
            "output_instruction": str(source_metadata.get("output_instruction") or ""),
            "forbidden_behavior": str(source_metadata.get("forbidden_behavior") or ""),
        },
        "execution_policy": {
            "execution_mode": str(node.get("execution_mode") or ""),
            "wait_policy": str(node.get("wait_policy") or ""),
            "join_policy": str(node.get("join_policy") or ""),
            "length_budget": dict(runtime_bindings.get("length_budget") or {}),
            "split_policy": dict(runtime_bindings.get("split_policy") or {}),
        },
        "quality_policy": {
            "review_gate_policy": dict(node.get("review_gate_policy") or {}),
            "quality_retry_policy": dict(dict(node.get("metadata") or {}).get("quality_retry_policy") or {}),
            "batch_acceptance_policy": dict(runtime_bindings.get("batch_acceptance_policy") or {}),
        },
        "memory_scope_ref": f"memory:{node_id}",
        "artifact_scope_ref": f"artifact:{node_id}",
        "permission_scope_ref": f"permission:{node_id}",
        "tool_policy_ref": f"tool:{node_id}",
        "loop_scope_ref": str(dict(node.get("metadata") or {}).get("loop_scope_id") or ""),
    }


def _edge_config_from_runtime_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        **dict(edge),
        "edge_kind": str(edge.get("mode") or edge.get("edge_type") or "handoff"),
        "dependency_policy": {"mode": str(edge.get("wait_policy") or "")},
        "handoff_policy": {
            "ack_required": bool(edge.get("ack_required", True)),
            "ack_policy": str(edge.get("ack_policy") or ""),
            "result_delivery_policy": str(edge.get("result_delivery_policy") or ""),
        },
        "condition_policy": dict(dict(edge.get("metadata") or {}).get("condition_policy") or {}),
        "payload_contract_ref": str(edge.get("payload_contract_id") or ""),
        "failure_propagation_policy": str(edge.get("failure_propagation_policy") or "fail_downstream"),
        "memory_handoff_policy": dict(edge.get("working_memory_handoff_policy") or {}),
        "artifact_ref_policy": dict(edge.get("artifact_ref_policy") or {}),
    }


def _module_config_from_runtime_plan(plan: dict[str, Any], *, linked_config_ids: dict[str, str]) -> dict[str, Any]:
    linked_graph_id = str(plan.get("linked_graph_id") or "")
    return {
        "module_id": str(plan.get("unit_id") or plan.get("runtime_node_id") or plan.get("plan_id") or ""),
        "plan_id": str(plan.get("plan_id") or ""),
        "runtime_node_id": str(plan.get("runtime_node_id") or ""),
        "linked_graph_id": linked_graph_id,
        "linked_config_id": str(linked_config_ids.get(linked_graph_id) or ""),
        "version_ref": str(plan.get("version_ref") or "published"),
        "isolation_policy": str(plan.get("isolation_policy") or "isolated_per_graph_module_run"),
        "visibility_policy": str(plan.get("visibility_policy") or "committed_only"),
        "input_port_contract_ref": str(plan.get("input_port_id") or "input.default"),
        "output_port_contract_ref": str(plan.get("output_port_id") or "output.default"),
        "handoff_policy": {"handoff_contract_id": str(plan.get("handoff_contract_id") or "")},
        "result_commit_policy": {"mode": "commit_imported_output_packet"},
    }


def _stage_contracts_from_runtime_payload(
    *,
    graph_id: str,
    runtime_payload: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    incoming_by_target: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if source and target and not _edge_is_feedback_or_control(edge):
            incoming_by_target.setdefault(target, []).append(dict(edge))
    modules_by_node = {
        str(module.get("runtime_node_id") or ""): dict(module)
        for module in modules
        if str(module.get("runtime_node_id") or "")
    }
    contracts: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("node_id") or node.get("id") or "").strip()
        if not node_id:
            continue
        task_ref = str(node.get("task_id") or node.get("task_ref") or "").strip()
        if not task_ref:
            task_ref = f"task_graph.node.{graph_id or runtime_payload.get('graph_id') or 'graph'}.{node_id}"
        input_bindings: list[dict[str, Any]] = []
        required_inputs: list[str] = []
        for edge in incoming_by_target.get(node_id, []):
            source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
            artifact_policy = dict(edge.get("artifact_ref_policy") or {})
            payload_contract_id = str(edge.get("payload_contract_id") or edge.get("contract_id") or "").strip()
            input_key = str(artifact_policy.get("target_input_key") or "").strip()
            if not input_key and payload_contract_id:
                input_key = f"{payload_contract_id}:artifact_refs"
            requires_artifact_input = bool(input_key) and (
                bool(payload_contract_id)
                or bool(artifact_policy)
                or artifact_policy.get("required") is True
            )
            if not requires_artifact_input:
                continue
            input_bindings.append(
                {
                    "source": "stage_output",
                    "source_stage_id": source,
                    "output_key": _stage_output_key_for_node(source, nodes),
                    "input_key": input_key,
                    "required": True,
                }
            )
            required_inputs.append(input_key)
        module = dict(modules_by_node.get(node_id) or {})
        metadata = dict(node.get("metadata") or {}) if isinstance(node.get("metadata"), dict) else {}
        node_type = str(node.get("node_type") or node.get("node_kind") or "").strip()
        executor_policy = dict(node.get("executor_policy") or {})
        if module:
            node_type = "graph_module"
            executor_policy = {
                **executor_policy,
                "default_executor": "graph_module",
                "allowed_executors": ["graph_module"],
                "linked_graph_id": str(module.get("linked_graph_id") or ""),
                "linked_config_id": str(module.get("linked_config_id") or ""),
                "auto_start_imported_initial_stage": True,
            }
        contracts.append(
            {
                "stage_id": node_id,
                "task_ref": task_ref,
                "node_id": node_id,
                "required_inputs": list(dict.fromkeys(required_inputs)),
                "optional_inputs": [],
                "input_bindings": input_bindings,
                "output_mappings": [{"output_key": _stage_output_key_for_payload(node), "required": True}],
                "gate_policy": "review_gate" if node_type == "review_gate" or node.get("review_gate_policy") else "",
                "on_success": "advance",
                "on_failure": "fail_closed",
                "retry_policy": dict(dict(node.get("execution_policy") or {}).get("retry_policy") or node.get("retry_policy") or {}),
                "agent_id": str(node.get("agent_id") or node.get("agent_binding_ref") or ""),
                "runtime_lane": str(node.get("runtime_lane") or node.get("runtime_profile_ref") or ""),
                "role": str(node.get("role") or ""),
                "title": str(node.get("title") or node_id),
                "input_contract_id": str(node.get("input_contract_id") or node.get("input_contract_ref") or ""),
                "output_contract_id": str(node.get("output_contract_id") or node.get("output_contract_ref") or node.get("node_contract_id") or ""),
                "node_type": node_type,
                "executor_policy": executor_policy,
                "memory_read_policy": dict(node.get("memory_read_policy") or {}),
                "memory_writeback_policy": dict(node.get("memory_writeback_policy") or {}),
                "dynamic_memory_read_policy": dict(node.get("dynamic_memory_read_policy") or {}),
                "review_gate_policy": dict(node.get("review_gate_policy") or {}),
                "human_gate_policy": dict(node.get("human_gate_policy") or {}),
                "artifact_policy": dict(node.get("artifact_policy") or {}),
                "stream_policy": dict(node.get("stream_policy") or {}),
                "artifact_context_policy": dict(node.get("artifact_context_policy") or {}),
                "revision_context_policy": dict(node.get("revision_context_policy") or {}),
                "quality_retry_policy": dict(dict(node.get("quality_policy") or {}).get("quality_retry_policy") or node.get("quality_retry_policy") or {}),
                "artifact_targets": list(node.get("artifact_targets") or []),
                "length_budget": dict(dict(node.get("execution_policy") or {}).get("length_budget") or {}),
                "graph_module_runtime_plan": module,
                "graph_module_runtime_plan_id": str(module.get("plan_id") or ""),
                "linked_graph_id": str(module.get("linked_graph_id") or metadata.get("linked_graph_id") or ""),
                "linked_config_id": str(module.get("linked_config_id") or metadata.get("linked_config_id") or ""),
                "version_ref": str(module.get("version_ref") or ""),
                "input_port_id": str(module.get("input_port_contract_ref") or "input.default"),
                "output_port_id": str(module.get("output_port_contract_ref") or "output.default"),
                "metadata": metadata,
            }
        )
    return contracts


def _stage_output_key_for_payload(node: dict[str, Any]) -> str:
    node_id = str(node.get("node_id") or node.get("id") or "").strip()
    contract_ref = str(node.get("output_contract_id") or node.get("output_contract_ref") or node.get("node_contract_id") or "").strip()
    return f"{contract_ref}:artifact_refs" if contract_ref else f"{node_id}:artifact_refs"


def _stage_output_key_for_node(node_id: str, nodes: list[dict[str, Any]]) -> str:
    node = next((dict(item) for item in nodes if str(item.get("node_id") or item.get("id") or "") == node_id), {"node_id": node_id})
    return _stage_output_key_for_payload(node)


def _edge_is_feedback_or_control(edge: dict[str, Any]) -> bool:
    metadata = dict(edge.get("metadata") or {}) if isinstance(edge.get("metadata"), dict) else {}
    mode = str(edge.get("mode") or edge.get("edge_type") or metadata.get("edge_type") or "").strip()
    dependency_role = str(edge.get("dependency_role") or metadata.get("dependency_role") or "").strip()
    loop_role = str(edge.get("loop_role") or metadata.get("loop_role") or "").strip()
    return mode in {
        "review_feedback",
        "repair_feedback",
        "conditional_feedback",
        "revision_request",
        "repair_route",
        "human_handoff",
        "conditional_route",
    } or dependency_role in {
        "feedback",
        "conditional_feedback",
        "repair_feedback",
        "non_blocking_feedback",
        "conditional_route",
        "repair_route",
        "failure_route",
        "human_handoff",
    } or loop_role in {"repair", "feedback"}


def _content_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)[:120] or "graph"


def _coordination_task_payload_from_graph_payload(*, graph_payload: dict[str, Any], runtime_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(graph_payload.get("metadata") or {})
    runtime_policy = dict(graph_payload.get("runtime_policy") or {})
    context_policy = dict(graph_payload.get("context_policy") or {})
    return {
        "graph_id": str(graph_payload.get("graph_id") or runtime_payload.get("graph_id") or ""),
        "graph_ref": str(graph_payload.get("graph_id") or runtime_payload.get("graph_ref") or runtime_payload.get("graph_id") or ""),
        "title": str(graph_payload.get("title") or ""),
        "coordination_mode": str(runtime_policy.get("coordination_mode") or metadata.get("coordination_mode") or "review_merge"),
        "coordinator_agent_id": str(runtime_payload.get("coordinator_agent_id") or runtime_policy.get("coordinator_agent_id") or "agent:0"),
        "domain_id": str(graph_payload.get("domain_id") or runtime_payload.get("domain_id") or ""),
        "agent_group_id": str(runtime_payload.get("agent_group_id") or runtime_policy.get("agent_group_id") or metadata.get("agent_group_id") or ""),
        "participant_agent_ids": list(runtime_policy.get("participant_agent_ids") or metadata.get("participant_agent_ids") or []),
        "topology_template_id": str(metadata.get("topology_template_id") or ""),
        "shared_context_policy": str(context_policy.get("shared_context_policy") or "explicit_refs_only"),
        "memory_sharing_policy": str(context_policy.get("memory_sharing_policy") or dict(graph_payload.get("working_memory_policy") or {}).get("memory_sharing_policy") or "isolated_by_default"),
        "handoff_policy": str(metadata.get("handoff_policy") or "filtered_handoff"),
        "conflict_resolution_policy": str(metadata.get("conflict_resolution_policy") or "coordinator_review"),
        "output_merge_policy": str(metadata.get("output_merge_policy") or runtime_policy.get("merge_policy") or "coordinator_final_merge"),
        "stop_conditions": list(metadata.get("stop_conditions") or []),
        "subtask_refs": list(runtime_payload.get("subtask_refs") or metadata.get("subtask_refs") or []),
        "graph_nodes": [dict(item) for item in list(runtime_payload.get("nodes") or graph_payload.get("nodes") or []) if isinstance(item, dict)],
        "graph_edges": [dict(item) for item in list(runtime_payload.get("edges") or graph_payload.get("edges") or []) if isinstance(item, dict)],
        "communication_modes": list(runtime_payload.get("communication_modes") or metadata.get("communication_modes") or []),
        "metadata": metadata,
    }
