from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from harness.loop.model_action_runtime import call_model_invoker, model_action_timeout_seconds
from harness.loop.task_executor import _task_model_selection


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
