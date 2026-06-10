from __future__ import annotations

import json
from typing import Any

from harness.runtime.progress_presenter import build_progress_presentation
from harness.runtime.public_chat_timeline import build_public_chat_timeline_from_progress_entries
from harness.runtime.public_projection_filters import should_hide_public_tool_observation
from harness.runtime.public_progress import public_runtime_progress_summary
from harness.runtime.public_progress import public_runtime_progress_title
from harness.runtime.runtime_monitor_public_projection import project_public_timeline_from_events
from harness.runtime.session_task_projection import build_single_agent_task_projection


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
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    events = [item.to_dict() for item in _recent_events(runtime_host, task_run_id, limit=max_timeline_items * 8)]
    monitor = runtime_host.monitor_projector.project_task_run(task_run, now=_latest_now(events, task_run))
    final_answer = str(diagnostics.get("final_answer") or "")
    artifact_refs = list(diagnostics.get("artifact_refs") or [])
    progress_presentation = build_progress_presentation(events=events, task_run=task_run, monitor=monitor)
    progress_entries = _progress_entries(events)[-max(1, int(max_timeline_items or 24)) :]
    anchor_turn_id = _anchor_turn_id(task_run_id=task_run_id, diagnostics=diagnostics, events=events)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    assistant_text = str(anchor_message.get("content") or "") if anchor_message else ""
    anchor_message_id = _history_message_id(anchor_message) if anchor_message else ""
    task_projection = build_single_agent_task_projection(
        runtime_host,
        task_run,
        events=events,
        monitor=monitor,
        anchor_turn_id=anchor_turn_id,
        anchor_message_id=anchor_message_id,
    )
    public_timeline = project_public_timeline_from_events(
        events,
        runtime_host=runtime_host,
        monitor=monitor,
        run_id=task_run_id,
        task_run_id=task_run_id,
        final_answer=final_answer,
        status=str(getattr(task_run, "status", "") or ""),
        assistant_text=assistant_text,
        limit=max_timeline_items,
    )
    public_timeline = _merge_public_timeline(
        public_timeline,
        _public_timeline_from_progress_entries(progress_entries),
        limit=max_timeline_items,
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
        "terminal_reason": public_runtime_progress_summary(getattr(task_run, "terminal_reason", "") or ""),
        "lifecycle": str(monitor.get("lifecycle") or ""),
        "bucket": str(monitor.get("bucket") or ""),
        "title": str(monitor.get("title") or ""),
        "summary": public_runtime_progress_summary(monitor.get("summary") or ""),
        "latest_step": dict(monitor.get("latest_step") or {}),
        "latest_step_summary": public_runtime_progress_summary(monitor.get("latest_step_summary") or ""),
        "latest_event_type": str(monitor.get("latest_event_type") or ""),
        "event_count": _event_count(runtime_host, task_run_id, fallback=len(events)),
        "progress_presentation": progress_presentation,
        "progress_entries": progress_entries,
        "public_timeline": public_timeline,
        **({"task_projection": task_projection} if task_projection else {}),
        "artifact_refs": artifact_refs,
        "final_answer": final_answer,
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
    events = [item.to_dict() for item in _recent_events(runtime_host, turn_run_id, limit=max_timeline_items * 8)]
    progress_entries = _progress_entries(events)[-max(1, int(max_timeline_items or 24)) :]
    anchor_turn_id = _valid_turn_ref(getattr(turn_run, "turn_id", "")) or _turn_id_from_turn_run_id(turn_run_id)
    anchor_message = _anchor_assistant_message(anchor_turn_id=anchor_turn_id, history_messages=history_messages)
    assistant_text = str(anchor_message.get("content") or "") if anchor_message else ""
    status = str(getattr(turn_run, "status", "") or "")
    terminal_reason = str(getattr(turn_run, "terminal_reason", "") or "")
    public_timeline = project_public_timeline_from_events(
        events,
        runtime_host=runtime_host,
        run_id=turn_run_id,
        turn_run_id=turn_run_id,
        final_answer=assistant_text,
        assistant_text=assistant_text,
        status=status,
        limit=max_timeline_items,
    )
    public_timeline = _merge_public_timeline(
        public_timeline,
        _public_timeline_from_progress_entries(progress_entries),
        limit=max_timeline_items,
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
        "latest_step": {
            "step": latest_event_type,
            "status": status,
            "summary": latest_public_text,
            "public_progress_note": latest_public_text,
            "agent_brief_output": "",
            "event_id": str(latest_event.get("event_id") or ""),
            "created_at": float(latest_event.get("created_at") or 0.0),
        },
        "latest_step_summary": latest_public_text,
        "latest_public_progress_note": latest_public_text,
        "agent_brief_output": "",
        "latest_event_type": latest_event_type,
        "event_count": _event_count(runtime_host, turn_run_id, fallback=len(events)),
        "progress_presentation": {},
        "progress_entries": progress_entries,
        "public_timeline": public_timeline,
        "artifact_refs": _artifact_refs_from_progress_entries(progress_entries),
        "final_answer": "",
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


def _merge_public_timeline(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    primary_has_error_item = any(_public_timeline_item_is_error(item) for item in primary)
    for item in [*list(primary or []), *list(secondary or [])]:
        payload = dict(item or {})
        if primary_has_error_item and str(payload.get("kind") or "") == "blocked":
            continue
        key = _public_timeline_key(payload)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(payload)
    return merged[-max(1, int(limit or 24)) :]


def _public_timeline_item_is_error(item: dict[str, Any]) -> bool:
    return str(item.get("kind") or "") == "blocked" or str(item.get("state") or "").lower() in {
        "error",
        "failed",
        "blocked",
    }


def _public_timeline_from_progress_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible_entries = [entry for entry in entries if not _is_control_model_action_progress_entry(entry)]
    items = list(build_public_chat_timeline_from_progress_entries(visible_entries))
    if any(str(item.get("kind") or "") == "opening_judgment" for item in items):
        return items
    for entry in visible_entries:
        if str(entry.get("kind") or "") != "model":
            continue
        text = public_runtime_progress_summary(entry.get("body") or entry.get("publicNote") or entry.get("agentBrief") or "").strip()
        if not text:
            continue
        return [
            {
                "item_id": f"opening:{entry.get('id') or entry.get('eventType') or len(items)}",
                "kind": "opening_judgment",
                "slot": "body",
                "surface": "assistant_body",
                "source_authority": "model",
                "title": "开局判断",
                "text": text,
                "state": "error" if str(entry.get("level") or "") == "error" else "done" if str(entry.get("level") or "") == "success" else "running",
                "trace_refs": [str(entry.get("id") or "")] if str(entry.get("id") or "") else [],
            },
            *items,
        ]
    return items


def _is_control_model_action_progress_entry(entry: dict[str, Any]) -> bool:
    if str(entry.get("evidenceType") or "") != "model_action":
        return False
    status = str(entry.get("statusText") or entry.get("status") or "").strip().lower()
    title = str(entry.get("title") or "").strip()
    body = public_runtime_progress_summary(entry.get("body") or entry.get("publicNote") or "").strip()
    return (
        status in {"waiting_user", "blocked", "work_control", "active_work_control"}
        or title in {"等待补充信息", "处理遇到阻塞", "已收到补充要求"}
        or body in {"需要用户补充信息后才能继续。", "当前请求无法继续执行。"}
    )


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
        _valid_turn_ref(diagnostics.get("turn_id"))
        or _turn_id_from_task_run(task_run_id)
        or _valid_turn_ref(diagnostics.get("latest_interaction_turn_id"))
        or _latest_interaction_turn_id(events)
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


def _progress_entries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    observations_by_ref = _observations_by_ref(events)
    step_observation_refs = _step_observation_refs(events)
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = dict(event.get("payload") or {})
        if event_type == "model_action_admission_checked":
            entry = _turn_model_action_entry(event, payload=payload)
            if entry:
                entries.append(entry)
            continue
        if event_type == "turn_tool_observation_recorded":
            entry = _turn_tool_observation_entry(event, payload=payload)
            if entry:
                entries.append(entry)
            continue
        if event_type == "step_summary_recorded":
            summary = public_runtime_progress_summary(payload.get("summary") or "").strip()
            public_note = public_runtime_progress_summary(payload.get("public_progress_note") or summary).strip()
            agent_brief = public_runtime_progress_summary(payload.get("agent_brief_output") or "").strip()
            public_action_state = dict(payload.get("public_action_state") or {})
            completion_status = public_runtime_progress_summary(
                payload.get("completion_status") or public_action_state.get("completion_status") or ""
            ).strip()
            current_judgment = public_runtime_progress_summary(
                payload.get("current_judgment") or public_action_state.get("current_judgment") or ""
            ).strip()
            next_action = public_runtime_progress_summary(
                payload.get("next_action") or public_action_state.get("next_action") or ""
            ).strip()
            action_type = str(payload.get("action_type") or public_action_state.get("action_type") or "").strip()
            tool_name = str(payload.get("tool_name") or public_action_state.get("tool_name") or "").strip()
            tool_target = public_runtime_progress_summary(payload.get("tool_target") or public_action_state.get("tool_target") or "").strip()
            action_brief = _public_action_state_brief(
                current_judgment=current_judgment,
                next_action=next_action,
                completion_status=completion_status,
                action_type=action_type,
                tool_name=tool_name,
                tool_target=tool_target,
            )
            meta = _public_action_state_meta(
                current_judgment=current_judgment,
                next_action=next_action,
                completion_status=completion_status,
                action_type=action_type,
                tool_name=tool_name,
                tool_target=tool_target,
            )
            step = str(payload.get("step") or "").strip()
            status = str(payload.get("status") or "").strip()
            if step.startswith("task_duplicate_tool_call_guarded"):
                continue
            if step.startswith("task_tool_observation_recorded"):
                refs = dict(event.get("refs") or {})
                observation = observations_by_ref.get(str(refs.get("observation_ref") or "").strip(), {})
                source = str(observation.get("source") or "").strip()
                ref_tool_name = str(refs.get("tool_name") or "").strip()
                if _is_internal_tool_observation(source=source, text=agent_brief):
                    continue
                tool_name = source.removeprefix("tool:") or ref_tool_name
                observation_body = _tool_observation_body(agent_brief or _observation_payload_result(observation) or public_note or summary)
                failed = _observation_text_is_failure(agent_brief or observation_body)
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source or (f"tool:{tool_name}" if tool_name else ""), observation=observation),
                        body=observation_body or public_note or summary,
                        kind="observation",
                        level="error" if failed else _level_from_status(status),
                        status="failed" if failed else (status or "completed"),
                        tool_name=tool_name,
                        public_note=observation_body or public_note or summary,
                        agent_brief=observation_body or agent_brief,
                        evidence_type="tool_observation",
                        meta=meta,
                    )
                )
                continue
            if _is_internal_step_only(step, summary=summary, public_note=public_note, action_brief=action_brief):
                continue
            if public_note or action_brief or summary or step:
                body = public_note or action_brief or summary
                if step.startswith("model_action_received"):
                    body = public_note or action_brief or _objective_model_step_body(step=step, status=status)
                entries.append(
                    _entry(
                        event,
                        title="正在思考" if step.startswith("model_action_received") else _step_title(step, status),
                        body=body,
                        kind=_step_kind(step),
                        level=_level_from_status(status),
                        status=status,
                        public_note=public_note or body,
                        agent_brief=agent_brief or action_brief,
                        evidence_type=_evidence_type(event_type, step),
                        meta=meta,
                    )
                )
            continue
        if event_type == "agent_todo_initialized":
            entries.append(
                _entry(
                    event,
                    title="待办已建立",
                    body="已把任务目标转成可跟踪的待办清单。",
                    kind="stage",
                    level="success",
                    status="completed",
                    public_note="已把任务目标转成可跟踪的待办清单。",
                    evidence_type="todo",
                )
            )
            continue
        if event_type in {"task_run_lifecycle_started", "task_run_executor_started"}:
            entries.append(
                _entry(
                    event,
                    title="处理已开始",
                    body="已开始处理。",
                    kind="stage",
                    level="running",
                    status="running",
                    public_note="已开始处理。",
                    evidence_type="runtime_step",
                )
            )
            continue
        if event_type in {"user_work_instruction_recorded", "active_task_steer_recorded"}:
            steer = dict(payload.get("steer") or {})
            observation = dict(payload.get("observation") or {})
            observation_payload = dict(observation.get("payload") or {})
            structured_payload = dict(observation_payload.get("structured_payload") or {})
            instruction = str(
                steer.get("content")
                or structured_payload.get("user_instruction")
                or observation_payload.get("result")
                or ""
            ).strip()
            entries.append(
                _entry(
                    event,
                    title="收到补充要求",
                    body=public_runtime_progress_summary(instruction),
                    kind="stage",
                    level="success",
                    status="completed",
                    public_note=public_runtime_progress_summary(instruction),
                    evidence_type="user_instruction",
                )
            )
            continue
        if event_type in {"executor_observation_recorded", "bounded_observation_recorded", "task_run_lifecycle_event", "task_tool_observation_recorded"}:
            observation = dict(payload.get("observation") or {})
            if event_type == "task_tool_observation_recorded":
                observation_id = str(observation.get("observation_id") or "").strip()
                if observation_id and observation_id in step_observation_refs:
                    continue
            source = str(observation.get("source") or "").strip()
            summary = public_runtime_progress_summary(observation.get("summary") or "").strip()
            if _is_internal_tool_observation(source=source, text=summary or _observation_payload_result(observation)):
                continue
            if event_type == "task_tool_observation_recorded" and source.startswith("tool:"):
                observation_body = _tool_observation_body(summary or _observation_payload_result(observation))
                if not observation_body:
                    continue
                failed = _observation_text_is_failure(observation_body)
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source, observation=observation),
                        body=observation_body,
                        kind="observation",
                        level="error" if failed else "success",
                        status="failed" if failed else "completed",
                        tool_name=source.removeprefix("tool:"),
                        public_note=observation_body,
                        agent_brief=observation_body,
                        evidence_type="tool_observation",
                    )
                )
                continue
            if source == "system:agent_todo" or _looks_like_raw_json(summary):
                continue
            if source or summary:
                entries.append(
                    _entry(
                        event,
                        title=_observation_title(source, observation=observation),
                        body=summary,
                        kind="tool" if source.startswith("tool:") else "system",
                        level="error" if observation.get("error") else "success",
                        status="failed" if observation.get("error") else "completed",
                        tool_name=source.removeprefix("tool:"),
                        public_note=summary,
                        agent_brief=summary,
                        evidence_type="tool_observation" if source.startswith("tool:") else "observation",
                    )
                )
            continue
        if event_type == "task_run_lifecycle_finished":
            task_run = dict(payload.get("task_run") or {})
            status = str(task_run.get("status") or "completed")
            entries.append(
                _entry(
                    event,
                    title="处理完成" if status == "completed" else "处理遇到阻塞",
                    body=public_runtime_progress_summary(task_run.get("terminal_reason") or status),
                    kind="terminal",
                    level="success" if status == "completed" else "error",
                    status=status,
                    public_note=public_runtime_progress_summary(task_run.get("terminal_reason") or status),
                    evidence_type="terminal",
                )
            )
    return entries


