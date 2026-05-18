from .candidates import CandidateEnvelope, CandidateSet
from .commit_gate import (
    RuntimeCommitGateDecision,
    build_assistant_session_message_commit_decision,
    build_blocked_runtime_commit_gate,
    build_task_run_final_commit_decision,
    build_user_message_commit_decision,
)
from .contracts import ControlKernelCandidateContext, PolicyHint, TaskContract, UnitDescriptor
from .execution_graph import CommitCandidate, ExecutionGraph, ExecutionNode
from .kernel import ControlKernel, ControlKernelResult
from .monitor import summarize_runtime_loop_events, summarize_runtime_loop_trace
from .agent_group_models import AgentGroup
from .agent_group_registry import AgentGroupRegistry, default_agent_groups
from .agent_models import AgentDescriptor, AgentLifecycleRecord
from .agent_registry import AgentRegistry, default_agent_descriptors
from .agent_runtime_models import AgentRuntimeProfile
from .agent_runtime_registry import AgentRuntimeRegistry, default_agent_runtime_profiles
from .assembly_models import AgentRuntimeSpec, TaskBodyOrchestration
from .body_models import (
    AgentBodyProfile,
    MemoryScopeProfile,
    OutputBoundaryProfile,
    PromptStructureProfile,
    RuntimeLaneProfile,
)
from .body_registry import BodyProfileRegistry
from .runtime_directive import RuntimeDirective
from .execution_scheduler import BackgroundTaskManager, BackgroundTaskRecord, ExecutionDispatchDecision, resolve_execution_dispatch
from .runtime_lane_registry import RuntimeLaneDescriptor, RuntimeLaneRegistry, default_runtime_lane_descriptors
from .worker_agent_blueprints import WorkerAgentBlueprint, WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from .worker_agent_factory import ProvisionedWorkerAgent, WorkerAgentFactory, default_worker_agent_blueprints
from .resource_gate import (
    ApprovalState,
    ApprovalToken,
    DenialTrackingState,
    OperationGate,
    OperationGatePipelineContext,
    OperationGateResult,
)
from .resource_policy import ResourceDecision, ResourcePolicy
from .resource_policy_builder import RuntimeApprovalContext, build_resource_policy_candidate
from .resource_runtime_view import ResourceRuntimeView, build_resource_runtime_views
from .unit_registry import BASE_UNIT_DESCRIPTORS, UnitCatalog, build_base_unit_catalog
from capability_system import build_default_operation_registry
from tasks.capability_requirements import OperationRequirement, build_operation_requirement


def build_orchestration_runtime_bundle(*args, **kwargs):
    from .assembly_builder import build_orchestration_runtime_bundle as _build

    return _build(*args, **kwargs)


def AgentRuntimeChainAssembler(*args, **kwargs):
    from .agent_runtime_chain import AgentRuntimeChainAssembler as _assembler

    return _assembler(*args, **kwargs)


_RUNTIME_LOOP_EXPORTS = {
    "RuntimeActionRequest",
    "RuntimeActionRequestType",
    "RuntimeCheckpoint",
    "RuntimeCheckpointStore",
    "AgentHandoffEnvelope",
    "AgentRun",
    "AgentRunResult",
    "CoordinationMergeResult",
    "CoordinationNodeRun",
    "CoordinationRun",
    "RuntimeContextInvariantReport",
    "RuntimeContextManager",
    "RuntimeContextObservationRecord",
    "RuntimeContextSnapshot",
    "ExecutionReceipt",
    "OperationExecutionRecord",
    "ReplayPolicy",
    "RuntimeEvent",
    "RuntimeEventLog",
    "RuntimeExecutionStore",
    "RuntimeLoopControlDecision",
    "RuntimeLoopLimits",
    "RuntimeLoopState",
    "RuntimeLoopTraceReader",
    "RuntimeObservation",
    "RuntimeObservationType",
    "RuntimeStateIndex",
    "StageProjectionCycle",
    "StageProjectionSnapshot",
    "TaskRunLoop",
    "TaskRunLoopStartResult",
    "build_executor_error_observation",
    "build_execution_receipt",
    "build_idempotency_token",
    "build_model_response_observation",
    "build_request_fingerprint",
    "build_tool_action_request",
    "build_tool_execution_error_observation",
    "build_tool_result_observation",
    "build_tool_request_runtime_adoption",
    "check_runtime_loop_control",
    "derive_replay_policy",
}


