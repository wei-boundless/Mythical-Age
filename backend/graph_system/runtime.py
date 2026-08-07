from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import RuntimeAnchor, TaskRun

from .models import ExecutableGraphConfig, GraphRun, GraphRuntimeEnvelope, safe_id
from .scheduler_view import build_scheduler_view


@dataclass(frozen=True, slots=True)
class GraphRuntimeStart:
    task_run: TaskRun
    runtime_anchor: RuntimeAnchor
    graph_run: GraphRun
    envelope: GraphRuntimeEnvelope
    events: tuple[dict[str, Any], ...] = ()


class GraphRuntime:
    """Static assembly layer for one graph run.

    GraphRuntime locks the published ExecutableGraphConfig and creates the durable
    run records. It does not decide node readiness or execute agents.
    """

    def __init__(self, *, services: Any) -> None:
        self._services = services

    def start(
        self,
        *,
        session_id: str,
        task_id: str,
        graph_config: ExecutableGraphConfig,
        initial_inputs: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> GraphRuntimeStart:
        if graph_config.status != "published":
            raise ValueError("GraphRuntime can only start a published ExecutableGraphConfig")
        expected_hash = graph_config.expected_content_hash()
        if graph_config.content_hash and graph_config.content_hash != expected_hash:
            raise ValueError("ExecutableGraphConfig content_hash mismatch")
        structure_hash = graph_config.expected_structural_hash()
        now = time.time()
        run_diagnostics = _strip_graph_environment_scope(dict(diagnostics or {}))
        graph_run_id = f"grun:{safe_id(graph_config.graph_id)}:{int(now * 1000)}"
        task_run_id = f"taskrun:{safe_id(graph_config.graph_id)}:{int(now * 1000)}"
        root_task_ref = task_id.strip() or graph_config.root_task_ref or graph_config.graph_id
        root_task_run_identity = _root_task_run_identity(task_run_id=task_run_id, root_task_ref=root_task_ref)
        origin = _graph_run_origin(diagnostics=dict(diagnostics or {}), graph_config=graph_config)
        runtime_scope = _graph_runtime_scope(
            graph_config=graph_config,
            graph_run_id=graph_run_id,
            task_run_id=task_run_id,
            initial_inputs=dict(initial_inputs or {}),
            diagnostics=dict(diagnostics or {}),
        )
        session_scope = _session_scope_from_runtime_scope(runtime_scope)
        task_run = TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=root_task_ref,
            task_run_contract_ref="",
            owner_agent_seat_id="graph",
            agent_id=str(dict(graph_config.agents or {}).get("coordinator_agent_id") or ""),
            agent_profile_id=str(dict(graph_config.agents or {}).get("coordinator_agent_profile_id") or ""),
            execution_runtime_kind="task_graph",
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                **run_diagnostics,
                "graph_run_id": graph_run_id,
                **root_task_run_identity,
                "graph_id": graph_config.graph_id,
                "graph_config_id": graph_config.config_id,
                "graph_config_hash": graph_config.content_hash,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": "graph_structure.v1",
                "config_snapshot_id": graph_config.config_id,
                "config_snapshot_hash": graph_config.content_hash,
                "session_scope": session_scope,
                "session_scope_key": _session_scope_key(session_scope),
                "runtime_scope": runtime_scope,
                **_public_scope_fields(runtime_scope),
                "origin": origin,
                **origin,
            },
        )
        runtime_anchor = RuntimeAnchor(
            runtime_anchor_id=f"rtanchor:{safe_id(graph_run_id)}",
            anchor_kind="graph_run",
            session_id=session_id,
            status="running",
            legacy_task_run_id=task_run_id,
            task_environment_id="",
            graph_run_id=graph_run_id,
            graph_config_id=graph_config.config_id,
            control_state="running",
            event_scope_ref=task_run_id,
            created_at=now,
            updated_at=now,
            diagnostics={
                "graph_id": graph_config.graph_id,
                "root_task_ref": root_task_ref,
                "legacy_runtime_anchor": "task_run_id",
                "authority": "graph_system_runtime.runtime_anchor",
            },
        )
        graph_run = GraphRun(
            graph_run_id=graph_run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            graph_id=graph_config.graph_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            structure_hash=structure_hash,
            structure_version="graph_structure.v1",
            config_snapshot_id=graph_config.config_id,
            config_snapshot_hash=graph_config.content_hash,
            workspace_view=session_scope["workspace_view"],
            task_environment_id="",
            project_id=session_scope["project_id"],
            session_scope_key=_session_scope_key(session_scope),
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                **run_diagnostics,
                "graph_config_id": graph_config.config_id,
                "graph_config_hash": graph_config.content_hash,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": "graph_structure.v1",
                "config_snapshot_id": graph_config.config_id,
                "config_snapshot_hash": graph_config.content_hash,
                "session_scope": session_scope,
                "session_scope_key": _session_scope_key(session_scope),
                **root_task_run_identity,
                "root_task_ref": graph_config.root_task_ref,
                "runtime_scope": runtime_scope,
                **_public_scope_fields(runtime_scope),
                "origin": origin,
                **origin,
            },
        )
        environment = dict(graph_config.environment or {})
        storage_space = dict(environment.get("storage_space") or {})
        file_access_tables = list(environment.get("file_access_tables") or [])
        memory_space = dict(environment.get("memory_space") or {})
        artifact_policy = dict(environment.get("artifact_policy") or {})
        sandbox_policy = dict(environment.get("sandbox_policy") or {})
        static_topology_view = _static_topology_view(graph_config)
        contract_index = _contract_index(graph_config)
        state_machine_spec = _state_machine_spec(graph_config=graph_config, static_topology_view=static_topology_view)
        loop_control_spec = _loop_control_spec(graph_config)
        envelope = GraphRuntimeEnvelope(
            envelope_id=f"grtenv:{safe_id(graph_run_id)}",
            graph_run_id=graph_run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            graph_id=graph_config.graph_id,
            structure_hash=structure_hash,
            structure_version="graph_structure.v1",
            config_snapshot_id=graph_config.config_id,
            config_snapshot_hash=graph_config.content_hash,
            initial_inputs=dict(initial_inputs or {}),
            static_topology_view=static_topology_view,
            contract_index=contract_index,
            state_machine_spec=state_machine_spec,
            loop_control_spec=loop_control_spec,
            runtime_services_ref="single_agent_runtime_host",
            permission_scope=dict(graph_config.permissions or {}),
            file_scope={
                "node_default_task_environment_id": graph_config.task_environment_id,
                "storage_space": storage_space,
                "file_management": dict(environment.get("file_management") or {}),
                "file_access_tables": file_access_tables,
                "graph_resource_policy": dict(graph_config.resources or {}),
                "authority": "graph_system_runtime_envelope.file_scope",
            },
            memory_scope={
                "node_default_task_environment_id": graph_config.task_environment_id,
                "memory_space": memory_space,
                "graph_memory_policy": dict(graph_config.memory or {}),
                "runtime_scope": runtime_scope,
                "graph_task_memory_namespace": dict(runtime_scope.get("graph_task_memory_namespace") or {}),
                "memory_namespace_id": str(runtime_scope.get("memory_namespace_id") or ""),
                **_public_scope_fields(runtime_scope),
                "authority": "graph_system_runtime_envelope.memory_scope",
            },
            sandbox_scope={
                **sandbox_policy,
                "node_default_task_environment_id": graph_config.task_environment_id,
                "artifact_policy": artifact_policy,
                "authority": "graph_system_runtime_envelope.sandbox_scope",
            },
            created_at=now,
        )
        self._services.state_index.upsert_task_run(task_run)
        upsert_runtime_anchor = getattr(self._services.state_index, "upsert_runtime_anchor", None)
        if callable(upsert_runtime_anchor):
            upsert_runtime_anchor(runtime_anchor)
        self._services.runtime_objects.put_object("graph_run", safe_id(graph_run_id), graph_run.to_dict())
        memory_sync = self._sync_formal_memory_spec(
            graph_config=graph_config,
            task_run_id=task_run.task_run_id,
            runtime_scope=runtime_scope,
        )
        start_event = self._services.event_log.append(
            task_run.task_run_id,
            "graph_run_created",
            payload={
                "graph_run_id": graph_run_id,
                "runtime_anchor_id": runtime_anchor.runtime_anchor_id,
                "graph_run": graph_run.to_dict(),
                "runtime_anchor": runtime_anchor.to_dict(),
                "graph_runtime_envelope": _runtime_envelope_event_view(envelope),
                "static_topology_view": _static_topology_event_view(static_topology_view),
                "contract_index": _contract_index_event_view(contract_index),
                "formal_memory_sync": _formal_memory_sync_event_view(memory_sync),
            },
            refs={
                "graph_run_ref": graph_run_id,
                "runtime_anchor_ref": runtime_anchor.runtime_anchor_id,
                "graph_config_ref": graph_config.config_id,
            },
        )
        return GraphRuntimeStart(
            task_run=task_run,
            runtime_anchor=runtime_anchor,
            graph_run=graph_run,
            envelope=envelope,
            events=(start_event.to_dict(),),
        )

    def _sync_formal_memory_spec(self, *, graph_config: ExecutableGraphConfig, task_run_id: str, runtime_scope: dict[str, Any]) -> dict[str, Any]:
        service = getattr(self._services, "formal_memory_service", None)
        if service is None:
            return {
                "synced": False,
                "reason": "formal_memory_service_unavailable",
                "authority": "graph_system_runtime.formal_memory_sync",
            }
        graph_spec = {
            "graph_id": graph_config.graph_id,
            "nodes": [dict(item) for item in graph_config.nodes],
            "resource_nodes": [dict(item) for item in list(dict(graph_config.resources or {}).get("resource_nodes") or []) if isinstance(item, dict)],
        }
        result = service.sync_graph_spec_for_scope(
            graph_id=graph_config.graph_id,
            graph_spec=graph_spec,
            task_run_id=task_run_id,
            runtime_scope=runtime_scope,
        )
        return {
            **dict(result or {}),
            "synced": True,
            "authority": "graph_system_runtime.formal_memory_sync",
        }


