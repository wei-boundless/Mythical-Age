from __future__ import annotations

from typing import Any

from capability_system.tools.agent_todo_state import agent_todo_state_store_from_backend_dir, todo_items
from harness.task_run_state_view import task_run_state_view
from harness.runtime.progress_presenter import build_progress_presentation, public_todo_plan_from_event
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.run_monitor.lifecycle import runtime_control


SINGLE_AGENT_TASK_PROJECTION_AUTHORITY = "harness.runtime.single_agent_task_projection.v1"
TERMINAL_PROJECTION_STATUSES = {"completed", "failed", "stopped"}


def build_single_agent_task_projection(
    runtime_host: Any,
    task_run: Any,
    *,
    events: list[dict[str, Any]] | None = None,
    monitor: dict[str, Any] | None = None,
    anchor_turn_id: str = "",
    anchor_message_id: str = "",
    max_events: int = 96,
) -> dict[str, Any]:
    task_run_id = _text(getattr(task_run, "task_run_id", ""))
    if not task_run_id or _text(getattr(task_run, "execution_runtime_kind", "")) != "single_agent_task":
        return {}

    diagnostics = _record(getattr(task_run, "diagnostics", {}))
    event_records = events if events is not None else _recent_event_dicts(runtime_host, task_run_id, limit=max_events)
    monitor_record = _record(monitor)
    contract = _task_contract(runtime_host, task_run, diagnostics)
    todo = _task_todo(runtime_host, task_run, events=event_records)
    control = _projection_control(task_run, diagnostics, monitor=monitor_record)
    projection_status = _projection_status(task_run, control=control, monitor=monitor_record)
    phase = _projection_phase(task_run, events=event_records, status=projection_status, control=control, monitor=monitor_record)
    artifact_refs = _artifact_refs(diagnostics, monitor_record)
    final_answer = _text(diagnostics.get("final_answer") or monitor_record.get("final_answer"))
    progress_presentation = _progress_presentation(
        task_run=task_run,
        events=event_records,
        monitor=monitor_record,
    )
    activities = _activities(progress_presentation=progress_presentation, todo=todo, status=projection_status, phase=phase)
    current_action = _current_action(activities=activities, monitor=monitor_record, phase=phase)
    resolved_anchor_turn_id = (
        _valid_turn_ref(anchor_turn_id)
        or _valid_turn_ref(monitor_record.get("latest_interaction_turn_id"))
        or _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))
        or _valid_turn_ref(diagnostics.get("turn_id"))
        or _turn_id_from_task_run(task_run_id)
    )
    updated_at = max(
        float(getattr(task_run, "updated_at", 0.0) or 0.0),
        max((float(event.get("created_at") or 0.0) for event in event_records), default=0.0),
    )
    user_visible_goal = (
        _text(contract.get("user_visible_goal"))
        or _text(contract.get("task_run_goal"))
        or _text(monitor_record.get("title"))
        or _text(getattr(task_run, "task_id", ""))
    )
    return _compact(
        {
            "projection_id": f"single-agent-task-projection:{task_run_id}",
            "authority": SINGLE_AGENT_TASK_PROJECTION_AUTHORITY,
            "task_run_id": task_run_id,
            "task_id": _text(getattr(task_run, "task_id", "")),
            "turn_id": _valid_turn_ref(diagnostics.get("turn_id")) or _turn_id_from_task_run(task_run_id),
            "anchor_turn_id": resolved_anchor_turn_id,
            "anchor_message_id": _text(anchor_message_id),
            "status": projection_status,
            "raw_status": _text(getattr(task_run, "status", "")),
            "task_work_state": _text(task_run_state_view(task_run, monitor=monitor_record).get("task_work_state")),
            "executor_lease_state": _text(task_run_state_view(task_run, monitor=monitor_record).get("executor_lease_state")),
            "phase": phase,
            "user_visible_goal": user_visible_goal,
            "current_action": current_action,
            "todo": todo,
            "activities": activities,
            "final_answer": final_answer,
            "artifact_refs": artifact_refs,
            "control": control,
            "debug_trace_ref": task_run_id,
            "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
            "updated_at": updated_at,
        }
    )


