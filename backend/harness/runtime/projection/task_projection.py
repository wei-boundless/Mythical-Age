from __future__ import annotations

import json
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
    todo = _todo_from_events(event_dicts)
    current_action = _current_action(
        activities=activities,
        status=status,
        monitor=monitor_payload,
        diagnostics=diagnostics,
        task_run=task_run,
        todo=todo,
    )
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
            "todo": todo,
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
        if tool_name == "agent_todo" or text(observation.get("source")) in {"system:agent_todo", "tool:agent_todo"}:
            return {}
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
        action_state = record(payload.get("public_action_state"))
        summary = public_text(
            payload.get("current_judgment")
            or action_state.get("current_judgment")
            or payload.get("agent_brief_output")
            or payload.get("public_progress_note")
            or payload.get("summary"),
            limit=180,
        )
        if not summary:
            return {}
        next_action = public_text(payload.get("next_action") or action_state.get("next_action"), limit=180)
        return compact(
            {
                "activity_id": stable_id("activity", event_id, step),
                "kind": "progress",
                "title": summary,
                "detail": next_action if next_action != summary else "",
                "state": "completed" if text(payload.get("status")) == "completed" else "running",
                "event_ref": event_id,
                "display_surface": "timeline",
                "visibility_level": "secondary",
                "source_kind": "stage_feedback",
            }
        )
    if event_type == "agent_todo_initialized":
        return {}
    return {}


def _current_action(
    *,
    activities: list[dict[str, Any]],
    status: str,
    monitor: dict[str, Any],
    diagnostics: dict[str, Any],
    task_run: Any,
    todo: dict[str, Any],
) -> dict[str, Any]:
    if text(status).lower() in TERMINAL_STATUSES:
        return _terminal_current_action(status=status, monitor=monitor, diagnostics=diagnostics, task_run=task_run)
    for activity in reversed(activities):
        if text(activity.get("state")) in {"running", "waiting"}:
            return activity
    todo_action = _current_action_from_todo(todo)
    if todo_action:
        return todo_action
    latest_action_state = record(diagnostics.get("latest_public_action_state") or monitor.get("latest_public_action_state"))
    title = public_text(
        diagnostics.get("latest_current_judgment")
        or latest_action_state.get("current_judgment")
        or monitor.get("current_judgment")
        or monitor.get("latest_current_judgment")
        or monitor.get("latest_public_progress_note")
        or monitor.get("latest_step_summary"),
        limit=120,
    )
    if not title:
        return {}
    next_action = public_text(
        diagnostics.get("latest_next_action")
        or latest_action_state.get("next_action")
        or monitor.get("next_action")
        or monitor.get("latest_next_action"),
        limit=180,
    )
    return compact(
        {
            "title": title,
            "detail": next_action if next_action != title else "",
            "state": "completed" if status in TERMINAL_STATUSES else "running",
            "display_surface": "timeline",
            "visibility_level": "secondary",
            "source_kind": "stage_feedback",
        }
    )


def _terminal_current_action(
    *,
    status: str,
    monitor: dict[str, Any],
    diagnostics: dict[str, Any],
    task_run: Any,
) -> dict[str, Any]:
    normalized = text(status).lower()
    if normalized == "completed":
        return compact(
            {
                "kind": "closeout",
                "title": "结果收口",
                "detail": _closeout_summary(diagnostics=diagnostics, monitor=monitor),
                "state": "completed",
                "display_surface": "timeline",
                "visibility_level": "primary",
                "source_kind": "closeout",
            }
        )
    if normalized in {"stopped", "aborted", "cancelled", "canceled"}:
        return compact(
            {
                "kind": "closeout",
                "title": "任务已停止",
                "detail": _terminal_detail(diagnostics=diagnostics, monitor=monitor, task_run=task_run),
                "state": "stopped",
                "display_surface": "timeline",
                "visibility_level": "primary",
                "source_kind": "closeout",
            }
        )
    return compact(
        {
            "kind": "closeout",
            "title": "处理遇到阻塞",
            "detail": _terminal_detail(diagnostics=diagnostics, monitor=monitor, task_run=task_run),
            "state": "error",
            "display_surface": "timeline",
            "visibility_level": "primary",
            "source_kind": "closeout",
        }
    )


def _closeout_summary(*, diagnostics: dict[str, Any], monitor: dict[str, Any]) -> str:
    for value in (
        diagnostics.get("closeout_summary"),
        diagnostics.get("final_answer"),
        monitor.get("closeout_summary"),
        monitor.get("final_answer"),
    ):
        visible = public_text(value, limit=260)
        if visible:
            return visible
    return ""


def _todo_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        plan = _todo_plan_from_event(event)
        if plan:
            return plan
    return {}


