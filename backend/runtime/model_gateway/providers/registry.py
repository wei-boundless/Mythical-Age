from __future__ import annotations

from .deepseek import DeepSeekProviderAdapter
from .models import ProviderAdapterResult, ProviderCapabilityError, ProviderCapabilityProfile, ProviderRequestProfile
from .openai_compatible import OpenAICompatibleProviderAdapter


def adapter_for_provider(provider: str):
    normalized = str(provider or "").strip().lower()
    if normalized == "deepseek":
        return DeepSeekProviderAdapter()
    return OpenAICompatibleProviderAdapter()


def build_provider_adapter_result(profile: ProviderRequestProfile) -> ProviderAdapterResult:
    _validate_provider_request_profile(profile)
    return adapter_for_provider(profile.provider).build(profile)


def provider_capabilities_for(*, provider: str, model: str) -> ProviderCapabilityProfile:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower().split("/")[-1]
    if normalized_provider == "deepseek":
        is_deepseek_v4 = normalized_model in {"deepseek-v4-pro", "deepseek-v4-flash"}
        context_presets = ("deepseek_1m", "long_128k", "standard") if is_deepseek_v4 else ("long_128k", "standard")
        return ProviderCapabilityProfile(
            provider=normalized_provider,
            model=normalized_model,
            supports_json_output=True,
            supports_tool_calling=True,
            supports_strict_tools=True,
            supports_chat_prefix=True,
            supported_context_budget_presets=context_presets,
            preferred_context_budget_preset="deepseek_1m" if is_deepseek_v4 else "long_128k",
            diagnostics={"capability_source": "runtime.model_gateway.providers.deepseek", "deepseek_v4_1m": is_deepseek_v4},
        )
    if normalized_provider in {"openai", "bailian", "google", "openrouter"}:
        return ProviderCapabilityProfile(
            provider=normalized_provider,
            model=normalized_model,
            supports_json_output=True,
            supports_tool_calling=True,
            supports_strict_tools=normalized_provider in {"openai", "bailian"},
            supported_context_budget_presets=("long_128k", "standard"),
            preferred_context_budget_preset="long_128k",
            diagnostics={"capability_source": "runtime.model_gateway.providers.openai_compatible"},
        )
    return ProviderCapabilityProfile(
        provider=normalized_provider,
        model=normalized_model,
        supported_context_budget_presets=("standard",),
        preferred_context_budget_preset="standard",
        diagnostics={"capability_source": "runtime.model_gateway.providers.default"},
    )


def _validate_provider_request_profile(profile: ProviderRequestProfile) -> None:
    capabilities = provider_capabilities_for(provider=profile.provider, model=profile.model)
    if profile.normalized_response_format() and not capabilities.supports_json_output:
        raise ProviderCapabilityError(provider=profile.provider, model=profile.model, feature="json_output")
    strict_tool_schema = bool(dict(profile.provider_extensions or {}).get("strict_tool_schema") is True)
    if strict_tool_schema and not capabilities.supports_strict_tools:
        raise ProviderCapabilityError(provider=profile.provider, model=profile.model, feature="strict_tool_schema")
