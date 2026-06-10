from __future__ import annotations

from typing import Any

from .authority import build_public_projection_frame
from .guards import compact, record, stable_id, text
from .items import control_item, observation_report_item, opening_judgment_item, status_item, work_action_item


TYPED_ASSISTANT_STREAM_EVENTS = {
    "assistant_text_delta",
    "assistant_text_final",
    "assistant_stream_repair",
}


def project_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
    task_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    items = projection_items_for_event(public_event_type, payload)
    frame = build_public_projection_frame(
        public_event_type,
        payload,
        session_id=session_id,
        sequence=sequence,
        items=items,
        task_projection=task_projection,
        public_anchor=public_anchor,
    )
    return {"public_projection_envelope": frame}


def attach_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
    task_projection: dict[str, Any] | None = None,
) -> None:
    projection = project_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
        public_anchor=public_anchor,
        task_projection=task_projection,
    )
    data["public_projection_envelope"] = projection["public_projection_envelope"]
    data.pop("public_timeline_delta", None)


def projection_items_for_event(public_event_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = text(public_event_type)
    if not event_type or event_type in TYPED_ASSISTANT_STREAM_EVENTS:
        return []
    if event_type == "assistant_text":
        item = _assistant_text_item(data)
        return [item] if item else []
    if event_type == "model_action_admission":
        return _model_action_items(data)
    if event_type in {"turn_tool_observation_recorded", "task_tool_observation_recorded", "tool_observation"}:
        item = _tool_observation_item(data)
        return [item] if item else []
    if event_type == "runtime_step_summary":
        return _runtime_step_summary_items(data)
    if event_type == "runtime_status":
        item = control_item(
            item_id=_item_id("control", data),
            kind="control_state",
            title=data.get("title") or data.get("summary") or "运行状态",
            detail=data.get("detail"),
            state=data.get("state") or data.get("status") or "running",
            trace_refs=_trace_refs(data),
        )
        return [item] if item else []
    if event_type == "active_task_steer_accepted":
        item = control_item(
            item_id=_item_id("steer", data),
            kind="steer_ack",
            title="已收到补充要求",
            detail=data.get("summary"),
            state="done",
            trace_refs=_trace_refs(data),
        )
        return [item] if item else []
    if event_type == "error":
        item = control_item(
            item_id=_item_id("error", data),
            kind="error_notice",
            title=data.get("error") or data.get("message") or "处理失败",
            detail=data.get("terminal_reason") or data.get("reason"),
            state="error",
            trace_refs=_trace_refs(data),
        )
        return [item] if item else []
    if event_type == "stopped":
        item = control_item(
            item_id=_item_id("stopped", data),
            kind="safe_boundary_wait",
            title=data.get("reason") or "当前处理已停止",
            detail=data.get("terminal_reason"),
            state="stopped",
            trace_refs=_trace_refs(data),
        )
        return [item] if item else []
    if event_type == "done":
        item = _done_item(data)
        return [item] if item else []
    return []


def _assistant_text_item(data: dict[str, Any]) -> dict[str, Any]:
    channel = text(data.get("answer_channel")).lower()
    if channel in {"task_control", "runtime_control", "active_work_control"}:
        return {}
    source = text(data.get("answer_source")).lower()
    content = data.get("content") or data.get("text") or data.get("answer")
    kind = "opening_judgment" if channel == "opening_judgment" or "opening_judgment" in source else "model_body_final"
    return opening_judgment_item(
        item_id=_item_id(kind, data),
        text_value=content,
        state="done" if data.get("answer_canonical_state") == "final" else "running",
        trace_refs=_trace_refs(data),
    ) if kind == "opening_judgment" else observation_report_item(
        item_id=_item_id(kind, data),
        detail=content,
        state="done",
        trace_refs=_trace_refs(data),
    )


def _model_action_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    action = _model_action_request(data)
    action_type = text(action.get("action_type")).lower()
    public_note = action.get("public_progress_note") or data.get("public_progress_note")
    action_state = record(action.get("public_action_state") or data.get("public_action_state"))
    current_judgment = action_state.get("current_judgment") or action.get("current_judgment")
    next_action = action_state.get("next_action") or action.get("next_action")
    trace_refs = _trace_refs(data)
    if action_type in {"respond", "ask_user", "block"}:
        detail = action.get("response") or action.get("user_question") or action.get("blocking_reason") or public_note
        item = observation_report_item(item_id=_item_id(action_type, data), detail=detail, implication=next_action, state="done", trace_refs=trace_refs)
        return [item] if item else []
    items: list[dict[str, Any]] = []
    feedback = current_judgment or public_note
    if action_type in {"tool_call", "request_task_run"} and feedback:
        item = opening_judgment_item(
            item_id=_item_id("opening", data),
            text_value=feedback,
            state="running",
            trace_refs=trace_refs,
        )
        if item:
            items.append(item)
    if action_type == "tool_call":
        tool = record(action.get("tool_call"))
        tool_name = text(tool.get("tool_name") or tool.get("name") or action.get("tool_name"))
        args = tool.get("args") or tool.get("arguments") or action.get("tool_args")
        item = work_action_item(
            item_id=_item_id("tool", data),
            tool_name=tool_name,
            raw_target=args,
            summary=next_action,
            state="running",
            trace_refs=trace_refs,
        )
        if item:
            items.append(item)
    if action_type == "request_task_run":
        item = control_item(
            item_id=_item_id("task", data),
            kind="control_state",
            title="任务已建立，等待执行器继续",
            detail=next_action,
            state="waiting",
            trace_refs=trace_refs,
        )
        if item:
            items.append(item)
    return items


def _tool_observation_item(data: dict[str, Any]) -> dict[str, Any]:
    event = record(data.get("event"))
    payload = record(event.get("payload") or data.get("payload"))
    observation = record(payload.get("observation") or data.get("observation") or payload)
    tool_name = text(
        observation.get("tool_name")
        or observation.get("tool")
        or payload.get("tool_name")
        or data.get("tool_name")
    )
    target = observation.get("target") or observation.get("path") or observation.get("query") or payload.get("target") or data.get("target")
    result = observation.get("summary") or observation.get("result") or observation.get("structured_payload") or payload.get("summary")
    state = "error" if observation.get("error") or payload.get("error") else "done"
    return work_action_item(
        item_id=_item_id("toolobs", data),
        tool_name=tool_name,
        raw_target=target,
        observation=result,
        state=state,
        trace_refs=_trace_refs(data),
        recovery_hint=observation.get("error") or payload.get("error"),
    )


def _runtime_step_summary_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    step = text(data.get("step"))
    if not step or step in {"task_lifecycle_started", "task_executor_scheduled"}:
        return []
    action_state = record(data.get("public_action_state"))
    summary = data.get("public_progress_note") or data.get("summary")
    current_judgment = data.get("current_judgment") or action_state.get("current_judgment")
    next_action = data.get("next_action") or action_state.get("next_action")
    trace_refs = _trace_refs(data)
    if step.startswith(("tool_", "task_tool_", "turn_tool_")):
        item = work_action_item(
            item_id=_item_id("step-tool", data),
            tool_name=data.get("tool_name") or step,
            summary=summary,
            state=data.get("status") or "running",
            trace_refs=trace_refs,
        )
        return [item] if item else []
    feedback = current_judgment or data.get("agent_brief_output")
    if feedback:
        item = observation_report_item(
            item_id=_item_id("step-feedback", data),
            detail=feedback,
            implication=next_action,
            state=data.get("status") or "running",
            trace_refs=trace_refs,
        )
        return [item] if item else []
    item = status_item(
        item_id=_item_id("step-status", data),
        title=summary,
        state=data.get("status") or "running",
        trace_refs=trace_refs,
    )
    return [item] if item else []


def _done_item(data: dict[str, Any]) -> dict[str, Any]:
    channel = text(data.get("answer_channel")).lower()
    reason = text(data.get("terminal_reason")).lower()
    if channel in {"task_control", "runtime_control", "active_work_control"} or reason == "task_executor_scheduled":
        return {}
    content = data.get("content")
    if content:
        return observation_report_item(
            item_id=_item_id("done", data),
            detail=content,
            state="done",
            trace_refs=_trace_refs(data),
        )
    return {}


def _model_action_request(data: dict[str, Any]) -> dict[str, Any]:
    action = record(data.get("model_action_request"))
    if action:
        return action
    public_action = record(data.get("public_action"))
    if public_action:
        return _model_action_request_from_public_action(public_action)
    event = record(data.get("event"))
    payload = record(event.get("payload"))
    return record(payload.get("model_action_request"))


def _model_action_request_from_public_action(public_action: dict[str, Any]) -> dict[str, Any]:
    kind = text(public_action.get("kind")).lower()
    action_type = {
        "tool": "tool_call",
        "task": "request_task_run",
        "reply": "respond",
        "question": "ask_user",
        "blocked": "block",
        "control": "active_work_control",
    }.get(kind)
    if not action_type:
        return {}
    action_state = record(public_action.get("action_state"))
    progress_note = public_action.get("progress_note") or action_state.get("current_judgment")
    payload: dict[str, Any] = {
        "action_type": action_type,
        "public_progress_note": progress_note,
        "public_action_state": action_state,
        "current_judgment": action_state.get("current_judgment") or progress_note,
        "next_action": action_state.get("next_action"),
    }
    if action_type == "tool_call":
        tool = record(public_action.get("tool"))
        target = text(tool.get("target"))
        payload["tool_call"] = compact(
            {
                "tool_name": tool.get("tool_name"),
                "args": {"target": target} if target else {},
            }
        )
    elif action_type == "ask_user":
        payload["user_question"] = public_action.get("question") or progress_note
    elif action_type == "block":
        payload["blocking_reason"] = public_action.get("reason") or progress_note
    elif action_type == "respond":
        payload["response"] = progress_note
    return compact(payload)


def _item_id(prefix: str, data: dict[str, Any]) -> str:
    event = record(data.get("event"))
    return stable_id(
        prefix,
        data.get("runtime_event_id") or data.get("event_id") or event.get("event_id"),
        data.get("sequence") or data.get("event_offset"),
        data.get("step"),
    )


def _trace_refs(data: dict[str, Any]) -> list[str]:
    event = record(data.get("event"))
    refs = []
    for value in (
        data.get("runtime_event_id"),
        data.get("event_id"),
        event.get("event_id"),
        data.get("debug_trace_ref"),
    ):
        if text(value):
            refs.append(text(value))
    return refs
