from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable

from .models import ExecutableGraphConfig, GraphNodeWorkOrder
from .runtime_algorithm_types import RuntimeAlgorithmPostprocessResult

RuntimeAlgorithmPostprocessCallable = Callable[..., RuntimeAlgorithmPostprocessResult | None]


@dataclass(frozen=True, slots=True)
class RuntimeAlgorithmPostprocessAdapter:
    adapter_id: str
    postprocess: RuntimeAlgorithmPostprocessCallable
    priority: int = 1000
    structured_output_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.adapter_id or '').strip():
            raise ValueError('RuntimeAlgorithmPostprocessAdapter requires adapter_id')
        if not callable(self.postprocess):
            raise ValueError('RuntimeAlgorithmPostprocessAdapter requires callable postprocess')


_ADAPTERS: dict[str, RuntimeAlgorithmPostprocessAdapter] = {}
_LOADED_MODULES: set[str] = set()


def snapshot_runtime_algorithm_adapter_registry() -> dict[str, Any]:
    return {
        "adapters": dict(_ADAPTERS),
        "loaded_modules": set(_LOADED_MODULES),
    }


def restore_runtime_algorithm_adapter_registry(snapshot: dict[str, Any]) -> None:
    _ADAPTERS.clear()
    _ADAPTERS.update(dict(snapshot.get("adapters") or {}))
    _LOADED_MODULES.clear()
    _LOADED_MODULES.update(str(item) for item in set(snapshot.get("loaded_modules") or set()) if str(item))


def register_runtime_algorithm_adapter(adapter: RuntimeAlgorithmPostprocessAdapter) -> None:
    adapter_id = str(adapter.adapter_id or "").strip()
    if adapter_id in _ADAPTERS:
        raise ValueError(f"duplicate runtime algorithm adapter id: {adapter_id}")
    _ADAPTERS[adapter_id] = adapter


def iter_runtime_algorithm_adapters() -> tuple[RuntimeAlgorithmPostprocessAdapter, ...]:
    return tuple(sorted(_ADAPTERS.values(), key=lambda adapter: (adapter.priority, adapter.adapter_id)))


def runtime_algorithm_structured_output_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for adapter in iter_runtime_algorithm_adapters():
        keys.extend(str(key).strip() for key in adapter.structured_output_keys if str(key).strip())
    return tuple(dict.fromkeys(keys))


def load_runtime_algorithm_adapter_module(module_name: str) -> None:
    normalized = str(module_name or "").strip()
    if not normalized or normalized in _LOADED_MODULES:
        return
    module = importlib.import_module(normalized)
    register = getattr(module, "register_runtime_algorithm_adapters", None)
    if not callable(register):
        raise ValueError(f"runtime algorithm adapter module has no register_runtime_algorithm_adapters(): {normalized}")
    before = dict(_ADAPTERS)
    try:
        register(register_runtime_algorithm_adapter)
    except Exception:
        _ADAPTERS.clear()
        _ADAPTERS.update(before)
        raise
    if _ADAPTERS == before:
        raise ValueError(f"runtime algorithm adapter module registered no adapters: {normalized}")
    _LOADED_MODULES.add(normalized)


def load_runtime_algorithm_adapter_modules(module_names: tuple[str, ...] | list[str]) -> None:
    for module_name in list(module_names or ()):
        load_runtime_algorithm_adapter_module(str(module_name or ""))


def adapter_postprocess_kwargs(
    *,
    structured_outputs: dict[str, Any],
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    node: dict[str, Any],
    final_answer: str = '',
) -> dict[str, Any]:
    return {
        'structured_outputs': structured_outputs,
        'graph_config': graph_config,
        'work_order': work_order,
        'node': node,
        'final_answer': final_answer,
    }
