from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ProviderCacheMode = Literal["automatic_prefix", "disabled"]
ProviderContextPhysicalModel = Literal["static_context_dynamic_tail", "static_context"]

CONTEXT_PHYSICAL_ORDER_WITH_TAIL = ("static_prefix", "context_memory", "dynamic_tail")
CONTEXT_PHYSICAL_ORDER_NO_TAIL = ("static_prefix", "context_memory")
CONTEXT_CACHE_SECTION_ORDER_WITH_TAIL = ("static_prefix", "context_memory_prefix", "context_append", "dynamic_tail")
CONTEXT_CACHE_SECTION_ORDER_NO_TAIL = ("static_prefix", "context_memory_prefix", "context_append")


@dataclass(frozen=True, slots=True)
class ProviderCachePolicy:
    provider: str
    model: str = ""
    base_url: str = ""
    mode: ProviderCacheMode = "disabled"
    context_physical_model: ProviderContextPhysicalModel = "static_context"
    dynamic_tail_supported: bool = False
    context_physical_segment_order: tuple[str, ...] = CONTEXT_PHYSICAL_ORDER_NO_TAIL
    context_cache_section_order: tuple[str, ...] = CONTEXT_CACHE_SECTION_ORDER_NO_TAIL
    reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.provider_cache_policy"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["context_physical_segment_order"] = list(self.context_physical_segment_order)
        payload["context_cache_section_order"] = list(self.context_cache_section_order)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


class ProviderCachePolicyResolver:
    """Declares cache support from provider adapters, not prompt text."""

    def resolve(
        self,
        *,
        provider: str,
        model: str = "",
        base_url: str = "",
        context_physical_model: str = "",
        dynamic_tail_supported: bool | None = None,
        override_reason: str = "",
    ) -> ProviderCachePolicy:
        normalized = str(provider or "").strip().lower()
        normalized_base_url = str(base_url or "").strip().lower()
        requested_physical_model = _normalize_context_physical_model(context_physical_model)
        if normalized == "deepseek" or "api.deepseek.com" in normalized_base_url:
            if requested_physical_model == "static_context_dynamic_tail" and dynamic_tail_supported is True:
                return ProviderCachePolicy(
                    provider=normalized,
                    model=str(model or ""),
                    base_url=str(base_url or ""),
                    mode="automatic_prefix",
                    context_physical_model="static_context_dynamic_tail",
                    dynamic_tail_supported=True,
                    context_physical_segment_order=CONTEXT_PHYSICAL_ORDER_WITH_TAIL,
                    context_cache_section_order=CONTEXT_CACHE_SECTION_ORDER_WITH_TAIL,
                    reason="provider_strategy_declares_independent_dynamic_tail_physical_model",
                    diagnostics={
                        "context_physical_model_reason": (
                            str(override_reason or "").strip()
                            or "deepseek_dynamic_tail_cache_probe_strategy"
                        ),
                        "context_physical_model_override": requested_physical_model,
                    },
                )
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                base_url=str(base_url or ""),
                mode="automatic_prefix",
                context_physical_model="static_context",
                dynamic_tail_supported=False,
                context_physical_segment_order=CONTEXT_PHYSICAL_ORDER_NO_TAIL,
                context_cache_section_order=CONTEXT_CACHE_SECTION_ORDER_NO_TAIL,
                reason="provider_adapter_reports_automatic_prefix_cache_accounting_with_append_only_context",
                diagnostics={
                    "context_physical_model_reason": (
                        "deepseek_automatic_prefix_cache_matches_persisted_complete_prefix_units;"
                        "dynamic_tail_is_folded_into_append_only_context_assembly"
                    ),
                },
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
                context_physical_model="static_context",
                dynamic_tail_supported=False,
                context_physical_segment_order=CONTEXT_PHYSICAL_ORDER_NO_TAIL,
                context_cache_section_order=CONTEXT_CACHE_SECTION_ORDER_NO_TAIL,
                reason="provider_adapter_reports_automatic_prefix_cache_accounting_with_append_only_context",
                diagnostics={
                    "context_physical_model_reason": (
                        "automatic_prefix_cache_matches_repeated_prefix_units;"
                        "dynamic_tail_is_folded_into_append_only_context_assembly"
                    ),
                },
            )
        if normalized == "openai":
            return ProviderCachePolicy(
                provider=normalized,
                model=str(model or ""),
                base_url=str(base_url or ""),
                mode="disabled",
                context_physical_model="static_context",
                dynamic_tail_supported=False,
                context_physical_segment_order=CONTEXT_PHYSICAL_ORDER_NO_TAIL,
                context_cache_section_order=CONTEXT_CACHE_SECTION_ORDER_NO_TAIL,
                reason="openai_compatible_endpoint_cache_support_not_declared_by_adapter",
                diagnostics={
                    "context_physical_model_reason": "adapter_does_not_declare_dynamic_tail_cache_support",
                },
            )
        return ProviderCachePolicy(
            provider=normalized,
            model=str(model or ""),
            base_url=str(base_url or ""),
            mode="disabled",
            context_physical_model="static_context",
            dynamic_tail_supported=False,
            context_physical_segment_order=CONTEXT_PHYSICAL_ORDER_NO_TAIL,
            context_cache_section_order=CONTEXT_CACHE_SECTION_ORDER_NO_TAIL,
            reason="provider_cache_support_not_declared_by_adapter",
            diagnostics={
                "context_physical_model_reason": "provider_adapter_support_not_declared",
            },
        )


def provider_cache_policy_override_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    extensions = dict(source.get("provider_extensions") or {})
    policy = dict(
        source.get("context_cache_policy")
        or extensions.get("context_cache_policy")
        or {}
    )
    physical_model = str(
        policy.get("context_physical_model")
        or extensions.get("context_physical_model")
        or source.get("context_physical_model")
        or ""
    ).strip()
    dynamic_tail_supported = _optional_bool(
        policy.get("dynamic_tail_supported", extensions.get("dynamic_tail_supported"))
    )
    return {
        "context_physical_model": physical_model,
        "dynamic_tail_supported": dynamic_tail_supported,
        "reason": str(
            policy.get("reason")
            or extensions.get("context_physical_model_reason")
            or source.get("context_physical_model_reason")
            or ""
        ).strip(),
    }


def _normalize_context_physical_model(value: Any) -> ProviderContextPhysicalModel | str:
    normalized = str(value or "").strip()
    if normalized in {"static_context", "static_context_dynamic_tail"}:
        return normalized
    return ""


def _optional_bool(value: Any) -> bool | None:
    if value is True:
        return True
    if value is False:
        return False
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None
