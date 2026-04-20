from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import observability.langsmith_tracing as tracing


class _FakeClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeRun:
    def __init__(self, run_id: str) -> None:
        self.id = run_id
        self.metadata: list[dict[str, object]] = []

    def get_url(self) -> str:
        return f"https://langsmith.local/{self.id}"

    def add_metadata(self, payload) -> None:
        self.metadata.append(dict(payload))


class _FakeContextManager:
    def __init__(self, value) -> None:
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _fake_tracing_context(**_kwargs):
    return _FakeContextManager(None)


def _fake_langsmith_trace(name: str, **_kwargs):
    return _FakeContextManager(_FakeRun(f"{name}-id"))


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch):
    tracing._build_client.cache_clear()
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_DEV_TRACE_LINKS", raising=False)
    monkeypatch.delenv("APP_TRACE_LOCAL", raising=False)
    monkeypatch.delenv("APP_TRACE_LOCAL_LINKS", raising=False)
    monkeypatch.delenv("APP_TRACE_DIR", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    yield
    tracing._build_client.cache_clear()


def test_langsmith_trace_adapter_stays_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    monkeypatch.setattr(tracing, "tracing_context", _fake_tracing_context)
    monkeypatch.setattr(tracing, "langsmith_trace", _fake_langsmith_trace)
    monkeypatch.setenv("APP_TRACE_LOCAL", "false")

    with tracing.start_turn_trace(
        session_id="session-1",
        user_message="hello",
        history_length=0,
    ) as turn_trace:
        assert turn_trace.enabled is False
        assert tracing.build_debug_trace_event(turn_trace) is None

    assert tracing.is_langsmith_tracing_enabled() is False
    assert tracing.should_emit_dev_trace_link() is False


def test_local_trace_fallback_writes_trace_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TRACE_LOCAL", "true")
    monkeypatch.setenv("APP_TRACE_DIR", str(tmp_path))

    with tracing.start_turn_trace(
        session_id="session-local",
        user_message="hello",
        history_length=1,
        metadata={"route": "chat"},
        tags=["smoke"],
    ) as turn_trace:
        assert turn_trace.enabled is True
        assert turn_trace.trace_source == "local"
        assert turn_trace.trace_id.startswith("local-")
        with turn_trace.stage("planner", metadata={"route": "chat"}) as stage_run:
            assert stage_run is not None
        turn_trace.annotate({"app.route": "chat"})
        payload = tracing.build_debug_trace_event(turn_trace)

    trace_path = Path(turn_trace.trace_url)
    assert payload is not None
    assert payload["kind"] == "local_trace"
    assert payload["trace_source"] == "local"
    assert trace_path.exists()
    assert '"name": "planner"' in trace_path.read_text(encoding="utf-8")


def test_langsmith_trace_adapter_exposes_debug_link_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    monkeypatch.setattr(tracing, "tracing_context", _fake_tracing_context)
    monkeypatch.setattr(tracing, "langsmith_trace", _fake_langsmith_trace)
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_DEV_TRACE_LINKS", "true")
    monkeypatch.setenv("APP_ENV", "development")

    with tracing.start_turn_trace(
        session_id="session-1",
        user_message="hello",
        history_length=2,
        metadata={"route": "chat"},
        tags=["smoke"],
    ) as turn_trace:
        assert turn_trace.enabled is True
        assert turn_trace.trace_id == "chat.turn-id"
        assert turn_trace.trace_url.endswith("/chat.turn-id")
        with turn_trace.stage("planner", metadata={"route": "chat"}) as stage_run:
            assert stage_run is not None
        payload = tracing.build_debug_trace_event(turn_trace)

    assert tracing.is_langsmith_tracing_enabled() is True
    assert tracing.should_emit_dev_trace_link() is True
    assert payload is not None
    assert payload["kind"] == "langsmith_trace"
    assert payload["trace_id"] == "chat.turn-id"


def test_langsmith_trace_links_are_hidden_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    monkeypatch.setattr(tracing, "tracing_context", _fake_tracing_context)
    monkeypatch.setattr(tracing, "langsmith_trace", _fake_langsmith_trace)
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("APP_ENV", "production")

    with tracing.start_turn_trace(
        session_id="session-2",
        user_message="hello",
        history_length=1,
    ) as turn_trace:
        assert turn_trace.enabled is True
        assert tracing.build_debug_trace_event(turn_trace) is None

    assert tracing.should_emit_dev_trace_link() is False
