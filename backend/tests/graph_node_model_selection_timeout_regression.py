from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from harness.loop.model_action_runtime import call_model_invoker, model_action_timeout_seconds
from harness.loop.task_executor import _invoke_task_model_action, _task_model_selection
from agent_system.models.model_profile_models import AgentModelProfile
from agent_system.models.model_profile_resolver import ModelProfileResolver
from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile


class _StreamingModelRuntime:
    def __init__(self) -> None:
        self.invoke_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []

    async def invoke_messages(self, messages, **kwargs):
        self.invoke_calls.append({"messages": list(messages or []), "kwargs": dict(kwargs)})
        return SimpleNamespace(content='{"action_type":"respond","public_progress_note":"done","public_action_state":{"completion_status":"ready_to_finish"},"final_answer":"non-stream"}')

    async def astream_messages(self, messages, **kwargs):
        self.stream_calls.append({"messages": list(messages or []), "kwargs": dict(kwargs)})
        yield SimpleNamespace(content='{"action_type":"respond","public_progress_note":"done",')
        yield SimpleNamespace(content='"public_action_state":{"completion_status":"ready_to_finish"},"final_answer":"stream"}')


def test_model_action_uses_long_timeout_for_large_output_selection() -> None:
    timeout = model_action_timeout_seconds(
        SimpleNamespace(),
        model_selection={
            "max_output_tokens": 65536,
            "timeout_seconds": 180,
            "long_output_timeout_seconds": 600,
        },
    )

    assert timeout == 600


def test_graph_node_model_requirement_overrides_agent_profile_model_family() -> None:
    task_run = SimpleNamespace(
        diagnostics={
            "runtime_contract": {
                "runtime_profile": {
                    "model_requirement": {
                        "provider_family": "deepseek",
                        "model_family": "deepseek-v4-pro",
                        "preferred_output_tokens": 32768,
                        "thinking_mode": "disabled",
                    }
                }
            }
        }
    )
    agent_profile = SimpleNamespace(
        agent_profile_id="writing_modular_creator_runtime",
        model_profile=SimpleNamespace(
            to_dict=lambda: {
                "profile_id": "llm.deepseek.flash_long_output_65536",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "max_output_tokens": 65536,
                "timeout_seconds": 180,
                "long_output_timeout_seconds": 600,
                "thinking_mode": "disabled",
            }
        ),
    )

    selection = _task_model_selection(task_run, agent_profile=agent_profile)

    assert selection["provider"] == "deepseek"
    assert selection["model"] == "deepseek-v4-pro"
    assert selection["max_output_tokens"] == 32768
    assert selection["thinking_mode"] == "disabled"


def test_graph_node_model_requirement_enables_stream_policy() -> None:
    task_run = SimpleNamespace(
        diagnostics={
            "runtime_contract": {
                "runtime_profile": {
                    "model_requirement": {
                        "provider_family": "deepseek",
                        "model_family": "deepseek-v4-flash",
                        "preferred_output_tokens": 32768,
                        "thinking_mode": "disabled",
                        "streaming_required": True,
                    }
                }
            }
        }
    )
    agent_profile = SimpleNamespace(
        agent_profile_id="writing_modular_creator_runtime",
        model_profile=SimpleNamespace(
            to_dict=lambda: {
                "profile_id": "llm.deepseek.flash_long_output_65536",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "max_output_tokens": 65536,
                "timeout_seconds": 180,
                "long_output_timeout_seconds": 600,
                "thinking_mode": "disabled",
                "stream_policy": {"enabled": False},
            }
        ),
    )

    selection = _task_model_selection(task_run, agent_profile=agent_profile)

    assert selection["stream_policy"]["enabled"] is True
    assert selection["stream_policy"]["mode"] == "model_text_stream"
    assert selection["stream_policy"]["source"] == "node.contract_bindings.runtime.model_requirement.streaming_required"


def test_existing_graph_node_model_selection_is_enriched_from_runtime_contract_streaming_requirement() -> None:
    task_run = SimpleNamespace(
        diagnostics={
            "model_selection": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "max_output_tokens": 32768,
                "thinking_mode": "disabled",
            },
            "runtime_contract": {
                "runtime_profile": {
                    "model_requirement": {
                        "streaming_required": True,
                    }
                }
            },
        }
    )

    selection = _task_model_selection(task_run, agent_profile=None)

    assert selection["stream_policy"]["enabled"] is True
    assert selection["stream_policy"]["fallback_to_non_stream_on_error"] is True


