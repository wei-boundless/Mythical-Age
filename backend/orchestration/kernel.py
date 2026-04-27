from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .candidates import CandidateEnvelope, CandidateSet
from .contracts import TaskContract
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
    ) -> ControlKernelResult:
        candidate_items = _candidate_tuple(candidates)
        graph = ExecutionGraph(
            graph_id=f"graph:{task.task_id}",
            task_id=task.task_id,
            nodes=(),
            edges=(),
            refs={"state": "empty_until_directive_builder_exists"},
        )
        return ControlKernelResult(
            task=task,
            candidates=candidate_items,
            execution_graph=graph,
            directives=(),
            status="blocked",
            reason="wiring_cleared_pending_control_kernel",
            diagnostics={
                "candidate_count": len(candidate_items),
                "execution_node_count": 0,
                "fail_closed": True,
                "cleared_old_wiring": True,
            },
        )


def _candidate_tuple(
    candidates: CandidateSet | list[CandidateEnvelope] | tuple[CandidateEnvelope, ...] | None,
) -> tuple[CandidateEnvelope, ...]:
    if candidates is None:
        return ()
    if isinstance(candidates, CandidateSet):
        return tuple(candidates.candidates)
    return tuple(candidates)
