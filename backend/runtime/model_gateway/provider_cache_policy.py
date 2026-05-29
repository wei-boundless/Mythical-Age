from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ProviderCacheMode = Literal["automatic_prefix", "disabled"]


@dataclass(frozen=True, slots=True)
class ProviderCachePolicy:
    provider: str
    model: str = ""
    base_url: str = ""
    mode: ProviderCacheMode = "disabled"
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.provider_cache_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


class ProviderCachePolicyResolver:
    """Declares cache support from provider adapters, not prompt text."""

    def resolve(self, *, provider: str, model: str = "", base_url: str = "") -> ProviderCachePolicy:
        normalized = str(provider or "").strip().lower()
        normalized_base_url = str(base_url or "").strip().lower()
        if normalized == "deepseek" or "api.deepseek.com" in normalized_base_url:
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                base_url=str(base_url or ""),
                mode="automatic_prefix",
                reason="provider_adapter_reports_automatic_prefix_cache_accounting",
            )
        if normalized == "openai" and (
            not normalized_base_url
            or "api.openai.com" in normalized_base_url
            or "api.openai.azure.com" in normalized_base_url
        ):
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                base_url=str(base_url or ""),
                mode="automatic_prefix",
                reason="provider_adapter_reports_automatic_prefix_cache_accounting",
            )
        if normalized == "openai":
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                base_url=str(base_url or ""),
                mode="disabled",
                reason="openai_compatible_endpoint_cache_support_not_declared_by_adapter",
            )
        return ProviderCachePolicy(
            provider=normalized,
            model=str(model or ""),
            base_url=str(base_url or ""),
            mode="disabled",
            reason="provider_cache_support_not_declared_by_adapter",
        )