def test_model_profile_resolver_compiles_streaming_requirement_into_resolved_spec() -> None:
    settings_service = SimpleNamespace(
        static=SimpleNamespace(
            llm_provider="deepseek",
            llm_model="deepseek-v4-flash",
            llm_api_key="test-key",
            llm_base_url="https://api.deepseek.com/v1",
            llm_timeout_seconds=180.0,
            llm_long_output_timeout_seconds=600.0,
            llm_max_retries=2,
            llm_max_output_tokens=65536,
            llm_thinking_mode="enabled",
            llm_reasoning_effort="auto",
        )
    )
    resolver = ModelProfileResolver(settings_service)
    profile = AgentRuntimeProfile(
        agent_profile_id="writing_modular_creator_runtime",
        agent_id="agent:writing_modular_creator",
        model_profile=AgentModelProfile(
            profile_id="llm.deepseek.flash_long_output_65536",
            provider="deepseek",
            model="deepseek-v4-flash",
            credential_ref="system:llm:primary",
            stream_policy={"enabled": False},
        ),
    )

    spec = resolver.resolve_model_spec(
        agent_runtime_profile=profile,
        model_requirement={"streaming_required": True, "thinking_mode": "disabled"},
    )

    assert spec.stream_policy["enabled"] is True
    assert spec.stream_policy["mode"] == "model_text_stream"
    assert spec.thinking_mode == "disabled"


def test_task_model_selection_drops_metadata_only_profile_payload() -> None:
    task_run = SimpleNamespace(
        diagnostics={
            "runtime_contract": {
                "runtime_profile": {},
            }
        }
    )
    agent_profile = SimpleNamespace(
        agent_profile_id="main_interactive_agent",
        model_profile=SimpleNamespace(
            to_dict=lambda: {
                "profile_id": "system-default",
                "stream_policy": {},
            }
        ),
    )

    selection = _task_model_selection(task_run, agent_profile=agent_profile)

    assert selection == {}


def test_task_model_action_uses_streamer_when_stream_policy_enabled() -> None:
    runtime = _StreamingModelRuntime()
    packet = SimpleNamespace(
        packet_id="packet:test",
        model_messages=[{"role": "user", "content": "choose next action"}],
        allowed_action_types=("respond",),
        segment_plan={},
        diagnostics={},
    )

    action_request, protocol = asyncio.run(
        _invoke_task_model_action(
            model_runtime=runtime,
            packet=packet,
            task_run_id="taskrun:test",
            session_id="session:test",
            invocation_index=1,
            model_selection={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "stream_policy": {"enabled": True},
            },
        )
    )

    assert protocol["status"] == "accepted"
    assert action_request is not None
    assert action_request.action_type == "respond"
    assert action_request.final_answer == "stream"
    assert len(runtime.stream_calls) == 1
    assert runtime.invoke_calls == []
    assert runtime.stream_calls[0]["kwargs"]["model_spec"]["stream_policy"]["enabled"] is True


def test_model_invoker_does_not_pass_metadata_only_model_selection() -> None:
    calls: list[dict[str, object]] = []

    async def _invoker(messages, **kwargs):
        calls.append({"messages": list(messages or []), "kwargs": dict(kwargs)})
        return SimpleNamespace(content="{}")

    asyncio.run(
        call_model_invoker(
            _invoker,
            [{"role": "user", "content": "hello"}],
            model_selection={"diagnostics": {"authority": "test.metadata_only"}},
            accounting_context={"source": "test"},
        )
    )

    assert calls
    kwargs = dict(calls[0]["kwargs"])
    assert "model_spec" not in kwargs
    assert kwargs["accounting_context"] == {"source": "test"}


def test_model_invoker_does_not_retry_bare_call_after_internal_type_error() -> None:
    calls: list[dict[str, object]] = []

    async def _invoker(messages, *, model_spec=None, accounting_context=None):
        calls.append(
            {
                "messages": list(messages or []),
                "model_spec": dict(model_spec or {}),
                "accounting_context": dict(accounting_context or {}),
            }
        )
        if accounting_context is not None:
            raise TypeError("accounting_context exploded inside provider adapter")
        return SimpleNamespace(content="{}")

    with pytest.raises(TypeError, match="accounting_context exploded"):
        asyncio.run(
            call_model_invoker(
                _invoker,
                [{"role": "user", "content": "hello"}],
                model_selection={"provider": "deepseek", "model": "deepseek-v4-pro"},
                accounting_context={"source": "test"},
            )
        )

    assert len(calls) == 1
    assert calls[0]["model_spec"] == {"provider": "deepseek", "model": "deepseek-v4-pro"}
    assert calls[0]["accounting_context"] == {"source": "test"}
