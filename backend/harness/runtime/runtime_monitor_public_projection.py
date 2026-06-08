from __future__ import annotations

from hashlib import sha1
from typing import Any

from harness.runtime.public_timeline_stream import project_public_timeline_delta
from harness.runtime.public_timeline_projection import public_text
from harness.runtime.session_task_projection import build_single_agent_task_projection_for_event


PUBLIC_PROJECTION_AUTHORITY = "runtime_monitor.public_event_projection.v1"
INTERNAL_TURN_TERMINAL_REASONS = {
    "assistant_message",
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
    event = _hydrate_external_event_payload(dict(runtime_event or {}), runtime_host=runtime_host)
    event_type = _text(event.get("event_type"))
    public_event_type = _public_event_type(event_type, event)
    if not public_event_type:
        return {}

    event = _hydrate_event_for_projection(event, runtime_host=runtime_host, allow_runtime_lookup=allow_runtime_lookup)
    anchor = _public_anchor(event, monitor=monitor)
    debug_trace_ref = _debug_trace_ref(event, anchor=anchor)
    task_projection = build_single_agent_task_projection_for_event(
        runtime_host,
        event,
        monitor=monitor,
    ) if include_task_projection and runtime_host is not None else {}
    if not _text(anchor.get("anchor_turn_id")):
        if task_projection:
            return {
                "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
                "public_event_type": public_event_type,
                "task_projection": task_projection,
                "task_projection_delta": task_projection,
                "public_anchor": anchor,
                "debug_trace_ref": debug_trace_ref,
            }
        return {
            "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
            "public_event_type": public_event_type,
            "public_projection_skip_reason": "missing_public_anchor",
            "debug_trace_ref": debug_trace_ref,
        }

    data = _public_event_data(public_event_type=public_event_type, event=event, monitor=monitor)
    delta = project_public_timeline_delta(public_event_type, data)
    if not delta:
        if task_projection:
            return {
                "public_projection_authority": PUBLIC_PROJECTION_AUTHORITY,
                "public_event_type": public_event_type,
                "task_projection": task_projection,
                "task_projection_delta": task_projection,
                "public_anchor": anchor,
                "public_projection_skip_reason": "empty_public_delta",
                "debug_trace_ref": debug_trace_ref,
            }
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
        **({"task_projection": task_projection, "task_projection_delta": task_projection} if task_projection else {}),
        "public_anchor": anchor,
        "debug_trace_ref": debug_trace_ref,
    }


