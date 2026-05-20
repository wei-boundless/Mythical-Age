from __future__ import annotations

import os
from typing import Any

from bootstrap.settings import AppSettingsService
from config import LLM_PROVIDER_DEFAULTS

from .agent_runtime_models import AgentRuntimeProfile
from .model_profile_models import AgentModelProfile, ModelRequirement, ResolvedModelSpec, parse_model_requirement


def build_provider_catalog(settings_service: AppSettingsService | None = None) -> dict[str, Any]:
    service = settings_service
    settings = service.static if service is not None else None
    active_provider = str(getattr(settings, "llm_provider", "") or "deepseek")
    active_model = str(getattr(settings, "llm_model", "") or "")
    active_base_url = str(getattr(settings, "llm_base_url", "") or "")
    providers: dict[str, Any] = {}
    for provider, defaults in LLM_PROVIDER_DEFAULTS.items():
        credential_configured = _provider_credential_configured(provider, settings=settings)
        providers[provider] = {
            "provider": provider,
            "display_name": str(defaults.get("display_name") or provider),
            "default_model": str(defaults.get("model") or ""),
            "default_base_url": str(defaults.get("base_url") or ""),
            "adapter": str(defaults.get("adapter") or "openai_compatible"),
            "credential_ref": f"provider:{provider}:primary",
            "fallback_credential_ref": f"provider:{provider}:fallback",
            "credential_configured": credential_configured,
            "credential_envs": list(defaults.get("credential_envs") or []),
            "model_presets": list(defaults.get("model_presets") or [str(defaults.get("model") or "")]),
            "capability_tags": list(defaults.get("capability_tags") or []),
            "recommended": bool(defaults.get("recommended", False)),
            "active": provider == active_provider,
            "metadata": dict(defaults.get("metadata") or {}),
        }
    return {
        "authority": "runtime.model_provider_catalog",
        "default_provider": active_provider,
        "default_model": active_model,
        "default_base_url": active_base_url,
        "recommended_provider": "deepseek",
        "providers": providers,
        "credential_refs": _credential_ref_catalog(settings=settings),
    }


