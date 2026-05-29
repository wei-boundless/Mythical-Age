from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import TaskRun

from .models import GraphHarnessConfig, GraphRun, GraphRuntimeEnvelope, safe_id


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
        now = time.time()
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
                **dict(diagnostics or {}),
                "graph_run_id": graph_run_id,
                "graph_id": graph_config.graph_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "task_environment_id": graph_config.task_environment_id,
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
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                **dict(diagnostics or {}),
                "task_environment_id": graph_config.task_environment_id,
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
        envelope = GraphRuntimeEnvelope(
            envelope_id=f"grtenv:{safe_id(graph_run_id)}",
            graph_run_id=graph_run_id,
            task_run_id=task_run_id,
            session_id=session_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            graph_id=graph_config.graph_id,
            initial_inputs=dict(initial_inputs or {}),
            runtime_services_ref="single_agent_runtime_host",
            permission_scope=dict(graph_config.permissions or {}),
            file_scope={
                "task_environment_id": graph_config.task_environment_id,
                "storage_space": storage_space,
                "file_management": dict(environment.get("file_management") or {}),
                "file_access_tables": file_access_tables,
                "graph_resource_policy": dict(graph_config.resources or {}),
                "authority": "harness.graph_runtime_envelope.file_scope",
            },
            memory_scope={
                "task_environment_id": graph_config.task_environment_id,
                "memory_space": memory_space,
                "graph_memory_policy": dict(graph_config.memory or {}),
                "runtime_scope": runtime_scope,
                **_public_scope_fields(runtime_scope),
                "authority": "harness.graph_runtime_envelope.memory_scope",
            },
            sandbox_scope={
                **sandbox_policy,
                "task_environment_id": graph_config.task_environment_id,
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
    initial_runtime_scope = dict(initial_inputs.get("runtime_scope") or {})
    diagnostic_runtime_scope = dict(diagnostics.get("runtime_scope") or {})
    scope = {
        **dict(environment.get("runtime_scope") or {}),
        **diagnostic_runtime_scope,
        **initial_runtime_scope,
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "graph_id": str(graph_config.graph_id or ""),
        "graph_run_id": str(graph_run_id or ""),
        "task_run_id": str(task_run_id or ""),
    }
    project_id = _first_scope_value(
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
        scope.setdefault("scope_source", "harness.graph_runtime.explicit_project_scope")
    elif scope_id:
        scope["scope_id"] = scope_id
        scope.setdefault("scope_source", "harness.graph_runtime.explicit_scope")
    else:
        scope["project_id"] = f"graphrun.{safe_id(graph_run_id)}"
        scope["scope_source"] = "harness.graph_runtime.generated_graph_run_project_scope"
    scope["authority"] = "harness.graph_runtime.runtime_scope"
    return scope


def _public_scope_fields(runtime_scope: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("project_id", "scope_id"):
        value = str(dict(runtime_scope or {}).get(key) or "").strip()
        if value:
            result[key] = value
    return result


def _first_scope_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
