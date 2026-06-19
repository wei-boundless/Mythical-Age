from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.chat_live import _resolve_subscription, _send_catchup, chat_session_live
from runtime.shared.events import RuntimeEvent
from runtime.shared.runtime_run_registry import RuntimeRun
from runtime.shared.stream_replay import RuntimeStreamReplayService


class _Registry:
    def __init__(self, run: RuntimeRun) -> None:
        self.run = run

    def get_run(self, stream_run_id: str) -> RuntimeRun | None:
        return self.run if stream_run_id == self.run.stream_run_id else None


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(dict(payload))


class _EventLog:
    def __init__(self, events: list[RuntimeEvent]) -> None:
        self.events = events

    def list_events(self, run_id: str) -> list[RuntimeEvent]:
        return [event for event in self.events if event.run_id == run_id]


def _run(*, session_id: str = "session:test") -> RuntimeRun:
    return RuntimeRun(
        stream_run_id="strun:test",
        session_id=session_id,
        event_log_id="chatrun:test",
        root_request_ref="chatreq:test",
        status="running",
        created_at=1.0,
        updated_at=1.0,
    )


def test_chat_live_subscription_resolves_cursor_from_last_event_id() -> None:
    run = _run()
    resolved_run, after_offset, last_event_id = _resolve_subscription(
        _Registry(run),
        "session:test",
        {
            "type": "subscribe",
            "protocol": "agent-live.v1",
            "subscriptions": [
                {
                    "stream_run_id": "strun:test",
                    "event_log_id": "chatrun:test",
                    "after_offset": 1,
                    "last_event_id": "strun:test:chatrun:test:3",
                }
            ],
        },
    )

    assert resolved_run is run
    assert after_offset == 3
    assert last_event_id == "strun:test:chatrun:test:3"


def test_chat_live_subscription_rejects_cross_session_run() -> None:
    with pytest.raises(ValueError, match="chat_run_session_mismatch"):
        _resolve_subscription(
            _Registry(_run()),
            "session:other",
            {
                "type": "subscribe",
                "protocol": "agent-live.v1",
                "stream_run_id": "strun:test",
            },
        )


def test_chat_live_catchup_sends_ledger_envelopes() -> None:
    run = _run()
    event = RuntimeEvent(
        event_id="rtevt:test",
        run_id="chatrun:test",
        event_type="chat_stream_event",  # type: ignore[arg-type]
        offset=2,
        created_at=123.0,
        payload={
            "public_event_type": "turn_completed",
            "terminal": True,
            "data": {"status": "completed"},
        },
    )
    websocket = _WebSocket()

    latest_offset, terminal = asyncio.run(
        _send_catchup(
            websocket,  # type: ignore[arg-type]
            RuntimeStreamReplayService(_EventLog([event])),  # type: ignore[arg-type]
            _Registry(run),
            run,
            latest_offset=1,
        )
    )

    assert latest_offset == 2
    assert terminal is True
    assert websocket.messages[0]["type"] == "event"
    assert websocket.messages[0]["public_event_type"] == "turn_completed"
    assert websocket.messages[0]["terminal"] is True


def test_chat_live_subscribes_before_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(session_id="session-test")
    event = RuntimeEvent(
        event_id="rtevt:test",
        run_id="chatrun:test",
        event_type="chat_stream_event",  # type: ignore[arg-type]
        offset=0,
        created_at=123.0,
        payload={
            "public_event_type": "turn_completed",
            "terminal": True,
            "data": {"status": "completed"},
        },
    )
    event_log = _SubscribingEventLog([event])
    host = SimpleNamespace(
        run_registry=_Registry(run),
        event_log=event_log,
        stream_replay=RuntimeStreamReplayService(event_log),  # type: ignore[arg-type]
    )
    runtime = SimpleNamespace(
        harness_runtime=SimpleNamespace(single_agent_runtime_host=host),
    )
    websocket = _ScriptedWebSocket(
        {
            "type": "subscribe",
            "protocol": "agent-live.v1",
            "stream_run_id": "strun:test",
            "after_offset": -1,
        }
    )
    monkeypatch.setattr("api.chat_live.require_runtime", lambda: runtime)

    asyncio.run(chat_session_live(websocket, "session-test"))  # type: ignore[arg-type]

    assert event_log.calls[:2] == ["subscribe", "list_events"]
    assert websocket.closed_code == 1000
    assert [message["type"] for message in websocket.messages] == ["hello", "event", "terminal"]


class _SubscribingEventLog:
    def __init__(self, events: list[RuntimeEvent]) -> None:
        self.events = events
        self.calls: list[str] = []
        self.subscribed = False

    def subscribe(self, *, run_id: str = "", max_queue_size: int = 500):
        del run_id, max_queue_size
        self.calls.append("subscribe")
        self.subscribed = True
        return SimpleNamespace(subscription_id="rtesub:test", queue=asyncio.Queue())

    def unsubscribe(self, subscription: object) -> None:
        del subscription
        self.calls.append("unsubscribe")

    def list_events(self, run_id: str) -> list[RuntimeEvent]:
        assert self.subscribed is True
        self.calls.append("list_events")
        return [event for event in self.events if event.run_id == run_id]


class _ScriptedWebSocket:
    def __init__(self, subscribe_message: dict) -> None:
        self.subscribe_message = subscribe_message
        self.messages: list[dict] = []
        self.closed_code: int | None = None

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.messages.append(dict(payload))

    async def receive_json(self) -> dict:
        return dict(self.subscribe_message)

    async def close(self, code: int) -> None:
        self.closed_code = int(code)
