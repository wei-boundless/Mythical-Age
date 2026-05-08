from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import CoordinationMergeResult, CoordinationNodeRun, CoordinationRun


@dataclass(slots=True)
class CoordinationTraceAdapter:
    state_index: Any
    event_log: Any

    def project_flow(self, state: dict[str, Any]) -> dict[str, Any]:
        stage_order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        stage_contracts = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_contracts") or {}).items()
            if str(key)
        }
        node_statuses = dict(state.get("node_statuses") or {})
        stage_results = dict(state.get("stage_results") or {})
        stages: list[dict[str, Any]] = []
        for stage_id in stage_order:
            contract = dict(stage_contracts.get(stage_id) or {})
            status = str(node_statuses.get(stage_id) or ("running" if stage_id == state.get("active_stage_id") else "pending"))
            stage = {
                "stage_id": stage_id,
                "title": str(contract.get("title") or stage_id),
                "node_id": str(contract.get("node_id") or stage_id),
                "role": str(contract.get("role") or ""),
                "task_ref": str(contract.get("task_ref") or ""),
                "message_type": str(contract.get("message_type") or ""),
                "status": status,
            }
            result = dict(stage_results.get(stage_id) or {})
            if result:
                stage["final_result_ref"] = str(result.get("task_result_ref") or result.get("agent_run_result_ref") or "")
                stage["artifact_refs"] = list(result.get("artifact_refs") or [])
            stages.append(stage)
        return {
            "coordination_mode": str(state.get("coordination_mode") or ""),
            "current_stage_id": str(state.get("active_stage_id") or ""),
            "next_stage_id": str(state.get("active_stage_id") or ""),
            "next_task_ref": str(state.get("active_task_ref") or ""),
            "accepted": str(state.get("terminal_status") or "") == "completed",
            "terminal_status": str(state.get("terminal_status") or ""),
            "blocked": str(state.get("terminal_status") or "") == "blocked",
            "waiting_for_human": str(state.get("terminal_status") or "") == "waiting_for_human",
            "missing_required_inputs": list(state.get("missing_required_inputs") or []),
            "ready_nodes": list(state.get("ready_nodes") or []),
            "blocked_nodes": list(state.get("blocked_nodes") or []),
            "running_nodes": list(state.get("running_nodes") or []),
            "waiting_nodes": list(state.get("waiting_nodes") or []),
            "completed_nodes": list(state.get("completed_nodes") or []),
            "failed_nodes": list(state.get("failed_nodes") or []),
            "completed_stage_ids": [
                str(stage.get("stage_id") or "")
                for stage in stages
                if str(stage.get("status") or "") == "completed"
            ],
            "stages": stages,
        }

    def write_state(
        self,
        *,
        coordination_run: CoordinationRun,
        state: dict[str, Any],
        checkpoint_ref: str = "",
        event_task_run_id: str = "",
    ) -> list[Any]:
        events: list[Any] = []
        flow = self.project_flow(state)
        status = _coordination_status_from_state(state)
        diagnostics = {
            **dict(coordination_run.diagnostics),
            "coordination_engine": "langgraph_runtime",
            "coordination_flow": flow,
            "langgraph_thread_id": str(state.get("coordination_run_id") or coordination_run.coordination_run_id),
            "langgraph_runtime_state": {
                "active_stage_id": str(state.get("active_stage_id") or ""),
                "active_task_ref": str(state.get("active_task_ref") or ""),
                "terminal_status": str(state.get("terminal_status") or ""),
                "missing_required_inputs": list(state.get("missing_required_inputs") or []),
                "contract_manifest_ref": str(dict(state.get("contract_manifest") or {}).get("manifest_id") or ""),
                "contract_status": dict(state.get("contract_status") or {}),
                "ready_nodes": list(state.get("ready_nodes") or []),
                "blocked_nodes": list(state.get("blocked_nodes") or []),
                "running_nodes": list(state.get("running_nodes") or []),
                "waiting_nodes": list(state.get("waiting_nodes") or []),
                "completed_nodes": list(state.get("completed_nodes") or []),
                "failed_nodes": list(state.get("failed_nodes") or []),
                "human_gate": dict(state.get("human_gate") or {}),
                "handoff_packet_count": len(list(state.get("handoff_packets") or [])),
                "handoff_packets": [
                    dict(item)
                    for item in list(state.get("handoff_packets") or [])[-10:]
                    if isinstance(item, dict)
                ],
            },
        }
        updated_run = CoordinationRun(
            coordination_run_id=coordination_run.coordination_run_id,
            task_run_id=coordination_run.task_run_id,
            coordination_task_ref=coordination_run.coordination_task_ref,
            coordinator_agent_id=coordination_run.coordinator_agent_id,
            topology_template_id=coordination_run.topology_template_id,
            communication_protocol_id=coordination_run.communication_protocol_id,
            handoff_policy=coordination_run.handoff_policy,
            failure_policy=coordination_run.failure_policy,
            merge_policy=coordination_run.merge_policy,
            status=status,
            latest_checkpoint_ref=checkpoint_ref or coordination_run.latest_checkpoint_ref,
            latest_merge_result_ref=coordination_run.latest_merge_result_ref,
            created_at=coordination_run.created_at,
            updated_at=time.time(),
            diagnostics=diagnostics,
        )
        self.state_index.upsert_coordination_run(updated_run)
        event_owner = event_task_run_id or coordination_run.task_run_id
        if status in {"completed", "failed"}:
            flow_event_type = "coordination_flow_finalized"
        elif coordination_run.diagnostics.get("coordination_flow"):
            flow_event_type = "coordination_flow_advanced"
        else:
            flow_event_type = "coordination_flow_registered"
        events.append(
            self.event_log.append(
                event_owner,
                flow_event_type,
                payload={
                    "coordination_flow": flow,
                    "langgraph_runtime_state": dict(diagnostics.get("langgraph_runtime_state") or {}),
                },
                refs={"coordination_run_ref": coordination_run.coordination_run_id},
            )
        )
        events.extend(self._upsert_node_runs(coordination_run=updated_run, flow=flow, event_task_run_id=event_owner))
        events.append(self._upsert_merge_result(coordination_run=updated_run, state=state, flow=flow, event_task_run_id=event_owner))
        return events

    def _upsert_node_runs(
        self,
        *,
        coordination_run: CoordinationRun,
        flow: dict[str, Any],
        event_task_run_id: str,
    ) -> list[Any]:
        events: list[Any] = []
        existing = {
            item.node_id: item
            for item in self.state_index.list_coordination_node_runs(coordination_run.coordination_run_id)
        }
        for stage in list(flow.get("stages") or []):
            stage_payload = dict(stage)
            node_id = str(stage_payload.get("node_id") or stage_payload.get("stage_id") or "").strip()
            if not node_id:
                continue
            status = _node_run_status(str(stage_payload.get("status") or "pending"))
            current = existing.get(node_id)
            diagnostics = {
                **(dict(current.diagnostics) if current is not None else {}),
                "coordination_engine": "langgraph_runtime",
                "stage_id": str(stage_payload.get("stage_id") or ""),
                "stage_status": str(stage_payload.get("status") or ""),
                "message_type": str(stage_payload.get("message_type") or ""),
                "task_ref": str(stage_payload.get("task_ref") or ""),
            }
            node_run = CoordinationNodeRun(
                node_run_id=(current.node_run_id if current is not None else f"coordnode:{coordination_run.coordination_run_id}:{node_id}"),
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=coordination_run.task_run_id,
                node_id=node_id,
                role=str(stage_payload.get("role") or (current.role if current is not None else "participant")),
                assigned_agent_id=(current.assigned_agent_id if current is not None else ""),
                assigned_agent_run_ref=(current.assigned_agent_run_ref if current is not None else ""),
                status=status,
                handoff_count=(current.handoff_count if current is not None else 0),
                latest_handoff_ref=(current.latest_handoff_ref if current is not None else ""),
                created_at=(current.created_at if current is not None else time.time()),
                updated_at=time.time(),
                diagnostics=diagnostics,
            )
            self.state_index.upsert_coordination_node_run(node_run)
            events.append(
                self.event_log.append(
                    event_task_run_id,
                    "coordination_node_run_updated" if current is not None else "coordination_node_run_created",
                    payload={"coordination_node_run": node_run.to_dict()},
                    refs={"coordination_node_run_ref": node_run.node_run_id},
                )
            )
            events.append(
                self.event_log.append(
                    event_task_run_id,
                    "coordination_stage_updated",
                    payload={
                        "stage": {
                            "stage_id": str(stage_payload.get("stage_id") or ""),
                            "node_id": node_id,
                            "message_type": str(stage_payload.get("message_type") or ""),
                            "status": str(stage_payload.get("status") or ""),
                        }
                    },
                    refs={"coordination_run_ref": coordination_run.coordination_run_id},
                )
            )
        return events

    def _upsert_merge_result(
        self,
        *,
        coordination_run: CoordinationRun,
        state: dict[str, Any],
        flow: dict[str, Any],
        event_task_run_id: str,
    ) -> Any:
        terminal_status = str(state.get("terminal_status") or "")
        accepted = terminal_status == "completed"
        unresolved = tuple(
            str(item)
            for item in list(state.get("missing_required_inputs") or [])
            if str(item)
        )
        result = CoordinationMergeResult(
            merge_result_id=f"coordmerge:{coordination_run.coordination_run_id}",
            coordination_run_id=coordination_run.coordination_run_id,
            task_run_id=coordination_run.task_run_id,
            merge_policy=coordination_run.merge_policy or "coordinator_final_merge",
            final_result_ref=str(state.get("final_result_ref") or ""),
            accepted=accepted,
            unresolved_issue_refs=unresolved,
            created_at=time.time(),
            diagnostics={
                "coordination_engine": "langgraph_runtime",
                "coordination_flow": flow,
                "terminal_status": terminal_status,
            },
        )
        self.state_index.upsert_coordination_merge_result(result)
        self.state_index.upsert_coordination_run(
            CoordinationRun(
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=coordination_run.task_run_id,
                coordination_task_ref=coordination_run.coordination_task_ref,
                coordinator_agent_id=coordination_run.coordinator_agent_id,
                topology_template_id=coordination_run.topology_template_id,
                communication_protocol_id=coordination_run.communication_protocol_id,
                handoff_policy=coordination_run.handoff_policy,
                failure_policy=coordination_run.failure_policy,
                merge_policy=coordination_run.merge_policy,
                status=coordination_run.status,
                latest_checkpoint_ref=coordination_run.latest_checkpoint_ref,
                latest_merge_result_ref=result.merge_result_id,
                created_at=coordination_run.created_at,
                updated_at=time.time(),
                diagnostics=dict(coordination_run.diagnostics),
            )
        )
        return self.event_log.append(
            event_task_run_id,
            "coordination_merge_result_created",
            payload={"coordination_merge_result": result.to_dict()},
            refs={"coordination_merge_result_ref": result.merge_result_id},
        )


def _coordination_status_from_state(state: dict[str, Any]) -> str:
    terminal = str(state.get("terminal_status") or "")
    if terminal == "completed":
        return "completed"
    if terminal in {"failed", "blocked"}:
        return "failed"
    if terminal == "waiting_for_human":
        return "waiting"
    return "running"


def _node_run_status(stage_status: str) -> str:
    if stage_status == "running":
        return "running"
    if stage_status in {"completed", "skipped"}:
        return "completed"
    if stage_status in {"failed", "blocked"}:
        return "failed"
    if stage_status == "waiting_for_human":
        return "waiting"
    return "pending"
