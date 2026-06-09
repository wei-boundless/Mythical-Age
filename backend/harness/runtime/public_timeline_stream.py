from __future__ import annotations

import json
from hashlib import sha1
from typing import Any

from harness.runtime.progress_presenter import public_todo_plan_from_event
from harness.runtime.public_chat_timeline import public_todo_plan_item
from harness.runtime.public_projection_filters import should_hide_public_tool_observation
from harness.runtime.public_timeline_projection import (
    memory_search_observation_detail,
    public_text,
    public_work_action_item,
)


_INTERNAL_STEP_SUMMARIES = {
    "turn_started",
    "runtime_packet_compiled",
    "action_admission_checked",
    "bounded_observation_recorded",
}

_SUPPRESSED_TEXT = {
    "",
    "assistant_message",
    "done",
    "completed",
    "running",
    "working",
    "开始处理",
    "处理完成",
    "处理已完成",
    "处理结束",
    "正在处理",
    "正在处理当前请求",
    "正在处理当前请求。",
    "正在处理任务",
    "正在建立任务运行",
    "正在建立任务运行。",
    "已开始处理当前请求",
    "已开始处理当前请求。",
    "回答已生成并写回会话",
    "会话输出完成",
}

_GENERIC_TOOL_WAIT_PREFIXES = (
    "已发起工具调用，正在等待工具返回",
    "已经过工具调用，正在等待工具返回",
)

_INTERNAL_PROTOCOL_TEXT_MARKERS = (
    "action_type",
    "内部工具协议",
    "工具调用残片",
    "completion_status",
    "dsml",
    "model_action",
    "public_action_state",
    "public_progress_note",
    "tool_call",
    "tool_calls",
    "active_work_control.action",
)
_CONTROL_ASSISTANT_CHANNELS = {
    "active_work_control",
    "ask_user",
    "blocked",
    "runtime_control",
    "task_control",
}
_STAGE_FEEDBACK_ASSISTANT_CHANNELS = {
    "progress_feedback",
    "stage_feedback",
}
_STAGE_FEEDBACK_ASSISTANT_SOURCES = {
    "harness.single_agent_turn.tool_commentary",
}


