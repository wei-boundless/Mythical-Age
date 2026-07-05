from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import ExecutableGraphConfig, GraphLoopState

GraphContextProviderCallable = Callable[..., 'GraphContextProviderContribution']


@dataclass(frozen=True, slots=True)
class GraphContextProviderContribution:
    initial_inputs: dict[str, Any] = field(default_factory=dict)
    inbound_context: list[dict[str, Any]] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphContextProvider:
    provider_id: str
    provide: GraphContextProviderCallable
    priority: int = 1000
    initial_input_keys: tuple[str, ...] = ()
    runtime_scope_keys: tuple[str, ...] = ()
    loop_contract_input_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.provider_id or '').strip():
            raise ValueError('GraphContextProvider requires provider_id')
        if not callable(self.provide):
            raise ValueError('GraphContextProvider requires callable provide')


_PROVIDERS: dict[str, GraphContextProvider] = {}
_LOADED_MODULES: set[str] = set()


def snapshot_graph_context_provider_registry() -> dict[str, Any]:
    return {
        "providers": dict(_PROVIDERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_graph_context_provider_registry(snapshot: dict[str, Any]) -> None:
    _PROVIDERS.clear()
    _PROVIDERS.update(dict(snapshot.get("providers") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_graph_context_provider(provider: GraphContextProvider) -> None:
    provider_id = str(provider.provider_id or "").strip()
    if provider_id in _PROVIDERS:
        raise ValueError(f"duplicate graph context provider id: {provider_id}")
    _PROVIDERS[provider_id] = provider


def iter_graph_context_providers() -> tuple[GraphContextProvider, ...]:
    return tuple(sorted(_PROVIDERS.values(), key=lambda provider: (provider.priority, provider.provider_id)))


def context_provider_initial_input_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for provider in iter_graph_context_providers():
        keys.extend(str(key).strip() for key in provider.initial_input_keys if str(key).strip())
    return tuple(dict.fromkeys(keys))


def context_provider_runtime_scope_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for provider in iter_graph_context_providers():
        keys.extend(str(key).strip() for key in provider.runtime_scope_keys if str(key).strip())
    return tuple(dict.fromkeys(keys))


def context_provider_loop_contract_input_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for provider in iter_graph_context_providers():
        keys.extend(str(key).strip() for key in provider.loop_contract_input_keys if str(key).strip())
    return tuple(dict.fromkeys(keys))


def apply_context_providers(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node: dict[str, Any],
    services: Any | None,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    next_initial_inputs = dict(initial_inputs or {})
    next_inbound_context = [dict(item) for item in list(inbound_context or []) if isinstance(item, dict)]
    for provider in iter_graph_context_providers():
        contribution = provider.provide(
            graph_config=graph_config,
            state=state,
            node=node,
            services=services,
            initial_inputs=dict(next_initial_inputs),
            inbound_context=list(next_inbound_context),
        )
        if not isinstance(contribution, GraphContextProviderContribution):
            raise ValueError(f"graph context provider returned invalid contribution: {provider.provider_id}")
        if contribution.initial_inputs:
            next_initial_inputs.update(dict(contribution.initial_inputs))
        if contribution.inbound_context is not None:
            next_inbound_context = [
                dict(item)
                for item in list(contribution.inbound_context or [])
                if isinstance(item, dict)
            ]
    return next_initial_inputs, next_inbound_context


def load_graph_context_provider_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_context_providers", None)
    if not callable(register):
        raise ValueError(f"graph context provider module has no register_context_providers(): {normalized}")
    before = dict(_PROVIDERS)
    try:
        register(register_graph_context_provider)
    except Exception:
        _PROVIDERS.clear()
        _PROVIDERS.update(before)
        raise
    if _PROVIDERS == before:
        raise ValueError(f"graph context provider module registered no providers: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_graph_context_provider_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_graph_context_provider_module(str(module_name or ""))
