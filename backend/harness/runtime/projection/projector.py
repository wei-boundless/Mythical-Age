from __future__ import annotations

from typing import Any

from .authority import build_public_projection_frame
from .guards import record, stable_id, text
from .items import control_item, status_item
from runtime.output_stream.public_contract import LOSSLESS_PUBLIC_EVENTS, TURN_COMPLETED_EVENT


TYPED_ASSISTANT_STREAM_EVENTS = {
    "assistant_text_delta",
    "assistant_text_final",
    "assistant_stream_repair",
}
DEPRECATED_NON_CONTRACT_EVENTS = {"assistant_text", "answer_candidate", "done"}
LIVE_TOOL_LEGACY_EVENTS = {
    "model_action_admission",
    "turn_tool_observation_recorded",
    "task_tool_observation_recorded",
    "tool_observation",
    "tool_item_started",
    "tool_item_completed",
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
    payload.setdefault("sequence", int(sequence or payload.get("sequence") or 0))
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
    if (
        not event_type
        or event_type in TYPED_ASSISTANT_STREAM_EVENTS
        or event_type in LOSSLESS_PUBLIC_EVENTS
        or event_type in DEPRECATED_NON_CONTRACT_EVENTS
        or event_type in LIVE_TOOL_LEGACY_EVENTS
    ):
        return []
    if event_type == "runtime_step_summary":
        return _runtime_step_summary_items(data)
    if event_type == "runtime_status":
        return []
    if event_type == "active_task_steer_accepted":
        return []
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
    if event_type == TURN_COMPLETED_EVENT:
        return []
    return []


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
        return []
    feedback = current_judgment or data.get("agent_brief_output")
    if feedback:
        item = status_item(
            item_id=_item_id("step-feedback", data),
            title=feedback,
            detail=next_action,
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