def _turn_model_action_entry(event: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    action_request = dict(payload.get("model_action_request") or {})
    action_type = str(action_request.get("action_type") or "").strip()
    public_note = public_runtime_progress_summary(action_request.get("public_progress_note") or "").strip()
    if action_type == "ask_user":
        question = public_runtime_progress_summary(action_request.get("user_question") or public_note or "需要补充信息后继续。").strip()
        return _entry(
            event,
            title="等待补充信息",
            body=question,
            kind="stage",
            level="waiting",
            status="waiting_user",
            public_note=public_note,
            evidence_type="model_action",
        )
    if action_type == "block":
        reason = public_runtime_progress_summary(action_request.get("blocking_reason") or public_note or "当前请求无法继续处理。").strip()
        return _entry(
            event,
            title="处理遇到阻塞",
            body=reason,
            kind="terminal",
            level="error",
            status="blocked",
            public_note=public_note,
            evidence_type="model_action",
        )
    if action_type == "active_work_control":
        title, body = _active_work_status_text_from_action(dict(action_request.get("active_work_control") or {}).get("action"))
        return _entry(
            event,
            title=title,
            body=public_note or body,
            kind="stage",
            level="success",
            status="work_control",
            public_note=public_note,
            evidence_type="model_action",
        )
    if action_type != "tool_call":
        body = public_note or "正在判断下一步动作。"
        return _entry(
            event,
            title="正在思考",
            body=body,
            kind="model",
            level="running",
            status="running",
            public_note=body,
            evidence_type="model_action",
        )
    tool_call = dict(action_request.get("tool_call") or {})
    tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or action_request.get("tool_name") or "").strip()
    preview = _tool_call_preview(tool_call)
    title = _tool_activity_title(tool_name=tool_name, preview=preview, phase="started")
    return _entry(
        event,
        title=title,
        body=public_note or preview or "已发起工具请求。",
        kind="tool",
        level="running",
        status=_tool_activity_status(tool_name=tool_name, phase="started"),
        tool_name=tool_name,
        public_note=public_note or preview,
        evidence_type="tool_request",
        meta=_compact_meta(
            [
                {"label": "工具", "value": tool_name},
                {"label": "目标", "value": preview},
            ]
        ),
    )


