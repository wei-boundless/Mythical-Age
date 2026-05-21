from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProfessionalRunResumeDecision:
    decision_id: str
    task_run_id: str
    decision: str
    reason: str
    resume_from_checkpoint_ref: str = ""
    current_obligation: dict[str, Any] = field(default_factory=dict)
    checkpoint_summary: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.professional_run_resume_decision"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_professional_run_resume(
    *,
    task_run_id: str,
    checkpoint: Any | None,
    current_obligation: dict[str, Any] | None = None,
    user_goal: str = "",
) -> ProfessionalRunResumeDecision:
    obligation = dict(current_obligation or {})
    if checkpoint is None:
        return ProfessionalRunResumeDecision(
            decision_id=f"professional-resume:{task_run_id}",
            task_run_id=str(task_run_id or ""),
            decision="start_new",
            reason="missing_checkpoint",
            current_obligation=obligation,
        )
    checkpoint_ref = str(getattr(checkpoint, "checkpoint_id", "") or "")
    loop_state = getattr(checkpoint, "loop_state", None)
    terminal_reason = str(getattr(loop_state, "terminal_reason", "") or "")
    status = str(getattr(loop_state, "status", "") or "")
    if _user_requests_restart(user_goal):
        decision = "restart"
        reason = "current_turn_requests_restart"
    elif terminal_reason == "completed" or status == "completed":
        decision = "reuse_completed"
        reason = "checkpoint_completed"
    elif _obligation_requires_new_side_effect(obligation):
        decision = "continue"
        reason = "current_obligation_requires_unsatisfied_side_effects"
    else:
        decision = "continue"
        reason = "checkpoint_available"
    return ProfessionalRunResumeDecision(
        decision_id=f"professional-resume:{task_run_id}",
        task_run_id=str(task_run_id or ""),
        decision=decision,
        reason=reason,
        resume_from_checkpoint_ref=checkpoint_ref,
        current_obligation=obligation,
        checkpoint_summary={
            "status": status,
            "terminal_reason": terminal_reason,
            "event_offset": int(getattr(checkpoint, "event_offset", 0) or 0),
        },
    )


def _user_requests_restart(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(marker in text for marker in ("重新开始", "从头", "restart", "start over"))


def _obligation_requires_new_side_effect(obligation: dict[str, Any]) -> bool:
    item = dict(obligation or {})
    return bool(list(item.get("required_writes") or []) or list(item.get("required_commands") or []))
