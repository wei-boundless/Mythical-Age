from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents import MAIN_AGENT
from runtime.model_runtime import ModelRuntime, ModelRuntimeError


class _SettingsStub:
    def __init__(
        self,
        *,
        timeout: float = 1.0,
        retries: int = 1,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
        fallback_api_key: str | None = None,
        fallback_base_url: str | None = None,
    ) -> None:
        self.static = SimpleNamespace(
            llm_provider="openai",
            llm_model="gpt-4.1-mini",
            llm_api_key="test-key",
            llm_base_url="https://example.invalid/v1",
            llm_fallback_provider=fallback_provider,
            llm_fallback_model=fallback_model,
            llm_fallback_api_key=fallback_api_key,
            llm_fallback_base_url=fallback_base_url,
            llm_timeout_seconds=timeout,
            llm_max_retries=retries,
        )


class _FakeModel:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    async def ainvoke(self, _messages):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if callable(self.outcome):
            return await self.outcome()
        return self.outcome


class _AsyncCloseable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _SyncCloseable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _CloseableFakeModel(_FakeModel):
    def __init__(self, outcome) -> None:
        super().__init__(outcome)
        self.root_async_client = _AsyncCloseable()
        self.root_client = _SyncCloseable()


class _FakeAgent:
    def __init__(self, *, items=None, error: Exception | None = None) -> None:
        self.items = list(items or [])
        self.error = error

    async def astream(self, _payload, *, stream_mode):
        if self.error is not None:
            raise self.error
        for item in self.items:
            yield item


def _runtime(
    *,
    timeout: float = 1.0,
    retries: int = 1,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
) -> ModelRuntime:
    return ModelRuntime(
        _SettingsStub(
            timeout=timeout,
            retries=retries,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            fallback_api_key=fallback_api_key,
            fallback_base_url=fallback_base_url,
        )
    )


def test_model_runtime_retries_transient_invoke_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=1)
    models = [
        _FakeModel(RuntimeError("rate limit exceeded")),
        _FakeModel(SimpleNamespace(content="ok")),
    ]
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: models.pop(0))

    response = asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert response.content == "ok"


def test_model_runtime_maps_timeout_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(timeout=0.01, retries=0)

    async def _slow_response():
        await asyncio.sleep(0.05)
        return SimpleNamespace(content="late")

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(_slow_response))

    with pytest.raises(ModelRuntimeError) as exc_info:
        asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert exc_info.value.code == "timeout"
    assert exc_info.value.retryable is True


def test_model_runtime_retries_stream_before_first_event(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=1)
    agents = [
        _FakeAgent(error=RuntimeError("rate limit")),
        _FakeAgent(items=[("messages", (SimpleNamespace(content="ok"), {}))]),
    ]
    monkeypatch.setattr(runtime, "_create_raw_agent", lambda **_kwargs: agents.pop(0))

    wrapper = runtime.create_conversation_agent(
        system_prompt="system",
        tools=[],
        agent_definition=MAIN_AGENT,
    )

    async def _collect():
        items = []
        async for item in wrapper.astream({"messages": []}, stream_mode=["messages"]):
            items.append(item)
        return items

    items = asyncio.run(_collect())

    assert items == [("messages", (SimpleNamespace(content="ok"), {}))]


def test_model_runtime_closes_model_clients_after_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0)
    model = _CloseableFakeModel(SimpleNamespace(content="ok"))
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: model)

    response = asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert response.content == "ok"
    assert model.root_async_client.closed is True
    assert model.root_client.closed is True


def test_model_runtime_closes_model_clients_after_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0)
    model = _CloseableFakeModel(SimpleNamespace(content="unused"))
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: model)
    monkeypatch.setattr(
        runtime,
        "_create_raw_agent",
        lambda **_kwargs: _FakeAgent(items=[("messages", (SimpleNamespace(content="ok"), {}))]),
    )

    wrapper = runtime.create_conversation_agent(
        system_prompt="system",
        tools=[],
        agent_definition=MAIN_AGENT,
    )

    async def _collect():
        items = []
        async for item in wrapper.astream({"messages": []}, stream_mode=["messages"]):
            items.append(item)
        return items

    items = asyncio.run(_collect())

    assert items == [("messages", (SimpleNamespace(content="ok"), {}))]
    assert model.root_async_client.closed is True
    assert model.root_client.closed is True


def test_model_runtime_appends_cross_provider_fallback_candidate() -> None:
    runtime = _runtime(
        fallback_provider="bailian",
        fallback_model="qwen3.5-plus",
        fallback_api_key="bailian-key",
        fallback_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    specs = runtime._candidate_specs()

    assert [(spec.provider, spec.model) for spec in specs] == [
        ("openai", "gpt-4.1-mini"),
        ("bailian", "qwen3.5-plus"),
    ]
