from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.model_gateway.model_runtime import ModelRuntime, ModelRuntimeError, ModelSpec
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts, tool_calls_for_langchain_messages
from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions

MAIN_AGENT = SimpleNamespace(agent_id="agent:main:test")


class _SettingsStub:
    def __init__(
        self,
        *,
        timeout: float = 1.0,
        retries: int = 1,
        max_output_tokens: int = 32768,
        long_output_timeout_seconds: float = 180.0,
        thinking_mode: str = "disabled",
        reasoning_effort: str = "high",
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
            llm_max_output_tokens=max_output_tokens,
            llm_long_output_timeout_seconds=long_output_timeout_seconds,
            llm_thinking_mode=thinking_mode,
            llm_reasoning_effort=reasoning_effort,
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


class _DelayedFakeAgent:
    def __init__(self, *, delay: float, items=None) -> None:
        self.delay = delay
        self.items = list(items or [])

    async def astream(self, _payload, *, stream_mode):
        for item in self.items:
            await asyncio.sleep(self.delay)
            yield item


def _runtime(
    *,
    timeout: float = 1.0,
    retries: int = 1,
    max_output_tokens: int = 32768,
    long_output_timeout_seconds: float = 180.0,
    thinking_mode: str = "disabled",
    reasoning_effort: str = "high",
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
) -> ModelRuntime:
    return ModelRuntime(
        _SettingsStub(
            timeout=timeout,
            retries=retries,
            max_output_tokens=max_output_tokens,
            long_output_timeout_seconds=long_output_timeout_seconds,
            thinking_mode=thinking_mode,
            reasoning_effort=reasoning_effort,
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
    runtime = _runtime(timeout=0.01, retries=0, max_output_tokens=4096)

    async def _slow_response():
        await asyncio.sleep(0.05)
        return SimpleNamespace(content="late")

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(_slow_response))

    with pytest.raises(ModelRuntimeError) as exc_info:
        asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert exc_info.value.code == "timeout"
    assert exc_info.value.retryable is True


def test_model_runtime_maps_read_errors_as_retryable_transport() -> None:
    runtime = _runtime(retries=0)
    error = runtime._map_error(
        RuntimeError("ReadError: peer closed connection during stream"),
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        ),
    )

    assert error.code == "provider_unavailable"
    assert error.retryable is True


def test_model_runtime_uses_long_output_timeout_for_large_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(
        timeout=0.01,
        retries=0,
        max_output_tokens=32768,
        long_output_timeout_seconds=0.2,
    )

    async def _slow_response():
        await asyncio.sleep(0.05)
        return SimpleNamespace(content="ok")

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(_slow_response))

    response = asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert response.content == "ok"


def test_model_runtime_keeps_short_output_timeout_for_small_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(
        timeout=0.01,
        retries=0,
        max_output_tokens=4096,
        long_output_timeout_seconds=0.2,
    )

    async def _slow_response():
        await asyncio.sleep(0.05)
        return SimpleNamespace(content="late")

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(_slow_response))

    with pytest.raises(ModelRuntimeError) as exc_info:
        asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))

    assert exc_info.value.code == "timeout"


def test_model_runtime_uses_long_output_timeout_for_stream_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(
        timeout=0.01,
        retries=0,
        max_output_tokens=32768,
        long_output_timeout_seconds=0.2,
    )
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(SimpleNamespace(content="unused")))
    monkeypatch.setattr(
        runtime,
        "_create_raw_agent",
        lambda **_kwargs: _DelayedFakeAgent(delay=0.05, items=[("messages", (SimpleNamespace(content="ok"), {}))]),
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


def test_model_runtime_reuses_model_clients_until_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0)
    model = _CloseableFakeModel(SimpleNamespace(content="ok"))
    build_count = 0

    def _build(_spec):
        nonlocal build_count
        build_count += 1
        return model

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", _build)

    response = asyncio.run(runtime.invoke_messages([{"role": "user", "content": "hello"}]))
    second_response = asyncio.run(runtime.invoke_messages([{"role": "user", "content": "again"}]))

    assert response.content == "ok"
    assert second_response.content == "ok"
    assert build_count == 1
    assert model.root_async_client.closed is False
    assert model.root_client.closed is False

    asyncio.run(runtime.close())

    assert model.root_async_client.closed is True
    assert model.root_client.closed is True


