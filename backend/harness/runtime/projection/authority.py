from __future__ import annotations

from typing import Any

from .guards import compact, record, stable_id, text


PUBLIC_PROJECTION_AUTHORITY = "harness.public_projection"
PUBLIC_PROJECTION_CONTRACT_REVISION = "20260613-user-first"

VALID_OPS = {
    "body_append",
    "body_finalize",
    "item_upsert",
    "item_retire",
    "scope_retire",
    "commit_ack",
    "commit_failed",
    "turn_terminal",
}
VALID_SLOTS = {"body", "current_action", "pinned", "final_result", "status", "trace"}
VALID_SOURCES = {"model", "tool", "runtime", "system"}
VALID_VISIBILITY = {"visible_live", "visible_final", "pinned", "trace_only", "hidden"}
VALID_RETENTION = {"transient", "final", "pinned_until_resolved", "trace"}


def build_public_projection_frame(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    spec: dict[str, Any] | None = None,
    public_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    frame_spec = dict(spec or {})
    anchor = projection_anchor(payload)
    source_event_id = _source_event_id(payload)
    event_offset = _int_value(payload.get("event_offset") or payload.get("offset") or sequence)
    invalid_fields = _invalid_spec_fields(frame_spec)
    if invalid_fields:
        frame_spec = _protocol_diagnostic_frame_spec(
            public_event_type,
            frame_spec,
            invalid_fields=invalid_fields,
        )
    op = _required_value(frame_spec.get("op"), VALID_OPS)
    slot = _required_value(frame_spec.get("slot"), VALID_SLOTS)
    source_authority = _required_value(frame_spec.get("source_authority"), VALID_SOURCES)
    main_visibility = _required_value(frame_spec.get("main_visibility"), VALID_VISIBILITY)
    retention = _required_value(frame_spec.get("retention"), VALID_RETENTION)
    frame_id = text(frame_spec.get("frame_id")) or stable_id(
        "publicframe",
        public_event_type,
        source_event_id,
        anchor.get("turn_id"),
        anchor.get("task_run_id"),
        event_offset,
        op,
        slot,
    )
    frame = {
        "authority": PUBLIC_PROJECTION_AUTHORITY,
        "contract_revision": PUBLIC_PROJECTION_CONTRACT_REVISION,
        "frame_id": frame_id,
        "projection_id": frame_id,
        "source_event_id": source_event_id,
        "source_event_type": text(public_event_type),
        "sequence": int(sequence or payload.get("sequence") or event_offset or 0),
        "event_offset": event_offset,
        "created_at": payload.get("created_at") or payload.get("updated_at") or 0,
        "anchor": {
            **anchor,
            "session_id": text(session_id or anchor.get("session_id") or payload.get("session_id")),
        },
        "op": op,
        "slot": slot,
        "source_authority": source_authority,
        "main_visibility": main_visibility,
        "retention": retention,
    }
    for key in (
        "source_item_id",
        "tool_call_id",
        "permission_decision_id",
        "parent_tool_call_id",
        "pin_reason",
        "item_id",
        "title",
        "text",
        "detail",
        "state",
        "status_kind",
        "tool_name",
        "tool_lifecycle_id",
        "action_kind",
        "subject_label",
        "arguments_preview",
        "target",
        "collapsed",
    ):
        value = frame_spec.get(key)
        if value not in ("", None, [], {}):
            frame[key] = value
    for key in ("trace_refs", "artifact_refs"):
        value = frame_spec.get(key)
        if isinstance(value, list) and value:
            frame[key] = value
    commit = record(frame_spec.get("commit"))
    if commit:
        frame["commit"] = commit
    diagnostics = record(frame_spec.get("diagnostics"))
    if diagnostics:
        frame["diagnostics"] = diagnostics
    return compact(frame)


def projection_anchor(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
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
            ),
            "message_id": text(public_anchor.get("message_id") or public_anchor.get("anchor_message_id") or payload.get("message_ref")),
            "task_run_id": (
                text(public_anchor.get("task_run_id"))
                or text(payload.get("runtime_task_run_id"))
                or text(payload.get("task_run_id"))
                or text(task_run.get("task_run_id"))
            ),
            "run_id": text(public_anchor.get("run_id") or payload.get("runtime_run_id") or payload.get("run_id")),
            "turn_run_id": text(public_anchor.get("turn_run_id") or payload.get("turn_run_id") or active_turn.get("turn_run_id")),
        }
    )


def _source_event_id(data: dict[str, Any]) -> str:
    event = record(data.get("event"))
    return text(
        data.get("runtime_event_id")
        or data.get("event_id")
        or event.get("event_id")
        or data.get("frame_id")
    )


def _required_value(value: Any, allowed: set[str]) -> str:
    normalized = text(value)
    if normalized not in allowed:
        raise ValueError(f"invalid public projection frame field: {normalized}")
    return normalized


def _invalid_spec_fields(frame_spec: dict[str, Any]) -> dict[str, str]:
    invalid: dict[str, str] = {}
    for key, allowed in {
        "op": VALID_OPS,
        "slot": VALID_SLOTS,
        "source_authority": VALID_SOURCES,
        "main_visibility": VALID_VISIBILITY,
        "retention": VALID_RETENTION,
    }.items():
        value = text(frame_spec.get(key))
        if value not in allowed:
            invalid[key] = value
    return invalid


def _protocol_diagnostic_frame_spec(
    public_event_type: str,
    frame_spec: dict[str, Any],
    *,
    invalid_fields: dict[str, str],
) -> dict[str, Any]:
    return {
        "op": "item_upsert",
        "slot": "trace",
        "source_authority": "system",
        "main_visibility": "hidden",
        "retention": "trace",
        "item_id": stable_id("projection-invalid-spec", public_event_type, invalid_fields),
        "title": "公开投影协议诊断",
        "text": "公开投影协议诊断",
        "detail": "public_projection_frame spec 包含非法字段，已拒绝进入主视图。",
        "state": "failed",
        "diagnostics": {
            "code": "invalid_projection_frame_spec",
            "invalid_fields": dict(invalid_fields),
            "source_event_type": text(public_event_type),
            "original_op": text(frame_spec.get("op")),
            "original_slot": text(frame_spec.get("slot")),
        },
    }


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