def __getattr__(name: str):
    if name in _RUNTIME_LOOP_EXPORTS:
        from . import runtime_loop

        value = getattr(runtime_loop, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'orchestration' has no attribute {name!r}")

__all__ = [
    "BASE_UNIT_DESCRIPTORS",
    "CandidateEnvelope",
    "CandidateSet",
    "CommitCandidate",
    "ControlKernel",
    "ControlKernelCandidateContext",
    "ControlKernelResult",
    "ExecutionGraph",
    "ExecutionNode",
    "BackgroundTaskManager",
    "BackgroundTaskRecord",
    "ExecutionDispatchDecision",
    "PolicyHint",
    "RuntimeDirective",
    "AgentRuntimeProfile",
    "AgentGroup",
    "AgentGroupRegistry",
    "AgentRuntimeChainAssembler",
    "AgentBodyProfile",
    "AgentDescriptor",
    "AgentLifecycleRecord",
    "AgentRegistry",
    "AgentRuntimeSpec",
    "AgentRuntimeRegistry",
    "ApprovalState",
    "ApprovalToken",
    "MemoryScopeProfile",
    "DenialTrackingState",
    "OperationGate",
    "OperationGatePipelineContext",
    "OperationGateResult",
    "OperationRequirement",
    "OutputBoundaryProfile",
    "PromptStructureProfile",
    "ResourceDecision",
    "ResourcePolicy",
    "ResourceRuntimeView",
    "RuntimeApprovalContext",
    "RuntimeCommitGateDecision",
    "RuntimeLaneProfile",
    "RuntimeLaneDescriptor",
    "RuntimeLaneRegistry",
    "BodyProfileRegistry",
    "build_orchestration_runtime_bundle",
    "RuntimeActionRequest",
    "RuntimeActionRequestType",
    "RuntimeCheckpoint",
    "RuntimeCheckpointStore",
    "AgentRun",
    "AgentRunResult",
    "CoordinationRun",
    "CoordinationNodeRun",
    "AgentHandoffEnvelope",
    "CoordinationMergeResult",
    "RuntimeContextInvariantReport",
    "RuntimeContextManager",
    "RuntimeContextObservationRecord",
    "RuntimeContextSnapshot",
    "ExecutionReceipt",
    "OperationExecutionRecord",
    "ReplayPolicy",
    "RuntimeEvent",
    "RuntimeEventLog",
    "RuntimeExecutionStore",
    "RuntimeLoopControlDecision",
    "RuntimeLoopLimits",
    "RuntimeLoopState",
    "RuntimeLoopTraceReader",
    "RuntimeObservation",
    "RuntimeObservationType",
    "RuntimeStateIndex",
    "StageProjectionCycle",
    "StageProjectionSnapshot",
    "summarize_runtime_loop_events",
    "summarize_runtime_loop_trace",
    "TaskRunLoop",
    "TaskRunLoopStartResult",
    "TaskBodyOrchestration",
    "TaskContract",
    "UnitCatalog",
    "UnitDescriptor",
    "WorkerAgentBlueprint",
    "WorkerAgentFactory",
    "WorkerAgentSpawnRequest",
    "WorkerAgentSpawnResult",
    "ProvisionedWorkerAgent",
    "build_assistant_session_message_commit_decision",
    "build_blocked_runtime_commit_gate",
    "build_resource_policy_candidate",
    "build_resource_runtime_views",
    "build_task_run_final_commit_decision",
    "build_user_message_commit_decision",
    "build_base_unit_catalog",
    "build_default_operation_registry",
    "build_operation_requirement",
    "resolve_execution_dispatch",
    "default_agent_descriptors",
    "default_agent_groups",
    "default_agent_runtime_profiles",
    "default_runtime_lane_descriptors",
    "default_worker_agent_blueprints",
    "build_executor_error_observation",
    "build_execution_receipt",
    "build_idempotency_token",
    "build_model_response_observation",
    "build_request_fingerprint",
    "build_tool_result_observation",
    "build_tool_action_request",
    "build_tool_execution_error_observation",
    "build_tool_request_runtime_adoption",
    "check_runtime_loop_control",
    "derive_replay_policy",
]
