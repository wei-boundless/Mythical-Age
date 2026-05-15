from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .checkpoint import RuntimeCheckpointStore
from .event_log import RuntimeEventLog
from .events import RuntimeEvent
from .langgraph_checkpoint_adapter import LangGraphCheckpointStoreAdapter
from .models import CoordinationRun, TaskRun
from .state_index import RuntimeStateIndex
from .task_graph_run_monitor import build_task_graph_run_monitor_view


@dataclass(frozen=True, slots=True)
class RuntimeLoopTraceReader:
    """Read-only view over TaskRunLoop event/checkpoint traces."""

    state_index: RuntimeStateIndex
    event_log: RuntimeEventLog
    checkpoints: RuntimeCheckpointStore
    coordination_checkpoints: LangGraphCheckpointStoreAdapter | None = None

    def list_session_task_runs(self, session_id: str) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_session_task_runs(session_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return {
            "session_id": session_id,
            "task_run_count": len(task_runs),
            "task_runs": [self._task_run_summary(item) for item in task_runs],
            "authority": "orchestration.runtime_loop_trace_reader",
        }

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        state_snapshot = self.state_index.read_session_monitor_snapshot(session_id)
        task_runs = _session_task_run_payloads(state_snapshot, session_id)
        latest = _pick_session_monitor_task_run_payload(task_runs, state_snapshot)
        monitor_index = dict(state_snapshot.get("monitor_index") or {})
        task_run_count = int(monitor_index.get("task_run_count") or len(task_runs))
        return {
            "session_id": session_id,
            "task_run_count": task_run_count,
            "latest_task_run_id": str(latest.get("task_run_id") or "") if latest is not None else "",
            "monitor": (
                self._get_task_run_live_monitor_from_snapshot(
                    str(latest.get("task_run_id") or ""),
                    state_snapshot=state_snapshot,
                )
                if latest is not None
                else None
            ),
            "authority": "orchestration.runtime_loop_live_monitor",
        }

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        return self._get_task_run_live_monitor_from_snapshot(
            task_run_id,
            state_snapshot=self.state_index.read_session_monitor_snapshot(task_run.session_id),
        )

    def get_task_graph_run_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        coordination_run = _pick_coordination_run(self.state_index.list_task_coordination_runs(task_run_id))
        if coordination_run is None:
            task_checkpoint = self.checkpoints.load_latest(task_run_id)
            return build_task_graph_run_monitor_view(
                task_run=task_run.to_dict(),
                coordination_run=None,
                coordination_state={},
                task_checkpoint=task_checkpoint.to_dict() if task_checkpoint is not None else None,
                event_count=len(self.event_log.list_events(task_run_id)),
                source="task_run",
            )
        return self.get_coordination_run_monitor(coordination_run.coordination_run_id)

    def get_coordination_run_monitor(self, coordination_run_id: str) -> dict[str, Any] | None:
        coordination_run = self.state_index.get_coordination_run(coordination_run_id)
        if coordination_run is None:
            return None
        task_run = self.state_index.get_task_run(coordination_run.task_run_id)
        if task_run is None:
            return None
        task_checkpoint = self.checkpoints.load_latest(task_run.task_run_id)
        coordination_checkpoint = (
            self.coordination_checkpoints.get_checkpoint(thread_id=coordination_run_id)
            if self.coordination_checkpoints is not None
            else None
        )
        coordination_state = dict(coordination_checkpoint.state) if coordination_checkpoint is not None else {}
        return build_task_graph_run_monitor_view(
            task_run=task_run.to_dict(),
            coordination_run=coordination_run.to_dict(),
            coordination_state=coordination_state,
            coordination_checkpoint=coordination_checkpoint.to_dict() if coordination_checkpoint is not None else None,
            task_checkpoint=task_checkpoint.to_dict() if task_checkpoint is not None else None,
            event_count=len(self.event_log.list_events(task_run.task_run_id)),
            source="coordination_run",
        )

    def _get_task_run_live_monitor_from_snapshot(
        self,
        task_run_id: str,
        *,
        state_snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        task_run_payload = dict((state_snapshot.get("task_runs") or {}).get(task_run_id) or {})
        task_run = _task_run_from_payload_summary(task_run_payload)
        if task_run is None:
            return None
        checkpoint = self.checkpoints.load_latest(task_run_id)
        coordination_runs = _task_coordination_run_payloads(state_snapshot, task_run_id)
        active_coordination_run = _pick_coordination_run_payload(coordination_runs)
        coordination_view = None
        if active_coordination_run is not None:
            active_coordination_run_id = str(active_coordination_run.get("coordination_run_id") or "")
            node_runs = _coordination_node_run_payloads(state_snapshot, active_coordination_run_id)
            handoffs = _coordination_handoff_payloads(state_snapshot, active_coordination_run_id)
            merge_result = _latest_coordination_merge_result_payload(state_snapshot, active_coordination_run_id)
            diagnostics = dict(active_coordination_run.get("diagnostics") or {})
            coordination_checkpoint = (
                self.coordination_checkpoints.get_checkpoint(
                    thread_id=active_coordination_run_id,
                )
                if self.coordination_checkpoints is not None
                else None
            )
            coordination_state = (
                dict(coordination_checkpoint.state)
                if coordination_checkpoint is not None
                else dict(diagnostics.get("langgraph_runtime_state_summary") or {})
            )
            coordination_view = {
                "coordination_run": _coordination_run_payload_summary(active_coordination_run),
                "coordination_flow": _coordination_flow_summary(dict(diagnostics.get("coordination_flow") or {})),
                "langgraph_runtime_state": _langgraph_state_summary(coordination_state),
                "task_graph_scheduler_state": _scheduler_state_summary(
                    dict(
                        coordination_state.get("task_graph_scheduler_state")
                        or dict(coordination_state.get("diagnostics") or {}).get("task_graph_scheduler_state")
                        or diagnostics.get("task_graph_scheduler_state")
                        or {}
                    )
                ),
                "coordination_graph_spec": _coordination_graph_spec_summary(
                    dict(
                        dict(coordination_state.get("diagnostics") or {}).get("coordination_graph_spec")
                        or diagnostics.get("coordination_graph_spec")
                        or diagnostics.get("coordination_graph_spec_summary")
                        or {}
                    )
                ),
                "coordination_checkpoint": (
                    {
                        "checkpoint_id": coordination_checkpoint.checkpoint_id,
                        "thread_id": coordination_checkpoint.thread_id,
                        "created_at": coordination_checkpoint.created_at,
                    }
                    if coordination_checkpoint is not None
                    else None
                ),
                "node_runs": [_node_run_payload_summary(item) for item in node_runs],
                "handoff_envelopes": [_handoff_payload_summary(item) for item in handoffs[-30:]],
                "latest_merge_result": _merge_result_payload_summary(merge_result) if merge_result is not None else None,
            }
        loop_state = checkpoint.loop_state.to_dict() if checkpoint is not None else {}
        return {
            "task_run": task_run,
            "latest_checkpoint": _checkpoint_summary(checkpoint) if checkpoint is not None else None,
            "loop_state": _loop_state_summary(loop_state),
            "coordination_run": coordination_view,
            "has_coordination": coordination_view is not None,
            "status": str(task_run.get("status") or loop_state.get("status") or "unknown"),
            "terminal_reason": str(task_run.get("terminal_reason") or loop_state.get("terminal_reason") or ""),
            "updated_at": float(
                max(
                    float(task_run.get("updated_at") or 0.0),
                    checkpoint.created_at if checkpoint is not None else 0.0,
                    float(active_coordination_run.get("updated_at") or 0.0) if active_coordination_run is not None else 0.0,
                )
            ),
            "authority": "orchestration.runtime_loop_live_monitor",
        }

    def get_task_run_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ) -> dict[str, Any] | None:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return None
        events = self.event_log.list_events(task_run_id)
        checkpoint = self.checkpoints.load_latest(task_run_id)
        agent_runs = self.state_index.list_task_agent_runs(task_run_id)
        coordination_runs = self.state_index.list_task_coordination_runs(task_run_id)
        return {
            "task_run": task_run.to_dict(),
            "agent_runs": [item.to_dict() for item in agent_runs],
            "agent_run_results": [item.to_dict() for item in self.state_index.list_task_agent_run_results(task_run_id)],
            "agent_delegation_requests": [
                item.to_dict() for item in self.state_index.list_task_agent_delegation_requests(task_run_id)
            ],
            "agent_delegation_results": [
                item.to_dict() for item in self.state_index.list_task_agent_delegation_results(task_run_id)
            ],
            "worker_spawn_requests": [
                item.to_dict() for item in self.state_index.list_task_worker_spawn_requests(task_run_id)
            ],
            "worker_spawn_results": [
                item.to_dict() for item in self.state_index.list_task_worker_spawn_results(task_run_id)
            ],
            "coordination_runs": [
                {
                    **item.to_dict(),
                    "node_runs": [node.to_dict() for node in self.state_index.list_coordination_node_runs(item.coordination_run_id)],
                    "handoff_envelopes": [
                        handoff.to_dict()
                        for handoff in self.state_index.list_coordination_handoffs(item.coordination_run_id)
                    ],
                    "latest_merge_result": (
                        self.state_index.get_latest_coordination_merge_result(item.coordination_run_id).to_dict()
                        if self.state_index.get_latest_coordination_merge_result(item.coordination_run_id) is not None
                        else None
                    ),
                }
                for item in coordination_runs
            ],
            "event_count": len(events),
            "events": [
                _event_view(
                    event,
                    include_payloads=include_payloads,
                    include_model_messages=include_model_messages,
                )
                for event in events
            ],
            "latest_checkpoint": checkpoint.to_dict() if checkpoint is not None else None,
            "trace_policy": {
                "payloads_included": include_payloads,
                "model_messages_included": include_model_messages,
                "default_redaction": "model_messages_and_section_content_are_summarized",
            },
            "authority": "orchestration.runtime_loop_trace_reader",
        }

    def _task_run_summary_without_checkpoint(self, task_run: TaskRun) -> dict[str, Any]:
        return {
            "task_run_id": task_run.task_run_id,
            "session_id": task_run.session_id,
            "task_id": task_run.task_id,
            "agent_id": task_run.agent_id,
            "agent_profile_id": task_run.agent_profile_id,
            "runtime_lane": task_run.runtime_lane,
            "status": task_run.status,
            "terminal_reason": task_run.terminal_reason,
            "graph_ref": str(dict(task_run.diagnostics or {}).get("graph_ref") or ""),
            "coordination_run_ref": str(dict(task_run.diagnostics or {}).get("coordination_run_ref") or ""),
            "created_at": task_run.created_at,
            "updated_at": task_run.updated_at,
            "authority": task_run.authority,
        }

    def _task_run_summary(self, task_run: TaskRun) -> dict[str, Any]:
        events = self.event_log.list_events(task_run.task_run_id)
        checkpoint = self.checkpoints.load_latest(task_run.task_run_id)
        agent_runs = self.state_index.list_task_agent_runs(task_run.task_run_id)
        coordination_runs = self.state_index.list_task_coordination_runs(task_run.task_run_id)
        return {
            "task_run": task_run.to_dict(),
            "agent_run_count": len(agent_runs),
            "coordination_run_count": len(coordination_runs),
            "event_count": len(events),
            "latest_event_type": events[-1].event_type if events else "",
            "latest_checkpoint": checkpoint.to_dict() if checkpoint is not None else None,
        }


def _checkpoint_summary(checkpoint: Any) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "task_run_id": checkpoint.task_run_id,
        "event_offset": checkpoint.event_offset,
        "created_at": checkpoint.created_at,
        "checksum": checkpoint.checksum,
        "execution_summary": dict(checkpoint.execution_summary or {}),
        "runtime_objects_summary": dict(checkpoint.runtime_objects_summary or {}),
        "authority": checkpoint.authority,
    }