def _static_topology_view(graph_config: ExecutableGraphConfig) -> dict[str, Any]:
    scheduler = build_scheduler_view(graph_config)
    inbound: dict[str, list[str]] = {}
    outbound: dict[str, list[str]] = {}
    edge_index: dict[str, dict[str, Any]] = {}
    node_index = {
        str(node.get("node_id") or ""): {
            "node_id": str(node.get("node_id") or ""),
            "node_type": str(node.get("node_type") or ""),
            "node_class": str(node.get("node_class") or ""),
            "executor_type": str(dict(node.get("executor") or {}).get("executor_type") or "agent"),
        }
        for node in graph_config.nodes
        if str(node.get("node_id") or "")
    }
    for edge in graph_config.edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        outbound.setdefault(source, []).append(edge_id)
        inbound.setdefault(target, []).append(edge_id)
        edge_index[edge_id] = {
            "edge_id": edge_id,
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": str(edge.get("edge_type") or ""),
            "scheduler_role": str(edge.get("scheduler_role") or ""),
            "semantic_role": str(edge.get("semantic_role") or ""),
        }
    return {
        "node_index": node_index,
        "edge_index": edge_index,
        "inbound_edges_by_node": inbound,
        "outbound_edges_by_node": outbound,
        "start_node_ids": list(scheduler.start_node_ids),
        "terminal_node_ids": list(scheduler.terminal_node_ids),
        "executable_node_ids": list(scheduler.executable_node_ids),
        "dependency_edge_ids": [str(edge.get("edge_id") or "") for edge in scheduler.dependency_edges],
        "authority": "graph_system_runtime.static_topology_view",
    }


