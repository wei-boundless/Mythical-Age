from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ProviderCacheMode = Literal["automatic_prefix", "disabled"]


@dataclass(frozen=True, slots=True)
class ProviderCachePolicy:
    provider: str
    model: str = ""
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

    def resolve(self, *, provider: str, model: str = "") -> ProviderCachePolicy:
        normalized = str(provider or "").strip().lower()
        if normalized in {"openai", "deepseek"}:
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                mode="automatic_prefix",
                reason="provider_adapter_reports_automatic_prefix_cache_accounting",
            )
        return ProviderCachePolicy(
            provider=normalized,
            model=str(model or ""),
            mode="disabled",
            reason="provider_cache_support_not_declared_by_adapter",
        )
