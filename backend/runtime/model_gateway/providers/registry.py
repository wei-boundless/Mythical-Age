from __future__ import annotations

from .deepseek import DeepSeekProviderAdapter
from .models import ProviderAdapterResult, ProviderRequestProfile
from .openai_compatible import OpenAICompatibleProviderAdapter


def adapter_for_provider(provider: str):
    normalized = str(provider or "").strip().lower()
    if normalized == "deepseek":
        return DeepSeekProviderAdapter()
    return OpenAICompatibleProviderAdapter()


def build_provider_adapter_result(profile: ProviderRequestProfile) -> ProviderAdapterResult:
    return adapter_for_provider(profile.provider).build(profile)
