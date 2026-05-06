"""Task system public exports."""

from __future__ import annotations

from typing import Any


__all__ = [
    "GeneralTaskProfile",
    "TaskAssignment",
    "SpecificTaskRecord",
    "TaskDomainRecord",
    "AgentTaskCarryingProfile",
    "TaskWorkflowBinding",
    "TaskProjectionBinding",
    "TaskFlowContractBinding",
    "TaskAgentAdoptionPlan",
    "TaskMemoryRequestProfile",
    "TaskCommunicationProtocol",
    "CoordinationGraphSpec",
    "CoordinationGraphNode",
    "CoordinationGraphEdge",
    "CoordinationGraphValidationIssue",
    "compile_coordination_graph_spec",
    "ProjectionSelectionResult",
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
    "TaskRecord",
    "TaskResultRef",
    "TaskResult",
    "TaskSummary",
    "TaskRunLedger",
    "TaskStepRun",
    "build_task_execution_assembly_bundle",
]


def __getattr__(name: str) -> Any:
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
        "TaskDomainRecord",
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
            TaskDomainRecord,
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
            "TaskDomainRecord": TaskDomainRecord,
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
    if name in {
        "CoordinationGraphSpec",
        "CoordinationGraphNode",
        "CoordinationGraphEdge",
        "CoordinationGraphValidationIssue",
    }:
        from tasks.coordination_graph_models import (
            CoordinationGraphEdge,
            CoordinationGraphNode,
            CoordinationGraphSpec,
            CoordinationGraphValidationIssue,
        )

        return {
            "CoordinationGraphSpec": CoordinationGraphSpec,
            "CoordinationGraphNode": CoordinationGraphNode,
            "CoordinationGraphEdge": CoordinationGraphEdge,
            "CoordinationGraphValidationIssue": CoordinationGraphValidationIssue,
        }[name]
    if name == "compile_coordination_graph_spec":
        from tasks.coordination_graph_compiler import compile_coordination_graph_spec

        return compile_coordination_graph_spec
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
    if name in {"SkillRuntimeView"}:
        from tasks.runtime_contracts import SkillRuntimeView

        mapping = {
            "SkillRuntimeView": SkillRuntimeView,
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
    raise AttributeError(name)
