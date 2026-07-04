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
_DEFAULT_MODULES_LOADED = False
_DEFAULT_MODULES = (
    'task_system.writing_graphs.runtime_adapters',
    'project_network_tasks.runtime_adapters',
)


def register_runtime_algorithm_adapter(adapter: RuntimeAlgorithmPostprocessAdapter) -> None:
    _ADAPTERS[adapter.adapter_id] = adapter


def iter_runtime_algorithm_adapters() -> tuple[RuntimeAlgorithmPostprocessAdapter, ...]:
    _ensure_default_modules_loaded()
    return tuple(sorted(_ADAPTERS.values(), key=lambda adapter: (adapter.priority, adapter.adapter_id)))


def runtime_algorithm_structured_output_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for adapter in iter_runtime_algorithm_adapters():
        keys.extend(str(key).strip() for key in adapter.structured_output_keys if str(key).strip())
    return tuple(dict.fromkeys(keys))


def _ensure_default_modules_loaded() -> None:
    global _DEFAULT_MODULES_LOADED
    if _DEFAULT_MODULES_LOADED:
        return
    _DEFAULT_MODULES_LOADED = True
    for module_name in _DEFAULT_MODULES:
        module = importlib.import_module(module_name)
        register = getattr(module, 'register_runtime_algorithm_adapters', None)
        if callable(register):
            register(register_runtime_algorithm_adapter)


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
