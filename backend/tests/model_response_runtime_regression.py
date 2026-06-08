from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from runtime.model_gateway.model_runtime import ModelRuntimeError
from runtime.shared.action_request import build_tool_action_request
from orchestration import RuntimeDirective
from harness.runtime.runtime_policy import model_stream_policy_from_task_execution_assembly


def _directive() -> RuntimeDirective:
    return RuntimeDirective(
        directive_id="directive:test",
        task_id="task:test",
        plan_ref="plan:test",
        stage_ref="stage:test",
        executor_type="model",
        adopted_resource_policy_ref="resource:test",
        execution_graph_ref="graph:test",
    )


class _RecoveringRuntime:
    def __init__(self) -> None:
        self.invoke_count = 0

    async def astream_messages(self, _messages):
        yield SimpleNamespace(content="partial")
        raise ModelRuntimeError(
            code="provider_unavailable",
            provider="deepseek",
            model="deepseek-v4-pro",
            detail="ReadError",
            retryable=True,
            user_message="模型服务暂时不可用，请稍后重试。",
        )

    async def invoke_messages(self, _messages):
        self.invoke_count += 1
        return SimpleNamespace(content="complete recovered content")


class _RecoveringBeforeDeltaRuntime:
    def __init__(self) -> None:
        self.invoke_count = 0

    async def astream_messages(self, _messages):
        if False:
            yield SimpleNamespace(content="unused")
        raise ModelRuntimeError(
            code="provider_unavailable",
            provider="deepseek",
            model="deepseek-v4-pro",
            detail="ReadError",
            retryable=True,
            user_message="模型服务暂时不可用，请稍后重试。",
        )

    async def invoke_messages(self, _messages):
        self.invoke_count += 1
        return SimpleNamespace(content="complete recovered content")


class _HangingRecoveryRuntime:
    async def astream_messages(self, _messages):
        yield SimpleNamespace(content="partial")
        raise ModelRuntimeError(
            code="provider_unavailable",
            provider="deepseek",
            model="deepseek-v4-pro",
            detail="ReadError",
            retryable=True,
            user_message="模型服务暂时不可用，请稍后重试。",
        )

    async def invoke_messages(self, _messages):
        await asyncio.sleep(10)
        return SimpleNamespace(content="late recovered content")


class _HangingRuntime:
    async def invoke_messages(self, _messages):
        await asyncio.sleep(10)
        return SimpleNamespace(content="late content")


class _HangingStreamRuntime:
    async def astream_messages(self, _messages):
        await asyncio.sleep(10)
        yield SimpleNamespace(content="late stream content")

    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="unused fallback")


class _PartialThenHangingStreamRuntime:
    async def astream_messages(self, _messages):
        yield SimpleNamespace(content="partial answer")
        await asyncio.sleep(10)
        yield SimpleNamespace(content="late stream content")

    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="unused fallback")


class _ReasoningOnlyToolStreamRuntime:
    async def astream_messages_with_tools(self, _messages, _tools, **_kwargs):
        yield SimpleNamespace(content="", additional_kwargs={"reasoning_content": "hidden chain"})

    async def invoke_messages(self, _messages):
        return SimpleNamespace(content="unused fallback")


class _CapturingSpecRuntime:
    def __init__(self) -> None:
        self.seen_model_spec = None

    async def invoke_messages(self, _messages, **kwargs):
        self.seen_model_spec = kwargs.get("model_spec")
        return SimpleNamespace(content="bounded spec ok")

    async def invoke_messages_with_tools(self, _messages, _tools, **kwargs):
        self.seen_model_spec = kwargs.get("model_spec")
        return SimpleNamespace(content="bounded spec ok")


class _BlockingForcedToolRuntime:
    async def invoke_messages(self, _messages):
        time.sleep(10)
        return SimpleNamespace(content="late blocking content")


class _NonStreamingRuntime:
    def __init__(self) -> None:
        self.invoke_count = 0

    async def invoke_messages(self, _messages):
        self.invoke_count += 1
        return SimpleNamespace(content="non-stream fallback content")


