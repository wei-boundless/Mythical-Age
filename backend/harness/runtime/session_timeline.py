from __future__ import annotations

import json
from typing import Any

from runtime.output_stream.public_contract import (
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
    TOOL_CALL_REQUESTED_EVENT,
    TOOL_ITEM_COMPLETED_EVENT,
    TOOL_ITEM_STARTED_EVENT,
    TOOL_PERMISSION_DECIDED_EVENT,
)
from runtime.shared.tool_identity import ensure_tool_call_id, permission_decision_id

from .projection.projector import ProjectionLifecycleState, project_public_projection_event

_TASK_ANCHOR_PUBLIC_EVENTS = {"task_bridge_started", "task_bridge_terminal"}
_TASK_CLOSED_PUBLIC_EVENTS = {"session_output_commit_ack"}
_BODY_ONLY_SURFACE = "body_only"
_LIVE_TIMELINE_SURFACE = "live_timeline"
_CLOSEOUT_SUMMARY_SURFACE = "closeout_summary"
_LOG_ONLY_SURFACE = "log_only"


def build_session_runtime_timeline(
    *,
    session_id: str,
    history: dict[str, Any],
    runtime_host: Any,
    max_timeline_items: int = 24,
) -> dict[str, Any]:
    history_record = dict(history or {})
    history_messages = list(history_record.get("messages") or [])
    stream_attachments = _stream_runtime_attachments(
        runtime_host,
        session_id=session_id,
        history_messages=history_messages,
    )
    task_attachments = [
        _runtime_attachment(runtime_host, task_run, history_messages=history_messages, max_timeline_items=max_timeline_items)
        for task_run in sorted(
            runtime_host.state_index.list_session_task_runs(session_id),
            key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
        )
        if _is_formal_chat_task_run(task_run)
    ]
    turn_attachments = [
        _turn_runtime_attachment(runtime_host, turn_run, history_messages=history_messages, max_timeline_items=max_timeline_items)
        for turn_run in sorted(
            runtime_host.state_index.list_session_turn_runs(session_id),
            key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
        )
    ]
    attachments = sorted(
        [item for item in [*stream_attachments, *task_attachments, *turn_attachments] if item],
        key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0),
    )
    return {
        **history_record,
        "session_id": session_id,
        "runtime_attachments": attachments,
        "authority": "session_runtime_timeline",
    }


def _is_formal_chat_task_run(task_run: Any) -> bool:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    return task_run_id.startswith("taskrun:turn:") or task_id.startswith("task:turn:")


def _stream_runtime_attachments(runtime_host: Any, *, session_id: str, history_messages: list[Any]) -> list[dict[str, Any]]:
    registry = getattr(runtime_host, "run_registry", None)
    list_runs = getattr(registry, "list_session_runs", None)
    if not callable(list_runs):
        return []
    try:
        runs = list(list_runs(session_id))
    except Exception:
        return []
    return [
        attachment
        for attachment in (
            _stream_runtime_attachment(runtime_host, run, history_messages=history_messages)
            for run in sorted(runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0))
        )
        if attachment
    ]


def _stream_runtime_attachment(runtime_host: Any, run: Any, *, history_messages: list[Any]) -> dict[str, Any]:
    event_log_id = str(getattr(run, "event_log_id", "") or "").strip()
    stream_run_id = str(getattr(run, "stream_run_id", "") or "").strip()
    if not stream_run_id or not event_log_id.startswith("chatrun:"):
        return {}
    public_events = _public_event_records_for_run(runtime_host, run)
    if not public_events:
        return {}
    frames = _public_projection_frames_from_public_events(public_events)
    projection_anchor = _projection_anchor_from_public_ledger(
        run,
        public_events=public_events,
        frames=frames,
        history_messages=history_messages,
    )
    anchored_frames = [
        _frame_with_projection_anchor(frame, projection_anchor=projection_anchor)
        for frame in frames
        if isinstance(frame, dict)
    ]
    display = _display_state_for_stream_run(run, public_events=public_events, frames=anchored_frames, projection_anchor=projection_anchor)
    tool_event_count = _tool_event_count(anchored_frames)
    closeout_summary = _closeout_summary(public_events=public_events, frames=anchored_frames)
    return {
        "attachment_id": f"runtime-attachment:{stream_run_id}",
        "run_id": stream_run_id,
        "stream_run_id": stream_run_id,
        "event_log_id": event_log_id,
        "anchor_turn_id": str(projection_anchor.get("anchor_turn_id") or ""),
        "anchor_message_id": str(projection_anchor.get("anchor_message_id") or ""),
        "anchor_role": "assistant",
        "turn_run_id": str(projection_anchor.get("turn_run_id") or ""),
        "task_run_id": str(projection_anchor.get("task_run_id") or ""),
        "task_id": "",
        "status": str(getattr(run, "status", "") or ""),
        "display_state": display["display_state"],
        "main_chat_surface": display["main_chat_surface"],
        "latest_event_type": _latest_public_event_type(public_events),
        "event_count": len(public_events),
        "tool_event_count": tool_event_count,
        "closeout_summary": closeout_summary if display["main_chat_surface"] == _CLOSEOUT_SUMMARY_SURFACE else "",
        "log_ref": event_log_id,
        "projection_anchor": projection_anchor,
        "public_projection_frames": anchored_frames,
        "artifact_refs": [],
        "trace_available": True,
        "debug_trace_ref": event_log_id,
        "created_at": float(getattr(run, "created_at", 0.0) or 0.0),
        "updated_at": max(
            float(getattr(run, "updated_at", 0.0) or 0.0),
            max((_float_value(item.get("created_at"), fallback=0.0) for item in public_events), default=0.0),
        ),
        "authority": "session_runtime_timeline.stream_attachment",
    }


