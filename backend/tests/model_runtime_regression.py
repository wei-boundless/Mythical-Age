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

from runtime.model_gateway.model_runtime import _DeepSeekReasoningCompatChatModel, ModelRuntime, ModelRuntimeError, ModelSpec
from runtime.model_gateway.provider_cache_policy import ProviderCachePolicyResolver
from runtime.tool_runtime.provider_tool_call_adapter import normalize_tool_call_dicts, tool_calls_for_langchain_messages
from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from runtime.tool_runtime.tool_call_policy import ToolCallBindingOptions
from runtime.prompt_accounting import PromptAccountingLedger
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from harness.loop.single_agent_turn import _assistant_tool_call_message

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


def test_model_runtime_records_fallback_candidate_switch_in_prompt_accounting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        retries=0,
        max_output_tokens=4096,
        fallback_provider="deepseek",
        fallback_model="deepseek-v4-pro",
        fallback_api_key="fallback-key",
        fallback_base_url="https://api.deepseek.com/v1",
    )
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    models = [
        _FakeModel(RuntimeError("rate limit exceeded")),
        _FakeModel(SimpleNamespace(content="ok")),
    ]
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: models.pop(0))

    response = asyncio.run(
        runtime.invoke_messages(
            [{"role": "user", "content": "hello"}],
            accounting_context={"request_id": "modelreq:fallback-switch", "session_id": "session:fallback"},
        )
    )

    records = ledger.list_prompt_cache_breaks(session_id="session:fallback")
    assert response.content == "ok"
    assert any(record.reason == "model_candidate_switch" for record in records)
    switch = next(record for record in records if record.reason == "model_candidate_switch")
    assert switch.diagnostics["from_model"]
    assert switch.diagnostics["to_model"] == "deepseek-v4-pro"
    assert switch.diagnostics["call_kind"] == "invoke_messages"


def test_model_runtime_marks_missing_segment_plan_as_unplanned(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)

    runtime._begin_prompt_accounting(
        [{"role": "user", "content": "hello"}],
        tools=None,
        spec=ModelSpec(provider="deepseek", model="deepseek-v4-flash", api_key="key", base_url="https://api.deepseek.com/v1"),
        accounting_context={
            "request_id": "modelreq:unplanned",
            "session_id": "session:unplanned",
            "source": "harness.single_agent_turn",
        },
        attempt=1,
        call_kind="invoke_messages",
    )

    local = [record for record in ledger.list_token_usage(session_id="session:unplanned") if record.source == "local_prediction"][0]
    breaks = ledger.list_prompt_cache_breaks(session_id="session:unplanned")
    assert local.diagnostics["cache_metric_scope"] == "unplanned_model_call"
    assert local.diagnostics["prompt_manifest"]["unplanned_model_call"] is True
    assert any(record.reason == "unplanned_model_call" for record in breaks)
    assert next(record for record in breaks if record.reason == "unplanned_model_call").diagnostics["severity"] == "high"


def test_generate_title_uses_utility_minimal_segment_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _FakeModel(SimpleNamespace(content="标题")))

    title = asyncio.run(runtime.generate_title("请检查缓存命中率"))

    records = ledger.list_token_usage()
    local = next(record for record in records if record.source == "local_prediction")
    assert title == "标题"
    assert local.diagnostics["cache_metric_scope"] == "utility_minimal_plan"
    assert local.diagnostics["call_purpose"] == "utility.generate_title"
    assert local.diagnostics["prompt_manifest"]["cache_metric_scope"] == "utility_minimal_plan"


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


def test_deepseek_thinking_keeps_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
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
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "strict": False,
        "parallel_tool_calls": False,
    }


def test_deepseek_global_thinking_keeps_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
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
            ),
            tool_call_options=options,
        )
    )

    assert response.content == "ok"
    assert captured["tools"] == [SimpleNamespace(name="read_file")]
    assert captured["kwargs"] == {
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "parallel_tool_calls": False,
    }


