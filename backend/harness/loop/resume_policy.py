from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .active_work import ActiveWorkContext


ResumePlanDecision = Literal[
    "same_run_resume",
    "checkout_fork",
    "completed_iteration",
    "already_running",
    "wait_for_user",
    "refuse",
]


@dataclass(frozen=True, slots=True)
class ResumePlan:
    resume_plan_id: str
    task_run_id: str
    logical_work_id: str
    decision: ResumePlanDecision
    reason: str
    source_checkpoint_ref: str = ""
    source_event_offset: int = -1
    new_task_run_id: str = ""
    rollout_ref: str = ""
    interrupted_context_ref: str = ""
    created_at: float = 0.0
    authority: str = "runtime.resume_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_resume_plan(
    runtime_host: Any,
    *,
    context: ActiveWorkContext,
    user_message: str = "",
) -> ResumePlan:
    task_run = runtime_host.state_index.get_task_run(context.task_run_id)
    checkpoint_ref = str(getattr(task_run, "latest_checkpoint_ref", "") or "") if task_run is not None else ""
    event_offset = int(getattr(task_run, "latest_event_offset", -1) or -1) if task_run is not None else -1
    decision: ResumePlanDecision
    reason: str
    if task_run is None:
        decision = "refuse"
        reason = "task_run_not_found"
    elif context.running:
        decision = "already_running"
        reason = "work_already_running"
    elif context.same_run_allowed or context.resumable:
        decision = "same_run_resume"
        reason = "non_terminal_resume_available"
    elif context.checkout_allowed or context.continuation_kind == "interrupted_checkoutable":
        decision = "checkout_fork"
        reason = "terminal_interrupted_requires_checkout"
    elif context.status in {"waiting_approval", "blocked"}:
        decision = "wait_for_user"
        reason = "work_waiting_for_user_or_blocked"
    elif context.status in {"completed", "success"} or context.continuation_kind == "completed_iteration":
        decision = "completed_iteration"
        reason = "completed_work_requires_new_iteration"
    else:
        decision = "refuse"
        reason = f"not_resumable:{context.status}"
    plan = ResumePlan(
        resume_plan_id=f"resumeplan:{context.task_run_id}:{uuid.uuid4().hex[:8]}",
        task_run_id=context.task_run_id,
        logical_work_id=context.active_work_id,
        decision=decision,
        reason=reason,
        source_checkpoint_ref=checkpoint_ref,
        source_event_offset=event_offset,
        created_at=time.time(),
    )
    _record_resume_plan(runtime_host, plan, user_message=user_message)
    return plan


def _record_resume_plan(runtime_host: Any, plan: ResumePlan, *, user_message: str) -> None:
    try:
        ref = runtime_host.runtime_objects.put_object("resume_plan", plan.resume_plan_id, plan.to_dict())
    except Exception:
        ref = ""
    try:
        runtime_host.event_log.append(
            plan.task_run_id,
            "resume_plan_created",
            payload={"resume_plan": plan.to_dict(), "user_message": str(user_message or "")},
            refs={"task_run_ref": plan.task_run_id, "resume_plan_ref": ref},
        )
    except Exception:
        return
