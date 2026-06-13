from __future__ import annotations

import asyncio
import json

from api import runtime_monitor as runtime_monitor_api


def test_runtime_monitor_stream_snapshot_has_no_raw_runtime_event(monkeypatch) -> None:
    async def collect(_service, *, limit: int) -> dict:
        return {
            "authority": "runtime_monitor",
            "revision": f"rtmon:test:{limit}",
            "signals": [],
            "updated_at": 1,
        }

    monkeypatch.setattr(runtime_monitor_api, "_service", lambda: object())
    monkeypatch.setattr(runtime_monitor_api, "_collect_global_runtime_monitor", collect)

    response = asyncio.run(runtime_monitor_api.stream_runtime_monitor_events(_DisconnectAfter([False]), limit=5))
    first_block, second_block = asyncio.run(_stream_blocks(response.body_iterator, count=2))
    payload = _sse_json(second_block)

    assert _sse_event(first_block) == "runtime_monitor_heartbeat"
    assert _sse_event(second_block) == "runtime_monitor_snapshot"
    assert payload["source"] == "initial"
    assert payload["monitor"]["authority"] == "runtime_monitor"
    assert "runtime_event" not in payload
    assert "public_projection_envelope" not in json.dumps(payload, ensure_ascii=False)


def test_runtime_monitor_stream_sends_heartbeat_before_collecting_snapshot(monkeypatch) -> None:
    collect_called = False

    async def collect(_service, *, limit: int) -> dict:
        nonlocal collect_called
        collect_called = True
        return {"authority": "runtime_monitor", "revision": f"rtmon:test:{limit}", "signals": []}

    monkeypatch.setattr(runtime_monitor_api, "_service", lambda: object())
    monkeypatch.setattr(runtime_monitor_api, "_collect_global_runtime_monitor", collect)

    response = asyncio.run(runtime_monitor_api.stream_runtime_monitor_events(_DisconnectAfter([False]), limit=5))
    first_block = asyncio.run(_first_stream_block(response.body_iterator))

    assert _sse_event(first_block) == "runtime_monitor_heartbeat"
    assert _sse_json(first_block)["source"] == "connected"
    assert collect_called is False


class _DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


class _DisconnectAfter:
    def __init__(self, states: list[bool]) -> None:
        self.states = list(states)

    async def is_disconnected(self) -> bool:
        if self.states:
            return self.states.pop(0)
        return True


async def _first_stream_block(iterator) -> str:
    return await anext(iterator)


async def _stream_blocks(iterator, *, count: int) -> list[str]:
    return [await anext(iterator) for _ in range(count)]


def _sse_event(block: str) -> str:
    for line in block.splitlines():
        if line.startswith("event: "):
            return line.removeprefix("event: ")
    return ""


def _sse_json(block: str) -> dict:
    data_lines = [
        line.removeprefix("data: ")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    return json.loads("\n".join(data_lines))