def test_model_runtime_reuses_stream_model_clients_until_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0)
    model = _CloseableFakeModel(SimpleNamespace(content="unused"))
    build_count = 0

    def _build(_spec):
        nonlocal build_count
        build_count += 1
        return model

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", _build)
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
    second_items = asyncio.run(_collect())

    assert items == [("messages", (SimpleNamespace(content="ok"), {}))]
    assert second_items == [("messages", (SimpleNamespace(content="ok"), {}))]
    assert build_count == 1
    assert model.root_async_client.closed is False
    assert model.root_client.closed is False

    asyncio.run(runtime.close())

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


def test_model_runtime_does_not_insert_provider_default_candidate() -> None:
    runtime = _runtime(
        fallback_provider="bailian",
        fallback_model="qwen3.5-plus",
        fallback_api_key="bailian-key",
        fallback_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    runtime.settings_service.static.llm_provider = "deepseek"
    runtime.settings_service.static.llm_model = "deepseek-v4-flash"
    runtime.settings_service.static.llm_base_url = "https://api.deepseek.com"

    specs = runtime._candidate_specs()

    assert [(spec.provider, spec.model) for spec in specs] == [
        ("deepseek", "deepseek-v4-flash"),
        ("bailian", "qwen3.5-plus"),
    ]


def test_model_runtime_logs_provider_detail_when_switching_tool_candidate(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime(
        retries=0,
        fallback_provider="bailian",
        fallback_model="qwen3.5-plus",
        fallback_api_key="bailian-key",
        fallback_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    models = [
        _FakeModel(RuntimeError("400 Bad Request: unsupported tool schema")),
        _FakeModel(SimpleNamespace(content="ok")),
    ]

    class _BindableFakeModel(_FakeModel):
        def bind_tools(self, _tools):
            return self

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _BindableFakeModel(models.pop(0).outcome))

    with caplog.at_level("WARNING", logger="runtime.model_gateway.model_runtime"):
        response = asyncio.run(runtime.invoke_messages_with_tools([HumanMessage(content="hello")], [object()]))

    assert response.content == "ok"
    assert "Switching tool-enabled model candidate after provider_error on openai/gpt-4.1-mini" in caplog.text
    assert "unsupported tool schema" in caplog.text


def test_model_runtime_passes_native_tool_choice_options(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0)
    captured: dict[str, object] = {}

    class _BindableFakeModel(_FakeModel):
        def bind_tools(self, tools, **kwargs):
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return self

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _BindableFakeModel(SimpleNamespace(content="ok")))

    options = ToolCallBindingOptions(
        tool_choice={"type": "function", "function": {"name": "write_file"}},
        strict=False,
        parallel_tool_calls=False,
    )
    response = asyncio.run(
        runtime.invoke_messages_with_tools(
            [HumanMessage(content="write")],
            [SimpleNamespace(name="write_file")],
            tool_call_options=options,
        )
    )

    assert response.content == "ok"
    assert captured["tools"] == [SimpleNamespace(name="write_file")]
    assert captured["kwargs"] == {
        "tool_choice": {"type": "function", "function": {"name": "write_file"}},
        "strict": False,
        "parallel_tool_calls": False,
    }


def test_deepseek_thinking_filters_unsupported_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0, thinking_mode="enabled")
    captured: dict[str, object] = {}

    class _BindableFakeModel(_FakeModel):
        def bind_tools(self, tools, **kwargs):
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return self

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _BindableFakeModel(SimpleNamespace(content="ok")))

    options = ToolCallBindingOptions(
        tool_choice={"type": "function", "function": {"name": "read_file"}},
        strict=False,
        parallel_tool_calls=False,
    )
    response = asyncio.run(
        runtime.invoke_messages_with_tools(
            [HumanMessage(content="read")],
            [SimpleNamespace(name="read_file")],
            model_spec=ModelSpec(
                provider="deepseek",
                model="deepseek-v4-pro",
                api_key="deepseek-key",
                base_url="https://api.deepseek.com/v1",
                thinking_mode="enabled",
            ),
            tool_call_options=options,
        )
    )

    assert response.content == "ok"
    assert captured["tools"] == [SimpleNamespace(name="read_file")]
    assert captured["kwargs"] == {
        "strict": False,
        "parallel_tool_calls": False,
    }


