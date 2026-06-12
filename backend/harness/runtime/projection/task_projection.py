from __future__ import annotations

import json
from typing import Any

from .guards import compact, public_state, public_text, record, stable_id, text
from .items import action_kind_for_tool, action_title


SINGLE_AGENT_TASK_PROJECTION_AUTHORITY = "harness.runtime.single_agent_task_projection"
TERMINAL_STATUSES = {"completed", "failed", "stopped", "aborted", "cancelled", "canceled"}
WAITING_STATUSES = {"waiting_executor", "waiting_approval", "waiting_user", "paused", "queued"}
ERROR_STATUSES = {"failed", "error", "blocked"}
ACTIVE_ACTIVITY_STATES = {"running", "working", "partial", "waiting", "queued", "paused"}
STRUCTURED_PLAN_TOOL_NAMES = {
    "agent_todo",
}
WRITE_PROGRESS_TOOL_NAMES = {
    "write_file",
    "edit_file",
    "apply_patch",
    "save_file",
    "create_file",
    "delete_file",
    "move_file",
}
TERMINAL_PROGRESS_TOOL_NAMES = {
    "terminal",
    "shell_command",
    "run_command",
    "execute_command",
}
CONTEXT_ONLY_TOOL_NAMES = {
    "read_file",
    "read_resource_state",
    "read_persisted_tool_result",
    "search_text",
    "search_files",
    "codebase_search",
    "stat_path",
    "agent_todo",
}
MATERIAL_PROGRESS_TOOL_NAMES = WRITE_PROGRESS_TOOL_NAMES | TERMINAL_PROGRESS_TOOL_NAMES
MATERIAL_PROGRESS_ACTION_KINDS = {"write", "edit", "verify", "run"}


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
    artifact_refs = list(diagnostics.get("artifact_refs") or monitor_payload.get("artifact_refs") or [])
    raw_activities = _activities_from_events(event_dicts)
    activities = _settled_activities_for_status(raw_activities, status=status)
    todo = _todo_from_events(event_dicts)
    material_progress = _material_progress_from_activities(raw_activities, artifact_refs=artifact_refs)
    current_action = _current_action(
        activities=raw_activities,
        status=status,
        monitor=monitor_payload,
        diagnostics=diagnostics,
        task_run=task_run,
        todo=todo,
    )
    projection_summary = "" if _latest_step_is_system_tool_status(
        monitor=monitor_payload,
        diagnostics=diagnostics,
    ) else public_text(monitor_payload.get("summary") or diagnostics.get("summary"), limit=220)
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
            "summary": projection_summary,
            "current_action": current_action,
            "todo": todo,
            "activities": activities[-20:],
            "material_progress": material_progress,
            "control": control,
            "artifact_refs": artifact_refs,
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
            or payload.get("tool_name")
            or source.removeprefix("tool:")
            or "工具"
        )
        normalized_tool_name = tool_name.lower()
        if normalized_tool_name in STRUCTURED_PLAN_TOOL_NAMES or source in {"agent_todo", "system:agent_todo", "tool:agent_todo"}:
            return {}
        tool_args = record(observation_payload.get("tool_args") or observation_payload.get("args") or envelope.get("args") or structured.get("args"))
        raw_tool_target = (
            observation.get("target")
            or payload.get("target")
            or observation_payload.get("target")
            or envelope.get("target")
            or tool_args
        )
        tool_target = _tool_target_label(raw_tool_target)
        raw_status = observation.get("status") or payload.get("status")
        state = "error" if observation.get("error") or payload.get("error") else (_activity_state_from_status(raw_status) if text(raw_status) else "completed")
        action_kind = action_kind_for_tool(tool_name, raw_tool_target or tool_target or tool_args)
        detail = _tool_observation_detail(observation, observation_payload=observation_payload, envelope=envelope)
        return compact(
            {
                "activity_id": stable_id("activity", event_id, tool_name),
                "kind": "tool_observation",
                "title": action_title(action_kind=action_kind, state="error" if state == "error" else "done"),
                "detail": detail,
                "tool_name": tool_name,
                "tool_target": tool_target,
                "state": state,
                "event_ref": event_id,
                "display_surface": "tool_window",
                "visibility_level": "secondary",
                "source_kind": action_kind,
                "source_event_id": event_id,
                "event_offset": int(event.get("offset") or 0),
                "sequence": int(event.get("offset") or 0),
                "created_at": float(event.get("created_at") or 0.0),
                "artifact_refs": _artifact_refs_from_observation(observation, observation_payload=observation_payload),
            }
        )
    if event_type == "step_summary_recorded":
        step = text(payload.get("step"))
        if step in {"task_lifecycle_started", "task_executor_scheduled"}:
            return {}
        if step.startswith("task_duplicate_tool_call_guarded"):
            return {}
        if _is_system_tool_step_summary(step, presentation_source=text(payload.get("presentation_source"))):
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
                "state": _activity_state_from_status(payload.get("status")),
                "event_ref": event_id,
                "display_surface": "timeline",
                "visibility_level": "secondary",
                "source_kind": "stage_feedback",
                "source_event_id": event_id,
                "event_offset": int(event.get("offset") or 0),
                "sequence": int(event.get("offset") or 0),
                "created_at": float(event.get("created_at") or 0.0),
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
    recovery_action = _waiting_executor_recovery_action(status=status, monitor=monitor, diagnostics=diagnostics)
    if recovery_action:
        return recovery_action
    if text(status).lower() == "waiting_executor":
        return {
            "kind": "lifecycle",
            "title": "等待执行器接管",
            "detail": "当前任务处于可恢复等待状态。",
            "state": "waiting",
            "display_surface": "timeline",
            "visibility_level": "primary",
            "source_kind": "executor_wait",
        }
    allowed_activity_states = _allowed_current_activity_states(status)
    for activity in reversed(activities):
        if text(activity.get("state")) in allowed_activity_states:
            return activity
    todo_action = _current_action_from_todo(todo, status=status)
    if todo_action:
        return todo_action
    if _latest_step_is_system_tool_status(monitor=monitor, diagnostics=diagnostics):
        return {}
    return {}


