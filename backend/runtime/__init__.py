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
from .graph_runtime import (
    TaskGraphEdgeHandoffState,
    TaskGraphMonitorDecision,
    TaskGraphNodeRunState,
    TaskGraphPhaseState,
    TaskGraphSchedulerState,
    attach_batch_execution_request,
    bootstrap_scheduler_state,
    build_task_graph_run_monitor_view,
    evaluate_task_graph_monitor_snapshot,
)
from .model_gateway import (
    ModelResponseRuntimeExecutor,
    ModelRuntime,
    ModelRuntimeError,
    ModelSpec,
    RuntimeConversationAgent,
    stringify_content,
)
from .shared.checkpoint import RuntimeCheckpoint, RuntimeCheckpointStore
from .shared.context_manager import (
    RuntimeContextInvariantReport,
    RuntimeContextManager,
    RuntimeContextObservationRecord,
    RuntimeContextSnapshot,
)
from .contracts.compiler import compile_coordination_contract_manifest, compile_workflow_contract_manifest
from .contracts.compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledGraphModuleHandoffContract,
    CompiledNodeContract,
    CompiledRuntimeContract,
    CompiledWorkflowContract,
    ContractCompileIssue,
    ContractManifest,
)

from .contracts.runtime_assembly_builder import build_node_runtime_assembly
from .contracts.runtime_assembly_models import (
    HandoffPacket,
    NodeRuntimeAssembly,
    RuntimeAcceptanceContract,
    RuntimeContextSection,
    RuntimeFailureContract,
    RuntimeLoopPolicy,
    RuntimeOutputContract,
)
from .agent_assembly import (
    AgentAssemblyContract,
    AgentInvocation,
    DirectWorkOrder,
    ExecutionPermit,
    GraphModuleWorkOrder,
    HumanWorkOrder,
    NodeWorkOrder,
    WorkOrder,
    build_agent_assembly_contract,
    build_agent_invocation,
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
from .shared.loop_control import RuntimeLoopControlDecision, RuntimeLoopLimits, check_runtime_loop_control
from .shared.models import (
    AgentHandoffEnvelope,
    AgentRun,
    AgentRunResult,
    CoordinationMergeResult,
    CoordinationNodeRun,
    CoordinationRun,
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    RuntimeLoopState,
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
    "RuntimeCheckpoint",
    "RuntimeCheckpointStore",
    "ModelResponseRuntimeExecutor",
    "ModelRuntime",
    "ModelRuntimeError",
    "ModelSpec",
    "RuntimeConversationAgent",
    "RuntimeExecutionStore",
    "TaskGraphEdgeHandoffState",
    "TaskGraphMonitorDecision",
    "TaskGraphNodeRunState",
    "TaskGraphPhaseState",
    "TaskGraphSchedulerState",
    "AgentRun",
    "AgentRunResult",
    "CoordinationRun",
    "CoordinationNodeRun",
    "AgentHandoffEnvelope",
    "CoordinationMergeResult",
    "ProjectProgressLedger",
    "ProjectRuntimeStatus",
    "SupervisionRecord",
    "RuntimeActionRequest",
    "RuntimeActionRequestType",
    "RuntimeContextManager",
    "RuntimeContextInvariantReport",
    "RuntimeContextObservationRecord",
    "RuntimeContextSnapshot",
    "RuntimeEvent",
    "ContractCompileIssue",
    "ContractManifest",
    "CompiledGlobalContract",
    "CompiledWorkflowContract",
    "CompiledNodeContract",
    "CompiledEdgeHandoffContract",
    "CompiledGraphModuleHandoffContract",
    "CompiledRuntimeContract",
    "CompiledAcceptanceContract",
    "AgentAssemblyContract",
    "AgentInvocation",
    "DirectWorkOrder",
    "ExecutionPermit",
    "GraphModuleWorkOrder",
    "HumanWorkOrder",
    "NodeWorkOrder",
    "WorkOrder",
    "NodeRuntimeAssembly",
    "RuntimeContextSection",
    "RuntimeOutputContract",
    "RuntimeAcceptanceContract",
    "RuntimeFailureContract",
    "RuntimeLoopPolicy",
    "HandoffPacket",
    "RuntimeEventLog",
    "RuntimeEventType",
    "RuntimeLoopState",
    "RuntimeLoopControlDecision",
    "RuntimeLoopLimits",
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
    "compile_workflow_contract_manifest",
    "compile_coordination_contract_manifest",
    "build_node_runtime_assembly",
    "build_agent_assembly_contract",
    "build_agent_invocation",
    "attach_batch_execution_request",
    "bootstrap_scheduler_state",
    "build_task_graph_run_monitor_view",
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
    "check_runtime_loop_control",
    "build_round_tool_call_options",
    "build_tool_result_envelope",
    "evaluate_task_graph_monitor_snapshot",
    "extract_tool_call_intents",
    "normalize_tool_call_dicts",
    "stringify_content",
    "tool_calls_for_langchain_messages",
]