def _public_event_records_for_run(runtime_host: Any, run: Any) -> list[dict[str, Any]]:
    replay = getattr(runtime_host, "stream_replay", None)
    reader = getattr(replay, "list_public_event_records", None)
    if callable(reader):
        try:
            return list(reader(run))
        except Exception:
            return []
    events_reader = getattr(getattr(runtime_host, "event_log", None), "list_events", None)
    if not callable(events_reader):
        return []
    records: list[dict[str, Any]] = []
    try:
        events = list(events_reader(str(getattr(run, "event_log_id", "") or "")))
    except Exception:
        return []
    for event in events:
        event_type = str(getattr(event, "event_type", "") or "")
        if event_type != "chat_stream_event":
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        data = dict(payload.get("data") or {})
        records.append(
            {
                "stream_run_id": str(getattr(run, "stream_run_id", "") or ""),
                "event_log_id": str(getattr(run, "event_log_id", "") or ""),
                "event_id": str(getattr(event, "event_id", "") or ""),
                "event_offset": int(getattr(event, "offset", 0) or 0),
                "created_at": float(getattr(event, "created_at", 0.0) or 0.0),
                "public_event_type": str(payload.get("public_event_type") or "").strip(),
                "terminal": bool(payload.get("terminal") is True),
                "data": data,
                "public_projection_frame": dict(data.get("public_projection_frame") or {})
                if isinstance(data.get("public_projection_frame"), dict)
                else {},
            }
        )
    return sorted(records, key=lambda item: int(item.get("event_offset") or 0))


