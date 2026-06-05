from __future__ import annotations

from typing import Any

from harness.runtime.public_timeline_stream import project_public_timeline_delta


PUBLIC_PROJECTION_AUTHORITY = "runtime_monitor.public_event_projection.v1"


def project_runtime_monitor_event_public_delta(
    runtime_event: dict[str, Any],
    *,
    runtime_host: Any | None = None,
    monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = _hydrate_external_event_payload(dict(runtime_event or {}), runtime_host=runtime_host)
    event_type = _text(event.get("event_type"))
    public_event_type = _public_event_type(event_type, event)
    if not public_event_type:
        return {}

    event = _hydrate_event_for_projection(event, runtime_host=runtime_host)
    anchor = _public_anchor(event, monitor=monitor)
    debug_trace_ref = _debug_trace_ref(event, anchor=anchor)
    if not _text(anchor.get("anchor_turn_id")):
        return {
            "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
            "public_event_type": public_event_type,
            "public_projection_skip_reason": "missing_public_anchor",
            "debug_trace_ref": debug_trace_ref,
        }

    data = _public_event_data(public_event_type=public_event_type, event=event, monitor=monitor)
    delta = project_public_timeline_delta(public_event_type, data)
    if not delta:
        return {
            "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
            "public_event_type": public_event_type,
            "public_anchor": anchor,
            "public_projection_skip_reason": "empty_public_delta",
            "debug_trace_ref": debug_trace_ref,
        }
    return {
        "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
        "public_event_type": public_event_type,
        "public_timeline_delta": delta,
        "public_anchor": anchor,
        "debug_trace_ref": debug_trace_ref,
    }


def _public_event_type(event_type: str, event: dict[str, Any]) -> str:
    if event_type in {"model_action_request_received", "model_action_admission_checked"}:
        return "model_action_admission"
    if event_type == "step_summary_recorded":
        return "runtime_step_summary"
    if event_type in {"turn_tool_observation_recorded", "task_tool_observation_recorded"}:
        return event_type
    if event_type == "agent_todo_initialized":
        return "task_run_lifecycle_event"
    if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
        return "runtime_status"
    if event_type in {"task_run_lifecycle_waiting_executor", "task_run_executor_scheduled"}:
        return "runtime_status"
    if event_type in {"active_task_steer_recorded", "active_task_steer_accepted"}:
        return "active_task_steer_accepted"
    if event_type in {"task_run_lifecycle_finished", "agent_turn_terminal"}:
        return _terminal_public_event_type(event)
    if event_type in {"loop_error", "agent_turn_failed"}:
        return "error"
    return ""


def _public_event_data(
    *,
    public_event_type: str,
    event: dict[str, Any],
    monitor: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = _record(event.get("payload"))
    anchor = _public_anchor(event, monitor=monitor)
    base = {
        "event": event,
        "runtime_task_run_id": anchor.get("task_run_id") or _text(event.get("run_id")),
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
            "public_action_state": payload.get("public_action_state"),
        }
    if public_event_type == "runtime_status":
        return {**base, **_runtime_status_data(event)}
    if public_event_type in {"done", "error", "stopped"}:
        return {**base, **_terminal_data(event, public_event_type=public_event_type)}
    if public_event_type == "active_task_steer_accepted":
        return {
            **base,
            "summary": _active_task_steer_summary(payload),
        }
    return base


def _hydrate_event_for_projection(event: dict[str, Any], *, runtime_host: Any | None) -> dict[str, Any]:
    event = _hydrate_external_event_payload(event, runtime_host=runtime_host)
    if _text(event.get("event_type")) != "model_action_admission_checked":
        return event
    payload = _record(event.get("payload"))
    if _record(payload.get("model_action_request")):
        return event
    action = _find_model_action_request(event, runtime_host=runtime_host)
    if not action:
        return event
    return {
        **event,
        "payload": {
            **payload,
            "model_action_request": action,
        },
    }


def _find_model_action_request(event: dict[str, Any], *, runtime_host: Any | None) -> dict[str, Any]:
    action_ref = _text(_record(event.get("refs")).get("action_request_ref"))
    if not action_ref or runtime_host is None:
        return {}
    event_log = getattr(runtime_host, "event_log", None)
    if event_log is None or not hasattr(event_log, "list_recent_events"):
        return {}
    try:
        events = event_log.list_recent_events(_text(event.get("run_id")), limit=80)
    except Exception:
        return {}
    for candidate in reversed(list(events or [])):
        payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate or {})
        payload = _hydrate_external_event_payload(payload, runtime_host=runtime_host)
        if _text(payload.get("event_type")) != "model_action_request_received":
            continue
        refs = _record(payload.get("refs"))
        action = _record(_record(payload.get("payload")).get("model_action_request"))
        request_id = _text(action.get("request_id"))
        if action_ref in {_text(refs.get("action_request_ref")), request_id}:
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
    payload = _record(event.get("payload"))
    refs = _record(event.get("refs"))
    run_id = _text(event.get("run_id") or event.get("task_run_id"))
    task_run_id = _task_run_id(
        event.get("task_run_id")
        or refs.get("task_run_ref")
        or payload.get("task_run_id")
        or run_id
    )
    turn_run_id = _turn_run_id(
        refs.get("turn_run_ref")
        or payload.get("turn_run_id")
        or run_id
    )
    action = _record(payload.get("model_action_request"))
    task_run = _record(payload.get("task_run"))
    diagnostics = _record(payload.get("diagnostics"))
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
    return _compact(
        {
            "run_id": run_id,
            "task_run_id": task_run_id,
            "turn_run_id": turn_run_id,
            "anchor_turn_id": anchor_turn_id,
            "anchor_role": "assistant",
        }
    )


def _terminal_public_event_type(event: dict[str, Any]) -> str:
    payload = _record(event.get("payload"))
    task_run = _record(payload.get("task_run"))
    status = _text(payload.get("status") or task_run.get("status")).lower()
    terminal_reason = _text(payload.get("terminal_reason") or task_run.get("terminal_reason")).lower()
    if terminal_reason in {"user_aborted", "stopped", "cancelled", "canceled"}:
        return "stopped"
    if status in {"completed", "success", "succeeded", "done"}:
        return "done"
    if status in {"aborted", "cancelled", "canceled"}:
        return "stopped"
    if status in {"failed", "error", "blocked"} or terminal_reason:
        return "error"
    return "done"


def _terminal_data(event: dict[str, Any], *, public_event_type: str) -> dict[str, Any]:
    payload = _record(event.get("payload"))
    task_run = _record(payload.get("task_run"))
    terminal_reason = _text(payload.get("terminal_reason") or task_run.get("terminal_reason") or payload.get("status") or task_run.get("status"))
    summary = (
        payload.get("receipt_summary")
        or payload.get("summary")
        or payload.get("final_answer")
        or _record(task_run.get("diagnostics")).get("final_answer")
        or terminal_reason
    )
    if public_event_type == "error":
        return {
            "error": payload.get("error") or payload.get("message") or summary or "处理失败",
            "terminal_reason": terminal_reason,
        }
    if public_event_type == "stopped":
        return {
            "reason": payload.get("reason") or summary or terminal_reason or "当前处理已停止",
            "terminal_reason": terminal_reason,
        }
    return {
        "terminal_reason": terminal_reason,
        "answer_channel": payload.get("answer_channel"),
        "completion_state": payload.get("completion_state"),
        "receipt_summary": summary,
        "summary": summary,
        "content": payload.get("content") or payload.get("final_answer"),
    }


def _runtime_status_data(event: dict[str, Any]) -> dict[str, Any]:
    event_type = _text(event.get("event_type"))
    payload = _record(event.get("payload"))
    if event_type in {"task_run_lifecycle_waiting_executor", "task_run_executor_scheduled"}:
        return {
            "title": "等待继续",
            "detail": payload.get("summary") or "当前处理已进入等待队列，继续后会接上现有进度。",
            "state": "waiting",
            "phase": "waiting",
        }
    return {
        "title": "开始处理",
        "detail": payload.get("summary") or payload.get("public_progress_note") or "已开始处理当前请求。",
        "state": "running",
    }


def _active_task_steer_summary(payload: dict[str, Any]) -> str:
    steer = _record(payload.get("steer"))
    observation = _record(payload.get("observation"))
    observation_payload = _record(observation.get("payload"))
    structured = _record(observation_payload.get("structured_payload"))
    return _text(
        steer.get("content")
        or structured.get("user_instruction")
        or observation_payload.get("result")
        or payload.get("summary")
    )


def _debug_trace_ref(event: dict[str, Any], *, anchor: dict[str, Any]) -> str:
    return _text(
        anchor.get("task_run_id")
        or anchor.get("turn_run_id")
        or anchor.get("run_id")
        or event.get("event_id")
    )


def _turn_id_from_monitor(run_id: str, monitor: dict[str, Any] | None) -> str:
    if not monitor:
        return ""
    for signal in list(monitor.get("signals") or []) + list(monitor.get("primary") or []) + list(monitor.get("attention") or []):
        if not isinstance(signal, dict):
            continue
        if run_id not in {_text(signal.get("task_run_id")), _text(signal.get("signal_id"))}:
            continue
        raw_refs = _record(signal.get("raw_refs"))
        diagnostics = _record(signal.get("diagnostics"))
        turn_id = _turn_id(raw_refs.get("turn_id") or diagnostics.get("turn_id") or diagnostics.get("latest_interaction_turn_id"))
        if turn_id:
            return turn_id
    return ""


def _turn_id_from_run_id(value: str) -> str:
    candidate = _text(value)
    if candidate.startswith("turnrun:"):
        turn_id = candidate.removeprefix("turnrun:")
        return turn_id if turn_id.startswith("turn:") else ""
    if not candidate.startswith("taskrun:turn:"):
        return ""
    parts = candidate.split(":")
    if len(parts) < 5:
        return ""
    for index in range(2, len(parts)):
        if parts[index].isdigit():
            return ":".join(parts[1 : index + 1])
    return ""


def _task_run_id(value: Any) -> str:
    text = _text(value)
    return text if text.startswith("taskrun:") else ""


def _turn_run_id(value: Any) -> str:
    text = _text(value)
    return text if text.startswith("turnrun:") else ""


def _turn_id(value: Any) -> str:
    text = _text(value)
    return text if text.startswith("turn:") else ""


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
