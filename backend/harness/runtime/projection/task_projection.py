from __future__ import annotations

from typing import Any

from .guards import compact, public_state, public_text, record, stable_id, text


SINGLE_AGENT_TASK_PROJECTION_AUTHORITY = "harness.runtime.single_agent_task_projection"
TERMINAL_STATUSES = {"completed", "failed", "stopped", "aborted", "cancelled", "canceled"}


def build_single_agent_task_projection(
    runtime_host: Any,
    task_run: Any,
    *,
    events: list[dict[str, Any]] | None = None,
    monitor: dict[str, Any] | None = None,
    anchor_turn_id: str = "",
    anchor_message_id: str = "",
) -> dict[str, Any]:
    task_run_id = text(getattr(task_run, "task_run_id", ""))
    if not task_run_id:
        return {}
    diagnostics = record(getattr(task_run, "diagnostics", {}))
    event_dicts = [record(event) for event in list(events or []) if isinstance(event, dict)]
    if not event_dicts and runtime_host is not None:
        event_dicts = _recent_events(runtime_host, task_run_id, limit=80)
    monitor_payload = record(monitor)
    status = text(getattr(task_run, "status", "") or monitor_payload.get("status") or "running")
    control = _control_projection(task_run, diagnostics, monitor=monitor_payload)
    activities = _activities_from_events(event_dicts)
    current_action = _current_action(activities=activities, status=status, monitor=monitor_payload)
    return compact(
        {
            "authority": SINGLE_AGENT_TASK_PROJECTION_AUTHORITY,
            "task_run_id": task_run_id,
            "task_id": text(getattr(task_run, "task_id", "")),
            "turn_id": text(anchor_turn_id) or text(diagnostics.get("turn_id")) or _turn_id_from_task_run(task_run_id),
            "anchor_turn_id": text(anchor_turn_id) or text(diagnostics.get("turn_id")) or _turn_id_from_task_run(task_run_id),
            "anchor_message_id": text(anchor_message_id),
            "status": _projection_status(status, control=control),
            "phase": _projection_phase(status=status, control=control),
            "title": public_text(_task_title(task_run, diagnostics), limit=120) or "任务执行",
            "summary": public_text(monitor_payload.get("summary") or diagnostics.get("summary"), limit=220),
            "current_action": current_action,
            "activities": activities[-20:],
            "control": control,
            "artifact_refs": list(diagnostics.get("artifact_refs") or monitor_payload.get("artifact_refs") or []),
            "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
            "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        }
    )


def build_single_agent_task_projection_for_event(
    runtime_host: Any,
    event: dict[str, Any],
    *,
    monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_id = projection_task_run_id_from_event(event)
    if not task_run_id or runtime_host is None:
        return {}
    state_index = getattr(runtime_host, "state_index", None)
    get_task_run = getattr(state_index, "get_task_run", None)
    task_run = None
    if callable(get_task_run):
        try:
            task_run = get_task_run(task_run_id)
        except Exception:
            task_run = None
    if task_run is None:
        return {}
    return build_single_agent_task_projection(runtime_host, task_run, monitor=monitor)


def projection_task_run_id_from_event(event: dict[str, Any]) -> str:
    payload = record(event.get("payload"))
    refs = record(event.get("refs"))
    run_id = text(event.get("run_id"))
    for value in (
        event.get("task_run_id"),
        refs.get("task_run_ref"),
        payload.get("task_run_id"),
        record(payload.get("task_run")).get("task_run_id"),
        run_id,
    ):
        candidate = text(value)
        if candidate.startswith("taskrun:"):
            return candidate
    return ""


def _activities_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        item = _activity_from_event(event)
        if not item:
            continue
        key = text(item.get("event_ref") or item.get("activity_id"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        activities.append(item)
    return activities


def _activity_from_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = text(event.get("event_type"))
    payload = record(event.get("payload"))
    refs = record(event.get("refs"))
    event_id = text(event.get("event_id"))
    if event_type in {"turn_tool_observation_recorded", "task_tool_observation_recorded"}:
        observation = record(payload.get("observation") or payload)
        tool_name = text(observation.get("tool_name") or payload.get("tool_name") or "工具")
        summary = public_text(observation.get("summary") or observation.get("result") or payload.get("summary"), limit=180)
        return compact(
            {
                "activity_id": stable_id("activity", event_id, tool_name),
                "kind": "tool_observation",
                "title": f"{tool_name} 已返回" if tool_name != "工具" else "工具已返回",
                "detail": summary,
                "state": "error" if observation.get("error") or payload.get("error") else "completed",
                "event_ref": event_id,
                "display_surface": "tool_window",
                "visibility_level": "secondary",
            }
        )
    if event_type == "step_summary_recorded":
        step = text(payload.get("step"))
        if step in {"task_lifecycle_started", "task_executor_scheduled"}:
            return {}
        summary = public_text(payload.get("public_progress_note") or payload.get("summary"), limit=180)
        if not summary:
            return {}
        return compact(
            {
                "activity_id": stable_id("activity", event_id, step),
                "kind": "progress",
                "title": summary,
                "state": "completed" if text(payload.get("status")) == "completed" else "running",
                "event_ref": event_id,
                "display_surface": "timeline",
                "visibility_level": "secondary",
            }
        )
    if event_type == "agent_todo_initialized":
        return compact(
            {
                "activity_id": stable_id("activity", event_id, "todo"),
                "kind": "todo",
                "title": "处理清单已建立",
                "state": "running",
                "event_ref": event_id,
                "display_surface": "timeline",
                "visibility_level": "secondary",
            }
        )
    return {}


def _current_action(*, activities: list[dict[str, Any]], status: str, monitor: dict[str, Any]) -> dict[str, Any]:
    for activity in reversed(activities):
        if text(activity.get("state")) in {"running", "waiting"}:
            return activity
    title = public_text(monitor.get("latest_public_progress_note") or monitor.get("latest_step_summary"), limit=120)
    if not title:
        return {}
    return compact(
        {
            "title": title,
            "state": "completed" if status in TERMINAL_STATUSES else "running",
            "display_surface": "timeline",
            "visibility_level": "secondary",
        }
    )


def _control_projection(task_run: Any, diagnostics: dict[str, Any], *, monitor: dict[str, Any]) -> dict[str, Any]:
    control = record(diagnostics.get("runtime_control"))
    state = text(control.get("state") or monitor.get("control_state"))
    if not state:
        return {}
    return compact(
        {
            "state": state,
            "recoverable": bool(diagnostics.get("recoverable") or monitor.get("recoverable")),
            "reason": public_text(control.get("reason") or monitor.get("diagnostic_summary"), limit=220),
        }
    )


def _projection_status(status: str, *, control: dict[str, Any]) -> str:
    state = text(control.get("state"))
    if state in {"pause_requested", "paused"}:
        return "paused"
    if status in TERMINAL_STATUSES:
        return "completed" if status == "completed" else "failed" if status == "failed" else "stopped"
    return public_state(status)


def _projection_phase(*, status: str, control: dict[str, Any]) -> str:
    state = text(control.get("state"))
    if state in {"pause_requested", "paused"}:
        return "waiting_safe_boundary"
    if status in {"waiting_executor", "queued"}:
        return "waiting_executor"
    if status in TERMINAL_STATUSES:
        return "closeout"
    return "executing"


def _task_title(task_run: Any, diagnostics: dict[str, Any]) -> str:
    contract = record(diagnostics.get("contract"))
    return text(contract.get("user_visible_goal") or diagnostics.get("user_visible_goal") or getattr(task_run, "task_id", ""))


def _recent_events(runtime_host: Any, task_run_id: str, *, limit: int) -> list[dict[str, Any]]:
    event_log = getattr(runtime_host, "event_log", None)
    if event_log is None or not hasattr(event_log, "list_recent_events"):
        return []
    try:
        events = event_log.list_recent_events(task_run_id, limit=limit)
    except Exception:
        return []
    return [event.to_dict() if hasattr(event, "to_dict") else record(event) for event in list(events or [])]


def _turn_id_from_task_run(task_run_id: str) -> str:
    parts = text(task_run_id).split(":")
    if len(parts) >= 3 and parts[1] == "turn":
        return f"turn:{parts[2]}"
    return ""

