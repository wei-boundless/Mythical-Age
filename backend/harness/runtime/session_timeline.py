from __future__ import annotations

from typing import Any

from .event_query import list_runtime_events, runtime_event_count
from .session_output_commit_projection import project_session_output_commit_state
from runtime.shared.stream_replay import sanitized_public_projection_frame
from runtime.output_stream.public_contract import (
    SESSION_OUTPUT_COMMIT_ACK_EVENT,
    SESSION_OUTPUT_COMMIT_FAILED_EVENT,
    SESSION_OUTPUT_COMMIT_SKIPPED_EVENT,
)

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
    max_stream_runs: int | None = None,
    max_task_runs: int | None = None,
    max_turn_runs: int | None = None,
    max_projection_frames_per_attachment: int | None = None,
) -> dict[str, Any]:
    history_record = dict(history or {})
    history_messages = list(history_record.get("messages") or [])
    stream_attachments = _stream_runtime_attachments(
        runtime_host,
        session_id=session_id,
        history_messages=history_messages,
        max_stream_runs=max_stream_runs,
        max_projection_frames_per_attachment=max_projection_frames_per_attachment,
    )
    task_runs = sorted(
        runtime_host.state_index.list_session_task_runs(session_id),
        key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
    )
    if max_task_runs is not None:
        task_runs = _tail_limit(task_runs, max_task_runs)
    task_attachments = [
        _runtime_attachment(runtime_host, task_run, history_messages=history_messages, max_timeline_items=max_timeline_items)
        for task_run in task_runs
        if _is_formal_chat_task_run(task_run)
    ]
    turn_runs = sorted(
        runtime_host.state_index.list_session_turn_runs(session_id),
        key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
    )
    if max_turn_runs is not None:
        turn_runs = _tail_limit(turn_runs, max_turn_runs)
    turn_attachments = [
        _turn_runtime_attachment(runtime_host, turn_run, history_messages=history_messages, max_timeline_items=max_timeline_items)
        for turn_run in turn_runs
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


def build_session_runtime_projection(
    *,
    session_id: str,
    history: dict[str, Any],
    runtime_host: Any,
    max_attachments: int = 8,
    max_timeline_items: int = 6,
    max_stream_runs: int = 6,
    max_task_runs: int = 6,
    max_turn_runs: int = 3,
    max_projection_frames_per_attachment: int = 48,
) -> dict[str, Any]:
    """Build the bounded main-chat runtime projection used by session hydration."""
    timeline = build_session_runtime_timeline(
        session_id=session_id,
        history=history,
        runtime_host=runtime_host,
        max_timeline_items=max_timeline_items,
        max_stream_runs=max_stream_runs,
        max_task_runs=max_task_runs,
        max_turn_runs=max_turn_runs,
        max_projection_frames_per_attachment=max_projection_frames_per_attachment,
    )
    attachments = [
        item
        for item in list(timeline.get("runtime_attachments") or [])
        if _runtime_projection_attachment_visible(item)
    ]
    selected = sorted(
        sorted(
            attachments,
            key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0),
            reverse=True,
        )[: max(0, int(max_attachments or 0))],
        key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0),
    )
    return {
        **timeline,
        "runtime_attachments": selected,
        "authority": "session_runtime_projection",
        "projection_mode": "main_chat_lightweight",
        "projection_limits": {
            "max_attachments": max_attachments,
            "max_timeline_items": max_timeline_items,
            "max_stream_runs": max_stream_runs,
            "max_task_runs": max_task_runs,
            "max_turn_runs": max_turn_runs,
            "max_projection_frames_per_attachment": max_projection_frames_per_attachment,
        },
    }


def _is_formal_chat_task_run(task_run: Any) -> bool:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    task_id = str(getattr(task_run, "task_id", "") or "")
    return task_run_id.startswith("taskrun:turn:") or task_id.startswith("task:turn:")


def _stream_runtime_attachments(
    runtime_host: Any,
    *,
    session_id: str,
    history_messages: list[Any],
    max_stream_runs: int | None,
    max_projection_frames_per_attachment: int | None,
) -> list[dict[str, Any]]:
    registry = getattr(runtime_host, "run_registry", None)
    list_runs = getattr(registry, "list_session_runs", None)
    if not callable(list_runs):
        return []
    try:
        runs = sorted(
            list(list_runs(session_id)),
            key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0),
        )
    except Exception:
        return []
    if max_stream_runs is not None:
        runs = _tail_limit(runs, max_stream_runs)
    return [
        attachment
        for attachment in (
            _stream_runtime_attachment(
                runtime_host,
                run,
                history_messages=history_messages,
                max_projection_frames=max_projection_frames_per_attachment,
            )
            for run in runs
        )
        if attachment
    ]