def test_deepseek_explicit_disabled_thinking_keeps_forced_tool_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime(retries=0, thinking_mode="enabled")
    captured: dict[str, object] = {}

    class _BindableFakeModel(_FakeModel):
        def bind_tools(self, tools, **kwargs):
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return self

    monkeypatch.setattr(runtime, "_build_chat_model_for_spec", lambda _spec: _BindableFakeModel(SimpleNamespace(content="ok")))

    options = ToolCallBindingOptions(
        tool_choice={"type": "function", "function": {"name": "write_file"}},
        parallel_tool_calls=False,
    )
    response = asyncio.run(
        runtime.invoke_messages_with_tools(
            [HumanMessage(content="write")],
            [SimpleNamespace(name="write_file")],
            model_spec=ModelSpec(
                provider="deepseek",
                model="deepseek-v4-pro",
                api_key="deepseek-key",
                base_url="https://api.deepseek.com/v1",
                thinking_mode="disabled",
            ),
            tool_call_options=options,
        )
    )

    assert response.content == "ok"
    assert captured["tools"] == [SimpleNamespace(name="write_file")]
    assert captured["kwargs"] == {
        "tool_choice": {"type": "function", "function": {"name": "write_file"}},
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


def test_model_response_executor_records_segment_plan_for_directive_model_call(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    runtime._get_chat_model_for_spec = lambda _spec: _FakeModel(SimpleNamespace(content="完成"))
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="close out",
            model_messages=[
                {"role": "system", "content": "你负责完成当前模型响应。"},
                {"role": "user", "content": "请收口。"},
            ],
            directive=SimpleNamespace(
                executor_type="model",
                directive_id="directive:planned",
                task_id="taskrun:planned",
                plan_ref="plan:test",
                execution_graph_ref="graph:test",
                diagnostics={"session_id": "session:planned", "task_run_id": "taskrun:planned"},
            ),
            tool_instances=[],
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())
    local = next(record for record in ledger.list_token_usage(session_id="session:planned") if record.source == "local_prediction")
    breaks = ledger.list_prompt_cache_breaks(session_id="session:planned")

    assert any(event["type"] == "done" for event in events)
    assert local.diagnostics["cache_metric_scope"] == "runtime_directive_model_response"
    assert local.diagnostics["prompt_manifest"]["segment_plan_ref"]
    assert not any(record.reason == "unplanned_model_call" for record in breaks)


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


def test_deepseek_payload_replays_reasoning_content_from_dict_tool_roundtrip() -> None:
    runtime = _runtime(retries=0)
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    payload = model._get_request_payload(
        [
            {"role": "user", "content": "明天是什么时候？"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I should call get_date first.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "name": "get_date",
                        "args": {},
                        "type": "tool_call",
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "2026-04-26"},
        ]
    )

    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["reasoning_content"] == "I should call get_date first."


def test_deepseek_payload_replays_reasoning_content_across_user_turns() -> None:
    runtime = _runtime(retries=0)
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    payload = model._get_request_payload(
        [
            {"role": "user", "content": "查杭州明天天气。"},
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "I need tomorrow's date first.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "name": "get_date",
                        "args": {},
                        "type": "tool_call",
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_123", "content": "2026-04-20"},
            {"role": "assistant", "content": "杭州明天多云。", "reasoning_content": "Now answer the user."},
            {"role": "user", "content": "再查广州。"},
        ]
    )

    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["reasoning_content"] == "I need tomorrow's date first."
    assert payload["messages"][3]["role"] == "assistant"
    assert payload["messages"][3]["reasoning_content"] == "Now answer the user."
    assert payload["messages"][4]["role"] == "user"


def test_single_agent_turn_preserves_deepseek_reasoning_content_for_tool_followup() -> None:
    message = _assistant_tool_call_message(
        SimpleNamespace(
            content="",
            additional_kwargs={"reasoning_content": "I should inspect the file before answering."},
        ),
        [
            {
                "id": "call_123",
                "name": "read_file",
                "args": {"path": "README.md"},
                "type": "tool_call",
            }
        ],
    )

    assert message["role"] == "assistant"
    assert message["reasoning_content"] == "I should inspect the file before answering."
    assert message["tool_calls"] == [
        {
            "id": "call_123",
            "name": "read_file",
            "args": {"path": "README.md"},
            "type": "tool_call",
        }
    ]


def test_deepseek_model_runtime_passes_long_output_and_thinking_controls() -> None:
    runtime = _runtime(
        retries=0,
        timeout=45,
        max_output_tokens=65536,
        long_output_timeout_seconds=300,
        thinking_mode="disabled",
        reasoning_effort="high",
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
    assert model.temperature is None
    assert model.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_model_runtime_omits_reasoning_effort_when_auto() -> None:
    runtime = _runtime(
        retries=0,
        max_output_tokens=65536,
        thinking_mode="enabled",
        reasoning_effort="auto",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com",
        )
    )

    assert model.reasoning_effort is None
    assert model.temperature is None
    assert model.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_thinking_omits_temperature_from_cache_relevant_params(tmp_path: Path) -> None:
    runtime = _runtime(retries=0, thinking_mode="enabled")
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:deepseek-thinking-temperature",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            temperature=0.0,
        ),
        accounting_context={
            "request_id": "modelreq:deepseek-thinking-temperature:1",
            "session_id": "session:deepseek-thinking-temperature",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            temperature=0.7,
        ),
        accounting_context={
            "request_id": "modelreq:deepseek-thinking-temperature:2",
            "session_id": "session:deepseek-thinking-temperature",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    latest = ledger.list_prompt_stability(session_id="session:deepseek-thinking-temperature")[-1]

    assert latest.diagnostics["dynamic_params_changed"] is False
    assert "temperature" not in latest.dynamic_param_summary["request_params"]


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


def test_openai_reasoning_model_sends_reasoning_effort_when_thinking_enabled() -> None:
    runtime = _runtime(
        retries=0,
        thinking_mode="enabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="openai",
            model="gpt-5",
            api_key="openai-key",
            base_url="https://api.openai.com/v1",
        )
    )

    assert model.reasoning_effort == "high"