def _runtime_envelope_event_view(envelope: GraphRuntimeEnvelope) -> dict[str, Any]:
    memory_scope = dict(envelope.memory_scope or {})
    return {
        "envelope_id": envelope.envelope_id,
        "graph_run_id": envelope.graph_run_id,
        "task_run_id": envelope.task_run_id,
        "root_task_run_id": envelope.task_run_id,
        "graph_root_task_run_id": envelope.task_run_id,
        "session_id": envelope.session_id,
        "config_id": envelope.config_id,
        "config_hash": envelope.config_hash,
        "graph_id": envelope.graph_id,
        "structure_hash": envelope.structure_hash,
        "structure_version": envelope.structure_version,
        "config_snapshot_id": envelope.config_snapshot_id,
        "config_snapshot_hash": envelope.config_snapshot_hash,
        "initial_input_keys": sorted(str(key) for key in dict(envelope.initial_inputs or {}).keys()),
        "initial_input_count": len(dict(envelope.initial_inputs or {})),
        "static_topology_view": _static_topology_event_view(envelope.static_topology_view),
        "contract_index": _contract_index_event_view(envelope.contract_index),
        "state_machine_spec": dict(envelope.state_machine_spec or {}),
        "loop_control_spec": _loop_control_event_view(envelope.loop_control_spec),
        "runtime_services_ref": envelope.runtime_services_ref,
        "permission_scope_summary": _mapping_summary(envelope.permission_scope),
        "file_scope_summary": _file_scope_event_view(envelope.file_scope),
        "memory_scope_summary": _memory_scope_event_view(memory_scope),
        "sandbox_scope_summary": _mapping_summary(envelope.sandbox_scope),
        "memory_namespace_id": str(memory_scope.get("memory_namespace_id") or ""),
        "created_at": envelope.created_at,
        "authority": "graph_system_runtime_envelope.event_view",
    }


