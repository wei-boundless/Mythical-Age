from __future__ import annotations

_EXPORTS = {
    "AgentRegistry": ("agent_registry", "AgentRegistry"),
    "default_agent_descriptors": ("agent_registry", "default_agent_descriptors"),
    "WorkerAgentBlueprint": ("worker_agent_blueprints", "WorkerAgentBlueprint"),
    "WorkerAgentSpawnRequest": ("worker_agent_blueprints", "WorkerAgentSpawnRequest"),
    "WorkerAgentSpawnResult": ("worker_agent_blueprints", "WorkerAgentSpawnResult"),
    "WorkerAgentFactory": ("worker_agent_factory", "WorkerAgentFactory"),
    "default_worker_agent_blueprints": ("worker_agent_factory", "default_worker_agent_blueprints"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'agent_system.registry' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)


