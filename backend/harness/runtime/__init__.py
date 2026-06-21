from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ActiveTurnConflict": ("harness.runtime.active_turn", "ActiveTurnConflict"),
    "ActiveTurnMismatch": ("harness.runtime.active_turn", "ActiveTurnMismatch"),
    "ActiveTurnRecord": ("harness.runtime.active_turn", "ActiveTurnRecord"),
    "ActiveTurnRegistry": ("harness.runtime.active_turn", "ActiveTurnRegistry"),
    "AgentRunScope": ("harness.runtime.agent_scope", "AgentRunScope"),
    "AgentRunSupervisor": ("harness.runtime.agent_run_supervisor", "AgentRunSupervisor"),
    "AgentRuntimeCell": ("harness.runtime.agent_runtime_cell", "AgentRuntimeCell"),
    "AgentRuntimeServices": ("harness.runtime.services", "AgentRuntimeServices"),
    "ExecutionContext": ("harness.runtime.execution_context", "ExecutionContext"),
    "OutputCommitAuthority": ("harness.runtime.output_commit_authority", "OutputCommitAuthority"),
    "OutputCommitRequest": ("harness.runtime.output_commit_authority", "OutputCommitRequest"),
    "OutputCommitResult": ("harness.runtime.output_commit_authority", "OutputCommitResult"),
    "RegisteredSemanticCompactionWorker": (
        "harness.runtime.semantic_compaction_adapter",
        "RegisteredSemanticCompactionWorker",
    ),
    "RuntimeAssembly": ("harness.runtime.assembly", "RuntimeAssembly"),
    "RuntimeAssemblyProfile": ("harness.runtime.assembly", "RuntimeAssemblyProfile"),
    "RuntimeCompilationResult": ("harness.runtime.compiler", "RuntimeCompilationResult"),
    "RuntimeCompiler": ("harness.runtime.compiler", "RuntimeCompiler"),
    "RuntimeControlSnapshot": ("harness.runtime.control_snapshot", "RuntimeControlSnapshot"),
    "RuntimeEnvelope": ("harness.runtime.envelope", "RuntimeEnvelope"),
    "RuntimeGateway": ("harness.runtime.runtime_gateway", "RuntimeGateway"),
    "RuntimeInvocationPacket": ("harness.runtime.invocation_packet", "RuntimeInvocationPacket"),
    "RuntimePacketContext": ("harness.runtime.packet_context", "RuntimePacketContext"),
    "RuntimePacketModelActionSurface": ("harness.runtime.packet_context", "RuntimePacketModelActionSurface"),
    "RuntimeSignalEnvelope": ("harness.runtime.control_events", "RuntimeSignalEnvelope"),
    "RuntimeSignalScope": ("harness.runtime.control_events", "RuntimeSignalScope"),
    "RuntimeToolPlan": ("harness.runtime.tool_plan", "RuntimeToolPlan"),
    "SingleAgentRuntimeHost": ("harness.runtime.single_agent_host", "SingleAgentRuntimeHost"),
    "TaskExecutorServices": ("harness.runtime.services", "TaskExecutorServices"),
    "ToolBatchGroup": ("harness.runtime.tool_batch_planner", "ToolBatchGroup"),
    "ToolBatchItem": ("harness.runtime.tool_batch_planner", "ToolBatchItem"),
    "ToolBatchPlan": ("harness.runtime.tool_batch_planner", "ToolBatchPlan"),
    "ToolConcurrencyDescriptor": ("harness.runtime.tool_batch_planner", "ToolConcurrencyDescriptor"),
    "ToolResourceLock": ("harness.runtime.tool_batch_planner", "ToolResourceLock"),
    "TurnInputFacts": ("harness.runtime.request_facts", "TurnInputFacts"),
    "artifact_policy_from_task_execution_assembly": (
        "harness.runtime.runtime_policy",
        "artifact_policy_from_task_execution_assembly",
    ),
    "assemble_runtime": ("harness.runtime.assembly", "assemble_runtime"),
    "build_execution_context": ("harness.runtime.execution_context", "build_execution_context"),
    "build_registered_semantic_compaction_worker": (
        "harness.runtime.semantic_compaction_adapter",
        "build_registered_semantic_compaction_worker",
    ),
    "build_runtime_assembly_profile": ("harness.runtime.assembly", "build_runtime_assembly_profile"),
    "build_runtime_tool_plan": ("harness.runtime.tool_plan", "build_runtime_tool_plan"),
    "build_single_agent_turn_packet_context": (
        "harness.runtime.packet_assembler",
        "build_single_agent_turn_packet_context",
    ),
    "build_task_execution_packet_context": (
        "harness.runtime.packet_assembler",
        "build_task_execution_packet_context",
    ),
    "build_tool_batch_plan": ("harness.runtime.tool_batch_planner", "build_tool_batch_plan"),
    "build_turn_input_facts": ("harness.runtime.request_facts", "build_turn_input_facts"),
    "model_stream_policy_from_task_execution_assembly": (
        "harness.runtime.runtime_policy",
        "model_stream_policy_from_task_execution_assembly",
    ),
    "runtime_packet_evidence_projection_event_payload": (
        "harness.runtime.packet_context",
        "runtime_packet_evidence_projection_event_payload",
    ),
    "runtime_packet_evidence_projection_ref": (
        "harness.runtime.packet_context",
        "runtime_packet_evidence_projection_ref",
    ),
    "runtime_packet_evidence_signal_scope": (
        "harness.runtime.packet_context",
        "runtime_packet_evidence_signal_scope",
    ),
    "tool_instances_for_runtime_tool_plan": (
        "harness.runtime.tool_plan",
        "tool_instances_for_runtime_tool_plan",
    ),
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
