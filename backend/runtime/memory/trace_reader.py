from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from ..shared.checkpoint import RuntimeCheckpointStore
from ..shared.event_log import RuntimeEventLog
from ..shared.events import RuntimeEvent
from ..coordination_runtime.checkpoint_adapter import LangGraphCheckpointStoreAdapter
from ..shared.models import CoordinationRun, TaskRun
from .state_index import RuntimeStateIndex
from ..graph_runtime.run_monitor import build_task_graph_run_monitor_view
from .timeline_ledger import TimelineLedgerStore


@dataclass(frozen=True, slots=True)
class RuntimeLoopTraceReader:
    """Read-only view over TaskRunLoop event/checkpoint traces."""

    state_index: RuntimeStateIndex
    event_log: RuntimeEventLog
    checkpoints: RuntimeCheckpointStore
    coordination_checkpoints: LangGraphCheckpointStoreAdapter | None = None
    timeline_ledger: TimelineLedgerStore | None = None

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
            "authority": "runtime_trace_reader",
        }

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        task_runs = sorted(
            self.state_index.list_task_runs(),
            key=lambda item: (item.updated_at, item.created_at),
            reverse=True,
        )[: max(1, min(int(limit or 20), 100))]
        items = [self._task_run_live_summary(item) for item in task_runs]
        active_statuses = {"created", "running", "waiting_approval", "blocked"}
        waiting_statuses = {"waiting_approval", "blocked"}
        return {
            "authority": "runtime_live_monitor.global",
            "summary": {
                "total": len(items),
                "running": sum(1 for item in items if str(item.get("status") or "") in active_statuses),
                "waiting": sum(1 for item in items if str(item.get("status") or "") in waiting_statuses),
                "completed": sum(1 for item in items if str(item.get("status") or "") == "completed"),
                "failed": sum(1 for item in items if str(item.get("status") or "") in {"failed", "aborted"}),
            },
            "task_runs": items,
            "updated_at": time.time(),
        }

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        state_snapshot = self.state_index.read_session_monitor_snapshot(session_id)
        task_runs = _session_task_run_payloads(state_snapshot, session_id)
        latest = _pick_session_monitor_task_run_payload(task_runs, state_snapshot)
        monitor_index = dict(state_snapshot.get("monitor_index") or {})
        task_run_payloads = dict(state_snapshot.get("task_runs") or {})
        coordination_run_payloads = dict(state_snapshot.get("coordination_runs") or {})
        task_run_count = int(monitor_index.get("task_run_count") or len(task_runs))
        latest_coordination_task_run_id = str(monitor_index.get("latest_coordination_task_run_id") or "")
        if latest_coordination_task_run_id and (
            latest_coordination_task_run_id not in task_run_payloads
            or not _task_coordination_run_payloads(state_snapshot, latest_coordination_task_run_id)
        ):
            latest_coordination_task_run_id = ""
        latest_coordination_run_id = str(monitor_index.get("latest_coordination_run_id") or "")
        if latest_coordination_run_id and latest_coordination_run_id not in coordination_run_payloads:
            latest_coordination_run_id = ""
        return {
            "session_id": session_id,
            "task_run_count": task_run_count,
            "latest_task_run_id": str(latest.get("task_run_id") or "") if latest is not None else "",
            "latest_coordination_task_run_id": latest_coordination_task_run_id,
            "latest_coordination_run_id": latest_coordination_run_id,
            "project_runtime_status": (
                self.state_index.get_session_active_project_status(session_id).to_dict()
                if self.state_index.get_session_active_project_status(session_id) is not None
                else None
            ),
            "monitor": (
                self._get_task_run_live_monitor_from_snapshot(
                    str(latest.get("task_run_id") or ""),
                    state_snapshot=state_snapshot,
                )
                if latest is not None
                else None
            ),
            "authority": "runtime_live_monitor",
        }

    def _task_run_live_summary(self, task_run: TaskRun) -> dict[str, Any]:
        coordination_runs = self.state_index.list_task_coordination_runs(task_run.task_run_id)
        coordination_run = _pick_coordination_run(coordination_runs)
        project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "")
        project_status = self.state_index.get_project_runtime_status(project_id) if project_id else None
        events = self.event_log.list_events(task_run.task_run_id)
        latest_event = events[-1] if events else None
        active_node_id = ""
        graph_id = ""
        if coordination_run is not None:
            diagnostics = dict(coordination_run.diagnostics or {})
            graph_id = str(coordination_run.graph_ref or "")
            flow = dict(diagnostics.get("coordination_flow") or {})
            active_node_id = str(flow.get("current_stage_id") or "")
        return {
            "task_run_id": task_run.task_run_id,
            "session_id": task_run.session_id,
            "task_id": task_run.task_id,
            "title": str(dict(task_run.diagnostics or {}).get("title") or dict(task_run.diagnostics or {}).get("project_title") or task_run.task_id or task_run.task_run_id),
            "status": task_run.status,
            "terminal_reason": str(task_run.terminal_reason or ""),
            "created_at": float(task_run.created_at or 0.0),
            "updated_at": float(task_run.updated_at or 0.0),
            "elapsed_seconds": max(0.0, time.time() - float(task_run.created_at or time.time())),
            "latest_event_type": str(latest_event.event_type if latest_event is not None else ""),
            "latest_event_at": float(latest_event.created_at if latest_event is not None else task_run.updated_at or 0.0),
            "event_count": len(events),
            "coordination_run_id": coordination_run.coordination_run_id if coordination_run is not None else "",
            "coordination_status": coordination_run.status if coordination_run is not None else "",
            "graph_id": graph_id,
            "active_node_id": active_node_id,
            "project_id": project_id,
            "project_title": str(dict(task_run.diagnostics or {}).get("project_title") or ""),
            "project_runtime_status": project_status.to_dict() if project_status is not None else None,
            "has_coordination": coordination_run is not None,
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
            project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "")
            return build_task_graph_run_monitor_view(
                task_run=task_run.to_dict(),
                coordination_run=None,
                coordination_state={},
                task_checkpoint=task_checkpoint.to_dict() if task_checkpoint is not None else None,
                event_count=len(self.event_log.list_events(task_run_id)),
                recent_events=[item.to_dict() for item in self.event_log.list_events(task_run_id)[-120:]],
                source="task_run",
                project_ledger=(
                    self.state_index.get_project_progress_ledger(project_id).to_dict()
                    if project_id and self.state_index.get_project_progress_ledger(project_id) is not None
                    else None
                ),
                project_status=(
                    self.state_index.get_project_runtime_status(project_id).to_dict()
                    if project_id and self.state_index.get_project_runtime_status(project_id) is not None
                    else None
                ),
                supervision_records=[
                    item.to_dict() for item in self.state_index.list_project_supervision_records(project_id)[-10:]
                ] if project_id else None,
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
        if self.timeline_ledger is not None:
            coordination_state["timeline"] = self.timeline_ledger.snapshot(coordination_run_id, limit=80)
        project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "")
        root_events = self.event_log.list_events(task_run.task_run_id)
        stream_source_event_groups = self._coordination_stream_source_event_groups(
            root_task_run=task_run,
            coordination_state=coordination_state,
        )
        recent_events = _merge_recent_event_groups(
            [[item.to_dict() for item in root_events[-120:]], *stream_source_event_groups],
            limit=240,
        )
        return build_task_graph_run_monitor_view(
            task_run=task_run.to_dict(),
            coordination_run=coordination_run.to_dict(),
            coordination_state=coordination_state,
            coordination_checkpoint=coordination_checkpoint.to_dict() if coordination_checkpoint is not None else None,
            task_checkpoint=task_checkpoint.to_dict() if task_checkpoint is not None else None,
            event_count=len(root_events) + sum(len(group) for group in stream_source_event_groups),
            recent_events=recent_events,
            source="coordination_run",
            project_ledger=(
                self.state_index.get_project_progress_ledger(project_id).to_dict()
                if project_id and self.state_index.get_project_progress_ledger(project_id) is not None
                else None
            ),
            project_status=(
                self.state_index.get_project_runtime_status(project_id).to_dict()
                if project_id and self.state_index.get_project_runtime_status(project_id) is not None
                else None
            ),
            supervision_records=[
                item.to_dict() for item in self.state_index.list_project_supervision_records(project_id)[-10:]
            ] if project_id else None,
        )

    def _coordination_stream_source_event_groups(
        self,
        *,
        root_task_run: TaskRun,
        coordination_state: dict[str, Any],
    ) -> list[list[dict[str, Any]]]:
        """Collect recent output-port events from active TaskGraph node task runs.

        The coordination/root task run owns the graph, clock, and scheduler state,
        while each dispatched node executes as its own agent task run. Model text
        stream chunks are emitted by those child task runs, so the monitor must
        attach to the active node output ports instead of only reading the root log.
        """

        node_ids = _active_stream_node_ids(coordination_state)
        if not node_ids:
            return []
        selected: list[tuple[str, list[dict[str, Any]]]] = []
        task_runs = self.state_index.list_session_task_runs(root_task_run.session_id)
        for node_id in node_ids:
            candidates = [
                item
                for item in task_runs
                if item.task_run_id != root_task_run.task_run_id
                and _task_run_matches_graph_node(item, node_id)
            ]
            if not candidates:
                continue
            best = self._pick_best_stream_source_task_run(candidates)
            if best is None:
                continue
            events = [item.to_dict() for item in self.event_log.list_events(best.task_run_id)[-120:]]
            if events:
                selected.append((best.task_run_id, events))
        deduped: dict[str, list[dict[str, Any]]] = {}
        for task_run_id, events in selected:
            deduped[task_run_id] = events
        return list(deduped.values())

    def _pick_best_stream_source_task_run(self, task_runs: list[TaskRun]) -> TaskRun | None:
        ranked: list[tuple[float, int, float, str, TaskRun]] = []
        for item in task_runs:
            events = self.event_log.list_events(item.task_run_id)
            latest_model_event_at = max(
                (
                    float(event.created_at or 0.0)
                    for event in events
                    if str(event.event_type or "") == "model_item_received"
                ),
                default=0.0,
            )
            ranked.append(
                (
                    latest_model_event_at,
                    1 if latest_model_event_at > 0.0 else 0,
                    float(item.updated_at or item.created_at or 0.0),
                    item.task_run_id,
                    item,
                )
            )
        if not ranked:
            return None
        return max(ranked, key=lambda item: item[:4])[-1]

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
            if self.timeline_ledger is not None:
                coordination_state["timeline"] = self.timeline_ledger.snapshot(active_coordination_run_id, limit=80)
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
        if checkpoint is not None:
            loop_state["checkpoint_resume_state"] = dict(getattr(checkpoint, "resume_state", {}) or {})
        events = self.event_log.list_events(task_run_id)
        professional_task_summary = _professional_task_summary(
            task_run=task_run,
            loop_state=loop_state,
            events=events,
            checkpoint=checkpoint,
        )
        return {
            "task_run": task_run,
            "latest_checkpoint": _checkpoint_summary(checkpoint) if checkpoint is not None else None,
            "loop_state": _loop_state_summary(loop_state),
            "coordination_run": coordination_view,
            "professional_task_summary": professional_task_summary,
            "project_runtime_status": (
                self.state_index.get_project_runtime_status(str(dict(task_run).get("diagnostics", {}).get("project_id") or "")).to_dict()
                if str(dict(task_run).get("diagnostics", {}).get("project_id") or "")
                and self.state_index.get_project_runtime_status(str(dict(task_run).get("diagnostics", {}).get("project_id") or "")) is not None
                else None
            ),
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
            "authority": "runtime_live_monitor",
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
                    **_coordination_run_trace_payload(
                        item,
                        state_index=self.state_index,
                        include_payloads=include_payloads,
                    ),
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
            "authority": "runtime_trace_reader",
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
        "resume_state": dict(getattr(checkpoint, "resume_state", {}) or {}),
        "authority": checkpoint.authority,
    }