def test_provider_tool_call_adapter_reads_additional_kwargs_tool_calls() -> None:
    response = SimpleNamespace(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"backend/app.py"}',
                    },
                }
            ]
        },
    )

    calls = normalize_tool_call_dicts(response, provider="deepseek")

    assert calls == [
        {
            "id": "call-1",
            "name": "read_file",
            "args": {"path": "backend/app.py"},
            "type": "tool_call",
            "source": "native_tool_call",
        }
    ]


def test_provider_tool_call_adapter_reads_function_call_payload() -> None:
    response = SimpleNamespace(
        content="",
        additional_kwargs={
            "function_call": {
                "name": "terminal",
                "arguments": '{"command":"pytest -q"}',
                "type": "function_call",
            }
        },
    )

    calls = normalize_tool_call_dicts(response, provider="deepseek")

    assert calls[0]["name"] == "terminal"
    assert calls[0]["args"] == {"command": "pytest -q"}


def test_provider_tool_call_adapter_converts_deepseek_dsml_tool_call() -> None:
    response = SimpleNamespace(
        content=(
            '<｜｜DSML｜｜invoke name="edit_file">'
            '<｜｜DSML｜｜parameter name="path" string="true">backend/order_pipeline.py</｜｜DSML｜｜parameter>'
            '<｜｜DSML｜｜parameter name="old_text" string="true">return 0</｜｜DSML｜｜parameter>'
            '<｜｜DSML｜｜parameter name="new_text" string="true">return sum(values)</｜｜DSML｜｜parameter>'
            '</｜｜DSML｜｜invoke>'
        ),
        additional_kwargs={"provider": "deepseek"},
    )

    calls = normalize_tool_call_dicts(response, provider="deepseek")

    assert calls == [
        {
            "id": "dsml-tool-call-1",
            "name": "edit_file",
            "args": {
                "path": "backend/order_pipeline.py",
                "old_text": "return 0",
                "new_text": "return sum(values)",
            },
            "type": "tool_call",
            "source": "provider_dsml_tool_call",
        }
    ]


def test_model_response_does_not_execute_dsml_when_no_tools_are_bound() -> None:
    class _DsmlModelRuntime:
        async def invoke_messages(self, _messages, **_kwargs):
            return SimpleNamespace(
                content=(
                    '<｜｜DSML｜｜invoke name="write_file">'
                    '<｜｜DSML｜｜parameter name="path" string="true">output/x.md</｜｜DSML｜｜parameter>'
                    '<｜｜DSML｜｜parameter name="content" string="true">x</｜｜DSML｜｜parameter>'
                    '</｜｜DSML｜｜invoke>'
                ),
                additional_kwargs={"provider": "deepseek"},
            )

    executor = ModelResponseRuntimeExecutor(model_runtime=_DsmlModelRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="close out",
            model_messages=[],
            directive=SimpleNamespace(
                executor_type="model",
                directive_id="directive:test",
                task_id="task:test",
                plan_ref="plan:test",
                execution_graph_ref="graph:test",
            ),
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert [event["type"] for event in events] == ["model_protocol_violation"]


def test_provider_tool_call_adapter_strips_metadata_for_langchain_messages() -> None:
    calls = tool_calls_for_langchain_messages(
        [
            {
                "id": "call-1",
                "name": "read_file",
                "args": {"path": "backend/app.py"},
                "type": "tool_call",
                "source": "native_tool_call",
            }
        ]
    )

    assert calls == [
        {
            "id": "call-1",
            "name": "read_file",
            "args": {"path": "backend/app.py"},
            "type": "tool_call",
        }
    ]


def test_deepseek_payload_replays_reasoning_content_for_tool_roundtrip() -> None:
    runtime = _runtime(retries=0)
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    assistant_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_date",
                "args": {},
                "id": "call_123",
                "type": "tool_call",
            }
        ],
        additional_kwargs={"reasoning_content": "I should call get_date first."},
    )

    payload = model._get_request_payload(
        [
            HumanMessage(content="明天是什么时候？"),
            assistant_message,
            ToolMessage(content="2026-04-26", tool_call_id="call_123"),
        ]
    )

    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["reasoning_content"] == "I should call get_date first."