def _public_projection_frames_from_public_events(public_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in public_events:
        frame = dict(event.get("public_projection_frame") or {})
        if not frame:
            data = _dict_record(event.get("data"))
            frame = dict(data.get("public_projection_frame") or {}) if isinstance(data.get("public_projection_frame"), dict) else {}
        frame_id = str(frame.get("frame_id") or frame.get("projection_id") or "").strip()
        if not frame_id or frame_id in seen:
            continue
        seen.add(frame_id)
        frames.append(frame)
    return sorted(frames, key=lambda item: (_int_value(item.get("event_offset"), fallback=0), str(item.get("frame_id") or "")))


def _projection_anchor_from_public_ledger(
    run: Any,
    *,
    public_events: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    history_messages: list[Any],
) -> dict[str, Any]:
    session_id = str(getattr(run, "session_id", "") or "")
    stream_run_id = str(getattr(run, "stream_run_id", "") or "")
    event_log_id = str(getattr(run, "event_log_id", "") or "")
    anchor: dict[str, str] = {
        "session_id": session_id,
        "run_id": stream_run_id,
        "stream_run_id": stream_run_id,
        "event_log_id": event_log_id,
    }
    for frame in frames:
        frame_anchor = _dict_record(frame.get("anchor"))
        _set_first(anchor, "anchor_turn_id", frame_anchor.get("turn_id"))
        _set_first(anchor, "anchor_message_id", frame_anchor.get("message_id"))
        _set_first(anchor, "task_run_id", frame_anchor.get("task_run_id"))
        _set_first(anchor, "turn_run_id", frame_anchor.get("turn_run_id"))
    for event in public_events:
        data = _dict_record(event.get("data"))
        _set_first(anchor, "anchor_turn_id", data.get("turn_id") or data.get("active_turn_id"))
        _set_first(anchor, "anchor_message_id", data.get("message_id") or data.get("message_ref"))
        _set_first(anchor, "task_run_id", data.get("task_run_id") or data.get("runtime_task_run_id"))
        _set_first(anchor, "turn_run_id", data.get("turn_run_id"))
    diagnostics = dict(getattr(run, "diagnostics", {}) or {})
    _set_first(anchor, "anchor_turn_id", diagnostics.get("active_turn_id") or diagnostics.get("expected_active_turn_id"))
    _set_first(anchor, "task_run_id", diagnostics.get("runtime_task_run_id"))
    _set_first(anchor, "turn_run_id", diagnostics.get("runtime_turn_run_id"))
    if not anchor.get("anchor_message_id") and anchor.get("anchor_turn_id"):
        anchor_message = _anchor_assistant_message(anchor_turn_id=anchor["anchor_turn_id"], history_messages=history_messages)
        _set_first(anchor, "anchor_message_id", _history_message_id(anchor_message) if anchor_message else "")
    return {key: value for key, value in anchor.items() if str(value or "").strip()}


def _set_first(target: dict[str, str], key: str, value: Any) -> None:
    if str(target.get(key) or "").strip():
        return
    text = str(value or "").strip()
    if text:
        target[key] = text


def _frame_with_projection_anchor(frame: dict[str, Any], *, projection_anchor: dict[str, Any]) -> dict[str, Any]:
    anchor = _dict_record(frame.get("anchor"))
    next_anchor = {
        **anchor,
        "session_id": str(anchor.get("session_id") or projection_anchor.get("session_id") or ""),
        "turn_id": str(anchor.get("turn_id") or projection_anchor.get("anchor_turn_id") or ""),
        "message_id": str(anchor.get("message_id") or projection_anchor.get("anchor_message_id") or ""),
        "task_run_id": str(anchor.get("task_run_id") or projection_anchor.get("task_run_id") or ""),
        "stream_run_id": str(anchor.get("stream_run_id") or projection_anchor.get("stream_run_id") or ""),
        "run_id": str(anchor.get("run_id") or projection_anchor.get("run_id") or ""),
        "turn_run_id": str(anchor.get("turn_run_id") or projection_anchor.get("turn_run_id") or ""),
    }
    return {
        **frame,
        "anchor": {key: value for key, value in next_anchor.items() if str(value or "").strip()},
    }


def _display_state_for_stream_run(
    run: Any,
    *,
    public_events: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    projection_anchor: dict[str, Any],
) -> dict[str, str]:
    has_task = bool(projection_anchor.get("task_run_id")) or any(
        str(event.get("public_event_type") or "") in _TASK_ANCHOR_PUBLIC_EVENTS
        for event in public_events
    )
    if not has_task:
        return {"display_state": "normal_turn", "main_chat_surface": _BODY_ONLY_SURFACE}
    closed = any(
        str(event.get("public_event_type") or "") in _TASK_CLOSED_PUBLIC_EVENTS
        for event in public_events
    ) or any(
        str(frame.get("op") or "") == "commit_ack"
        for frame in frames
    )
    if closed:
        return {"display_state": "task_closed", "main_chat_surface": _CLOSEOUT_SUMMARY_SURFACE}
    return {"display_state": "task_live", "main_chat_surface": _LIVE_TIMELINE_SURFACE}


def _tool_event_count(frames: list[dict[str, Any]]) -> int:
    tool_call_ids = {
        str(frame.get("tool_call_id") or "").strip()
        for frame in frames
        if str(frame.get("event_family") or "") == "tool_control" and str(frame.get("tool_call_id") or "").strip()
    }
    if tool_call_ids:
        return len(tool_call_ids)
    return sum(1 for frame in frames if str(frame.get("event_family") or "") == "tool_control")


def _closeout_summary(*, public_events: list[dict[str, Any]], frames: list[dict[str, Any]]) -> str:
    for frame in reversed(frames):
        if str(frame.get("slot") or "") == "body" and str(frame.get("op") or "") == "body_finalize":
            text = str(frame.get("text") or "").strip()
            if text:
                return text
    for event in reversed(public_events):
        public_event_type = str(event.get("public_event_type") or "").strip()
        data = _dict_record(event.get("data"))
        if public_event_type in {"session_output_commit_ack", "session_output_commit_failed", "session_output_commit_skipped"}:
            summary = str(data.get("summary") or data.get("reason") or data.get("error") or "").strip()
            if summary:
                return summary
        if public_event_type == "turn_completed":
            summary = str(data.get("error_summary") or data.get("stopped_reason") or data.get("terminal_reason") or data.get("status") or "").strip()
            if summary:
                return f"任务已结束：{summary}"
        if public_event_type == "task_bridge_terminal":
            summary = str(data.get("terminal_reason") or data.get("completion_state") or data.get("status") or "").strip()
            if summary:
                return f"任务已收口：{summary}"
    return "任务已结束，但没有可提交的正文。"


def _latest_public_event_type(public_events: list[dict[str, Any]]) -> str:
    latest = public_events[-1] if public_events else {}
    return str(latest.get("public_event_type") or "")


def _runtime_attachment(runtime_host: Any, task_run: Any, *, history_messages: list[Any], max_timeline_items: int) -> dict[str, Any]:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    if not task_run_id:
        return {}
    session_id = str(getattr(task_run, "session_id", "") or "")
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    events = [item.to_dict() for item in _recent_events(runtime_host, task_run_id, limit=max_timeline_items * 8)]
    session_output_commit = _session_output_commit_state(events, diagnostics=diagnostics, task_run=task_run)
    artifact_refs = list(diagnostics.get("artifact_refs") or [])
    anchor_turn_id = _anchor_turn_id(task_run_id=task_run_id, diagnostics=diagnostics, events=events)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    anchor_message_id = _history_message_id(anchor_message) if anchor_message else ""
    projection_anchor = _projection_anchor(
        session_id=session_id,
        run_id=task_run_id,
        anchor_turn_id=anchor_turn_id,
        anchor_message_id=anchor_message_id,
        task_run_id=task_run_id,
    )
    public_projection_frames = _task_public_projection_frames(
        events,
        task_run=task_run,
        projection_anchor=projection_anchor,
        max_timeline_items=max_timeline_items,
    )
    display = _display_state_for_task_run(
        task_run,
        session_output_commit=session_output_commit,
        public_projection_frames=public_projection_frames,
    )
    closeout_summary = _task_closeout_summary(
        task_run,
        session_output_commit=session_output_commit,
        public_projection_frames=public_projection_frames,
    )
    return {
        "attachment_id": f"runtime-attachment:{task_run_id}",
        "run_id": task_run_id,
        "anchor_turn_id": anchor_turn_id,
        "anchor_message_id": anchor_message_id,
        "anchor_role": "assistant",
        "task_run_id": task_run_id,
        "task_id": str(getattr(task_run, "task_id", "") or ""),
        "status": str(getattr(task_run, "status", "") or ""),
        "latest_event_type": _latest_event_type(events),
        "event_count": _event_count(runtime_host, task_run_id, fallback=len(events)),
        **({"session_output_commit": session_output_commit} if session_output_commit else {}),
        "display_state": display["display_state"],
        "main_chat_surface": display["main_chat_surface"],
        "projection_anchor": projection_anchor,
        "public_projection_frames": public_projection_frames,
        "artifact_refs": artifact_refs,
        "tool_event_count": _tool_event_count(public_projection_frames),
        "closeout_summary": closeout_summary if display["main_chat_surface"] == _CLOSEOUT_SUMMARY_SURFACE else "",
        "trace_available": True,
        "debug_trace_ref": task_run_id,
        "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
        "authority": "session_runtime_timeline.task_attachment",
    }


def _task_public_projection_frames(
    events: list[dict[str, Any]],
    *,
    task_run: Any,
    projection_anchor: dict[str, Any],
    max_timeline_items: int,
) -> list[dict[str, Any]]:
    lifecycle_state = ProjectionLifecycleState()
    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    session_id = str(getattr(task_run, "session_id", "") or projection_anchor.get("session_id") or "")
    public_anchor = _projection_public_anchor(projection_anchor)
    for event in sorted(list(events or []), key=lambda item: _int_value(item.get("offset"), fallback=0)):
        offset = _int_value(event.get("offset"), fallback=0)
        for public_event_type, data in _task_public_projection_inputs(event, task_run=task_run):
            projection = project_public_projection_event(
                public_event_type,
                data,
                session_id=session_id,
                sequence=offset,
                public_anchor=public_anchor,
                lifecycle_state=lifecycle_state,
            )
            frame = dict(projection.get("public_projection_frame") or {})
            frame_id = str(frame.get("frame_id") or frame.get("projection_id") or "").strip()
            if not frame_id or frame_id in seen:
                continue
            seen.add(frame_id)
            frames.append(_frame_with_projection_anchor(frame, projection_anchor=projection_anchor))
    max_frames = max(24, int(max_timeline_items or 24) * 8)
    return sorted(frames[-max_frames:], key=lambda item: (_int_value(item.get("event_offset"), fallback=0), str(item.get("frame_id") or "")))


def _task_public_projection_inputs(event: dict[str, Any], *, task_run: Any) -> list[tuple[str, dict[str, Any]]]:
    event_type = str(event.get("event_type") or "").strip()
    payload = _dict_record(event.get("payload"))
    base = _task_public_base_data(event, task_run=task_run)
    if event_type == "step_summary_recorded":
        return [("runtime_step_summary", {**payload, **base})]
    if event_type == "model_action_request_received":
        return [
            (TOOL_CALL_REQUESTED_EVENT, {**base, **request})
            for request in _tool_request_projection_data(payload.get("model_action_request"))
        ]
    if event_type == "model_action_admission_checked":
        return [
            (TOOL_PERMISSION_DECIDED_EVENT, {**base, **decision})
            for decision in _tool_permission_projection_data(payload)
        ]
    if event_type == TOOL_ITEM_STARTED_EVENT:
        return [(TOOL_ITEM_STARTED_EVENT, {**payload, **base})]
    if event_type in {"task_tool_observation_recorded", "approved_task_tool_observation_recorded"}:
        completed = _tool_completed_projection_data(payload)
        return [(TOOL_ITEM_COMPLETED_EVENT, {**base, **completed})] if completed else []
    if event_type in {SESSION_OUTPUT_COMMIT_ACK_EVENT, SESSION_OUTPUT_COMMIT_FAILED_EVENT, SESSION_OUTPUT_COMMIT_SKIPPED_EVENT}:
        return [(event_type, {**payload, **base})]
    return []


def _task_public_base_data(event: dict[str, Any], *, task_run: Any) -> dict[str, Any]:
    payload = _dict_record(event.get("payload"))
    refs = _dict_record(event.get("refs"))
    task_run_id = str(payload.get("task_run_id") or refs.get("task_run_ref") or getattr(task_run, "task_run_id", "") or "")
    diagnostics = _dict_record(getattr(task_run, "diagnostics", {}) or {})
    return {
        "runtime_event_id": str(event.get("event_id") or ""),
        "source_task_event_id": str(event.get("event_id") or ""),
        "source_task_event_offset": _int_value(event.get("offset"), fallback=0),
        "created_at": _float_value(event.get("created_at"), fallback=0.0),
        "task_run_id": task_run_id,
        "turn_id": str(payload.get("turn_id") or diagnostics.get("turn_id") or ""),
        "debug_trace_ref": task_run_id,
        "event": event,
    }


def _projection_public_anchor(projection_anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "session_id": projection_anchor.get("session_id"),
            "turn_id": projection_anchor.get("anchor_turn_id"),
            "anchor_turn_id": projection_anchor.get("anchor_turn_id"),
            "message_id": projection_anchor.get("anchor_message_id"),
            "anchor_message_id": projection_anchor.get("anchor_message_id"),
            "task_run_id": projection_anchor.get("task_run_id"),
            "run_id": projection_anchor.get("run_id"),
            "turn_run_id": projection_anchor.get("turn_run_id"),
        }.items()
        if str(value or "").strip()
    }


