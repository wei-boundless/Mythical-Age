from __future__ import annotations

from graph_system.extensions import GraphExtensionModules, ensure_graph_extensions_loaded


APP_GRAPH_EXTENSION_MODULES = GraphExtensionModules(
    runtime_algorithm_adapter_modules=(
        "task_system.writing_graphs.runtime_adapters",
        "project_network_tasks.runtime_adapters",
    ),
    graph_context_provider_modules=(
        "task_system.writing_graphs.context_providers",
        "project_network_tasks.context_providers",
    ),
    runtime_algorithm_effect_modules=(
        "project_network_tasks.runtime_effects",
    ),
    memory_candidate_handler_modules=(
        "task_system.writing_graphs.memory_candidate_handlers",
    ),
    deterministic_work_order_handler_modules=(
        "task_system.writing_graphs.work_order_handlers",
    ),
    quality_gate_handler_modules=(
        "task_system.writing_graphs.quality_gate_handlers",
    ),
    revision_signal_handler_modules=(
        "task_system.writing_graphs.revision_signal_handlers",
    ),
)


def ensure_app_graph_extensions_loaded() -> None:
    ensure_graph_extensions_loaded(APP_GRAPH_EXTENSION_MODULES)