def test_deepseek_model_runtime_passes_long_output_and_thinking_controls() -> None:
    runtime = _runtime(
        retries=0,
        timeout=45,
        max_output_tokens=65536,
        long_output_timeout_seconds=300,
        thinking_mode="disabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    assert model.max_tokens == 65536
    assert model.request_timeout == 300
    assert model.max_retries == 0
    assert model.reasoning_effort is None
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_deepseek_model_runtime_only_sends_reasoning_effort_when_thinking_enabled() -> None:
    runtime = _runtime(
        retries=0,
        max_output_tokens=65536,
        thinking_mode="enabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    assert model.reasoning_effort == "max"
    assert model.extra_body == {"thinking": {"type": "enabled"}}


def test_openai_compatible_runtime_passes_max_completion_tokens() -> None:
    runtime = _runtime(
        retries=0,
        timeout=45,
        max_output_tokens=32768,
        long_output_timeout_seconds=240,
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="openai",
            model="gpt-4.1-mini",
            api_key="openai-key",
            base_url="https://example.invalid/v1",
        )
    )

    assert model.max_tokens == 32768
    assert model.request_timeout == 240
    assert model.max_retries == 0


def test_model_runtime_reads_long_output_settings_dynamically() -> None:
    runtime = _runtime(
        timeout=45,
        max_output_tokens=32768,
        long_output_timeout_seconds=180,
    )
    runtime.settings_service.static.llm_max_output_tokens = 65536
    runtime.settings_service.static.llm_long_output_timeout_seconds = 360
    runtime.settings_service.static.llm_thinking_mode = "enabled"

    assert runtime.max_output_tokens == 65536
    assert runtime.long_output_timeout_seconds == 360
    assert runtime.model_call_timeout_seconds == 360
    assert runtime.thinking_mode == "enabled"


def test_model_runtime_per_call_override_controls_deepseek_parameters() -> None:
    runtime = _runtime(
        retries=1,
        timeout=45,
        max_output_tokens=32768,
        long_output_timeout_seconds=180,
        thinking_mode="enabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com/v1",
            max_output_tokens=65536,
            timeout_seconds=30,
            long_output_timeout_seconds=420,
            max_retries=0,
            thinking_mode="disabled",
            reasoning_effort="high",
            temperature=0.7,
        )
    )

    assert model.max_tokens == 65536
    assert model.request_timeout == 420
    assert model.max_retries == 0
    assert model.temperature == 0.7
    assert model.reasoning_effort is None
    assert model.extra_body == {"thinking": {"type": "disabled"}}


def test_model_runtime_per_call_override_bypasses_fallback_candidates() -> None:
    runtime = _runtime(
        fallback_provider="bailian",
        fallback_model="qwen3.5-plus",
        fallback_api_key="bailian-key",
        fallback_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    specs = runtime._candidate_specs(
        model_spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com/v1",
            max_output_tokens=65536,
        )
    )

    assert [(spec.provider, spec.model, spec.max_output_tokens) for spec in specs] == [
        ("deepseek", "deepseek-v4-pro", 65536)
    ]
