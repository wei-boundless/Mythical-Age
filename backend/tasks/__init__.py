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
    "ContractSpec",
    "ContractField",
    "ArtifactRequirement",
    "AcceptanceRule",
    "RuntimeRequirement",
    "ContextVisibilityPolicy",
    "HandoffPolicy",
    "FailurePolicy",
    "HumanGatePolicy",
    "ContractValidationIssue",
    "TaskContractRegistry",
    "TaskAgentAdoptionPlan",
    "TaskMemoryRequestProfile",
    "TaskCommunicationProtocol",
    "TaskGraphDefinition",
    "TaskGraphNodeDefinition",
    "TaskGraphEdgeDefinition",
    "TaskGraphValidationIssue",
    "TaskGraphStandardView",
    "build_task_graph_standard_view",
    "apply_task_graph_standard_view_update",
    "TaskGraphRuntimeSpec",
    "compile_task_graph_definition_runtime_spec",
    "ProjectionSelectionResult",
    "TaskExecutionAssembly",
    "TaskSpec",
    "TaskIntentContract",
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
    "TaskValidationRule",
    "ExecutionRecipe",
    "ExecutionShape",
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
        "ContractSpec",
        "ContractField",
        "ArtifactRequirement",
        "AcceptanceRule",
        "RuntimeRequirement",
        "ContextVisibilityPolicy",
        "HandoffPolicy",
        "FailurePolicy",
        "HumanGatePolicy",
        "ContractValidationIssue",
    }:
        from tasks.contract_definition_models import (
            AcceptanceRule,
            ArtifactRequirement,
            ContextVisibilityPolicy,
            ContractField,
            ContractSpec,
            ContractValidationIssue,
            FailurePolicy,
            HandoffPolicy,
            HumanGatePolicy,
            RuntimeRequirement,
        )

        return {
            "ContractSpec": ContractSpec,
            "ContractField": ContractField,
            "ArtifactRequirement": ArtifactRequirement,
            "AcceptanceRule": AcceptanceRule,
            "RuntimeRequirement": RuntimeRequirement,
            "ContextVisibilityPolicy": ContextVisibilityPolicy,
            "HandoffPolicy": HandoffPolicy,
            "FailurePolicy": FailurePolicy,
            "HumanGatePolicy": HumanGatePolicy,
            "ContractValidationIssue": ContractValidationIssue,
        }[name]
    if name == "TaskContractRegistry":
        from tasks.contract_registry import TaskContractRegistry

        return TaskContractRegistry
    if name in {
        "TaskGraphDefinition",
        "TaskGraphNodeDefinition",
        "TaskGraphEdgeDefinition",
        "TaskGraphValidationIssue",
    }:
        from tasks.task_graph_models import (
            TaskGraphDefinition,
            TaskGraphEdgeDefinition,
            TaskGraphNodeDefinition,
            TaskGraphValidationIssue,
        )

        return {
            "TaskGraphDefinition": TaskGraphDefinition,
            "TaskGraphNodeDefinition": TaskGraphNodeDefinition,
            "TaskGraphEdgeDefinition": TaskGraphEdgeDefinition,
            "TaskGraphValidationIssue": TaskGraphValidationIssue,
        }[name]
    if name in {"TaskGraphStandardView", "build_task_graph_standard_view", "apply_task_graph_standard_view_update"}:
        from tasks.task_graph_standard_models import (
            TaskGraphStandardView,
            apply_task_graph_standard_view_update,
            build_task_graph_standard_view,
        )

        return {
            "TaskGraphStandardView": TaskGraphStandardView,
            "build_task_graph_standard_view": build_task_graph_standard_view,
            "apply_task_graph_standard_view_update": apply_task_graph_standard_view_update,
        }[name]
    if name == "TaskGraphRuntimeSpec":
        from tasks.coordination_graph_models import (
            TaskGraphRuntimeSpec,
        )

        return TaskGraphRuntimeSpec
    if name == "compile_task_graph_definition_runtime_spec":
        from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec

        return compile_task_graph_definition_runtime_spec
    if name in {"TaskWorkflowBinding"}:
        from tasks.workflow_models import TaskWorkflowBinding

        return TaskWorkflowBinding
    if name == "TaskWorkflowRegistry":
        from tasks.workflow_registry import TaskWorkflowRegistry

        return TaskWorkflowRegistry
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
    if name == "TaskValidationRule":
        from tasks.execution_recipe_models import TaskValidationRule

        return TaskValidationRule
    if name == "ExecutionRecipe":
        from tasks.execution_recipe_models import ExecutionRecipe

        return ExecutionRecipe
    if name == "ExecutionShape":
        from tasks.execution_shape_resolver import ExecutionShape

        return ExecutionShape
    if name == "TaskSpec":
        from tasks.spec_models import TaskSpec

        return TaskSpec
    if name == "TaskIntentContract":
        from tasks.match_contracts import TaskIntentContract

        return TaskIntentContract
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
