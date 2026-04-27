from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExecutionCandidate:
    diagnostics: dict[str, Any] = field(default_factory=dict)


class ExecutionCandidateGate:
    """Candidate seam before legacy QueryExecutionPlan enters the runtime executor."""

    def build_candidate(self, execution: Any) -> ExecutionCandidate:
        understanding = getattr(execution, "query_understanding", None)
        worker_plan = getattr(execution, "worker_plan", None)
        dispatch_plan = getattr(execution, "dispatch_plan", None)
        execution_id = (
            str(getattr(execution, "subtask_id", "") or "")
            or str(getattr(execution, "bundle_item_id", "") or "")
            or "main"
        )
        diagnostics = {
            "phase": "8M",
            "state": "execution_candidate_projected",
            "mode": "legacy_runtime_apply",
            "canonical_owner": "orchestration.execution_directive",
            "legacy_owner": "query.runtime._stream_planned_execution",
            "execution_id": execution_id,
            "execution_kind": str(getattr(execution, "execution_kind", "") or "agent"),
            "route": str(getattr(understanding, "route", "") or ""),
            "tool": str(getattr(understanding, "tool_name", "") or ""),
            "worker_route": str(getattr(worker_plan, "worker_route", "") or ""),
            "skill": str(getattr(understanding, "skill_name", "") or ""),
            "dispatch_state": str(getattr(dispatch_plan, "state", "") or ""),
            "apply_mode": "legacy_runtime_apply",
            "takeover_allowed": False,
            "delete_allowed": False,
            "safe_rule": "8M 只把 legacy execution 投影成候选；真实执行仍走现有 RuntimeToolBridge/worker/model 分支。",
        }
        return ExecutionCandidate(diagnostics=diagnostics)
