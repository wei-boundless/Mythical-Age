from __future__ import annotations

from .models import AgentAssemblyContract, ExecutionResult, NodeResultEnvelope, SubRuntimeResultEnvelope


def project_execution_result(assembly: AgentAssemblyContract, *, result: ExecutionResult) -> ExecutionResult:
    if result.assembly_id != assembly.assembly_id:
        raise ValueError("execution result assembly mismatch")
    return result


def project_node_result_envelope(
    assembly: AgentAssemblyContract,
    *,
    coordination_run_id: str,
    node_id: str,
    result: ExecutionResult,
) -> NodeResultEnvelope:
    return NodeResultEnvelope(
        envelope_id="",
        coordination_run_id=coordination_run_id,
        work_order_id=assembly.work_order_id,
        assembly_id=assembly.assembly_id,
        node_id=node_id,
        stage_id=assembly.stage_id,
        task_ref=assembly.task_ref,
        executor_type=assembly.executor_type,
        accepted=True,
        status=result.status,
        result_refs=tuple(result.result_refs),
        artifact_refs=tuple(result.artifact_refs),
        output_refs=tuple(result.output_refs),
        final_content=result.content,
        execution_result=result,
        diagnostics=dict(result.diagnostics),
        metadata=dict(result.metadata),
    )


def project_subruntime_result(
    assembly: AgentAssemblyContract,
    *,
    invocation_id: str,
    kind: str,
    content: str,
) -> SubRuntimeResultEnvelope:
    return SubRuntimeResultEnvelope(
        result_id="",
        invocation_id=invocation_id,
        kind=kind,
        work_order_id=assembly.work_order_id,
        assembly_id=assembly.assembly_id,
        content=content,
    )
