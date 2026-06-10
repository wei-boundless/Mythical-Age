from __future__ import annotations

from typing import Any

from .guards import compact, record, stable_id, text


PUBLIC_PROJECTION_AUTHORITY = "harness.public_projection"
PUBLIC_PROJECTION_CONTRACT_REVISION = "20260610-replacement"
VALID_SURFACES = {"control", "timeline", "diagnostics"}
VALID_SOURCES = {"model", "tool", "runtime", "system", "user"}


def build_public_projection_frame(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    items: list[dict[str, Any]] | None = None,
    task_projection: dict[str, Any] | None = None,
    public_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    projection = record(task_projection or payload.get("task_projection_delta") or payload.get("task_projection"))
    anchor = projection_anchor(payload, task_projection=projection)
    projected_items = [item for item in [_authorize_item(item) for item in list(items or [])] if item]
    source, surface = _frame_source_surface(public_event_type, payload, projected_items, task_projection=projection)
    projected_items = [item for item in projected_items if text(item.get("slot")) != "body"]
    frame = {
        "authority": PUBLIC_PROJECTION_AUTHORITY,
        "contract_revision": PUBLIC_PROJECTION_CONTRACT_REVISION,
        "projection_id": _projection_id(public_event_type, payload, anchor, sequence),
        "frame_id": _projection_id(public_event_type, payload, anchor, sequence),
        "sequence": int(sequence or payload.get("sequence") or 0),
        "event_offset": int(payload.get("event_offset") or payload.get("offset") or sequence or 0),
        "created_at": payload.get("created_at") or payload.get("updated_at") or 0,
        "session_id": text(session_id or payload.get("session_id")),
        "anchor": anchor,
        "source_authority": source,
        "source": source,
        "surface": surface,
        "lifecycle": _lifecycle(public_event_type, payload, items=projected_items),
        "items": projected_items,
    }
    terminal = _terminal(public_event_type, payload)
    if terminal:
        frame["terminal"] = terminal
    if projection:
        frame["task_projection"] = projection
    active_turn_update = _active_turn_update(payload, task_projection=projection)
    if active_turn_update:
        frame["active_turn_update"] = active_turn_update
    return compact(frame)


def projection_anchor(data: dict[str, Any], *, task_projection: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(data or {})
    projection = record(task_projection)
    public_anchor = record(payload.get("public_anchor"))
    active_turn = record(payload.get("active_turn"))
    task_run = record(payload.get("task_run"))
    return compact(
        {
            "session_id": text(public_anchor.get("session_id") or payload.get("session_id")),
            "turn_id": (
                text(public_anchor.get("turn_id"))
                or text(public_anchor.get("anchor_turn_id"))
                or text(active_turn.get("turn_id"))
                or text(payload.get("turn_id"))
                or text(payload.get("active_turn_id"))
                or text(projection.get("anchor_turn_id"))
                or text(projection.get("turn_id"))
            ),
            "message_id": text(public_anchor.get("message_id") or public_anchor.get("anchor_message_id") or projection.get("anchor_message_id")),
            "task_run_id": (
                text(public_anchor.get("task_run_id"))
                or text(projection.get("task_run_id"))
                or text(payload.get("runtime_task_run_id"))
                or text(payload.get("task_run_id"))
                or text(task_run.get("task_run_id"))
            ),
            "run_id": text(public_anchor.get("run_id") or payload.get("runtime_run_id") or payload.get("run_id")),
            "turn_run_id": text(public_anchor.get("turn_run_id") or payload.get("turn_run_id") or active_turn.get("turn_run_id")),
            "prompt_packet_ref": text(public_anchor.get("prompt_packet_ref") or payload.get("prompt_packet_ref")),
            "anchor_role": text(public_anchor.get("anchor_role")) or "assistant",
        }
    )


def _authorize_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item or {})
    surface = text(payload.get("surface"))
    source = text(payload.get("source_authority") or payload.get("source"))
    slot = text(payload.get("slot"))
    if surface not in VALID_SURFACES or source not in VALID_SOURCES:
        return {}
    if slot == "body" or surface == "assistant_body" or surface == "tool_window":
        return {}
    return compact({**payload, "surface": surface, "source_authority": source})


def _frame_source_surface(
    public_event_type: str,
    data: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    task_projection: dict[str, Any],
) -> tuple[str, str]:
    if any(text(item.get("surface")) == "control" for item in items):
        return "runtime", "control"
    if task_projection:
        return "runtime", "timeline"
    event_type = text(public_event_type)
    if event_type in {"turn_completed", "runtime_status", "active_task_steer_accepted"}:
        return "runtime", "control"
    return "runtime", "timeline"


def _lifecycle(public_event_type: str, data: dict[str, Any], *, items: list[dict[str, Any]]) -> str:
    event_type = text(public_event_type)
    if event_type == "turn_completed":
        status = text(data.get("status")).lower()
        if status == "failed":
            return "error"
        if status == "stopped":
            return "stopped"
        return "done"
    if event_type == "assistant_text_final":
        return "done"
    state = text(data.get("state") or data.get("status")).lower()
    if state in {"failed", "error", "blocked"}:
        return "error"
    if state in {"waiting", "queued", "paused", "waiting_executor", "waiting_approval", "waiting_safe_boundary"}:
        return "waiting"
    if any(text(item.get("state")) == "waiting" for item in items):
        return "waiting"
    if any(text(item.get("state")) == "error" for item in items):
        return "error"
    return "running"


def _terminal(public_event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if public_event_type != "turn_completed":
        return {}
    reason = text(data.get("terminal_reason") or data.get("reason") or data.get("code"))
    status = text(data.get("status")).lower()
    return compact({"event": public_event_type, "status": status, "visible": True, "reason": reason})


def _active_turn_update(data: dict[str, Any], *, task_projection: dict[str, Any]) -> dict[str, Any]:
    anchor = projection_anchor(data, task_projection=task_projection)
    state = text(record(data.get("active_turn")).get("state") or data.get("work_status") or task_projection.get("status"))
    reason = text(data.get("terminal_reason"))
    if reason == "task_executor_scheduled" and not state:
        state = "waiting_executor"
    if not anchor.get("turn_id") and not anchor.get("task_run_id"):
        return {}
    return compact({"turn_id": anchor.get("turn_id"), "task_run_id": anchor.get("task_run_id"), "state": state})


def _projection_id(public_event_type: str, data: dict[str, Any], anchor: dict[str, Any], sequence: int) -> str:
    return stable_id(
        "publicproj",
        public_event_type,
        data.get("runtime_event_id") or data.get("event_id"),
        anchor.get("turn_id"),
        anchor.get("task_run_id"),
        sequence,
    )
