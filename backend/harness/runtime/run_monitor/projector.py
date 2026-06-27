from __future__ import annotations

from typing import Any

from artifact_system.artifact_authority import artifact_refs_from_events, dedupe_artifact_refs
from harness.loop.task_launch_gate import public_pending_launch_gate
from harness.task_run_state_view import task_run_state_view
from harness.task_run_status import runtime_control_state_from_task_run
from harness.runtime.event_query import list_runtime_events, runtime_event_count
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.session_output_commit_projection import project_session_output_commit_state

from .activity import RuntimeActivityControlContext, activity_is_monitor_visible, activity_sort_rank, with_runtime_activity
from .contract import build_envelope, build_navigation_target, build_task_detail_envelope, monitor_revision
from .lifecycle import (
    BLOCKED_TASK_RUN_STATUSES,
    COMPLETED_TASK_RUN_STATUSES,
    FAILED_TASK_RUN_STATUSES,
    GLOBAL_MONITOR_BUCKETS,
    KNOWN_TASK_RUN_STATUSES,
    RUNNING_TASK_RUN_STATUSES,
    TERMINAL_TASK_RUN_STATUSES,
    WAITING_TASK_RUN_STATUSES,
    ended_at,
    is_terminal_status,
    monitor_bucket,
    task_lifecycle,
)


TRACE_ONLY_PRESENTATION_SOURCES = {
    "runtime.protocol_repair",
    "system.tool_call_status",
    "system.user_steer_status",
    "tool_observation.summary",
}


