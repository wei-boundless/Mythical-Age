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
from .runtime_directive import RuntimeDirective
from .execution_scheduler import BackgroundTaskManager, BackgroundTaskRecord, ExecutionDispatchDecision, resolve_execution_dispatch
from .runtime_lane_registry import RuntimeLaneDescriptor, RuntimeLaneRegistry, default_runtime_lane_descriptors
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
from task_system.contracts.capability_requirements import OperationRequirement, build_operation_requirement


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
        from importlib import import_module

        runtime = import_module("runtime")
        value = getattr(runtime, name)
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
    "ApprovalState",
    "ApprovalToken",
    "DenialTrackingState",
    "OperationGate",
    "OperationGatePipelineContext",
    "OperationGateResult",
    "OperationRequirement",
    "ResourceDecision",
    "ResourcePolicy",
    "ResourceRuntimeView",
    "RuntimeApprovalContext",
    "RuntimeCommitGateDecision",
    "RuntimeLaneDescriptor",
    "RuntimeLaneRegistry",
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
    "TaskContract",
    "UnitCatalog",
    "UnitDescriptor",
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
    "default_runtime_lane_descriptors",
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
