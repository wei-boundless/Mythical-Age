from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .delegation_models import AgentDelegationRequest
from .event_log import RuntimeEventLog
from .models import AgentHandoffEnvelope, AgentRun, CoordinationNodeRun, CoordinationRun
from .state_index import RuntimeStateIndex


def build_delegation_graph_payload(request: AgentDelegationRequest) -> dict[str, Any]:
    target_suffix = request.target_agent_id.replace(":", "_")
    return {
        "graph_source": "delegation_graph",
        "graph_id": f"graph.delegation:{request.request_id}",
        "coordinator_agent_id": request.source_agent_id,
        "nodes": [
            {
                "node_id": "coordinator",
                "node_type": "coordinator",
                "agent_id": request.source_agent_id,
                "role": "coordinator",
                "timeline_order": 0,
            },
            {
                "node_id": f"delegate_{target_suffix}",
                "node_type": "delegated_agent",
                "agent_id": request.target_agent_id,
                "role": "worker_participant",
                "timeline_order": 1,
                "delegation_request_ref": request.request_id,
            },
            {
                "node_id": "parent_observation",
                "node_type": "merge_observation",
                "agent_id": request.source_agent_id,
                "role": "coordinator",
                "timeline_order": 2,
            },
        ],
        "edges": [
            {
                "edge_id": "delegate_request",
                "source_node_id": "coordinator",
                "target_node_id": f"delegate_{target_suffix}",
                "message_type": "delegate/request",
                "handoff_policy": "structured_packet",
            },
            {
                "edge_id": "delegate_result",
                "source_node_id": f"delegate_{target_suffix}",
                "target_node_id": "parent_observation",
                "message_type": "delegate/result",
                "handoff_policy": "summary_and_refs_only",
            },
        ],
        "timeline_policy": {
            "mode": "sequence",
            "join_policy": "single_success",
            "failure_policy": "return_failed_observation",
        },
    }


class DelegationGraphAdapter:
    def __init__(self, root_dir: Path, *, state_index: RuntimeStateIndex | None = None, event_log: RuntimeEventLog | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.state_index = state_index or RuntimeStateIndex(self.root_dir)
        self.event_log = event_log or RuntimeEventLog(self.root_dir)

    def create_runtime_objects(
        self,
        *,
        request: AgentDelegationRequest,
        parent_agent_run: AgentRun,
        child_agent_run: AgentRun,
    ) -> tuple[CoordinationRun, tuple[CoordinationNodeRun, ...], tuple[AgentHandoffEnvelope, ...], tuple[Any, ...]]:
        now = time.time()
        graph_payload = build_delegation_graph_payload(request)
        coordination_run = CoordinationRun(
            coordination_run_id=f"coordrun:{request.request_id}",
            task_run_id=request.task_run_id,
            graph_ref=str(graph_payload["graph_id"]),
            coordinator_agent_id=request.source_agent_id,
            handoff_policy="summary_and_refs_only",
            failure_policy="return_failed_observation",
            merge_policy="parent_final_observation",
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                "graph_source": "delegation_graph",
                "delegation_request_ref": request.request_id,
                "delegation_graph": graph_payload,
            },
        )
        self.state_index.upsert_coordination_run(coordination_run)
        events: list[Any] = [
            self.event_log.append(
                request.task_run_id,
                "coordination_run_created",
                payload={"coordination_run": coordination_run.to_dict()},
                refs={"coordination_run_ref": coordination_run.coordination_run_id, "delegation_request_ref": request.request_id},
            )
        ]
        child_node_id = str(graph_payload["nodes"][1]["node_id"])
        node_runs = (
            CoordinationNodeRun(
                node_run_id=f"coordnode:{coordination_run.coordination_run_id}:coordinator",
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=request.task_run_id,
                node_id="coordinator",
                role="coordinator",
                assigned_agent_id=parent_agent_run.agent_id,
                assigned_agent_run_ref=parent_agent_run.agent_run_id,
                status="completed",
                created_at=now,
                updated_at=now,
                diagnostics={"graph_source": "delegation_graph", "timeline_order": 0},
            ),
            CoordinationNodeRun(
                node_run_id=f"coordnode:{coordination_run.coordination_run_id}:{child_node_id}",
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=request.task_run_id,
                node_id=child_node_id,
                role="worker_participant",
                assigned_agent_id=child_agent_run.agent_id,
                assigned_agent_run_ref=child_agent_run.agent_run_id,
                status="running",
                created_at=now,
                updated_at=now,
                diagnostics={"graph_source": "delegation_graph", "timeline_order": 1},
            ),
            CoordinationNodeRun(
                node_run_id=f"coordnode:{coordination_run.coordination_run_id}:parent_observation",
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=request.task_run_id,
                node_id="parent_observation",
                role="coordinator",
                assigned_agent_id=parent_agent_run.agent_id,
                assigned_agent_run_ref=parent_agent_run.agent_run_id,
                status="pending",
                created_at=now,
                updated_at=now,
                diagnostics={"graph_source": "delegation_graph", "timeline_order": 2},
            ),
        )
        for node_run in node_runs:
            self.state_index.upsert_coordination_node_run(node_run)
            events.append(
                self.event_log.append(
                    request.task_run_id,
                    "coordination_node_run_created",
                    payload={"coordination_node_run": node_run.to_dict()},
                    refs={"coordination_node_run_ref": node_run.node_run_id, "delegation_request_ref": request.request_id},
                )
            )
        handoffs = (
            AgentHandoffEnvelope(
                handoff_id=f"handoff:{coordination_run.coordination_run_id}:request",
                task_run_id=request.task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                source_agent_run_ref=parent_agent_run.agent_run_id,
                target_agent_run_ref=child_agent_run.agent_run_id,
                message_type="delegate/request",
                payload_ref=request.request_id,
                ack_state="acked",
                created_at=now,
                diagnostics={"handoff_policy": "structured_packet", "graph_source": "delegation_graph"},
            ),
        )
        for handoff in handoffs:
            self.state_index.upsert_handoff_envelope(handoff)
            events.append(
                self.event_log.append(
                    request.task_run_id,
                    "handoff_envelope_created",
                    payload={"handoff_envelope": handoff.to_dict()},
                    refs={"handoff_ref": handoff.handoff_id, "delegation_request_ref": request.request_id},
                )
            )
        return coordination_run, node_runs, handoffs, tuple(events)