def _todo_plan_from_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = text(event.get("event_type"))
    payload = record(event.get("payload"))
    if event_type == "agent_todo_initialized":
        for candidate in (payload, payload.get("observation"), record(payload.get("observation")).get("payload")):
            plan = _parse_todo_plan(candidate, trace_ref=text(event.get("event_id")))
            if plan:
                return plan
        return {}
    if event_type not in {"turn_tool_observation_recorded", "task_tool_observation_recorded"}:
        return {}
    observation = record(payload.get("observation") or payload.get("tool_observation") or payload)
    source = text(observation.get("source"))
    observation_payload = record(observation.get("payload"))
    envelope = record(observation_payload.get("result_envelope") or observation.get("result_envelope"))
    structured = record(observation_payload.get("structured_payload") or envelope.get("structured_payload"))
    tool_name = text(
        observation.get("tool_name")
        or observation_payload.get("tool_name")
        or envelope.get("tool_name")
        or structured.get("tool_name")
        or source.removeprefix("tool:")
    )
    if tool_name != "agent_todo" and source not in {"agent_todo", "system:agent_todo", "tool:agent_todo"}:
        return {}
    for candidate in (
        observation_payload.get("result"),
        observation_payload.get("text"),
        observation_payload.get("structured_payload"),
        envelope.get("text"),
        envelope.get("structured_payload"),
        observation.get("summary"),
        observation,
    ):
        plan = _parse_todo_plan(candidate, trace_ref=text(event.get("event_id")))
        if plan:
            return plan
    return {}


def _parse_todo_plan(value: Any, *, trace_ref: str = "") -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
    elif isinstance(value, dict):
        parsed = dict(value)
    else:
        return {}
    for key in ("result", "structured_payload", "tool_result", "payload"):
        nested_value = parsed.get(key)
        if nested_value is not None and "items" not in parsed:
            nested = _parse_todo_plan(nested_value, trace_ref=trace_ref)
            if nested:
                return nested
    items = [_todo_item(item) for item in list(parsed.get("items") or []) if isinstance(item, dict)]
    items = [item for item in items if item]
    if not items:
        return {}
    active = text(parsed.get("active_item_id"))
    if active and not any(item.get("todo_id") == active and item.get("status") == "in_progress" for item in items):
        active = ""
    trace_refs = _trace_refs(parsed)
    if trace_ref and trace_ref not in trace_refs:
        trace_refs.append(trace_ref)
    completed = sum(1 for item in items if item.get("status") == "completed")
    total = len(items)
    return compact(
        {
            "plan_id": text(parsed.get("plan_id")),
            "active_item_id": active,
            "completion_ready": bool(parsed.get("completion_ready") or (total and completed == total)),
            "completed_count": completed,
            "total_count": total,
            "items": items,
            "trace_refs": trace_refs,
            "authority": "harness.runtime.single_agent_task_projection.todo",
        }
    )


def _todo_item(item: dict[str, Any]) -> dict[str, Any]:
    content = public_text(item.get("content") or item.get("title"), limit=180)
    if not content:
        return {}
    status = text(item.get("status") or "pending")
    if status not in {"pending", "in_progress", "completed", "blocked"}:
        status = "pending"
    return compact(
        {
            "todo_id": text(item.get("todo_id") or content),
            "content": content,
            "active_form": public_text(item.get("active_form") or content, limit=180),
            "status": status,
            "notes": public_text(item.get("notes"), limit=180),
        }
    )


def _current_action_from_todo(todo: dict[str, Any]) -> dict[str, Any]:
    items = [record(item) for item in list(record(todo).get("items") or []) if isinstance(item, dict)]
    if not items:
        return {}
    active_id = text(todo.get("active_item_id"))
    active = next((item for item in items if text(item.get("todo_id")) == active_id), {})
    completed = int(todo.get("completed_count") or sum(1 for item in items if text(item.get("status")) == "completed"))
    total = int(todo.get("total_count") or len(items))
    title = "任务进度"
    detail_parts = []
    if total:
        detail_parts.append(f"{completed}/{total} 已完成")
    if active:
        detail_parts.append("当前阶段正在推进")
    return compact(
        {
            "kind": "todo",
            "title": title,
            "detail": "；".join(detail_parts),
            "state": "completed" if total and completed == total else "running",
            "display_surface": "task_projection",
            "visibility_level": "secondary",
            "source_kind": "todo",
            "event_ref": ",".join(_trace_refs(todo)),
        }
    )


def _trace_refs(value: dict[str, Any]) -> list[str]:
    refs = value.get("trace_refs") or value.get("technical_trace_refs") or []
    if not isinstance(refs, list):
        return []
    return [text(item) for item in refs if text(item)]


def _terminal_detail(*, diagnostics: dict[str, Any], monitor: dict[str, Any], task_run: Any) -> str:
    control = record(diagnostics.get("runtime_control"))
    for value in (
        control.get("reason"),
        monitor.get("diagnostic_summary"),
        monitor.get("summary"),
        getattr(task_run, "terminal_reason", ""),
    ):
        visible = public_text(value, limit=220)
        if visible:
            return visible
    return ""


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