class RuntimeMonitorProjector:
    def __init__(
        self,
        event_log: Any,
        *,
        runtime_host: Any | None = None,
        freshness_seconds: float = 5 * 60.0,
        resource_resolver: Any | None = None,
        session_scope_resolver: Any | None = None,
        observability_query: Any | None = None,
        fact_ledger: Any | None = None,
        trace_service: Any | None = None,
    ) -> None:
        self.event_log = event_log
        self.runtime_host = runtime_host
        self.freshness_seconds = float(freshness_seconds)
        self.resource_resolver = resource_resolver
        self.session_scope_resolver = session_scope_resolver
        self.observability_query = observability_query
        self.fact_ledger = fact_ledger
        self.trace_service = trace_service

    def project_task_run(
        self,
        task_run: Any,
        *,
        now: float,
        include_runtime_details: bool = True,
        include_graph_runtime: bool = True,
    ) -> dict[str, Any]:
        current_time = float(now)
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        session_id = str(getattr(task_run, "session_id", "") or "")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        events = list_runtime_events(self.event_log, task_run_id, limit=240, prefer_window=False) if include_runtime_details else []
        session_output_commit = project_session_output_commit_state(
            events,
            diagnostics=diagnostics,
            task_run=task_run,
            authority="runtime_monitor.session_output_commit",
        )
        latest_event = _public_runtime_event(events[-1]) if events else {}
        latest_step = self._latest_step_summary(events) if include_runtime_details else self._latest_step_from_diagnostics(diagnostics)
        latest_public_step = self._latest_public_step_summary(events) if include_runtime_details else latest_step
        latest_interaction_turn_id = _latest_interaction_turn_id(events, diagnostics=diagnostics) if include_runtime_details else str(diagnostics.get("latest_interaction_turn_id") or diagnostics.get("turn_id") or "")
        event_count = runtime_event_count(self.event_log, task_run_id, fallback=len(events)) if include_runtime_details else int(diagnostics.get("event_count") or 0)
        created_at = float(getattr(task_run, "created_at", 0.0) or 0.0)
        updated_at = float(getattr(task_run, "updated_at", 0.0) or 0.0)
        latest_event_at = float(latest_event.get("created_at") or updated_at or 0.0)
        last_activity_at = max(created_at, updated_at, latest_event_at)
        last_activity_age_seconds = max(0.0, current_time - last_activity_at) if last_activity_at else 0.0
        status = str(getattr(task_run, "status", "") or "")
        pending_launch_gate = public_pending_launch_gate(dict(diagnostics.get("pending_launch_gate") or {})) if isinstance(diagnostics.get("pending_launch_gate"), dict) else {}
        state_view = task_run_state_view(task_run, runtime_host=self.runtime_host)
        control = dict(state_view.get("runtime_control") or {})
        control_state = str(state_view.get("control_state") or "")
        control_capability = dict(state_view.get("control_capability") or {})
        activity = dict(state_view.get("activity") or {})
        terminal = is_terminal_status(status)
        route = self._route(task_run, diagnostics)
        session_scope = self._session_scope(task_run, diagnostics)
        graph_id = str(route.get("graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_config_id = str(diagnostics.get("graph_config_id") or "")
        kind = self._kind_from_route(route)
        graph_monitor = self._graph_monitor(graph_run_id, graph_config_id) if kind == "task_graph" and include_graph_runtime else None
        graph_status = self._graph_status(graph_monitor, graph_id=graph_id, graph_run_id=graph_run_id) if kind == "task_graph" else None
        graph_runtime_active = (
            kind == "task_graph"
            and graph_monitor is not None
            and _graph_monitor_has_active_runtime(graph_monitor)
        )
        stale = control_state != "paused" and status in RUNNING_TASK_RUN_STATUSES | {"waiting_executor"} and (
            not last_activity_at or last_activity_age_seconds > self.freshness_seconds
        )
        if stale and graph_runtime_active:
            stale = False
        action_required = status in {"waiting_approval"} | BLOCKED_TASK_RUN_STATUSES or control_state == "paused"
        diagnostic_reasons = self._diagnostic_reasons(
            task_run=task_run,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            latest_event=latest_event,
            last_activity_at=last_activity_at,
            route=route,
            stale=stale,
            control_state=control_state,
        )
        lifecycle = "stale" if diagnostic_reasons else task_lifecycle(status, stale=stale, action_required=action_required, control_state=control_state)
        bucket = "diagnostics" if diagnostic_reasons else monitor_bucket(lifecycle)
        resource_class = "dynamic" if bucket == "running" and not terminal else "static"
        ended = ended_at(status=status, updated_at=updated_at, last_activity_at=last_activity_at, resource_class=resource_class)
        duration_end_at = current_time if resource_class == "dynamic" else ended
        duration_seconds = max(0.0, duration_end_at - created_at) if created_at and duration_end_at else 0.0
        title = self._display_title(task_run, diagnostics, lifecycle=lifecycle)
        diagnostic_summary = self._diagnostic_summary(
            diagnostic_reasons=diagnostic_reasons,
            latest_step=latest_step,
            last_activity_age_seconds=last_activity_age_seconds,
        )
        agent_brief = public_runtime_progress_summary(latest_public_step.get("agent_brief_output") or "")
        artifact_refs = dedupe_artifact_refs(
            [
                *[dict(item) for item in list(diagnostics.get("artifact_refs") or []) if isinstance(item, dict)],
                *(_artifact_refs_from_event_log(self.event_log, task_run_id) if include_runtime_details else []),
            ]
        )
        diagnostic_public_progress = public_runtime_progress_summary(
            diagnostics.get("latest_public_progress_note")
            or diagnostics.get("latest_current_judgment")
            or ""
        )
        public_step_summary = public_runtime_progress_summary(
            latest_public_step.get("summary")
            or latest_public_step.get("public_progress_note")
            or latest_public_step.get("current_judgment")
            or ""
        )
        public_step_note = public_runtime_progress_summary(
            latest_public_step.get("public_progress_note")
            or latest_public_step.get("current_judgment")
            or latest_public_step.get("summary")
            or ""
        )
        summary = diagnostic_summary or agent_brief or public_step_summary or diagnostic_public_progress
        latest_public_progress_note = diagnostic_summary or public_step_note or diagnostic_public_progress or summary
        task_instance_id = graph_run_id if kind == "task_graph" and graph_run_id else task_run_id
        resource_refs = self._resource_refs(
            task_run_id=task_run_id,
            session_id=session_id,
            graph_run_id=graph_run_id,
            graph_config_id=graph_config_id,
            artifact_refs=artifact_refs,
            resolve_availability=include_runtime_details,
        )
        child_runtime_refs = self._child_runtime_refs(graph_monitor) if include_runtime_details and kind == "task_graph" else []
        if include_runtime_details:
            fact_summary = self._fact_summary(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id)
            trace_summary = self._trace_summary(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                hydrate=True,
            )
            diagnostic_signal_refs = self._diagnostic_signal_refs(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                fact_summary=fact_summary,
                trace_summary=trace_summary,
            )
        else:
            fact_summary = self._deferred_fact_summary(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id)
            trace_summary = self._deferred_trace_summary(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id)
            diagnostic_signal_refs = []
        latest_progress = {
            "tool_status": str(latest_step.get("tool_status") or diagnostics.get("latest_tool_status") or ""),
            "observation": "",
            "current_judgment": public_runtime_progress_summary(
                "" if diagnostic_summary else latest_public_step.get("current_judgment") or diagnostics.get("latest_current_judgment") or ""
            ),
            "next_action": public_runtime_progress_summary(
                "" if diagnostic_summary else latest_public_step.get("next_action") or diagnostics.get("latest_next_action") or ""
            ),
            "completion_status": str(latest_public_step.get("completion_status") or diagnostics.get("latest_completion_status") or ""),
            "open_risks": [],
            "evidence_refs": [],
            "summary": summary,
            "agent_brief": agent_brief,
            "source": "runtime_diagnostic" if diagnostic_summary else "runtime_monitor",
        }
        navigation_target = build_navigation_target(
            kind=kind,
            task_instance_id=task_instance_id,
            task_run_id=task_run_id,
            session_id=session_id,
            session_scope=session_scope,
            graph_run_id=graph_run_id,
            graph_id=graph_id,
            focus_node_id=str((graph_status or {}).get("active_node_id") or diagnostics.get("active_node_id") or diagnostics.get("node_id") or ""),
        )
        has_graph_run = bool(graph_run_id or graph_config_id)
        item = {
            "task_run_id": task_run_id,
            "session_id": session_id,
            "task_id": str(getattr(task_run, "task_id", "") or ""),
            "execution_runtime_kind": str(getattr(task_run, "execution_runtime_kind", "") or ""),
            "task_instance_id": task_instance_id,
            "root_task_run_id": task_run_id,
            "kind": kind,
            "title": title,
            "status": status,
            "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
            "lifecycle": lifecycle,
            "bucket": bucket,
            "resource_class": resource_class,
            "started_at": created_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "ended_at": ended,
            "duration_seconds": duration_seconds,
            "elapsed_seconds": duration_seconds,
            "runtime_seconds": duration_seconds,
            "runtime_end_at": ended,
            "last_activity_at": last_activity_at,
            "last_activity_age_seconds": last_activity_age_seconds,
            "action_required": action_required,
            "terminal": terminal,
            "stale": bool(stale or diagnostic_reasons),
            "diagnostic_reasons": diagnostic_reasons,
            "runtime_control": control,
            "control_state": control_state,
            "task_work_state": str(state_view.get("task_work_state") or ""),
            "executor_status": str(state_view.get("executor_status") or ""),
            "executor_lease_state": str(state_view.get("executor_lease_state") or ""),
            "wait_reason": str(diagnostics.get("wait_reason") or ""),
            "recovery_action": str(state_view.get("recovery_action") or ""),
            "recovery_cause": str(state_view.get("recovery_cause") or ""),
            "recoverable": bool(state_view.get("recoverable")),
            "graph_controlled": bool(state_view.get("graph_controlled")),
            "running_claimed": bool(state_view.get("running_claimed")),
            "can_pause": bool(state_view.get("can_pause")),
            "can_resume": bool(state_view.get("can_resume")),
            "can_stop": bool(state_view.get("can_stop")),
            "resume_mode": str(state_view.get("resume_mode") or ""),
            "activity_state": str(activity.get("activity_state") or ""),
            "activity_label": str(activity.get("activity_label") or ""),
            "is_resumable": bool(control_capability.get("can_resume_task", state_view.get("can_resume"))),
            "is_interruptible": bool(control_capability.get("can_pause_task", state_view.get("can_pause"))),
            "control_reason": str(control_capability.get("control_reason") or state_view.get("control_reason") or ""),
            "activity": activity,
            "control_capability": control_capability,
            "is_live": resource_class == "dynamic",
            "summary": summary,
            "latest_progress": latest_progress,
            **({"session_output_commit": session_output_commit} if session_output_commit else {}),
            "latest_event_type": str(latest_event.get("event_type") or ""),
            "latest_event_at": latest_event_at,
            "latest_event": latest_event,
            "latest_step": latest_step,
            "latest_step_summary": summary,
            "latest_public_progress_note": latest_public_progress_note,
            "latest_interaction_turn_id": latest_interaction_turn_id,
            "agent_brief_output": agent_brief,
            "latest_step_name": str(latest_step.get("step") or diagnostics.get("latest_step") or ""),
            "latest_step_status": str(latest_step.get("status") or diagnostics.get("latest_step_status") or ""),
            **({"pending_launch_gate": pending_launch_gate} if pending_launch_gate else {}),
            "artifact_count": len(artifact_refs),
            "artifact_refs": artifact_refs[:10],
            "resource_refs": resource_refs,
            "primary_resource_ref": resource_refs[0] if resource_refs else None,
            "fact_summary": fact_summary,
            "trace_summary": trace_summary,
            "diagnostic_signal_refs": diagnostic_signal_refs,
            "graph_status": graph_status,
            "child_runtime_refs": child_runtime_refs,
            "navigation_target": navigation_target,
            "pending_user_steer_count": int(diagnostics.get("pending_user_steer_count") or 0),
            "latest_user_steer_ref": str(diagnostics.get("latest_user_steer_ref") or ""),
            "active_contract_revision_count": int(diagnostics.get("active_contract_revision_count") or 0),
            "latest_contract_revision_ref": str(diagnostics.get("latest_contract_revision_ref") or ""),
            "executor_epoch": int(diagnostics.get("executor_epoch") or 0),
            "next_invocation_index": int(diagnostics.get("next_invocation_index") or 0),
            "route": route,
            "session_scope": session_scope,
            "graph_run_id": graph_run_id,
            "graph_config_id": graph_config_id,
            "graph_id": graph_id,
            "active_node_id": str((graph_status or {}).get("active_node_id") or diagnostics.get("active_node_id") or diagnostics.get("node_id") or ""),
            "project_id": str(diagnostics.get("project_id") or ""),
            "project_title": self._public_text(diagnostics.get("project_title")),
            "project_runtime_status": None,
            "has_graph_run": has_graph_run,
            "event_count": event_count,
            "authority": "runtime_monitor.v1.item",
        }
        return with_runtime_activity(item)

    def build_global_monitor(self, task_runs: list[Any], *, now: float, limit: int) -> dict[str, Any]:
        candidates = [
            task_run
            for task_run in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True)
            if not self._is_internal_child_run(task_run) and self._is_global_live_task_run_candidate(task_run)
        ]
        projected = [
            self.project_task_run(task_run, now=now, include_runtime_details=False, include_graph_runtime=False)
            for task_run in candidates
        ]
        items = self._current_graph_items_by_scope(
            self.select_current_items_by_session([item for item in projected if self._is_global_live_item(item)])
        )
        return build_envelope(scope="global", items=items, now=now, limit=limit)

    def build_session_monitor(self, session_id: str, task_runs: list[Any], *, now: float, limit: int = 20) -> dict[str, Any]:
        task_runs_by_id: dict[str, Any] = {}
        items = []
        for task_run in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True):
            if self._is_internal_child_run(task_run):
                continue
            item = self.project_task_run(task_run, now=now, include_runtime_details=False, include_graph_runtime=False)
            task_runs_by_id[str(item.get("task_run_id") or "")] = task_run
            items.append(item)
        active_items = self.select_current_items_by_session([item for item in items if activity_is_monitor_visible(item)])
        visible = active_items[: max(1, min(int(limit or 20), 100))]
        latest = items[0] if items else None
        active = visible[0] if visible else None
        if active:
            active_id = str(active.get("task_run_id") or "")
            source = task_runs_by_id.get(active_id)
            if source is not None:
                detailed = self.project_task_run(source, now=now, include_runtime_details=True, include_graph_runtime=False)
                visible = [detailed if str(item.get("task_run_id") or "") == active_id else item for item in visible]
                latest = detailed if latest and str(latest.get("task_run_id") or "") == active_id else latest
                active = detailed
        return build_envelope(
            scope="session",
            items=visible,
            now=now,
            limit=limit,
            selected=active,
            extra={
                "session_id": session_id,
                "active_task_run_id": str(active.get("task_run_id") or "") if active else "",
                "latest_task_run_id": str(latest.get("task_run_id") or "") if latest else "",
                "task_run_count": len(items),
                "monitor": active,
            },
        )

    def build_task_monitor(self, task_run: Any, *, now: float) -> dict[str, Any]:
        return build_task_detail_envelope(item=self.project_task_run(task_run, now=now), now=now)

    def project_active_turn(
        self,
        *,
        active_turn: Any,
        turn_run: Any | None,
        runtime_run: Any | None,
        now: float,
    ) -> dict[str, Any]:
        current_time = float(now)
        session_id = str(getattr(active_turn, "session_id", "") or "")
        turn_id = str(getattr(active_turn, "turn_id", "") or "")
        turn_run_id = str(getattr(active_turn, "turn_run_id", "") or "")
        bound_task_run_id = str(getattr(active_turn, "bound_task_run_id", "") or "").strip()
        stream_run_id = str(getattr(active_turn, "stream_run_id", "") or "")
        task_run_id = bound_task_run_id or turn_run_id
        task_instance_id = turn_run_id or stream_run_id or turn_id or task_run_id
        active_state = str(getattr(active_turn, "state", "") or "model_turn")
        started_at = float(
            getattr(active_turn, "started_at", 0.0)
            or getattr(turn_run, "created_at", 0.0)
            or getattr(runtime_run, "created_at", 0.0)
            or 0.0
        )
        updated_at = float(
            getattr(active_turn, "updated_at", 0.0)
            or getattr(turn_run, "updated_at", 0.0)
            or getattr(runtime_run, "updated_at", 0.0)
            or started_at
            or 0.0
        )
        last_activity_at = max(started_at, updated_at)
        last_activity_age_seconds = max(0.0, current_time - last_activity_at) if last_activity_at else 0.0
        duration_seconds = max(0.0, current_time - started_at) if started_at else 0.0
        status = _active_turn_status(active_state)
        latest_event_type = "single_agent_turn_started" if active_state in {"starting", "model_turn"} else "runtime_live_monitor"
        summary = _active_turn_summary(active_state)
        latest_progress = {
            "tool_status": "",
            "observation": "",
            "current_judgment": "",
            "next_action": "",
            "completion_status": "",
            "open_risks": [],
            "evidence_refs": [],
            "summary": summary,
            "agent_brief": "",
        }
        fact_summary = self._fact_summary(task_run_id=task_run_id, session_id=session_id, graph_run_id="")
        trace_summary = self._trace_summary(
            task_run_id=task_run_id,
            session_id=session_id,
            graph_run_id="",
            hydrate=True,
        )
        diagnostic_signal_refs = self._diagnostic_signal_refs(
            task_run_id=task_run_id,
            session_id=session_id,
            graph_run_id="",
            fact_summary=fact_summary,
            trace_summary=trace_summary,
        )
        item = {
            "task_run_id": task_run_id,
            "session_id": session_id,
            "task_id": turn_id or stream_run_id or task_run_id,
            "execution_runtime_kind": "single_agent_turn",
            "task_instance_id": task_instance_id,
            "root_task_run_id": task_run_id,
            "kind": "agent_run",
            "title": "持续处理",
            "status": status,
            "terminal_reason": str(getattr(active_turn, "terminal_reason", "") or ""),
            "lifecycle": "running" if status == "running" else "waiting",
            "bucket": "running" if status == "running" else "waiting",
            "resource_class": "dynamic",
            "started_at": started_at,
            "created_at": started_at,
            "updated_at": updated_at,
            "ended_at": None,
            "duration_seconds": duration_seconds,
            "elapsed_seconds": duration_seconds,
            "runtime_seconds": duration_seconds,
            "runtime_end_at": None,
            "last_activity_at": last_activity_at,
            "last_activity_age_seconds": last_activity_age_seconds,
            "action_required": status != "running",
            "terminal": False,
            "stale": False,
            "diagnostic_reasons": [],
            "runtime_control": {},
            "control_state": active_state,
            "is_live": True,
            "summary": summary,
            "latest_progress": latest_progress,
            "latest_event_type": latest_event_type,
            "latest_event_at": updated_at,
            "latest_event": {},
            "latest_step": {
                "step": active_state or "model_turn",
                "status": status,
                "summary": summary,
                "public_progress_note": summary,
                "agent_brief_output": "",
                "tool_status": "",
                "observation": "",
                "current_judgment": "",
                "next_action": "",
                "completion_status": "",
                "presentation_source": "active_turn",
                "event_id": "",
                "offset": -1,
                "created_at": updated_at,
            },
            "latest_step_summary": summary,
            "latest_public_progress_note": summary,
            "latest_interaction_turn_id": turn_id,
            "agent_brief_output": "",
            "latest_step_name": active_state or "model_turn",
            "latest_step_status": status,
            "artifact_count": 0,
            "artifact_refs": [],
            "resource_refs": [],
            "primary_resource_ref": None,
            "fact_summary": fact_summary,
            "trace_summary": trace_summary,
            "diagnostic_signal_refs": diagnostic_signal_refs,
            "graph_status": None,
            "child_runtime_refs": [],
            "navigation_target": build_navigation_target(
                kind="agent_run",
                task_instance_id=task_instance_id,
                task_run_id=task_run_id,
                session_id=session_id,
                session_scope={"workspace_view": "chat"},
            ),
            "pending_user_steer_count": 0,
            "latest_user_steer_ref": "",
            "active_contract_revision_count": 0,
            "latest_contract_revision_ref": "",
            "executor_epoch": 0,
            "next_invocation_index": 0,
            "route": {
                "kind": "agent_runtime_run",
                "session_id": session_id,
                "task_run_id": task_run_id,
                "graph_id": "",
                "graph_run_id": "",
                "graph_config_id": "",
            },
            "session_scope": {"workspace_view": "chat", "task_environment_id": "", "project_id": ""},
            "graph_run_id": "",
            "graph_config_id": "",
            "graph_id": "",
            "active_node_id": "",
            "project_id": "",
            "project_title": "",
            "project_runtime_status": None,
            "has_graph_run": False,
            "event_count": 0,
            "authority": "runtime_monitor.v1.item",
        }
        return with_runtime_activity(
            item,
            control_context=RuntimeActivityControlContext(
                resumable=status == "waiting_executor" and bool(bound_task_run_id),
                interruptible=status == "running" and bool(bound_task_run_id),
                reason="active_turn",
            ),
        )

    def build_turn_monitor(
        self,
        *,
        active_turn: Any,
        turn_run: Any | None,
        runtime_run: Any | None,
        now: float,
    ) -> dict[str, Any]:
        return build_task_detail_envelope(
            item=self.project_active_turn(
                active_turn=active_turn,
                turn_run=turn_run,
                runtime_run=runtime_run,
                now=now,
            ),
            now=now,
        )

    def select_current_items_by_session(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected_by_session: dict[str, dict[str, Any]] = {}
        unscoped: list[dict[str, Any]] = []
        for item in items:
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                unscoped.append(item)
                continue
            current = selected_by_session.get(session_id)
            if current is None or _session_current_item_key(item) > _session_current_item_key(current):
                selected_by_session[session_id] = item
        return [*unscoped, *selected_by_session.values()]

    def _current_graph_items_by_scope(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected_by_graph_scope: dict[str, dict[str, Any]] = {}
        passthrough: list[dict[str, Any]] = []
        for item in items:
            key = _graph_scope_key(item)
            if not key:
                passthrough.append(item)
                continue
            current = selected_by_graph_scope.get(key)
            if current is None or _session_current_item_key(item) > _session_current_item_key(current):
                selected_by_graph_scope[key] = item
        return [*passthrough, *selected_by_graph_scope.values()]

    def _fact_summary(self, *, task_run_id: str, session_id: str, graph_run_id: str) -> dict[str, Any]:
        scope_ref = _fact_scope_ref(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id)
        if self.fact_ledger is None or not scope_ref.get("scope_key"):
            return {
                "authority": "runtime_monitor.fact_summary",
                "available": False,
                "task_run_id": task_run_id,
                "session_id": session_id,
                "graph_run_id": graph_run_id,
                "fact_count": 0,
                "fact_type_counts": {},
                "retention_class_counts": {},
                "scope_ref": scope_ref,
            }
        try:
            records = self._fact_records_for_scope(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                limit=5000,
            )
        except Exception:
            records = []
        return {
            "authority": "runtime_monitor.fact_summary",
            "available": True,
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": graph_run_id,
            "fact_count": len(records),
            "fact_type_counts": _counts(_record_field(item, "fact_type") for item in records),
            "retention_class_counts": _counts(_record_field(item, "retention_class") for item in records),
            "scope_ref": scope_ref,
        }

    def _deferred_fact_summary(self, *, task_run_id: str, session_id: str, graph_run_id: str) -> dict[str, Any]:
        return {
            "authority": "runtime_monitor.fact_summary",
            "available": False,
            "deferred": True,
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": graph_run_id,
            "fact_count": 0,
            "fact_type_counts": {},
            "retention_class_counts": {},
            "scope_ref": _fact_scope_ref(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id),
        }

    def _trace_summary(self, *, task_run_id: str, session_id: str, graph_run_id: str, hydrate: bool) -> dict[str, Any]:
        query = getattr(self.observability_query, "trace_summary", None)
        if callable(query):
            try:
                summary = dict(
                    query(
                        task_run_id=task_run_id,
                        session_id=session_id,
                        graph_run_id=graph_run_id,
                        hydrate=hydrate,
                    )
                    or {}
                )
            except Exception:
                summary = {}
            if summary:
                return {
                    **summary,
                    "authority": "runtime_monitor.trace_summary",
                    "source_authority": str(summary.get("authority") or ""),
                }
        trace_fact = self._latest_trace_run_fact(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id)
        trace_id = _record_ref(trace_fact, "trace_id") if trace_fact is not None else ""
        base = {
            "authority": "runtime_monitor.trace_summary",
            "available": bool(trace_id),
            "hydrated": False,
            "trace_id": trace_id,
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": graph_run_id,
            "source_fact_id": _record_field(trace_fact, "fact_id") if trace_fact is not None else "",
            "detail_ref": {"kind": "trace", "trace_id": trace_id} if trace_id else {},
        }
        if not trace_id or not hydrate:
            return base
        summarizer = getattr(self.trace_service, "summarize_trace", None)
        if not callable(summarizer):
            return base
        try:
            raw = dict(summarizer(trace_id) or {})
        except Exception:
            return {**base, "available": False}
        if raw.get("available") is not True:
            return {**base, "available": False, "hydrated": True}
        return {
            **base,
            "available": True,
            "hydrated": True,
            "run": _compact_trace_run(dict(raw.get("run") or {})),
            "span_count": int(raw.get("span_count") or 0),
            "event_count": int(raw.get("event_count") or 0),
            "error_span_count": int(raw.get("error_span_count") or 0),
            "latest_span": _compact_trace_span(dict(raw.get("latest_span") or {})),
        }

    def _deferred_trace_summary(self, *, task_run_id: str, session_id: str, graph_run_id: str) -> dict[str, Any]:
        return {
            "authority": "runtime_monitor.trace_summary",
            "available": False,
            "deferred": True,
            "hydrated": False,
            "trace_id": "",
            "task_run_id": task_run_id,
            "session_id": session_id,
            "graph_run_id": graph_run_id,
            "source_fact_id": "",
            "detail_ref": {},
        }

    def _diagnostic_signal_refs(
        self,
        *,
        task_run_id: str,
        session_id: str,
        graph_run_id: str,
        fact_summary: dict[str, Any],
        trace_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        trace_id = str(trace_summary.get("trace_id") or "").strip()
        if trace_id:
            refs.append(
                {
                    "kind": "trace",
                    "ref": f"trace:{trace_id}",
                    "trace_id": trace_id,
                    "task_run_id": task_run_id,
                    "session_id": session_id,
                    "graph_run_id": graph_run_id,
                    "error_span_count": int(trace_summary.get("error_span_count") or 0),
                }
            )
        scope_ref = dict(fact_summary.get("scope_ref") or {})
        fact_count = int(fact_summary.get("fact_count") or 0)
        if bool(fact_summary.get("available")) and fact_count > 0 and scope_ref.get("scope_key"):
            refs.append(
                {
                    "kind": "fact_scope",
                    "ref": str(scope_ref.get("scope_key") or ""),
                    "task_run_id": task_run_id,
                    "session_id": session_id,
                    "graph_run_id": graph_run_id,
                    "fact_count": fact_count,
                    "fact_type_counts": dict(fact_summary.get("fact_type_counts") or {}),
                }
            )
        for fact in self._recent_diagnostic_facts(task_run_id=task_run_id, session_id=session_id, graph_run_id=graph_run_id):
            refs.append(
                {
                    "kind": "fact",
                    "ref": str(_record_field(fact, "fact_id") or ""),
                    "fact_id": str(_record_field(fact, "fact_id") or ""),
                    "fact_type": str(_record_field(fact, "fact_type") or ""),
                    "task_run_id": task_run_id,
                    "session_id": session_id,
                    "graph_run_id": graph_run_id,
                    "summary": _short_text(_record_field(fact, "summary"), limit=180),
                    "created_at": float(_record_field(fact, "created_at") or 0.0),
                }
            )
        return _dedupe_signal_refs(refs)[:12]

    def _latest_trace_run_fact(self, *, task_run_id: str, session_id: str, graph_run_id: str) -> Any | None:
        try:
            records = self._fact_records_for_scope(
                task_run_id=task_run_id,
                session_id=session_id,
                graph_run_id=graph_run_id,
                fact_type="trace_run",
                limit=50,
            )
        except Exception:
            records = []
        records = [item for item in records if _record_ref(item, "trace_id")]
        if not records:
            return None
        return sorted(records, key=lambda item: float(_record_field(item, "created_at") or 0.0), reverse=True)[0]

    def _recent_diagnostic_facts(self, *, task_run_id: str, session_id: str, graph_run_id: str) -> list[Any]:
        records: list[Any] = []
        for fact_type in ("monitor_signal", "health_issue"):
            try:
                records.extend(
                    self._fact_records_for_scope(
                        task_run_id=task_run_id,
                        session_id=session_id,
                        graph_run_id=graph_run_id,
                        fact_type=fact_type,
                        limit=20,
                    )
                )
            except Exception:
                continue
        return sorted(records, key=lambda item: float(_record_field(item, "created_at") or 0.0), reverse=True)[:10]

    def _fact_records_for_scope(
        self,
        *,
        task_run_id: str,
        session_id: str,
        graph_run_id: str = "",
        fact_type: str = "",
        limit: int = 200,
    ) -> list[Any]:
        reader = getattr(self.fact_ledger, "list_records", None)
        if not callable(reader):
            return []
        queries: list[dict[str, Any]] = []
        normalized_task_run_id = str(task_run_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_graph_run_id = str(graph_run_id or "").strip()
        if normalized_task_run_id.startswith("turnrun:"):
            queries.append({"turn_run_id": normalized_task_run_id})
        elif normalized_task_run_id:
            queries.append({"task_run_id": normalized_task_run_id})
        if normalized_graph_run_id:
            queries.append({"graph_run_id": normalized_graph_run_id})
        if not queries and normalized_session_id:
            queries.append({"session_id": normalized_session_id})
        if not queries:
            return []
        records: list[Any] = []
        seen: set[str] = set()
        per_query_limit = max(1, min(int(limit or 200), 5000))
        for filters in queries:
            query = dict(filters)
            if fact_type:
                query["fact_type"] = fact_type
            for record in list(reader(**query, limit=per_query_limit)):
                fact_id = str(_record_field(record, "fact_id") or "")
                identity = fact_id or f"{_record_field(record, 'fact_type')}:{_record_field(record, 'created_at')}"
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(record)
        records.sort(key=lambda item: float(_record_field(item, "created_at") or 0.0))
        if len(records) > per_query_limit:
            return records[-per_query_limit:]
        return records

    def _route(self, task_run: Any, diagnostics: dict[str, Any]) -> dict[str, str]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        session_id = str(getattr(task_run, "session_id", "") or "")
        graph_id = str(diagnostics.get("graph_id") or diagnostics.get("task_graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_config_id = str(diagnostics.get("graph_config_id") or "")
        if graph_run_id or graph_config_id:
            kind = "task_graph_run"
        else:
            kind = "agent_runtime_run"
        return {
            "kind": kind,
            "session_id": session_id,
            "task_run_id": task_run_id,
            "graph_id": graph_id,
            "graph_run_id": graph_run_id,
            "graph_config_id": graph_config_id,
        }

    def _session_scope(self, task_run: Any, diagnostics: dict[str, Any]) -> dict[str, str]:
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        runtime_scope = dict(diagnostics.get("runtime_scope") or {})
        runtime_contract = dict(diagnostics.get("runtime_contract") or {})
        resolved = {
            "workspace_view": str(
                diagnostics.get("workspace_view")
                or runtime_scope.get("workspace_view")
                or runtime_contract.get("workspace_view")
                or ""
            ).strip(),
            "task_environment_id": str(
                diagnostics.get("task_environment_id")
                or runtime_scope.get("task_environment_id")
                or runtime_contract.get("task_environment_id")
                or runtime_contract.get("environment_id")
                or ""
            ).strip(),
            "project_id": str(
                diagnostics.get("project_id")
                or runtime_scope.get("project_id")
                or runtime_contract.get("project_id")
                or ""
            ).strip(),
        }
        if not resolved["workspace_view"] and resolved["task_environment_id"]:
            resolved["workspace_view"] = "task_environment"
        resolver = getattr(self, "session_scope_resolver", None)
        if callable(resolver) and session_id:
            try:
                session_scope = dict(resolver(session_id) or {})
            except Exception:
                session_scope = {}
            if session_scope:
                resolved = {
                    "workspace_view": str(session_scope.get("workspace_view") or resolved["workspace_view"] or "chat").strip() or "chat",
                    "task_environment_id": str(session_scope.get("task_environment_id") or resolved["task_environment_id"]).strip(),
                    "project_id": str(session_scope.get("project_id") or resolved["project_id"]).strip(),
                }
        return {
            "workspace_view": resolved["workspace_view"] or "chat",
            "task_environment_id": resolved["task_environment_id"],
            "project_id": resolved["project_id"],
        }

    def _kind_from_route(self, route: dict[str, str]) -> str:
        route_kind = str(route.get("kind") or "")
        if route_kind == "task_graph_run":
            return "task_graph"
        return "agent_run"

    def _diagnostic_reasons(
        self,
        *,
        task_run: Any,
        status: str,
        created_at: float,
        updated_at: float,
        latest_event: dict[str, Any],
        last_activity_at: float,
        route: dict[str, str],
        stale: bool,
        control_state: str = "",
    ) -> list[str]:
        reasons: list[str] = []
        if stale:
            reasons.append("stale_runtime_activity")
        if not created_at or not updated_at or not last_activity_at:
            reasons.append("missing_runtime_time")
        if status not in KNOWN_TASK_RUN_STATUSES:
            reasons.append("unknown_task_status")
        kind = str(route.get("kind") or "")
        if not route.get("task_run_id"):
            reasons.append("missing_route_task_run_id")
        if kind == "agent_runtime_run" and not route.get("session_id"):
            reasons.append("missing_route_session_id")
        if kind == "task_graph_run" and not route.get("graph_id"):
            reasons.append("missing_route_graph_id")
        event_type = str(latest_event.get("event_type") or "")
        if status in TERMINAL_TASK_RUN_STATUSES and event_type.startswith("task_run_lifecycle_waiting"):
            reasons.append("terminal_status_with_waiting_event")
        if status in RUNNING_TASK_RUN_STATUSES and str(getattr(task_run, "terminal_reason", "") or "") in TERMINAL_TASK_RUN_STATUSES:
            reasons.append("running_status_with_terminal_reason")
        if control_state and control_state not in {"running", "pause_requested", "paused", "resume_requested", "stop_requested", "stopped", "replan_requested", "interrupted_for_replan"}:
            reasons.append("unknown_runtime_control_state")
        return reasons

    def _is_internal_child_run(self, task_run: Any) -> bool:
        task_id = str(getattr(task_run, "task_id", "") or "")
        contract_ref = str(getattr(task_run, "task_contract_ref", "") or "")
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        if task_id.startswith("task_graph.graph_module.") or contract_ref.startswith("task_graph.graph_module."):
            return True
        return bool(
            diagnostics.get("coordination_stage_id")
            or diagnostics.get("stage_request_id")
            or diagnostics.get("stage_idempotency_key")
            or diagnostics.get("graph_node_id")
            or diagnostics.get("graph_work_order_id")
        )

    def is_top_level_task_run(self, task_run: Any) -> bool:
        return not self._is_internal_child_run(task_run)

    def _is_global_live_task_run_candidate(self, task_run: Any) -> bool:
        status = str(getattr(task_run, "status", "") or "").strip()
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        control_state = runtime_control_state_from_task_run(
            task_run,
            runtime_host=self.runtime_host,
        )
        if status in RUNNING_TASK_RUN_STATUSES | WAITING_TASK_RUN_STATUSES | BLOCKED_TASK_RUN_STATUSES:
            return True
        if control_state in {"pause_requested", "paused", "resume_requested", "stop_requested"}:
            return True
        if status and status not in KNOWN_TASK_RUN_STATUSES:
            return True
        return False

    def _is_global_live_item(self, item: dict[str, Any]) -> bool:
        if str(item.get("kind") or "").strip() == "task_graph":
            return (
                str(item.get("activity_state") or "").strip() == "running"
                and item.get("is_running") is True
                and item.get("stale") is not True
                and str(item.get("lifecycle") or "").strip() != "stale"
            )
        return activity_is_monitor_visible(item)

    def _display_title(self, task_run: Any, diagnostics: dict[str, Any], *, lifecycle: str) -> str:
        for key in ("title", "task_graph_title", "project_title", "goal", "task_goal"):
            value = self._public_text(diagnostics.get(key))
            if value:
                return value
        contract = dict(diagnostics.get("contract") or {})
        for key in ("user_visible_goal", "task_run_goal", "goal", "title"):
            value = self._public_text(contract.get(key))
            if value:
                return value
        task_id = self._public_task_id(getattr(task_run, "task_id", ""))
        if task_id:
            return task_id
        if str(getattr(task_run, "execution_runtime_kind", "") or "") == "single_agent_task":
            return "Agent 运行"
        if lifecycle == "completed":
            return "会话运行已完成"
        if lifecycle == "failed":
            return "会话运行失败"
        if lifecycle == "action_required":
            return "会话运行等待处理"
        if lifecycle == "paused":
            return "会话运行已暂停"
        if lifecycle == "stale":
            return "运行状态需诊断"
        return "会话运行中"

    def _public_text(self, value: Any) -> str:
        candidate = str(value or "").strip()
        if not candidate or _looks_internal_identifier(candidate):
            return ""
        return candidate

    def _public_task_id(self, value: Any) -> str:
        candidate = str(value or "").strip()
        if not candidate:
            return ""
        if candidate.startswith("task:turn:") or candidate.startswith("taskrun:") or candidate.startswith("turn:"):
            return ""
        return candidate

    def _latest_step_summary(self, events: list[Any]) -> dict[str, Any]:
        for event in reversed(events):
            if str(getattr(event, "event_type", "") or "") != "step_summary_recorded":
                continue
            return _step_summary_from_event(event)
        return {}

    def _latest_public_step_summary(self, events: list[Any]) -> dict[str, Any]:
        for event in reversed(events):
            if str(getattr(event, "event_type", "") or "") != "step_summary_recorded":
                continue
            step = _step_summary_from_event(event)
            if _is_public_progress_step(step):
                return step
        return {}

    def _latest_step_from_diagnostics(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        return {
            "step": str(diagnostics.get("latest_step") or ""),
            "status": str(diagnostics.get("latest_step_status") or ""),
            "summary": public_runtime_progress_summary(diagnostics.get("latest_step_summary") or diagnostics.get("summary") or ""),
            "public_progress_note": public_runtime_progress_summary(
                diagnostics.get("latest_public_progress_note")
                or diagnostics.get("public_progress_note")
                or ""
            ),
            "agent_brief_output": public_runtime_progress_summary(diagnostics.get("agent_brief_output") or ""),
            "tool_status": public_runtime_progress_summary(diagnostics.get("latest_tool_status") or ""),
            "observation": public_runtime_progress_summary(diagnostics.get("latest_observation") or ""),
            "current_judgment": public_runtime_progress_summary(diagnostics.get("latest_current_judgment") or ""),
            "next_action": public_runtime_progress_summary(diagnostics.get("latest_next_action") or ""),
            "completion_status": str(diagnostics.get("latest_completion_status") or "").strip(),
            "presentation_source": "diagnostics",
            "event_id": "",
            "offset": -1,
            "created_at": float(diagnostics.get("latest_step_at") or diagnostics.get("latest_event_at") or 0.0),
        }

    def _diagnostic_summary(
        self,
        *,
        diagnostic_reasons: list[str],
        latest_step: dict[str, Any],
        last_activity_age_seconds: float,
    ) -> str:
        if "stale_runtime_activity" not in diagnostic_reasons:
            return ""
        elapsed = _human_duration(last_activity_age_seconds)
        step = str(latest_step.get("step") or "")
        if step.startswith("model_action_waiting") or step.startswith("task_model_action_waiting"):
            return f"模型响应已超过{elapsed}没有更新，可能是模型服务或网络异常；当前处理已进入诊断状态。"
        return f"处理已超过{elapsed}没有新的运行事件；当前处理已进入诊断状态。"

    def _resource_refs(
        self,
        *,
        task_run_id: str,
        session_id: str,
        graph_run_id: str,
        graph_config_id: str,
        artifact_refs: list[dict[str, Any]],
        resolve_availability: bool = True,
    ) -> list[dict[str, Any]]:
        resolver = self.resource_resolver
        if resolver is None:
            return []
        refs = [_resolver_task_run_ref(resolver, task_run_id, available=True)]
        if session_id:
            refs.append(resolver.session_ref(session_id))
        if graph_run_id:
            refs.append(_resolver_graph_run_ref(resolver, graph_run_id, available=True if not resolve_availability else None))
        if graph_config_id:
            refs.append(_resolver_graph_config_ref(resolver, graph_config_id, available=True if not resolve_availability else None))
        refs.extend(_resolver_artifact_refs(resolver, artifact_refs, resolve_availability=resolve_availability))
        return refs

    def _graph_monitor(self, graph_run_id: str, graph_config_id: str) -> dict[str, Any] | None:
        resolver = self.resource_resolver
        if resolver is None or not graph_run_id:
            return None
        return resolver.graph_monitor(graph_run_id, graph_config_id)

    def _graph_status(self, monitor: dict[str, Any] | None, *, graph_id: str, graph_run_id: str) -> dict[str, Any]:
        payload = dict(monitor or {})
        graph_config = dict(payload.get("graph_config") or {})
        loop_state = dict(payload.get("graph_loop_state") or {})
        node_statuses = _node_statuses_from_monitor(payload)
        active_node_id = _active_node_id(loop_state, node_statuses)
        active_node = next((item for item in node_statuses if item.get("node_id") == active_node_id), {})
        status = str(loop_state.get("status") or dict(payload.get("task_run") or {}).get("status") or "").strip()
        running_count = sum(1 for item in node_statuses if item.get("status") == "running")
        completed_count = sum(1 for item in node_statuses if item.get("status") in {"completed", "success", "succeeded"})
        failed_count = sum(1 for item in node_statuses if item.get("status") in {"failed", "error"})
        blocked_count = sum(1 for item in node_statuses if item.get("status") in {"blocked", "waiting_human_gate", "waiting_approval"})
        ready_ids = [str(item) for item in list(loop_state.get("ready_node_ids") or [])]
        return {
            "graph_id": graph_id or str(graph_config.get("graph_id") or ""),
            "graph_run_id": graph_run_id,
            "graph_title": self._public_text(graph_config.get("graph_title")) or "任务图",
            "graph_lifecycle": _graph_lifecycle(status, failed_count=failed_count, blocked_count=blocked_count),
            "active_node_id": active_node_id,
            "active_node_label": str(active_node.get("node_label") or active_node.get("node_id") or ""),
            "active_node_status": str(active_node.get("status") or ""),
            "ready_node_count": len(ready_ids),
            "running_node_count": running_count,
            "completed_node_count": completed_count,
            "failed_node_count": failed_count,
            "blocked_node_count": blocked_count,
            "current_stage_summary": _graph_stage_summary(active_node=active_node, status=status, ready_count=len(ready_ids), running_count=running_count),
            "next_action_label": _graph_next_action(status=status, ready_count=len(ready_ids), failed_count=failed_count, blocked_count=blocked_count),
            "node_statuses": node_statuses,
        }

    def _child_runtime_refs(self, monitor: dict[str, Any] | None) -> list[dict[str, Any]]:
        payload = dict(monitor or {})
        refs: list[dict[str, Any]] = []
        for item in [
            *list(payload.get("active_node_runtime_views") or []),
            *list(payload.get("node_runtime_views") or []),
        ]:
            view = dict(item or {})
            task_run_id = str(view.get("node_executor_task_run_id") or "")
            if not task_run_id:
                continue
            task_monitor = dict(view.get("node_executor_task_run_monitor") or {})
            refs.append(
                {
                    "task_run_id": task_run_id,
                    "node_id": str(view.get("node_id") or ""),
                    "node_label": str(view.get("node_label") or view.get("node_id") or ""),
                    "runtime_kind": "agent_runtime",
                    "lifecycle": str(task_monitor.get("lifecycle") or view.get("status") or ""),
                    "latest_progress": dict(task_monitor.get("latest_progress") or {}),
                    "artifact_refs": list(view.get("artifact_refs") or task_monitor.get("artifact_refs") or []),
                }
            )
        return refs

def _latest_interaction_turn_id(events: list[Any], *, diagnostics: dict[str, Any]) -> str:
    for event in reversed(events):
        event_type = str(getattr(event, "event_type", "") or "")
        payload = dict(getattr(event, "payload", {}) or {})
        refs = dict(getattr(event, "refs", {}) or {})
        if event_type in {
            "user_work_instruction_recorded",
            "active_task_steer_recorded",
            "active_task_steer_included",
            "active_task_steer_consumed",
            "task_run_resume_requested",
            "task_run_executor_scheduled",
            "step_summary_recorded",
        }:
            steer = dict(payload.get("steer") or {})
            submission = dict(payload.get("submission") or {})
            for candidate in (
                refs.get("turn_ref"),
                payload.get("turn_id"),
                submission.get("turn_id"),
                steer.get("turn_id"),
            ):
                turn_id = _valid_turn_ref(candidate)
                if turn_id:
                    return turn_id
    return _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))


def _resolver_task_run_ref(resolver: Any, task_run_id: str, *, available: bool) -> dict[str, Any]:
    try:
        return resolver.task_run_ref(task_run_id, available=available)
    except TypeError:
        return resolver.task_run_ref(task_run_id)


def _resolver_graph_run_ref(resolver: Any, graph_run_id: str, *, available: bool | None) -> dict[str, Any]:
    if available is None:
        return resolver.graph_run_ref(graph_run_id)
    try:
        return resolver.graph_run_ref(graph_run_id, available=available)
    except TypeError:
        return resolver.graph_run_ref(graph_run_id)


def _resolver_graph_config_ref(resolver: Any, graph_config_id: str, *, available: bool | None) -> dict[str, Any]:
    if available is None:
        return resolver.graph_config_ref(graph_config_id)
    try:
        return resolver.graph_config_ref(graph_config_id, available=available)
    except TypeError:
        return resolver.graph_config_ref(graph_config_id)


def _resolver_artifact_refs(resolver: Any, artifact_refs: list[dict[str, Any]], *, resolve_availability: bool) -> list[dict[str, Any]]:
    try:
        return list(resolver.artifact_refs(artifact_refs, resolve_availability=resolve_availability))
    except TypeError:
        return list(resolver.artifact_refs(artifact_refs))


def _valid_turn_ref(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("turn:") else ""


def _human_duration(seconds: float) -> str:
    safe = max(0, int(float(seconds or 0.0)))
    if safe >= 3600:
        hours = safe // 3600
        minutes = (safe % 3600) // 60
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    if safe >= 60:
        minutes = safe // 60
        remain = safe % 60
        return f"{minutes}分钟{remain}秒" if remain else f"{minutes}分钟"
    return f"{safe}秒"


def _looks_internal_identifier(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("task:", "taskrun:", "turn:", "turnrun:", "session:", "taskinst:", "coordrun:", "grun:"))


def _artifact_refs_from_event_log(event_log: Any, task_run_id: str) -> list[dict[str, Any]]:
    reader = getattr(event_log, "list_event_window", None)
    if callable(reader):
        try:
            return artifact_refs_from_events(list(reader(task_run_id, limit=240, include_payloads=True)))
        except Exception:
            pass
    reader = getattr(event_log, "list_events", None)
    if callable(reader):
        try:
            return artifact_refs_from_events(list(reader(task_run_id))[-240:])
        except Exception:
            pass
    return []


def _fact_scope_ref(*, task_run_id: str, session_id: str, graph_run_id: str) -> dict[str, str]:
    normalized_task_run_id = str(task_run_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_graph_run_id = str(graph_run_id or "").strip()
    if normalized_task_run_id.startswith("turnrun:"):
        return {
            "kind": "runtime_fact_scope",
            "scope_kind": "turn_run",
            "scope_key": f"runtime_fact_scope:turn_run:{normalized_task_run_id}",
            "task_run_id": normalized_task_run_id,
            "session_id": normalized_session_id,
            "graph_run_id": normalized_graph_run_id,
        }
    if normalized_task_run_id:
        return {
            "kind": "runtime_fact_scope",
            "scope_kind": "task_run",
            "scope_key": f"runtime_fact_scope:task_run:{normalized_task_run_id}",
            "task_run_id": normalized_task_run_id,
            "session_id": normalized_session_id,
            "graph_run_id": normalized_graph_run_id,
        }
    if normalized_graph_run_id:
        return {
            "kind": "runtime_fact_scope",
            "scope_kind": "graph_run",
            "scope_key": f"runtime_fact_scope:graph_run:{normalized_graph_run_id}",
            "task_run_id": "",
            "session_id": normalized_session_id,
            "graph_run_id": normalized_graph_run_id,
        }
    if normalized_session_id:
        return {
            "kind": "runtime_fact_scope",
            "scope_kind": "session",
            "scope_key": f"runtime_fact_scope:session:{normalized_session_id}",
            "task_run_id": "",
            "session_id": normalized_session_id,
            "graph_run_id": "",
        }
    return {"kind": "runtime_fact_scope", "scope_kind": "", "scope_key": "", "task_run_id": "", "session_id": "", "graph_run_id": ""}


def _compact_trace_run(run: dict[str, Any]) -> dict[str, Any]:
    if not run:
        return {}
    return {
        "trace_id": str(run.get("trace_id") or ""),
        "run_kind": str(run.get("run_kind") or ""),
        "root_run_id": str(run.get("root_run_id") or ""),
        "status": str(run.get("status") or ""),
        "terminal_reason": str(run.get("terminal_reason") or ""),
        "started_at": float(run.get("started_at") or 0.0),
        "ended_at": float(run.get("ended_at") or 0.0),
        "scope": _compact_ref_payload(dict(run.get("scope") or {})),
        "refs": _compact_ref_payload(dict(run.get("refs") or {})),
    }


def _compact_trace_span(span: dict[str, Any]) -> dict[str, Any]:
    if not span:
        return {}
    return {
        "trace_id": str(span.get("trace_id") or ""),
        "span_id": str(span.get("span_id") or ""),
        "parent_span_id": str(span.get("parent_span_id") or ""),
        "name": str(span.get("name") or ""),
        "span_kind": str(span.get("span_kind") or ""),
        "status": str(span.get("status") or ""),
        "started_at": float(span.get("started_at") or 0.0),
        "ended_at": float(span.get("ended_at") or 0.0),
        "latency_ms": float(span.get("latency_ms") or 0.0),
        "refs": _compact_ref_payload(dict(span.get("refs") or {})),
    }


def _compact_ref_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "trace_id",
        "span_id",
        "task_run_id",
        "turn_id",
        "turn_run_id",
        "graph_run_id",
        "node_id",
        "work_order_id",
        "execution_id",
        "usage_id",
        "artifact_ref",
        "runtime_event_id",
        "runtime_run_id",
        "action_request_ref",
        "observation_ref",
        "runtime_invocation_packet_ref",
        "fact_id",
        "tool_call_id",
        "executor_epoch",
    }
    result: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        normalized_key = str(key or "")
        if normalized_key not in allowed or value in (None, "", [], {}):
            continue
        if isinstance(value, (bool, int, float)):
            result[normalized_key] = value
        else:
            result[normalized_key] = _short_text(value, limit=240)
    return result


def _record_field(record: Any, field: str) -> Any:
    if record is None:
        return ""
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, "")


def _record_ref(record: Any, key: str) -> str:
    refs = _record_field(record, "refs")
    if not isinstance(refs, dict):
        return ""
    return str(refs.get(key) or "").strip()


def _counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "").strip() or "unknown"
        result[key] = result.get(key, 0) + 1
    return result


def _short_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _public_runtime_event(event: Any) -> dict[str, Any]:
    payload = dict(getattr(event, "payload", {}) or {})
    public_payload = _public_event_payload(payload)
    return {
        "event_id": str(getattr(event, "event_id", "") or ""),
        "event_type": str(getattr(event, "event_type", "") or ""),
        "offset": int(getattr(event, "offset", -1) or -1),
        "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
        **({"payload": public_payload} if public_payload else {}),
    }


def _step_summary_from_event(event: Any) -> dict[str, Any]:
    payload = dict(getattr(event, "payload", {}) or {})
    public_action_state = dict(payload.get("public_action_state") or {})
    presentation_source = str(payload.get("presentation_source") or "")
    trace_only = presentation_source in TRACE_ONLY_PRESENTATION_SOURCES
    public_summary = "" if presentation_source in TRACE_ONLY_PRESENTATION_SOURCES else payload.get("summary")
    return {
        "step": str(payload.get("step") or ""),
        "status": str(payload.get("status") or ""),
        "summary": public_runtime_progress_summary(payload.get("summary") or ""),
        "public_progress_note": public_runtime_progress_summary(payload.get("public_progress_note") or public_summary or ""),
        "agent_brief_output": "" if trace_only else public_runtime_progress_summary(payload.get("agent_brief_output") or ""),
        "tool_status": public_runtime_progress_summary(payload.get("tool_status") or ""),
        "observation": public_runtime_progress_summary(payload.get("observation") or ""),
        "current_judgment": public_runtime_progress_summary(
            payload.get("current_judgment")
            or public_action_state.get("current_judgment")
            or ""
        ),
        "next_action": public_runtime_progress_summary(payload.get("next_action") or public_action_state.get("next_action") or ""),
        "completion_status": str(
            payload.get("completion_status")
            or public_action_state.get("completion_status")
            or ""
        ).strip(),
        "open_risks": list(public_action_state.get("open_risks") or []),
        "evidence_refs": list(public_action_state.get("evidence_refs") or []),
        "presentation_source": presentation_source,
        "event_id": str(getattr(event, "event_id", "") or ""),
        "offset": int(getattr(event, "offset", -1) or -1),
        "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
    }


def _is_public_progress_step(step: dict[str, Any]) -> bool:
    if str(step.get("presentation_source") or "") in TRACE_ONLY_PRESENTATION_SOURCES:
        return False
    return bool(
        public_runtime_progress_summary(
            step.get("public_progress_note")
            or step.get("current_judgment")
            or step.get("next_action")
            or step.get("summary")
            or ""
        )
    )


def _public_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "task_run_id",
        "status",
        "step",
        "summary",
        "public_progress_note",
        "current_judgment",
        "next_action",
        "completion_status",
        "tool_name",
        "tool_target",
        "artifact_refs",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "artifact_refs" and isinstance(value, list):
            result[key] = [dict(item) for item in value[:8] if isinstance(item, dict)]
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


def _int_value(value: Any, *, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _dedupe_signal_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        payload = dict(ref or {})
        identity = "|".join(
            [
                str(payload.get("kind") or ""),
                str(payload.get("ref") or ""),
                str(payload.get("fact_id") or ""),
                str(payload.get("trace_id") or ""),
            ]
        )
        if not identity.strip("|") or identity in seen:
            continue
        seen.add(identity)
        result.append(payload)
    return result


def _active_turn_status(state: str) -> str:
    normalized = str(state or "").strip()
    if normalized in {"waiting_executor", "waiting_user"}:
        return "waiting_executor"
    return "running"


def _active_turn_summary(state: str) -> str:
    normalized = str(state or "").strip()
    if normalized in {"starting", "model_turn"}:
        return "正在分析请求并准备执行。"
    if normalized == "waiting_user":
        return "等待新的用户输入。"
    if normalized == "waiting_executor":
        return "等待执行器继续。"
    if normalized == "interrupting":
        return "中断请求已记录。"
    return ""


def _session_current_item_key(item: dict[str, Any]) -> tuple[int, int, int, float, float]:
    status = str(item.get("status") or "").strip()
    state_rank = activity_sort_rank(item)
    status_rank = {
        "running": 6,
        "created": 5,
        "waiting_executor": 4,
        "waiting_approval": 3,
        "blocked": 2,
    }.get(status, 0)
    fresh_rank = 0 if item.get("stale") is True else 1
    return (
        state_rank,
        status_rank,
        fresh_rank,
        float(item.get("last_activity_at") or item.get("updated_at") or 0.0),
        float(item.get("created_at") or 0.0),
    )


def _graph_scope_key(item: dict[str, Any]) -> str:
    if str(item.get("kind") or "").strip() != "task_graph":
        return ""
    graph_id = str(item.get("graph_id") or dict(item.get("route") or {}).get("graph_id") or "").strip()
    if not graph_id:
        return ""
    scope = dict(item.get("session_scope") or {})
    workspace_view = str(scope.get("workspace_view") or "").strip()
    task_environment_id = str(scope.get("task_environment_id") or "").strip()
    project_id = str(scope.get("project_id") or item.get("project_id") or "").strip()
    if not (workspace_view or task_environment_id or project_id):
        return ""
    return "|".join([workspace_view, task_environment_id, project_id, graph_id])


def _graph_monitor_has_active_runtime(monitor: dict[str, Any] | None) -> bool:
    payload = dict(monitor or {})
    if list(payload.get("active_node_work_orders") or []):
        return True
    loop_state = dict(payload.get("graph_loop_state") or {})
    if list(loop_state.get("running_node_ids") or []) or list(loop_state.get("active_node_ids") or []):
        return True
    if list(loop_state.get("ready_node_ids") or []):
        return True
    for node_state in dict(loop_state.get("node_states") or {}).values():
        status = str(dict(node_state or {}).get("status") or "").strip()
        if status in {"running", "waiting_executor", "waiting_approval", "blocked"}:
            return True
    for view in [
        *list(payload.get("active_node_runtime_views") or []),
        *list(payload.get("node_runtime_views") or []),
    ]:
        status = str(dict(view or {}).get("status") or "").strip()
        if status in {"running", "waiting_executor", "waiting_approval", "blocked"}:
            return True
    return False


def _node_statuses_from_monitor(monitor: dict[str, Any]) -> list[dict[str, Any]]:
    config_nodes = {
        str(dict(node).get("node_id") or ""): dict(node)
        for node in list(dict(monitor.get("graph_config") or {}).get("nodes") or [])
        if isinstance(node, dict)
    }
    result: list[dict[str, Any]] = []
    for view in [
        *list(monitor.get("active_node_runtime_views") or []),
        *list(monitor.get("node_runtime_views") or []),
    ]:
        payload = dict(view or {})
        node_id = str(payload.get("node_id") or "")
        node_config = config_nodes.get(node_id, {})
        result.append(
            {
                "node_id": node_id,
                "node_label": str(node_config.get("title") or node_config.get("label") or payload.get("node_label") or node_id),
                "status": str(payload.get("status") or ""),
                "executor_type": str(payload.get("executor_type") or ""),
                "task_run_id": str(payload.get("node_executor_task_run_id") or ""),
            }
        )
    if result:
        return result
    loop_state = dict(monitor.get("graph_loop_state") or {})
    node_states = dict(loop_state.get("node_states") or {})
    for node_id, node_state in node_states.items():
        payload = dict(node_state or {})
        node_config = config_nodes.get(str(node_id), {})
        result.append(
            {
                "node_id": str(node_id),
                "node_label": str(node_config.get("title") or node_config.get("label") or node_id),
                "status": str(payload.get("status") or ""),
                "executor_type": str(payload.get("executor_type") or ""),
                "task_run_id": "",
            }
        )
    return result


def _active_node_id(loop_state: dict[str, Any], node_statuses: list[dict[str, Any]]) -> str:
    for key in ("active_node_id", "current_node_id"):
        value = str(loop_state.get(key) or "").strip()
        if value:
            return value
    for status in ("running", "waiting_approval", "blocked"):
        for item in node_statuses:
            if str(item.get("status") or "") == status:
                return str(item.get("node_id") or "")
    ready = list(loop_state.get("ready_node_ids") or [])
    return str(ready[0]) if ready else ""


def _graph_lifecycle(status: str, *, failed_count: int, blocked_count: int) -> str:
    normalized = status.lower()
    if normalized in {"completed", "success", "succeeded"}:
        return "completed"
    if normalized in {"failed", "error"} or failed_count:
        return "failed"
    if blocked_count:
        return "action_required"
    if normalized in {"waiting", "waiting_executor", "waiting_approval"}:
        return "waiting"
    if normalized in {"created", "running"}:
        return "running"
    return normalized or "stale"


def _graph_stage_summary(*, active_node: dict[str, Any], status: str, ready_count: int, running_count: int) -> str:
    node_label = str(active_node.get("node_label") or active_node.get("node_id") or "").strip()
    if node_label and running_count:
        return f"正在执行节点：{node_label}"
    if ready_count:
        return f"有 {ready_count} 个节点等待执行"
    if status in {"completed", "success", "succeeded"}:
        return "任务图已完成"
    if status in {"failed", "error"}:
        return "任务图执行失败"
    return "任务图状态已同步"


def _graph_next_action(*, status: str, ready_count: int, failed_count: int, blocked_count: int) -> str:
    if failed_count:
        return "查看问题"
    if blocked_count:
        return "等待审批"
    if ready_count:
        return "继续执行"
    if status in {"completed", "success", "succeeded"}:
        return "已完成"
    return "等待进展"