def _stream_runtime_attachment(
    runtime_host: Any,
    run: Any,
    *,
    history_messages: list[Any],
    max_projection_frames: int | None = None,
) -> dict[str, Any]:
    event_log_id = str(getattr(run, "event_log_id", "") or "").strip()
    stream_run_id = str(getattr(run, "stream_run_id", "") or "").strip()
    if not stream_run_id or not event_log_id.startswith("chatrun:"):
        return {}
    public_events = _public_event_records_for_run(runtime_host, run)
    if not public_events:
        return {}
    frames = _projection_frames_from_public_events(public_events)
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
    if max_projection_frames is not None:
        anchored_frames = _bounded_projection_frames(anchored_frames, max_projection_frames)
    display = _display_state_for_stream_run(run, public_events=public_events, frames=anchored_frames, projection_anchor=projection_anchor)
    tool_event_count = _tool_event_count(anchored_frames)
    closeout_summary = _closeout_summary(public_events=public_events, frames=anchored_frames)
    projection_slices = _projection_slices(
        slice_ref=event_log_id or stream_run_id,
        projection_anchor=projection_anchor,
        frames=anchored_frames,
        display_state=display["display_state"],
        main_chat_surface=display["main_chat_surface"],
        closeout_summary=closeout_summary if display["main_chat_surface"] == _CLOSEOUT_SUMMARY_SURFACE else "",
        log_ref=event_log_id,
        tool_event_count=tool_event_count,
    )
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
        "projection_slices": projection_slices,
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


def _runtime_projection_attachment_visible(attachment: dict[str, Any]) -> bool:
    surface = str(attachment.get("main_chat_surface") or "").strip()
    if surface in {_LIVE_TIMELINE_SURFACE, _CLOSEOUT_SUMMARY_SURFACE}:
        return True
    if surface == _BODY_ONLY_SURFACE:
        status = str(attachment.get("status") or "").strip().lower()
        return status in {"running", "waiting", "waiting_executor", "waiting_user", "waiting_approval"}
    return False


def _tail_limit(items: list[Any], limit: int | None) -> list[Any]:
    count = max(0, int(limit or 0))
    if count <= 0:
        return []
    return list(items)[-count:]


def _bounded_projection_frames(frames: list[dict[str, Any]], max_frames: int) -> list[dict[str, Any]]:
    limit = max(0, int(max_frames or 0))
    if not limit or len(frames) <= limit:
        return frames
    return sorted(
        frames[-limit:],
        key=lambda item: (_int_value(item.get("event_offset"), fallback=0), str(item.get("frame_id") or item.get("projection_id") or "")),
    )


def _projection_slices(
    *,
    slice_ref: str,
    projection_anchor: dict[str, Any],
    frames: list[dict[str, Any]],
    display_state: str,
    main_chat_surface: str,
    closeout_summary: str = "",
    log_ref: str = "",
    tool_event_count: int = 0,
) -> list[dict[str, Any]]:
    ordered_frames = sorted(
        [dict(frame) for frame in frames if isinstance(frame, dict)],
        key=lambda item: (_int_value(item.get("event_offset"), fallback=0), str(item.get("frame_id") or item.get("projection_id") or "")),
    )
    if not ordered_frames:
        return []
    offsets = [_int_value(frame.get("event_offset"), fallback=0) for frame in ordered_frames]
    projection_key = {
        key: value
        for key, value in {
            "session_id": projection_anchor.get("session_id"),
            "turn_id": projection_anchor.get("anchor_turn_id"),
            "message_id": projection_anchor.get("anchor_message_id"),
            "stream_run_id": projection_anchor.get("stream_run_id"),
            "run_id": projection_anchor.get("run_id"),
            "task_run_id": projection_anchor.get("task_run_id"),
            "turn_run_id": projection_anchor.get("turn_run_id"),
            "event_log_id": projection_anchor.get("event_log_id"),
        }.items()
        if str(value or "").strip()
    }
    cursor = {
        "min_event_offset": min(offsets),
        "max_event_offset": max(offsets),
        "frame_count": len(ordered_frames),
    }
    event_log_id = str(projection_anchor.get("event_log_id") or "").strip()
    return [
        {
            "slice_id": f"projection-slice:{slice_ref}",
            "schema_version": "chronological_projection",
            "event_log_id": event_log_id,
            "start_offset": cursor["min_event_offset"],
            "end_offset": cursor["max_event_offset"],
            "projection_key": projection_key,
            "cursor": cursor,
            "frames": ordered_frames,
            "display_hint": {
                "lifecycle": _projection_lifecycle_hint(
                    display_state=display_state,
                    main_chat_surface=main_chat_surface,
                    frames=ordered_frames,
                ),
                "main_surface_hint": _projection_main_surface_hint(main_chat_surface),
                "closeout_summary": closeout_summary,
                "log_ref": log_ref,
                "tool_event_count": tool_event_count,
            },
            "authority": "session_runtime_timeline.projection_slice",
        }
    ]


