from .shared.action_request import (
    RuntimeActionRequest,
    RuntimeActionRequestType,
    RuntimeObservation,
    RuntimeObservationType,
    build_executor_error_observation,
    build_model_response_observation,
    build_tool_execution_error_observation,
    build_tool_result_observation,
    build_tool_action_request,
)
from .model_gateway import (
    ModelResponseRuntimeExecutor,
    ModelRuntime,
    ModelRuntimeError,
    ModelSpec,
    RuntimeConversationAgent,
    stringify_content,
)
from .shared.event_log import RuntimeEventLog
from .shared.events import RuntimeEvent, RuntimeEventType
from .shared.execution_record import (
    ExecutionReceipt,
    OperationExecutionRecord,
    ReplayPolicy,
    RuntimeExecutionStore,
    build_execution_receipt,
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from .shared.models import (
    AgentRun,
    AgentRunResult,
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    RuntimeTerminalReason,
    RuntimeTransition,
    SupervisionRecord,
    TaskRun,
    TaskRunStatus,
)
from .memory.state_index import RuntimeStateIndex
from .shared.tool_repetition_guard import ToolRepetitionGuard
from .tool_runtime import (
    ToolCallBindingOptions,
    ToolCallIntent,
    ToolResultEnvelope,
    ToolRuntimeExecutor,
    build_round_tool_call_options,
    build_tool_result_envelope,
    extract_tool_call_intents,
    normalize_tool_call_dicts,
    tool_calls_for_langchain_messages,
)
from agent_system.registry.worker_agent_blueprints import WorkerAgentBlueprint, WorkerAgentSpawnRequest, WorkerAgentSpawnResult

_LAZY_EXPORTS = {
    "build_model_response_runtime_admission": ("permissions", "build_model_response_runtime_admission"),
    "build_tool_request_runtime_admission": ("permissions", "build_tool_request_runtime_admission"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'runtime' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value


__all__ = [
    "ModelResponseRuntimeExecutor",
    "ModelRuntime",
    "ModelRuntimeError",
    "ModelSpec",
    "RuntimeConversationAgent",
    "RuntimeExecutionStore",
    "AgentRun",
    "AgentRunResult",
    "ProjectProgressLedger",
    "ProjectRuntimeStatus",
    "SupervisionRecord",
    "RuntimeActionRequest",
    "RuntimeActionRequestType",
    "RuntimeEvent",
    "RuntimeEventLog",
    "RuntimeEventType",
    "RuntimeObservation",
    "RuntimeObservationType",
    "ReplayPolicy",
    "ExecutionReceipt",
    "OperationExecutionRecord",
    "RuntimeStateIndex",
    "RuntimeTerminalReason",
    "RuntimeTransition",
    "TaskRun",
    "TaskRunStatus",
    "ToolCallBindingOptions",
    "ToolCallIntent",
    "ToolResultEnvelope",
    "ToolRuntimeExecutor",
    "ToolRepetitionGuard",
    "WorkerAgentBlueprint",
    "WorkerAgentSpawnRequest",
    "WorkerAgentSpawnResult",
    "build_executor_error_observation",
    "build_execution_receipt",
    "build_idempotency_token",
    "build_model_response_runtime_admission",
    "build_model_response_observation",
    "build_tool_result_observation",
    "build_tool_execution_error_observation",
    "build_tool_request_runtime_admission",
    "build_tool_action_request",
    "build_request_fingerprint",
    "derive_replay_policy",
    "build_round_tool_call_options",
    "build_tool_result_envelope",
    "extract_tool_call_intents",
    "normalize_tool_call_dicts",
    "stringify_content",
    "tool_calls_for_langchain_messages",
]


