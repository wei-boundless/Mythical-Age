from __future__ import annotations

from dataclasses import dataclass

from graph_system.adapter_registry import (
    load_runtime_algorithm_adapter_modules,
    restore_runtime_algorithm_adapter_registry,
    snapshot_runtime_algorithm_adapter_registry,
)
from graph_system.context_provider_registry import (
    load_graph_context_provider_modules,
    restore_graph_context_provider_registry,
    snapshot_graph_context_provider_registry,
)
from graph_system.memory_candidate_registry import (
    load_memory_candidate_payload_handler_modules,
    restore_memory_candidate_payload_handler_registry,
    snapshot_memory_candidate_payload_handler_registry,
)
from graph_system.quality_gate_registry import (
    load_quality_gate_handler_modules,
    restore_quality_gate_handler_registry,
    snapshot_quality_gate_handler_registry,
)
from graph_system.revision_signal_registry import (
    load_revision_signal_handler_modules,
    restore_revision_signal_handler_registry,
    snapshot_revision_signal_handler_registry,
)
from graph_system.runtime_effect_registry import (
    load_runtime_algorithm_effect_modules,
    restore_runtime_algorithm_effect_registry,
    snapshot_runtime_algorithm_effect_registry,
)
from graph_system.work_order_handler_registry import (
    load_deterministic_work_order_handler_modules,
    restore_deterministic_work_order_handler_registry,
    snapshot_deterministic_work_order_handler_registry,
)


@dataclass(frozen=True, slots=True)
class GraphExtensionModules:
    runtime_algorithm_adapter_modules: tuple[str, ...] = ()
    graph_context_provider_modules: tuple[str, ...] = ()
    runtime_algorithm_effect_modules: tuple[str, ...] = ()
    memory_candidate_handler_modules: tuple[str, ...] = ()
    deterministic_work_order_handler_modules: tuple[str, ...] = ()
    quality_gate_handler_modules: tuple[str, ...] = ()
    revision_signal_handler_modules: tuple[str, ...] = ()


_LOADED_FINGERPRINTS: set[tuple[tuple[str, ...], ...]] = set()


def ensure_graph_extensions_loaded(modules: GraphExtensionModules) -> None:
    normalized = _normalize_graph_extension_modules(modules)
    fingerprint = _modules_fingerprint(normalized)
    if not any(fingerprint):
        raise ValueError("Graph extension modules are required.")
    if fingerprint in _LOADED_FINGERPRINTS:
        return
    snapshot = _snapshot_graph_extension_registries()
    loaded_fingerprints_before = set(_LOADED_FINGERPRINTS)
    try:
        load_runtime_algorithm_adapter_modules(normalized.runtime_algorithm_adapter_modules)
        load_graph_context_provider_modules(normalized.graph_context_provider_modules)
        load_runtime_algorithm_effect_modules(normalized.runtime_algorithm_effect_modules)
        load_memory_candidate_payload_handler_modules(normalized.memory_candidate_handler_modules)
        load_deterministic_work_order_handler_modules(normalized.deterministic_work_order_handler_modules)
        load_quality_gate_handler_modules(normalized.quality_gate_handler_modules)
        load_revision_signal_handler_modules(normalized.revision_signal_handler_modules)
    except Exception:
        _restore_graph_extension_registries(snapshot)
        _LOADED_FINGERPRINTS.clear()
        _LOADED_FINGERPRINTS.update(loaded_fingerprints_before)
        raise
    _LOADED_FINGERPRINTS.add(fingerprint)


def _snapshot_graph_extension_registries() -> dict[str, dict]:
    return {
        "runtime_algorithm_adapters": snapshot_runtime_algorithm_adapter_registry(),
        "context_providers": snapshot_graph_context_provider_registry(),
        "runtime_algorithm_effects": snapshot_runtime_algorithm_effect_registry(),
        "memory_candidate_handlers": snapshot_memory_candidate_payload_handler_registry(),
        "deterministic_work_order_handlers": snapshot_deterministic_work_order_handler_registry(),
        "quality_gate_handlers": snapshot_quality_gate_handler_registry(),
        "revision_signal_handlers": snapshot_revision_signal_handler_registry(),
    }


def _restore_graph_extension_registries(snapshot: dict[str, dict]) -> None:
    restore_runtime_algorithm_adapter_registry(dict(snapshot.get("runtime_algorithm_adapters") or {}))
    restore_graph_context_provider_registry(dict(snapshot.get("context_providers") or {}))
    restore_runtime_algorithm_effect_registry(dict(snapshot.get("runtime_algorithm_effects") or {}))
    restore_memory_candidate_payload_handler_registry(dict(snapshot.get("memory_candidate_handlers") or {}))
    restore_deterministic_work_order_handler_registry(dict(snapshot.get("deterministic_work_order_handlers") or {}))
    restore_quality_gate_handler_registry(dict(snapshot.get("quality_gate_handlers") or {}))
    restore_revision_signal_handler_registry(dict(snapshot.get("revision_signal_handlers") or {}))


def _normalize_graph_extension_modules(modules: GraphExtensionModules) -> GraphExtensionModules:
    if not isinstance(modules, GraphExtensionModules):
        raise TypeError("ensure_graph_extensions_loaded requires GraphExtensionModules.")
    return GraphExtensionModules(
        runtime_algorithm_adapter_modules=_module_tuple(modules.runtime_algorithm_adapter_modules),
        graph_context_provider_modules=_module_tuple(modules.graph_context_provider_modules),
        runtime_algorithm_effect_modules=_module_tuple(modules.runtime_algorithm_effect_modules),
        memory_candidate_handler_modules=_module_tuple(modules.memory_candidate_handler_modules),
        deterministic_work_order_handler_modules=_module_tuple(modules.deterministic_work_order_handler_modules),
        quality_gate_handler_modules=_module_tuple(modules.quality_gate_handler_modules),
        revision_signal_handler_modules=_module_tuple(modules.revision_signal_handler_modules),
    )


def _module_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item or "").strip() for item in tuple(values or ()) if str(item or "").strip()))


def _modules_fingerprint(modules: GraphExtensionModules) -> tuple[tuple[str, ...], ...]:
    return (
        modules.runtime_algorithm_adapter_modules,
        modules.graph_context_provider_modules,
        modules.runtime_algorithm_effect_modules,
        modules.memory_candidate_handler_modules,
        modules.deterministic_work_order_handler_modules,
        modules.quality_gate_handler_modules,
        modules.revision_signal_handler_modules,
    )
