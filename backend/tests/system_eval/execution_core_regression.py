from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.system_eval.execution_core import collect_sse_events, extract_langsmith_trace_reference, final_text


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    def iter_lines(self):
        for line in self._lines:
            yield line


def test_collect_sse_events_parses_stream_and_done_payload() -> None:
    response = _FakeResponse(
        [
            "event: token",
            'data: {"content":"hello "}',
            "",
            "event: done",
            'data: {"content":"hello world"}',
            "",
        ]
    )

    events, timing = collect_sse_events(response, request_start=0.0, request_start_ts="2026-04-20T12:00:00")

    assert [item["event"] for item in events] == ["token", "done"]
    assert final_text(events) == "hello world"
    assert timing.event_count == 2
    assert timing.terminal_event == "done"


def test_extract_langsmith_trace_reference_reads_debug_event() -> None:
    events = [
        {"event": "token", "data": {"content": "hello"}},
        {
            "event": "debug",
            "data": {
                "kind": "langsmith_trace",
                "trace_id": "trace-123",
                "trace_url": "https://langsmith.local/trace-123",
            },
        },
    ]

    trace_ref = extract_langsmith_trace_reference(events)

    assert trace_ref["trace_id"] == "trace-123"
    assert trace_ref["trace_available"] is True
    assert trace_ref["trace_source"] == "langsmith"


def test_extract_langsmith_trace_reference_reads_local_trace_event() -> None:
    events = [
        {
            "event": "debug",
            "data": {
                "kind": "local_trace",
                "trace_source": "local",
                "trace_id": "local-123",
                "trace_url": "D:/AI应用/langchain-agent/output/local_traces/local-123.json",
            },
        },
    ]

    trace_ref = extract_langsmith_trace_reference(events)

    assert trace_ref["trace_id"] == "local-123"
    assert trace_ref["trace_available"] is True
    assert trace_ref["trace_source"] == "local"
