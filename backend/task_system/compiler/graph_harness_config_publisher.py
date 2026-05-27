from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from harness.runtime.graph_config import GraphHarnessConfig, build_graph_harness_config_from_runtime_spec
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
) -> GraphHarnessConfig:
    registry = TaskFlowRegistry(base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise ValueError(f"TaskGraph not found: {graph_id}")
    if graph.publish_state != "published":
        raise ValueError(f"TaskGraph must be published before GraphHarnessConfig publication: {graph_id}")
    visited = set(_visited or set())
    if graph.graph_id in visited:
        raise ValueError(f"Graph module cycle detected while publishing GraphHarnessConfig: {graph.graph_id}")
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
    blocking_issues = [issue.to_dict() for issue in runtime_spec.issues if issue.severity == "error"]
    if blocking_issues:
        raise ValueError(f"GraphHarnessConfig publication blocked by runtime issues: {blocking_issues}")

    linked_config_ids: dict[str, str] = {}
    for plan in getattr(runtime_spec, "graph_module_runtime_plans", ()) or ():
        linked_graph_id = str(getattr(plan, "linked_graph_id", "") or "").strip()
        if not linked_graph_id:
            continue
        linked_config = publish_graph_harness_config_for_graph(
            base_dir=base_dir,
            graph_id=linked_graph_id,
            publish_version=publish_version,
            _visited=set(visited),
        )
        linked_config_ids[linked_graph_id] = linked_config.config_id

    contract_registry = TaskContractRegistry(base_dir)
    agent_profiles = tuple(
        profile
        for profile in (
            AgentRuntimeRegistry(base_dir).get_profile(str(node.agent_id or "").strip())
            for node in runtime_spec.nodes
            if str(node.agent_id or "").strip()
        )
        if profile is not None
    )
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=registry.derive_coordination_task_view_from_graph(graph),
        graph_spec=runtime_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    if not manifest.valid:
        raise ValueError(f"GraphHarnessConfig publication blocked by contract manifest issues: {[item.to_dict() for item in manifest.issues]}")
    config = build_graph_harness_config_from_runtime_spec(
        graph=graph,
        runtime_spec=runtime_spec,
        contract_manifest=manifest.to_dict(),
        publish_version=publish_version,
        linked_module_config_ids=linked_config_ids,
    )
    registry.upsert_graph_harness_config(config)
    return config