def _projection_lifecycle_hint(
    *,
    display_state: str,
    main_chat_surface: str,
    frames: list[dict[str, Any]],
) -> str:
    if any(str(frame.get("source_event_type") or "") == SESSION_OUTPUT_COMMIT_FAILED_EVENT for frame in frames):
        return "failed"
    if any(str(frame.get("source_event_type") or "") == SESSION_OUTPUT_COMMIT_ACK_EVENT for frame in frames):
        return "committed"
    if any(str(frame.get("source_event_type") or "") in {"error", "stopped"} for frame in frames):
        return "stopped"
    surface = str(main_chat_surface or "").strip()
    if surface == _LOG_ONLY_SURFACE:
        return "log_only"
    if surface == _CLOSEOUT_SUMMARY_SURFACE or str(display_state or "").strip() == "task_closed":
        return "committed"
    return "running"


def _projection_main_surface_hint(main_chat_surface: str) -> str:
    surface = str(main_chat_surface or "").strip()
    if surface == _LIVE_TIMELINE_SURFACE:
        return "live"
    if surface == _CLOSEOUT_SUMMARY_SURFACE:
        return "closeout"
    if surface == _LOG_ONLY_SURFACE:
        return "log_only"
    return "committed"


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
        data_frame = data.get("public_projection_frame")
        if isinstance(data_frame, dict):
            data = {**data, "public_projection_frame": sanitized_public_projection_frame(data_frame)}
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
                "public_projection_frame": sanitized_public_projection_frame(data.get("public_projection_frame"))
                if isinstance(data.get("public_projection_frame"), dict)
                else {},
            }
        )
    return sorted(records, key=lambda item: int(item.get("event_offset") or 0))


def _projection_frames_from_public_events(public_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in public_events:
        frame = dict(event.get("public_projection_frame") or {})
        if not frame:
            data = _dict_record(event.get("data"))
            frame = dict(data.get("public_projection_frame") or {}) if isinstance(data.get("public_projection_frame"), dict) else {}
        frame = sanitized_public_projection_frame(frame)
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
    steer_target_turn_id = _steer_target_turn_id_from_diagnostics(diagnostics)
    diagnostics_turn_id = (
        diagnostics.get("public_anchor_turn_id")
        or _turn_id_from_turn_run_id(str(diagnostics.get("runtime_turn_run_id") or ""))
        or ("" if steer_target_turn_id else diagnostics.get("active_turn_id") or diagnostics.get("expected_active_turn_id"))
    )
    _set_first(anchor, "anchor_turn_id", diagnostics_turn_id)
    _set_first(anchor, "task_run_id", diagnostics.get("runtime_task_run_id"))
    _set_first(anchor, "turn_run_id", diagnostics.get("runtime_turn_run_id"))
    if not anchor.get("anchor_message_id") and anchor.get("anchor_turn_id"):
        anchor_message = _anchor_assistant_message(anchor_turn_id=anchor["anchor_turn_id"], history_messages=history_messages)
        _set_first(anchor, "anchor_message_id", _history_message_id(anchor_message) if anchor_message else "")
    return {key: value for key, value in anchor.items() if str(value or "").strip()}


def _steer_target_turn_id_from_diagnostics(diagnostics: dict[str, Any]) -> str:
    policy = str(diagnostics.get("active_turn_input_policy") or "").strip().lower()
    expected = _valid_turn_ref(diagnostics.get("expected_active_turn_id"))
    return expected if policy == "steer" else ""


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
        if str(frame.get("event_family") or "") == "tool_control"
        and str(frame.get("tool_call_id") or "").strip()
        and str(frame.get("tool_name") or "").strip().lower() != "agent_todo"
    }
    if tool_call_ids:
        return len(tool_call_ids)
    return sum(
        1
        for frame in frames
        if str(frame.get("event_family") or "") == "tool_control"
        and str(frame.get("tool_name") or "").strip().lower() != "agent_todo"
    )


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
    events = [_event_dict(item) for item in list_runtime_events(runtime_host, task_run_id, limit=max_timeline_items * 8)]
    session_output_commit = project_session_output_commit_state(
        events,
        diagnostics=diagnostics,
        task_run=task_run,
        authority="session_runtime_timeline.session_output_commit",
    )
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
    projection_frames: list[dict[str, Any]] = []
    display = _display_state_for_task_run(
        task_run,
        session_output_commit=session_output_commit,
        projection_frames=projection_frames,
    )
    closeout_summary = _task_closeout_summary(
        task_run,
        session_output_commit=session_output_commit,
        projection_frames=projection_frames,
    )
    projection_slices = _projection_slices(
        slice_ref=task_run_id,
        projection_anchor=projection_anchor,
        frames=projection_frames,
        display_state=display["display_state"],
        main_chat_surface=display["main_chat_surface"],
        closeout_summary=closeout_summary if display["main_chat_surface"] == _CLOSEOUT_SUMMARY_SURFACE else "",
        log_ref=task_run_id,
        tool_event_count=_tool_event_count(projection_frames),
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
        "event_count": runtime_event_count(runtime_host, task_run_id, fallback=len(events)),
        **({"session_output_commit": session_output_commit} if session_output_commit else {}),
        "display_state": display["display_state"],
        "main_chat_surface": display["main_chat_surface"],
        "projection_anchor": projection_anchor,
        "projection_slices": projection_slices,
        "artifact_refs": artifact_refs,
        "tool_event_count": _tool_event_count(projection_frames),
        "closeout_summary": closeout_summary if display["main_chat_surface"] == _CLOSEOUT_SUMMARY_SURFACE else "",
        "trace_available": True,
        "debug_trace_ref": task_run_id,
        "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
        "authority": "session_runtime_timeline.task_attachment",
    }


