from __future__ import annotations

from typing import TYPE_CHECKING

from .assembly import RuntimeAssembly, RuntimeAssemblyProfile, assemble_runtime, build_runtime_assembly_profile
from .active_turn import ActiveTurnConflict, ActiveTurnMismatch, ActiveTurnRecord, ActiveTurnRegistry, TurnSteerResult
from .compiler import RuntimeCompilationResult, RuntimeCompiler
from .envelope import RuntimeEnvelope
from .execution_context import ExecutionContext, build_execution_context
from .invocation_packet import RuntimeInvocationPacket
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
    "RuntimeEnvelope",
    "ExecutionContext",
    "RuntimeInvocationPacket",
    "RuntimeToolPlan",
    "RegisteredSemanticCompactionWorker",
    "ToolBatchGroup",
    "ToolBatchItem",
    "ToolBatchPlan",
    "ToolConcurrencyDescriptor",
    "ToolResourceLock",
    "TurnSteerResult",
    "artifact_policy_from_task_execution_assembly",
    "assemble_runtime",
    "build_runtime_assembly_profile",
    "build_execution_context",
    "build_runtime_tool_plan",
    "build_registered_semantic_compaction_worker",
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
