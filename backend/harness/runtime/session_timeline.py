from __future__ import annotations

from typing import Any

from harness.runtime.projection.projector import ProjectionLifecycleState, project_public_projection_event


def build_session_runtime_timeline(
    *,
    session_id: str,
    history: dict[str, Any],
    runtime_host: Any,
    max_timeline_items: int = 24,
) -> dict[str, Any]:
    history_record = dict(history or {})
    history_messages = list(history_record.get("messages") or [])
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
        [item for item in [*task_attachments, *turn_attachments] if item],
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
    public_projection_frames = _public_projection_frames_from_events(
        runtime_host,
        events,
        projection_anchor=projection_anchor,
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
        "projection_anchor": projection_anchor,
        "public_projection_frames": public_projection_frames,
        "artifact_refs": artifact_refs,
        "trace_available": True,
        "debug_trace_ref": task_run_id,
        "created_at": float(getattr(task_run, "created_at", 0.0) or 0.0),
        "updated_at": float(getattr(task_run, "updated_at", 0.0) or 0.0),
        "authority": "session_runtime_timeline.attachment",
    }


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
    public_projection_frames = _public_projection_frames_from_events(
        runtime_host,
        events,
        projection_anchor=projection_anchor,
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
        "projection_anchor": projection_anchor,
        "public_projection_frames": public_projection_frames,
        "artifact_refs": [],
        "trace_available": True,
        "debug_trace_ref": turn_run_id,
        "created_at": float(getattr(turn_run, "created_at", 0.0) or 0.0),
        "updated_at": max(_latest_now(events, turn_run), float(getattr(turn_run, "updated_at", 0.0) or 0.0)),
        "authority": "session_runtime_timeline.turn_attachment",
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


def _public_anchor_for_frame(projection_anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "session_id": projection_anchor.get("session_id"),
            "turn_id": projection_anchor.get("anchor_turn_id"),
            "message_id": projection_anchor.get("anchor_message_id"),
            "run_id": projection_anchor.get("run_id"),
            "task_run_id": projection_anchor.get("task_run_id"),
            "turn_run_id": projection_anchor.get("turn_run_id"),
        }.items()
        if value
    }


def _public_projection_frames_from_events(
    runtime_host: Any,
    events: list[dict[str, Any]],
    *,
    projection_anchor: dict[str, Any],
) -> list[dict[str, Any]]:
    if not events or not projection_anchor.get("anchor_turn_id"):
        return []
    try:
        from api.chat import _project_public_stream_event
    except Exception:
        return []
    session_id = str(projection_anchor.get("session_id") or "")
    public_anchor = _public_anchor_for_frame(projection_anchor)
    lifecycle_state = ProjectionLifecycleState()
    frames: list[dict[str, Any]] = []
    seen_frame_ids: set[str] = set()
    for event_index, event in enumerate(events):
        stream_event = _runtime_event_record_to_stream_event(runtime_host, event)
        event_type = str(stream_event.get("type") or "").strip()
        if not event_type:
            continue
        source_event = _dict_record(stream_event.get("event"))
        source_event_id = str(source_event.get("event_id") or event.get("event_id") or "").strip()
        source_offset = _int_value(source_event.get("offset") or event.get("offset"), fallback=event_index)
        try:
            public_events = list(_project_public_stream_event(event_type, stream_event))
        except Exception:
            public_events = []
        for public_index, (public_event_type, data) in enumerate(public_events):
            public_data = dict(data or {})
            _apply_projection_anchor_to_public_data(
                public_data,
                projection_anchor=projection_anchor,
                source_event_id=source_event_id,
                source_offset=source_offset,
            )
            sequence = max(0, source_offset) * 10 + public_index
            try:
                frame = project_public_projection_event(
                    public_event_type,
                    public_data,
                    session_id=session_id,
                    sequence=sequence,
                    public_anchor=public_anchor,
                    lifecycle_state=lifecycle_state,
                ).get("public_projection_frame")
            except Exception:
                continue
            if not _history_public_projection_frame_allowed(frame):
                continue
            frame_id = str(dict(frame or {}).get("frame_id") or dict(frame or {}).get("projection_id") or "").strip()
            if frame_id and frame_id in seen_frame_ids:
                continue
            if frame_id:
                seen_frame_ids.add(frame_id)
            frames.append(dict(frame))
    return sorted(frames, key=lambda item: (_int_value(item.get("event_offset"), fallback=0), str(item.get("frame_id") or "")))


def _runtime_event_record_to_stream_event(runtime_host: Any, event: dict[str, Any]) -> dict[str, Any]:
    raw = dict(event or {})
    try:
        payload_store = getattr(getattr(runtime_host, "event_log", None), "payload_store", None)
        hydrated = payload_store.hydrate_event_payload(raw) if payload_store is not None else raw
    except Exception:
        hydrated = raw
    event_type = str(hydrated.get("event_type") or raw.get("event_type") or "").strip()
    return {"type": event_type, "event": hydrated}


def _apply_projection_anchor_to_public_data(
    data: dict[str, Any],
    *,
    projection_anchor: dict[str, Any],
    source_event_id: str,
    source_offset: int,
) -> None:
    session_id = str(projection_anchor.get("session_id") or "")
    turn_id = str(projection_anchor.get("anchor_turn_id") or "")
    message_id = str(projection_anchor.get("anchor_message_id") or "")
    run_id = str(projection_anchor.get("run_id") or "")
    task_run_id = str(projection_anchor.get("task_run_id") or "")
    turn_run_id = str(projection_anchor.get("turn_run_id") or "")
    if session_id:
        data.setdefault("session_id", session_id)
    if turn_id:
        data.setdefault("turn_id", turn_id)
        data.setdefault("active_turn_id", turn_id)
    if message_id:
        data.setdefault("message_id", message_id)
        data.setdefault("message_ref", message_id)
    if run_id:
        data.setdefault("run_id", run_id)
    if task_run_id:
        data.setdefault("task_run_id", task_run_id)
        data.setdefault("runtime_task_run_id", task_run_id)
    if turn_run_id:
        data.setdefault("turn_run_id", turn_run_id)
    if source_event_id:
        data.setdefault("runtime_event_id", source_event_id)
        data.setdefault("source_task_event_id", source_event_id)
    if source_offset >= 0:
        data.setdefault("source_task_event_offset", source_offset)


def _history_public_projection_frame_allowed(frame: Any) -> bool:
    if not isinstance(frame, dict):
        return False
    family = str(frame.get("event_family") or "").strip()
    slot = str(frame.get("slot") or "").strip()
    source = str(frame.get("source_authority") or "").strip()
    visibility = str(frame.get("main_visibility") or "").strip()
    if slot == "body":
        return True
    if family in {"tool_control", "runtime_commit", "turn_anchor_terminal"}:
        return True
    if family == "status_trace" and source == "model":
        return True
    return visibility in {"visible_live", "visible_final", "pinned"}


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
