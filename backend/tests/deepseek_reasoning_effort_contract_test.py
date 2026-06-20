from __future__ import annotations

from types import SimpleNamespace

from config import _resolve_llm_reasoning_effort
from runtime.model_gateway.providers.deepseek import DeepSeekProviderAdapter
from runtime.model_gateway.providers.models import ProviderRequestProfile


def _profile(reasoning_effort: str) -> ProviderRequestProfile:
    return ProviderRequestProfile(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        thinking_mode="enabled",
        reasoning_effort=reasoning_effort,
    )


def test_deepseek_adapter_omits_auto_reasoning_effort_from_request_params() -> None:
    adapter = DeepSeekProviderAdapter()

    for value in ("", "auto", "default", "adaptive"):
        result = adapter.build(_profile(value))
        assert "reasoning_effort" not in result.model_kwargs
        assert "reasoning_effort" not in result.request_params_for_accounting


def test_deepseek_adapter_normalizes_official_reasoning_effort_values() -> None:
    adapter = DeepSeekProviderAdapter()

    assert adapter.build(_profile("max")).request_params_for_accounting["reasoning_effort"] == "max"
    assert adapter.build(_profile("xhigh")).request_params_for_accounting["reasoning_effort"] == "max"
    assert adapter.build(_profile("high")).request_params_for_accounting["reasoning_effort"] == "high"
    assert adapter.build(_profile("medium")).request_params_for_accounting["reasoning_effort"] == "high"
    assert adapter.build(_profile("low")).request_params_for_accounting["reasoning_effort"] == "high"


def test_settings_reasoning_effort_default_is_unset(monkeypatch) -> None:
    import config as config_module

    monkeypatch.setattr(config_module, "_runtime_system_value", lambda *_args, **_kwargs: "")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)

    assert _resolve_llm_reasoning_effort() == ""


def test_model_runtime_normalizes_auto_to_no_provider_reasoning_effort() -> None:
    from runtime.model_gateway.model_runtime import ModelRuntime, ModelSpec

    runtime = ModelRuntime(SimpleNamespace(static=SimpleNamespace(llm_reasoning_effort="auto")))
    spec = ModelSpec(provider="deepseek", model="deepseek-v4-flash", api_key="test", base_url="https://api.deepseek.com", reasoning_effort=None)

    assert runtime._reasoning_effort_for_spec(spec) == ""
