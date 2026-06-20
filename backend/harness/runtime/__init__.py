from __future__ import annotations

from typing import TYPE_CHECKING

from .assembly import RuntimeAssembly, RuntimeAssemblyProfile, assemble_runtime, build_runtime_assembly_profile
from .active_turn import ActiveTurnConflict, ActiveTurnMismatch, ActiveTurnRecord, ActiveTurnRegistry
from .compiler import RuntimeCompilationResult, RuntimeCompiler
from .envelope import RuntimeEnvelope
from .agent_run_supervisor import AgentRunSupervisor
from .agent_runtime_cell import AgentRuntimeCell
from .agent_scope import AgentRunScope
from .control_bus import RuntimeControlBus
from .control_events import RuntimeSignalEnvelope, RuntimeSignalScope
from .control_snapshot import RuntimeControlSnapshot
from .execution_context import ExecutionContext, build_execution_context
from .invocation_packet import RuntimeInvocationPacket
from .packet_assembler import build_single_agent_turn_packet_context, build_task_execution_packet_context
from .output_commit_authority import OutputCommitAuthority, OutputCommitRequest, OutputCommitResult
from .packet_context import (
    RuntimePacketContext,
    RuntimePacketModelActionSurface,
    runtime_packet_evidence_projection_event_payload,
    runtime_packet_evidence_projection_ref,
    runtime_packet_evidence_signal_scope,
)
from .request_facts import TurnInputFacts, build_turn_input_facts
from .runtime_policy import artifact_policy_from_task_execution_assembly, model_stream_policy_from_task_execution_assembly
from .services import AgentRuntimeServices, TaskExecutorServices
from .single_agent_host import SingleAgentRuntimeHost
from .tool_batch_planner import (
    ToolBatchGroup,
    ToolBatchItem,
    ToolBatchPlan,
    ToolConcurrencyDescriptor,
    ToolResourceLock,
    build_tool_batch_plan,
)
from .tool_plan import RuntimeToolPlan, build_runtime_tool_plan, tool_instances_for_runtime_tool_plan

if TYPE_CHECKING:
    from .semantic_compaction_adapter import RegisteredSemanticCompactionWorker, build_registered_semantic_compaction_worker

__all__ = [
    "AgentRuntimeServices",
    "AgentRunScope",
    "AgentRunSupervisor",
    "AgentRuntimeCell",
    "ActiveTurnConflict",
    "ActiveTurnMismatch",
    "ActiveTurnRecord",
    "ActiveTurnRegistry",
    "TaskExecutorServices",
    "TurnInputFacts",
    "SingleAgentRuntimeHost",
    "RuntimeAssembly",
    "RuntimeAssemblyProfile",
    "RuntimeCompilationResult",
    "RuntimeCompiler",
    "RuntimeControlBus",
    "RuntimeControlSnapshot",
    "RuntimeEnvelope",
    "RuntimeSignalEnvelope",
    "RuntimeSignalScope",
    "RuntimePacketContext",
    "RuntimePacketModelActionSurface",
    "OutputCommitAuthority",
    "OutputCommitRequest",
    "OutputCommitResult",
    "runtime_packet_evidence_projection_event_payload",
    "runtime_packet_evidence_projection_ref",
    "runtime_packet_evidence_signal_scope",
    "ExecutionContext",
    "RuntimeInvocationPacket",
    "RuntimeToolPlan",
    "RegisteredSemanticCompactionWorker",
    "ToolBatchGroup",
    "ToolBatchItem",
    "ToolBatchPlan",
    "ToolConcurrencyDescriptor",
    "ToolResourceLock",
    "artifact_policy_from_task_execution_assembly",
    "assemble_runtime",
    "build_runtime_assembly_profile",
    "build_execution_context",
    "build_runtime_tool_plan",
    "build_registered_semantic_compaction_worker",
    "build_single_agent_turn_packet_context",
    "build_task_execution_packet_context",
    "build_tool_batch_plan",
    "build_turn_input_facts",
    "model_stream_policy_from_task_execution_assembly",
    "tool_instances_for_runtime_tool_plan",
]


def __getattr__(name: str):
    if name in {"RegisteredSemanticCompactionWorker", "build_registered_semantic_compaction_worker"}:
        from .semantic_compaction_adapter import RegisteredSemanticCompactionWorker, build_registered_semantic_compaction_worker

        return {
            "RegisteredSemanticCompactionWorker": RegisteredSemanticCompactionWorker,
            "build_registered_semantic_compaction_worker": build_registered_semantic_compaction_worker,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
