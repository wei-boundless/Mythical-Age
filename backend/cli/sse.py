from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable


MAX_STREAM_BUFFER_CHARS = 1024 * 1024
TERMINAL_STREAM_EVENTS = {"done", "error", "stopped", "turn_completed"}


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    event: str
    data: dict[str, Any]
    event_id: str = ""


def parse_sse_block(block: str) -> ServerSentEvent | None:
    event = "message"
    event_id = ""
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("id:"):
            event_id = line[3:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    payload = json.loads("\n".join(data_lines))
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return ServerSentEvent(event=event, data=payload, event_id=event_id)


def _find_boundary(buffer: str) -> tuple[int, int] | None:
    candidates = [
        (index, len(marker))
        for marker in ("\r\n\r\n", "\n\n", "\r\r")
        if (index := buffer.find(marker)) >= 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])


class SSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[ServerSentEvent]:
        self._buffer += text
        if len(self._buffer) > MAX_STREAM_BUFFER_CHARS:
            raise ValueError("SSE buffer exceeded 1MB without a complete event boundary.")

        events: list[ServerSentEvent] = []
        boundary = _find_boundary(self._buffer)
        while boundary is not None:
            index, length = boundary
            block = self._buffer[:index]
            self._buffer = self._buffer[index + length :]
            event = parse_sse_block(block)
            if event is not None:
                events.append(event)
            boundary = _find_boundary(self._buffer)
        return events

    def flush(self) -> list[ServerSentEvent]:
        if not self._buffer.strip():
            self._buffer = ""
            return []
        block = self._buffer
        self._buffer = ""
        event = parse_sse_block(block)
        return [event] if event is not None else []


def decode_sse_text_chunks(chunks: Iterable[str]) -> list[ServerSentEvent]:
    decoder = SSEDecoder()
    events: list[ServerSentEvent] = []
    for chunk in chunks:
        events.extend(decoder.feed(chunk))
    events.extend(decoder.flush())
    return events