def _display_state_for_task_run(
    task_run: Any,
    *,
    session_output_commit: dict[str, Any],
    projection_frames: list[dict[str, Any]],
) -> dict[str, str]:
    if projection_frames and str(session_output_commit.get("state") or "").strip() == "committed":
        return {"display_state": "task_closed", "main_chat_surface": _CLOSEOUT_SUMMARY_SURFACE}
    if projection_frames:
        return {"display_state": "task_live", "main_chat_surface": _LIVE_TIMELINE_SURFACE}
    return {"display_state": "log_only", "main_chat_surface": _LOG_ONLY_SURFACE}


def _task_closeout_summary(
    task_run: Any,
    *,
    session_output_commit: dict[str, Any],
    projection_frames: list[dict[str, Any]],
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
    for frame in reversed(projection_frames):
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
    diagnostics = _dict_record(getattr(turn_run, "diagnostics", {}) or {})
    events = [_event_dict(item) for item in list_runtime_events(runtime_host, turn_run_id, limit=max_timeline_items * 8)]
    anchor_turn_id = _valid_turn_ref(getattr(turn_run, "turn_id", "")) or _turn_id_from_turn_run_id(turn_run_id)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    anchor_message_id = _history_message_id(anchor_message) if anchor_message else ""
    status = str(getattr(turn_run, "status", "") or "")
    recovery_signal = _turn_recovery_control_signal(turn_run, events=events, diagnostics=diagnostics)
    projection_anchor = _projection_anchor(
        session_id=session_id,
        run_id=turn_run_id,
        anchor_turn_id=anchor_turn_id,
        anchor_message_id=anchor_message_id,
        turn_run_id=turn_run_id,
    )
    projection_frames: list[dict[str, Any]] = []
    display_state = "task_live" if projection_frames else "log_only"
    main_chat_surface = _LIVE_TIMELINE_SURFACE if projection_frames else _LOG_ONLY_SURFACE
    projection_slices = _projection_slices(
        slice_ref=turn_run_id,
        projection_anchor=projection_anchor,
        frames=projection_frames,
        display_state=display_state,
        main_chat_surface=main_chat_surface,
        log_ref=turn_run_id,
        tool_event_count=_tool_event_count(projection_frames),
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
        "event_count": runtime_event_count(runtime_host, turn_run_id, fallback=len(events)),
        "display_state": display_state,
        "main_chat_surface": main_chat_surface,
        "projection_anchor": projection_anchor,
        "projection_slices": projection_slices,
        "artifact_refs": [],
        **({"runtime_control_signal": recovery_signal} if recovery_signal else {}),
        "trace_available": True,
        "debug_trace_ref": turn_run_id,
        "created_at": float(getattr(turn_run, "created_at", 0.0) or 0.0),
        "updated_at": max(_latest_now(events, turn_run), float(getattr(turn_run, "updated_at", 0.0) or 0.0)),
        "authority": "session_runtime_timeline.turn_trace_attachment",
    }


def _turn_recovery_control_signal(turn_run: Any, *, events: list[dict[str, Any]], diagnostics: dict[str, Any]) -> dict[str, Any]:
    diagnostic_signal = _dict_record(diagnostics.get("latest_runtime_control_signal"))
    if str(diagnostic_signal.get("signal_kind") or "") == "agent_closeout_recovery_required":
        return diagnostic_signal
    for event in reversed(list(events or [])):
        payload = _dict_record(event.get("payload"))
        signal = _dict_record(payload.get("runtime_control_signal"))
        if str(signal.get("signal_kind") or "") == "agent_closeout_recovery_required":
            return signal
    return {}


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


def _event_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:
            return {}
    return {}


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