def _static_topology_event_view(view: dict[str, Any]) -> dict[str, Any]:
    payload = dict(view or {})
    return {
        "node_count": len(dict(payload.get("node_index") or {})),
        "edge_count": len(dict(payload.get("edge_index") or {})),
        "inbound_index_count": len(dict(payload.get("inbound_edges_by_node") or {})),
        "outbound_index_count": len(dict(payload.get("outbound_edges_by_node") or {})),
        "dependency_edge_count": len(list(payload.get("dependency_edge_ids") or [])),
        "executable_node_count": len(list(payload.get("executable_node_ids") or [])),
        "start_node_ids": list(payload.get("start_node_ids") or []),
        "terminal_node_ids": list(payload.get("terminal_node_ids") or []),
        "authority": "graph_system_runtime.static_topology_event_view",
    }


def _contract_index_event_view(index: dict[str, Any]) -> dict[str, Any]:
    payload = dict(index or {})
    deployment_package = dict(payload.get("deployment_package") or {})
    compile_report = dict(payload.get("compile_report") or {})
    return {
        "node_contract_count": len(dict(payload.get("node_contract_index") or {})),
        "node_task_contract_count": len(dict(payload.get("node_task_contract_index") or {})),
        "node_agent_binding_count": len(dict(payload.get("node_agent_binding_index") or {})),
        "resource_contract_count": len(dict(payload.get("resource_contract_index") or {})),
        "edge_contract_count": len(dict(payload.get("edge_contract_index") or {})),
        "node_contract_manifest_count": len(list(payload.get("node_contracts") or [])),
        "edge_contract_manifest_count": len(list(payload.get("edge_contracts") or [])),
        "runtime_contract_count": len(list(payload.get("runtime_contracts") or [])),
        "acceptance_contract_count": len(list(payload.get("acceptance_contracts") or [])),
        "system_node_contract_count": len(dict(payload.get("system_node_contract_index") or {})),
        "deployment_package_id": str(deployment_package.get("package_id") or ""),
        "deployment_required_resource_count": len(list(deployment_package.get("required_resources") or [])),
        "compile_report": _compile_report_event_view(compile_report),
        "authority": "graph_system_runtime.contract_index_event_view",
    }


