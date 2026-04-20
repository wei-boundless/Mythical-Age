from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from harness.contracts import TimingSnapshot


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def collect_sse_events(
    response: Any,
    *,
    request_start: float,
    request_start_ts: str | None = None,
) -> tuple[list[dict[str, Any]], TimingSnapshot]:
    timing = TimingSnapshot(started_at=request_start_ts or iso_now())
    events: list[dict[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = "message"
            data_lines = []
            return
        delta_ms = round((time.perf_counter() - request_start) * 1000.0, 2)
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            payload = {"raw": "\n".join(data_lines)}
        events.append({"event": event_name, "data": payload, "ts_ms": delta_ms})
        if timing.first_event_ms is None:
            timing.first_event_ms = delta_ms
        if event_name in {"token", "message"} and timing.first_token_ms is None:
            content = str(payload.get("content", "") or "")
            if content.strip():
                timing.first_token_ms = delta_ms
        if event_name in {"done", "error"}:
            timing.done_ms = delta_ms
            timing.terminal_event = event_name
        event_name = "message"
        data_lines = []

    for raw in response.iter_lines():
        line = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if line == "":
            flush()
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    flush()
    timing.ended_at = iso_now()
    timing.duration_ms = round((time.perf_counter() - request_start) * 1000.0, 2)
    timing.event_count = len(events)
    return events, timing


def final_text(events: list[dict[str, Any]]) -> str:
    for item in reversed(events):
        if item.get("event") == "done":
            return str(dict(item.get("data") or {}).get("content", "") or "").strip()
    return "".join(
        str(dict(item.get("data") or {}).get("content", "") or "")
        for item in events
        if item.get("event") in {"token", "message"}
    ).strip()


def extract_langsmith_trace_reference(events: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(events):
        if str(item.get("event", "") or "") != "debug":
            continue
        payload = dict(item.get("data") or {})
        kind = str(payload.get("kind", "") or "")
        if kind not in {"langsmith_trace", "local_trace"}:
            continue
        trace_id = str(payload.get("trace_id", "") or "")
        trace_url = str(payload.get("trace_url", "") or "")
        trace_source = str(payload.get("trace_source", "") or "")
        if not trace_source:
            trace_source = "langsmith" if kind == "langsmith_trace" else "local"
        return {
            "trace_id": trace_id,
            "trace_url": trace_url,
            "trace_available": bool(trace_id or trace_url),
            "trace_source": trace_source,
        }
    return {
        "trace_id": "",
        "trace_url": "",
        "trace_available": False,
        "trace_source": "",
    }


def has_event(events: list[dict[str, Any]], event_name: str) -> bool:
    return any(item.get("event") == event_name for item in events)