def _loop_state_summary(loop_state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(loop_state.get("diagnostics") or {})
    stage_request = dict(diagnostics.get("stage_execution_request") or {})
    return {
        "task_run_id": str(loop_state.get("task_run_id") or ""),
        "status": str(loop_state.get("status") or ""),
        "transition": str(loop_state.get("transition") or ""),
        "terminal_reason": str(loop_state.get("terminal_reason") or ""),
        "turn_count": int(loop_state.get("turn_count") or 0),
        "step_count": int(loop_state.get("step_count") or 0),
        "current_step_id": str(loop_state.get("current_step_id") or ""),
        "agent_id": str(loop_state.get("agent_id") or ""),
        "runtime_lane": str(loop_state.get("runtime_lane") or ""),
        "projection_ref": str(loop_state.get("projection_ref") or ""),
        "result_ref_count": len(list(loop_state.get("result_refs") or [])),
        "diagnostics": {
            "task_graph_run": bool(diagnostics.get("task_graph_run") is True),
            "task_graph_id": str(diagnostics.get("task_graph_id") or ""),
            "langgraph_coordination_initialized": bool(
                diagnostics.get("langgraph_coordination_initialized") is True
            ),
            "langgraph_checkpoint_ref": str(diagnostics.get("langgraph_checkpoint_ref") or ""),
            "active_stage_id": str(stage_request.get("stage_id") or ""),
        },
        "authority": str(loop_state.get("authority") or "orchestration.runtime_loop_state"),
    }


def _coordination_run_summary(coordination_run: CoordinationRun) -> dict[str, Any]:
    return {
        "coordination_run_id": coordination_run.coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "graph_ref": coordination_run.graph_ref,
        "coordinator_agent_id": coordination_run.coordinator_agent_id,
        "topology_template_id": coordination_run.topology_template_id,
        "communication_protocol_id": coordination_run.communication_protocol_id,
        "status": coordination_run.status,
        "terminal_reason": str(dict(coordination_run.diagnostics or {}).get("terminal_reason") or ""),
        "created_at": coordination_run.created_at,
        "updated_at": coordination_run.updated_at,
        "authority": coordination_run.authority,
    }


def _coordination_flow_summary(flow: dict[str, Any]) -> dict[str, Any]:
    stages = list(flow.get("stages") or [])
    return {
        "current_stage_id": str(flow.get("current_stage_id") or ""),
        "stage_count": len(stages),
        "completed_stage_count": sum(
            1 for item in stages if str(dict(item).get("status") or "") == "completed"
        ),
        "running_stage_ids": [
            str(dict(item).get("stage_id") or "")
            for item in stages
            if str(dict(item).get("status") or "") == "running"
        ],
        "blocked_stage_count": sum(
            1 for item in stages if str(dict(item).get("status") or "") == "blocked"
        ),
        "accepted": bool(flow.get("accepted") is True),
    }


def _langgraph_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    stage_results = dict(state.get("stage_results") or {})
    return {
        "active_stage_id": str(state.get("active_stage_id") or ""),
        "active_node_id": str(state.get("active_node_id") or ""),
        "ready_nodes": list(state.get("ready_nodes") or []),
        "running_nodes": list(state.get("running_nodes") or []),
        "completed_nodes": list(state.get("completed_nodes") or []),
        "failed_nodes": list(state.get("failed_nodes") or []),
        "blocked_node_count": len(list(state.get("blocked_nodes") or [])),
        "terminal_status": str(state.get("terminal_status") or ""),
        "stage_result_count": len(stage_results),
        "stage_results": {
            stage_id: {
                "status": str(dict(result).get("status") or ""),
                "artifact_refs": [
                    ref
                    for ref in list(dict(result).get("artifact_refs") or [])
                    if str(ref).startswith("artifact:")
                ],
                "trace_ref_count": len(list(dict(result).get("trace_refs") or [])),
            }
            for stage_id, result in stage_results.items()
        },
        "artifact_refs": [
            dict(item)
            for item in list(state.get("artifact_refs") or [])
            if str(dict(item).get("ref") or dict(item).get("artifact_ref") or "").startswith("artifact:")
        ][-50:],
        "working_memory_operation_count": len(list(state.get("working_memory_operations") or [])),
    }


def _scheduler_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    node_statuses = dict(state.get("node_statuses") or {})
    return {
        "node_count": len(node_statuses),
        "ready_nodes": list(state.get("ready_nodes") or []),
        "running_nodes": list(state.get("running_nodes") or []),
        "completed_nodes": list(state.get("completed_nodes") or []),
        "failed_nodes": list(state.get("failed_nodes") or []),
        "blocked_node_count": len(list(state.get("blocked_nodes") or [])),
        "node_statuses": node_statuses,
    }


def _coordination_graph_spec_summary(spec: dict[str, Any]) -> dict[str, Any]:
    nodes = list(spec.get("nodes") or [])
    edges = list(spec.get("edges") or [])
    return {
        "graph_id": str(spec.get("graph_id") or ""),
        "coordination_task_id": str(spec.get("coordination_task_id") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": [
            {
                "node_id": str(dict(item).get("node_id") or ""),
                "title": str(dict(item).get("title") or ""),
                "role": str(dict(item).get("role") or ""),
                "agent_id": str(dict(item).get("agent_id") or ""),
            }
            for item in nodes
        ],
        "edges": [
            {
                "edge_id": str(dict(item).get("edge_id") or ""),
                "from_node_id": str(dict(item).get("from_node_id") or ""),
                "to_node_id": str(dict(item).get("to_node_id") or ""),
                "label": str(dict(item).get("label") or ""),
            }
            for item in edges
        ],
    }


def _node_run_summary(node_run: Any) -> dict[str, Any]:
    payload = node_run.to_dict()
    return {
        "node_run_id": str(payload.get("node_run_id") or ""),
        "node_id": str(payload.get("node_id") or ""),
        "assigned_agent_id": str(payload.get("assigned_agent_id") or ""),
        "assigned_agent_run_ref": str(payload.get("assigned_agent_run_ref") or ""),
        "status": str(payload.get("status") or ""),
        "input_refs": list(payload.get("input_refs") or []),
        "output_refs": [
            ref for ref in list(payload.get("output_refs") or []) if str(ref).startswith("artifact:")
        ],
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
    }


def _handoff_summary(handoff: Any) -> dict[str, Any]:
    payload = handoff.to_dict()
    return {
        "handoff_id": str(payload.get("handoff_id") or ""),
        "source_agent_run_ref": str(payload.get("source_agent_run_ref") or ""),
        "target_agent_run_ref": str(payload.get("target_agent_run_ref") or ""),
        "protocol_id": str(payload.get("protocol_id") or ""),
        "message_type": str(payload.get("message_type") or ""),
        "ack_state": str(payload.get("ack_state") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
    }


def _merge_result_summary(merge_result: Any) -> dict[str, Any]:
    payload = merge_result.to_dict()
    return {
        "merge_result_id": str(payload.get("merge_result_id") or ""),
        "merge_policy": str(payload.get("merge_policy") or ""),
        "accepted": bool(payload.get("accepted") is True),
        "final_result_ref": str(payload.get("final_result_ref") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
    }


def _session_task_run_payloads(state_snapshot: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    task_runs = dict(state_snapshot.get("task_runs") or {})
    ids = list((state_snapshot.get("sessions") or {}).get(session_id) or [])
    payloads = [dict(task_runs[item]) for item in ids if isinstance(task_runs.get(item), dict)]
    return sorted(payloads, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)


def _task_coordination_run_payloads(state_snapshot: dict[str, Any], task_run_id: str) -> list[dict[str, Any]]:
    coordination_runs = dict(state_snapshot.get("coordination_runs") or {})
    ids = list((state_snapshot.get("task_coordination_runs") or {}).get(task_run_id) or [])
    payloads = [dict(coordination_runs[item]) for item in ids if isinstance(coordination_runs.get(item), dict)]
    return sorted(payloads, key=lambda item: float(item.get("updated_at") or 0.0), reverse=True)


def _coordination_node_run_payloads(state_snapshot: dict[str, Any], coordination_run_id: str) -> list[dict[str, Any]]:
    node_runs = dict(state_snapshot.get("coordination_node_runs") or {})
    ids = list((state_snapshot.get("coordination_node_run_index") or {}).get(coordination_run_id) or [])
    payloads = [dict(node_runs[item]) for item in ids if isinstance(node_runs.get(item), dict)]
    return sorted(
        payloads,
        key=lambda item: (float(item.get("updated_at") or 0.0), str(item.get("node_id") or "")),
        reverse=False,
    )


def _coordination_handoff_payloads(state_snapshot: dict[str, Any], coordination_run_id: str) -> list[dict[str, Any]]:
    handoffs = dict(state_snapshot.get("handoff_envelopes") or {})
    ids = list((state_snapshot.get("coordination_handoffs") or {}).get(coordination_run_id) or [])
    payloads = [dict(handoffs[item]) for item in ids if isinstance(handoffs.get(item), dict)]
    return sorted(payloads, key=lambda item: float(item.get("created_at") or 0.0), reverse=False)


def _latest_coordination_merge_result_payload(
    state_snapshot: dict[str, Any],
    coordination_run_id: str,
) -> dict[str, Any] | None:
    results = [
        dict(item)
        for item in dict(state_snapshot.get("coordination_merge_results") or {}).values()
        if isinstance(item, dict) and str(item.get("coordination_run_id") or "") == coordination_run_id
    ]
    if not results:
        return None
    return sorted(results, key=lambda item: float(item.get("created_at") or 0.0), reverse=True)[0]


def _pick_session_monitor_task_run_payload(
    task_runs: list[dict[str, Any]],
    state_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    if not task_runs:
        return None
    task_coordination_runs = dict(state_snapshot.get("task_coordination_runs") or {})
    for item in task_runs:
        if list(task_coordination_runs.get(str(item.get("task_run_id") or "")) or []):
            return item
    return task_runs[0]


def _pick_coordination_run_payload(coordination_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not coordination_runs:
        return None
    for status in ("running", "waiting", "pending"):
        for item in coordination_runs:
            if str(item.get("status") or "") == status:
                return item
    return coordination_runs[0]


def _task_run_from_payload_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    diagnostics = dict(payload.get("diagnostics") or {})
    return {
        "task_run_id": str(payload.get("task_run_id") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "task_id": str(payload.get("task_id") or ""),
        "agent_id": str(payload.get("agent_id") or ""),
        "agent_profile_id": str(payload.get("agent_profile_id") or ""),
        "runtime_lane": str(payload.get("runtime_lane") or ""),
        "status": str(payload.get("status") or ""),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "graph_ref": str(diagnostics.get("graph_ref") or ""),
        "coordination_run_ref": str(diagnostics.get("coordination_run_ref") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
        "authority": str(payload.get("authority") or ""),
    }


def _coordination_run_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "coordination_run_id": str(payload.get("coordination_run_id") or ""),
        "task_run_id": str(payload.get("task_run_id") or ""),
        "coordinator_agent_id": str(payload.get("coordinator_agent_id") or ""),
        "graph_ref": str(payload.get("graph_ref") or ""),
        "status": str(payload.get("status") or ""),
        "terminal_reason": str(payload.get("terminal_reason") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
    }


def _node_run_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_run_id": str(payload.get("node_run_id") or ""),
        "node_id": str(payload.get("node_id") or ""),
        "assigned_agent_id": str(payload.get("assigned_agent_id") or ""),
        "assigned_agent_run_ref": str(payload.get("assigned_agent_run_ref") or ""),
        "status": str(payload.get("status") or ""),
        "input_refs": list(payload.get("input_refs") or []),
        "output_refs": [
            ref for ref in list(payload.get("output_refs") or []) if str(ref).startswith("artifact:")
        ],
        "created_at": float(payload.get("created_at") or 0.0),
        "updated_at": float(payload.get("updated_at") or 0.0),
    }


def _handoff_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "handoff_id": str(payload.get("handoff_id") or ""),
        "source_agent_run_ref": str(payload.get("source_agent_run_ref") or ""),
        "target_agent_run_ref": str(payload.get("target_agent_run_ref") or ""),
        "protocol_id": str(payload.get("protocol_id") or ""),
        "message_type": str(payload.get("message_type") or ""),
        "ack_state": str(payload.get("ack_state") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
    }


def _merge_result_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "merge_result_id": str(payload.get("merge_result_id") or ""),
        "merge_policy": str(payload.get("merge_policy") or ""),
        "accepted": bool(payload.get("accepted") is True),
        "final_result_ref": str(payload.get("final_result_ref") or ""),
        "created_at": float(payload.get("created_at") or 0.0),
    }


def _event_view(
    event: RuntimeEvent,
    *,
    include_payloads: bool,
    include_model_messages: bool,
) -> dict[str, Any]:
    payload = dict(event.payload or {})
    view = {
        "event_id": event.event_id,
        "task_run_id": event.task_run_id,
        "event_type": event.event_type,
        "offset": event.offset,
        "created_at": event.created_at,
        "refs": dict(event.refs or {}),
    }
    if include_payloads:
        view["payload"] = _sanitize_payload(payload, include_model_messages=include_model_messages)
    else:
        view["payload_summary"] = _payload_summary(event.event_type, payload)
    return view


def _pick_coordination_run(coordination_runs: list[CoordinationRun]) -> CoordinationRun | None:
    if not coordination_runs:
        return None
    for status in ("running", "waiting", "pending"):
        for item in coordination_runs:
            if item.status == status:
                return item
    return coordination_runs[0]


def _pick_session_monitor_task_run(task_runs: list[TaskRun], state_index: RuntimeStateIndex) -> TaskRun | None:
    if not task_runs:
        return None
    for item in task_runs:
        if state_index.list_task_coordination_runs(item.task_run_id):
            return item
    return task_runs[0]


def _payload_summary(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"keys": sorted(str(key) for key in payload.keys())}
    if event_type == "context_snapshot_built":
        snapshot = dict(payload.get("context_snapshot") or {})
        summary.update(
            {
                "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                "model_message_count": len(list(snapshot.get("model_messages") or [])),
                "history_message_count": int(snapshot.get("history_message_count") or 0),
                "pending_user_message_chars": int(snapshot.get("pending_user_message_chars") or 0),
                "system_prompt_chars": int(snapshot.get("system_prompt_chars") or 0),
                "context_policy_ref": str(snapshot.get("context_policy_ref") or ""),
                "memory_runtime_view_ref": str(snapshot.get("memory_runtime_view_ref") or ""),
                "projection_ref": str(snapshot.get("projection_ref") or ""),
                "prompt_manifest_ref": str(snapshot.get("prompt_manifest_ref") or ""),
                "token_pressure": dict(snapshot.get("token_pressure") or {}),
            }
        )
    elif event_type == "stage_projection_built":
        projection = dict(payload.get("stage_projection") or {})
        summary.update(
            {
                "snapshot_id": str(projection.get("snapshot_id") or ""),
                "projection_ref": str(projection.get("projection_ref") or ""),
                "prompt_manifest_ref": str(projection.get("prompt_manifest_ref") or ""),
                "visible_tool_ids": list(projection.get("visible_tool_ids") or []),
                "visible_skill_ids": list(projection.get("visible_skill_ids") or []),
                "visible_section_count": int(projection.get("visible_section_count") or 0),
            }
        )
    elif event_type == "context_invariant_checked":
        report = dict(payload.get("invariant_report") or {})
        summary.update(
            {
                "report_id": str(report.get("report_id") or ""),
                "snapshot_ref": str(report.get("snapshot_ref") or ""),
                "tool_result_pairing_ok": bool(report.get("tool_result_pairing_ok") is True),
                "needs_compaction": bool(report.get("needs_compaction") is True),
                "compaction_reason": str(report.get("compaction_reason") or ""),
                "token_pressure": dict(report.get("token_pressure") or {}),
            }
        )
    elif event_type == "task_contract_built":
        contract = dict(payload.get("task_contract") or {})
        recipe = dict(payload.get("selected_recipe") or {})
        task_spec = dict(payload.get("task_spec") or {})
        task_run_ledger = dict(payload.get("task_run_ledger") or {})
        summary.update(
            {
                "task_id": str(contract.get("task_id") or ""),
                "session_id": str(contract.get("session_id") or ""),
                "template_id": str(contract.get("template_id") or recipe.get("template_id") or ""),
                "task_spec_ref": str(contract.get("task_spec_ref") or task_spec.get("task_spec_ref") or ""),
                "requested_outputs": list(task_spec.get("requested_outputs") or []),
                "step_count": len(list(task_run_ledger.get("step_runs") or [])),
                "user_goal_chars": len(str(contract.get("user_goal") or "")),
                "adoption_plan_ref": str(dict(payload.get("task_agent_adoption_plan") or {}).get("plan_id") or ""),
                "graph_ref": str(
                    dict(payload.get("task_graph_record") or {}).get("graph_id")
                    or dict(payload.get("graph_record") or {}).get("graph_id")
                    or ""
                ),
                "source": str(payload.get("source") or ""),
            }
        )
    elif event_type == "agent_run_created":
        agent_run = dict(payload.get("agent_run") or {})
        summary.update(
            {
                "agent_run_id": str(agent_run.get("agent_run_id") or ""),
                "agent_id": str(agent_run.get("agent_id") or ""),
                "role": str(agent_run.get("role") or ""),
                "spawn_mode": str(agent_run.get("spawn_mode") or ""),
                "status": str(agent_run.get("status") or ""),
            }
        )
    elif event_type == "coordination_run_created":
        coordination_run = dict(payload.get("coordination_run") or {})
        summary.update(
            {
                "coordination_run_id": str(coordination_run.get("coordination_run_id") or ""),
                "graph_ref": str(coordination_run.get("graph_ref") or ""),
                "coordinator_agent_id": str(coordination_run.get("coordinator_agent_id") or ""),
                "topology_template_id": str(coordination_run.get("topology_template_id") or ""),
                "communication_protocol_id": str(coordination_run.get("communication_protocol_id") or ""),
                "status": str(coordination_run.get("status") or ""),
            }
        )
    elif event_type == "worker_agent_spawn_requested":
        request = dict(payload.get("worker_spawn_request") or {})
        summary.update(
            {
                "spawn_request_id": str(request.get("spawn_request_id") or ""),
                "blueprint_id": str(request.get("blueprint_id") or ""),
                "requested_agent_name": str(request.get("requested_agent_name") or ""),
                "runtime_lane": str(request.get("runtime_lane") or ""),
                "requested_by_agent_id": str(request.get("requested_by_agent_id") or ""),
            }
        )
    elif event_type == "worker_agent_spawn_completed":
        result = dict(payload.get("worker_spawn_result") or {})
        summary.update(
            {
                "spawn_result_id": str(result.get("spawn_result_id") or ""),
                "spawn_request_id": str(result.get("spawn_request_id") or ""),
                "spawned_agent_id": str(result.get("spawned_agent_id") or ""),
                "spawned_agent_run_ref": str(result.get("spawned_agent_run_ref") or ""),
                "status": str(result.get("status") or ""),
            }
        )
    elif event_type == "agent_delegation_requested":
        request = dict(payload.get("agent_delegation_request") or {})
        summary.update(
            {
                "request_id": str(request.get("request_id") or ""),
                "source_agent_id": str(request.get("source_agent_id") or ""),
                "target_agent_id": str(request.get("target_agent_id") or ""),
                "delegation_kind": str(request.get("delegation_kind") or ""),
            }
        )
    elif event_type == "agent_delegation_result_created":
        result = dict(payload.get("agent_delegation_result") or {})
        summary.update(
            {
                "result_id": str(result.get("result_id") or ""),
                "request_id": str(result.get("request_id") or ""),
                "target_agent_id": str(result.get("target_agent_id") or ""),
                "status": str(result.get("status") or ""),
            }
        )
    elif event_type == "coordination_node_run_created":
        node_run = dict(payload.get("coordination_node_run") or {})
        summary.update(
            {
                "node_run_id": str(node_run.get("node_run_id") or ""),
                "node_id": str(node_run.get("node_id") or ""),
                "assigned_agent_id": str(node_run.get("assigned_agent_id") or ""),
                "assigned_agent_run_ref": str(node_run.get("assigned_agent_run_ref") or ""),
                "status": str(node_run.get("status") or ""),
            }
        )
    elif event_type == "coordination_node_run_updated":
        node_run = dict(payload.get("coordination_node_run") or {})
        summary.update(
            {
                "node_run_id": str(node_run.get("node_run_id") or ""),
                "node_id": str(node_run.get("node_id") or ""),
                "status": str(node_run.get("status") or ""),
                "assigned_agent_run_ref": str(node_run.get("assigned_agent_run_ref") or ""),
            }
        )
    elif event_type == "handoff_envelope_created":
        handoff = dict(payload.get("handoff_envelope") or {})
        summary.update(
            {
                "handoff_id": str(handoff.get("handoff_id") or ""),
                "source_agent_run_ref": str(handoff.get("source_agent_run_ref") or ""),
                "target_agent_run_ref": str(handoff.get("target_agent_run_ref") or ""),
                "protocol_id": str(handoff.get("protocol_id") or ""),
                "message_type": str(handoff.get("message_type") or ""),
                "ack_state": str(handoff.get("ack_state") or ""),
            }
        )
    elif event_type == "coordination_merge_result_created":
        merge_result = dict(payload.get("coordination_merge_result") or {})
        summary.update(
            {
                "merge_result_id": str(merge_result.get("merge_result_id") or ""),
                "merge_policy": str(merge_result.get("merge_policy") or ""),
                "accepted": bool(merge_result.get("accepted") is True),
                "final_result_ref": str(merge_result.get("final_result_ref") or ""),
            }
        )
    elif event_type in {"coordination_flow_registered", "coordination_flow_finalized"}:
        flow = dict(payload.get("coordination_flow") or {})
        summary.update(
            {
                "current_stage_id": str(flow.get("current_stage_id") or ""),
                "stage_count": len(list(flow.get("stages") or [])),
                "revision_loop_enabled": bool(flow.get("revision_loop_enabled") is True),
                "completed_revision_cycles": int(flow.get("completed_revision_cycles") or 0),
                "accepted": bool(flow.get("accepted") is True),
            }
        )
    elif event_type == "coordination_stage_updated":
        stage = dict(payload.get("stage") or {})
        summary.update(
            {
                "stage_id": str(stage.get("stage_id") or ""),
                "node_id": str(stage.get("node_id") or ""),
                "message_type": str(stage.get("message_type") or ""),
                "status": str(stage.get("status") or ""),
            }
        )
    elif event_type == "memory_runtime_view_built":
        summary.update(
            {
                "memory_runtime_view_ref": str(payload.get("memory_runtime_view_ref") or ""),
                "conversation_candidate_count": int(payload.get("conversation_candidate_count") or 0),
                "state_candidate_count": int(payload.get("state_candidate_count") or 0),
                "long_term_candidate_count": int(payload.get("long_term_candidate_count") or 0),
            }
        )
    elif event_type == "runtime_directive_issued":
        directive = dict(payload.get("directive") or {})
        policy = dict(payload.get("resource_policy") or {})
        summary.update(
            {
                "directive_id": str(directive.get("directive_id") or ""),
                "directive_kind": str(directive.get("kind") or directive.get("directive_type") or ""),
                "resource_policy_id": str(policy.get("policy_id") or ""),
            }
        )
    elif event_type == "operation_gate_checked":
        gate = dict(payload.get("gate") or {})
        summary.update(
            {
                "operation_id": str(gate.get("operation_id") or ""),
                "allowed": bool(gate.get("allowed") is True),
                "reason": str(gate.get("reason") or ""),
            }
        )
    elif event_type == "loop_control_checked":
        control = dict(payload.get("control") or {})
        snapshot = dict(control.get("snapshot") or {})
        summary.update(
            {
                "allowed": bool(control.get("allowed") is True),
                "reason": str(control.get("reason") or ""),
                "turn_count": int(snapshot.get("turn_count") or 0),
                "model_call_count": int(snapshot.get("model_call_count") or 0),
                "event_count": int(snapshot.get("event_count") or 0),
                "elapsed_seconds": float(snapshot.get("elapsed_seconds") or 0.0),
            }
        )
    elif event_type == "executor_observation_received":
        observation = dict(payload.get("observation") or {})
        context_record = dict(payload.get("context_record") or {})
        summary.update(
            {
                "observation_id": str(observation.get("observation_id") or ""),
                "observation_type": str(observation.get("observation_type") or ""),
                "source": str(payload.get("source") or observation.get("source") or ""),
                "content_chars": int(payload.get("content_chars") or observation.get("content_chars") or 0),
                "needs_model_followup": bool(observation.get("needs_model_followup") is True),
                "context_record_id": str(context_record.get("record_id") or ""),
                "context_update_mode": str(dict(context_record.get("context_update") or {}).get("mode") or ""),
            }
        )
    elif event_type == "tool_call_requested":
        action_request = dict(payload.get("action_request") or {})
        request_payload = dict(action_request.get("payload") or {})
        summary.update(
            {
                "request_id": str(action_request.get("request_id") or ""),
                "request_type": str(action_request.get("request_type") or ""),
                "tool_name": str(request_payload.get("tool_name") or ""),
                "execution_state": str(request_payload.get("execution_state") or ""),
            }
        )
    elif event_type in {
        "execution_record_created",
        "execution_dispatch_started",
        "execution_result_recorded",
        "execution_result_reused",
        "replay_guard_triggered",
        "recovery_replay_decided",
    }:
        record = dict(payload.get("execution_record") or {})
        summary.update(
            {
                "execution_id": str(record.get("execution_id") or ""),
                "step_id": str(record.get("step_id") or ""),
                "operation_id": str(record.get("operation_id") or ""),
                "status": str(record.get("status") or ""),
                "replay_policy": str(record.get("replay_policy") or ""),
                "request_ref": str(record.get("request_ref") or ""),
                "result_ref": str(record.get("result_ref") or ""),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type in {"step_entered", "step_completed", "step_failed", "step_skipped"}:
        step_run = dict(payload.get("step_run") or {})
        summary.update(
            {
                "step_id": str(step_run.get("step_id") or ""),
                "step_kind": str(step_run.get("step_kind") or ""),
                "executor_type": str(step_run.get("executor_type") or ""),
                "status": str(step_run.get("status") or ""),
                "attempt_count": int(step_run.get("attempt_count") or 0),
                "failure_reason": str(step_run.get("failure_reason") or ""),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type == "task_run_ledger_updated":
        ledger = dict(payload.get("task_run_ledger") or {})
        step_runs = list(ledger.get("step_runs") or [])
        summary.update(
            {
                "ledger_id": str(ledger.get("ledger_id") or ""),
                "status": str(ledger.get("status") or ""),
                "current_step_id": str(ledger.get("current_step_id") or ""),
                "step_count": len(step_runs),
                "completed_step_count": sum(
                    1 for item in step_runs if str(dict(item).get("status") or "") in {"completed", "failed", "skipped"}
                ),
                "reason": str(payload.get("reason") or ""),
            }
        )
    elif event_type == "commit_gate_checked":
        decision = dict(payload.get("commit_decision") or payload.get("commit_gate") or {})
        candidate_payload = dict(dict(decision.get("commit_candidate") or {}).get("payload") or {})
        task_result = dict(candidate_payload.get("task_result") or {})
        summary.update(
            {
                "gate_id": str(decision.get("gate_id") or ""),
                "commit_type": str(decision.get("commit_type") or ""),
                "commit_allowed": bool(decision.get("commit_allowed") is True),
                "reason": str(decision.get("reason") or ""),
                "task_spec_ref": str(candidate_payload.get("task_spec_ref") or task_result.get("task_spec_ref") or ""),
                "template_id": str(candidate_payload.get("template_id") or task_result.get("template_id") or ""),
            }
        )
    elif event_type == "loop_terminal":
        task_result = dict(payload.get("task_result") or {})
        summary.update(
            {
                "status": str(payload.get("status") or ""),
                "terminal_reason": str(payload.get("terminal_reason") or ""),
                "final_content_chars": int(payload.get("final_content_chars") or 0),
                "task_result_ref": str(task_result.get("result_id") or ""),
                "template_id": str(task_result.get("template_id") or ""),
                "requested_outputs": list(task_result.get("requested_outputs") or []),
            }
        )
    elif event_type == "checkpoint_written":
        execution_summary = dict(payload.get("execution_summary") or {})
        runtime_objects_summary = dict(payload.get("runtime_objects_summary") or {})
        summary.update(
            {
                "checkpoint_id": str(payload.get("checkpoint_id") or ""),
                "event_offset": int(payload.get("event_offset") or 0),
                "execution_count": int(execution_summary.get("execution_count") or 0),
                "completed_count": int(execution_summary.get("completed_count") or 0),
                "reused_count": int(execution_summary.get("reused_count") or 0),
                "suppressed_count": int(execution_summary.get("suppressed_count") or 0),
                "agent_run_count": int(runtime_objects_summary.get("agent_run_count") or 0),
                "coordination_run_count": int(runtime_objects_summary.get("coordination_run_count") or 0),
            }
        )
    return summary


def _sanitize_payload(payload: Any, *, include_model_messages: bool) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if key_text == "model_messages" and not include_model_messages:
                sanitized[key_text] = _message_summaries(value)
                continue
            if key_text == "content":
                sanitized[key_text] = {"content_chars": len(str(value or ""))}
                continue
            sanitized[key_text] = _sanitize_payload(value, include_model_messages=include_model_messages)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(item, include_model_messages=include_model_messages) for item in payload]
    if isinstance(payload, tuple):
        return [_sanitize_payload(item, include_model_messages=include_model_messages) for item in payload]
    return payload


def _message_summaries(value: Any) -> list[dict[str, Any]]:
    messages = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        messages.append(
            {
                "role": str(item.get("role") or ""),
                "content_chars": len(str(item.get("content") or "")),
            }
        )
    return messages