def _compile_report_event_view(report: dict[str, Any]) -> dict[str, Any]:
    payload = dict(report or {})
    return {
        "status": str(payload.get("status") or ""),
        "issue_count": len(list(payload.get("issues") or [])),
        "warning_count": len(list(payload.get("warnings") or [])),
        "node_count": int(payload.get("node_count") or 0),
        "edge_count": int(payload.get("edge_count") or 0),
        "resource_count": int(payload.get("resource_count") or 0),
        "authority": "graph_system_runtime.compile_report_event_view",
    }


def _loop_control_event_view(spec: dict[str, Any]) -> dict[str, Any]:
    payload = dict(spec or {})
    return {
        "loop_frame_count": len(list(payload.get("loop_frames") or [])),
        "has_runtime_settings": bool(payload.get("runtime_settings")),
        "control_keys": sorted(str(key) for key in payload.keys()),
        "authority": "graph_system_runtime.loop_control_event_view",
    }


def _file_scope_event_view(scope: dict[str, Any]) -> dict[str, Any]:
    payload = dict(scope or {})
    storage_space = dict(payload.get("storage_space") or {})
    graph_resource_policy = dict(payload.get("graph_resource_policy") or {})
    return {
        "node_default_task_environment_id": str(payload.get("node_default_task_environment_id") or ""),
        "storage_namespace": str(storage_space.get("storage_namespace") or ""),
        "workspace_root_present": bool(storage_space.get("workspace_root")),
        "file_access_table_count": len(list(payload.get("file_access_tables") or [])),
        "resource_node_count": len(list(graph_resource_policy.get("resource_nodes") or [])),
        "authority": "graph_system_runtime.file_scope_event_view",
    }


def _memory_scope_event_view(scope: dict[str, Any]) -> dict[str, Any]:
    payload = dict(scope or {})
    policy = dict(payload.get("graph_memory_policy") or {})
    namespace = dict(payload.get("graph_task_memory_namespace") or {})
    return {
        "node_default_task_environment_id": str(payload.get("node_default_task_environment_id") or ""),
        "memory_namespace_id": str(payload.get("memory_namespace_id") or ""),
        "graph_task_memory_namespace": {
            "namespace_id": str(namespace.get("namespace_id") or ""),
            "scope_kind": str(namespace.get("scope_kind") or ""),
            "isolation": str(namespace.get("isolation") or ""),
        },
        "working_memory_policy_profile_id": str(policy.get("working_memory_policy_profile_id") or ""),
        "memory_read_rule_count": len(list(policy.get("read_rules") or [])),
        "memory_matrix_key_count": len(dict(policy.get("memory_matrix") or {})),
        "authority": "graph_system_runtime.memory_scope_event_view",
    }


