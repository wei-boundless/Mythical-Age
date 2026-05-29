from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentBodyProfile": (".profiles.body_models", "AgentBodyProfile"),
    "AgentDescriptor": (".models.agent_models", "AgentDescriptor"),
    "AgentGroup": (".groups.models", "AgentGroup"),
    "AgentGroupRegistry": (".groups.registry", "AgentGroupRegistry"),
    "AgentLifecycleRecord": (".models.agent_models", "AgentLifecycleRecord"),
    "AgentModelProfile": (".models.model_profile_models", "AgentModelProfile"),
    "AgentRuntimeProfile": (".profiles.runtime_profile_models", "AgentRuntimeProfile"),
    "AgentRuntimeRegistry": (".profiles.runtime_profile_registry", "AgentRuntimeRegistry"),
    "AgentRuntimeSpec": (".assembly.runtime_spec_models", "AgentRuntimeSpec"),
    "AgentRegistry": (".registry.agent_registry", "AgentRegistry"),
    "BodyProfileRegistry": (".profiles.body_registry", "BodyProfileRegistry"),
    "MemoryScopeProfile": (".profiles.body_models", "MemoryScopeProfile"),
    "ModelProfileResolver": (".models.model_profile_resolver", "ModelProfileResolver"),
    "ModelRequirement": (".models.model_profile_models", "ModelRequirement"),
    "OutputBoundaryProfile": (".profiles.body_models", "OutputBoundaryProfile"),
    "PromptStructureProfile": (".profiles.body_models", "PromptStructureProfile"),
    "ProvisionedWorkerAgent": (".registry.worker_agent_factory", "ProvisionedWorkerAgent"),
    "ResolvedModelSpec": (".models.model_profile_models", "ResolvedModelSpec"),
    "TaskBodyOrchestration": (".assembly.runtime_spec_models", "TaskBodyOrchestration"),
    "WorkerAgentBlueprint": (".registry.worker_agent_blueprints", "WorkerAgentBlueprint"),
    "WorkerAgentFactory": (".registry.worker_agent_factory", "WorkerAgentFactory"),
    "WorkerAgentSpawnRequest": (".registry.worker_agent_blueprints", "WorkerAgentSpawnRequest"),
    "WorkerAgentSpawnResult": (".registry.worker_agent_blueprints", "WorkerAgentSpawnResult"),
    "agent_id_aliases": (".identity", "agent_id_aliases"),
    "build_provider_catalog": (".models.model_profile_resolver", "build_provider_catalog"),
    "default_agent_descriptors": (".registry.agent_registry", "default_agent_descriptors"),
    "default_agent_groups": (".groups.registry", "default_agent_groups"),
    "default_agent_runtime_profiles": (".profiles.runtime_profile_registry", "default_agent_runtime_profiles"),
    "default_worker_agent_blueprints": (".registry.worker_agent_factory", "default_worker_agent_blueprints"),
    "normalize_agent_id": (".identity", "normalize_agent_id"),
    "normalize_agent_id_sequence": (".identity", "normalize_agent_id_sequence"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


