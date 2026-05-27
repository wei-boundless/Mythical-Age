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
    "TaskExecutionPolicy",
    "TaskMemoryRequestProfile",
    "TaskCommunicationProtocol",
    "TaskGraphDefinition",
    "TaskGraphNodeDefinition",
    "TaskGraphEdgeDefinition",
    "TaskGraphValidationIssue",
    "TaskGraphStandardView",
    "ComposableGraphView",
    "ComposableUnit",
    "UnitInterface",
    "UnitPort",
    "UnitPortEdge",
    "GraphModuleRuntimePlan",
    "build_composable_graph_view",
    "build_task_graph_standard_view",
    "apply_task_graph_standard_view_update",
    "TaskGraphRuntimeSpec",
    "compile_task_graph_definition_runtime_spec",
    "BatchAcceptancePolicy",
    "BatchLifecyclePlan",
    "BatchLifecycleStep",
    "BatchMergePolicy",
    "BatchMergeReadinessPlan",
    "BatchRange",
    "BatchSpec",
    "SplitMergeIssue",
    "StaticSplitPlan",
    "build_static_split_plan",
    "build_static_split_plans_for_graph",
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
    "AgentWorkLifecycleIntent",
    "TaskActivationRequest",
    "TaskLifecycle",
    "TaskRuntimeAssemblyRequest",
    "TaskRuntimeAssemblyRequestBuilder",
    "TaskLifecycleFactory",
    "TaskLifecycleRegistry",
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
        from task_system.contracts.contracts import TaskContract

        return TaskContract
    if name in {"TaskDefinition"}:
        from task_system.tasks.definitions import TaskDefinition

        return TaskDefinition
    if name in {
        "TaskFlowDefinition",
        "TaskAgentBinding",
        "AgentTaskConnectionProfile",
        "GeneralTaskProfile",
        "TaskAssignment",
        "SpecificTaskRecord",
        "TaskDomainRecord",
        "TaskFlowContractBinding",
        "TaskExecutionPolicy",
        "TaskMemoryRequestProfile",
        "TaskCommunicationProtocol",
        "AgentTaskCarryingProfile",
    }:
        from task_system.registry.flow_models import (
            AgentTaskCarryingProfile,
            AgentTaskConnectionProfile,
            GeneralTaskProfile,
            SpecificTaskRecord,
            TaskDomainRecord,
            TaskExecutionPolicy,
            TaskAgentBinding,
            TaskAssignment,
            TaskCommunicationProtocol,
            TaskFlowDefinition,
            TaskFlowContractBinding,
            TaskMemoryRequestProfile,
        )

        return {
            "GeneralTaskProfile": GeneralTaskProfile,
            "TaskAssignment": TaskAssignment,
            "SpecificTaskRecord": SpecificTaskRecord,
            "TaskDomainRecord": TaskDomainRecord,
            "TaskFlowContractBinding": TaskFlowContractBinding,
            "TaskExecutionPolicy": TaskExecutionPolicy,
            "TaskMemoryRequestProfile": TaskMemoryRequestProfile,
            "TaskCommunicationProtocol": TaskCommunicationProtocol,
            "AgentTaskCarryingProfile": AgentTaskCarryingProfile,
            "TaskFlowDefinition": TaskFlowDefinition,
            "TaskAgentBinding": TaskAgentBinding,
            "AgentTaskConnectionProfile": AgentTaskConnectionProfile,
        }[name]
    if name == "TaskFlowRegistry":
        from task_system.registry.flow_registry import TaskFlowRegistry

        return TaskFlowRegistry
    if name in {
        "AgentWorkLifecycleIntent",
        "TaskActivationRequest",
        "TaskLifecycle",
        "TaskRuntimeAssemblyRequest",
    }:
        from task_system import primitives

        return getattr(primitives, name)
    if name == "TaskRuntimeAssemblyRequestBuilder":
        from task_system.assembly import TaskRuntimeAssemblyRequestBuilder

        return TaskRuntimeAssemblyRequestBuilder
    if name in {"TaskLifecycleFactory", "TaskLifecycleRegistry"}:
        from task_system import lifecycle

        return getattr(lifecycle, name)
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
        from task_system.contracts.contract_definition_models import (
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
        from task_system.registry.contract_registry import TaskContractRegistry

        return TaskContractRegistry
    if name in {
        "TaskGraphDefinition",
        "TaskGraphNodeDefinition",
        "TaskGraphEdgeDefinition",
        "TaskGraphValidationIssue",
    }:
        from task_system.graphs.task_graph_models import (
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
    if name in {
        "ComposableGraphView",
        "ComposableUnit",
        "UnitInterface",
        "UnitPort",
        "UnitPortEdge",
        "GraphModuleRuntimePlan",
        "build_composable_graph_view",
    }:
        from task_system.graphs.composable_graph_builder import build_composable_graph_view
        from task_system.graphs.composable_graph_models import (
            ComposableGraphView,
            ComposableUnit,
            GraphModuleRuntimePlan,
            UnitInterface,
            UnitPort,
            UnitPortEdge,
        )

        return {
            "ComposableGraphView": ComposableGraphView,
            "ComposableUnit": ComposableUnit,
            "UnitInterface": UnitInterface,
            "UnitPort": UnitPort,
            "UnitPortEdge": UnitPortEdge,
            "GraphModuleRuntimePlan": GraphModuleRuntimePlan,
            "build_composable_graph_view": build_composable_graph_view,
        }[name]
    if name in {"TaskGraphStandardView", "build_task_graph_standard_view", "apply_task_graph_standard_view_update"}:
        from task_system.graphs.task_graph_standard_models import (
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
        from task_system.compiler.coordination_graph_models import (
            TaskGraphRuntimeSpec,
        )

        return TaskGraphRuntimeSpec
    if name == "compile_task_graph_definition_runtime_spec":
        from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec

        return compile_task_graph_definition_runtime_spec
    if name in {
        "BatchAcceptancePolicy",
        "BatchLifecyclePlan",
        "BatchLifecycleStep",
        "BatchMergePolicy",
        "BatchMergeReadinessPlan",
        "BatchRange",
        "BatchSpec",
        "SplitMergeIssue",
        "StaticSplitPlan",
    }:
        from task_system.planning.task_split_merge_models import (
            BatchAcceptancePolicy,
            BatchLifecyclePlan,
            BatchLifecycleStep,
            BatchMergePolicy,
            BatchMergeReadinessPlan,
            BatchRange,
            BatchSpec,
            SplitMergeIssue,
            StaticSplitPlan,
        )

        return {
            "BatchAcceptancePolicy": BatchAcceptancePolicy,
            "BatchLifecyclePlan": BatchLifecyclePlan,
            "BatchLifecycleStep": BatchLifecycleStep,
            "BatchMergePolicy": BatchMergePolicy,
            "BatchMergeReadinessPlan": BatchMergeReadinessPlan,
            "BatchRange": BatchRange,
            "BatchSpec": BatchSpec,
            "SplitMergeIssue": SplitMergeIssue,
            "StaticSplitPlan": StaticSplitPlan,
        }[name]
    if name in {"build_static_split_plan", "build_static_split_plans_for_graph"}:
        from task_system.planning.task_split_plan_builder import build_static_split_plan, build_static_split_plans_for_graph

        return {
            "build_static_split_plan": build_static_split_plan,
            "build_static_split_plans_for_graph": build_static_split_plans_for_graph,
        }[name]
    if name in {"TaskWorkflowBinding"}:
        from task_system.registry.workflow_models import TaskWorkflowBinding

        return TaskWorkflowBinding
    if name == "TaskWorkflowRegistry":
        from task_system.registry.workflow_registry import TaskWorkflowRegistry

        return TaskWorkflowRegistry
    if name in {"TaskBindingRecord"}:
        from task_system.services.bindings import TaskBindingRecord

        return TaskBindingRecord
    if name in {"SkillRuntimeView"}:
        from task_system.contracts.runtime_contracts import SkillRuntimeView

        mapping = {
            "SkillRuntimeView": SkillRuntimeView,
        }
        return mapping[name]
    if name in {"TaskBindings", "TaskConstraints", "TaskContextRef", "TaskResultRef", "TaskSummary"}:
        from task_system.models.context_models import TaskBindings, TaskConstraints, TaskContextRef, TaskResultRef, TaskSummary

        mapping = {
            "TaskBindings": TaskBindings,
            "TaskConstraints": TaskConstraints,
            "TaskContextRef": TaskContextRef,
            "TaskResultRef": TaskResultRef,
            "TaskSummary": TaskSummary,
        }
        return mapping[name]
    if name in {"TaskResult", "TaskRunLedger", "TaskStepRun"}:
        from task_system.tasks.run_models import TaskResult, TaskRunLedger, TaskStepRun

        return {
            "TaskResult": TaskResult,
            "TaskRunLedger": TaskRunLedger,
            "TaskStepRun": TaskStepRun,
        }[name]
    if name in {"TaskEvent", "TaskRecord"}:
        from task_system.tasks.models import TaskEvent, TaskRecord

        return {"TaskEvent": TaskEvent, "TaskRecord": TaskRecord}[name]
    if name in {"TaskStepBlueprint", "StepInputBinding"}:
        from task_system.tasks.step_models import StepInputBinding, TaskStepBlueprint

        return {"TaskStepBlueprint": TaskStepBlueprint, "StepInputBinding": StepInputBinding}[name]
    if name == "TaskValidationRule":
        from task_system.planning.execution_recipe_models import TaskValidationRule

        return TaskValidationRule
    if name == "ExecutionRecipe":
        from task_system.planning.execution_recipe_models import ExecutionRecipe

        return ExecutionRecipe
    if name == "ExecutionShape":
        from task_system.planning.execution_shape_resolver import ExecutionShape

        return ExecutionShape
    if name == "TaskSpec":
        from task_system.tasks.spec_models import TaskSpec

        return TaskSpec
    if name == "TaskIntentContract":
        from task_system.contracts.match_contracts import TaskIntentContract

        return TaskIntentContract
    if name in {"TaskExecutionAssembly"}:
        from task_system.services.assembly_models import TaskExecutionAssembly

        return {
            "TaskExecutionAssembly": TaskExecutionAssembly,
        }[name]
    if name in {"BundleSpec", "BundleItemSpec"}:
        from task_system.services.bundle_models import BundleItemSpec, BundleSpec

        return {
            "BundleSpec": BundleSpec,
            "BundleItemSpec": BundleItemSpec,
        }[name]
    if name == "build_task_execution_assembly_bundle":
        from task_system.services.assembly_builder import build_task_execution_assembly_bundle

        return build_task_execution_assembly_bundle
    raise AttributeError(name)
