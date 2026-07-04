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
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    'project_network_tasks.context_providers',
    'task_system.writing_graphs.context_providers',
)


def register_graph_context_provider(provider: GraphContextProvider) -> None:
    _PROVIDERS[provider.provider_id] = provider


def iter_graph_context_providers() -> tuple[GraphContextProvider, ...]:
    _ensure_default_modules_loaded()
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
            continue
        if contribution.initial_inputs:
            next_initial_inputs.update(dict(contribution.initial_inputs))
        if contribution.inbound_context is not None:
            next_inbound_context = [
                dict(item)
                for item in list(contribution.inbound_context or [])
                if isinstance(item, dict)
            ]
    return next_initial_inputs, next_inbound_context


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, 'register_context_providers', None)
        if callable(register):
            register(register_graph_context_provider)