def test_stream_retryable_error_with_partial_output_suppresses_non_stream_fallback() -> None:
    runtime = _RecoveringRuntime()
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True, "fallback_to_non_stream_on_error": True},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "assistant_text_delta" and event.get("content") == "partial" for event in events)
    assert any(
        event.get("type") == "stream_recovery"
        and event.get("status") == "suppressed"
        and event.get("reason") == "partial_output_already_emitted"
        for event in events
    )
    assert runtime.invoke_count == 0
    assert events[-1]["type"] == "error"
    assert events[-1]["answer_channel"] == "orchestration_fail_closed"


def test_stream_retryable_error_without_partial_output_falls_back_to_real_non_stream_invoke() -> None:
    runtime = _RecoveringBeforeDeltaRuntime()
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True, "fallback_to_non_stream_on_error": True},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert runtime.invoke_count == 1
    assert any(
        event.get("type") == "stream_recovery" and event.get("status") == "recovered"
        for event in events
    )
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "complete recovered content"


def test_stream_recovery_with_partial_output_does_not_start_hanging_fallback() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_HangingRecoveryRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={
                "enabled": True,
                "fallback_to_non_stream_on_error": True,
                "non_stream_fallback_timeout_seconds": 0.01,
            },
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "assistant_text_delta" and event.get("content") == "partial" for event in events)
    assert any(
        event.get("type") == "stream_recovery"
        and event.get("status") == "suppressed"
        and event.get("reason") == "partial_output_already_emitted"
        for event in events
    )
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "模型服务暂时不可用，请稍后重试。"
    assert events[-1]["answer_channel"] == "orchestration_fail_closed"


def test_non_stream_model_response_has_hard_timeout() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_HangingRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"model_response_timeout_seconds": 0.01},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "model_response_timeout"
    assert events[-1]["answer_channel"] == "orchestration_fail_closed"


def test_stream_model_response_has_hard_timeout() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_HangingStreamRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True, "model_response_timeout_seconds": 0.01},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "model_response_timeout"
    assert events[-1]["answer_channel"] == "orchestration_fail_closed"


def test_stream_model_response_timeout_after_partial_output_commits_partial_done() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_PartialThenHangingStreamRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True, "model_response_timeout_seconds": 0.01},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert any(event.get("type") == "assistant_text_delta" and event.get("content") == "partial answer" for event in events)
    assert not any(event.get("type") == "error" and event.get("error") == "model_response_timeout" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "partial answer"
    assert events[-1]["completion_state"] == "partial_timeout"
    assert events[-1]["terminal_reason"] == "model_response_timeout_after_partial_output"
    assert events[-1]["answer_canonical_state"] == "partial_timeout"


def test_stream_preview_does_not_emit_hidden_reasoning_content() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_ReasoningOnlyToolStreamRuntime())

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            tool_instances=[SimpleNamespace(name="inspect")],
            model_stream_policy={"enabled": True},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert not any(
        event.get("type") == "assistant_text_delta" and event.get("content") == "hidden chain"
        for event in events
    )


def test_tool_action_request_does_not_surface_hidden_reasoning_preview() -> None:
    request = build_tool_action_request(
        "task-run:test",
        {
            "tool_call": {"name": "inspect", "args": {"path": "README.md"}},
            "assistant_content": "",
            "assistant_additional_kwargs": {"reasoning_content": "hidden chain"},
        },
    )

    assert request.payload["assistant_content_preview"] == ""
    assert "assistant_reasoning_preview" not in request.payload
    assert request.payload["assistant_additional_kwargs"] == {"reasoning_content": "hidden chain"}
    assert request.payload["assistant_protocol_message"]["reasoning_content"] == "hidden chain"