def _turn_tool_observation_entry(event: dict[str, Any], *, payload: dict[str, Any]) -> dict[str, Any]:
    preview = dict(payload.get("preview") or {})
    observation = dict(preview.get("tool_observation") or payload.get("tool_observation") or {})
    if not observation:
        return {}
    envelope = dict(observation.get("result_envelope") or {})
    receipt = dict(observation.get("execution_receipt") or {})
    tool_name = str(observation.get("tool_name") or envelope.get("tool_name") or receipt.get("tool_name") or "").strip()
    tool_args = dict(observation.get("tool_args") or envelope.get("tool_args") or {})
    target = _tool_args_preview(tool_args)
    status = str(observation.get("status") or receipt.get("status") or "").strip()
    error = str(observation.get("error") or receipt.get("error") or "").strip()
    failed = bool(error or (status and status.lower() not in {"ok", "completed", "success"}))
    result_text = public_runtime_progress_summary(
        error
        or observation.get("text")
        or envelope.get("text")
        or (f"工具状态：{status}" if status else "工具结果已返回。")
    ).strip()
    if failed and should_hide_public_tool_observation(
        tool_name,
        target,
        result_text,
        error,
        observation.get("text"),
        envelope.get("error"),
        envelope.get("text"),
        _record_value(observation.get("structured_error")).get("message"),
        _record_value(envelope.get("structured_error")).get("message"),
    ):
        return {}
    return _entry(
        event,
        title=_tool_activity_title(tool_name=tool_name, preview=target, phase="failed" if failed else "completed"),
        body=result_text,
        kind="tool",
        level="error" if failed else "success",
        status=_tool_activity_status(tool_name=tool_name, phase="failed" if failed else "completed"),
        tool_name=tool_name,
        public_note=result_text,
        agent_brief=result_text,
        evidence_type="tool_observation",
        meta=_compact_meta(
            [
                {"label": "工具", "value": tool_name},
                {"label": "目标", "value": target},
            ]
        ),
        artifacts=_turn_tool_observation_artifacts(observation),
    )