class ModelProfileResolver:
    def __init__(self, settings_service: AppSettingsService) -> None:
        self.settings_service = settings_service

    def resolve_model_spec(
        self,
        *,
        agent_runtime_profile: AgentRuntimeProfile | None = None,
        model_requirement: dict[str, Any] | ModelRequirement | None = None,
        runtime_lane: str = "",
        graph_runtime_defaults: dict[str, Any] | None = None,
    ) -> ResolvedModelSpec:
        settings = self.settings_service.static
        requirement = (
            model_requirement
            if isinstance(model_requirement, ModelRequirement)
            else parse_model_requirement(model_requirement)
        )
        agent_model_profile = (
            agent_runtime_profile.model_profile
            if agent_runtime_profile is not None
            else AgentModelProfile()
        )
        defaults = dict(graph_runtime_defaults or {})
        source_chain: list[str] = ["system_config.model_provider"]
        warnings: list[str] = []

        system_provider = str(getattr(settings, "llm_provider", "") or "deepseek").strip().lower()
        provider = str(defaults.get("provider") or system_provider or "deepseek").strip().lower()
        model = str(
            defaults.get("model")
            or (getattr(settings, "llm_model", "") if provider == system_provider else "")
            or ""
        ).strip()
        credential_ref = str(defaults.get("credential_ref") or "").strip()

        if agent_model_profile.provider:
            provider_changed = agent_model_profile.provider != provider
            provider = agent_model_profile.provider
            source_chain.append("agent_runtime_profile.model_profile.provider")
            if provider_changed and not agent_model_profile.model:
                model = ""
            if provider_changed and not agent_model_profile.credential_ref:
                credential_ref = ""
        if agent_model_profile.model:
            model = agent_model_profile.model
            source_chain.append("agent_runtime_profile.model_profile.model")
        if agent_model_profile.credential_ref:
            credential_ref = agent_model_profile.credential_ref
            source_chain.append("agent_runtime_profile.model_profile.credential_ref")

        if requirement.profile_ref:
            if requirement.profile_ref != agent_model_profile.profile_id:
                warnings.append("model_requirement_profile_ref_not_matched")
            source_chain.append("node.contract_bindings.runtime.model_requirement.profile_ref")
        if requirement.provider_family and requirement.provider_family not in {provider, "openai-compatible", "openai_compatible"}:
            warnings.append("model_requirement_provider_family_differs")
        if requirement.capability_tags:
            missing = [tag for tag in requirement.capability_tags if tag not in set(agent_model_profile.capability_tags)]
            if missing and agent_model_profile.capability_tags:
                warnings.append("model_requirement_capability_tags_not_fully_matched")

        provider_defaults = dict(LLM_PROVIDER_DEFAULTS.get(provider) or {})
        if not model:
            model = str(provider_defaults.get("model") or "")
        base_url = self.resolve_provider_base_url(provider=provider, graph_runtime_defaults=defaults)
        if not credential_ref:
            credential_ref = f"provider:{provider}:primary"

        max_output_tokens = _positive_int(
            agent_model_profile.max_output_tokens,
            _positive_int(defaults.get("max_output_tokens"), int(getattr(settings, "llm_max_output_tokens", 32768) or 32768)),
        )
        if requirement.preferred_output_tokens:
            max_output_tokens = max(max_output_tokens, int(requirement.preferred_output_tokens))
            source_chain.append("node.contract_bindings.runtime.model_requirement.preferred_output_tokens")
        if requirement.min_output_tokens and max_output_tokens < requirement.min_output_tokens:
            warnings.append("model_requirement_min_output_tokens_exceeds_profile")

        timeout_seconds = _positive_float(
            agent_model_profile.timeout_seconds,
            _positive_float(defaults.get("timeout_seconds"), float(getattr(settings, "llm_timeout_seconds", 45.0) or 45.0)),
        )
        long_output_timeout_seconds = _positive_float(
            agent_model_profile.long_output_timeout_seconds,
            _positive_float(
                defaults.get("long_output_timeout_seconds"),
                float(getattr(settings, "llm_long_output_timeout_seconds", 180.0) or 180.0),
            ),
        )
        max_retries = _nonnegative_int(
            agent_model_profile.max_retries,
            _nonnegative_int(defaults.get("max_retries"), int(getattr(settings, "llm_max_retries", 2) or 2)),
        )
        temperature = _float_or(
            agent_model_profile.temperature,
            _float_or(defaults.get("temperature"), 0.0),
        )
        thinking_mode = str(
            agent_model_profile.thinking_mode
            or defaults.get("thinking_mode")
            or getattr(settings, "llm_thinking_mode", "disabled")
            or "disabled"
        ).strip().lower()
        if requirement.thinking_mode and requirement.thinking_mode != "any":
            if thinking_mode and thinking_mode != requirement.thinking_mode:
                warnings.append("model_requirement_thinking_mode_differs")
            thinking_mode = requirement.thinking_mode
            source_chain.append("node.contract_bindings.runtime.model_requirement.thinking_mode")
        reasoning_effort = str(
            agent_model_profile.reasoning_effort
            or defaults.get("reasoning_effort")
            or getattr(settings, "llm_reasoning_effort", "high")
            or "high"
        ).strip().lower()

        api_key = self.resolve_credential_ref(credential_ref=credential_ref, provider=provider)
        if not api_key and provider != "ollama":
            warnings.append("credential_ref_unresolved")

        diagnostics = {
            "agent_id": getattr(agent_runtime_profile, "agent_id", "") if agent_runtime_profile is not None else "",
            "agent_profile_id": getattr(agent_runtime_profile, "agent_profile_id", "") if agent_runtime_profile is not None else "",
            "model_profile_id": agent_model_profile.profile_id,
            "runtime_lane": runtime_lane,
            "credential_ref": credential_ref,
            "credential_configured": bool(api_key) or provider == "ollama",
            "requirement": requirement.to_dict(),
            "warnings": warnings,
        }
        return ResolvedModelSpec(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            long_output_timeout_seconds=max(long_output_timeout_seconds, timeout_seconds),
            max_retries=max_retries,
            temperature=temperature,
            thinking_mode=thinking_mode or "disabled",
            reasoning_effort=reasoning_effort or "high",
            stream_policy=dict(agent_model_profile.stream_policy or {}),
            source_chain=tuple(dict.fromkeys(source_chain)),
            diagnostics=diagnostics,
        )

    def resolve_credential_ref(self, *, credential_ref: str, provider: str) -> str | None:
        settings = self.settings_service.static
        ref = str(credential_ref or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if ref in {"", f"provider:{normalized_provider}:primary"}:
            if str(getattr(settings, "llm_provider", "") or "").strip().lower() == normalized_provider:
                return getattr(settings, "llm_api_key", None)
            return _first_env_for_provider(normalized_provider)
        if ref == f"provider:{normalized_provider}:fallback":
            if str(getattr(settings, "llm_fallback_provider", "") or "").strip().lower() == normalized_provider:
                return getattr(settings, "llm_fallback_api_key", None)
            return _first_env_for_provider(normalized_provider)
        if ref == "system:llm:primary":
            return getattr(settings, "llm_api_key", None)
        if ref == "system:llm:fallback":
            return getattr(settings, "llm_fallback_api_key", None)
        if ref.startswith("provider:"):
            parts = ref.split(":")
            ref_provider = parts[1] if len(parts) >= 2 else normalized_provider
            ref_slot = parts[2] if len(parts) >= 3 else "primary"
            if ref_slot == "fallback" and str(getattr(settings, "llm_fallback_provider", "") or "").strip().lower() == ref_provider:
                return getattr(settings, "llm_fallback_api_key", None)
            if str(getattr(settings, "llm_provider", "") or "").strip().lower() == ref_provider:
                return getattr(settings, "llm_api_key", None)
            return _first_env_for_provider(ref_provider)
        if ref.startswith("env:"):
            env_name = ref.removeprefix("env:").strip()
            allowed = _provider_env_names(normalized_provider)
            return os.getenv(env_name) if env_name in allowed else None
        return None

    def resolve_provider_base_url(self, *, provider: str, graph_runtime_defaults: dict[str, Any] | None = None) -> str:
        settings = self.settings_service.static
        normalized_provider = str(provider or "").strip().lower()
        defaults = dict(graph_runtime_defaults or {})
        default_provider = str(defaults.get("provider") or "").strip().lower()
        if default_provider == normalized_provider:
            default_base_url = str(defaults.get("base_url") or "").strip()
            if default_base_url:
                return default_base_url
        if str(getattr(settings, "llm_provider", "") or "").strip().lower() == normalized_provider:
            return str(getattr(settings, "llm_base_url", "") or "").strip()
        provider_defaults = dict(LLM_PROVIDER_DEFAULTS.get(normalized_provider) or {})
        return str(provider_defaults.get("base_url") or "").strip()


def _credential_ref_catalog(*, settings: Any | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for provider in LLM_PROVIDER_DEFAULTS:
        refs.append(
            {
                "credential_ref": f"provider:{provider}:primary",
                "provider": provider,
                "slot": "primary",
                "configured": _provider_credential_configured(provider, settings=settings),
            }
        )
        refs.append(
            {
                "credential_ref": f"provider:{provider}:fallback",
                "provider": provider,
                "slot": "fallback",
                "configured": bool(
                    settings is not None
                    and str(getattr(settings, "llm_fallback_provider", "") or "").strip().lower() == provider
                    and getattr(settings, "llm_fallback_api_key", None)
                ),
            }
        )
    refs.extend(
        [
            {
                "credential_ref": "system:llm:primary",
                "provider": str(getattr(settings, "llm_provider", "") or "deepseek") if settings is not None else "deepseek",
                "slot": "primary",
                "configured": bool(getattr(settings, "llm_api_key", None)) if settings is not None else False,
            },
            {
                "credential_ref": "system:llm:fallback",
                "provider": str(getattr(settings, "llm_fallback_provider", "") or "") if settings is not None else "",
                "slot": "fallback",
                "configured": bool(getattr(settings, "llm_fallback_api_key", None)) if settings is not None else False,
            },
        ]
    )
    return refs


def _provider_credential_configured(provider: str, *, settings: Any | None) -> bool:
    normalized = str(provider or "").strip().lower()
    if normalized == "ollama":
        return True
    if settings is not None and str(getattr(settings, "llm_provider", "") or "").strip().lower() == normalized:
        return bool(getattr(settings, "llm_api_key", None))
    return bool(_first_env_for_provider(normalized))


def _first_env_for_provider(provider: str) -> str | None:
    for name in _provider_env_names(provider):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _provider_env_names(provider: str) -> tuple[str, ...]:
    defaults = dict(LLM_PROVIDER_DEFAULTS.get(provider) or {})
    names = defaults.get("credential_envs") or ()
    return tuple(str(item).strip() for item in names if str(item).strip())


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(0, parsed)


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(0.01, parsed)


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