def _tool_request_projection_data(action_request: Any) -> list[dict[str, Any]]:
    action = _dict_record(action_request)
    if str(action.get("action_type") or "").strip() != "tool_call":
        return []
    request_id = str(action.get("request_id") or "").strip()
    calls = _action_tool_calls(action)
    result: list[dict[str, Any]] = []
    for index, raw_call in enumerate(calls):
        tool_call = ensure_tool_call_id(raw_call, request_id=request_id, ordinal=index)
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        if not tool_name:
            continue
        tool_args = _dict_record(tool_call.get("args") or tool_call.get("tool_args"))
        result.append(
            {
                "request_id": request_id,
                "tool_call_id": str(tool_call.get("id") or ""),
                "tool_name": tool_name,
                "arguments_preview": _compact_json(tool_args),
                "target": _tool_target_from_args(tool_args),
                "state": "running",
            }
        )
    return result


def _tool_permission_projection_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    admission = _dict_record(payload.get("admission"))
    if str(admission.get("decision") or "").strip() not in {"allow", "allowed", "auto_allow"}:
        return []
    result: list[dict[str, Any]] = []
    for request in _tool_request_projection_data(payload.get("model_action_request")):
        tool_call_id = str(request.get("tool_call_id") or "").strip()
        result.append(
            {
                **request,
                "permission_decision": "allow",
                "decision": "allow",
                "permission_decision_id": permission_decision_id(admission, tool_call_id=tool_call_id),
                "state": "done",
            }
        )
    return result


