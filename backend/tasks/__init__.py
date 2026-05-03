"""Task system public exports."""

from __future__ import annotations

from typing import Any


__all__ = [
    "GeneralTaskProfile",
    "TaskAssignment",
    "SpecificTaskRecord",
    "AgentTaskCarryingProfile",
    "TaskWorkflowBinding",
    "TaskProjectionBinding",
    "TaskFlowContractBinding",
    "TaskAgentAdoptionPlan",
    "TaskMemoryRequestProfile",
    "TaskCommunicationProtocol",
    "ProjectionSelectionResult",
    "ProjectionRequirement",
    "SkillRuntimeView",
    "TaskExecutionAssembly",
    "TaskSpec",
    "TaskIntentContract",
    "TemplateMatchResult",
    "BundleSpec",
    "BundleItemSpec",
    "TaskBindingRecord",
    "TaskBindings",
    "TaskConstraints",
    "TaskContextRef",
    "TaskContract",
    "TaskCoordinator",
    "TaskDefinition",
    "TaskFlowDefinition",
    "TaskAgentBinding",
    "AgentTaskConnectionProfile",
    "TaskFlowRegistry",
    "TaskWorkflowRegistry",
    "TaskStepBlueprint",
    "StepInputBinding",
    "TaskTemplate",
    "TaskTemplateRegistry",
    "TaskValidationRule",
    "TaskEvent",
    "TaskPromptContract",
    "TaskRecord",
    "TaskResultRef",
    "TaskResult",
    "TaskSummary",
    "TaskRunLedger",
    "TaskStepRun",
    "build_task_execution_assembly_bundle",
    "build_task_runtime_contract",
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
    if name in {
        "TaskFlowDefinition",
        "TaskAgentBinding",
        "AgentTaskConnectionProfile",
        "GeneralTaskProfile",
        "TaskAssignment",
        "SpecificTaskRecord",
        "TaskProjectionBinding",
        "TaskFlowContractBinding",
        "TaskAgentAdoptionPlan",
        "TaskMemoryRequestProfile",
        "TaskCommunicationProtocol",
        "AgentTaskCarryingProfile",
    }:
        from tasks.flow_models import (
            AgentTaskCarryingProfile,
            AgentTaskConnectionProfile,
            GeneralTaskProfile,
            SpecificTaskRecord,
            TaskAgentAdoptionPlan,
            TaskAgentBinding,
            TaskAssignment,
            TaskCommunicationProtocol,
            TaskFlowDefinition,
            TaskFlowContractBinding,
            TaskMemoryRequestProfile,
            TaskProjectionBinding,
        )

        return {
            "GeneralTaskProfile": GeneralTaskProfile,
            "TaskAssignment": TaskAssignment,
            "SpecificTaskRecord": SpecificTaskRecord,
            "TaskProjectionBinding": TaskProjectionBinding,
            "TaskFlowContractBinding": TaskFlowContractBinding,
            "TaskAgentAdoptionPlan": TaskAgentAdoptionPlan,
            "TaskMemoryRequestProfile": TaskMemoryRequestProfile,
            "TaskCommunicationProtocol": TaskCommunicationProtocol,
            "AgentTaskCarryingProfile": AgentTaskCarryingProfile,
            "TaskFlowDefinition": TaskFlowDefinition,
            "TaskAgentBinding": TaskAgentBinding,
            "AgentTaskConnectionProfile": AgentTaskConnectionProfile,
        }[name]
    if name == "TaskFlowRegistry":
        from tasks.flow_registry import TaskFlowRegistry

        return TaskFlowRegistry
    if name in {"TaskWorkflowBinding"}:
        from tasks.workflow_models import TaskWorkflowBinding

        return TaskWorkflowBinding
    if name == "TaskWorkflowRegistry":
        from tasks.workflow_registry import TaskWorkflowRegistry

        return TaskWorkflowRegistry
    if name == "TaskTemplateRegistry":
        from tasks.template_registry import TaskTemplateRegistry

        return TaskTemplateRegistry
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
    if name in {"TaskResult", "TaskRunLedger", "TaskStepRun"}:
        from tasks.run_models import TaskResult, TaskRunLedger, TaskStepRun

        return {
            "TaskResult": TaskResult,
            "TaskRunLedger": TaskRunLedger,
            "TaskStepRun": TaskStepRun,
        }[name]
    if name in {"TaskEvent", "TaskRecord"}:
        from tasks.models import TaskEvent, TaskRecord

        return {"TaskEvent": TaskEvent, "TaskRecord": TaskRecord}[name]
    if name in {"TaskStepBlueprint", "StepInputBinding"}:
        from tasks.step_models import StepInputBinding, TaskStepBlueprint

        return {"TaskStepBlueprint": TaskStepBlueprint, "StepInputBinding": StepInputBinding}[name]
    if name in {"TaskTemplate", "TaskValidationRule"}:
        from tasks.template_models import TaskTemplate, TaskValidationRule

        return {"TaskTemplate": TaskTemplate, "TaskValidationRule": TaskValidationRule}[name]
    if name == "TaskSpec":
        from tasks.spec_models import TaskSpec

        return TaskSpec
    if name in {"TaskIntentContract", "TemplateMatchResult"}:
        from tasks.match_contracts import TaskIntentContract, TemplateMatchResult

        return {
            "TaskIntentContract": TaskIntentContract,
            "TemplateMatchResult": TemplateMatchResult,
        }[name]
    if name in {"ProjectionSelectionResult", "TaskExecutionAssembly"}:
        from tasks.assembly_models import ProjectionSelectionResult, TaskExecutionAssembly

        return {
            "ProjectionSelectionResult": ProjectionSelectionResult,
            "TaskExecutionAssembly": TaskExecutionAssembly,
        }[name]
    if name in {"BundleSpec", "BundleItemSpec"}:
        from tasks.bundle_models import BundleItemSpec, BundleSpec

        return {
            "BundleSpec": BundleSpec,
            "BundleItemSpec": BundleItemSpec,
        }[name]
    if name == "build_task_execution_assembly_bundle":
        from tasks.assembly_builder import build_task_execution_assembly_bundle

        return build_task_execution_assembly_bundle
    if name == "build_task_runtime_contract":
        from tasks.contract_builder import build_task_runtime_contract

        return build_task_runtime_contract
    raise AttributeError(name)
