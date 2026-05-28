from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from runtime.shared.models import CoordinationRun, TaskRun

from .models import GraphHarnessConfig, GraphRuntimeEnvelope, safe_id


@dataclass(frozen=True, slots=True)
class GraphRuntimeStart:
    task_run: TaskRun
    coordination_run: CoordinationRun
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
        task_run = TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=root_task_ref,
            task_contract_ref=graph_config.root_task_ref,
            owner_agent_seat_id="graph",
            agent_id=str(dict(graph_config.agents or {}).get("coordinator_agent_id") or "agent:0"),
            agent_profile_id=str(dict(graph_config.agents or {}).get("coordinator_agent_profile_id") or "task_graph_coordinator"),
            runtime_lane=str(dict(graph_config.agents or {}).get("runtime_lane") or "task_graph"),
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                "graph_run_id": graph_run_id,
                "graph_id": graph_config.graph_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "task_environment_id": graph_config.task_environment_id,
                **dict(diagnostics or {}),
            },
        )
        coordination_run = CoordinationRun(
            coordination_run_id=graph_run_id,
            task_run_id=task_run_id,
            coordinator_agent_id=str(dict(graph_config.agents or {}).get("coordinator_agent_id") or "agent:0"),
            graph_ref=graph_config.graph_id,
            topology_template_id="",
            communication_protocol_id=str(dict(graph_config.control or {}).get("communication_protocol_id") or ""),
            handoff_policy=str(dict(graph_config.control or {}).get("handoff_policy") or ""),
            failure_policy=str(dict(dict(graph_config.control or {}).get("failure_policy") or {}).get("mode") or ""),
            merge_policy=str(dict(graph_config.control or {}).get("merge_policy") or ""),
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                "graph_run_id": graph_run_id,
                "graph_harness_config_id": graph_config.config_id,
                "graph_harness_config_hash": graph_config.content_hash,
                "task_environment_id": graph_config.task_environment_id,
            },
        )
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
            file_scope=dict(graph_config.resources or {}),
            memory_scope=dict(graph_config.memory or {}),
            sandbox_scope=dict(dict(graph_config.permissions or {}).get("sandbox") or {}),
            created_at=now,
        )
        self._services.state_index.upsert_task_run(task_run)
        self._services.state_index.upsert_coordination_run(coordination_run)
        start_event = self._services.event_log.append(
            task_run.task_run_id,
            "coordination_run_created",
            payload={
                "graph_run_id": graph_run_id,
                "graph_runtime_envelope": envelope.to_dict(),
            },
            refs={
                "graph_run_ref": graph_run_id,
                "graph_harness_config_ref": graph_config.config_id,
            },
        )
        return GraphRuntimeStart(
            task_run=task_run,
            coordination_run=coordination_run,
            envelope=envelope,
            events=(start_event.to_dict(),),
        )

