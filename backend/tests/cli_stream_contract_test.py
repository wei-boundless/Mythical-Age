from __future__ import annotations

import json
from io import StringIO
from typing import Any

from backend.cli.client import AgentCliClient
from backend.cli.main import _render_stream_event
from backend.cli.sse import ServerSentEvent


class _FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.readline_count = 0

    def read(self, _size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def readline(self) -> bytes:
        self.readline_count += 1
        if not self._chunks:
            return b""
        chunk = self._chunks[0]
        newline_index = chunk.find(b"\n")
        if newline_index < 0:
            self._chunks.pop(0)
            return chunk
        line = chunk[: newline_index + 1]
        rest = chunk[newline_index + 1 :]
        if rest:
            self._chunks[0] = rest
        else:
            self._chunks.pop(0)
        return line


def test_cli_client_accepts_turn_completed_as_terminal_event() -> None:
    calls: list[str] = []
    posted_payloads: list[dict[str, Any]] = []
    replay_payload = {
        "stream_run_id": "strun:test",
        "event_log_id": "chatrun:test",
        "after_offset": -1,
        "latest_event_offset": 2,
        "terminal": True,
        "events": [
            {
                "type": "event",
                "event_id": "strun:test:chatrun:test:0",
                "event_offset": 0,
                "public_event_type": "assistant_text_delta",
                "terminal": False,
                "data": {"content": "你好", "event_offset": 0},
            },
            {
                "type": "event",
                "event_id": "strun:test:chatrun:test:1",
                "event_offset": 1,
                "public_event_type": "assistant_text_final",
                "terminal": False,
                "data": {"content": "你好世界", "event_offset": 1},
            },
            {
                "type": "event",
                "event_id": "strun:test:chatrun:test:2",
                "event_offset": 2,
                "public_event_type": "turn_completed",
                "terminal": True,
                "data": {"status": "completed", "event_offset": 2},
            },
        ],
        "authority": "runtime.stream_replay",
    }

    def opener(request, timeout=None):  # noqa: ANN001, ANN202
        url = str(request.full_url)
        calls.append(url)
        if url.endswith("/chat/runs"):
            posted_payloads.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse([json.dumps({"stream_run_id": "strun:test"}).encode("utf-8")])
        return _FakeResponse([json.dumps(replay_payload).encode("utf-8")])

    client = AgentCliClient(api_base="http://127.0.0.1:8003/api", opener=opener)

    events = list(client.stream_chat(session_id="session:test", message="hi"))

    assert [event.event for event in events] == [
        "assistant_text_delta",
        "assistant_text_final",
        "turn_completed",
    ]
    assert calls[-1].endswith("/chat/runs/strun%3Atest/events/replay?after_offset=-1&limit=500")
    assert posted_payloads[-1]["model_selection"]["stream_policy"] == {
        "enabled": True,
        "emit_assistant_text_delta": True,
        "upstream_reconnect_enabled": True,
        "partial_stream_recovery": "continue_from_visible_prefix",
        "chunk_strategy": "adaptive_buffer",
        "first_flush_delay_ms": 70,
        "target_buffer_delay_ms": 150,
        "adaptive_min_buffer_delay_ms": 80,
        "adaptive_max_buffer_delay_ms": 240,
        "release_tick_ms": 16,
        "max_buffer_delay_ms": 320,
        "max_flush_interval_ms": 80,
        "max_pending_utf8_bytes": 1536,
        "max_release_utf8_bytes": 192,
        "max_pending_line_count": 1,
        "min_event_interval_ms": 16,
        "event_budget_per_second": 45,
        "source": "backend.cli.chat_stream_default",
    }


def test_cli_renderer_does_not_duplicate_assistant_text_final_after_deltas() -> None:
    stdout = StringIO()
    stderr = StringIO()
    state: dict[str, Any] = {}

    assert _render_stream_event(
        ServerSentEvent("assistant_text_delta", {"content": "你好"}),
        stdout=stdout,
        stderr=stderr,
        verbose=False,
        state=state,
    ) == ""
    assert _render_stream_event(
        ServerSentEvent("assistant_text_final", {"content": "你好世界"}),
        stdout=stdout,
        stderr=stderr,
        verbose=False,
        state=state,
    ) == ""
    assert _render_stream_event(
        ServerSentEvent("turn_completed", {"status": "completed"}),
        stdout=stdout,
        stderr=stderr,
        verbose=False,
        state=state,
    ) == "done"

    assert stdout.getvalue() == "你好世界\n"
    assert stderr.getvalue() == ""
