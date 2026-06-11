from __future__ import annotations

from typing import Any

from .guards import compact, public_text, record, stable_id, text
from .items import (
    control_item,
    status_item,
    work_action_item,
)
from .projector import project_public_projection_event
from .task_projection import build_single_agent_task_projection_for_event


PUBLIC_PROJECTION_AUTHORITY = "runtime_monitor.public_event_projection"
INTERNAL_TURN_TERMINAL_REASONS = {
    "active_work_control",
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "active_work_control_denied",
    "active_work_control_action_not_allowed",
    "ask_user",
    "assistant_message",
    "block",
    "stream_cancelled",
    "turn_stream_closed",
    "harness.entrypoint_error",
}


def project_runtime_monitor_event_public_delta(
    runtime_event: dict[str, Any],
    *,
    runtime_host: Any | None = None,
    monitor: dict[str, Any] | None = None,
    include_task_projection: bool = True,
    allow_runtime_lookup: bool = True,
) -> dict[str, Any]:
    event = _hydrate_external_event_payload(record(runtime_event), runtime_host=runtime_host)
    event_type = text(event.get("event_type"))
    public_event_type = _public_event_type(event_type, event)
    if not public_event_type:
        return {}
    event = _hydrate_event_for_projection(event, runtime_host=runtime_host, allow_runtime_lookup=allow_runtime_lookup)
    anchor = _public_anchor(event, monitor=monitor)
    task_projection = build_single_agent_task_projection_for_event(
        runtime_host,
        event,
        monitor=monitor,
    ) if include_task_projection and runtime_host is not None else {}
    data = _public_event_data(public_event_type=public_event_type, event=event, monitor=monitor)
    projection = project_public_projection_event(
        public_event_type,
        data,
        sequence=int(event.get("offset") or 0),
        public_anchor=anchor,
        task_projection=task_projection,
    )
    envelope = projection["public_projection_envelope"]
    items = _projection_items_from_envelope(envelope)
    result = {
        "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
        "public_event_type": public_event_type,
        "public_anchor": anchor,
        "public_projection_envelope": envelope,
        "debug_trace_ref": _debug_trace_ref(event, anchor=anchor),
    }
    if not items:
        result["public_projection_skip_reason"] = "empty_public_delta"
    if task_projection:
        result["task_projection"] = task_projection
        result["task_projection_delta"] = task_projection
    return result


