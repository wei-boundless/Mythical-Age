from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .event_log import RuntimeEventLog
from .events import RuntimeEvent
from .runtime_run_registry import RuntimeRun
from runtime.output_stream.public_contract import is_terminal_public_event


PUBLIC_STREAM_EVENT_TYPE = "chat_stream_event"


@dataclass(frozen=True, slots=True)
class RuntimeStreamCursor:
    stream_run_id: str
    event_log_id: str
    last_event_offset: int
    last_event_id: str = ""
    authority: str = "runtime.stream_cursor"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_run_id": self.stream_run_id,
            "event_log_id": self.event_log_id,
            "last_event_offset": self.last_event_offset,
            "last_event_id": self.last_event_id,
            "authority": self.authority,
        }


class RuntimeStreamReplayService:
    def __init__(self, event_log: RuntimeEventLog) -> None:
        self.event_log = event_log

    def append_public_event(
        self,
        run: RuntimeRun,
        *,
        public_event_type: str,
        data: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        event_name = str(public_event_type or "message").strip() or "message"
        payload = {
            "stream_run_id": run.stream_run_id,
            "public_event_type": event_name,
            "data": dict(data or {}),
            "terminal": is_terminal_public_event(event_name),
        }
        return self.event_log.append(
            run.event_log_id,
            PUBLIC_STREAM_EVENT_TYPE,  # type: ignore[arg-type]
            payload=payload,
            refs={"stream_run_ref": run.stream_run_id, "root_request_ref": run.root_request_ref},
        )

    def list_public_events_after(self, run: RuntimeRun, *, after_offset: int = -1) -> list[RuntimeEvent]:
        return [
            event
            for event in self.event_log.list_events(run.event_log_id)
            if event.offset > int(after_offset)
            and str(event.event_type) == PUBLIC_STREAM_EVENT_TYPE
        ]

    def list_public_events(self, run: RuntimeRun) -> list[RuntimeEvent]:
        return [
            event
            for event in self.event_log.list_events(run.event_log_id)
            if str(event.event_type) == PUBLIC_STREAM_EVENT_TYPE
        ]

    def list_public_event_records(self, run: RuntimeRun) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for event in self.list_public_events(run):
            payload = dict(event.payload or {})
            data = dict(payload.get("data") or {})
            data = _data_with_sanitized_public_projection_frame(data)
            records.append(
                {
                    "stream_run_id": run.stream_run_id,
                    "event_log_id": run.event_log_id,
                    "event_id": event.event_id,
                    "event_offset": event.offset,
                    "created_at": event.created_at,
                    "public_event_type": str(payload.get("public_event_type") or "message").strip() or "message",
                    "terminal": bool(payload.get("terminal") is True),
                    "data": data,
                    "public_projection_frame": dict(data.get("public_projection_frame") or {})
                    if isinstance(data.get("public_projection_frame"), dict)
                    else {},
                }
            )
        return sorted(records, key=lambda item: int(item.get("event_offset") or 0))

    def to_public_sse(self, run: RuntimeRun, event: RuntimeEvent, *, retry_ms: int = 1500) -> str:
        payload = dict(event.payload or {})
        event_name = str(payload.get("public_event_type") or "message").strip() or "message"
        data = dict(payload.get("data") or {})
        data = _data_with_sanitized_public_projection_frame(data)
        data.update(
            {
                "stream_run_id": run.stream_run_id,
                "event_log_id": run.event_log_id,
                "event_offset": event.offset,
                "runtime_event_id": event.event_id,
            }
        )
        return format_sse(
            event_name,
            data,
            event_id=stream_event_id(run.stream_run_id, run.event_log_id, event.offset),
            retry_ms=retry_ms,
        )

    def is_terminal_event(self, event: RuntimeEvent) -> bool:
        payload = dict(event.payload or {})
        return bool(payload.get("terminal") is True) or is_terminal_public_event(str(payload.get("public_event_type") or ""))


def stream_event_id(stream_run_id: str, event_log_id: str, offset: int) -> str:
    return f"{stream_run_id}:{event_log_id}:{int(offset)}"


def sanitized_public_projection_frame(frame: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(frame or {})
    if not _is_legacy_protocol_repair_public_frame(payload):
        return payload
    sanitized = {
        key: value
        for key, value in payload.items()
        if key not in {"detail", "public_summary", "status_kind", "text", "title"}
    }
    sanitized.update(
        {
            "op": "item_upsert",
            "slot": "trace",
            "source_authority": "runtime",
            "main_visibility": "hidden",
            "retention": "trace",
        }
    )
    return sanitized


def _data_with_sanitized_public_projection_frame(data: dict[str, Any]) -> dict[str, Any]:
    frame = data.get("public_projection_frame")
    if not isinstance(frame, dict):
        return data
    sanitized = sanitized_public_projection_frame(frame)
    if sanitized == frame:
        return data
    return {**data, "public_projection_frame": sanitized}


def _is_legacy_protocol_repair_public_frame(frame: dict[str, Any]) -> bool:
    status_kind = str(frame.get("status_kind") or "").strip().lower()
    if status_kind == "protocol_repair_status":
        return True
    item_id = str(frame.get("item_id") or "").strip().lower()
    return item_id.startswith("protocol-repair")


def parse_stream_event_id(value: str, *, expected_stream_run_id: str = "", expected_event_log_id: str = "") -> RuntimeStreamCursor | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    prefix = f"{expected_stream_run_id}:{expected_event_log_id}:" if expected_stream_run_id and expected_event_log_id else ""
    if prefix and raw.startswith(prefix):
        tail = raw[len(prefix):]
        if tail.isdigit():
            return RuntimeStreamCursor(
                stream_run_id=expected_stream_run_id,
                event_log_id=expected_event_log_id,
                last_event_offset=int(tail),
                last_event_id=raw,
            )
    parts = raw.rsplit(":", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return RuntimeStreamCursor(
        stream_run_id=expected_stream_run_id,
        event_log_id=expected_event_log_id,
        last_event_offset=int(parts[1]),
        last_event_id=raw,
    )


def format_sse(event: str, data: dict[str, Any], *, event_id: str = "", retry_ms: int = 0) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    if retry_ms > 0:
        lines.append(f"retry: {int(retry_ms)}")
    lines.append(f"event: {str(event or 'message').strip() or 'message'}")
    encoded = json.dumps(dict(data or {}), ensure_ascii=False)
    for line in encoded.splitlines() or ["{}"]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"