def _waiting_executor_recovery_action(*, status: str, monitor: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    if text(status).lower() != "waiting_executor":
        return {}
    recoverable = record(diagnostics.get("recoverable_error") or monitor.get("recoverable_error"))
    latest_step = record(monitor.get("latest_step"))
    latest_step_name = text(
        diagnostics.get("latest_step")
        or latest_step.get("step")
        or monitor.get("latest_step_name")
        or monitor.get("latest_step")
    )
    error_code = text(recoverable.get("error_code") or recoverable.get("code"))
    is_runtime_restart = (
        latest_step_name == "task_executor_recovered_after_runtime_start"
        or error_code == "task_executor_interrupted_by_runtime_restart"
    )
    if not is_runtime_restart:
        return {}
    title = public_text(recoverable.get("user_message"), limit=160) or "后端运行时已重启，当前任务可继续。"
    detail = public_text(recoverable.get("user_message"), limit=180)
    return compact(
        {
            "kind": "lifecycle",
            "title": title,
            "detail": detail if detail != title else "",
            "state": "waiting",
            "display_surface": "timeline",
            "visibility_level": "primary",
            "source_kind": "runtime_recovery",
        }
    )


def _activity_state_from_status(value: Any) -> str:
    status = text(value).lower()
    if status in {"completed", "success", "done"}:
        return "completed"
    if status in {"waiting_executor", "waiting_approval", "waiting_user", "paused", "queued"}:
        return "waiting"
    if status in {"failed", "error", "blocked", "aborted", "cancelled", "canceled", "stopped"}:
        return "error"
    return "running"


def _is_system_tool_step_summary(step: str, *, presentation_source: str) -> bool:
    if text(presentation_source) == "system.tool_call_status":
        return True
    return step.startswith(("task_tool_batch_started", "task_tool_batch_group_started", "task_tool_repair_required"))


def _latest_step_is_system_tool_status(*, monitor: dict[str, Any], diagnostics: dict[str, Any]) -> bool:
    latest_step = record(monitor.get("latest_step") or diagnostics.get("latest_step"))
    step = text(
        latest_step.get("step")
        or monitor.get("latest_step_name")
        or monitor.get("latest_step")
        or diagnostics.get("latest_step")
    )
    presentation_source = text(
        latest_step.get("presentation_source")
        or monitor.get("presentation_source")
        or diagnostics.get("presentation_source")
    )
    return step.startswith("task_duplicate_tool_call_guarded") or _is_system_tool_step_summary(
        step,
        presentation_source=presentation_source,
    )


def _tool_target_label(value: Any) -> str:
    structured = record(value)
    if structured:
        for key in ("path", "file_path", "relative_path", "target_path", "query", "pattern", "command", "url"):
            visible = public_text(structured.get(key), limit=160)
            if visible:
                return visible
    return public_text(value, limit=160)


def _tool_observation_detail(
    observation: dict[str, Any],
    *,
    observation_payload: dict[str, Any],
    envelope: dict[str, Any],
) -> str:
    for candidate in (
        observation.get("summary"),
        observation.get("result"),
        observation_payload.get("result"),
        envelope.get("text"),
        envelope.get("summary"),
        observation.get("error"),
        observation_payload.get("error"),
        envelope.get("error"),
    ):
        visible = _visible_tool_result_text(candidate)
        if visible:
            return visible
    return ""


def _visible_tool_result_text(value: Any) -> str:
    direct = public_text(value, limit=260)
    if direct:
        return direct
    raw = text(value)
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return ""
    structured = record(parsed)
    if not structured:
        return ""
    error = structured.get("error") or structured.get("message")
    structured_error = record(structured.get("structured_error"))
    error = error or structured_error.get("message") or structured_error.get("error")
    if error:
        return public_text(error, limit=260)
    result = structured.get("result") or structured.get("summary") or structured.get("output") or structured.get("text")
    return public_text(result, limit=260)


def _current_action_state_from_status(status: str) -> str:
    normalized = text(status).lower()
    if normalized in TERMINAL_STATUSES:
        return "completed"
    if normalized in WAITING_STATUSES:
        return "waiting"
    if normalized in ERROR_STATUSES:
        return "error"
    return "running"


def _allowed_current_activity_states(status: str) -> set[str]:
    normalized = text(status).lower()
    if normalized in WAITING_STATUSES:
        return {"waiting"}
    if normalized in ERROR_STATUSES:
        return {"error"}
    if normalized in TERMINAL_STATUSES:
        return set()
    return {"running", "waiting"}


def _settled_activities_for_status(activities: list[dict[str, Any]], *, status: str) -> list[dict[str, Any]]:
    state = _settled_activity_state_from_status(status)
    if not state:
        return activities
    settled: list[dict[str, Any]] = []
    for activity in activities:
        current_state = text(activity.get("state")).lower()
        if current_state in ACTIVE_ACTIVITY_STATES:
            settled.append(compact({**activity, "state": state}))
        else:
            settled.append(activity)
    return settled


def _settled_activity_state_from_status(status: str) -> str:
    normalized = text(status).lower()
    if normalized == "completed":
        return "completed"
    if normalized in WAITING_STATUSES:
        return "waiting"
    if normalized in {"stopped", "aborted", "cancelled", "canceled"}:
        return "stopped"
    if normalized in ERROR_STATUSES:
        return "error"
    return ""


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


def _current_action_from_todo(todo: dict[str, Any], *, status: str) -> dict[str, Any]:
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
            "state": "completed" if total and completed == total else _current_action_state_from_status(status),
            "display_surface": "task_projection",
            "visibility_level": "secondary",
            "source_kind": "todo",
            "event_ref": ",".join(_trace_refs(todo)),
        }
    )


