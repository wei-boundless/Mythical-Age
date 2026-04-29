from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AgentRuntimeChainPreview:
    """Single-agent runtime chain assembly result.

    This is the new main-chain boundary. It connects task, soul, memory,
    context, orchestration, operation, and commit previews while keeping query
    runtime as an adapter.
    """

    chain_id: str
    session_id: str
    task_id: str
    task_operation_preview_ref: str
    memory_runtime_view_ref: str = ""
    context_policy_authority: str = "context_policy_preview"
    orchestration_plan_ref: str = ""
    operation_gate_ref: str = ""
    commit_gate_ref: str = ""
    status: str = "blocked"
    reason: str = "runtime_directive_missing"
    query_runtime_role: str = "adapter_only"
    topology_mode: str = "single_agent"
    preview_only: bool = True
    runtime_executable: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.preview_only:
            raise ValueError("AgentRuntimeChainPreview must remain preview_only")
        if self.runtime_executable:
            raise ValueError("AgentRuntimeChainPreview cannot be runtime executable")
        if self.query_runtime_role != "adapter_only":
            raise ValueError("QueryRuntime must stay adapter_only in the new chain")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_agent_runtime_chain_preview(
    *,
    session_id: str,
    task_operation_preview: dict[str, Any],
    memory_runtime_view: dict[str, Any] | None = None,
    context_policy_preview: dict[str, Any] | None = None,
) -> AgentRuntimeChainPreview:
    task_contract = dict(task_operation_preview.get("task_contract") or {})
    task_id = str(task_contract.get("task_id") or "task-preview")
    orchestration_plan = dict(task_operation_preview.get("orchestration_plan_preview") or {})
    operation_gate = dict(task_operation_preview.get("operation_gate_preflight") or {})
    commit_gate = dict(task_operation_preview.get("commit_gate_preview") or {})
    context_diagnostics = dict((context_policy_preview or {}).get("diagnostics") or {})
    memory_ref = str(
        (memory_runtime_view or {}).get("view_id")
        or context_diagnostics.get("memory_runtime_view_ref")
        or ""
    )
    return AgentRuntimeChainPreview(
        chain_id=f"agent-runtime-chain:{task_id}:single-agent:preview",
        session_id=session_id,
        task_id=task_id,
        task_operation_preview_ref=task_id,
        memory_runtime_view_ref=memory_ref,
        context_policy_authority=str((context_policy_preview or {}).get("authority") or "context_policy_preview"),
        orchestration_plan_ref=str(orchestration_plan.get("plan_id") or ""),
        operation_gate_ref=str(operation_gate.get("preflight_id") or ""),
        commit_gate_ref=str(commit_gate.get("gate_id") or ""),
        status="blocked",
        reason=str(operation_gate.get("reason") or commit_gate.get("reason") or "runtime_directive_missing"),
        query_runtime_role="adapter_only",
        topology_mode=str(orchestration_plan.get("topology_mode") or "single_agent"),
        preview_only=True,
        runtime_executable=False,
        diagnostics={
            "task_system_connected": bool(task_contract),
            "soul_system_connected": bool(task_operation_preview.get("soul_runtime_view")),
            "memory_system_connected": bool(memory_ref),
            "context_policy_connected": bool(context_policy_preview),
            "orchestration_system_connected": bool(orchestration_plan),
            "operation_system_connected": bool(operation_gate),
            "commit_gate_connected": bool(commit_gate),
            "query_runtime_adapter_only": True,
            "legacy_query_execution_available": False,
            "runtime_directive_required": True,
            "operation_gate_passed": bool(operation_gate.get("operation_gate_passed") is True),
            "commit_allowed": bool(commit_gate.get("commit_allowed") is True),
        },
    )