def _active_work_status_text_from_action(value: Any) -> tuple[str, str]:
    action = str(value or "").strip()
    if action == "continue_active_work":
        return "继续当前工作", "当前工作已进入继续处理流程。"
    if action == "pause_active_work":
        return "暂停当前工作", "暂停请求已记录。"
    if action == "stop_active_work":
        return "停止当前工作", "停止请求已记录。"
    if action == "append_instruction_to_active_work":
        return "已收到补充要求", "补充要求已进入当前工作队列。"
    if action in {"answer_about_active_work", "answer_then_continue_active_work"}:
        return "查看当前进展", "当前工作进展已同步。"
    return "当前工作控制", "当前工作控制状态已更新。"


def _tool_call_preview(tool_call: dict[str, Any]) -> str:
    return _tool_args_preview(dict(tool_call.get("args") or tool_call.get("input") or {}))


def _tool_args_preview(args: dict[str, Any]) -> str:
    for key in ("command", "shell_command", "cmd", "script", "path", "file_path", "relative_path", "target_path", "query", "pattern", "url"):
        value = public_runtime_progress_summary(args.get(key) or "").strip()
        if value:
            return value[:240]
    return ""


def _tool_activity_title(*, tool_name: str, preview: str, phase: str) -> str:
    family = _tool_family(tool_name)
    target = preview or tool_name or "工具"
    labels = {
        "write": {"started": "正在写入", "completed": "写入完成", "failed": "写入失败"},
        "read": {"started": "正在读取", "completed": "读取完成", "failed": "读取失败"},
        "run": {"started": "正在运行", "completed": "命令已完成", "failed": "命令失败"},
        "search": {"started": "正在搜索", "completed": "搜索完成", "failed": "搜索失败"},
        "tool": {"started": "正在调用", "completed": "工具已完成", "failed": "工具失败"},
    }
    title = labels.get(family, labels["tool"]).get(phase, labels["tool"]["started"])
    return f"{title} {target}".strip()


