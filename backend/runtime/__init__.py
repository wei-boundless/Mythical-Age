from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentRun": ("runtime.shared.models", "AgentRun"),
    "AgentRunResult": ("runtime.shared.models", "AgentRunResult"),
    "ExecutionReceipt": ("runtime.shared.execution_record", "ExecutionReceipt"),
    "ModelResponseRuntimeExecutor": ("runtime.model_gateway.model_response", "ModelResponseRuntimeExecutor"),
    "ModelRuntime": ("runtime.model_gateway.model_runtime", "ModelRuntime"),
    "ModelRuntimeError": ("runtime.model_gateway.model_runtime", "ModelRuntimeError"),
    "ModelSpec": ("runtime.model_gateway.model_runtime", "ModelSpec"),
    "OperationExecutionRecord": ("runtime.shared.execution_record", "OperationExecutionRecord"),
    "ProjectProgressLedger": ("runtime.shared.models", "ProjectProgressLedger"),
    "ProjectRuntimeStatus": ("runtime.shared.models", "ProjectRuntimeStatus"),
    "ReplayPolicy": ("runtime.shared.execution_record", "ReplayPolicy"),
    "RuntimeActionRequest": ("runtime.shared.action_request", "RuntimeActionRequest"),
    "RuntimeActionRequestType": ("runtime.shared.action_request", "RuntimeActionRequestType"),
    "RuntimeConversationAgent": ("runtime.model_gateway.model_runtime", "RuntimeConversationAgent"),
    "RuntimeEvent": ("runtime.shared.events", "RuntimeEvent"),
    "RuntimeEventLog": ("runtime.shared.event_log", "RuntimeEventLog"),
    "RuntimeEventType": ("runtime.shared.events", "RuntimeEventType"),
    "RuntimeExecutionStore": ("runtime.shared.execution_record", "RuntimeExecutionStore"),
    "RuntimeObservation": ("runtime.shared.action_request", "RuntimeObservation"),
    "RuntimeObservationType": ("runtime.shared.action_request", "RuntimeObservationType"),
    "RuntimeStateIndex": ("runtime.memory.state_index", "RuntimeStateIndex"),
    "RuntimeTerminalReason": ("runtime.shared.models", "RuntimeTerminalReason"),
    "RuntimeTransition": ("runtime.shared.models", "RuntimeTransition"),
    "SupervisionRecord": ("runtime.shared.models", "SupervisionRecord"),
    "TaskRun": ("runtime.shared.models", "TaskRun"),
    "TaskRunStatus": ("runtime.shared.models", "TaskRunStatus"),
    "ToolCallBindingOptions": ("runtime.tool_runtime.tool_call_policy", "ToolCallBindingOptions"),
    "ToolCallIntent": ("runtime.tool_runtime.tool_call_intent", "ToolCallIntent"),
    "ToolRepetitionGuard": ("runtime.shared.tool_repetition_guard", "ToolRepetitionGuard"),
    "ToolResultEnvelope": ("runtime.tool_runtime.tool_result_envelope", "ToolResultEnvelope"),
    "ToolRuntimeExecutor": ("runtime.tool_runtime.tool_executor", "ToolRuntimeExecutor"),
    "WorkerAgentBlueprint": ("agent_system.registry.worker_agent_blueprints", "WorkerAgentBlueprint"),
    "WorkerAgentSpawnRequest": ("agent_system.registry.worker_agent_blueprints", "WorkerAgentSpawnRequest"),
    "WorkerAgentSpawnResult": ("agent_system.registry.worker_agent_blueprints", "WorkerAgentSpawnResult"),
    "build_executor_error_observation": ("runtime.shared.action_request", "build_executor_error_observation"),
    "build_execution_receipt": ("runtime.shared.execution_record", "build_execution_receipt"),
    "build_idempotency_token": ("runtime.shared.execution_record", "build_idempotency_token"),
    "build_model_response_observation": ("runtime.shared.action_request", "build_model_response_observation"),
    "build_model_response_runtime_admission": ("permissions", "build_model_response_runtime_admission"),
    "build_request_fingerprint": ("runtime.shared.execution_record", "build_request_fingerprint"),
    "build_round_tool_call_options": ("runtime.tool_runtime.tool_call_policy", "build_round_tool_call_options"),
    "build_tool_action_request": ("runtime.shared.action_request", "build_tool_action_request"),
    "build_tool_execution_error_observation": ("runtime.shared.action_request", "build_tool_execution_error_observation"),
    "build_tool_result_envelope": ("runtime.tool_runtime.tool_result_envelope", "build_tool_result_envelope"),
    "build_tool_result_observation": ("runtime.shared.action_request", "build_tool_result_observation"),
    "derive_replay_policy": ("runtime.shared.execution_record", "derive_replay_policy"),
    "extract_tool_call_intents": ("runtime.tool_runtime.provider_tool_call_adapter", "extract_tool_call_intents"),
    "normalize_tool_call_dicts": ("runtime.tool_runtime.provider_tool_call_adapter", "normalize_tool_call_dicts"),
    "stringify_content": ("runtime.model_gateway.model_runtime", "stringify_content"),
    "tool_calls_for_langchain_messages": ("runtime.tool_runtime.provider_tool_call_adapter", "tool_calls_for_langchain_messages"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
