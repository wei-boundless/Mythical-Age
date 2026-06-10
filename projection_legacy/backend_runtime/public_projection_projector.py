from __future__ import annotations

from typing import Any

from harness.runtime.public_projection_envelope import build_public_projection_envelope
from harness.runtime.public_timeline_stream import project_public_timeline_delta


_TYPED_ASSISTANT_STREAM_EVENTS = {
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
    include_legacy_timeline_delta: bool = True,
) -> dict[str, Any]:
    payload = dict(data or {})
    if public_anchor:
        payload["public_anchor"] = dict(public_anchor)
    projection = _record(task_projection or payload.get("task_projection_delta") or payload.get("task_projection"))
    raw_items = _projection_items_for_event(public_event_type, payload)
    envelope = build_public_projection_envelope(
        public_event_type,
        payload,
        session_id=session_id,
        sequence=sequence,
        public_timeline_delta=raw_items,
        task_projection=projection,
    )
    envelope_items = [
        dict(item)
        for item in list(envelope.get("items") or [])
        if isinstance(item, dict)
    ]
    result = {"public_projection_envelope": envelope}
    if include_legacy_timeline_delta and envelope_items:
        result["public_timeline_delta"] = envelope_items
    return result


def attach_public_projection_event(
    public_event_type: str,
    data: dict[str, Any],
    *,
    session_id: str = "",
    sequence: int = 0,
    public_anchor: dict[str, Any] | None = None,
    task_projection: dict[str, Any] | None = None,
    include_legacy_timeline_delta: bool = True,
) -> None:
    projection = project_public_projection_event(
        public_event_type,
        data,
        session_id=session_id,
        sequence=sequence,
        public_anchor=public_anchor,
        task_projection=task_projection,
        include_legacy_timeline_delta=include_legacy_timeline_delta,
    )
    data["public_projection_envelope"] = projection["public_projection_envelope"]
    if "public_timeline_delta" in projection:
        data["public_timeline_delta"] = projection["public_timeline_delta"]
    else:
        data.pop("public_timeline_delta", None)


def _projection_items_for_event(public_event_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = str(public_event_type or "").strip()
    if not event_type or event_type in _TYPED_ASSISTANT_STREAM_EVENTS:
        return []
    return project_public_timeline_delta(event_type, data)


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
