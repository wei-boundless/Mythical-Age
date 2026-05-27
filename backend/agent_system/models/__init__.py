from __future__ import annotations

_EXPORTS = {
    "AgentDescriptor": ("agent_models", "AgentDescriptor"),
    "AgentLifecycleRecord": ("agent_models", "AgentLifecycleRecord"),
    "AgentModelProfile": ("model_profile_models", "AgentModelProfile"),
    "ModelRequirement": ("model_profile_models", "ModelRequirement"),
    "ResolvedModelSpec": ("model_profile_models", "ResolvedModelSpec"),
    "contains_raw_secret": ("model_profile_models", "contains_raw_secret"),
    "parse_agent_model_profile": ("model_profile_models", "parse_agent_model_profile"),
    "parse_model_requirement": ("model_profile_models", "parse_model_requirement"),
    "sanitize_model_profile_payload": ("model_profile_models", "sanitize_model_profile_payload"),
    "ModelProfileResolver": ("model_profile_resolver", "ModelProfileResolver"),
    "build_provider_catalog": ("model_profile_resolver", "build_provider_catalog"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'agent_system.models' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)