def test_openai_chat_model_omits_reasoning_effort_when_not_reasoning_capable() -> None:
    runtime = _runtime(
        retries=0,
        thinking_mode="enabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="openai",
            model="gpt-4.1-mini",
            api_key="openai-key",
            base_url="https://api.openai.com/v1",
        )
    )

    assert model.reasoning_effort is None


def test_openai_reasoning_model_omits_reasoning_effort_when_thinking_disabled() -> None:
    runtime = _runtime(
        retries=0,
        thinking_mode="disabled",
        reasoning_effort="max",
    )
    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="openai",
            model="gpt-5",
            api_key="openai-key",
            base_url="https://api.openai.com/v1",
        )
    )

    assert model.reasoning_effort is None


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


def test_deepseek_chat_prefix_protocol_preserves_assistant_prefix_flag() -> None:
    model = _DeepSeekReasoningCompatChatModel(
        model="deepseek-v4-flash",
        api_key="deepseek-key",
        base_url="https://api.deepseek.com/beta",
        api_base="https://api.deepseek.com/beta",
        extra_body={"thinking": {"type": "disabled"}},
    )

    payload = model._get_request_payload(
        [
            {"role": "system", "content": "写作任务"},
            {
                "role": "assistant",
                "content": "## 章节正文候选\n\n### 第11章 ",
                "prefix": True,
            },
        ]
    )

    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["prefix"] is True


def test_deepseek_model_runtime_sets_langchain_deepseek_api_base_for_beta_prefix_endpoint() -> None:
    runtime = _runtime(retries=0, thinking_mode="disabled")

    model = runtime._build_chat_model_for_spec(
        ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com/beta",
            completion_profile={
                "mode": "chat_prefix",
                "provider_mode": "deepseek_chat_prefix",
            },
        )
    )

    assert model.openai_api_base == "https://api.deepseek.com/beta"
    assert model.api_base == "https://api.deepseek.com/beta"


def test_model_runtime_rejects_deepseek_max_when_thinking_disabled() -> None:
    runtime = _runtime(
        retries=0,
        thinking_mode="disabled",
        reasoning_effort="max",
    )

    with pytest.raises(ModelRuntimeError) as exc_info:
        runtime._build_chat_model_for_spec(
            ModelSpec(
                provider="deepseek",
                model="deepseek-v4-pro",
                api_key="deepseek-key",
                base_url="https://api.deepseek.com/v1",
            )
        )

    assert exc_info.value.code == "configuration"
    assert "thinking_mode=enabled" in exc_info.value.detail


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


