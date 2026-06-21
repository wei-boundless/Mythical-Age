from __future__ import annotations

import asyncio
from types import SimpleNamespace

from orchestration.runtime_directive import RuntimeDirective
from runtime.model_gateway.model_response import ModelResponseRuntimeExecutor
from runtime.model_gateway.model_runtime import ModelRuntimeError


def _directive() -> RuntimeDirective:
    return RuntimeDirective(
        directive_id="directive:model-response-recovery",
        task_id="task:model-response-recovery",
        plan_ref="plan:model-response-recovery",
        stage_ref="stage:model-response-recovery",
        executor_type="model",
        adopted_resource_policy_ref="policy:model-response-recovery",
        diagnostics={
            "task_run_id": "taskrun:model-response-recovery",
            "turn_id": "turn:model-response-recovery",
            "turn_run_id": "turnrun:model-response-recovery",
            "model_request_id": "modelreq:model-response-recovery",
        },
    )


def _stream_policy() -> dict[str, object]:
    return {
        "enabled": True,
        "emit_assistant_text_delta": True,
        "upstream_reconnect_enabled": True,
        "partial_stream_recovery": "continue_from_visible_prefix",
        "chunk_strategy": "typing",
        "max_flush_interval_ms": 0,
        "max_pending_utf8_bytes": 24,
        "partial_stream_recovery_attempts": 2,
    }


def _model_spec() -> dict[str, object]:
    return {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    }


def _retryable_stream_error() -> ModelRuntimeError:
    return ModelRuntimeError(
        code="provider_unavailable",
        provider="deepseek",
        model="deepseek-chat",
        detail="provider stream disconnected",
        retryable=True,
        user_message="provider stream disconnected",
    )


async def _collect(model_runtime: object) -> list[dict[str, object]]:
    executor = ModelResponseRuntimeExecutor(model_runtime=model_runtime)
    events: list[dict[str, object]] = []
    async for event in executor.stream(
        user_message="Continue.",
        model_messages=[{"role": "user", "content": "Continue."}],
        directive=_directive(),
        model_stream_policy=_stream_policy(),
        model_spec=_model_spec(),
    ):
        events.append(event)
    return events


async def _collect_with_tools(model_runtime: object) -> list[dict[str, object]]:
    executor = ModelResponseRuntimeExecutor(model_runtime=model_runtime)
    events: list[dict[str, object]] = []
    async for event in executor.stream(
        user_message="Continue.",
        model_messages=[{"role": "user", "content": "Continue."}],
        directive=_directive(),
        tool_instances=[SimpleNamespace(name="read_file")],
        model_stream_policy=_stream_policy(),
        model_spec=_model_spec(),
    ):
        events.append(event)
    return events


def test_model_response_recovers_partial_provider_stream_from_visible_prefix() -> None:
    class InterruptedModel:
        def __init__(self) -> None:
            self.invoke_messages_seen: list[list[dict[str, object]]] = []
            self.invoke_model_specs_seen: list[object] = []

        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="Already")
            raise _retryable_stream_error()

        async def invoke_messages(self, messages, **kwargs):
            self.invoke_messages_seen.append([dict(item) for item in list(messages or []) if isinstance(item, dict)])
            self.invoke_model_specs_seen.append(kwargs.get("model_spec"))
            return SimpleNamespace(content="Already done")

    model = InterruptedModel()
    events = asyncio.run(_collect(model))
    streamed_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta")
    recovery_events = [event for event in events if event.get("type") == "stream_recovery"]
    done = next(event for event in events if event.get("type") == "done")

    assert streamed_text == "Already done"
    assert [event.get("status") for event in recovery_events] == ["started", "completed"]
    assert recovery_events[-1]["reason"] == "continued_from_visible_prefix"
    assert done["content"] == "Already done"
    assert not [event for event in events if event.get("type") == "error"]
    assert model.invoke_messages_seen[-1][-1]["role"] == "assistant"
    assert model.invoke_messages_seen[-1][-1]["content"] == "Already"
    assert model.invoke_messages_seen[-1][-1]["prefix"] is True
    completion_profile = dict(getattr(model.invoke_model_specs_seen[-1], "completion_profile", {}) or {})
    assert completion_profile == {
        "mode": "chat_prefix",
        "provider_mode": "deepseek_chat_prefix",
        "source": "partial_stream_recovery",
    }