def _tool_completed_projection_data(payload: dict[str, Any]) -> dict[str, Any]:
    observation = _dict_record(payload.get("observation"))
    if not observation:
        return {}
    observation_payload = _dict_record(observation.get("payload"))
    structured_payload = _dict_record(observation_payload.get("structured_payload"))
    tool_result = _dict_record(structured_payload.get("tool_result"))
    tool_call_id = str(
        observation.get("tool_call_id")
        or observation_payload.get("tool_call_id")
        or tool_result.get("tool_call_id")
        or ""
    ).strip()
    if not tool_call_id:
        return {}
    tool_name = str(
        observation.get("tool_name")
        or observation_payload.get("tool_name")
        or tool_result.get("tool_name")
        or ""
    ).strip()
    status = str(tool_result.get("status") or observation_payload.get("status") or observation.get("status") or "").strip().lower()
    error = str(observation.get("error") or observation_payload.get("error") or tool_result.get("error") or "").strip()
    return {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "state": "failed" if error or status in {"error", "failed", "denied", "canceled"} else "done",
        "observation": _observation_summary(observation),
        "error": error,
        "summary": _observation_summary(observation),
    }


def _action_tool_calls(action: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = action.get("tool_calls")
    calls = [dict(item) for item in list(raw_calls or []) if isinstance(item, dict)]
    if calls:
        return calls
    tool_call = _dict_record(action.get("tool_call"))
    return [tool_call] if tool_call else []


def _tool_target_from_args(args: dict[str, Any]) -> str:
    for key in ("path", "target", "query", "pattern", "url", "command"):
        value = str(args.get(key) or "").strip()
        if value:
            return value[:180]
    return ""


def _compact_json(value: Any) -> str:
    if value in ({}, [], "", None):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))[:360]
    except TypeError:
        return str(value)[:360]