def project_public_timeline_from_events(
    events: list[Any],
    *,
    runtime_host: Any | None = None,
    monitor: dict[str, Any] | None = None,
    run_id: str = "",
    task_run_id: str = "",
    turn_run_id: str = "",
    final_answer: str = "",
    status: str = "",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    action_requests = _action_requests_by_ref([_event_record(event) for event in events])
    for event in _ordered_events(events):
        event = _event_with_action_request(event, action_requests)
        delta = project_runtime_monitor_event_public_delta(
            event,
            runtime_host=runtime_host,
            monitor=monitor,
            include_task_projection=False,
            allow_runtime_lookup=False,
        )
        for item in _projection_items_from_envelope(record(delta.get("public_projection_envelope"))):
            _append_or_replace_public_item(items, index_by_key, item)
    return _trim_public_timeline_items(items, limit)


def build_public_chat_timeline(
    *,
    progress_presentation: dict[str, Any] | None,
    final_answer: str = "",
    artifact_refs: list[Any] | None = None,
    status: str = "",
    terminal_reason: str = "",
) -> list[dict[str, Any]]:
    presentation = record(progress_presentation)
    units = [record(item) for item in list(presentation.get("work_units") or []) if isinstance(item, dict)]
    items: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for unit in units:
        unit_state = unit.get("status") or unit.get("state") or "running"
        feedback = public_text(
            unit.get("agent_brief_output")
            or unit.get("current_judgment")
            or unit.get("judgment")
            or unit.get("summary")
            or unit.get("agent_feedback"),
            limit=260,
        )
        if feedback:
            item = status_item(
                item_id=stable_id("status", unit.get("unit_id"), feedback),
                title=feedback,
                state=unit_state,
                trace_refs=_trace_refs(unit),
            )
            _append_or_replace_public_item(items, index_by_key, item)
        if _is_tool_like(unit):
            item = work_action_item(
                item_id=stable_id("work", unit.get("unit_id"), unit.get("tool_name"), unit.get("title")),
                tool_name=unit.get("tool_name") or unit.get("kind"),
                raw_target=unit.get("target") or unit.get("title"),
                summary=unit.get("summary") or unit.get("action"),
                observation=_first_evidence_summary(unit),
                state=unit_state,
                trace_refs=_trace_refs(unit),
            )
            _append_or_replace_public_item(items, index_by_key, item)
        report_text = public_text(unit.get("observation") or unit.get("implication"), limit=260)
        if report_text:
            _append_or_replace_public_item(
                items,
                index_by_key,
                status_item(
                    item_id=stable_id("report", unit.get("unit_id"), report_text),
                    title=report_text,
                    state=unit_state,
                    trace_refs=_trace_refs(unit),
                ),
            )
    for artifact in list(artifact_refs or []):
        item = status_item(
            item_id=stable_id("artifact", artifact),
            title="产物已生成",
            detail=record(artifact).get("label") or record(artifact).get("path") or artifact,
            state="done",
        )
        _append_or_replace_public_item(items, index_by_key, item)
    if status in {"failed", "error", "blocked"} or terminal_reason:
        item = control_item(
            item_id=stable_id("blocked", status, terminal_reason),
            kind="error_notice",
            title=terminal_reason or "处理遇到阻塞",
            state="error",
        )
        _append_or_replace_public_item(items, index_by_key, item)
    return items


def build_public_chat_timeline_from_progress_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for entry in list(entries or []):
        payload = record(entry)
        kind = text(payload.get("kind"))
        level = text(payload.get("level"))
        state = "error" if level == "error" else "done" if level == "success" else "waiting" if level == "waiting" else "running"
        refs = [text(payload.get("id"))] if text(payload.get("id")) else []
        body = public_text(payload.get("body") or payload.get("agentBrief") or payload.get("publicNote") or payload.get("title"), limit=260)
        if kind == "tool":
            tool_call_id = text(payload.get("toolCallId") or payload.get("tool_call_id"))
            tool_lifecycle_id = text(payload.get("toolLifecycleId") or payload.get("tool_lifecycle_id") or tool_call_id)
            target = text(payload.get("target") or payload.get("toolTarget") or payload.get("tool_target"))
            item = work_action_item(
                item_id=tool_lifecycle_id or stable_id("progress-tool", payload.get("id"), payload.get("toolName")),
                tool_name=payload.get("toolName"),
                tool_lifecycle_id=tool_lifecycle_id,
                tool_call_id=tool_call_id,
                raw_target=target or payload.get("title"),
                summary=payload.get("title"),
                observation=body,
                state=state,
                trace_refs=refs,
            )
        elif kind == "model":
            item = status_item(
                item_id=stable_id("progress-model", payload.get("id"), body),
                title=body,
                state=state,
                trace_refs=refs,
            )
        elif state == "error":
            item = control_item(
                item_id=stable_id("progress-error", payload.get("id"), body),
                kind="error_notice",
                title=body,
                state="error",
                trace_refs=refs,
            )
        else:
            item = status_item(
                item_id=stable_id("progress-status", payload.get("id"), body),
                title=body,
                state=state,
                trace_refs=refs,
            )
        _append_or_replace_public_item(items, index_by_key, item)
    return items


def _public_event_type(event_type: str, event: dict[str, Any]) -> str:
    if event_type == "agent_turn_terminal" and _is_internal_turn_terminal(event):
        return ""
    if event_type in {"model_action_request_received", "model_action_admission_checked"}:
        return "model_action_admission"
    if event_type == "step_summary_recorded":
        return "runtime_step_summary"
    if event_type in {"turn_tool_observation_recorded", "task_tool_observation_recorded"}:
        return event_type
    if event_type == "agent_todo_initialized":
        return "task_run_lifecycle_event"
    if event_type in {"task_run_lifecycle_started", "task_run_executor_started", "task_run_lifecycle_waiting_executor", "task_run_executor_scheduled", "active_work_control_observed"}:
        return "runtime_status"
    if event_type in {"active_task_steer_recorded", "active_task_steer_accepted", "active_task_steer_included", "active_task_steer_consumed"}:
        return "active_task_steer_accepted"
    if event_type in {"task_run_lifecycle_finished", "agent_turn_terminal"}:
        return _terminal_public_event_type(event)
    if event_type in {"loop_error", "agent_turn_failed"}:
        return "error"
    return ""


def _public_event_data(*, public_event_type: str, event: dict[str, Any], monitor: dict[str, Any] | None) -> dict[str, Any]:
    payload = record(event.get("payload"))
    anchor = _public_anchor(event, monitor=monitor)
    base = {
        "event": event,
        "runtime_event_id": text(event.get("event_id")),
        "runtime_run_id": text(event.get("run_id")),
        "event_offset": int(event.get("offset") or 0),
        "created_at": event.get("created_at"),
        "runtime_task_run_id": anchor.get("task_run_id") or text(event.get("run_id")),
        "task_run_id": anchor.get("task_run_id") or "",
        "turn_run_id": anchor.get("turn_run_id") or "",
        "active_turn": {
            "turn_id": anchor.get("anchor_turn_id") or "",
            "turn_run_id": anchor.get("turn_run_id") or "",
        },
    }
    if public_event_type == "runtime_step_summary":
        return {
            **base,
            "step": payload.get("step"),
            "status": payload.get("status"),
            "summary": payload.get("summary"),
            "public_progress_note": payload.get("public_progress_note"),
            "agent_brief_output": payload.get("agent_brief_output"),
            "current_judgment": payload.get("current_judgment"),
            "next_action": payload.get("next_action"),
            "completion_status": payload.get("completion_status"),
            "public_action_state": payload.get("public_action_state"),
            "tool_name": payload.get("tool_name"),
        }
    if public_event_type == "runtime_status":
        return {**base, **_runtime_status_data(event)}
    if public_event_type in {"done", "error", "stopped"}:
        return {**base, **_terminal_data(event, public_event_type=public_event_type)}
    if public_event_type == "active_task_steer_accepted":
        return {
            **base,
            "summary": _active_task_steer_summary(payload),
            "title": _active_task_steer_title(payload),
            "detail": _active_task_steer_detail(payload),
            "state": _active_task_steer_state(payload),
        }
    return base


def _hydrate_event_for_projection(event: dict[str, Any], *, runtime_host: Any | None, allow_runtime_lookup: bool = True) -> dict[str, Any]:
    event = _hydrate_external_event_payload(event, runtime_host=runtime_host)
    if text(event.get("event_type")) != "model_action_admission_checked":
        return event
    payload = record(event.get("payload"))
    if record(payload.get("model_action_request")) or not allow_runtime_lookup:
        return event
    action = _find_model_action_request(event, runtime_host=runtime_host)
    if not action:
        return event
    return {**event, "payload": {**payload, "model_action_request": action}}


def _find_model_action_request(event: dict[str, Any], *, runtime_host: Any | None) -> dict[str, Any]:
    action_ref = text(record(event.get("refs")).get("action_request_ref"))
    if not action_ref or runtime_host is None:
        return {}
    event_log = getattr(runtime_host, "event_log", None)
    if event_log is None or not hasattr(event_log, "list_recent_events"):
        return {}
    try:
        events = event_log.list_recent_events(text(event.get("run_id")), limit=80)
    except Exception:
        return {}
    for candidate in reversed(list(events or [])):
        payload = _hydrate_external_event_payload(_event_record(candidate), runtime_host=runtime_host)
        if text(payload.get("event_type")) != "model_action_request_received":
            continue
        refs = record(payload.get("refs"))
        action = record(record(payload.get("payload")).get("model_action_request"))
        if action_ref in {text(refs.get("action_request_ref")), text(action.get("request_id"))}:
            return action
    return {}


def _hydrate_external_event_payload(event: dict[str, Any], *, runtime_host: Any | None) -> dict[str, Any]:
    if runtime_host is None:
        return event
    event_log = getattr(runtime_host, "event_log", None)
    payload_store = getattr(event_log, "payload_store", None)
    if payload_store is None or not hasattr(payload_store, "hydrate_event_payload"):
        return event
    try:
        return dict(payload_store.hydrate_event_payload(dict(event or {})))
    except Exception:
        return event


def _public_anchor(event: dict[str, Any], *, monitor: dict[str, Any] | None) -> dict[str, Any]:
    payload = record(event.get("payload"))
    refs = record(event.get("refs"))
    run_id = text(event.get("run_id") or event.get("task_run_id"))
    task_run_id = _task_run_id(event.get("task_run_id") or refs.get("task_run_ref") or payload.get("task_run_id") or run_id)
    turn_run_id = _turn_run_id(refs.get("turn_run_ref") or payload.get("turn_run_id") or run_id)
    action = record(payload.get("model_action_request"))
    task_run = record(payload.get("task_run"))
    diagnostics = record(payload.get("diagnostics"))
    anchor_turn_id = _turn_id(
        refs.get("turn_ref")
        or payload.get("turn_id")
        or action.get("turn_id")
        or task_run.get("turn_id")
        or diagnostics.get("turn_id")
        or diagnostics.get("latest_interaction_turn_id")
    )
    if not anchor_turn_id:
        anchor_turn_id = _turn_id_from_run_id(run_id) or _turn_id_from_run_id(task_run_id) or _turn_id_from_monitor(run_id, monitor)
    return compact(
        {
            "run_id": run_id,
            "task_run_id": task_run_id,
            "turn_run_id": turn_run_id,
            "anchor_turn_id": anchor_turn_id,
            "turn_id": anchor_turn_id,
            "anchor_role": "assistant",
        }
    )


def _terminal_public_event_type(event: dict[str, Any]) -> str:
    payload = record(event.get("payload"))
    task_run = record(payload.get("task_run"))
    status = text(payload.get("status") or task_run.get("status")).lower()
    terminal_reason = text(payload.get("terminal_reason") or task_run.get("terminal_reason")).lower()
    if terminal_reason in {"user_aborted", "stopped", "cancelled", "canceled"} or status in {"aborted", "cancelled", "canceled"}:
        return "stopped"
    if status in {"completed", "success", "succeeded", "done"}:
        return "done"
    if status in {"failed", "error", "blocked"} or terminal_reason:
        return "error"
    return "done"


def _terminal_data(event: dict[str, Any], *, public_event_type: str) -> dict[str, Any]:
    payload = record(event.get("payload"))
    task_run = record(payload.get("task_run"))
    raw_reason = text(payload.get("terminal_reason") or task_run.get("terminal_reason") or payload.get("status") or task_run.get("status"))
    summary = payload.get("receipt_summary") or payload.get("summary") or payload.get("final_answer") or record(task_run.get("diagnostics")).get("final_answer")
    if public_event_type == "error":
        return {"error": payload.get("error") or payload.get("message") or summary or "处理失败", "terminal_reason": raw_reason}
    if public_event_type == "stopped":
        return {"reason": payload.get("reason") or summary or raw_reason or "当前处理已停止", "terminal_reason": raw_reason}
    return {
        "terminal_reason": raw_reason,
        "answer_channel": payload.get("answer_channel"),
        "receipt_summary": summary,
        "summary": summary,
        "content": payload.get("content") or payload.get("final_answer"),
    }


def _runtime_status_data(event: dict[str, Any]) -> dict[str, Any]:
    event_type = text(event.get("event_type"))
    payload = record(event.get("payload"))
    if event_type == "active_work_control_observed":
        return {"title": payload.get("title") or "当前工作控制", "detail": payload.get("detail"), "state": payload.get("state") or "running"}
    if event_type in {"task_run_lifecycle_waiting_executor", "task_run_executor_scheduled"}:
        return {"title": "等待执行器继续", "detail": payload.get("summary"), "state": "waiting"}
    return {"state": payload.get("status") or "running", "summary": payload.get("summary")}


def _active_task_steer_summary(payload: dict[str, Any]) -> str:
    steer = record(payload.get("steer"))
    transition = record(payload.get("steer_transition"))
    return text(transition.get("summary") or steer.get("summary") or steer.get("instruction") or payload.get("summary"))


def _active_task_steer_title(payload: dict[str, Any]) -> str:
    transition = record(payload.get("steer_transition"))
    return text(transition.get("title") or "已收到补充要求")


def _active_task_steer_detail(payload: dict[str, Any]) -> str:
    transition = record(payload.get("steer_transition"))
    steer = record(payload.get("steer"))
    return text(transition.get("summary") or steer.get("content") or payload.get("summary"))


def _active_task_steer_state(payload: dict[str, Any]) -> str:
    transition = record(payload.get("steer_transition"))
    state = text(transition.get("status"))
    if state:
        return state
    return "running"


def _is_internal_turn_terminal(event: dict[str, Any]) -> bool:
    payload = record(event.get("payload"))
    terminal_reason = text(payload.get("terminal_reason")).lower()
    status = text(payload.get("status")).lower()
    return terminal_reason in INTERNAL_TURN_TERMINAL_REASONS or (status in {"aborted", "cancelled", "canceled"} and terminal_reason == "stream_cancelled")


def _action_requests_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    for event in events:
        if text(event.get("event_type")) != "model_action_request_received":
            continue
        payload = record(event.get("payload"))
        refs = record(event.get("refs"))
        action = record(payload.get("model_action_request"))
        for key in (refs.get("action_request_ref"), action.get("request_id")):
            if text(key):
                requests[text(key)] = action
    return requests


def _event_with_action_request(event: dict[str, Any], action_requests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if text(event.get("event_type")) != "model_action_admission_checked":
        return event
    payload = record(event.get("payload"))
    if record(payload.get("model_action_request")):
        return event
    action_ref = text(record(event.get("refs")).get("action_request_ref"))
    action = action_requests.get(action_ref)
    if not action:
        return event
    return {**event, "payload": {**payload, "model_action_request": action}}


def _ordered_events(events: list[Any]) -> list[dict[str, Any]]:
    return sorted([_event_record(event) for event in list(events or [])], key=lambda item: (int(item.get("offset") or 0), float(item.get("created_at") or 0.0)))


def _event_record(event: Any) -> dict[str, Any]:
    return event.to_dict() if hasattr(event, "to_dict") else record(event)


def _append_or_replace_public_item(items: list[dict[str, Any]], index_by_key: dict[str, int], item: dict[str, Any]) -> None:
    payload = record(item)
    if not payload:
        return
    key = _public_timeline_item_key(payload)
    if not key:
        return
    if key in index_by_key:
        items[index_by_key[key]] = {**items[index_by_key[key]], **payload}
        return
    index_by_key[key] = len(items)
    items.append(payload)


def _projection_items_from_envelope(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    if record(envelope.get("terminal")).get("visible") is False:
        return []
    return [record(item) for item in list(envelope.get("items") or []) if record(item)]


def _public_timeline_item_key(item: dict[str, Any]) -> str:
    for key in ("item_id", "id"):
        value = text(item.get(key))
        if value:
            return value
    return stable_id("timeline", item.get("kind"), item.get("title"), item.get("text"), item.get("detail"), item.get("public_summary"))


def _trim_public_timeline_items(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if not limit:
        return items
    return items[-max(1, int(limit)) :]


def _first_evidence_summary(unit: dict[str, Any]) -> str:
    for item in list(unit.get("evidence") or []):
        if isinstance(item, dict):
            visible = public_text(item.get("summary") or item.get("detail") or item.get("text"), limit=220)
            if visible:
                return visible
    return ""


def _is_tool_like(unit: dict[str, Any]) -> bool:
    kind = text(unit.get("kind")).lower()
    return kind in {"tool", "work_action", "observation"} or bool(text(unit.get("tool_name")))


def _trace_refs(value: dict[str, Any]) -> list[str]:
    refs = value.get("trace_refs") or value.get("technical_trace_refs") or []
    return [text(item) for item in refs if text(item)] if isinstance(refs, list) else []


def _debug_trace_ref(event: dict[str, Any], *, anchor: dict[str, Any]) -> str:
    return text(event.get("event_id")) or stable_id("event", event.get("run_id"), event.get("event_type"), anchor)


def _turn_id_from_monitor(run_id: str, monitor: dict[str, Any] | None) -> str:
    monitor_payload = record(monitor)
    if text(monitor_payload.get("turn_id")):
        return text(monitor_payload.get("turn_id"))
    return ""


def _turn_id_from_run_id(value: str) -> str:
    parts = text(value).split(":")
    if len(parts) >= 3 and parts[0] in {"turnrun", "taskrun"} and parts[1] == "turn":
        return f"turn:{parts[2]}"
    return ""


def _task_run_id(value: Any) -> str:
    candidate = text(value)
    return candidate if candidate.startswith("taskrun:") else ""


def _turn_run_id(value: Any) -> str:
    candidate = text(value)
    return candidate if candidate.startswith("turnrun:") else ""


def _turn_id(value: Any) -> str:
    candidate = text(value)
    return candidate if candidate.startswith("turn:") else ""
