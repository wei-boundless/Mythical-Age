from __future__ import annotations

from hashlib import sha1
from typing import Any


PUBLIC_PROJECTION_ENVELOPE_AUTHORITY = "harness.public_projection.v1"

_SYSTEM_CHANNELS = {"active_work_control", "ask_user", "blocked", "runtime_control", "task_control"}
_MODEL_BODY_CHANNELS = {"", "conversation", "progress_feedback", "stage_feedback"}
_VALID_ITEM_SLOTS = {"body", "timeline", "tool", "status", "task", "control"}


def build_public_projection_envelope(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_timeline_delta: list[dict[str, Any]] | None = None,
    task_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_type = _text(public_event_type) or "message"
    payload = dict(data or {})
    source_items = public_timeline_delta if public_timeline_delta is not None else payload.get("public_timeline_delta")
    items = [dict(item) for item in list(source_items or []) if isinstance(item, dict)]
    projection = _record(task_projection or payload.get("task_projection_delta") or payload.get("task_projection"))
    anchor = _anchor(payload, projection=projection)
    source_authority, surface = _source_and_surface(event_type, payload, projection=projection)
    terminal = _terminal(event_type, payload)
    if terminal.get("visible") is False:
        items = []
    projected_items = [_projection_item(item) for item in items]
    projected_items = [item for item in projected_items if item]
    has_model_body_item = any(_is_model_body_projection_item(item) for item in projected_items)
    if event_type == "model_action_admission" and has_model_body_item:
        source_authority, surface = "model", "assistant_body"
    if source_authority != "model" or surface != "assistant_body":
        projected_items = [item for item in projected_items if _text(item.get("slot")) != "body"]
    envelope = {
        "authority": PUBLIC_PROJECTION_ENVELOPE_AUTHORITY,
        "projection_id": _projection_id(event_type, payload, anchor, sequence),
        "sequence": int(sequence or 0),
        "created_at": payload.get("created_at") or payload.get("updated_at") or 0,
        "session_id": _text(session_id or payload.get("session_id")),
        "anchor": anchor,
        "lifecycle": _lifecycle(event_type, payload, items=projected_items, terminal=terminal),
        "source_authority": source_authority,
        "surface": surface,
        "items": projected_items,
    }
    if terminal:
        envelope["terminal"] = terminal
    if projection:
        envelope["task_projection"] = projection
    active_turn_update = _active_turn_update(payload, projection=projection)
    if active_turn_update:
        envelope["active_turn_update"] = active_turn_update
    return _compact(envelope)


def _source_and_surface(event_type: str, data: dict[str, Any], *, projection: dict[str, Any]) -> tuple[str, str]:
    answer_channel = _text(data.get("answer_channel")).lower()
    if projection:
        return "runtime", "task_projection"
    if event_type == "runtime_status":
        return "system", "status_bar"
    if event_type == "model_action_admission":
        action_type = _model_action_type(data)
        if action_type == "tool_call":
            return "tool", "tool_window"
        if action_type in {"active_work_control", "ask_user", "block", "request_task_run"}:
            return "system", "control"
        return "model", "assistant_body"
    if event_type in {"turn_tool_observation_recorded", "task_tool_observation_recorded", "tool_observation"}:
        return "tool", "tool_window"
    if event_type in {"assistant_text", "assistant_text_delta", "assistant_text_final", "assistant_stream_repair", "answer_candidate", "done"}:
        if answer_channel in _SYSTEM_CHANNELS:
            return "system", "control"
        if answer_channel in _MODEL_BODY_CHANNELS:
            return "model", "assistant_body"
    if event_type in {"active_task_steer_accepted"}:
        return "system", "status_bar"
    if event_type in {"error", "stopped"}:
        return "system", "status_bar"
    return "runtime", "timeline"


def _terminal(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_type not in {"done", "error", "stopped"}:
        return {}
    reason = _text(data.get("terminal_reason") or data.get("reason") or data.get("code"))
    answer_channel = _text(data.get("answer_channel")).lower()
    handoff = reason == "task_executor_scheduled" or answer_channel == "task_control"
    return _compact(
        {
            "event": event_type,
            "visible": False if handoff else True,
            "reason": reason,
        }
    )


def _lifecycle(event_type: str, data: dict[str, Any], *, items: list[dict[str, Any]], terminal: dict[str, Any]) -> str:
    if terminal:
        event = _text(terminal.get("event"))
        if event == "error":
            return "error"
        if event == "stopped":
            return "stopped"
        return "done"
    if event_type == "assistant_text_final":
        return "done"
    state = _text(data.get("state") or data.get("status")).lower()
    if state in {"error", "failed", "blocked"}:
        return "error"
    if state in {"stopped", "aborted", "cancelled", "canceled"}:
        return "stopped"
    if state in {"waiting", "queued", "paused", "waiting_executor", "waiting_approval"}:
        return "waiting"
    for item in reversed(items):
        item_state = _text(item.get("state")).lower()
        if item_state in {"error", "failed", "blocked"}:
            return "error"
        if item_state in {"waiting", "queued", "paused"}:
            return "waiting"
    return "running"


def _anchor(data: dict[str, Any], *, projection: dict[str, Any]) -> dict[str, Any]:
    active_turn = _record(data.get("active_turn"))
    task_run = _record(data.get("task_run"))
    public_anchor = _record(data.get("public_anchor"))
    return _compact(
        {
            "turn_id": (
                _text(public_anchor.get("turn_id"))
                or _text(public_anchor.get("anchor_turn_id"))
                or _text(active_turn.get("turn_id"))
                or _text(data.get("active_turn_id"))
                or _text(projection.get("anchor_turn_id"))
                or _text(projection.get("turn_id"))
            ),
            "message_id": _text(public_anchor.get("message_id") or public_anchor.get("anchor_message_id") or projection.get("anchor_message_id")),
            "task_run_id": (
                _text(public_anchor.get("task_run_id"))
                or _text(projection.get("task_run_id"))
                or _text(data.get("runtime_task_run_id"))
                or _text(data.get("task_run_id"))
                or _text(task_run.get("task_run_id"))
            ),
            "run_id": _text(public_anchor.get("run_id") or data.get("runtime_run_id") or data.get("run_id")),
            "turn_run_id": _text(public_anchor.get("turn_run_id") or data.get("turn_run_id") or active_turn.get("turn_run_id")),
            "anchor_role": _text(public_anchor.get("anchor_role")) or "assistant",
        }
    )


def _active_turn_update(data: dict[str, Any], *, projection: dict[str, Any]) -> dict[str, Any]:
    active_turn = _record(data.get("active_turn"))
    public_anchor = _record(data.get("public_anchor"))
    turn_id = _text(
        public_anchor.get("turn_id")
        or public_anchor.get("anchor_turn_id")
        or active_turn.get("turn_id")
        or data.get("active_turn_id")
        or projection.get("anchor_turn_id")
        or projection.get("turn_id")
    )
    task_run_id = _text(
        public_anchor.get("task_run_id")
        or projection.get("task_run_id")
        or data.get("runtime_task_run_id")
        or data.get("task_run_id")
        or active_turn.get("bound_task_run_id")
        or active_turn.get("task_run_id")
    )
    if not turn_id and not task_run_id:
        return {}
    state = _text(active_turn.get("state") or data.get("work_status") or projection.get("status"))
    reason = _text(data.get("terminal_reason"))
    if reason == "task_executor_scheduled" and not state:
        state = "waiting_executor"
    return _compact({"turn_id": turn_id, "task_run_id": task_run_id, "state": state})


def _projection_item(item: dict[str, Any]) -> dict[str, Any]:
    slot = _text(item.get("slot")).lower()
    surface = _text(item.get("surface"))
    source_authority = _text(item.get("source_authority"))
    if slot not in _VALID_ITEM_SLOTS or not surface or not source_authority:
        return {}
    if slot == "body" and (source_authority != "model" or surface != "assistant_body"):
        return {}
    return _compact({**item, "slot": slot, "surface": surface, "source_authority": source_authority})


def _is_model_body_projection_item(item: dict[str, Any]) -> bool:
    return (
        _text(item.get("slot")) == "body"
        and _text(item.get("source_authority")) == "model"
        and _text(item.get("surface")) == "assistant_body"
    )


def _model_action_type(data: dict[str, Any]) -> str:
    public_kind = _text(_record(data.get("public_action")).get("kind")).lower()
    if public_kind:
        return {
            "tool": "tool_call",
            "task": "request_task_run",
            "reply": "respond",
            "question": "ask_user",
            "blocked": "block",
            "control": "active_work_control",
        }.get(public_kind, "")
    event = _record(data.get("event"))
    payload = _record(event.get("payload"))
    request = _record(payload.get("model_action_request")) or _record(data.get("model_action_request"))
    return _text(request.get("action_type")).lower()


def _projection_id(event_type: str, data: dict[str, Any], anchor: dict[str, Any], sequence: int) -> str:
    seed = "|".join(
        [
            event_type,
            _text(data.get("runtime_event_id") or data.get("event_id")),
            _text(anchor.get("turn_id")),
            _text(anchor.get("task_run_id")),
            str(sequence or 0),
        ]
    )
    return f"publicproj:{sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