def projection_task_run_id_from_event(event: dict[str, Any]) -> str:
    payload = _record(event.get("payload"))
    refs = _record(event.get("refs"))
    task_run = _record(payload.get("task_run"))
    action = _record(payload.get("model_action_request"))
    candidates = (
        event.get("task_run_id"),
        event.get("run_id"),
        refs.get("task_run_ref"),
        payload.get("task_run_id"),
        task_run.get("task_run_id"),
        action.get("task_run_id"),
    )
    for value in candidates:
        normalized = _text(value)
        if normalized.startswith("taskrun:"):
            return normalized
    return ""


def build_single_agent_task_projection_for_event(
    runtime_host: Any,
    event: dict[str, Any],
    *,
    monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_id = projection_task_run_id_from_event(event)
    if not task_run_id:
        return {}
    state_index = getattr(runtime_host, "state_index", None)
    task_run = state_index.get_task_run(task_run_id) if state_index is not None else None
    if task_run is None:
        return {}
    return build_single_agent_task_projection(runtime_host, task_run, monitor=_monitor_for_task(monitor, task_run_id))


def _recent_event_dicts(runtime_host: Any, task_run_id: str, *, limit: int) -> list[dict[str, Any]]:
    event_log = getattr(runtime_host, "event_log", None)
    if event_log is None:
        return []
    window_reader = getattr(event_log, "list_event_window", None)
    if callable(window_reader):
        try:
            return [
                item.to_dict() if hasattr(item, "to_dict") else _record(item)
                for item in list(window_reader(task_run_id, limit=max(1, int(limit or 96)), include_payloads=True))
            ]
        except TypeError:
            pass
        except Exception:
            return []
    reader = getattr(event_log, "list_recent_events", None)
    if callable(reader):
        try:
            return [item.to_dict() if hasattr(item, "to_dict") else _record(item) for item in list(reader(task_run_id, limit=max(1, int(limit or 96))))]
        except TypeError:
            try:
                return [item.to_dict() if hasattr(item, "to_dict") else _record(item) for item in list(reader(task_run_id))]
            except Exception:
                return []
        except Exception:
            return []
    return []


def _task_contract(runtime_host: Any, task_run: Any, diagnostics: dict[str, Any]) -> dict[str, Any]:
    contract = _record(diagnostics.get("contract"))
    if contract:
        return contract
    object_store = getattr(runtime_host, "runtime_objects", None)
    getter = getattr(object_store, "get_object", None)
    if callable(getter):
        try:
            return _record(getter(_text(getattr(task_run, "task_contract_ref", ""))))
        except Exception:
            return {}
    return {}


def _task_todo(runtime_host: Any, task_run: Any, *, events: list[dict[str, Any]]) -> dict[str, Any]:
    session_id = _text(getattr(task_run, "session_id", ""))
    task_run_id = _text(getattr(task_run, "task_run_id", ""))
    try:
        store = agent_todo_state_store_from_backend_dir(getattr(runtime_host, "backend_dir", ""))
        plan = _record(store.read(session_id=session_id, task_id=task_run_id))
        if todo_items(plan):
            return _normalize_todo_plan(plan)
    except Exception:
        pass
    for event in reversed(events):
        plan = public_todo_plan_from_event(event)
        if plan:
            return _normalize_todo_plan(plan)
    return {}


def _normalize_todo_plan(plan: dict[str, Any]) -> dict[str, Any]:
    items = []
    active_item_id = _text(plan.get("active_item_id"))
    for raw in todo_items(plan):
        status = _text(raw.get("status")) or "pending"
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        todo_id = _text(raw.get("todo_id")) or _text(raw.get("id")) or _text(raw.get("content"))
        item = _compact(
            {
                "todo_id": todo_id,
                "content": _text(raw.get("content") or raw.get("title")),
                "active_form": _text(raw.get("active_form") or raw.get("activeForm") or raw.get("content")),
                "status": status,
                "notes": _text(raw.get("notes")),
            }
        )
        if item:
            items.append(item)
            if status == "in_progress" and not active_item_id:
                active_item_id = todo_id
    if not items:
        return {}
    return _compact(
        {
            "plan_id": _text(plan.get("plan_id")),
            "active_item_id": active_item_id,
            "completion_ready": bool(plan.get("completion_ready") is True or all(item.get("status") == "completed" for item in items)),
            "items": items,
            "authority": _text(plan.get("authority")) or "agent.todo_plan",
        }
    )


def _projection_control(task_run: Any, diagnostics: dict[str, Any], *, monitor: dict[str, Any]) -> dict[str, Any]:
    monitor_control = _record(monitor.get("runtime_control"))
    control = monitor_control or runtime_control(diagnostics)
    control_state = _text(control.get("state"))
    raw_status = _text(getattr(task_run, "status", ""))
    state_view = task_run_state_view(task_run, monitor=monitor)
    terminal = _projection_status(task_run, control={"state": control_state}, monitor=monitor) in TERMINAL_PROJECTION_STATUSES
    needs_approval = raw_status == "waiting_approval" or bool(_record(diagnostics.get("pending_approval")))
    can_resume = not terminal and bool(state_view.get("can_resume"))
    can_pause = not terminal and control_state not in {"paused", "stop_requested"} and _text(state_view.get("task_work_state")) in {"active", "ready_to_continue", "waiting_approval"}
    can_stop = not terminal and control_state != "stop_requested"
    return _compact(
        {
            "state": control_state,
            "can_pause": can_pause,
            "can_resume": can_resume,
            "can_stop": can_stop,
            "needs_approval": needs_approval,
            "pending_approval": _record(diagnostics.get("pending_approval")),
            "reason": _text(control.get("reason")),
        }
    )


def _projection_status(task_run: Any, *, control: dict[str, Any], monitor: dict[str, Any]) -> str:
    state_view = task_run_state_view(task_run, monitor=monitor)
    work_state = _text(state_view.get("task_work_state"))
    if work_state == "paused":
        return "paused"
    if work_state == "completed":
        return "completed"
    if work_state == "stopped":
        return "stopped"
    if work_state == "failed":
        return "failed"
    if work_state == "waiting_approval":
        return "waiting_approval"
    if work_state == "waiting_user":
        return "waiting_user"
    if work_state == "ready_to_continue":
        return "waiting_user"
    raw_status = _text(getattr(task_run, "status", "") or monitor.get("status")).lower()
    terminal_reason = _text(getattr(task_run, "terminal_reason", "") or monitor.get("terminal_reason")).lower()
    diagnostics = _record(getattr(task_run, "diagnostics", {}))
    executor_status = _text(diagnostics.get("executor_status") or monitor.get("executor_status")).lower()
    recovery_action = _text(diagnostics.get("recovery_action") or monitor.get("recovery_action")).lower()
    control_state = _text(control.get("state") or monitor.get("control_state")).lower()
    if control_state == "paused" or raw_status == "paused":
        return "paused"
    if raw_status in {"completed", "success", "done"}:
        return "completed"
    if raw_status in {"stopped"} or terminal_reason in {"stopped", "user_stopped"}:
        return "stopped"
    if raw_status in {"aborted", "cancelled", "canceled", "user_aborted"}:
        return "stopped" if terminal_reason in {"stopped", "user_stopped", "user_aborted", "cancelled", "canceled"} else "failed"
    if raw_status in {"failed", "error"}:
        return "failed"
    if raw_status == "waiting_approval":
        return "waiting_approval"
    if raw_status in {"waiting_user", "blocked"}:
        return "waiting_user"
    if raw_status in {"created", "queued"}:
        return "queued"
    if raw_status == "waiting_executor":
        if executor_status in {"scheduled", "running"}:
            return "running"
        return "waiting_user"
    return "running"


def _projection_phase(
    task_run: Any,
    *,
    events: list[dict[str, Any]],
    status: str,
    control: dict[str, Any],
    monitor: dict[str, Any],
) -> str:
    if status == "completed":
        return "completed"
    if status in {"failed", "stopped"}:
        return "blocked" if status == "failed" else "completed"
    if status == "paused":
        return "blocked"
    state_view = task_run_state_view(task_run, monitor=monitor)
    if _text(state_view.get("task_work_state")) == "ready_to_continue":
        return "handoff"
    if status in {"waiting_approval", "waiting_user"}:
        return "tool_waiting" if status == "waiting_approval" else "blocked"
    latest_event_type = _text(monitor.get("latest_event_type") or _latest_event_type(events))
    latest_step = _text(_record(monitor.get("latest_step")).get("step") or _latest_step(events))
    raw_status = _text(getattr(task_run, "status", ""))
    diagnostics = _record(getattr(task_run, "diagnostics", {}))
    executor_status = _text(diagnostics.get("executor_status") or monitor.get("executor_status")).lower()
    if latest_event_type in {"task_run_executor_started", "model_action_request_received"}:
        return "executing"
    if latest_event_type in {"task_tool_observation_recorded", "turn_tool_observation_recorded"} or latest_step.startswith("task_tool_"):
        return "tool_waiting"
    if executor_status == "scheduled" or latest_event_type == "task_run_executor_scheduled" or latest_step == "task_executor_scheduled":
        return "scheduled"
    if executor_status == "running":
        return "executing"
    if raw_status == "waiting_executor":
        return "handoff" if status == "running" else "blocked"
    return "executing" if status == "running" else "handoff"


def _progress_presentation(*, task_run: Any, events: list[dict[str, Any]], monitor: dict[str, Any]) -> dict[str, Any]:
    existing = _record(monitor.get("progress_presentation"))
    if existing:
        return existing
    try:
        return build_progress_presentation(events=events, task_run=task_run, monitor=monitor)
    except Exception:
        return {}


def _activities(*, progress_presentation: dict[str, Any], todo: dict[str, Any], status: str, phase: str) -> list[dict[str, Any]]:
    work_units = [dict(item) for item in list(progress_presentation.get("work_units") or []) if isinstance(item, dict)]
    activities = [_activity_from_work_unit(item) for item in work_units]
    activities = [item for item in activities if item]
    if todo and not any(item.get("kind") == "todo" for item in activities):
        activities.append(
            _compact(
                {
                    "activity_id": f"todo:{todo.get('plan_id') or todo.get('active_item_id') or 'plan'}",
                    "kind": "todo",
                    "title": "处理清单",
                    "detail": _todo_detail(todo),
                    "state": "completed" if todo.get("completion_ready") else "running",
                }
            )
        )
    if not activities and status in {"running", "queued"}:
        activities.append(
            {
                "activity_id": f"status:{phase}",
                "kind": "status",
                "title": "正在处理",
                "detail": "",
                "state": "running",
            }
        )
    return activities[-12:]


def _activity_from_work_unit(unit: dict[str, Any]) -> dict[str, Any]:
    kind = _text(unit.get("kind"))
    if not kind:
        return {}
    state = _item_state(_text(unit.get("state")))
    title = _text(unit.get("title") or _kind_title(kind))
    detail = public_runtime_progress_summary(
        unit.get("action")
        or unit.get("agent_feedback")
        or unit.get("judgment")
        or unit.get("next_action")
        or unit.get("risk")
        or ""
    )
    trace_refs = [_text(value) for value in list(unit.get("technical_trace_refs") or []) if _text(value)]
    return _compact(
        {
            "activity_id": _text(unit.get("unit_id")) or (trace_refs[0] if trace_refs else ""),
            "kind": _projection_activity_kind(kind),
            "title": title,
            "detail": detail,
            "state": state,
            "event_ref": trace_refs[0] if trace_refs else "",
            "source_kind": kind,
        }
    )


def _current_action(*, activities: list[dict[str, Any]], monitor: dict[str, Any], phase: str) -> dict[str, Any]:
    for activity in reversed(activities):
        if _text(activity.get("state")) in {"running", "waiting"}:
            return _compact(
                {
                    "title": _text(activity.get("title")),
                    "detail": _text(activity.get("detail")),
                    "state": _text(activity.get("state")),
                    "event_ref": _text(activity.get("event_ref")),
                    "phase": phase,
                }
            )
    latest_step = _record(monitor.get("latest_step"))
    return _compact(
        {
            "title": _text(monitor.get("latest_step_summary") or latest_step.get("summary") or monitor.get("summary") or "正在处理"),
            "detail": _text(latest_step.get("public_progress_note") or latest_step.get("agent_brief_output")),
            "state": "completed" if phase == "completed" else "running",
            "event_ref": _text(_record(monitor.get("latest_event")).get("event_id")),
            "phase": phase,
        }
    )


def _artifact_refs(diagnostics: dict[str, Any], monitor: dict[str, Any]) -> list[dict[str, Any]]:
    raw = list(diagnostics.get("artifact_refs") or monitor.get("artifact_refs") or [])
    return [dict(item) for item in raw if isinstance(item, dict)]


def _monitor_for_task(monitor: dict[str, Any] | None, task_run_id: str) -> dict[str, Any]:
    record = _record(monitor)
    if _text(record.get("task_run_id")) == task_run_id:
        return record
    task_run = _record(record.get("task_run"))
    if _text(task_run.get("task_run_id")) == task_run_id:
        return record
    for item in list(record.get("items") or record.get("task_runs") or []):
        item_record = _record(item)
        item_task_run = _record(item_record.get("task_run"))
        if _text(item_record.get("task_run_id") or item_task_run.get("task_run_id")) == task_run_id:
            return item_record
    return {}


def _latest_event_type(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        event_type = _text(event.get("event_type"))
        if event_type:
            return event_type
    return ""


def _latest_step(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        payload = _record(event.get("payload"))
        step = _text(payload.get("step"))
        if step:
            return step
    return ""


def _todo_detail(todo: dict[str, Any]) -> str:
    items = [item for item in list(todo.get("items") or []) if isinstance(item, dict)]
    if not items:
        return ""
    completed = sum(1 for item in items if _text(item.get("status")) == "completed")
    return f"{completed}/{len(items)} 已完成"


def _projection_activity_kind(kind: str) -> str:
    if kind == "todo_plan":
        return "todo"
    if kind in {"work_action"}:
        return "action"
    if kind in {"observation_report", "opening_judgment"}:
        return "observation"
    if kind in {"final_summary"}:
        return "final"
    if kind in {"blocked"}:
        return "error"
    return "status"


def _kind_title(kind: str) -> str:
    return {
        "todo_plan": "处理清单",
        "work_action": "执行动作",
        "observation_report": "处理反馈",
        "opening_judgment": "开局判断",
        "final_summary": "收尾总结",
        "blocked": "处理受阻",
    }.get(kind, "处理进展")


def _item_state(state: str) -> str:
    normalized = _text(state).lower()
    if normalized in {"done", "completed", "success", "passed", "ready"}:
        return "completed"
    if normalized in {"error", "failed", "blocked", "missing"}:
        return "failed"
    if normalized in {"waiting", "waiting_approval", "waiting_user"}:
        return "waiting"
    if normalized in {"stopped", "aborted", "cancelled", "canceled"}:
        return "stopped"
    return "running"


def _turn_id_from_task_run(task_run_id: str) -> str:
    prefix = "taskrun:"
    if not task_run_id.startswith(prefix):
        return ""
    rest = task_run_id[len(prefix):]
    if ":task" in rest:
        rest = rest.split(":task", 1)[0]
    parts = rest.split(":")
    if len(parts) >= 3 and parts[0] == "turn":
        return ":".join(parts[:3])
    return rest if rest.startswith("turn:") else ""


def _valid_turn_ref(value: Any) -> str:
    text = _text(value)
    return text if text.startswith("turn:") else ""


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        result[key] = value
    return result