def _tool_activity_status(*, tool_name: str, phase: str) -> str:
    family = _tool_family(tool_name)
    if phase == "failed":
        return "失败"
    if phase == "completed":
        return "已完成"
    if family == "write":
        return "写入中"
    if family == "read":
        return "读取中"
    if family == "run":
        return "运行中"
    if family == "search":
        return "搜索中"
    return "调用中"


def _tool_family(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    if any(item in normalized for item in ("write", "edit", "patch")):
        return "write"
    if "read" in normalized:
        return "read"
    if any(item in normalized for item in ("terminal", "shell", "command")):
        return "run"
    if "search" in normalized:
        return "search"
    return "tool"


def _turn_tool_observation_artifacts(observation: dict[str, Any]) -> list[dict[str, str]]:
    envelope = dict(observation.get("result_envelope") or {})
    structured = dict(observation.get("structured_payload") or {})
    envelope_structured = dict(envelope.get("structured_payload") or {})
    artifacts: list[dict[str, str]] = []
    for source in (observation, structured, envelope_structured):
        for path in [
            *list(source.get("observed_paths") or []),
            *list(source.get("written_paths") or []),
            *list(source.get("matched_paths") or []),
        ]:
            normalized = str(path or "").strip()
            if normalized:
                artifacts.append({"label": "产物", "path": normalized})
        for item in list(source.get("artifact_refs") or []):
            if isinstance(item, str):
                normalized = item.strip()
            elif isinstance(item, dict):
                normalized = str(item.get("path") or item.get("file") or item.get("absolute_path") or item.get("ref") or "").strip()
            else:
                normalized = ""
            if normalized:
                artifacts.append({"label": "产物", "path": normalized})
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in artifacts:
        key = f"{item.get('label')}:{item.get('path')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def _compact_meta(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [item for item in items if str(item.get("label") or "").strip() and str(item.get("value") or "").strip()][:6]


def _record_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _artifact_refs_from_progress_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for entry in entries:
        artifacts.extend([dict(item) for item in list(entry.get("artifacts") or []) if isinstance(item, dict)])
    return artifacts[:12]


def _entry(
    event: dict[str, Any],
    *,
    title: str,
    body: str = "",
    kind: str = "stage",
    level: str = "running",
    status: str = "",
    tool_name: str = "",
    public_note: str = "",
    agent_brief: str = "",
    evidence_type: str = "",
    meta: list[dict[str, str]] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    item = {
        "id": str(event.get("event_id") or f"{event.get('run_id') or event.get('task_run_id')}:{event.get('offset')}"),
        "eventType": str(event.get("event_type") or ""),
        "runId": str(event.get("run_id") or event.get("task_run_id") or ""),
        "taskRunId": _formal_task_run_id(event.get("run_id") or event.get("task_run_id")),
        "title": title,
        "body": body,
        "kind": kind,
        "level": level,
        "statusText": status,
        "toolName": tool_name,
        "createdAt": float(event.get("created_at") or 0.0),
    }
    if public_note:
        item["publicNote"] = public_note
    if agent_brief:
        item["agentBrief"] = agent_brief
    if evidence_type:
        item["evidenceType"] = evidence_type
    if meta:
        item["meta"] = list(meta)
    if artifacts:
        item["artifacts"] = list(artifacts)
    return item


def _formal_task_run_id(value: Any) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate.startswith("taskrun:") else ""


def _observations_by_ref(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if str(event.get("event_type") or "") != "task_tool_observation_recorded":
            continue
        observation = dict(dict(event.get("payload") or {}).get("observation") or {})
        observation_id = str(observation.get("observation_id") or "").strip()
        if observation_id:
            result[observation_id] = observation
    return result


def _step_observation_refs(events: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for event in events:
        if str(event.get("event_type") or "") != "step_summary_recorded":
            continue
        payload = dict(event.get("payload") or {})
        step = str(payload.get("step") or "")
        if not step.startswith(("task_tool_observation_recorded", "task_duplicate_tool_call_guarded")):
            continue
        observation_ref = str(dict(event.get("refs") or {}).get("observation_ref") or "").strip()
        if observation_ref:
            refs.add(observation_ref)
    return refs


def _observation_payload_result(observation: dict[str, Any]) -> str:
    return str(dict(observation.get("payload") or {}).get("result") or "").strip()


def _is_internal_tool_observation(*, source: str, text: str) -> bool:
    tool_name = str(source or "").strip().removeprefix("tool:")
    if tool_name == "agent_todo":
        return True
    stripped = str(text or "").strip()
    return stripped.startswith("{") and '"plan_id"' in stripped and '"items"' in stripped


def _public_action_state_brief(
    *,
    current_judgment: str = "",
    next_action: str = "",
    completion_status: str = "",
    action_type: str = "",
    tool_name: str = "",
    tool_target: str = "",
) -> str:
    parts = []
    if current_judgment:
        parts.append(f"说明：{current_judgment}")
    visible_next_action = _validated_public_next_action(
        next_action=next_action,
        action_type=action_type,
        tool_name=tool_name,
        tool_target=tool_target,
    )
    if visible_next_action:
        parts.append(f"计划：{visible_next_action}")
    if completion_status:
        parts.append(f"状态：{completion_status}")
    return public_runtime_progress_summary("；".join(parts))


def _public_action_state_meta(
    *,
    current_judgment: str = "",
    next_action: str = "",
    completion_status: str = "",
    action_type: str = "",
    tool_name: str = "",
    tool_target: str = "",
) -> list[dict[str, str]]:
    visible_next_action = _validated_public_next_action(
        next_action=next_action,
        action_type=action_type,
        tool_name=tool_name,
        tool_target=tool_target,
    )
    labels = (
        ("模型说明", current_judgment),
        ("计划动作", visible_next_action),
        ("状态", completion_status),
    )
    return [{"label": label, "value": value} for label, value in labels if value]


def _validated_public_next_action(*, next_action: str, action_type: str, tool_name: str, tool_target: str) -> str:
    candidate = public_runtime_progress_summary(next_action).strip()
    normalized_action = str(action_type or "").strip().lower()
    if not candidate:
        return ""
    if normalized_action == "tool_call":
        fragments = [
            tool_name,
            tool_name.replace("_", " "),
            tool_target,
            _target_basename(tool_target),
            *_tool_action_keywords(tool_name),
        ]
        return candidate if _contains_public_fragment(candidate, fragments) else ""
    if normalized_action == "respond":
        return candidate if _contains_public_fragment(candidate, ("回复", "回答", "整理", "总结", "收口", "说明", "respond")) else ""
    if normalized_action == "ask_user":
        return candidate if _contains_public_fragment(candidate, ("询问", "提问", "确认", "补充", "请你", "需要你", "ask")) else ""
    if normalized_action == "request_task_run":
        return candidate if _contains_public_fragment(candidate, ("任务", "运行", "持续", "后台", "建立", "启动", "处理流程")) else ""
    if normalized_action == "block":
        return candidate if _contains_public_fragment(candidate, ("阻塞", "受阻", "说明", "无法", "等待", "确认")) else ""
    return candidate if not normalized_action else ""


def _target_basename(target: str) -> str:
    text = str(target or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else ""


def _tool_action_keywords(tool_name: str) -> tuple[str, ...]:
    normalized = str(tool_name or "").strip().lower()
    if normalized in {"image_generate", "image_generation", "generate_image"}:
        return ("图像", "图片", "生图", "美术", "资源", "生成", "image")
    if normalized == "path_exists":
        return ("路径", "存在", "检查", "确认", "artifact", "path")
    if normalized in {"stat_path", "list_dir"}:
        return ("路径", "目录", "检查", "读取", "列表", "path", "dir")
    if normalized in {"read_file", "read_path"}:
        return ("读取", "查看", "文件", "内容", "read")
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return ("写入", "创建", "修改", "编辑", "补丁", "文件", "write", "edit", "patch")
    if normalized in {"search_text", "search_files", "glob_paths"}:
        return ("搜索", "查找", "检索", "匹配", "search", "grep")
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return ("命令", "终端", "运行", "执行", "shell", "powershell")
    return tuple(part for part in normalized.replace("-", "_").split("_") if part)


def _contains_public_fragment(value: str, fragments: list[str] | tuple[str, ...]) -> bool:
    haystack = _match_public_text(value)
    for fragment in fragments:
        needle = _match_public_text(fragment)
        if len(needle) >= 2 and needle in haystack:
            return True
    return False


def _match_public_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _objective_model_step_body(*, step: str, status: str) -> str:
    if str(status or "").strip().lower().startswith("wait"):
        return "等待模型输出。"
    if step.startswith(("task_model_action_waiting", "model_action_waiting")):
        return "等待模型输出。"
    return "正在思考。"


def _is_internal_step_only(step: str, *, summary: str, public_note: str, action_brief: str) -> bool:
    if action_brief:
        return False
    if step.startswith("task_lifecycle_started"):
        return True
    if step.startswith(("task_model_action_invocation_started", "task_model_action_waiting")):
        return True
    if step.startswith("task_execution_packet_compiled") and (summary == "已同步最新进展。" or public_note == "已同步最新进展。"):
        return True
    return False


def _looks_like_raw_json(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")
    )


def _tool_observation_body(value: str) -> str:
    text = public_runtime_progress_summary(value).strip()
    if not text:
        return ""
    if not _looks_like_raw_json(text):
        return text
    try:
        data = json.loads(text)
    except Exception:
        return "工具返回了结构化结果，正在根据结果继续。"
    if isinstance(data, dict):
        ok = data.get("ok")
        error = data.get("error") or data.get("message")
        structured_error = data.get("structured_error")
        if isinstance(structured_error, dict):
            error = error or structured_error.get("message") or structured_error.get("error")
        if ok is False or error:
            message = public_runtime_progress_summary(error or "工具调用失败").strip()
            return f"工具返回失败：{message}"
        result = data.get("result") or data.get("summary") or data.get("output")
        if result:
            return public_runtime_progress_summary(result)
        artifact_refs = data.get("artifact_refs")
        if isinstance(artifact_refs, list) and artifact_refs:
            return f"工具返回成功，产生 {len(artifact_refs)} 个产物引用。"
        return "工具返回成功，正在根据结果继续。"
    return "工具返回了结构化结果，正在根据结果继续。"


def _observation_text_is_failure(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "工具返回失败" in text:
        return True
    if _looks_like_raw_json(text):
        try:
            data = json.loads(text)
        except Exception:
            return False
        if isinstance(data, dict):
            return data.get("ok") is False or bool(data.get("error") or data.get("structured_error"))
    return False


def _step_title(step: str, status: str) -> str:
    if step.startswith("task_model_action_invocation_started"):
        return "正在思考"
    if step.startswith("task_model_action_waiting"):
        return "等待模型输出"
    if step.startswith("task_execution_packet_compiled"):
        return "整理上下文"
    if step.startswith("task_tool_executed"):
        return "执行操作"
    if step.startswith("task_completion_repair_required"):
        return "补充验收证据"
    if step == "task_run_completed":
        return "处理已完成"
    if status == "completed":
        return "步骤已完成"
    return public_runtime_progress_title(step=step, status=status)


def _step_kind(step: str) -> str:
    if "observation" in step:
        return "observation"
    if "tool" in step:
        return "tool"
    if "completed" in step:
        return "terminal"
    if "repair" in step or "verification" in step:
        return "verification"
    if "model" in step:
        return "model"
    return "stage"


def _level_from_status(status: str) -> str:
    if status in {"completed", "success"}:
        return "success"
    if status in {"failed", "error", "blocked"}:
        return "error"
    if status.startswith("wait"):
        return "waiting"
    return "running"


def _observation_title(source: str, *, observation: dict[str, Any] | None = None) -> str:
    if source.startswith("tool:"):
        tool_name = source.removeprefix("tool:").strip()
        return _tool_result_title(tool_name)
    if dict(observation or {}).get("error"):
        return "结果未完成"
    return "结果已返回"


def _tool_result_title(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    if normalized in {"read_file", "read_path", "stat_path", "list_dir", "path_exists"}:
        return "上下文已返回"
    if normalized in {"search_text", "search_files", "glob_paths", "memory_search"}:
        return "检索结果已返回"
    if normalized in {"write_file", "edit_file", "apply_patch"}:
        return "文件更新已返回"
    if normalized in {"terminal", "shell", "run_command", "powershell"}:
        return "命令结果已返回"
    if normalized in {"image_generate", "image_generation", "generate_image"}:
        return "图像结果已返回"
    return "结果已返回"


def _evidence_type(event_type: str, step: str) -> str:
    if "tool" in step:
        return "tool_observation"
    if "model_action" in step:
        return "model_action"
    if "repair" in step or "verification" in step:
        return "verification"
    if "completed" in step or event_type.endswith("finished"):
        return "terminal"
    return "runtime_step"
