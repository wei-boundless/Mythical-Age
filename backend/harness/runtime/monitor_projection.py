from __future__ import annotations

import hashlib
from typing import Any

from harness.runtime.public_progress import public_runtime_progress_summary


RUNNING_TASK_RUN_STATUSES = {"created", "running"}
WAITING_TASK_RUN_STATUSES = {"waiting_executor", "waiting_approval"}
BLOCKED_TASK_RUN_STATUSES = {"blocked"}
FAILED_TASK_RUN_STATUSES = {"failed", "aborted", "cancelled", "error"}
COMPLETED_TASK_RUN_STATUSES = {"completed", "success"}
TERMINAL_TASK_RUN_STATUSES = COMPLETED_TASK_RUN_STATUSES | FAILED_TASK_RUN_STATUSES
GLOBAL_MONITOR_BUCKETS = ("running", "completed", "failed", "diagnostics")
KNOWN_TASK_RUN_STATUSES = (
    RUNNING_TASK_RUN_STATUSES
    | WAITING_TASK_RUN_STATUSES
    | BLOCKED_TASK_RUN_STATUSES
    | FAILED_TASK_RUN_STATUSES
    | COMPLETED_TASK_RUN_STATUSES
)


class TaskRunMonitorProjector:
    def __init__(self, event_log: Any, *, freshness_seconds: float = 5 * 60.0) -> None:
        self.event_log = event_log
        self.freshness_seconds = float(freshness_seconds)

    def project_task_run(self, task_run: Any, *, now: float) -> dict[str, Any]:
        current_time = float(now)
        events = self.event_log.list_events(task_run.task_run_id)
        latest_event = events[-1].to_dict() if events else {}
        latest_step = self._latest_step_summary(events)
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        created_at = float(getattr(task_run, "created_at", 0.0) or 0.0)
        updated_at = float(getattr(task_run, "updated_at", 0.0) or 0.0)
        latest_event_at = float(latest_event.get("created_at") or updated_at or 0.0)
        last_activity_at = max(created_at, updated_at, latest_event_at)
        last_activity_age_seconds = max(0.0, current_time - last_activity_at) if last_activity_at else 0.0
        status = str(getattr(task_run, "status", "") or "")
        runtime_control = self._runtime_control(diagnostics)
        control_state = str(runtime_control.get("state") or "")
        terminal = status in TERMINAL_TASK_RUN_STATUSES
        stale = control_state != "paused" and status in RUNNING_TASK_RUN_STATUSES | {"waiting_executor"} and (
            not last_activity_at or last_activity_age_seconds > self.freshness_seconds
        )
        action_required = status in {"waiting_approval"} | BLOCKED_TASK_RUN_STATUSES or control_state == "paused"
        route = self._route(task_run, diagnostics)
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
        lifecycle = "stale" if diagnostic_reasons else self._lifecycle(status, stale=stale, action_required=action_required, control_state=control_state)
        bucket = "diagnostics" if diagnostic_reasons else self._bucket(lifecycle)
        resource_class = "dynamic" if bucket == "running" and not terminal else "static"
        ended_at = self._ended_at(
            status=status,
            updated_at=updated_at,
            last_activity_at=last_activity_at,
            resource_class=resource_class,
        )
        duration_end_at = current_time if resource_class == "dynamic" else ended_at
        duration_seconds = max(0.0, duration_end_at - created_at) if created_at and duration_end_at else 0.0
        title = self._display_title(task_run, diagnostics, lifecycle=lifecycle)
        summary = public_runtime_progress_summary(
            latest_step.get("public_progress_note")
            or latest_step.get("summary")
            or diagnostics.get("public_progress_note")
            or diagnostics.get("latest_public_progress_note")
            or diagnostics.get("latest_step_summary")
            or diagnostics.get("summary")
            or ""
        )
        agent_brief = public_runtime_progress_summary(
            latest_step.get("agent_brief_output")
            or diagnostics.get("agent_brief_output")
            or ""
        )
        graph_id = str(route.get("graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_harness_config_id = str(diagnostics.get("graph_harness_config_id") or "")
        has_graph_run = bool(graph_run_id or graph_harness_config_id)
        return {
            "task_run_id": str(getattr(task_run, "task_run_id", "") or ""),
            "session_id": str(getattr(task_run, "session_id", "") or ""),
            "task_id": str(getattr(task_run, "task_id", "") or ""),
            "execution_runtime_kind": str(getattr(task_run, "execution_runtime_kind", "") or ""),
            "title": title,
            "status": status,
            "terminal_reason": str(getattr(task_run, "terminal_reason", "") or ""),
            "lifecycle": lifecycle,
            "bucket": bucket,
            "resource_class": resource_class,
            "started_at": created_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "elapsed_seconds": duration_seconds,
            "runtime_seconds": duration_seconds,
            "runtime_end_at": ended_at,
            "last_activity_at": last_activity_at,
            "last_activity_age_seconds": last_activity_age_seconds,
            "action_required": action_required,
            "terminal": terminal,
            "stale": bool(stale or diagnostic_reasons),
            "diagnostic_reasons": diagnostic_reasons,
            "runtime_control": runtime_control,
            "control_state": control_state,
            "is_live": resource_class == "dynamic",
            "summary": summary,
            "latest_event_type": str(latest_event.get("event_type") or ""),
            "latest_event_at": latest_event_at,
            "latest_event": latest_event,
            "latest_step": latest_step,
            "latest_step_summary": summary,
            "latest_public_progress_note": public_runtime_progress_summary(latest_step.get("public_progress_note") or summary),
            "agent_brief_output": agent_brief,
            "latest_step_name": str(latest_step.get("step") or diagnostics.get("latest_step") or ""),
            "latest_step_status": str(latest_step.get("status") or diagnostics.get("latest_step_status") or ""),
            "artifact_count": len(list(diagnostics.get("artifact_refs") or [])),
            "artifact_refs": list(diagnostics.get("artifact_refs") or [])[:10],
            "route": route,
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
            "graph_id": graph_id,
            "active_node_id": str(diagnostics.get("active_node_id") or diagnostics.get("node_id") or ""),
            "project_id": str(diagnostics.get("project_id") or ""),
            "project_title": self._public_text(diagnostics.get("project_title")),
            "project_runtime_status": None,
            "has_graph_run": has_graph_run,
            "event_count": len(events),
            "authority": "single_agent_runtime_monitor.item",
        }

    def build_global_monitor(self, task_runs: list[Any], *, now: float, limit: int) -> dict[str, Any]:
        requested_limit = max(1, min(int(limit or 20), 100))
        buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in GLOBAL_MONITOR_BUCKETS}
        for task_run in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True):
            if self._is_internal_child_run(task_run):
                continue
            item = self.project_task_run(task_run, now=now)
            bucket = str(item.get("bucket") or "diagnostics")
            if bucket not in buckets:
                bucket = "diagnostics"
            if len(buckets[bucket]) >= requested_limit:
                continue
            buckets[bucket].append(item)
        for name in GLOBAL_MONITOR_BUCKETS:
            buckets[name].sort(key=self._bucket_sort_key(name), reverse=True)
        items = [item for name in GLOBAL_MONITOR_BUCKETS for item in buckets[name]]
        return {
            "authority": "single_agent_runtime_monitor.global",
            "revision": self._revision(items, now=now),
            "updated_at": float(now),
            "bucket_limit": requested_limit,
            "summary": {
                "total": len(items),
                "running": len(buckets["running"]),
                "completed": len(buckets["completed"]),
                "failed": len(buckets["failed"]),
                "diagnostics": len(buckets["diagnostics"]),
                "action_required": sum(1 for item in items if item.get("action_required") is True),
            },
            "buckets": buckets,
            "task_runs": items,
        }

    def build_session_monitor(self, session_id: str, task_runs: list[Any], *, now: float, limit: int = 20) -> dict[str, Any]:
        items = [
            self.project_task_run(item, now=now)
            for item in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True)
            if not self._is_internal_child_run(item)
        ]
        visible = [item for item in items if item.get("bucket") in {"running", "diagnostics"}][: max(1, min(int(limit or 20), 100))]
        latest = items[0] if items else None
        active = visible[0] if visible else None
        return {
            "authority": "single_agent_runtime_monitor.session",
            "session_id": session_id,
            "revision": self._revision(items, now=now),
            "updated_at": float(now),
            "active_task_run_id": str(active.get("task_run_id") or "") if active else "",
            "latest_task_run_id": str(latest.get("task_run_id") or "") if latest else "",
            "task_run_count": len(items),
            "task_runs": visible,
        }

    def _lifecycle(self, status: str, *, stale: bool, action_required: bool, control_state: str = "") -> str:
        if status in COMPLETED_TASK_RUN_STATUSES:
            return "completed"
        if status in FAILED_TASK_RUN_STATUSES:
            return "failed"
        if control_state == "paused":
            return "paused"
        if control_state in {"pause_requested", "stop_requested"}:
            return "running"
        if stale:
            return "stale"
        if action_required:
            return "action_required"
        if status in WAITING_TASK_RUN_STATUSES:
            return "waiting"
        return "running"

    def _bucket(self, lifecycle: str) -> str:
        if lifecycle == "completed":
            return "completed"
        if lifecycle == "failed":
            return "failed"
        if lifecycle in {"stale", "action_required", "paused"}:
            return "diagnostics"
        return "running"

    def _ended_at(self, *, status: str, updated_at: float, last_activity_at: float, resource_class: str) -> float | None:
        if resource_class == "dynamic":
            return None
        if status in TERMINAL_TASK_RUN_STATUSES:
            return updated_at or last_activity_at or None
        return last_activity_at or updated_at or None

    def _route(self, task_run: Any, diagnostics: dict[str, Any]) -> dict[str, str]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        session_id = str(getattr(task_run, "session_id", "") or "")
        task_id = str(getattr(task_run, "task_id", "") or "")
        execution_runtime_kind = str(getattr(task_run, "execution_runtime_kind", "") or "")
        graph_id = str(diagnostics.get("graph_id") or diagnostics.get("task_graph_id") or "")
        graph_run_id = str(diagnostics.get("graph_run_id") or "")
        graph_harness_config_id = str(diagnostics.get("graph_harness_config_id") or "")
        if graph_run_id or graph_harness_config_id:
            kind = "task_graph_run"
        elif _is_chat_scoped(task_run_id=task_run_id, task_id=task_id):
            kind = "chat_turn_runtime"
        elif execution_runtime_kind == "single_agent_task":
            kind = "agent_runtime_run"
        else:
            kind = "chat_turn_runtime"
        return {
            "kind": kind,
            "session_id": session_id,
            "task_run_id": task_run_id,
            "graph_id": graph_id,
            "graph_run_id": graph_run_id,
            "graph_harness_config_id": graph_harness_config_id,
        }

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
        if kind in {"chat_turn_runtime", "agent_runtime_run"} and not route.get("session_id"):
            reasons.append("missing_route_session_id")
        if kind == "task_graph_run" and not route.get("graph_id"):
            reasons.append("missing_route_graph_id")
        event_type = str(latest_event.get("event_type") or "")
        if status in TERMINAL_TASK_RUN_STATUSES and event_type.startswith("task_run_lifecycle_waiting"):
            reasons.append("terminal_status_with_waiting_event")
        if status in RUNNING_TASK_RUN_STATUSES and str(getattr(task_run, "terminal_reason", "") or "") in TERMINAL_TASK_RUN_STATUSES:
            reasons.append("running_status_with_terminal_reason")
        if control_state and control_state not in {"running", "pause_requested", "paused", "resume_requested", "stop_requested", "stopped"}:
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

    def _display_title(self, task_run: Any, diagnostics: dict[str, Any], *, lifecycle: str) -> str:
        for key in ("title", "task_graph_title", "project_title", "goal", "task_goal"):
            value = self._public_text(diagnostics.get(key))
            if value:
                return value
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

    def _runtime_control(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        control = diagnostics.get("runtime_control")
        if not isinstance(control, dict):
            return {}
        return {
            "state": str(control.get("state") or ""),
            "requested_by": str(control.get("requested_by") or ""),
            "requested_at": float(control.get("requested_at") or 0.0),
            "reason": str(control.get("reason") or ""),
            "authority": str(control.get("authority") or "orchestration.task_run_control"),
        }

    def _public_text(self, value: Any) -> str:
        candidate = str(value or "").strip()
        if not candidate or _looks_internal_identifier(candidate):
            return ""
        return candidate

    def _latest_step_summary(self, events: list[Any]) -> dict[str, Any]:
        for event in reversed(events):
            if str(getattr(event, "event_type", "") or "") != "step_summary_recorded":
                continue
            payload = dict(getattr(event, "payload", {}) or {})
            return {
                "step": str(payload.get("step") or ""),
                "status": str(payload.get("status") or ""),
                "summary": public_runtime_progress_summary(payload.get("summary") or ""),
                "public_progress_note": public_runtime_progress_summary(payload.get("public_progress_note") or payload.get("summary") or ""),
                "agent_brief_output": public_runtime_progress_summary(payload.get("agent_brief_output") or ""),
                "presentation_source": str(payload.get("presentation_source") or ""),
                "event_id": str(getattr(event, "event_id", "") or ""),
                "offset": int(getattr(event, "offset", -1) or -1),
                "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
            }
        return {}

    def _bucket_sort_key(self, bucket: str):
        if bucket in {"completed", "failed"}:
            return lambda item: float(item.get("ended_at") or item.get("last_activity_at") or 0.0)
        return lambda item: float(item.get("last_activity_at") or 0.0)

    def _revision(self, items: list[dict[str, Any]], *, now: float) -> str:
        latest = max((float(item.get("last_activity_at") or 0.0) for item in items), default=0.0)
        identity = "|".join(
            f"{item.get('task_run_id')}:{item.get('status')}:{item.get('bucket')}:{item.get('last_activity_at')}"
            for item in items
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        return f"rtmon:{int(latest or now)}:{digest}"


def _is_chat_scoped(*, task_run_id: str, task_id: str) -> bool:
    return task_run_id.startswith("turnrun:") or task_run_id.startswith("taskrun:turn:") or task_id.startswith("turn:") or task_id.startswith("task:turn:")


def _looks_internal_identifier(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("task:", "taskrun:", "turn:", "turnrun:", "session:", "taskinst:", "coordrun:"))