def _loop_state_summary(loop_state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(loop_state.get("diagnostics") or {})
    stage_request = dict(diagnostics.get("stage_execution_request") or {})
    pending_approval_state = dict(loop_state.get("pending_approval_state") or {})
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
        "pending_approval_state": pending_approval_state,
        "resume_state": dict(loop_state.get("resume_state") or {}),
        "checkpoint_resume_state": dict(loop_state.get("checkpoint_resume_state") or {}),
        "diagnostics": {
            "task_graph_run": bool(diagnostics.get("task_graph_run") is True),
            "task_graph_id": str(diagnostics.get("task_graph_id") or ""),
            "langgraph_coordination_initialized": bool(
                diagnostics.get("langgraph_coordination_initialized") is True
            ),
            "langgraph_checkpoint_ref": str(diagnostics.get("langgraph_checkpoint_ref") or ""),
            "active_stage_id": str(stage_request.get("stage_id") or ""),
            "pending_approval": bool(str(pending_approval_state.get("status") or "") == "pending"),
        },
        "authority": str(loop_state.get("authority") or "runtime_state"),
    }


def _professional_task_summary(
    *,
    task_run: dict[str, Any],
    loop_state: dict[str, Any],
    events: list[RuntimeEvent],
    checkpoint: Any,
) -> dict[str, Any] | None:
    started_event = _latest_runtime_event(events, "professional_task_started")
    plan_event = _latest_runtime_event(events, "professional_task_semantic_plan_drafted")
    state_event = _latest_runtime_event(events, "professional_task_state_changed")
    ledger_event = _latest_runtime_event(events, "professional_tool_observation_ledger_updated")
    session_event = _latest_runtime_event(events, "professional_run_session_updated")
    verification_event = _latest_runtime_event(events, "professional_task_deliverable_validation_checked")
    diagnostics = dict(loop_state.get("diagnostics") or {})
    is_professional_task = bool(
        started_event is not None
        or plan_event is not None
        or verification_event is not None
        or str(task_run.get("runtime_lane") or "") in {"role_interaction", "standard_task", "professional_task"}
        or str(loop_state.get("runtime_lane") or "") in {"role_interaction", "standard_task", "professional_task"}
        or str(loop_state.get("task_template_id") or "")
        in {"runtime.recipe.role_interaction", "runtime.recipe.standard_task", "runtime.recipe.professional_task"}
        or str(diagnostics.get("interaction_mode") or "")
    )
    if not is_professional_task:
        return None

    started_payload = dict(started_event.payload or {}) if started_event is not None else {}
    plan_payload = dict(plan_event.payload or {}) if plan_event is not None else {}
    state_payload = dict(state_event.payload or {}) if state_event is not None else {}
    ledger = _latest_task_run_ledger_from_events(events)
    current_step_id = str(
        dict(ledger).get("current_step_id")
        or loop_state.get("current_step_id")
        or ""
    )
    verification = _professional_verification_summary(verification_event)
    professional_run_state = _professional_run_state_summary(
        session_event=session_event,
        ledger_event=ledger_event,
        verification_event=verification_event,
        state_payload=state_payload,
        diagnostics=diagnostics,
    )
    tool_observation_ledger = _professional_tool_observation_ledger_summary(
        ledger_event=ledger_event,
        session_event=session_event,
        verification_event=verification_event,
    )
    professional_run_session = _professional_run_session_summary(session_event)
    observation = _professional_observation_summary(events)
    return {
        "available": True,
        "task_run_id": str(task_run.get("task_run_id") or loop_state.get("task_run_id") or ""),
        "runtime_driver": "professional_task_run",
        "interaction_mode": str(
            started_payload.get("interaction_mode")
            or plan_payload.get("interaction_mode")
            or diagnostics.get("interaction_mode")
            or ""
        ),
        "mode": str(
            started_payload.get("interaction_mode")
            or plan_payload.get("interaction_mode")
            or diagnostics.get("interaction_mode")
            or ""
        ),
        "goal": str(started_payload.get("goal") or ""),
        "state": str(
            professional_run_state.get("state")
            or state_payload.get("to_state")
            or diagnostics.get("professional_state")
            or ""
        ),
        "transition": {
            "from_state": str(state_payload.get("from_state") or ""),
            "to_state": str(state_payload.get("to_state") or ""),
            "terminal_reason": str(state_payload.get("terminal_reason") or ""),
        },
        "plan": {
            "source": str(plan_payload.get("plan_source") or ""),
            "ledger_backed": bool(plan_payload.get("ledger_backed") is True or bool(ledger)),
            "item_count": len(list(plan_payload.get("plan_items") or [])),
            "tool_execution_enabled": bool(plan_payload.get("tool_execution_enabled") is True),
            "delegation_enabled": bool(plan_payload.get("delegation_enabled") is True),
            "allowed_tool_names": [
                str(item)
                for item in list(plan_payload.get("allowed_tool_names") or [])
                if str(item)
            ],
        },
        "current_plan_item": _current_plan_item_summary(ledger, current_step_id=current_step_id),
        "progress": _professional_ledger_progress(ledger, current_step_id=current_step_id),
        "observation": observation,
        "verification": verification,
        "professional_run_state": professional_run_state,
        "professional_run_session": professional_run_session,
        "tool_observation_ledger": tool_observation_ledger,
        "blocker": _professional_task_blocker(
            task_run=task_run,
            loop_state=loop_state,
            events=events,
            verification=verification,
        ),
        "latest_checkpoint": (
            {
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "created_at": checkpoint.created_at,
            }
            if checkpoint is not None
            else None
        ),
        "latest_event": (
            {
                "event_id": events[-1].event_id,
                "event_type": events[-1].event_type,
                "offset": events[-1].offset,
                "created_at": events[-1].created_at,
            }
            if events
            else None
        ),
        "authority": "runtime_professional_task_summary",
    }