def _observation_summary(observation: dict[str, Any]) -> str:
    payload = _dict_record(observation.get("payload"))
    structured_payload = _dict_record(payload.get("structured_payload"))
    tool_result = _dict_record(structured_payload.get("tool_result"))
    for value in (
        observation.get("summary"),
        observation.get("result"),
        payload.get("summary"),
        payload.get("result"),
        tool_result.get("preview"),
        tool_result.get("output"),
        tool_result.get("text"),
        observation.get("error"),
        payload.get("error"),
        tool_result.get("error"),
    ):
        text = str(value or "").strip()
        if text:
            return text[:500]
    return ""


def _display_state_for_task_run(
    task_run: Any,
    *,
    session_output_commit: dict[str, Any],
    public_projection_frames: list[dict[str, Any]],
) -> dict[str, str]:
    if str(session_output_commit.get("state") or "").strip() == "committed":
        return {"display_state": "task_closed", "main_chat_surface": _CLOSEOUT_SUMMARY_SURFACE}
    if public_projection_frames:
        return {"display_state": "task_live", "main_chat_surface": _LIVE_TIMELINE_SURFACE}
    return {"display_state": "log_only", "main_chat_surface": _LOG_ONLY_SURFACE}


def _task_closeout_summary(
    task_run: Any,
    *,
    session_output_commit: dict[str, Any],
    public_projection_frames: list[dict[str, Any]],
) -> str:
    if str(session_output_commit.get("state") or "").strip() != "committed":
        return ""
    diagnostics = _dict_record(getattr(task_run, "diagnostics", {}) or {})
    for value in (
        diagnostics.get("final_answer"),
        diagnostics.get("latest_public_status"),
        session_output_commit.get("reason"),
    ):
        text = str(value or "").strip()
        if text and text != "committed":
            return text
    for frame in reversed(public_projection_frames):
        if str(frame.get("slot") or "") == "body":
            text = str(frame.get("text") or "").strip()
            if text:
                return text
    return "任务已完成。"