def test_model_runtime_resolves_frontend_model_selection_dict_credential_ref() -> None:
    runtime = _runtime()
    runtime.settings_service.static.llm_provider = "deepseek"
    runtime.settings_service.static.llm_model = "deepseek-v4-pro"
    runtime.settings_service.static.llm_api_key = "deepseek-key"
    runtime.settings_service.static.llm_base_url = "https://api.deepseek.com/v1"

    specs = runtime._candidate_specs(
        model_spec={
            "selection_id": "system-default",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "credential_ref": "provider:deepseek:primary",
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
        }
    )

    assert len(specs) == 1
    assert specs[0].provider == "deepseek"
    assert specs[0].model == "deepseek-v4-pro"
    assert specs[0].api_key == "deepseek-key"
    assert specs[0].thinking_mode == "enabled"
    assert specs[0].reasoning_effort == "max"


def test_model_runtime_partial_model_selection_inherits_system_model_config() -> None:
    runtime = _runtime()
    runtime.settings_service.static.llm_provider = "deepseek"
    runtime.settings_service.static.llm_model = "deepseek-v4-pro"
    runtime.settings_service.static.llm_api_key = "deepseek-key"
    runtime.settings_service.static.llm_base_url = "https://api.deepseek.com/v1"

    specs = runtime._candidate_specs(
        model_spec={
            "timeout_seconds": 12,
            "diagnostics": {"authority": "test.partial_model_selection"},
        }
    )

    assert len(specs) == 1
    assert specs[0].provider == "deepseek"
    assert specs[0].model == "deepseek-v4-pro"
    assert specs[0].api_key == "deepseek-key"
    assert specs[0].base_url == "https://api.deepseek.com/v1"
    assert specs[0].timeout_seconds == 12


def test_model_runtime_prompt_accounting_records_cache_efficiency_metrics(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "stable contract"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:metrics",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": "stable contract",
                "kind": "task_stable",
                "source_ref": "contract.test",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    accounting = runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(provider="openai", model="gpt-4.1-mini", api_key="key", base_url="https://example.invalid/v1"),
        accounting_context={
            "request_id": "modelreq:metrics",
            "session_id": "session:metrics",
            "source": "test.metrics",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="test_call",
    )
    runtime._finish_prompt_accounting(
        accounting,
        response=SimpleNamespace(
            content="ok",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 4,
                    "total_tokens": 24,
                    "prompt_tokens_details": {"cached_tokens": 8},
                }
            },
        ),
    )

    cache_record = ledger.list_prompt_cache(session_id="session:metrics")[-1]
    provider_usage = [record for record in ledger.list_token_usage(session_id="session:metrics") if record.source == "provider_usage"][0]

    assert cache_record.diagnostics["prefix_hash_matches_model_request"] is True
    assert cache_record.diagnostics["unplanned_message_count"] == 0
    assert cache_record.diagnostics["provider_cached_tokens"] == 8
    assert cache_record.diagnostics["cache_efficiency"] > 0
    assert cache_record.diagnostics["duration_seconds"] >= 0
    assert provider_usage.diagnostics["duration_seconds"] >= 0