def _material_progress_from_activities(activities: list[dict[str, Any]], *, artifact_refs: list[Any]) -> dict[str, Any]:
    material_actions: list[dict[str, Any]] = []
    context_streak = 0
    material_since_context = False
    write_event_count = 0
    verification_event_count = 0
    terminal_event_count = 0
    latest_material_at = 0.0
    observed_artifact_refs = [_safe_artifact_ref(item) for item in artifact_refs]
    for activity in activities:
        tool_name = text(activity.get("tool_name")).removeprefix("tool:")
        source_kind = text(activity.get("source_kind"))
        is_material = tool_name in MATERIAL_PROGRESS_TOOL_NAMES or source_kind in MATERIAL_PROGRESS_ACTION_KINDS
        if is_material:
            state = text(activity.get("state")).lower()
            if state not in {"failed", "error", "blocked", "stopped"}:
                material_since_context = True
                context_streak = 0
                created_at = _float_value(activity.get("created_at"))
                if created_at:
                    latest_material_at = max(latest_material_at, created_at)
                if tool_name in WRITE_PROGRESS_TOOL_NAMES or source_kind in {"write", "edit"}:
                    write_event_count += 1
                if tool_name in TERMINAL_PROGRESS_TOOL_NAMES:
                    terminal_event_count += 1
                if source_kind == "verify":
                    verification_event_count += 1
                for artifact_ref in list(activity.get("artifact_refs") or []):
                    observed_artifact_refs.append(_safe_artifact_ref(artifact_ref))
                material_actions.append(
                    compact(
                        {
                            "tool_name": tool_name or source_kind,
                            "action_kind": source_kind,
                            "target": public_text(activity.get("tool_target"), limit=160),
                            "summary": public_text(activity.get("detail") or activity.get("title"), limit=180),
                            "event_ref": text(activity.get("event_ref") or activity.get("source_event_id")),
                            "event_offset": activity.get("event_offset"),
                            "created_at": created_at,
                        }
                    )
                )
            continue
        if tool_name in CONTEXT_ONLY_TOOL_NAMES or source_kind in CONTEXT_ONLY_TOOL_NAMES:
            context_streak += 1
    artifact_count = len(_dedupe_artifact_refs(observed_artifact_refs))
    return compact(
        {
            "authority": "harness.runtime.single_agent_task_projection.material_progress",
            "material_event_count": len(material_actions),
            "write_event_count": write_event_count,
            "verification_event_count": verification_event_count,
            "terminal_event_count": terminal_event_count,
            "artifact_count": artifact_count,
            "last_material_progress_at": latest_material_at,
            "material_actions": material_actions[-8:],
            "context_action_streak": context_streak,
            "material_progress_since_last_context_action": material_since_context and context_streak == 0,
        }
    )


def _artifact_refs_from_observation(observation: dict[str, Any], *, observation_payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for source in (
        observation.get("artifact_refs"),
        observation_payload.get("artifact_refs"),
        record(observation_payload.get("result_envelope")).get("artifact_refs"),
    ):
        if isinstance(source, list):
            refs.extend(_safe_artifact_ref(item) for item in source)
    return _dedupe_artifact_refs(refs)


def _safe_artifact_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return compact(
            {
                "path": text(value.get("path")),
                "kind": text(value.get("kind")),
                "label": public_text(value.get("label") or value.get("title"), limit=120),
            }
        )
    candidate = public_text(value, limit=180)
    return {"path": candidate} if candidate else {}


def _dedupe_artifact_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        payload = record(ref)
        if not payload:
            continue
        key = text(payload.get("path") or payload.get("label") or payload)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