def test_model_response_policy_caps_underlying_model_spec_timeout() -> None:
    runtime = _CapturingSpecRuntime()
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)
    original_spec = SimpleNamespace(
        provider="test",
        model="test-model",
        api_key="key",
        base_url="https://example.invalid/v1",
        max_output_tokens=65536,
        timeout_seconds=240.0,
        long_output_timeout_seconds=360.0,
        max_retries=2,
        temperature=0.0,
        thinking_mode="disabled",
        reasoning_effort="high",
        stream_policy={},
        source_chain=("test",),
        diagnostics={"source": "unit"},
    )

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            tool_instances=[SimpleNamespace(name="write_file")],
            model_spec=original_spec,
            model_stream_policy={
                "model_response_timeout_seconds": 0.05,
                "forced_tool_timeout_applied": True,
            },
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[-1]["type"] == "done"
    assert original_spec.timeout_seconds == 240.0
    assert runtime.seen_model_spec is not original_spec
    assert runtime.seen_model_spec.timeout_seconds == 0.05
    assert runtime.seen_model_spec.long_output_timeout_seconds == 0.05
    assert runtime.seen_model_spec.max_retries == 0
    assert runtime.seen_model_spec.diagnostics["runtime_policy_timeout_applied"] is True


def test_forced_tool_choice_keeps_deepseek_thinking_for_forced_tool_round() -> None:
    runtime = _CapturingSpecRuntime()
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)
    original_spec = SimpleNamespace(
        provider="deepseek",
        model="deepseek-v4-pro",
        api_key="key",
        base_url="https://api.deepseek.com/v1",
        max_output_tokens=65536,
        timeout_seconds=240.0,
        long_output_timeout_seconds=360.0,
        max_retries=2,
        temperature=0.0,
        thinking_mode="enabled",
        reasoning_effort="high",
        stream_policy={},
        source_chain=("test",),
        diagnostics={"source": "unit"},
    )

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="write",
            model_messages=[{"role": "user", "content": "write"}],
            directive=_directive(),
            tool_instances=[SimpleNamespace(name="write_file")],
            tool_call_options={
                "tool_choice": {"type": "function", "function": {"name": "write_file"}},
                "parallel_tool_calls": False,
            },
            model_spec=original_spec,
            model_stream_policy={
                "model_response_timeout_seconds": 0.05,
                "forced_tool_timeout_applied": True,
            },
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert events[-1]["type"] == "done"
    assert original_spec.thinking_mode == "enabled"
    assert runtime.seen_model_spec.thinking_mode == "enabled"
    assert runtime.seen_model_spec.max_retries == 0
    assert runtime.seen_model_spec.diagnostics["forced_tool_choice_name"] == "write_file"
    assert "deepseek_thinking_disabled_for_forced_tool_choice" not in runtime.seen_model_spec.diagnostics


def test_forced_tool_model_timeout_survives_blocking_async_invoker() -> None:
    executor = ModelResponseRuntimeExecutor(model_runtime=_BlockingForcedToolRuntime())

    async def _collect():
        events = []
        started = time.monotonic()
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={
                "model_response_timeout_seconds": 0.05,
                "forced_tool_timeout_applied": True,
            },
        ):
            events.append(event)
        return events, time.monotonic() - started

    events, elapsed = asyncio.run(_collect())

    assert elapsed < 1.0
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "model_response_timeout"


def test_stream_enabled_runtime_without_stream_method_uses_non_stream_invoke() -> None:
    runtime = _NonStreamingRuntime()
    executor = ModelResponseRuntimeExecutor(model_runtime=runtime)

    async def _collect():
        events = []
        async for event in executor.stream(
            user_message="run",
            model_messages=[{"role": "user", "content": "run"}],
            directive=_directive(),
            model_stream_policy={"enabled": True},
        ):
            events.append(event)
        return events

    events = asyncio.run(_collect())

    assert runtime.invoke_count == 1
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "non-stream fallback content"
    assert not any(event.get("type") == "stream_recovery" for event in events)


def test_task_stream_policy_preserves_recovery_timeout_fields() -> None:
    policy = model_stream_policy_from_task_execution_assembly(
        {
            "metadata": {
                "stream_policy": {
                    "enabled": True,
                    "mode": "model_text_stream",
                    "non_stream_fallback_timeout_seconds": 240,
                    "stream_recovery_timeout_seconds": 240,
                }
            }
        }
    )

    assert policy["enabled"] is True
    assert policy["non_stream_fallback_timeout_seconds"] == 240
    assert policy["stream_recovery_timeout_seconds"] == 240


