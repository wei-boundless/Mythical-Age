from __future__ import annotations

from typing import Any

from harness.runtime.projection.timeline_builder import (
    merge_public_timeline_item,
    project_public_timeline_from_events,
    public_timeline_order_key,
)
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.projection.task_projection import build_single_agent_task_projection


_SUPPRESSED_PROGRESS_TEXT = {
    "",
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在处理",
    "正在处理当前请求",
    "正在处理任务",
    "正在思考",
    "正在思考。",
    "等待模型输出",
    "等待模型输出。",
    "已开始处理",
    "已开始处理。",
    "已开始处理当前请求",
    "已开始处理当前请求。",
    "已同步最新进展。",
    "已接上当前工作，正在同步最新进展。",
    "已开始继续处理；接下来会持续汇报正在推进的步骤。",
    "已把任务目标转成可跟踪的待办清单。",
    "已把任务目标转成可跟踪的处理清单。",
    "处理清单已建立",
    "处理清单已更新。",
    "工具调用已完成，正在根据结果继续。",
    "工具返回成功，正在根据结果继续。",
    "工具返回了结构化结果，正在根据结果继续。",
    "正在判断下一步动作。",
    "等待结果返回",
    "结果已返回",
    "上下文已返回",
    "读取未完成，需要重新确认读取范围后继续。",
    "waiting_for_tool",
    "tool_returned",
    "ready_to_finish",
    "responding",
    "verifying",
    "completed",
    "done",
    "running",
    "working",
    "success",
}
_STRUCTURED_PLAN_TOOL_NAMES = {
    "agent_todo",
}
_PUBLIC_TIMELINE_RESET_EVENTS = {
    "user_work_instruction_recorded",
    "active_task_steer_recorded",
    "active_task_steer_accepted",
    "active_task_steer_included",
    "active_task_steer_consumed",
    "task_run_resume_requested",
}


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
    public_since_offset = _public_since_offset(events)
    public_events = _events_since_offset(events, public_since_offset)
    monitor = runtime_host.monitor_projector.project_task_run(task_run, now=_latest_now(events, task_run))
    artifact_refs = list(diagnostics.get("artifact_refs") or [])
    anchor_turn_id = _anchor_turn_id(task_run_id=task_run_id, diagnostics=diagnostics, events=public_events or events)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    anchor_message_id = _history_message_id(anchor_message) if anchor_message else ""
    task_projection = build_single_agent_task_projection(
        runtime_host,
        task_run,
        events=public_events,
        monitor=monitor,
        anchor_turn_id=anchor_turn_id,
        anchor_message_id=anchor_message_id,
    )
    public_timeline = _public_timeline_from_task_projection(task_projection, limit=max_timeline_items)
    public_timeline = _scope_public_timeline_items(
        public_timeline,
        session_id=session_id,
        anchor_turn_id=anchor_turn_id,
        run_id=task_run_id,
        task_run_id=task_run_id,
        turn_run_id="",
    )
    closeout_summary = _attachment_closeout_summary(task_run=task_run, diagnostics=diagnostics, monitor=monitor)
    projection_summary = _task_projection_summary(task_projection)
    projection_missing = not task_projection or not projection_summary
    visible_summary = closeout_summary or projection_summary or "progress_projection_missing"
    return {
        "attachment_id": f"runtime-attachment:{task_run_id}",
        "run_id": task_run_id,
        "anchor_turn_id": anchor_turn_id,
        "anchor_message_id": anchor_message_id,
        "anchor_role": "assistant",
        "task_run_id": task_run_id,
        "task_id": str(getattr(task_run, "task_id", "") or ""),
        "status": str(getattr(task_run, "status", "") or ""),
        "terminal_reason": _visible_progress_summary(getattr(task_run, "terminal_reason", "") or ""),
        "lifecycle": str(monitor.get("lifecycle") or ""),
        "bucket": str(monitor.get("bucket") or ""),
        "title": str(monitor.get("title") or ""),
        "summary": visible_summary,
        "latest_event_type": str(monitor.get("latest_event_type") or ""),
        "event_count": _event_count(runtime_host, task_run_id, fallback=len(events)),
        "public_timeline": public_timeline,
        "public_since_offset": public_since_offset,
        "public_projection_status": {
            "authority": "session_runtime_timeline.public_projection_status",
            "source": "task_projection" if not projection_missing else "progress_projection_missing",
            "missing": projection_missing,
            **({"diagnostic": "progress_projection_missing"} if projection_missing else {}),
        },
        **({"session_output_commit": session_output_commit} if session_output_commit else {}),
        **({"task_projection": task_projection} if task_projection else {}),
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
    status = str(getattr(turn_run, "status", "") or "")
    terminal_reason = str(getattr(turn_run, "terminal_reason", "") or "")
    public_timeline = project_public_timeline_from_events(
        events,
        runtime_host=runtime_host,
        run_id=turn_run_id,
        turn_run_id=turn_run_id,
        final_answer="",
        status=status,
        limit=max_timeline_items,
    )
    public_timeline = _scope_public_timeline_items(
        public_timeline,
        session_id=session_id,
        anchor_turn_id=anchor_turn_id,
        run_id=turn_run_id,
        task_run_id="",
        turn_run_id=turn_run_id,
    )
    if not public_timeline:
        return {}
    latest_public_text = _latest_public_timeline_text(public_timeline)
    latest_event = events[-1] if events else {}
    latest_event_type = str(latest_event.get("event_type") or "")
    return {
        "attachment_id": f"runtime-attachment:{turn_run_id}",
        "run_id": turn_run_id,
        "turn_run_id": turn_run_id,
        "anchor_turn_id": anchor_turn_id,
        "anchor_message_id": _history_message_id(anchor_message) if anchor_message else "",
        "anchor_role": "assistant",
        "task_run_id": "",
        "task_id": "",
        "status": status,
        "terminal_reason": "" if _is_internal_turn_terminal_reason(terminal_reason) else public_runtime_progress_summary(terminal_reason),
        "lifecycle": status,
        "bucket": "turn",
        "title": "会话运行",
        "summary": latest_public_text,
        "latest_event_type": latest_event_type,
        "event_count": _event_count(runtime_host, turn_run_id, fallback=len(events)),
        "public_timeline": public_timeline,
        "artifact_refs": [],
        "trace_available": True,
        "debug_trace_ref": turn_run_id,
        "created_at": float(getattr(turn_run, "created_at", 0.0) or 0.0),
        "updated_at": max(_latest_now(events, turn_run), float(getattr(turn_run, "updated_at", 0.0) or 0.0)),
        "authority": "session_runtime_timeline.turn_attachment",
    }


def _is_internal_turn_terminal_reason(reason: str) -> bool:
    normalized = str(reason or "").strip().lower()
    return normalized in {
        "active_work_control",
        "ask_user",
        "assistant_message",
        "block",
        "stream_cancelled",
        "turn_stream_closed",
        "harness.entrypoint_error",
    }


def _attachment_closeout_summary(*, task_run: Any, diagnostics: dict[str, Any], monitor: dict[str, Any]) -> str:
    status = str(getattr(task_run, "status", "") or monitor.get("status") or "").strip().lower()
    if status not in {"completed", "failed", "stopped", "aborted", "cancelled", "canceled"}:
        return ""
    for value in (
        diagnostics.get("closeout_summary"),
        diagnostics.get("final_answer"),
        monitor.get("closeout_summary"),
        monitor.get("final_answer"),
    ):
        visible = _visible_progress_summary(value)
        if visible:
            return visible
    if status == "completed":
        return "结果收口"
    for value in (
        getattr(task_run, "terminal_reason", ""),
        monitor.get("diagnostic_summary"),
        monitor.get("summary"),
    ):
        visible = _visible_progress_summary(value)
        if visible:
            return visible
    return ""


def _merge_public_timeline(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged_by_key: dict[str, dict[str, Any]] = {}
    insertion_order: list[str] = []
    seen: set[str] = set()
    primary_has_error_item = any(_public_timeline_item_is_error(item) for item in primary)
    for item in [*list(primary or []), *list(secondary or [])]:
        payload = dict(item or {})
        if primary_has_error_item and str(payload.get("kind") or "") == "blocked":
            continue
        key = _public_timeline_key(payload)
        if not key:
            continue
        if key in seen:
            merged_by_key[key] = merge_public_timeline_item(merged_by_key[key], payload)
            continue
        seen.add(key)
        insertion_order.append(key)
        merged_by_key[key] = payload
    ordered = sorted(
        enumerate([merged_by_key[key] for key in insertion_order]),
        key=lambda item: (*public_timeline_order_key(item[1]), item[0]),
    )
    return [item for _, item in ordered][-max(1, int(limit or 24)) :]


def _scope_public_timeline_items(
    items: list[dict[str, Any]],
    *,
    session_id: str,
    anchor_turn_id: str,
    run_id: str,
    task_run_id: str,
    turn_run_id: str,
) -> list[dict[str, Any]]:
    scoped: list[dict[str, Any]] = []
    for item in list(items or []):
        payload = dict(item or {})
        turn_id = str(payload.get("turn_id") or payload.get("anchor_turn_id") or anchor_turn_id)
        scoped.append(
            {
                **payload,
                "session_id": str(payload.get("session_id") or session_id),
                "anchor_turn_id": turn_id,
                "turn_id": turn_id,
                "run_id": str(payload.get("run_id") or payload.get("source_run_id") or run_id),
                "task_run_id": str(payload.get("task_run_id") or task_run_id),
                "turn_run_id": str(payload.get("turn_run_id") or turn_run_id),
            }
        )
    return scoped


def _public_timeline_item_is_error(item: dict[str, Any]) -> bool:
    return str(item.get("kind") or "") == "blocked" or str(item.get("state") or "").lower() in {
        "error",
        "failed",
        "blocked",
    }


def _task_projection_summary(projection: dict[str, Any]) -> str:
    payload = _dict_record(projection)
    if not payload:
        return ""
    current_action = _dict_record(payload.get("current_action"))
    for value in (
        current_action.get("title"),
        current_action.get("detail"),
        payload.get("summary"),
        payload.get("title"),
    ):
        visible = _visible_progress_summary(value)
        if visible:
            return visible
    return ""


def _public_timeline_from_task_projection(projection: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    payload = _dict_record(projection)
    if not payload:
        return []
    items: list[dict[str, Any]] = []
    current_action = _dict_record(payload.get("current_action"))
    for index, activity in enumerate(list(payload.get("activities") or [])):
        item = _projection_activity_timeline_item(_dict_record(activity), fallback_index=index)
        if item:
            items.append(item)
    current_item = _projection_activity_timeline_item(
        current_action,
        fallback_index=len(items),
        fallback_item_id=f"task-projection:current:{payload.get('task_run_id') or ''}:{_projection_revision(payload, public_since_offset=0)}",
        primary=True,
    )
    if current_item:
        items.append(current_item)
    return _merge_public_timeline(items, [], limit=limit)


def _projection_activity_timeline_item(
    activity: dict[str, Any],
    *,
    fallback_index: int,
    fallback_item_id: str = "",
    primary: bool = False,
) -> dict[str, Any]:
    if not activity:
        return {}
    title = _visible_progress_summary(activity.get("title") or activity.get("summary"))
    detail = _visible_progress_summary(activity.get("detail"))
    if not title and detail:
        title, detail = detail, ""
    if not title:
        return {}
    event_ref = str(activity.get("event_ref") or "").strip()
    item_id = event_ref or fallback_item_id or f"task-projection:activity:{fallback_index}"
    event_offset = _int_value(activity.get("event_offset") or activity.get("sequence"), fallback=fallback_index)
    created_at = _float_value(activity.get("created_at"), fallback=0.0)
    surface = str(activity.get("display_surface") or "").strip()
    kind = str(activity.get("kind") or "").strip()
    state = _projection_timeline_state(activity.get("state"))
    source_kind = str(activity.get("source_kind") or kind or "").strip()
    base = {
        "item_id": item_id,
        "title": title,
        "detail": detail,
        "text": detail or title,
        "state": state,
        "phase": "done" if state in {"done", "completed", "stopped", "error"} else "running",
        "stream_state": "done" if state in {"done", "completed", "stopped", "error"} else "streaming",
        "source_event_id": event_ref,
        "event_offset": event_offset,
        "sequence": event_offset,
        "created_at": created_at,
        "source_authority": "runtime",
    }
    if surface == "tool_window" or "tool" in kind or activity.get("tool_name"):
        return {
            **base,
            "kind": "work_action",
            "slot": "tool",
            "surface": "tool_window",
            "source_authority": "tool",
            "action_kind": source_kind or "tool",
            "tool_name": str(activity.get("tool_name") or ""),
            "subject_label": str(activity.get("tool_target") or ""),
            "public_summary": detail or title,
        }
    return {
        **base,
        "kind": "status_update",
        "slot": "status" if primary else "timeline",
        "surface": "status_bar" if primary and surface == "status" else "timeline",
    }


def _projection_revision(projection: dict[str, Any], *, public_since_offset: int) -> str:
    value = projection.get("updated_at") or public_since_offset or projection.get("created_at") or "current"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value or "current").strip() or "current"
    if numeric.is_integer():
        return str(int(numeric))
    return str(numeric)


def _projection_timeline_state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"completed", "success"}:
        return "done"
    if normalized in {"failed", "error", "blocked"}:
        return "error"
    if normalized in {"stopped", "aborted", "cancelled", "canceled"}:
        return "stopped"
    if normalized.startswith("wait") or normalized in {"paused", "queued"}:
        return "waiting"
    return normalized or "running"


def _dict_record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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


def _public_timeline_key(item: dict[str, Any]) -> str:
    for key in ("item_id", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "|".join(
        [
            str(item.get("kind") or ""),
            str(item.get("text") or item.get("detail") or item.get("public_summary") or ""),
            str(item.get("title") or ""),
        ]
    ).strip("|")


def _latest_public_timeline_text(items: list[dict[str, Any]]) -> str:
    for item in reversed(list(items or [])):
        text = _public_timeline_item_text(item)
        if text:
            return text
    return ""


def _public_timeline_item_text(item: dict[str, Any]) -> str:
    for key in (
        "public_summary",
        "text",
        "detail",
        "observation",
        "title",
        "subject_label",
        "path",
        "href",
    ):
        text = str(item.get(key) or "").strip()
        if text:
            return public_runtime_progress_summary(text)
    return ""


def _public_since_offset(events: list[dict[str, Any]]) -> int:
    for event in reversed(sorted(list(events or []), key=lambda item: int(item.get("offset") or 0))):
        event_type = str(event.get("event_type") or "")
        if event_type in _PUBLIC_TIMELINE_RESET_EVENTS:
            return int(event.get("offset") or 0)
        if event_type == "task_run_executor_scheduled":
            payload = dict(event.get("payload") or {})
            scheduler = str(payload.get("scheduler") or "").strip()
            if scheduler in {"task_run_resume_api", "task_run_approval_resume_api"}:
                return int(event.get("offset") or 0)
    return 0


def _events_since_offset(events: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    boundary = int(offset or 0)
    if boundary <= 0:
        return list(events or [])
    return [event for event in list(events or []) if int(event.get("offset") or 0) >= boundary]


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


def _looks_like_raw_json(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")
    )


def _visible_progress_summary(value: Any) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    compact = "".join(text.split()).strip("。.!！?？,，;；:：").lower()
    suppressed = {
        "".join(item.split()).strip("。.!！?？,，;；:：").lower()
        for item in _SUPPRESSED_PROGRESS_TEXT
    }
    return "" if compact in suppressed else text
