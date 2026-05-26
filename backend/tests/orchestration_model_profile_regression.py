from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.models.model_profile_resolver import ModelProfileResolver
from runtime.agent_runtime.invocation_loop import _chat_model_selection_runtime_defaults


class _SettingsService:
    def __init__(self) -> None:
        self.static = SimpleNamespace(
            llm_provider="deepseek",
            llm_model="deepseek-v4-pro",
            llm_api_key="deepseek-key",
            llm_base_url="https://api.deepseek.com/v1",
            llm_fallback_provider="openai",
            llm_fallback_model="gpt-4.1-mini",
            llm_fallback_api_key="openai-key",
            llm_fallback_base_url="https://api.openai.com/v1",
            llm_timeout_seconds=45,
            llm_long_output_timeout_seconds=360,
            llm_max_retries=1,
            llm_max_output_tokens=32768,
            llm_thinking_mode="disabled",
            llm_reasoning_effort="high",
        )


def test_agent_runtime_profile_round_trips_model_profile(tmp_path: Path) -> None:
    registry = AgentRuntimeRegistry(tmp_path)

    profile = registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        allowed_runtime_lanes=("standard_task",),
        allowed_operations=("op.model_response",),
        model_profile={
            "profile_id": "deepseek_long_output",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://legacy-agent-endpoint.example/v1",
            "credential_ref": "provider:deepseek:primary",
            "max_output_tokens": 65536,
            "capability_tags": ["long_output", "reasoning"],
        },
    )

    loaded = registry.get_profile("agent:0")

    assert profile.model_profile.profile_id == "deepseek_long_output"
    assert loaded is not None
    assert loaded.model_profile.provider == "deepseek"
    assert loaded.model_profile.max_output_tokens == 65536
    assert "base_url" not in loaded.model_profile.to_dict()
    assert "api_key" not in loaded.model_profile.to_dict()


def test_agent_runtime_profile_rejects_raw_model_secret(tmp_path: Path) -> None:
    registry = AgentRuntimeRegistry(tmp_path)

    with pytest.raises(ValueError, match="credential_ref"):
        registry.upsert_profile(
            agent_id="agent:0",
            agent_profile_id="main_interactive_agent",
            allowed_runtime_lanes=("standard_task",),
            allowed_operations=("op.model_response",),
            model_profile={"provider": "deepseek", "api_key": "raw-secret"},
        )


def test_model_profile_resolver_inherits_system_and_applies_requirement() -> None:
    resolver = ModelProfileResolver(_SettingsService())
    runtime_profile = SimpleNamespace(
        agent_id="agent:writer",
        agent_profile_id="writer_runtime",
        model_profile=SimpleNamespace(
            profile_id="writer_long",
            provider="deepseek",
            model="deepseek-v4-pro",
            credential_ref="provider:deepseek:primary",
            max_output_tokens=32768,
            timeout_seconds=None,
            long_output_timeout_seconds=500,
            max_retries=0,
            temperature=0.7,
            thinking_mode="disabled",
            reasoning_effort="high",
            stream_policy={},
            capability_tags=("long_output",),
        ),
    )

    resolved = resolver.resolve_model_spec(
        agent_runtime_profile=runtime_profile,
        model_requirement={
            "profile_ref": "writer_long",
            "preferred_output_tokens": 65536,
            "thinking_mode": "disabled",
        },
        runtime_lane="long_generation",
    )
    public = resolved.to_public_dict()

    assert resolved.provider == "deepseek"
    assert resolved.base_url == "https://api.deepseek.com/v1"
    assert resolved.api_key == "deepseek-key"
    assert resolved.max_output_tokens == 65536
    assert resolved.long_output_timeout_seconds == 500
    assert public["credential_configured"] is True
    assert "api_key" not in str(public).lower()


def test_chat_model_selection_defaults_keep_deepseek_thinking_controls() -> None:
    defaults = _chat_model_selection_runtime_defaults(
        {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com/v1",
            "credential_ref": "provider:deepseek:primary",
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
        }
    )

    assert defaults == {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com/v1",
        "credential_ref": "provider:deepseek:primary",
        "thinking_mode": "enabled",
        "reasoning_effort": "max",
    }


def test_model_profile_resolver_does_not_let_agent_base_url_override_provider_endpoint() -> None:
    resolver = ModelProfileResolver(_SettingsService())
    runtime_profile = SimpleNamespace(
        agent_id="agent:writer",
        agent_profile_id="writer_runtime",
        model_profile=SimpleNamespace(
            profile_id="writer_openai",
            provider="openai",
            model="gpt-4.1-mini",
            base_url="https://legacy-agent-endpoint.example/v1",
            credential_ref="provider:openai:primary",
            max_output_tokens=None,
            timeout_seconds=None,
            long_output_timeout_seconds=None,
            max_retries=None,
            temperature=None,
            thinking_mode="",
            reasoning_effort="",
            stream_policy={},
            capability_tags=(),
        ),
    )

    resolved = resolver.resolve_model_spec(agent_runtime_profile=runtime_profile)
    public = resolved.to_public_dict()

    assert resolved.provider == "openai"
    assert resolved.base_url == "https://api.openai.com/v1"
    assert "agent_runtime_profile.model_profile.base_url" not in public["source_chain"]
