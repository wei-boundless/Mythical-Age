"""Task system public exports.

The coordinator depends on query modules that may import ``tasks`` again during
package initialization. Keep these exports lazy so lightweight contract imports
do not pull the legacy runtime graph into preview-only code paths.
"""

from __future__ import annotations

from typing import Any


__all__ = [
    "ProjectionRequirement",
    "SkillRuntimeView",
    "TaskBindingRecord",
    "TaskBindings",
    "TaskConstraints",
    "TaskContextRef",
    "TaskContract",
    "TaskCoordinator",
    "TaskDefinition",
    "TaskFlowDefinition",
    "TaskAgentBinding",
    "TaskFlowRegistry",
    "TaskEvent",
    "TaskPromptContract",
    "TaskRecord",
    "TaskResultRef",
    "TaskSummary",
    "build_task_runtime_contract_preview",
]


def __getattr__(name: str) -> Any:
    if name == "TaskCoordinator":
        from tasks.coordinator import TaskCoordinator

        return TaskCoordinator
    if name in {"TaskContract"}:
        from tasks.contracts import TaskContract

        return TaskContract
    if name in {"TaskDefinition"}:
        from tasks.definitions import TaskDefinition

        return TaskDefinition
    if name in {"TaskFlowDefinition", "TaskAgentBinding"}:
        from tasks.flow_models import TaskAgentBinding, TaskFlowDefinition

        return {"TaskFlowDefinition": TaskFlowDefinition, "TaskAgentBinding": TaskAgentBinding}[name]
    if name == "TaskFlowRegistry":
        from tasks.flow_registry import TaskFlowRegistry

        return TaskFlowRegistry
    if name in {"TaskBindingRecord"}:
        from tasks.bindings import TaskBindingRecord

        return TaskBindingRecord
    if name in {"ProjectionRequirement", "SkillRuntimeView", "TaskPromptContract"}:
        from tasks.runtime_contracts import ProjectionRequirement, SkillRuntimeView, TaskPromptContract

        mapping = {
            "ProjectionRequirement": ProjectionRequirement,
            "SkillRuntimeView": SkillRuntimeView,
            "TaskPromptContract": TaskPromptContract,
        }
        return mapping[name]
    if name in {"TaskBindings", "TaskConstraints", "TaskContextRef", "TaskResultRef", "TaskSummary"}:
        from tasks.context_models import TaskBindings, TaskConstraints, TaskContextRef, TaskResultRef, TaskSummary

        mapping = {
            "TaskBindings": TaskBindings,
            "TaskConstraints": TaskConstraints,
            "TaskContextRef": TaskContextRef,
            "TaskResultRef": TaskResultRef,
            "TaskSummary": TaskSummary,
        }
        return mapping[name]
    if name in {"TaskEvent", "TaskRecord"}:
        from tasks.models import TaskEvent, TaskRecord

        return {"TaskEvent": TaskEvent, "TaskRecord": TaskRecord}[name]
    if name == "build_task_runtime_contract_preview":
        from tasks.contract_builder import build_task_runtime_contract_preview

        return build_task_runtime_contract_preview
    raise AttributeError(name)