def _turn_runtime_attachment(runtime_host: Any, turn_run: Any, *, history_messages: list[Any], max_timeline_items: int) -> dict[str, Any]:
    turn_run_id = str(getattr(turn_run, "turn_run_id", "") or "")
    if not turn_run_id:
        return {}
    session_id = str(getattr(turn_run, "session_id", "") or "")
    events = [item.to_dict() for item in _recent_events(runtime_host, turn_run_id, limit=max_timeline_items * 8)]
    anchor_turn_id = _valid_turn_ref(getattr(turn_run, "turn_id", "")) or _turn_id_from_turn_run_id(turn_run_id)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    anchor_message_id = _history_message_id(anchor_message) if anchor_message else ""
    status = str(getattr(turn_run, "status", "") or "")
    projection_anchor = _projection_anchor(
        session_id=session_id,
        run_id=turn_run_id,
        anchor_turn_id=anchor_turn_id,
        anchor_message_id=anchor_message_id,
        turn_run_id=turn_run_id,
    )
    return {
        "attachment_id": f"runtime-attachment:{turn_run_id}",
        "run_id": turn_run_id,
        "turn_run_id": turn_run_id,
        "anchor_turn_id": anchor_turn_id,
        "anchor_message_id": anchor_message_id,
        "anchor_role": "assistant",
        "task_run_id": "",
        "task_id": "",
        "status": status,
        "latest_event_type": _latest_event_type(events),
        "event_count": _event_count(runtime_host, turn_run_id, fallback=len(events)),
        "display_state": "log_only",
        "main_chat_surface": _LOG_ONLY_SURFACE,
        "projection_anchor": projection_anchor,
        "public_projection_frames": [],
        "artifact_refs": [],
        "trace_available": True,
        "debug_trace_ref": turn_run_id,
        "created_at": float(getattr(turn_run, "created_at", 0.0) or 0.0),
        "updated_at": max(_latest_now(events, turn_run), float(getattr(turn_run, "updated_at", 0.0) or 0.0)),
        "authority": "session_runtime_timeline.turn_trace_attachment",
    }


def _dict_record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _projection_anchor(
    *,
    session_id: str,
    run_id: str,
    anchor_turn_id: str,
    anchor_message_id: str,
    task_run_id: str = "",
    turn_run_id: str = "",
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "session_id": str(session_id or ""),
            "anchor_turn_id": str(anchor_turn_id or ""),
            "anchor_message_id": str(anchor_message_id or ""),
            "run_id": str(run_id or ""),
            "task_run_id": str(task_run_id or ""),
            "turn_run_id": str(turn_run_id or ""),
        }.items()
        if value
    }