def project_public_timeline_from_events(
    events: list[Any],
    *,
    runtime_host: Any | None = None,
    monitor: dict[str, Any] | None = None,
    run_id: str = "",
    task_run_id: str = "",
    turn_run_id: str = "",
    status: str = "",
    final_answer: str = "",
    assistant_text: str = "",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rebuild history with the same event projection used by live monitor deltas."""

    normalized = [
        _event_with_projection_defaults(
            _event_record(event),
            run_id=run_id,
            task_run_id=task_run_id,
            turn_run_id=turn_run_id,
        )
        for event in events
    ]
    action_requests = _action_requests_by_ref(normalized)
    items: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for event in _ordered_events(normalized):
        projected_event = _event_with_action_request(event, action_requests)
        projection = project_runtime_monitor_event_public_delta(
            projected_event,
            runtime_host=runtime_host,
            monitor=monitor,
            include_task_projection=False,
            allow_runtime_lookup=False,
        )
        for item in list(projection.get("public_timeline_delta") or []):
            if isinstance(item, dict):
                _append_or_replace_public_item(items, index_by_key, item)

    final_item = _final_answer_timeline_item(
        run_id=task_run_id or run_id or turn_run_id,
        final_answer=final_answer,
        assistant_text=assistant_text,
        status=status,
    )
    if final_item:
        _append_or_replace_public_item(items, index_by_key, final_item)
    items = _settle_completed_model_body_items(items, status=status)
    return _trim_public_timeline_items(items, limit)


def _event_record(event: Any) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        try:
            value = event.to_dict()
        except Exception:
            value = {}
    elif isinstance(event, dict):
        value = event
    else:
        value = {}
    record = dict(value or {})
    payload = record.get("payload")
    refs = record.get("refs")
    record["payload"] = dict(payload) if isinstance(payload, dict) else {}
    record["refs"] = dict(refs) if isinstance(refs, dict) else {}
    return record


def _event_with_projection_defaults(
    event: dict[str, Any],
    *,
    run_id: str,
    task_run_id: str,
    turn_run_id: str,
) -> dict[str, Any]:
    normalized = dict(event or {})
    payload = _record(normalized.get("payload"))
    refs = _record(normalized.get("refs"))
    resolved_run_id = _text(normalized.get("run_id") or normalized.get("task_run_id") or task_run_id or turn_run_id or run_id)
    resolved_task_run_id = _task_run_id(normalized.get("task_run_id") or task_run_id or resolved_run_id)
    resolved_turn_run_id = _turn_run_id(normalized.get("turn_run_id") or turn_run_id or resolved_run_id)
    turn_id = _turn_id(
        refs.get("turn_ref")
        or payload.get("turn_id")
        or _record(payload.get("model_action_request")).get("turn_id")
    ) or _turn_id_from_run_id(resolved_run_id) or _turn_id_from_run_id(resolved_task_run_id) or _turn_id_from_run_id(resolved_turn_run_id)
    if resolved_run_id:
        normalized["run_id"] = resolved_run_id
    if resolved_task_run_id:
        normalized["task_run_id"] = resolved_task_run_id
        refs.setdefault("task_run_ref", resolved_task_run_id)
    if resolved_turn_run_id:
        refs.setdefault("turn_run_ref", resolved_turn_run_id)
    if turn_id:
        refs.setdefault("turn_ref", turn_id)
        payload.setdefault("turn_id", turn_id)
    normalized["payload"] = payload
    normalized["refs"] = refs
    return normalized


def _action_requests_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if _text(event.get("event_type")) != "model_action_request_received":
            continue
        payload = _record(event.get("payload"))
        action = _record(payload.get("model_action_request"))
        if not action:
            continue
        refs = _record(event.get("refs"))
        for key in (
            refs.get("action_request_ref"),
            action.get("request_id"),
            event.get("event_id"),
        ):
            normalized = _text(key)
            if normalized:
                result[normalized] = action
    return result


def _event_with_action_request(event: dict[str, Any], action_requests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if _text(event.get("event_type")) != "model_action_admission_checked":
        return event
    payload = _record(event.get("payload"))
    if _record(payload.get("model_action_request")):
        return event
    refs = _record(event.get("refs"))
    admission = _record(payload.get("admission"))
    for key in (
        refs.get("action_request_ref"),
        payload.get("action_request_ref"),
        admission.get("action_request_ref"),
        admission.get("request_id"),
    ):
        action = action_requests.get(_text(key))
        if action:
            return {
                **event,
                "payload": {
                    **payload,
                    "model_action_request": action,
                },
            }
    return event


def _ordered_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda item: (
            float(item.get("created_at") or 0.0),
            int(item.get("offset") or 0),
            _text(item.get("event_id")),
        ),
    )


def _append_or_replace_public_item(items: list[dict[str, Any]], index_by_key: dict[str, int], item: dict[str, Any]) -> None:
    normalized = _compact(dict(item or {}))
    if not normalized:
        return
    key = _public_timeline_item_key(normalized)
    if not key:
        return
    existing_index = index_by_key.get(key)
    if existing_index is not None:
        items[existing_index] = _merge_public_timeline_item(items[existing_index], normalized)
        return
    index_by_key[key] = len(items)
    items.append(normalized)


def _public_timeline_item_key(item: dict[str, Any]) -> str:
    body_key = _public_timeline_body_key(item)
    if body_key:
        return body_key
    item_id = _text(item.get("item_id"))
    if item_id:
        return item_id
    if _text(item.get("kind")) == "work_action":
        subject = _text(item.get("subject_label") or item.get("public_summary") or item.get("title"))
        action_kind = _text(item.get("action_kind"))
        if subject and action_kind and action_kind != "batch":
            return f"work:{action_kind}:{subject}"
    refs = [_text(ref) for ref in list(item.get("trace_refs") or []) if _text(ref)]
    if refs:
        return f"refs:{','.join(refs)}"
    seed = "|".join(_text(item.get(key)) for key in ("kind", "surface", "title", "detail", "text", "public_summary", "subject_label"))
    if not seed.strip("|"):
        return ""
    return f"semantic:{_stable_digest(seed)}"


def _public_timeline_body_key(item: dict[str, Any]) -> str:
    if not _is_model_body_item(item):
        return ""
    text = public_text(
        item.get("text")
        or item.get("detail")
        or item.get("public_summary")
        or item.get("observation")
        or item.get("implication"),
        limit=1000,
    )
    if not text:
        return ""
    return f"body:{_text(item.get('kind'))}:{_stable_digest(text)}"


def _merge_public_timeline_item(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if _public_item_state_rank(right) >= _public_item_state_rank(left):
        merged = {**left, **right}
    else:
        merged = {**right, **left}
    trace_refs = []
    seen: set[str] = set()
    for ref in [*list(left.get("trace_refs") or []), *list(right.get("trace_refs") or [])]:
        normalized = _text(ref)
        if normalized and normalized not in seen:
            seen.add(normalized)
            trace_refs.append(normalized)
    if trace_refs:
        merged["trace_refs"] = trace_refs
    return _compact(merged)


def _public_item_state_rank(item: dict[str, Any]) -> int:
    state = _text(item.get("state")).lower()
    if state in {"error", "failed", "blocked", "missing"} or _text(item.get("kind")) == "blocked":
        return 4
    if state in {"done", "ready", "passed", "success", "completed"}:
        return 3
    if state in {"running", "working", "partial"} or _text(item.get("stream_state")) == "streaming":
        return 2
    return 1


def _final_answer_timeline_item(
    *,
    run_id: str,
    final_answer: str,
    assistant_text: str,
    status: str,
) -> dict[str, Any]:
    if _text(status).lower() not in {"completed", "success", "succeeded", "done"}:
        return {}
    text = public_text(final_answer, limit=420)
    if not text or _same_public_text(text, assistant_text):
        return {}
    return {
        "item_id": f"final:{_stable_digest(run_id + '|' + text)}",
        "kind": "final_summary",
        "surface": "body",
        "source_authority": "model",
        "text": text,
        "state": "done",
    }


def _trim_public_timeline_items(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if not limit or limit <= 0 or len(items) <= limit:
        return items
    protected = {index for index, item in enumerate(items) if _is_model_body_item(item)}
    if not protected:
        return items[-int(limit):]
    selected = set(protected)
    target_size = max(int(limit), len(protected))
    for index in range(len(items) - 1, -1, -1):
        if len(selected) >= target_size:
            break
        selected.add(index)
    return [item for index, item in enumerate(items) if index in selected]


def _settle_completed_model_body_items(items: list[dict[str, Any]], *, status: str) -> list[dict[str, Any]]:
    if _text(status).lower() not in {"completed", "success", "succeeded", "done"}:
        return items
    settled: list[dict[str, Any]] = []
    for item in list(items or []):
        payload = dict(item or {})
        state = _text(payload.get("state")).lower()
        if _is_model_body_item(payload) and state in {"running", "working", "partial"}:
            payload["state"] = "done"
            if _text(payload.get("stream_state")) == "streaming":
                payload["stream_state"] = "done"
        settled.append(_compact(payload))
    return settled


def _is_model_body_item(item: dict[str, Any]) -> bool:
    surface = _text(item.get("surface"))
    authority = _text(item.get("source_authority"))
    kind = _text(item.get("kind"))
    if surface == "body":
        return authority not in {"runtime", "tool", "system"}
    if surface in {"tool_window", "status"}:
        return False
    return kind in {"assistant_text", "opening_judgment", "task_plan", "tool_result_feedback", "stage_summary", "observation_report", "final_summary"}


def _same_public_text(left: str, right: str) -> bool:
    left_text = public_text(left, limit=1000)
    right_text = public_text(right, limit=1000)
    if not left_text or not right_text:
        return False
    return left_text == right_text or left_text in right_text or right_text in left_text


def _stable_digest(seed: str) -> str:
    return sha1(str(seed or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _public_event_type(event_type: str, event: dict[str, Any]) -> str:
    if event_type == "agent_turn_terminal" and _is_internal_turn_terminal(event):
        return ""
    if event_type == "assistant_text":
        return "assistant_text"
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


def _is_internal_turn_terminal(event: dict[str, Any]) -> bool:
    payload = _record(event.get("payload"))
    terminal_reason = _text(payload.get("terminal_reason")).lower()
    status = _text(payload.get("status")).lower()
    return terminal_reason in INTERNAL_TURN_TERMINAL_REASONS or (
        status in {"aborted", "cancelled", "canceled"} and terminal_reason == "stream_cancelled"
    )


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
    if public_event_type == "assistant_text":
        return {
            **base,
            "content": payload.get("content") or payload.get("text") or payload.get("answer"),
            "answer_channel": payload.get("answer_channel"),
            "answer_source": payload.get("answer_source"),
            "answer_canonical_state": payload.get("answer_canonical_state"),
            "answer_persist_policy": payload.get("answer_persist_policy"),
        }
    if public_event_type in {"done", "error", "stopped"}:
        return {**base, **_terminal_data(event, public_event_type=public_event_type)}
    if public_event_type == "active_task_steer_accepted":
        return {
            **base,
            "summary": _active_task_steer_summary(payload),
        }
    return base


def _hydrate_event_for_projection(event: dict[str, Any], *, runtime_host: Any | None, allow_runtime_lookup: bool = True) -> dict[str, Any]:
    event = _hydrate_external_event_payload(event, runtime_host=runtime_host)
    if _text(event.get("event_type")) != "model_action_admission_checked":
        return event
    payload = _record(event.get("payload"))
    if _record(payload.get("model_action_request")):
        return event
    if not allow_runtime_lookup:
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
