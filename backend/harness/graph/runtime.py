from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun

from .models import GraphHarnessConfig, GraphRun, GraphRuntimeEnvelope, safe_id
from .scheduler_view import build_scheduler_view


@dataclass(frozen=True, slots=True)
class GraphRuntimeStart:
    task_run: TaskRun
    graph_run: GraphRun
    envelope: GraphRuntimeEnvelope
    events: tuple[dict[str, Any], ...] = ()


class GraphRuntime:
    """Static assembly layer for one graph run.

    GraphRuntime locks the published GraphHarnessConfig and creates the durable
    run records. It does not decide node readiness or execute agents.
    """

    def __init__(self, *, services: Any) -> None:
        self._services = services

    def start(
        self,
        *,
        session_id: str,
        task_id: str,
        graph_config: GraphHarnessConfig,
        initial_inputs: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> GraphRuntimeStart:
        if graph_config.status != "published":
            raise ValueError("GraphRuntime can only start a published GraphHarnessConfig")
        expected_hash = graph_config.expected_content_hash()
        if graph_config.content_hash and graph_config.content_hash != expected_hash:
            raise ValueError("GraphHarnessConfig content_hash mismatch")
        structure_hash = graph_config.expected_structural_hash()
        now = time.time()
        run_diagnostics = _strip_graph_environment_scope(dict(diagnostics or {}))
        graph_run_id = f"grun:{safe_id(graph_config.graph_id)}:{int(now * 1000)}"
        task_run_id = f"taskrun:{safe_id(graph_config.graph_id)}:{int(now * 1000)}"
        root_task_ref = task_id.strip() or graph_config.root_task_ref or graph_config.graph_id
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
            task_contract_ref=graph_config.root_task_ref,
            owner_agent_seat_id="graph",
            agent_id=str(dict(graph_config.agents or {}).get("coordinator_agent_id") or "agent:0"),
            agent_profile_id=str(dict(graph_config.agents or {}).get("coordinator_agent_profile_id") or "task_graph_coordinator"),
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                **run_diagnostics,
                "graph_run_id": graph_run_id,
                "graph_id": graph_config.graph_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
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
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": "graph_structure.v1",
                "config_snapshot_id": graph_config.config_id,
                "config_snapshot_hash": graph_config.content_hash,
                "session_scope": session_scope,
                "session_scope_key": _session_scope_key(session_scope),
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
                "authority": "harness.graph_runtime_envelope.file_scope",
            },
            memory_scope={
                "node_default_task_environment_id": graph_config.task_environment_id,
                "memory_space": memory_space,
                "graph_memory_policy": dict(graph_config.memory or {}),
                "runtime_scope": runtime_scope,
                "graph_task_memory_namespace": dict(runtime_scope.get("graph_task_memory_namespace") or {}),
                "memory_namespace_id": str(runtime_scope.get("memory_namespace_id") or ""),
                **_public_scope_fields(runtime_scope),
                "authority": "harness.graph_runtime_envelope.memory_scope",
            },
            sandbox_scope={
                **sandbox_policy,
                "node_default_task_environment_id": graph_config.task_environment_id,
                "artifact_policy": artifact_policy,
                "authority": "harness.graph_runtime_envelope.sandbox_scope",
            },
            created_at=now,
        )
        self._services.state_index.upsert_task_run(task_run)
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
                "graph_run": graph_run.to_dict(),
                "graph_runtime_envelope": envelope.to_dict(),
                "static_topology_view": static_topology_view,
                "contract_index": contract_index,
                "formal_memory_sync": memory_sync,
            },
            refs={
                "graph_run_ref": graph_run_id,
                "graph_harness_config_ref": graph_config.config_id,
            },
        )
        return GraphRuntimeStart(
            task_run=task_run,
            graph_run=graph_run,
            envelope=envelope,
            events=(start_event.to_dict(),),
        )

    def _sync_formal_memory_spec(self, *, graph_config: GraphHarnessConfig, task_run_id: str, runtime_scope: dict[str, Any]) -> dict[str, Any]:
        service = getattr(self._services, "formal_memory_service", None)
        if service is None:
            return {
                "synced": False,
                "reason": "formal_memory_service_unavailable",
                "authority": "harness.graph_runtime.formal_memory_sync",
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
            "authority": "harness.graph_runtime.formal_memory_sync",
        }


