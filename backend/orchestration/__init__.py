from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentRun": ("runtime", "AgentRun"),
    "AgentRunResult": ("runtime", "AgentRunResult"),
    "ApprovalState": ("permissions", "ApprovalState"),
    "ApprovalToken": ("permissions", "ApprovalToken"),
    "BASE_UNIT_DESCRIPTORS": (".unit_registry", "BASE_UNIT_DESCRIPTORS"),
    "BackgroundTaskManager": (".execution_scheduler", "BackgroundTaskManager"),
    "BackgroundTaskRecord": (".execution_scheduler", "BackgroundTaskRecord"),
    "CandidateEnvelope": (".candidates", "CandidateEnvelope"),
    "CandidateSet": (".candidates", "CandidateSet"),
    "CommitCandidate": (".execution_graph", "CommitCandidate"),
    "ControlKernel": (".kernel", "ControlKernel"),
    "ControlKernelCandidateContext": (".contracts", "ControlKernelCandidateContext"),
    "ControlKernelResult": (".kernel", "ControlKernelResult"),
    "DenialTrackingState": ("permissions", "DenialTrackingState"),
    "ExecutionDispatchDecision": (".execution_scheduler", "ExecutionDispatchDecision"),
    "ExecutionGraph": (".execution_graph", "ExecutionGraph"),
    "ExecutionNode": (".execution_graph", "ExecutionNode"),
    "ExecutionReceipt": ("runtime", "ExecutionReceipt"),
    "OperationExecutionRecord": ("runtime", "OperationExecutionRecord"),
    "OperationGate": ("permissions", "OperationGate"),
    "OperationGatePipelineContext": ("permissions", "OperationGatePipelineContext"),
    "OperationGateResult": ("permissions", "OperationGateResult"),
    "OperationRequirement": ("task_system.contracts.capability_requirements", "OperationRequirement"),
    "PolicyHint": (".contracts", "PolicyHint"),
    "ReplayPolicy": ("runtime", "ReplayPolicy"),
    "ResourceDecision": ("permissions", "ResourceDecision"),
    "ResourcePolicy": ("permissions", "ResourcePolicy"),
    "ResourceRuntimeView": (".resource_runtime_view", "ResourceRuntimeView"),
    "RuntimeActionRequest": ("runtime", "RuntimeActionRequest"),
    "RuntimeActionRequestType": ("runtime", "RuntimeActionRequestType"),
    "RuntimeApprovalContext": ("permissions", "RuntimeApprovalContext"),
    "RuntimeCommitGateDecision": (".commit_gate", "RuntimeCommitGateDecision"),
    "RuntimeDirective": (".runtime_directive", "RuntimeDirective"),
    "RuntimeEvent": ("runtime", "RuntimeEvent"),
    "RuntimeEventLog": ("runtime", "RuntimeEventLog"),
    "RuntimeExecutionStore": ("runtime", "RuntimeExecutionStore"),
    "RuntimeObservation": ("runtime", "RuntimeObservation"),
    "RuntimeObservationType": ("runtime", "RuntimeObservationType"),
    "RuntimeStateIndex": ("runtime", "RuntimeStateIndex"),
    "TaskContract": (".contracts", "TaskContract"),
    "UnitCatalog": (".unit_registry", "UnitCatalog"),
    "UnitDescriptor": (".contracts", "UnitDescriptor"),
    "build_assistant_session_message_commit_decision": (
        ".commit_gate",
        "build_assistant_session_message_commit_decision",
    ),
    "build_base_unit_catalog": (".unit_registry", "build_base_unit_catalog"),
    "build_blocked_runtime_commit_gate": (".commit_gate", "build_blocked_runtime_commit_gate"),
    "build_default_operation_registry": ("capability_system", "build_default_operation_registry"),
    "build_execution_receipt": ("runtime", "build_execution_receipt"),
    "build_executor_error_observation": ("runtime", "build_executor_error_observation"),
    "build_idempotency_token": ("runtime", "build_idempotency_token"),
    "build_model_response_observation": ("runtime", "build_model_response_observation"),
    "build_operation_requirement": (
        "task_system.contracts.capability_requirements",
        "build_operation_requirement",
    ),
    "build_request_fingerprint": ("runtime", "build_request_fingerprint"),
    "build_resource_policy_candidate": ("permissions", "build_resource_policy_candidate"),
    "build_resource_runtime_views": (".resource_runtime_view", "build_resource_runtime_views"),
    "build_task_run_final_commit_decision": (".commit_gate", "build_task_run_final_commit_decision"),
    "build_tool_action_request": ("runtime", "build_tool_action_request"),
    "build_tool_execution_error_observation": ("runtime", "build_tool_execution_error_observation"),
    "build_tool_request_runtime_admission": ("runtime", "build_tool_request_runtime_admission"),
    "build_tool_result_observation": ("runtime", "build_tool_result_observation"),
    "build_user_message_commit_decision": (".commit_gate", "build_user_message_commit_decision"),
    "derive_replay_policy": ("runtime", "derive_replay_policy"),
    "resolve_execution_dispatch": (".execution_scheduler", "resolve_execution_dispatch"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


