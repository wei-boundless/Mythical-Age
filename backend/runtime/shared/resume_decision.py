from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeResumeDecision:
    decision_id: str
    task_run_id: str
    decision: str
    reason: str
    resume_from_checkpoint_ref: str = ""
    current_obligation: dict[str, Any] = field(default_factory=dict)
    checkpoint_summary: dict[str, Any] = field(default_factory=dict)
    human_gate_summary: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.runtime_resume_decision"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def decide_runtime_resume(
    *,
    task_run_id: str,
    checkpoint: Any | None,
    current_obligation: dict[str, Any] | None = None,
    user_goal: str = "",
    human_gate_state: dict[str, Any] | None = None,
) -> RuntimeResumeDecision:
    obligation = dict(current_obligation or {})
    human_gate = dict(human_gate_state or {})
    if checkpoint is None:
        return RuntimeResumeDecision(
            decision_id=f"runtime-resume:{task_run_id}",
            task_run_id=str(task_run_id or ""),
            decision="start_new",
            reason="missing_checkpoint",
            current_obligation=obligation,
            human_gate_summary=_human_gate_summary(human_gate),
        )

    checkpoint_ref = str(getattr(checkpoint, "checkpoint_id", "") or "")
    loop_state = getattr(checkpoint, "loop_state", None)
    terminal_reason = str(getattr(loop_state, "terminal_reason", "") or "")
    status = str(getattr(loop_state, "status", "") or "")
    gate_status = str(human_gate.get("status") or "").strip().lower()

    if _user_requests_restart(user_goal):
        decision = "restart"
        reason = "current_turn_requests_restart"
    elif gate_status in {"pending", "waiting"} and not _user_requests_force_continue(user_goal):
        decision = "wait_for_human"
        reason = "human_gate_pending"
    elif gate_status in {"rejected", "failed"}:
        decision = "rewind"
        reason = "human_gate_rejected"
    elif gate_status in {"approved", "cleared", "resolved"}:
        decision = "continue"
        reason = "human_gate_cleared"
    elif terminal_reason == "completed" or status == "completed":
        decision = "reuse_completed"
        reason = "checkpoint_completed"
    elif _obligation_requires_new_side_effect(obligation):
        decision = "continue"
        reason = "current_obligation_requires_unsatisfied_side_effects"
    elif status in {"blocked", "waiting_approval"}:
        decision = "wait_for_human"
        reason = "checkpoint_waiting_for_human"
    else:
        decision = "continue"
        reason = "checkpoint_available"
    return RuntimeResumeDecision(
        decision_id=f"runtime-resume:{task_run_id}",
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
        human_gate_summary=_human_gate_summary(human_gate),
    )


def decide_professional_run_resume(
    *,
    task_run_id: str,
    checkpoint: Any | None,
    current_obligation: dict[str, Any] | None = None,
    user_goal: str = "",
) -> ProfessionalRunResumeDecision:
    runtime_decision = decide_runtime_resume(
        task_run_id=task_run_id,
        checkpoint=checkpoint,
        current_obligation=current_obligation,
        user_goal=user_goal,
    )
    return ProfessionalRunResumeDecision(
        decision_id=f"professional-resume:{task_run_id}",
        task_run_id=str(task_run_id or ""),
        decision=runtime_decision.decision
        if runtime_decision.decision in {"start_new", "restart", "reuse_completed", "continue"}
        else "continue",
        reason=runtime_decision.reason,
        resume_from_checkpoint_ref=runtime_decision.resume_from_checkpoint_ref,
        current_obligation=dict(runtime_decision.current_obligation),
        checkpoint_summary=dict(runtime_decision.checkpoint_summary),
    )


def _user_requests_restart(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(marker in text for marker in ("重新开始", "从头", "restart", "start over"))


def _user_requests_force_continue(user_goal: str) -> bool:
    text = str(user_goal or "").lower()
    return any(marker in text for marker in ("继续", "continue", "go on", "resume"))


def _obligation_requires_new_side_effect(obligation: dict[str, Any]) -> bool:
    item = dict(obligation or {})
    return bool(list(item.get("required_writes") or []) or list(item.get("required_commands") or []))


def _human_gate_summary(human_gate: dict[str, Any]) -> dict[str, Any]:
    if not human_gate:
        return {}
    return {
        "status": str(human_gate.get("status") or ""),
        "stage_id": str(human_gate.get("stage_id") or human_gate.get("pending_stage_id") or ""),
        "decision": str(human_gate.get("decision") or human_gate.get("action") or ""),
    }
