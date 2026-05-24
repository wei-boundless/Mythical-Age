from __future__ import annotations

import json
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from health_system.maintenance.harness.contracts import RunContext, TimingSnapshot


class SseEventCollector:
    def __init__(
        self,
        *,
        request_start: float,
        request_start_ts: str | None = None,
        on_event: Callable[[dict[str, Any], list[dict[str, Any]], TimingSnapshot], None] | None = None,
    ) -> None:
        self.timing = TimingSnapshot(started_at=request_start_ts or iso_now())
        self.events: list[dict[str, Any]] = []
        self._request_start = request_start
        self._on_event = on_event
        self._event_name = "message"
        self._data_lines: list[str] = []

    def consume_line(self, raw: Any) -> None:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if line == "":
            self.flush()
            return
        if line.startswith("event:"):
            self._event_name = line[6:].strip()
        elif line.startswith("data:"):
            self._data_lines.append(line[5:].strip())

    def finish(self) -> tuple[list[dict[str, Any]], TimingSnapshot]:
        self.flush()
        self.timing.ended_at = iso_now()
        self.timing.duration_ms = round((time.perf_counter() - self._request_start) * 1000.0, 2)
        self.timing.event_count = len(self.events)
        return self.events, self.timing

    def flush(self) -> None:
        if not self._data_lines:
            self._event_name = "message"
            self._data_lines = []
            return
        delta_ms = round((time.perf_counter() - self._request_start) * 1000.0, 2)
        try:
            payload = json.loads("\n".join(self._data_lines))
        except json.JSONDecodeError:
            payload = {"raw": "\n".join(self._data_lines)}
        event = {"event": self._event_name, "data": payload, "ts_ms": delta_ms}
        self.events.append(event)
        if self.timing.first_event_ms is None:
            self.timing.first_event_ms = delta_ms
        if self._event_name in {"token", "message"} and self.timing.first_token_ms is None:
            content = str(payload.get("content", "") or "")
            if content.strip():
                self.timing.first_token_ms = delta_ms
        if self._event_name in {"done", "error"}:
            self.timing.done_ms = delta_ms
            self.timing.terminal_event = self._event_name
        if self._on_event is not None:
            self._on_event(event, self.events, self.timing)
        self._event_name = "message"
        self._data_lines = []


def iso_now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def slug(value: str) -> str:
    parts = []
    for char in value:
        if char.isalnum():
            parts.append(char.lower())
        else:
            parts.append("-")
    normalized = "".join(parts).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized or "artifact"


def collect_sse_events(
    response: Any,
    *,
    request_start: float,
    request_start_ts: str | None = None,
    on_event: Callable[[dict[str, Any], list[dict[str, Any]], TimingSnapshot], None] | None = None,
) -> tuple[list[dict[str, Any]], TimingSnapshot]:
    collector = SseEventCollector(
        request_start=request_start,
        request_start_ts=request_start_ts,
        on_event=on_event,
    )
    for raw in response.iter_lines():
        collector.consume_line(raw)
    return collector.finish()


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


def latest_event_payload(events: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    for item in reversed(events):
        if str(item.get("event") or "") != event_name:
            continue
        data = item.get("data")
        return dict(data) if isinstance(data, dict) else {}
    return {}


def orchestration_diff_mismatches(diff: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for item in list(diff.get("items") or []):
        if not isinstance(item, dict) or str(item.get("status") or "") != "mismatch":
            continue
        field = str(item.get("field") or "unknown")
        expected = item.get("expected")
        actual = item.get("actual")
        reason = str(item.get("reason") or "")
        suffix = f" / {reason}" if reason else ""
        mismatches.append(f"{field}: expected={expected!r}, actual={actual!r}{suffix}")
    return mismatches


def build_run_context(
    *,
    profile: str,
    output_dir: Path,
    repo_root: Path,
    backend_root: Path,
    frontend_root: Path,
    settings: Any,
    langsmith_enabled: bool,
    trace_backend: str,
    trace_enabled: bool,
    mode: str = "inprocess",
) -> RunContext:
    return RunContext(
        run_id=output_dir.name,
        profile=profile,
        mode=mode,
        repo_root=str(repo_root),
        backend_root=str(backend_root),
        frontend_root=str(frontend_root),
        output_dir=str(output_dir),
        generated_at=iso_now(),
        python_version=platform.python_version(),
        llm_provider=str(getattr(settings, "llm_provider", "") or ""),
        llm_model=str(getattr(settings, "llm_model", "") or ""),
        langsmith_enabled=langsmith_enabled,
        trace_backend=trace_backend,
        trace_enabled=trace_enabled,
    )