def test_model_runtime_records_prompt_stability_report_and_provider_usage(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    spec = ModelSpec(provider="deepseek", model="deepseek-v4-pro", api_key="key", base_url="https://api.deepseek.com/v1")
    first_messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "stable contract A"},
        {"role": "user", "content": "current request"},
    ]
    first_plan = build_prompt_segment_plan(
        packet_id="packet:stability:1",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": "stable contract A",
                "kind": "task_stable",
                "source_ref": "contract.test",
                "cache_role": "session_stable",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()
    first = runtime._begin_prompt_accounting(
        first_messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:stability:1",
            "session_id": "session:stability",
            "source": "turn_action",
            "segment_plan": first_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._finish_prompt_accounting(
        first,
        response=SimpleNamespace(
            content="ok",
            usage_metadata={
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 100,
                "completion_tokens": 3,
            },
        ),
    )

    second_messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "stable contract B"},
        {"role": "user", "content": "current request"},
    ]
    second_plan = build_prompt_segment_plan(
        packet_id="packet:stability:2",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": "stable contract B",
                "kind": "task_stable",
                "source_ref": "contract.test",
                "cache_role": "session_stable",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()
    second = runtime._begin_prompt_accounting(
        second_messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:stability:2",
            "session_id": "session:stability",
            "source": "turn_action",
            "segment_plan": second_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._finish_prompt_accounting(
        second,
        response=SimpleNamespace(
            content="ok",
            usage_metadata={
                "prompt_cache_hit_tokens": 64,
                "prompt_cache_miss_tokens": 36,
                "completion_tokens": 3,
            },
        ),
    )

    reports = ledger.list_prompt_stability(session_id="session:stability")

    assert len(reports) == 2
    assert reports[-1].previous_report_ref == "pstability:modelreq:stability:1"
    assert reports[-1].first_changed_section["ordinal"] == 2
    assert reports[-1].diagnostics["likely_break_reason"] == "provider_cache_hit"
    assert reports[-1].provider_usage["cached_tokens"] == 64
    assert reports[-1].provider_usage["cache_hit_rate"] == 0.64


def test_model_runtime_records_prompt_cache_baseline_and_honors_reset(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    spec = ModelSpec(provider="deepseek", model="deepseek-v4-pro", api_key="key", base_url="https://api.deepseek.com/v1")
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "system", "content": "Session memory\n用户要求保护 prompt cache baseline。"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:cache-baseline",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": messages[0]["content"],
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_scope": "global",
                "cache_role": "cacheable_prefix",
                "prefix_tier": "provider_global",
                "compression_role": "preserve",
            },
            {
                "role": "system",
                "content": messages[1]["content"],
                "kind": "session_memory_stable",
                "source_ref": "memory.session_emphasis",
                "cache_scope": "session",
                "cache_role": "session_stable",
                "prefix_tier": "session",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": messages[2]["content"],
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_scope": "none",
                "cache_role": "volatile",
                "prefix_tier": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:cache-baseline:1",
            "session_id": "session:cache-baseline",
            "task_run_id": "taskrun:cache-baseline",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    reset = ledger.reset_prompt_cache_baseline(
        request_id="pcachebaseline-reset:runtime-test",
        session_id="session:cache-baseline",
        reason="context_compaction:microcompact",
        reset_ref="compact-receipt:runtime-test",
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:cache-baseline:2",
            "session_id": "session:cache-baseline",
            "task_run_id": "taskrun:cache-baseline",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    baselines = ledger.list_prompt_cache_baselines(session_id="session:cache-baseline")
    active = [record for record in baselines if record.status == "active"]

    assert len(active) == 2
    assert active[0].diagnostics["baseline_segments"]["memory"]["segment_count"] == 1
    assert reset.status == "invalidated"
    assert active[-1].generation == reset.generation
    assert active[-1].previous_baseline_ref == ""


def test_model_runtime_prompt_stability_detects_dynamic_param_change(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:param-stability",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            temperature=0.0,
        ),
        accounting_context={
            "request_id": "modelreq:param-stability:1",
            "session_id": "session:param-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            temperature=0.7,
        ),
        accounting_context={
            "request_id": "modelreq:param-stability:2",
            "session_id": "session:param-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    reports = ledger.list_prompt_stability(session_id="session:param-stability")
    latest = reports[-1]
    diff = latest.diagnostics["dynamic_param_diff"]

    assert latest.first_changed_section == {}
    assert latest.diagnostics["likely_break_reason"] == "dynamic_request_params_changed"
    assert latest.diagnostics["dynamic_params_changed"] is True
    assert diff["request_params"]["previous"]["temperature"] == 0.0
    assert diff["request_params"]["current"]["temperature"] == 0.7


def test_model_runtime_prompt_stability_ignores_client_only_timeout_changes(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:timeout-stability",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            timeout_seconds=10,
            max_retries=0,
        ),
        accounting_context={
            "request_id": "modelreq:timeout-stability:1",
            "session_id": "session:timeout-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
            timeout_seconds=30,
            max_retries=2,
        ),
        accounting_context={
            "request_id": "modelreq:timeout-stability:2",
            "session_id": "session:timeout-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    latest = ledger.list_prompt_stability(session_id="session:timeout-stability")[-1]

    assert latest.diagnostics["dynamic_params_changed"] is False
    assert "timeout_seconds" not in latest.dynamic_param_summary["request_params"]
    assert "max_retries" not in latest.dynamic_param_summary["request_params"]


def test_model_runtime_prompt_stability_records_tool_call_options(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    tool = {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:tool-option-stability",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()
    spec = ModelSpec(provider="deepseek", model="deepseek-v4-pro", api_key="key", base_url="https://api.deepseek.com/v1")

    runtime._begin_prompt_accounting(
        messages,
        tools=[tool],
        spec=spec,
        accounting_context={
            "request_id": "modelreq:tool-option-stability:1",
            "session_id": "session:tool-option-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="invoke_messages_with_tools",
        tool_call_options=ToolCallBindingOptions(parallel_tool_calls=False),
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=[tool],
        spec=spec,
        accounting_context={
            "request_id": "modelreq:tool-option-stability:2",
            "session_id": "session:tool-option-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="invoke_messages_with_tools",
        tool_call_options=ToolCallBindingOptions(
            tool_choice={"type": "function", "function": {"name": "write_file"}},
            parallel_tool_calls=False,
        ),
    )

    reports = ledger.list_prompt_stability(session_id="session:tool-option-stability")
    latest = reports[-1]
    current_options = latest.dynamic_param_summary["request_params"]["tool_call_options"]

    assert current_options["tool_choice"] == {"type": "function", "function": {"name": "write_file"}}
    assert current_options["parallel_tool_calls"] is False
    assert latest.diagnostics["likely_break_reason"] == "dynamic_request_params_changed"
    assert latest.diagnostics["dynamic_param_diff"]["request_params"]["previous"]["tool_call_options"] == {
        "parallel_tool_calls": False
    }


def test_model_runtime_prompt_stability_compares_same_run_before_session(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:session-cross-run-stability",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()
    spec = ModelSpec(provider="deepseek", model="deepseek-v4-pro", api_key="key", base_url="https://api.deepseek.com/v1")

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:session-cross-run-stability:1",
            "run_id": "run:first",
            "session_id": "session:cross-run-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )
    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:session-cross-run-stability:2",
            "run_id": "run:second",
            "session_id": "session:cross-run-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    reports = ledger.list_prompt_stability(session_id="session:cross-run-stability")

    assert reports[-1].previous_report_ref == ""
    assert reports[-1].diagnostics["has_previous_report"] is False

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=spec,
        accounting_context={
            "request_id": "modelreq:session-cross-run-stability:3",
            "run_id": "run:second",
            "session_id": "session:cross-run-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="turn_action",
    )

    reports = ledger.list_prompt_stability(session_id="session:cross-run-stability")

    assert reports[-1].previous_report_ref == "pstability:modelreq:session-cross-run-stability:2"
    assert reports[-1].diagnostics["has_previous_report"] is True


def test_model_runtime_prompt_stability_records_context_window_facts(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    segment_plan = build_prompt_segment_plan(
        packet_id="packet:context-window-stability",
        invocation_kind="turn_action",
        message_specs=[
            {
                "role": "system",
                "content": "stable runtime",
                "kind": "global_static",
                "source_ref": "runtime.test",
                "cache_role": "cacheable_prefix",
                "compression_role": "preserve",
            },
            {
                "role": "user",
                "content": "current request",
                "kind": "volatile_user",
                "source_ref": "turn.test",
                "cache_role": "volatile",
                "compression_role": "summarize",
            },
        ],
    ).to_dict()

    runtime._begin_prompt_accounting(
        messages,
        tools=None,
        spec=ModelSpec(provider="deepseek", model="deepseek-v4-pro", api_key="key", base_url="https://api.deepseek.com/v1"),
        accounting_context={
            "request_id": "modelreq:context-window-stability:1",
            "session_id": "session:context-window-stability",
            "source": "turn_action",
            "segment_plan": segment_plan,
            "prompt_manifest": {
                "context_window": {
                    "context_recovery_package_hash": "sha256:compressed",
                    "context_recovery_package_present": True,
                    "raw_history_message_count": 12,
                    "active_history_message_count": 12,
                }
            },
        },
        attempt=1,
        call_kind="turn_action",
    )

    report = ledger.list_prompt_stability(session_id="session:context-window-stability")[0]
    context_window = report.diagnostics["context_window"]

    assert report.compaction_generation == 1
    assert report.context_window_generation == 1
    assert context_window["context_recovery_package_hash"] == "sha256:compressed"
    assert context_window["raw_history_message_count"] == 12
    assert context_window["active_history_message_count"] == 12


def test_model_runtime_prompt_stability_keeps_deepseek_thinking_tool_choice(tmp_path: Path) -> None:
    runtime = _runtime(retries=0)
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    spec = ModelSpec(
        provider="deepseek",
        model="deepseek-v4-pro",
        api_key="key",
        base_url="https://api.deepseek.com/v1",
        thinking_mode="enabled",
    )

    runtime._begin_prompt_accounting(
        messages,
        tools=[tool],
        spec=spec,
        accounting_context={
            "request_id": "modelreq:thinking-tool-option-stability:1",
            "session_id": "session:thinking-tool-option-stability",
            "source": "turn_action",
        },
        attempt=1,
        call_kind="invoke_messages_with_tools",
        tool_call_options=ToolCallBindingOptions(
            tool_choice={"type": "function", "function": {"name": "read_file"}},
            parallel_tool_calls=False,
        ),
    )

    report = ledger.list_prompt_stability(session_id="session:thinking-tool-option-stability")[0]
    options = report.dynamic_param_summary["request_params"]["tool_call_options"]

    assert options == {
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "parallel_tool_calls": False,
    }


def test_model_runtime_prompt_stability_keeps_global_deepseek_thinking_tool_choice(tmp_path: Path) -> None:
    runtime = _runtime(retries=0, thinking_mode="enabled")
    ledger = PromptAccountingLedger(tmp_path)
    runtime.attach_prompt_accounting_ledger(ledger)
    messages = [
        {"role": "system", "content": "stable runtime"},
        {"role": "user", "content": "current request"},
    ]
    tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    runtime._begin_prompt_accounting(
        messages,
        tools=[tool],
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="key",
            base_url="https://api.deepseek.com/v1",
        ),
        accounting_context={
            "request_id": "modelreq:global-thinking-tool-option-stability:1",
            "session_id": "session:global-thinking-tool-option-stability",
            "source": "turn_action",
        },
        attempt=1,
        call_kind="invoke_messages_with_tools",
        tool_call_options=ToolCallBindingOptions(
            tool_choice={"type": "function", "function": {"name": "read_file"}},
            parallel_tool_calls=False,
        ),
    )

    report = ledger.list_prompt_stability(session_id="session:global-thinking-tool-option-stability")[0]
    options = report.dynamic_param_summary["request_params"]["tool_call_options"]

    assert options == {
        "tool_choice": {"type": "function", "function": {"name": "read_file"}},
        "parallel_tool_calls": False,
    }


def test_provider_cache_policy_disables_undeclared_openai_compatible_endpoint() -> None:
    resolver = ProviderCachePolicyResolver()

    official = resolver.resolve(
        provider="openai",
        model="gpt-4.1-mini",
        base_url="https://api.openai.com/v1",
    )
    compatible = resolver.resolve(
        provider="openai",
        model="compatible-model",
        base_url="https://example.invalid/v1",
    )
    deepseek = resolver.resolve(
        provider="deepseek",
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/v1",
    )

    assert official.mode == "automatic_prefix"
    assert deepseek.mode == "automatic_prefix"
    assert compatible.mode == "disabled"
    assert compatible.reason == "openai_compatible_endpoint_cache_support_not_declared_by_adapter"