def project_public_timeline_delta(
    public_event_type: str,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    event_type = str(public_event_type or "").strip()
    if not event_type:
        return []
    items = _items_for_event(event_type, data)
    return [item for item in items if item]


def _items_for_event(event_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    if event_type == "runtime_step_summary":
        return _runtime_step_summary_items(data)
    if event_type == "model_action_admission":
        return _model_action_admission_items(data)
    if event_type in {"assistant_text", "answer_candidate"}:
        return [_assistant_text_item(event_type, data)]
    if event_type == "turn_tool_observation_recorded":
        return [_turn_tool_observation_item(data)]
    if event_type == "task_tool_observation_recorded":
        return [_task_tool_observation_item(data)]
    if event_type == "task_run_lifecycle_event":
        return [_task_run_lifecycle_item(data)]
    if event_type == "runtime_status":
        title = _visible_text(data.get("title"))
        detail = _visible_text(data.get("detail"))
        if not title and not detail:
            return []
        return [_status_item(
            item_id=_stable_id("status", str(data.get("runtime_task_run_id") or ""), str(data.get("title") or data.get("detail") or "")),
            title=title or detail,
            detail=detail if detail != title else "",
            state=str(data.get("state") or "running"),
            phase=str(data.get("phase") or ""),
        )]
    if event_type == "active_task_steer_accepted":
        return [_status_item(
            item_id=_stable_id("steer", str(data.get("runtime_task_run_id") or ""), str(data.get("summary") or "")),
            title="已收到补充要求",
            detail=_visible_text(data.get("summary")),
            state="running",
        )]
    if event_type == "done":
        return [_done_item(data)]
    if event_type == "error":
        return [_blocked_item(
            item_id=_stable_id("error", str(data.get("runtime_task_run_id") or ""), str(data.get("error") or "")),
            text=_visible_text(data.get("error") or data.get("content") or "处理失败"),
            state="error",
        )]
    if event_type == "stopped":
        return [_status_item(
            item_id=_stable_id("stopped", str(data.get("runtime_task_run_id") or ""), str(data.get("reason") or "")),
            title="已停止当前处理",
            detail=_visible_text(data.get("reason") or data.get("content")),
            state="stopped",
            phase="stopped",
        )]
    return []


def _task_run_lifecycle_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    if str(event.get("event_type") or "").strip() != "agent_todo_initialized":
        return {}
    return public_todo_plan_item(public_todo_plan_from_event(event))


def _assistant_text_item(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    answer_channel = str(data.get("answer_channel") or "").strip().lower()
    answer_source = str(data.get("answer_source") or "").strip()
    text = _visible_agent_feedback(data.get("content") or data.get("text") or data.get("answer"))
    if answer_channel == "ask_user":
        return _status_item(
            item_id=_stable_id(event_type, str(data.get("event_id") or data.get("debug_trace_ref") or ""), text),
            title="等待补充信息",
            detail=text,
            state="waiting",
            phase="waiting_user",
            slot="control",
            surface="control",
        )
    if answer_channel == "blocked":
        return _blocked_item(
            item_id=_stable_id(event_type, str(data.get("event_id") or data.get("debug_trace_ref") or ""), text),
            text=text or "当前请求无法继续处理。",
            state="error",
        )
    if answer_channel in _CONTROL_ASSISTANT_CHANNELS:
        return {}
    if event_type == "answer_candidate" or not _is_public_assistant_text(
        answer_channel=answer_channel,
        answer_source=answer_source,
    ):
        return {}
    if not text:
        return {}
    task_run_id = str(data.get("runtime_task_run_id") or data.get("task_run_id") or "").strip()
    trace_ref = str(data.get("event_id") or data.get("debug_trace_ref") or "").strip()
    kind = "opening_judgment" if answer_channel == "task_control" else "stage_summary"
    title = "开局判断" if kind == "opening_judgment" else "阶段反馈"
    return _compact(
        {
            "item_id": _stable_id(event_type, trace_ref or task_run_id, text),
            "kind": kind,
            "slot": "body",
            "surface": "assistant_body",
            "source_authority": "model",
            "title": title,
            "text": text,
            "state": "running",
            "trace_refs": [trace_ref] if trace_ref else [],
        }
    )


def _is_public_assistant_text(*, answer_channel: str, answer_source: str) -> bool:
    if answer_channel in _STAGE_FEEDBACK_ASSISTANT_CHANNELS:
        return True
    return answer_source in _STAGE_FEEDBACK_ASSISTANT_SOURCES


def _model_action_admission_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    request = _record(payload.get("model_action_request"))
    action_type = str(request.get("action_type") or "").strip().lower()
    control_item = _control_action_item_from_model_action(
        item_id=_stable_id("control-action", str(event.get("event_id") or ""), action_type),
        request=request,
        state="waiting" if action_type == "ask_user" else "error" if action_type == "block" else "running",
    )
    if control_item:
        return [control_item]
    items: list[dict[str, Any]] = []
    if action_type != "tool_call":
        feedback = _agent_feedback_item_from_model_action(
            item_id=_stable_id("agent-feedback", str(event.get("event_id") or ""), str(request.get("public_progress_note") or "")),
            request=request,
            state="running",
            trace_ref=str(event.get("event_id") or ""),
        )
        if feedback:
            items.append(feedback)
        return items
    feedback = _agent_feedback_item_from_model_action(
        item_id=_stable_id("agent-feedback", str(event.get("event_id") or ""), str(request.get("public_progress_note") or "")),
        request=request,
        state="running",
        trace_ref=str(event.get("event_id") or ""),
    )
    if feedback:
        items.append(feedback)
    tool_name, target = _tool_details_from_event(request)
    trace_ref = str(event.get("event_id") or "") or _stable_id("tool-admission", tool_name, target)
    item_id = _work_action_id(data=data, event=event, tool_name=tool_name, target=target, fallback=trace_ref)
    action = public_work_action_item(
        item_id=item_id,
        tool_name=tool_name,
        raw_target=target,
        state="running",
        trace_refs=[trace_ref],
    )
    if action:
        items.append(action)
    return items


def _control_action_item_from_model_action(
    *,
    item_id: str,
    request: dict[str, Any],
    state: str,
) -> dict[str, Any]:
    action_type = str(request.get("action_type") or "").strip().lower()
    if action_type == "ask_user":
        question = _visible_agent_feedback(request.get("user_question")) or _visible_agent_feedback(request.get("public_progress_note"))
        return _status_item(
            item_id=item_id,
            title="等待补充信息",
            detail=question,
            state=state,
            phase="waiting_user",
        )
    if action_type == "block":
        reason = _visible_agent_feedback(request.get("blocking_reason")) or _visible_agent_feedback(request.get("public_progress_note"))
        return _blocked_item(
            item_id=item_id,
            text=reason or "当前请求无法继续处理。",
            state=state,
        )
    if action_type == "active_work_control":
        title, fallback = _active_work_control_status_text(request)
        note = _visible_agent_feedback(request.get("public_progress_note")) or _visible_agent_feedback(_record(request.get("public_action_state")).get("current_judgment"))
        return _status_item(
            item_id=item_id,
            title=title,
            detail=note or fallback,
            state=state,
            phase="active_work_control",
        )
    return {}


def _active_work_control_status_text(request: dict[str, Any]) -> tuple[str, str]:
    control = _record(request.get("active_work_control"))
    action = str(control.get("resolved_action") or control.get("action") or "").strip()
    return _active_work_status_text_from_action(action)


def _active_work_status_text_from_action(action: str) -> tuple[str, str]:
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


def _turn_tool_observation_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    observation = _record(payload.get("tool_observation") or _record(payload.get("preview")).get("tool_observation"))
    return _tool_observation_item(data=data, event=event, observation=observation)


def _task_tool_observation_item(data: dict[str, Any]) -> dict[str, Any]:
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    observation = _record(payload.get("observation"))
    return _tool_observation_item(data=data, event=event, observation=observation)


def _tool_observation_item(*, data: dict[str, Any], event: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    if not observation:
        return {}
    tool_name = _tool_name_from_observation(observation)
    if tool_name == "agent_todo":
        return public_todo_plan_item(public_todo_plan_from_event(event))
    target = _tool_target_from_observation(observation)
    state = _tool_observation_state(observation)
    detail = _tool_observation_detail(observation, target=target)
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    structured_error = _record(observation.get("structured_error")) or _record(payload.get("structured_error"))
    envelope_structured_error = _record(envelope.get("structured_error"))
    if state == "error" and should_hide_public_tool_observation(
        tool_name,
        target,
        detail,
        observation.get("error"),
        observation.get("text"),
        payload.get("error"),
        payload.get("result"),
        envelope.get("error"),
        envelope.get("text"),
        structured_error.get("message"),
        envelope_structured_error.get("message"),
    ):
        return {}
    trace_ref = str(event.get("event_id") or "") or _stable_id("tool-observation", tool_name, target or detail)
    item_id = _work_action_id(data=data, event=event, tool_name=tool_name, target=target or detail, fallback=trace_ref)
    return public_work_action_item(
        item_id=item_id,
        tool_name=tool_name,
        raw_target=target,
        observation=detail,
        state=state,
        trace_refs=[trace_ref],
        recovery_hint=observation.get("error") or envelope.get("error"),
    )


def _runtime_step_summary_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    step = str(data.get("step") or "").strip()
    if not step or step in _INTERNAL_STEP_SUMMARIES:
        return []
    event = _record(data.get("event"))
    todo = public_todo_plan_item(public_todo_plan_from_event(event))
    if todo:
        return [todo]
    status = str(data.get("status") or "").strip().lower()
    payload = _record(event.get("payload"))
    summary = _visible_text(data.get("public_progress_note") or data.get("summary"))
    agent_brief = _visible_text(data.get("agent_brief_output") or data.get("current_judgment"))
    state = _timeline_state(status)
    trace_ref = str(event.get("event_id") or "") or _stable_id("step", step, summary or agent_brief)

    if _looks_like_tool_step(step, payload):
        tool_name, target = _tool_details_from_event(payload)
        detail = _tool_detail(summary=summary, agent_brief=agent_brief, target=target)
        item_id = _work_action_id(data=data, event=event, tool_name=tool_name, target=target or detail, fallback=trace_ref)
        item = public_work_action_item(
            item_id=item_id,
            tool_name=tool_name,
            raw_target=target,
            summary=detail,
            state=state,
            trace_refs=[trace_ref],
        )
        return [item] if item else []

    if _is_status_only_step(step):
        prose = _visible_text(agent_brief or summary)
        return [_compact(
            {
                "item_id": trace_ref,
                "kind": "status_update",
                "slot": "status",
                "surface": "status_bar",
                "source_authority": "system",
                "title": prose,
                "text": prose,
                "state": state,
                "trace_refs": [trace_ref],
            }
        )] if prose else []
    feedback = _agent_feedback_item_from_model_action(
        item_id=trace_ref,
        request={**payload, "public_progress_note": summary},
        state=state,
        trace_ref=trace_ref,
        fallback=agent_brief,
        force_feedback=True,
    )
    return [feedback] if feedback else []


def _agent_feedback_item_from_model_action(
    *,
    item_id: str,
    request: dict[str, Any],
    state: str,
    trace_ref: str,
    fallback: Any = "",
    force_feedback: bool = False,
) -> dict[str, Any]:
    action_state = _record(request.get("public_action_state"))
    text = _visible_agent_feedback(
        action_state.get("current_judgment")
        or request.get("current_judgment")
        or request.get("public_progress_note")
        or fallback
    )
    if not text:
        return {}
    if force_feedback:
        next_step = _visible_agent_feedback(action_state.get("next_action") or request.get("next_action"))
        return _compact(
            {
                "item_id": item_id,
                "kind": "observation_report",
                "slot": "body",
                "surface": "assistant_body",
                "source_authority": "model",
                "title": "处理反馈",
                "detail": text,
                "implication": next_step if next_step and next_step != text else "",
                "state": state,
                "trace_refs": [trace_ref] if trace_ref else [],
            }
        )
    return _compact(
        {
            "item_id": item_id,
            "kind": "opening_judgment",
            "slot": "body",
            "surface": "assistant_body",
            "source_authority": "model",
            "title": "开局判断",
            "text": text,
            "state": state,
            "trace_refs": [trace_ref] if trace_ref else [],
        }
    )


def _visible_agent_feedback(value: Any) -> str:
    text = _visible_text(value, limit=0)
    if not text:
        return ""
    lowered = text.lower()
    if _looks_like_internal_protocol_text(text):
        return ""
    if any(lowered.startswith(prefix) for prefix in _GENERIC_TOOL_WAIT_PREFIXES):
        return ""
    if text in _SUPPRESSED_TEXT or lowered in _SUPPRESSED_TEXT:
        return ""
    if text.startswith(("正在调用", "工具已完成", "工具失败")):
        return ""
    return text


def _looks_like_internal_protocol_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _INTERNAL_PROTOCOL_TEXT_MARKERS)


def _done_item(data: dict[str, Any]) -> dict[str, Any]:
    task_run_id = str(data.get("runtime_task_run_id") or "").strip()
    terminal_reason = str(data.get("terminal_reason") or "").strip()
    answer_channel = str(data.get("answer_channel") or "").strip()
    summary = _visible_text(data.get("receipt_summary") or data.get("summary") or data.get("message"))
    if terminal_reason == "task_executor_scheduled" or answer_channel == "task_control":
        return {}
    if str(data.get("completion_state") or "").strip() == "task_steer_accepted":
        return _status_item(
            item_id=_stable_id("steer-done", task_run_id, summary),
            title="已收到补充要求",
            detail=summary,
            state="running",
        )
    if not summary:
        return {}
    return _status_item(
        item_id=_stable_id("done", task_run_id, terminal_reason),
        title=summary,
        state="done",
        phase="done",
    )


def _status_item(
    *,
    item_id: str,
    title: str,
    detail: str = "",
    state: str,
    phase: str = "",
    slot: str = "status",
    surface: str = "status_bar",
) -> dict[str, Any]:
    return _compact(
        {
            "item_id": item_id,
            "kind": "status_update",
            "slot": slot,
            "surface": surface,
            "source_authority": "system",
            "title": title,
            "detail": detail,
            "state": state,
            "phase": phase,
        }
    )


def _blocked_item(*, item_id: str, text: str, state: str) -> dict[str, Any]:
    if not text:
        return {}
    return _compact(
        {
            "item_id": item_id,
            "kind": "blocked",
            "slot": "status",
            "surface": "status_bar",
            "source_authority": "system",
            "text": text,
            "state": state,
        }
    )


def _looks_like_tool_step(step: str, payload: dict[str, Any]) -> bool:
    normalized = step.lower()
    if "tool" in normalized or "observation" in normalized:
        return True
    action_type = str(payload.get("action_type") or _record(payload.get("public_action_state")).get("action_type") or "").strip().lower()
    return action_type == "tool_call"


def _is_status_only_step(step: str) -> bool:
    normalized = step.lower()
    return normalized.startswith("task_executor_scheduled") or "resume" in normalized or "handoff" in normalized


def _tool_details_from_event(payload: dict[str, Any]) -> tuple[str, str]:
    public_action_state = _record(payload.get("public_action_state"))
    direct_tool_call = _record(payload.get("tool_call"))
    action_request = _record(payload.get("action_request"))
    nested_tool_call = _record(action_request.get("tool_call"))
    tool_name = str(
        payload.get("tool_name")
        or public_action_state.get("tool_name")
        or action_request.get("tool_name")
        or direct_tool_call.get("name")
        or nested_tool_call.get("name")
        or "",
    ).strip()
    raw_target = (
        payload.get("tool_target")
        or public_action_state.get("tool_target")
        or ""
    )
    target = _visible_text(raw_target, limit=240) if not isinstance(raw_target, dict) else ""
    if not target:
        tool_call = direct_tool_call or nested_tool_call
        args = _record(tool_call.get("args"))
        for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
            target = _visible_text(args.get(key), limit=240)
            if target:
                break
    return tool_name, target


def _tool_target_from_observation(observation: dict[str, Any]) -> str:
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    args = _record(observation.get("tool_args")) or _record(payload.get("tool_args")) or _record(envelope.get("tool_args"))
    for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
        target = _visible_text(args.get(key), limit=240)
        if target:
            return target
    structured = _observation_structured_payload(observation)
    tool_result = _record(structured.get("tool_result"))
    for key in ("path", "file_path", "target_path", "query", "pattern", "command", "url"):
        target = _visible_text(tool_result.get(key), limit=240)
        if target:
            return target
    observed_paths = structured.get("observed_paths")
    if isinstance(observed_paths, list):
        for item in observed_paths:
            target = _visible_text(item, limit=240)
            if target:
                return target
    return ""


def _tool_family(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    if normalized == "memory_search":
        return "memory"
    if normalized in {"path_exists", "stat_path", "list_dir"}:
        return "check"
    if any(item in normalized for item in ("write", "edit", "patch")):
        return "write"
    if "read" in normalized:
        return "read"
    if any(item in normalized for item in ("search", "grep", "glob")):
        return "search"
    if any(item in normalized for item in ("terminal", "shell", "command", "powershell")):
        return "run"
    return "tool"


def _work_action_id(*, data: dict[str, Any], event: dict[str, Any], tool_name: str, target: str, fallback: str) -> str:
    scope = _runtime_scope_key(data=data, event=event)
    family = _tool_family(tool_name)
    subject = target or tool_name or fallback
    return _stable_id("work-action", scope or family, f"{family}|{subject}")


def _runtime_scope_key(*, data: dict[str, Any], event: dict[str, Any]) -> str:
    active_turn = _record(data.get("active_turn"))
    return str(
        data.get("runtime_task_run_id")
        or data.get("task_run_id")
        or data.get("turn_run_id")
        or active_turn.get("turn_run_id")
        or active_turn.get("turn_id")
        or event.get("run_id")
        or event.get("task_run_id")
        or event.get("turn_id")
        or "",
    ).strip()


def _tool_detail(*, summary: str, agent_brief: str, target: str) -> str:
    for candidate in (summary, agent_brief):
        text = _visible_text(candidate)
        if not text:
            continue
        lowered = text.lower()
        if any(lowered.startswith(prefix) for prefix in _GENERIC_TOOL_WAIT_PREFIXES):
            continue
        if text == target:
            continue
        return text
    return target


def _tool_observation_detail(observation: dict[str, Any], *, target: str) -> str:
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    tool_name = _tool_name_from_observation(observation).lower()
    if tool_name == "memory_search":
        return _memory_search_observation_detail(
            observation.get("text")
            or payload.get("result")
            or payload.get("text")
            or envelope.get("text")
            or envelope.get("structured_payload")
        )
    structured = _observation_structured_payload(observation)
    tool_result = _record(structured.get("tool_result"))
    if tool_name == "path_exists":
        exists = _result_bool(tool_result.get("exists"))
        if exists is None:
            exists = _result_bool(payload.get("result"))
        if exists is True:
            return "目标路径存在"
        if exists is False:
            return "目标路径不存在"
    if tool_name in {"search_text", "search_files", "glob_paths"}:
        return _search_observation_detail(
            observation=observation,
            payload=payload,
            envelope=envelope,
            structured=structured,
            tool_result=tool_result,
            target=target,
        )
    if str(tool_result.get("kind") or "").strip() == "path_exists":
        exists = tool_result.get("exists")
        if exists is True:
            return "目标路径存在"
        if exists is False:
            return "目标路径不存在"
    text = _visible_text(observation.get("text") or payload.get("text") or payload.get("result") or envelope.get("text") or tool_result.get("summary"))
    if text and text != target:
        return text
    return target


def _search_observation_detail(
    *,
    observation: dict[str, Any],
    payload: dict[str, Any],
    envelope: dict[str, Any],
    structured: dict[str, Any],
    tool_result: dict[str, Any],
    target: str,
) -> str:
    matched_paths = _public_path_list(
        payload.get("matched_paths"),
        structured.get("matched_paths"),
        envelope.get("matched_paths"),
        tool_result.get("matched_paths"),
        tool_result.get("paths"),
        tool_result.get("files"),
    )
    if matched_paths:
        preview = "、".join(matched_paths[:3])
        suffix = f"等 {len(matched_paths)} 处" if len(matched_paths) > 3 else ""
        return f"已找到相关引用：{preview}{suffix}"

    observed_paths = _public_path_list(
        payload.get("observed_paths"),
        structured.get("observed_paths"),
        envelope.get("observed_paths"),
        tool_result.get("observed_paths"),
    )
    result_count = _safe_int(
        tool_result.get("result_count")
        or tool_result.get("match_count")
        or tool_result.get("count")
        or structured.get("result_count")
        or envelope.get("result_count")
    )
    if result_count and result_count > 0:
        if observed_paths:
            return f"已找到 {result_count} 处相关引用，涉及 {'、'.join(observed_paths[:3])}"
        return f"已找到 {result_count} 处相关引用"

    text = _visible_text(observation.get("text") or payload.get("text") or payload.get("result") or envelope.get("text") or tool_result.get("summary"))
    if text and text != target:
        return text
    if result_count == 0:
        return "未找到相关引用"
    return ""


def _public_path_list(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidates = value if isinstance(value, list) else []
        for item in candidates:
            if isinstance(item, dict):
                raw = item.get("path") or item.get("file") or item.get("href") or item.get("url")
            else:
                raw = item
            text = _visible_text(raw, limit=120)
            if not text:
                continue
            key = text.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
    return result


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timeline_state(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "success", "done"}:
        return "done"
    if normalized in {"failed", "error", "blocked", "aborted", "cancelled", "canceled"}:
        return "error"
    if normalized.startswith("wait"):
        return "running"
    return "running"


def _visible_text(value: Any, *, limit: int = 220) -> str:
    return public_text(value, limit=limit)


def _memory_search_observation_detail(value: Any) -> str:
    return memory_search_observation_detail(value)


def _tool_name_from_observation(observation: dict[str, Any]) -> str:
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    structured = _observation_structured_payload(observation)
    source = str(observation.get("source") or "").strip()
    if source in {"agent_todo", "system:agent_todo", "tool:agent_todo"}:
        return "agent_todo"
    return str(
        observation.get("tool_name")
        or payload.get("tool_name")
        or envelope.get("tool_name")
        or structured.get("tool_name")
        or source.removeprefix("tool:")
        or "",
    ).strip()


def _tool_observation_state(observation: dict[str, Any]) -> str:
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    structured = _observation_structured_payload(observation)
    tool_result = _record(structured.get("tool_result"))
    for value in (
        observation.get("status"),
        payload.get("status"),
        envelope.get("status"),
        tool_result.get("status"),
    ):
        status = str(value or "").strip().lower()
        if status in {"ok", "success", "done", "completed"}:
            return "done"
        if status in {"needs_approval", "waiting_approval"}:
            return "running"
        if status in {"failed", "error", "denied", "canceled", "cancelled", "aborted"}:
            return "error"
        if status in {"needs_contract"}:
            return "error"
    parsed = _parse_result(payload.get("result"))
    if isinstance(parsed, dict) and (parsed.get("ok") is False or parsed.get("error") or parsed.get("structured_error")):
        return "error"
    if observation.get("error") or payload.get("error") or envelope.get("error") or tool_result.get("error"):
        return "error"
    return "done"


def _observation_payload(observation: dict[str, Any]) -> dict[str, Any]:
    return _record(observation.get("payload"))


def _observation_envelope(observation: dict[str, Any]) -> dict[str, Any]:
    payload = _observation_payload(observation)
    return _record(observation.get("result_envelope")) or _record(payload.get("result_envelope"))


def _observation_structured_payload(observation: dict[str, Any]) -> dict[str, Any]:
    payload = _observation_payload(observation)
    envelope = _observation_envelope(observation)
    return _record(observation.get("structured_payload")) or _record(payload.get("structured_payload")) or _record(envelope.get("structured_payload"))


def _parse_result(value: Any) -> Any:
    if isinstance(value, (dict, list, bool, int, float)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _result_bool(value: Any) -> bool | None:
    parsed = _parse_result(value)
    if isinstance(parsed, bool):
        return parsed
    if isinstance(parsed, dict):
        for key in ("exists", "ok", "success", "result"):
            if isinstance(parsed.get(key), bool):
                return parsed[key]
    return None


def _stable_id(prefix: str, left: str, right: str) -> str:
    digest = sha1(f"{prefix}|{left}|{right}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}