def _session_output_commit_state(events: list[dict[str, Any]], *, diagnostics: dict[str, Any], task_run: Any) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for event in list(events or []):
        payload = _dict_record(event)
        event_type = str(payload.get("event_type") or "").strip()
        if event_type not in {
            "session_output_commit_checked",
            "session_output_commit_ack",
            "session_output_commit_failed",
            "session_output_commit_skipped",
        }:
            continue
        event_payload = _dict_record(payload.get("payload"))
        state = str(event_payload.get("state") or event_payload.get("status") or "").strip()
        if event_type == "session_output_commit_checked" and not state:
            state = "checked"
        elif event_type == "session_output_commit_ack":
            state = "committed"
        elif event_type == "session_output_commit_failed":
            state = "failed"
        elif event_type == "session_output_commit_skipped":
            state = "skipped"
        latest = {
            "authority": "session_runtime_timeline.session_output_commit",
            "state": state,
            "session_id": str(event_payload.get("session_id") or getattr(task_run, "session_id", "") or ""),
            "turn_id": str(event_payload.get("turn_id") or diagnostics.get("turn_id") or ""),
            "task_run_id": str(event_payload.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
            "task_id": str(event_payload.get("task_id") or getattr(task_run, "task_id", "") or ""),
            "anchor_message_id": str(event_payload.get("anchor_message_id") or ""),
            "content_sha256": str(event_payload.get("content_sha256") or ""),
            "reason": str(event_payload.get("reason") or ""),
            "commit_event_offset": _int_value(payload.get("offset"), fallback=-1),
            "checked_event_offset": _int_value(event_payload.get("checked_event_offset"), fallback=-1),
            "created_at": _float_value(payload.get("created_at"), fallback=0.0),
        }
    if latest:
        return {key: value for key, value in latest.items() if value not in ("", None)}
    diagnostic_commit = _dict_record(diagnostics.get("output_commit"))
    state = str(diagnostic_commit.get("state") or diagnostic_commit.get("status") or diagnostics.get("output_commit_status") or "").strip()
    if not state:
        return {}
    return {
        "authority": "session_runtime_timeline.session_output_commit",
        "state": state,
        "session_id": str(diagnostic_commit.get("session_id") or getattr(task_run, "session_id", "") or ""),
        "turn_id": str(diagnostic_commit.get("turn_id") or diagnostics.get("turn_id") or ""),
        "task_run_id": str(diagnostic_commit.get("task_run_id") or getattr(task_run, "task_run_id", "") or ""),
        "task_id": str(diagnostic_commit.get("task_id") or getattr(task_run, "task_id", "") or ""),
        "anchor_message_id": str(diagnostic_commit.get("anchor_message_id") or ""),
        "content_sha256": str(diagnostic_commit.get("content_sha256") or ""),
        "reason": str(diagnostic_commit.get("reason") or ""),
        "commit_event_offset": _int_value(diagnostic_commit.get("event_offset"), fallback=-1),
    }


def _int_value(value: Any, *, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float_value(value: Any, *, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _recent_events(runtime_host: Any, task_run_id: str, *, limit: int) -> list[Any]:
    window_reader = getattr(runtime_host.event_log, "list_event_window", None)
    if callable(window_reader):
        try:
            return list(window_reader(task_run_id, limit=max(1, int(limit or 160)), include_payloads=True))
        except TypeError:
            try:
                return list(window_reader(task_run_id, limit=max(1, int(limit or 160))))
            except Exception:
                pass
        except Exception:
            pass
    reader = getattr(runtime_host.event_log, "list_recent_events", None)
    if callable(reader):
        try:
            return list(reader(task_run_id, limit=max(1, int(limit or 160))))
        except TypeError:
            return list(reader(task_run_id))
        except Exception:
            return []
    all_events_reader = getattr(runtime_host.event_log, "list_events", None)
    if callable(all_events_reader):
        try:
            return list(all_events_reader(task_run_id))[-max(1, int(limit or 160)) :]
        except Exception:
            return []
    return []


def _event_count(runtime_host: Any, task_run_id: str, *, fallback: int) -> int:
    estimator = getattr(runtime_host.event_log, "estimated_event_count", None)
    if callable(estimator):
        try:
            return int(estimator(task_run_id))
        except Exception:
            return int(fallback)
    counter = getattr(runtime_host.event_log, "event_count", None)
    if callable(counter):
        try:
            return int(counter(task_run_id))
        except Exception:
            return int(fallback)
    return int(fallback)


def _latest_now(events: list[dict[str, Any]], task_run: Any) -> float:
    event_time = max((float(item.get("created_at") or 0.0) for item in events), default=0.0)
    return max(event_time, float(getattr(task_run, "updated_at", 0.0) or 0.0))


def _latest_event_type(events: list[dict[str, Any]]) -> str:
    latest_event = events[-1] if events else {}
    return str(latest_event.get("event_type") or "")


def _anchor_turn_id(*, task_run_id: str, diagnostics: dict[str, Any], events: list[dict[str, Any]]) -> str:
    return (
        _latest_interaction_turn_id(events)
        or _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))
        or _valid_turn_ref(diagnostics.get("turn_id"))
        or _turn_id_from_task_run(task_run_id)
        or ""
    )


def _anchor_assistant_message(*, anchor_turn_id: str, history_messages: list[Any]) -> dict[str, Any]:
    messages = [dict(item) for item in history_messages if isinstance(item, dict)]
    if not messages:
        return {}
    for index, message in enumerate(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        if _message_turn_id(message) == anchor_turn_id:
            return {**message, "__history_index": index}
    return {}


def _history_message_id(message: dict[str, Any]) -> str:
    for key in ("id", "message_id"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    turn_id = _message_turn_id(message)
    if turn_id:
        return f"history-message:{turn_id}:assistant"
    index = message.get("__history_index")
    if isinstance(index, int) and index >= 0:
        return f"history-message:{index}"
    return ""


def _message_turn_id(message: dict[str, Any]) -> str:
    for key in ("turn_id", "turn_ref", "anchor_turn_id"):
        turn_id = _valid_turn_ref(message.get(key))
        if turn_id:
            return turn_id
    return ""


def _latest_interaction_turn_id(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        refs = dict(event.get("refs") or {})
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
            observation = dict(payload.get("observation") or {})
            observation_payload = dict(observation.get("payload") or {})
            structured_payload = dict(observation_payload.get("structured_payload") or {})
            for candidate in (
                refs.get("turn_ref"),
                payload.get("turn_id"),
                dict(payload.get("submission") or {}).get("turn_id"),
                observation.get("request_ref"),
                structured_payload.get("turn_id"),
                steer.get("turn_id"),
            ):
                turn_id = _valid_turn_ref(candidate)
                if turn_id:
                    return turn_id
    return ""


def _valid_turn_ref(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("turn:") else ""


def _turn_id_from_task_run(task_run_id: str) -> str:
    prefix = "taskrun:turn:"
    if not task_run_id.startswith(prefix):
        return ""
    parts = task_run_id.split(":")
    if len(parts) < 5:
        return ""
    for index in range(2, len(parts)):
        if parts[index].isdigit():
            return ":".join(parts[1 : index + 1])
    return ""


def _turn_id_from_turn_run_id(turn_run_id: str) -> str:
    prefix = "turnrun:"
    candidate = str(turn_run_id or "").strip()
    if candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]
    return candidate if candidate.startswith("turn:") else ""
