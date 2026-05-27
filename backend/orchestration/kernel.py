from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .candidates import CandidateEnvelope, CandidateSet
from .contracts import ControlKernelCandidateContext, TaskContract
from .execution_graph import ExecutionGraph


@dataclass(slots=True, frozen=True)
class ControlKernelResult:
    """Fail-closed output while the architecture is being rewired."""

    task: TaskContract
    candidates: tuple[CandidateEnvelope, ...] = ()
    execution_graph: ExecutionGraph | None = None
    directives: tuple[dict[str, Any], ...] = ()
    status: str = "blocked"
    reason: str = "wiring_cleared_pending_control_kernel"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "execution_graph": self.execution_graph.to_dict() if self.execution_graph is not None else None,
            "directives": [dict(item) for item in self.directives],
            "status": self.status,
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class ControlKernel:
    """New canonical control-plane entry point.

    This kernel intentionally does not reuse the old adapter/planner/runtime
    wiring. Until policies and directive builders are rebuilt, every request is
    collected as candidates and then blocked by default.
    """

    def collect(
        self,
        *,
        task: TaskContract,
        candidates: CandidateSet | list[CandidateEnvelope] | tuple[CandidateEnvelope, ...] | None = None,
        candidate_context: ControlKernelCandidateContext | None = None,
    ) -> ControlKernelResult:
        candidate_items = _candidate_tuple(candidates)
        graph_refs = _graph_refs(candidate_context)
        diagnostics = _diagnostics(candidate_items, candidate_context)
        reason = candidate_context.blocked_reason if candidate_context is not None else "wiring_cleared_pending_control_kernel"
        graph = ExecutionGraph(
            graph_id=f"graph:{task.task_id}",
            task_id=task.task_id,
            nodes=(),
            edges=(),
            refs=graph_refs,
        )
        return ControlKernelResult(
            task=task,
            candidates=candidate_items,
            execution_graph=graph,
            directives=(),
            status="blocked",
            reason=reason,
            diagnostics=diagnostics,
        )


def _candidate_tuple(
    candidates: CandidateSet | list[CandidateEnvelope] | tuple[CandidateEnvelope, ...] | None,
) -> tuple[CandidateEnvelope, ...]:
    if candidates is None:
        return ()
    if isinstance(candidates, CandidateSet):
        return tuple(candidates.candidates)
    return tuple(candidates)


def _graph_refs(candidate_context: ControlKernelCandidateContext | None) -> dict[str, Any]:
    if candidate_context is None:
        return {"state": "empty_until_directive_builder_exists"}
    payload = {
        "state": "candidate_only",
        "blocked_reason": candidate_context.blocked_reason,
        "resource_policy_ref": candidate_context.resource_policy_ref,
        "resource_policy_state": candidate_context.resource_policy_state,
        "resource_policy_adopted": candidate_context.resource_policy_adopted,
        "task_prompt_contract_ref": candidate_context.task_prompt_contract_ref,
        "prompt_manifest_ref": candidate_context.prompt_manifest_ref,
        "operation_requirement_ref": candidate_context.operation_requirement_ref,
        "runtime_directive_enabled": candidate_context.runtime_directive_enabled,
        "runtime_executable": candidate_context.runtime_executable,
        "operation_gate_required_before_execution": candidate_context.operation_gate_required_before_execution,
    }
    payload.update(candidate_context.refs)
    return payload


def _diagnostics(
    candidates: tuple[CandidateEnvelope, ...],
    candidate_context: ControlKernelCandidateContext | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_count": len(candidates),
        "execution_node_count": 0,
        "fail_closed": True,
        "cleared_old_wiring": True,
        "runtime_directive_enabled": False,
        "runtime_executable": False,
        "directive_count": 0,
    }
    if candidate_context is None:
        return payload
    payload.update(
        {
            "task_prompt_contract_ref": candidate_context.task_prompt_contract_ref,
            "resource_policy_ref": candidate_context.resource_policy_ref,
            "prompt_manifest_ref": candidate_context.prompt_manifest_ref,
            "operation_requirement_ref": candidate_context.operation_requirement_ref,
            "resource_policy_state": candidate_context.resource_policy_state,
            "resource_policy_adopted": candidate_context.resource_policy_adopted,
            "runtime_view_only": candidate_context.runtime_view_only,
            "blocked_reason": candidate_context.blocked_reason,
            "denied_operations": list(candidate_context.denied_operations),
            "requires_approval_operations": list(candidate_context.requires_approval_operations),
            "operation_gate_required_before_execution": candidate_context.operation_gate_required_before_execution,
        }
    )
    payload.update(candidate_context.diagnostics)
    payload["fail_closed"] = True
    payload["runtime_directive_enabled"] = False
    payload["runtime_executable"] = False
    payload["directive_count"] = 0
    payload["execution_node_count"] = 0
    return payload