def _static_topology_view(graph_config: GraphHarnessConfig) -> dict[str, Any]:
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
        "authority": "harness.graph_runtime.static_topology_view",
    }


def _contract_index(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    contracts = dict(graph_config.contracts or {})
    return {
        "node_protocol_index": dict(contracts.get("node_protocol_index") or {}),
        "edge_protocol_index": dict(contracts.get("edge_protocol_index") or {}),
        "node_contract_index": dict(contracts.get("node_contract_index") or {}),
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
        "authority": "harness.graph_runtime.contract_index",
    }


def _state_machine_spec(*, graph_config: GraphHarnessConfig, static_topology_view: dict[str, Any]) -> dict[str, Any]:
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
        "authority": "harness.graph_runtime.state_machine_spec",
    }


def _loop_control_spec(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    return {
        "loop_frames": [dict(item) for item in graph_config.loop_frames],
        "batch_policy": dict(dict(graph_config.control or {}).get("batch_policy") or {}),
        "authority": "harness.graph_runtime.loop_control_spec",
    }


def _graph_run_origin(*, diagnostics: dict[str, Any], graph_config: GraphHarnessConfig) -> dict[str, str]:
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
    if source == "harness.task_graph_start_api":
        return {
            "origin_kind": "user_requested",
            "origin_authority": "harness.api.task_graph_run_start",
            "origin_ref": graph_config.root_task_ref or graph_config.graph_id,
            "parent_run_ref": "",
        }
    return {
        "origin_kind": "system_assigned",
        "origin_authority": "harness.graph_runtime",
        "origin_ref": graph_config.root_task_ref or graph_config.graph_id,
        "parent_run_ref": "",
    }


def _graph_runtime_scope(
    *,
    graph_config: GraphHarnessConfig,
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
        scope["workspace_view"] = "project"
        scope["graph_binding_mode"] = str(binding_contract.get("binding_mode") or "project_scoped")
        scope.setdefault("scope_source", "harness.graph_runtime.explicit_project_scope")
    elif scope_id:
        scope["scope_id"] = scope_id
        scope.setdefault("scope_source", "harness.graph_runtime.explicit_scope")
    else:
        scope["scope_source"] = "harness.graph_runtime.unscoped_graph_run"
    graph_task_memory_namespace = _graph_task_memory_namespace(
        graph_config=graph_config,
        graph_run_id=graph_run_id,
        task_run_id=task_run_id,
    )
    scope["graph_task_memory_namespace"] = graph_task_memory_namespace
    scope["memory_namespace_id"] = graph_task_memory_namespace["namespace_id"]
    scope["authority"] = "harness.graph_runtime.runtime_scope"
    return scope


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
    graph_config: GraphHarnessConfig,
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
        "authority": "harness.graph_runtime.graph_task_memory_namespace",
    }


def _format_namespace_template(template: str, *, graph_run_id: str, task_run_id: str) -> str:
    return template.format(
        graph_run_id=safe_id(graph_run_id),
        raw_graph_run_id=graph_run_id,
        task_run_id=safe_id(task_run_id),
        root_task_run_id=safe_id(task_run_id),
        raw_task_run_id=task_run_id,
        raw_root_task_run_id=task_run_id,
    )


def _public_scope_fields(runtime_scope: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("project_id", "scope_id"):
        value = str(dict(runtime_scope or {}).get(key) or "").strip()
        if value:
            result[key] = value
    return result


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
