from __future__ import annotations

_EXPORTS = {
    "AgentBodyProfile": ("body_models", "AgentBodyProfile"),
    "BodyProfileRegistry": ("body_registry", "BodyProfileRegistry"),
    "AgentRuntimeProfile": ("runtime_profile_models", "AgentRuntimeProfile"),
    "AgentRuntimeRegistry": ("runtime_profile_registry", "AgentRuntimeRegistry"),
    "default_agent_runtime_profiles": ("runtime_profile_registry", "default_agent_runtime_profiles"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'agent_system.profiles' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)