def _formal_memory_sync_event_view(sync: dict[str, Any]) -> dict[str, Any]:
    payload = dict(sync or {})
    return {
        "synced": bool(payload.get("synced") is True),
        "reason": str(payload.get("reason") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "repository_count": int(payload.get("repository_count") or len(list(payload.get("repositories") or []))),
        "collection_count": int(payload.get("collection_count") or len(list(payload.get("collections") or []))),
        "authority": "graph_system_runtime.formal_memory_sync_event_view",
    }


def _mapping_summary(value: dict[str, Any]) -> dict[str, Any]:
    payload = dict(value or {})
    return {
        "key_count": len(payload),
        "keys": sorted(str(key) for key in payload.keys()),
        "authority": "graph_system_runtime.mapping_event_view",
    }


def _contract_index(graph_config: ExecutableGraphConfig) -> dict[str, Any]:
    contracts = dict(graph_config.contracts or {})
    return {
        "node_contract_index": dict(contracts.get("node_contract_index") or {}),
        "node_task_contract_index": dict(contracts.get("node_task_contract_index") or {}),
        "node_agent_binding_index": dict(contracts.get("node_agent_binding_index") or {}),
        "resource_contract_index": dict(contracts.get("resource_contract_index") or {}),
        "edge_contract_index": dict(contracts.get("edge_contract_index") or {}),
        "compile_report": dict(contracts.get("compile_report") or {}),
        "deployment_package": dict(contracts.get("deployment_package") or {}),
        "graph_binding_contract": dict(contracts.get("graph_binding_contract") or {}),
        "maintenance_contract": dict(contracts.get("maintenance_contract") or {}),
        "system_node_contract_index": dict(contracts.get("system_node_contract_index") or {}),
        "configurator_write_contract": dict(contracts.get("configurator_write_contract") or {}),
        "node_contracts": list(contracts.get("node_contracts") or []),
        "edge_contracts": list(contracts.get("edge_contracts") or []),
        "runtime_contracts": list(contracts.get("runtime_contracts") or []),
        "acceptance_contracts": list(contracts.get("acceptance_contracts") or []),
        "authority": "graph_system_runtime.contract_index",
    }


def _state_machine_spec(*, graph_config: ExecutableGraphConfig, static_topology_view: dict[str, Any]) -> dict[str, Any]:
    control = dict(graph_config.control or {})
    return {
        "start_node_ids": list(static_topology_view.get("start_node_ids") or []),
        "terminal_node_ids": list(static_topology_view.get("terminal_node_ids") or []),
        "dependency_edge_ids": list(static_topology_view.get("dependency_edge_ids") or []),
        "scheduling_policy": dict(control.get("scheduling_policy") or {}),
        "failure_policy": dict(control.get("failure_policy") or {}),
        "checkpoint_policy": dict(control.get("checkpoint_policy") or {}),
        "resume_policy": dict(control.get("resume_policy") or {}),
        "human_gate_policy": dict(control.get("human_gate_policy") or {}),
        "authority": "graph_system_runtime.state_machine_spec",
    }


def _loop_control_spec(graph_config: ExecutableGraphConfig) -> dict[str, Any]:
    return {
        "loop_frames": [dict(item) for item in graph_config.loop_frames],
        "batch_policy": dict(dict(graph_config.control or {}).get("batch_policy") or {}),
        "authority": "graph_system_runtime.loop_control_spec",
    }


def _graph_run_origin(*, diagnostics: dict[str, Any], graph_config: ExecutableGraphConfig) -> dict[str, str]:
    engagement_run_ref = str(diagnostics.get("engagement_run_ref") or "").strip()
    engagement_contract_ref = str(diagnostics.get("engagement_contract_ref") or "").strip()
    if engagement_run_ref or engagement_contract_ref:
        return {
            "origin_kind": "engagement_assigned",
            "origin_authority": "task_system.engagement",
            "origin_ref": engagement_contract_ref or engagement_run_ref,
            "parent_run_ref": engagement_run_ref,
        }
    source = str(diagnostics.get("source") or "").strip()
    if source == "graph_system.task_graph_start_api":
        return {
            "origin_kind": "user_requested",
            "origin_authority": "graph_system.api.task_graph_run_start",
            "origin_ref": graph_config.root_task_ref or graph_config.graph_id,
            "parent_run_ref": "",
        }
    return {
        "origin_kind": "system_assigned",
        "origin_authority": "graph_system_runtime",
        "origin_ref": graph_config.root_task_ref or graph_config.graph_id,
        "parent_run_ref": "",
    }


def _graph_runtime_scope(
    *,
    graph_config: ExecutableGraphConfig,
    graph_run_id: str,
    task_run_id: str,
    initial_inputs: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    binding_contract = dict(dict(graph_config.contracts or {}).get("graph_binding_contract") or dict(graph_config.control or {}).get("graph_binding") or environment.get("graph_binding") or {})
    initial_runtime_scope = dict(initial_inputs.get("runtime_scope") or {})
    diagnostic_runtime_scope = dict(diagnostics.get("runtime_scope") or {})
    for payload in (initial_runtime_scope, diagnostic_runtime_scope):
        payload.pop("task_environment_id", None)
        payload.pop("environment_id", None)
    scope = {
        **diagnostic_runtime_scope,
        **initial_runtime_scope,
        "graph_id": str(graph_config.graph_id or ""),
        "graph_run_id": str(graph_run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "root_task_run_id": str(task_run_id or ""),
        "graph_root_task_run_id": str(task_run_id or ""),
    }
    project_id = _first_scope_value(
        binding_contract.get("project_id"),
        scope.get("project_id"),
        diagnostics.get("project_id"),
        initial_inputs.get("project_id"),
        initial_inputs.get("project_ref"),
        initial_inputs.get("workspace_project_id"),
    )
    scope_id = _first_scope_value(
        scope.get("scope_id"),
        diagnostics.get("scope_id"),
        initial_inputs.get("scope_id"),
    )
    if project_id:
        scope["project_id"] = project_id
        scope["workspace_view"] = "graph_task"
        scope["graph_binding_mode"] = str(binding_contract.get("binding_mode") or "project_scoped")
        scope.setdefault("scope_source", "graph_system_runtime.explicit_project_scope")
    elif scope_id:
        scope["scope_id"] = scope_id
        scope.setdefault("scope_source", "graph_system_runtime.explicit_scope")
    else:
        scope["scope_source"] = "graph_system_runtime.unscoped_graph_run"
    project_path = _first_scope_value(
        scope.get("project_path"),
        diagnostics.get("project_path"),
        initial_inputs.get("project_path"),
    )
    artifact_root = _first_scope_value(
        scope.get("artifact_root"),
        diagnostics.get("artifact_root"),
        initial_inputs.get("artifact_root"),
    )
    if project_path:
        scope["project_path"] = _normalize_logical_root(project_path)
    if artifact_root:
        scope["artifact_root"] = _normalize_logical_root(artifact_root)
    elif project_path:
        scope["artifact_root"] = f"{_normalize_logical_root(project_path)}/artifacts"
    else:
        scope["artifact_root"] = _graph_task_artifact_root(graph_run_id=graph_run_id, graph_task_instance_id=scope.get("graph_task_instance_id") or project_id)
    graph_task_memory_namespace = _graph_task_memory_namespace(
        graph_config=graph_config,
        graph_run_id=graph_run_id,
        task_run_id=task_run_id,
    )
    scope["graph_task_memory_namespace"] = graph_task_memory_namespace
    scope["memory_namespace_id"] = graph_task_memory_namespace["namespace_id"]
    scope["authority"] = "graph_system_runtime.runtime_scope"
    return scope


def _graph_task_artifact_root(*, graph_run_id: str, graph_task_instance_id: str = "") -> str:
    instance_id = str(graph_task_instance_id or "").strip()
    if instance_id:
        return f"storage/graph_task_instances/{safe_id(instance_id)}/runs/{safe_id(graph_run_id)}/artifacts"
    return f"output/graph_runs/{safe_id(graph_run_id)}/artifacts"


def _normalize_logical_root(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip().strip("'\"`").strip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def _strip_graph_environment_scope(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload or {})
    result.pop("task_environment_id", None)
    result.pop("environment_id", None)
    runtime_scope = dict(result.get("runtime_scope") or {})
    runtime_scope.pop("task_environment_id", None)
    runtime_scope.pop("environment_id", None)
    if runtime_scope:
        result["runtime_scope"] = runtime_scope
    else:
        result.pop("runtime_scope", None)
    session_scope = dict(result.get("session_scope") or {})
    session_scope.pop("task_environment_id", None)
    session_scope.pop("environment_id", None)
    if session_scope:
        result["session_scope"] = session_scope
    else:
        result.pop("session_scope", None)
    return result


def _graph_task_memory_namespace(
    *,
    graph_config: ExecutableGraphConfig,
    graph_run_id: str,
    task_run_id: str,
) -> dict[str, Any]:
    policy = dict(dict(graph_config.memory or {}).get("graph_task_memory_namespace") or {})
    raw_namespace = str(policy.get("namespace_id") or "").strip()
    namespace_template = str(policy.get("namespace_template") or policy.get("namespace_id_template") or "").strip()
    shared = bool(policy.get("shared") is True) or str(policy.get("isolation") or policy.get("scope_kind") or "") in {
        "explicit_shared",
        "durable_shared",
    }
    if namespace_template:
        namespace_id = _format_namespace_template(namespace_template, graph_run_id=graph_run_id, task_run_id=task_run_id)
        source = "graph_config_namespace_template"
    elif raw_namespace and ("{graph_run_id}" in raw_namespace or "{root_task_run_id}" in raw_namespace or "{task_run_id}" in raw_namespace):
        namespace_id = _format_namespace_template(raw_namespace, graph_run_id=graph_run_id, task_run_id=task_run_id)
        source = "graph_config_namespace_template"
    elif raw_namespace and shared:
        namespace_id = raw_namespace
        source = "graph_config_explicit_shared_namespace"
    else:
        namespace_id = f"graphmem:{safe_id(graph_run_id)}"
        source = "graph_runtime_default_graph_run_namespace"
    return {
        "namespace_id": namespace_id,
        "scope_kind": "graph_task_instance" if not shared else "explicit_shared",
        "isolation": "per_graph_run" if not shared else "explicit_shared",
        "source": source,
        "graph_run_id": graph_run_id,
        "root_task_run_id": task_run_id,
        "graph_root_task_run_id": task_run_id,
        "authority": "graph_system_runtime.graph_task_memory_namespace",
    }


def _format_namespace_template(template: str, *, graph_run_id: str, task_run_id: str) -> str:
    return template.format(
        graph_run_id=safe_id(graph_run_id),
        raw_graph_run_id=graph_run_id,
        task_run_id=safe_id(task_run_id),
        root_task_run_id=safe_id(task_run_id),
        graph_root_task_run_id=safe_id(task_run_id),
        raw_task_run_id=task_run_id,
        raw_root_task_run_id=task_run_id,
        raw_graph_root_task_run_id=task_run_id,
    )


def _public_scope_fields(runtime_scope: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("project_id", "scope_id", "graph_task_instance_id"):
        value = str(dict(runtime_scope or {}).get(key) or "").strip()
        if value:
            result[key] = value
    return result


def _root_task_run_identity(*, task_run_id: str, root_task_ref: str) -> dict[str, str]:
    root_id = str(task_run_id or "").strip()
    return {
        "root_task_run_id": root_id,
        "graph_root_task_run_id": root_id,
        "graph_root_task_ref": str(root_task_ref or "").strip(),
        "root_task_run_authority": "graph_system_runtime.root_task_run_anchor",
    }


def _session_scope_from_runtime_scope(runtime_scope: dict[str, Any]) -> dict[str, str]:
    return {
        "workspace_view": str(dict(runtime_scope or {}).get("workspace_view") or "graph").strip() or "graph",
        "task_environment_id": "",
        "project_id": str(dict(runtime_scope or {}).get("project_id") or "").strip(),
    }


def _session_scope_key(scope: dict[str, Any]) -> str:
    return "|".join(
        [
            str(dict(scope or {}).get("workspace_view") or "chat").strip() or "chat",
            str(dict(scope or {}).get("task_environment_id") or "").strip(),
            str(dict(scope or {}).get("project_id") or "").strip(),
        ]
    )


def _first_scope_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
