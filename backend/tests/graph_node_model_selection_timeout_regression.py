from __future__ import annotations

from types import SimpleNamespace

from harness.loop.model_action_runtime import model_action_timeout_seconds
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
            "runtime_task_selection": {
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