def test_model_response_falls_back_to_plain_continuation_when_prefix_recovery_fails() -> None:
    class PrefixFailingModel:
        def __init__(self) -> None:
            self.invoke_messages_seen: list[list[dict[str, object]]] = []
            self.invoke_model_specs_seen: list[object] = []

        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="Already")
            raise _retryable_stream_error()

        async def invoke_messages(self, messages, **kwargs):
            model_spec = kwargs.get("model_spec")
            self.invoke_messages_seen.append([dict(item) for item in list(messages or []) if isinstance(item, dict)])
            self.invoke_model_specs_seen.append(model_spec)
            completion_profile = (
                dict(model_spec.get("completion_profile") or {})
                if isinstance(model_spec, dict)
                else dict(getattr(model_spec, "completion_profile", {}) or {})
            )
            if completion_profile.get("mode") == "chat_prefix":
                raise ModelRuntimeError(
                    code="provider_unavailable",
                    provider="deepseek",
                    model="deepseek-chat",
                    detail="prefix recovery unavailable",
                    retryable=True,
                    user_message="prefix recovery unavailable",
                )
            return SimpleNamespace(content="Already done")

    model = PrefixFailingModel()
    events = asyncio.run(_collect(model))
    streamed_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta")
    recovery_events = [event for event in events if event.get("type") == "stream_recovery"]
    done = next(event for event in events if event.get("type") == "done")

    assert streamed_text == "Already done"
    assert recovery_events[-1]["reason"] == "continued_from_visible_prefix"
    assert recovery_events[-1]["fallback_mode"] == "plain_continuation"
    assert done["content"] == "Already done"
    assert len(model.invoke_messages_seen) >= 3
    assert model.invoke_messages_seen[-1][-1]["role"] == "user"
    assert "不要重复已经公开的文字" in model.invoke_messages_seen[-1][-1]["content"]
    last_spec = model.invoke_model_specs_seen[-1]
    if isinstance(last_spec, dict):
        assert "completion_profile" not in last_spec
    else:
        assert getattr(last_spec, "completion_profile", None) is None


def test_model_response_fails_when_recovery_call_fails() -> None:
    class RecoveryFailingModel:
        async def astream_messages(self, _messages, **_kwargs):
            yield SimpleNamespace(content="Visible prefix")
            raise _retryable_stream_error()

        async def invoke_messages(self, _messages, **_kwargs):
            raise ModelRuntimeError(
                code="provider_unavailable",
                provider="deepseek",
                model="deepseek-chat",
                detail="recovery provider unavailable",
                retryable=True,
                user_message="recovery provider unavailable",
            )

    events = asyncio.run(_collect(RecoveryFailingModel()))
    streamed_text = "".join(str(event.get("content") or "") for event in events if event.get("type") == "assistant_text_delta")
    recovery_events = [event for event in events if event.get("type") == "stream_recovery"]
    error_events = [event for event in events if event.get("type") == "error"]
    done_events = [event for event in events if event.get("type") == "done"]

    assert streamed_text == "Visible prefix"
    assert recovery_events[-1]["status"] == "failed"
    assert recovery_events[-1]["reason"] == "partial_stream_recovery_failed"
    assert recovery_events[-1]["recovery_call_status"] == "failed"
    assert error_events[-1]["code"] == "partial_stream_recovery_failed"
    assert error_events[-1]["content"] == "运行中断"
    assert done_events == []


def test_model_response_keeps_non_stream_fallback_when_no_public_prefix_exists() -> None:
    class FallbackModel:
        async def astream_messages(self, _messages, **_kwargs):
            raise _retryable_stream_error()
            yield SimpleNamespace(content="unreachable")

        async def invoke_messages(self, _messages, **_kwargs):
            return SimpleNamespace(content="Fallback answer")

    events = asyncio.run(_collect(FallbackModel()))
    recovery_events = [event for event in events if event.get("type") == "stream_recovery"]
    done = next(event for event in events if event.get("type") == "done")

    assert [event.get("reason") for event in recovery_events] == [
        "retryable_stream_error",
        "non_stream_fallback_succeeded",
    ]
    assert done["content"] == "Fallback answer"


def test_model_response_does_not_non_stream_fallback_tool_protocol_after_stream_error() -> None:
    class ToolProtocolStreamFailureModel:
        async def astream_messages_with_tools(self, _messages, _tools, **_kwargs):
            raise _retryable_stream_error()
            yield SimpleNamespace(content="unreachable")

        async def invoke_messages_with_tools(self, _messages, _tools, **_kwargs):
            raise AssertionError("tool protocol fallback must not re-invoke non-stream tools")

        async def invoke_messages(self, _messages, **_kwargs):
            raise AssertionError("tool protocol fallback must not switch to plain non-stream")

    events = asyncio.run(_collect_with_tools(ToolProtocolStreamFailureModel()))
    recovery_events = [event for event in events if event.get("type") == "stream_recovery"]
    error_events = [event for event in events if event.get("type") == "error"]
    done_events = [event for event in events if event.get("type") == "done"]

    assert recovery_events[-1]["status"] == "suppressed"
    assert recovery_events[-1]["reason"] == "non_stream_fallback_disabled_for_tool_protocol"
    assert error_events[-1]["code"] == "provider_unavailable"
    assert error_events[-1]["content"] == "运行中断"
    assert done_events == []