def _latest_runtime_event(events: list[RuntimeEvent], event_type: str) -> RuntimeEvent | None:
    for event in reversed(events):
        if str(event.event_type or "") == event_type:
            return event
    return None


def _latest_task_run_ledger_from_events(events: list[RuntimeEvent]) -> dict[str, Any]:
    for event in reversed(events):
        payload = dict(event.payload or {})
        ledger = dict(payload.get("task_run_ledger") or {})
        if ledger:
            return ledger
    return {}


def _professional_run_state_summary(
    *,
    session_event: RuntimeEvent | None,
    ledger_event: RuntimeEvent | None,
    verification_event: RuntimeEvent | None,
    state_payload: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    state = _first_record_payload(
        (
            session_event,
            "professional_run_state",
        ),
        (
            ledger_event,
            "professional_run_state",
        ),
        (
            verification_event,
            "verification.professional_run_state",
        ),
    )
    transitions = [
        dict(item)
        for item in list(state.get("transitions") or [])
        if isinstance(item, dict)
    ]
    latest_transition = transitions[-1] if transitions else {}
    return {
        "run_state_id": str(state.get("run_state_id") or ""),
        "task_run_id": str(state.get("task_run_id") or ""),
        "state": str(
            state.get("state")
            or state_payload.get("to_state")
            or diagnostics.get("professional_state")
            or ""
        ),
        "transition_count": len(transitions),
        "latest_transition": {
            "from_state": str(latest_transition.get("from_state") or ""),
            "to_state": str(latest_transition.get("to_state") or ""),
            "reason": str(latest_transition.get("reason") or ""),
            "evidence_refs": [
                str(item)
                for item in list(latest_transition.get("evidence_refs") or [])
                if str(item)
            ],
        } if latest_transition else {},
        "unsatisfied_obligations": [
            str(item)
            for item in list(state.get("unsatisfied_obligations") or [])
            if str(item)
        ],
        "blocked_reason": str(state.get("blocked_reason") or ""),
        "diagnostics": dict(state.get("diagnostics") or {}),
        "authority": str(state.get("authority") or "orchestration.professional_run_state"),
    }


def _professional_tool_observation_ledger_summary(
    *,
    ledger_event: RuntimeEvent | None,
    session_event: RuntimeEvent | None,
    verification_event: RuntimeEvent | None,
) -> dict[str, Any]:
    ledger_payload = _first_record_payload(
        (
            ledger_event,
            "tool_observation_ledger",
        ),
        (
            session_event,
            "tool_observation_ledger",
        ),
        (
            verification_event,
            "verification.tool_observation_ledger",
        ),
    )
    event_summary = _first_record_payload(
        (
            ledger_event,
            "summary",
        ),
    )
    records = [
        dict(item)
        for item in list(ledger_payload.get("records") or [])
        if isinstance(item, dict)
    ]
    computed_summary = {
        "record_count": len(records),
        "read_count": sum(1 for item in records if str(item.get("side_effect_kind") or "") == "read"),
        "write_count": sum(1 for item in records if str(item.get("side_effect_kind") or "") == "write"),
        "verification_count": sum(1 for item in records if str(item.get("side_effect_kind") or "") == "verification"),
        "delegation_count": sum(1 for item in records if str(item.get("side_effect_kind") or "") == "delegation"),
        "satisfied_obligations": sorted(
            {
                str(obligation)
                for item in records
                for obligation in list(item.get("satisfies") or [])
                if str(obligation)
            }
        ),
    }
    summary = {**computed_summary, **event_summary}
    latest_record = records[-1] if records else {}
    return {
        "ledger_id": str(ledger_payload.get("ledger_id") or ""),
        "task_run_id": str(ledger_payload.get("task_run_id") or ""),
        "summary": summary,
        "latest_record": _tool_observation_record_summary(latest_record) if latest_record else {},
        "authority": str(ledger_payload.get("authority") or "orchestration.tool_observation_ledger"),
    }


def _tool_observation_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    args = dict(record.get("tool_args") or {})
    return {
        "observation_ref": str(record.get("observation_ref") or ""),
        "tool_name": str(record.get("tool_name") or ""),
        "side_effect_kind": str(record.get("side_effect_kind") or ""),
        "satisfies": [
            str(item)
            for item in list(record.get("satisfies") or [])
            if str(item)
        ],
        "side_effect_hash": str(record.get("side_effect_hash") or ""),
        "tool_args_keys": sorted(str(key) for key in args.keys()),
        "result_preview": str(record.get("result_preview") or "")[:240],
        "authority": str(record.get("authority") or "orchestration.tool_observation_record"),
    }


def _professional_run_session_summary(session_event: RuntimeEvent | None) -> dict[str, Any]:
    session = _first_record_payload((session_event, "professional_run_session"))
    if not session:
        return {}
    return {
        "session_id": str(session.get("session_id") or ""),
        "task_run_id": str(session.get("task_run_id") or ""),
        "interaction_mode": str(session.get("interaction_mode") or ""),
        "state_ref": str(session.get("state_ref") or ""),
        "tool_observation_ledger_ref": str(session.get("tool_observation_ledger_ref") or ""),
        "resume_decision": dict(session.get("resume_decision") or {}),
        "execution_obligation": dict(session.get("execution_obligation") or {}),
        "authority": str(session.get("authority") or "orchestration.professional_run_session"),
    }


def _first_record_payload(*candidates: tuple[RuntimeEvent | None, str]) -> dict[str, Any]:
    for event, dotted_key in candidates:
        payload = _payload_by_dotted_key(dict(event.payload or {}) if event is not None else {}, dotted_key)
        if payload:
            return payload
    return {}


def _payload_by_dotted_key(payload: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    current: Any = payload
    for part in [item for item in str(dotted_key or "").split(".") if item]:
        if not isinstance(current, dict):
            return {}
        current = current.get(part)
    return dict(current or {}) if isinstance(current, dict) else {}


def _professional_ledger_progress(ledger: dict[str, Any], *, current_step_id: str) -> dict[str, Any]:
    step_runs = [dict(item) for item in list(dict(ledger or {}).get("step_runs") or []) if isinstance(item, dict)]
    return {
        "ledger_id": str(dict(ledger or {}).get("ledger_id") or ""),
        "ledger_status": str(dict(ledger or {}).get("status") or ""),
        "current_step_id": str(current_step_id or dict(ledger or {}).get("current_step_id") or ""),
        "step_count": len(step_runs),
        "plan_item_count": sum(1 for item in step_runs if _is_professional_plan_step(item)),
        "completed_count": sum(1 for item in step_runs if str(item.get("status") or "") == "completed"),
        "running_count": sum(1 for item in step_runs if str(item.get("status") or "") == "running"),
        "pending_count": sum(1 for item in step_runs if str(item.get("status") or "") == "pending"),
        "failed_count": sum(1 for item in step_runs if str(item.get("status") or "") == "failed"),
        "skipped_count": sum(1 for item in step_runs if str(item.get("status") or "") == "skipped"),
    }


def _current_plan_item_summary(ledger: dict[str, Any], *, current_step_id: str) -> dict[str, Any]:
    step_runs = [dict(item) for item in list(dict(ledger or {}).get("step_runs") or []) if isinstance(item, dict)]
    if not step_runs:
        return {}
    selected = None
    if current_step_id:
        selected = next((item for item in step_runs if str(item.get("step_id") or "") == current_step_id), None)
    if selected is None:
        selected = next((item for item in step_runs if str(item.get("status") or "") == "running"), None)
    if selected is None:
        selected = next((item for item in step_runs if str(item.get("status") or "") == "pending"), None)
    if selected is None:
        selected = step_runs[-1]
    diagnostics = dict(selected.get("diagnostics") or {})
    plan_item = dict(diagnostics.get("plan_item") or {})
    return {
        "step_id": str(selected.get("step_id") or ""),
        "title": str(selected.get("title") or ""),
        "status": str(selected.get("status") or ""),
        "step_kind": str(selected.get("step_kind") or ""),
        "executor_type": str(selected.get("executor_type") or ""),
        "action_kind": str(plan_item.get("action_kind") or ""),
        "summary": str(plan_item.get("summary") or ""),
        "attempt_count": int(selected.get("attempt_count") or 0),
        "failure_reason": str(selected.get("failure_reason") or ""),
        "required_operations": [
            str(item)
            for item in list(selected.get("required_operations") or [])
            if str(item)
        ],
        "observation_ref_count": len(list(selected.get("observation_refs") or [])),
        "output_ref_count": len(list(selected.get("output_refs") or [])),
    }


def _is_professional_plan_step(step_run: dict[str, Any]) -> bool:
    diagnostics = dict(step_run.get("diagnostics") or {})
    return bool(
        str(step_run.get("step_kind") or "") == "plan_item"
        or dict(diagnostics.get("plan_item") or {})
        or str(step_run.get("step_id") or "").startswith("professional.")
        
    )


def _professional_observation_summary(events: list[RuntimeEvent]) -> dict[str, Any]:
    tool_call_events = [event for event in events if str(event.event_type or "") == "tool_call_requested"]
    observation_events = [
        event
        for event in events
        if _executor_observation_payload(event).get("observation_type") == "tool_result"
    ]
    delegation_events = [
        event
        for event in events
        if str(event.event_type or "") in {
            "agent_delegation_requested",
            "agent_delegation_result_created",
            "agent_delegation_parent_observation_created",
        }
    ]
    delegation_observations = [
        event
        for event in observation_events
        if str(dict(_executor_observation_payload(event).get("payload") or {}).get("tool_name") or "") == "delegate_to_agent"
    ]
    latest_observation = observation_events[-1] if observation_events else None
    latest_payload = _executor_observation_payload(latest_observation) if latest_observation is not None else {}
    latest_tool_payload = dict(latest_payload.get("payload") or {})
    return {
        "tool_call_count": len(tool_call_events),
        "tool_observation_count": len(observation_events),
        "delegation_event_count": len(delegation_events),
        "delegation_observation_count": len(delegation_observations),
        "latest_observation": (
            {
                "event_id": latest_observation.event_id,
                "observation_type": str(latest_payload.get("observation_type") or ""),
                "source": str(latest_payload.get("source") or ""),
                "tool_name": str(latest_tool_payload.get("tool_name") or ""),
                "content_chars": int(latest_payload.get("content_chars") or 0),
                "created_at": latest_observation.created_at,
            }
            if latest_observation is not None
            else None
        ),
    }


def _executor_observation_payload(event: RuntimeEvent | None) -> dict[str, Any]:
    if event is None or str(event.event_type or "") != "executor_observation_received":
        return {}
    payload = dict(event.payload or {})
    observation = dict(payload.get("observation") or {})
    if not observation:
        return {}
    return observation


def _professional_verification_summary(event: RuntimeEvent | None) -> dict[str, Any]:
    if event is None:
        return {"status": "not_run", "passed": False}
    verification = dict(dict(event.payload or {}).get("verification") or {})
    passed = bool(verification.get("passed") is True)
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "mode": str(verification.get("mode") or ""),
        "checks": dict(verification.get("checks") or {}),
        "event_id": event.event_id,
        "created_at": event.created_at,
    }


def _professional_task_blocker(
    *,
    task_run: dict[str, Any],
    loop_state: dict[str, Any],
    events: list[RuntimeEvent],
    verification: dict[str, Any],
) -> dict[str, Any]:
    loop_error = _latest_runtime_event(events, "loop_error")
    if loop_error is not None:
        payload = dict(loop_error.payload or {})
        return {
            "kind": str(payload.get("error") or "loop_error"),
            "summary": str(payload.get("message") or payload.get("reason") or "Runtime loop emitted an error."),
            "event_id": loop_error.event_id,
        }
    status = str(task_run.get("status") or loop_state.get("status") or "")
    terminal_reason = str(task_run.get("terminal_reason") or loop_state.get("terminal_reason") or "")
    if status in {"blocked", "failed", "aborted"}:
        return {
            "kind": terminal_reason or status,
            "summary": f"Task run status is {status}.",
            "event_id": "",
        }
    if terminal_reason and terminal_reason not in {"completed", "waiting_approval"}:
        return {
            "kind": terminal_reason,
            "summary": f"Task run terminal reason is {terminal_reason}.",
            "event_id": "",
        }
    if str(verification.get("status") or "") == "failed":
        return {
            "kind": "verification_failed",
            "summary": "Autonomous task verification did not pass.",
            "event_id": str(verification.get("event_id") or ""),
        }
    return {}


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
    batch_lifecycle = _batch_lifecycle_summary(
        dict(
            state.get("batch_lifecycle_runtime_state")
            or dict(state.get("diagnostics") or {}).get("batch_lifecycle_runtime_state")
            or {}
        )
    )
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
        "batch_lifecycle_runtime_state": batch_lifecycle,
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


def _batch_lifecycle_summary(state: dict[str, Any]) -> dict[str, Any]:
    if str(state.get("authority") or "") != "task_system.batch_lifecycle_runtime_state":
        return {"available": False}
    batches = [dict(item) for item in list(state.get("batch_states") or []) if isinstance(item, dict)]
    plans = [dict(item) for item in list(state.get("plan_states") or []) if isinstance(item, dict)]
    instances = [dict(item) for item in list(state.get("batch_execution_instances") or []) if isinstance(item, dict)]
    return {
        "available": True,
        "authority": str(state.get("authority") or ""),
        "mode": str(state.get("mode") or ""),
        "graph_id": str(state.get("graph_id") or ""),
        "summary": dict(state.get("summary") or {}),
        "ready_batch_ids": list(state.get("ready_batch_ids") or []),
        "running_batch_ids": list(state.get("running_batch_ids") or []),
        "committed_batch_ids": list(state.get("committed_batch_ids") or []),
        "failed_batch_ids": list(state.get("failed_batch_ids") or []),
        "active_batch_by_node": dict(state.get("active_batch_by_node") or {}),
        "active_execution_by_node": dict(state.get("active_execution_by_node") or {}),
        "active_execution_by_batch": dict(state.get("active_execution_by_batch") or {}),
        "execution_mode_by_plan": dict(state.get("execution_mode_by_plan") or {}),
        "plans": [
            {
                "plan_id": str(item.get("plan_id") or ""),
                "node_id": str(item.get("node_id") or ""),
                "status": str(item.get("status") or ""),
                "unit_kind": str(item.get("unit_kind") or ""),
                "batch_count": int(item.get("batch_count") or 0),
                "committed_batch_count": int(item.get("committed_batch_count") or 0),
                "failed_batch_count": int(item.get("failed_batch_count") or 0),
                "active_batch_id": str(item.get("active_batch_id") or ""),
            }
            for item in plans
        ],
        "batches": [
            {
                "batch_id": str(item.get("batch_id") or ""),
                "plan_id": str(item.get("plan_id") or ""),
                "node_id": str(item.get("node_id") or ""),
                "sequence_index": int(item.get("sequence_index") or 0),
                "unit_kind": str(item.get("unit_kind") or ""),
                "range": dict(item.get("range") or {}),
                "status": str(item.get("status") or ""),
                "attempt_index": int(item.get("attempt_index") or 0),
                "repair_round": int(item.get("repair_round") or 0),
                "last_result_ref": str(item.get("last_result_ref") or ""),
                "last_verdict": str(item.get("last_verdict") or ""),
            }
            for item in batches[-80:]
        ],
        "execution_instances": [
            {
                "execution_id": str(item.get("execution_id") or ""),
                "batch_id": str(item.get("batch_id") or ""),
                "plan_id": str(item.get("plan_id") or ""),
                "node_id": str(item.get("node_id") or ""),
                "status": str(item.get("status") or ""),
                "attempt_index": int(item.get("attempt_index") or 0),
                "repair_round": int(item.get("repair_round") or 0),
                "request_id": str(item.get("request_id") or ""),
                "dispatch_event_id": str(item.get("dispatch_event_id") or ""),
                "result_ref": str(item.get("result_ref") or ""),
                "verdict": str(item.get("verdict") or ""),
            }
            for item in instances[-120:]
        ],
        "merge_states": [
            {
                "merge_id": str(item.get("merge_id") or ""),
                "plan_id": str(item.get("plan_id") or ""),
                "node_id": str(item.get("node_id") or ""),
                "status": str(item.get("status") or ""),
                "mode": str(item.get("mode") or ""),
                "ready_condition": str(item.get("ready_condition") or ""),
            }
            for item in list(state.get("merge_states") or [])
            if isinstance(item, dict)
        ],
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


def _active_stream_node_ids(coordination_state: dict[str, Any]) -> list[str]:
    state = dict(coordination_state or {})
    diagnostics = dict(state.get("diagnostics") or {})
    scheduler_state = dict(
        state.get("task_graph_scheduler_state")
        or diagnostics.get("task_graph_scheduler_state")
        or {}
    )
    stage_request = dict(state.get("stage_execution_request") or {})
    dispatch_context = dict(stage_request.get("dispatch_context") or {})
    values: list[str] = [
        str(state.get("active_stage_id") or ""),
        str(state.get("active_node_id") or ""),
        str(stage_request.get("stage_id") or ""),
        str(stage_request.get("node_id") or ""),
        str(dispatch_context.get("stage_id") or ""),
        str(dispatch_context.get("node_id") or ""),
    ]
    values.extend(_string_items(state.get("running_nodes")))
    values.extend(_string_items(scheduler_state.get("running_nodes")))
    values.extend(_string_items(state.get("ready_nodes")) if not any(values) else [])
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _task_run_matches_graph_node(task_run: TaskRun, node_id: str) -> bool:
    target = str(node_id or "").strip()
    if not target:
        return False
    values = [
        str(task_run.task_id or ""),
        str(task_run.task_contract_ref or ""),
    ]
    diagnostics = dict(task_run.diagnostics or {})
    values.extend(
        [
            str(diagnostics.get("stage_id") or ""),
            str(diagnostics.get("node_id") or ""),
            str(diagnostics.get("active_stage_id") or ""),
            str(diagnostics.get("active_node_id") or ""),
            str(diagnostics.get("task_ref") or ""),
        ]
    )
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        if cleaned == target or cleaned.endswith(f".{target}"):
            return True
        if target in _identifier_segments(cleaned):
            return True
    return False


def _identifier_segments(value: str) -> set[str]:
    text = str(value or "")
    for separator in (":", "/", "\\", ".", "|"):
        text = text.replace(separator, "\n")
    return {item.strip() for item in text.splitlines() if item.strip()}


def _merge_recent_event_groups(
    event_groups: list[list[dict[str, Any]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in event_groups:
        for item in group:
            event = dict(item or {})
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            events.append(event)
    return sorted(
        events,
        key=lambda item: (
            float(dict(item).get("created_at") or 0.0),
            int(dict(item).get("offset") or 0),
            str(dict(item).get("event_id") or ""),
        ),
    )[-max(int(limit or 0), 1):]


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item)]


def _pick_session_monitor_task_run_payload(
    task_runs: list[dict[str, Any]],
    state_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    if not task_runs:
        return None
    monitor_index = dict(state_snapshot.get("monitor_index") or {})
    freshest_task_run_id = str(monitor_index.get("freshest_task_run_id") or "")
    if freshest_task_run_id:
        for item in task_runs:
            if str(item.get("task_run_id") or "") == freshest_task_run_id:
                return item
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


def _coordination_run_trace_payload(
    coordination_run: CoordinationRun,
    *,
    state_index: RuntimeStateIndex,
    include_payloads: bool,
) -> dict[str, Any]:
    payload = coordination_run.to_dict()
    diagnostics = dict(payload.get("diagnostics") or {})
    graph_spec_ref = str(diagnostics.get("coordination_graph_spec_ref") or "")
    if include_payloads and graph_spec_ref and "coordination_graph_spec" not in diagnostics:
        graph_spec = state_index.runtime_objects.get_object(graph_spec_ref)
        if graph_spec:
            diagnostics["coordination_graph_spec"] = graph_spec
    payload["diagnostics"] = diagnostics
    return payload


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
    elif event_type == "model_item_received":
        summary.update(
            {
                "stream_ref": str(payload.get("stream_ref") or ""),
                "delta_index": int(payload.get("delta_index") or 0),
                "delta_chars": int(payload.get("delta_chars") or 0),
                "accumulated_chars": int(payload.get("accumulated_chars") or 0),
                "delta_preview": str(payload.get("delta_preview") or ""),
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
