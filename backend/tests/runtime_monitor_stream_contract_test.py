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

    response = asyncio.run(runtime_monitor_api.stream_runtime_monitor_events(_DisconnectedRequest(), limit=5))
    first_block = asyncio.run(_first_stream_block(response.body_iterator))
    payload = _sse_json(first_block)

    assert payload["source"] == "initial"
    assert payload["monitor"]["authority"] == "runtime_monitor"
    assert "runtime_event" not in payload
    assert "public_projection_envelope" not in json.dumps(payload, ensure_ascii=False)


class _DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


async def _first_stream_block(iterator) -> str:
    return await anext(iterator)


def _sse_json(block: str) -> dict:
    data_lines = [
        line.removeprefix("data: ")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    return json.loads("\n".join(data_lines))
