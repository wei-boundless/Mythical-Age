from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from api import runtime_monitor as runtime_monitor_api
from runtime.file_change_signals import publish_file_change_record
from runtime.shared.event_log import RuntimeEventLog


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


def test_runtime_monitor_snapshot_coalesces_concurrent_collects() -> None:
    class Service:
        def __init__(self) -> None:
            self.calls = 0

        def collect_global_runtime_monitor(self, *, limit: int) -> dict:
            self.calls += 1
            time.sleep(0.02)
            return {"authority": "runtime_monitor", "revision": f"rtmon:coalesced:{limit}", "signals": []}

    async def collect_twice(service: Service) -> list[dict]:
        coalescer = runtime_monitor_api._RuntimeMonitorSnapshotCoalescer(ttl_seconds=1.0)
        return await asyncio.gather(
            coalescer.collect(service, limit=5),
            coalescer.collect(service, limit=5),
        )

    service = Service()
    results = asyncio.run(collect_twice(service))

    assert service.calls == 1
    assert [item["revision"] for item in results] == ["rtmon:coalesced:5", "rtmon:coalesced:5"]


def test_runtime_monitor_snapshot_waiter_cancel_does_not_cancel_shared_collect() -> None:
    class Service:
        def __init__(self) -> None:
            self.calls = 0

        def collect_global_runtime_monitor(self, *, limit: int) -> dict:
            self.calls += 1
            time.sleep(0.02)
            return {"authority": "runtime_monitor", "revision": f"rtmon:shielded:{limit}", "signals": []}

    async def cancel_one_waiter(service: Service) -> dict:
        coalescer = runtime_monitor_api._RuntimeMonitorSnapshotCoalescer(ttl_seconds=1.0)
        first = asyncio.create_task(coalescer.collect(service, limit=5))
        await asyncio.sleep(0)
        second = asyncio.create_task(coalescer.collect(service, limit=5))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await second

    service = Service()
    result = asyncio.run(cancel_one_waiter(service))

    assert service.calls == 1
    assert result["revision"] == "rtmon:shielded:5"


def test_runtime_monitor_stream_emits_file_change_signal_from_event_log(tmp_path, monkeypatch) -> None:
    event_log = RuntimeEventLog(tmp_path / "events")
    service = SimpleNamespace(runtime_host=SimpleNamespace(event_log=event_log))

    async def collect(_service, *, limit: int) -> dict:
        return {"authority": "runtime_monitor", "revision": f"rtmon:file-change:{limit}", "signals": []}

    monkeypatch.setattr(runtime_monitor_api, "_service", lambda: service)
    monkeypatch.setattr(runtime_monitor_api, "_collect_global_runtime_monitor", collect)

    response = asyncio.run(runtime_monitor_api.stream_runtime_monitor_events(_DisconnectAfter([False, False, False, False]), limit=5))
    first_block, second_block, third_block, event_id = asyncio.run(
        _file_change_stream_blocks(response.body_iterator, service.runtime_host)
    )
    payload = _sse_json(third_block)

    assert _sse_event(first_block) == "runtime_monitor_heartbeat"
    assert _sse_event(second_block) == "runtime_monitor_snapshot"
    assert _sse_event(third_block) == "runtime_monitor_file_change"
    assert payload["event_id"] == event_id
    assert payload["file_change_record"]["record_id"] == "filechange-stream-test"


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


async def _file_change_stream_blocks(iterator, runtime_host: SimpleNamespace) -> tuple[str, str, str, str]:
    first_block = await anext(iterator)
    second_block = await anext(iterator)
    signal = publish_file_change_record(
        runtime_host,
        {
            "record_id": "filechange-stream-test",
            "session_id": "session:file-change",
            "task_run_id": "taskrun:file-change",
            "logical_path": "src/app.py",
        },
        action="write",
        source="test",
    )
    third_block = await anext(iterator)
    return first_block, second_block, third_block, str(signal.get("event_id") or "")


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
