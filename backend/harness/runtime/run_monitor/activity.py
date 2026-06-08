from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict


ActivityState = Literal["running", "waiting", "paused", "stopped", "failed", "completed", "stale", "idle"]
ActivityTone = Literal["active", "neutral", "attention", "done"]
SignalState = Literal["active", "waiting", "attention", "completed", "failed", "stale"]


class RuntimeActivity(TypedDict):
    activity_state: ActivityState
    activity_label: str
    is_running: bool
    is_waiting: bool
    is_resumable: bool
    is_interruptible: bool
    control_reason: str
    tone: ActivityTone


@dataclass(frozen=True, slots=True)
class RuntimeActivityControlContext:
    resumable: bool | None = None
    interruptible: bool | None = None
    reason: str = ""


STOPPED_STATUSES = {"cancelled", "canceled", "stopped", "user_aborted"}
STOPPED_REASONS = {"cancelled", "canceled", "stopped", "user_aborted", "user_cancelled", "user_canceled", "user_stopped"}
FAILED_STATUSES = {"failed", "error"}
COMPLETED_STATUSES = {"completed", "success", "done", "succeeded"}
WAITING_STATUSES = {"waiting_executor", "waiting_approval", "waiting_user", "blocked"}
RUNNING_STATUSES = {"created", "queued", "in_progress", "running"}


def with_runtime_activity(item: dict[str, Any], *, control_context: RuntimeActivityControlContext | None = None) -> dict[str, Any]:
    activity = project_runtime_activity(item, control_context=control_context)
    existing_capability = dict(item.get("control_capability") or {})
    control_capability = {
        **existing_capability,
        "is_resumable": activity["is_resumable"],
        "is_interruptible": activity["is_interruptible"],
        "control_reason": activity["control_reason"],
    }
    return {
        **item,
        **activity,
        "activity": activity,
        "control_capability": control_capability,
    }


def project_runtime_activity(item: dict[str, Any], *, control_context: RuntimeActivityControlContext | None = None) -> RuntimeActivity:
    state = activity_state(item)
    is_running = state == "running"
    is_waiting = state in {"waiting", "paused"}
    is_resumable, resumable_reason = _is_resumable(item, state=state, control_context=control_context)
    is_interruptible, interruptible_reason = _is_interruptible(item, state=state, control_context=control_context)
    control_reason = _first_text(
        (control_context.reason if control_context else ""),
        resumable_reason if is_resumable else "",
        interruptible_reason if is_interruptible else "",
        _default_control_reason(state, is_resumable=is_resumable, is_interruptible=is_interruptible),
    )
    return {
        "activity_state": state,
        "activity_label": _activity_label(item, state=state),
        "is_running": is_running,
        "is_waiting": is_waiting,
        "is_resumable": is_resumable,
        "is_interruptible": is_interruptible,
        "control_reason": control_reason,
        "tone": _tone(state),
    }


def activity_state(item: dict[str, Any]) -> ActivityState:
    explicit = _text(item.get("activity_state") or dict(item.get("activity") or {}).get("activity_state"))
    status = _text(item.get("status"))
    lifecycle = _text(item.get("lifecycle"))
    bucket = _text(item.get("bucket"))
    terminal_reason = _text(item.get("terminal_reason"))
    control_state = _text(item.get("control_state") or dict(item.get("runtime_control") or {}).get("state"))

    if _is_user_stopped(status=status, terminal_reason=terminal_reason, control_state=control_state):
        return "stopped"
    if status in FAILED_STATUSES or status == "aborted" or lifecycle == "failed" or bucket == "failed":
        return "failed"
    if status in COMPLETED_STATUSES or lifecycle == "completed" or bucket == "completed":
        return "completed"
    if control_state == "paused" or status == "paused" or lifecycle == "paused":
        return "paused"
    if lifecycle == "stale" or bool(item.get("stale") is True):
        return "stale"
    if (
        status in WAITING_STATUSES
        or lifecycle in {"waiting", "waiting_executor", "waiting_approval", "waiting_user", "action_required"}
        or bucket == "waiting"
        or bool(item.get("action_required") is True)
    ):
        return "waiting"
    if explicit in {"running", "waiting", "paused", "stopped", "failed", "completed", "stale", "idle"}:
        return explicit  # type: ignore[return-value]
    if status in RUNNING_STATUSES or lifecycle in {"running", "active"} or bucket == "running" or bool(item.get("is_live") is True):
        return "running"
    return "idle"


def signal_state_from_activity(activity: dict[str, Any] | str) -> SignalState:
    state = _text(activity if isinstance(activity, str) else activity.get("activity_state"))
    if state == "running":
        return "active"
    if state in {"waiting", "paused"}:
        return "waiting"
    if state == "failed":
        return "failed"
    if state in {"completed", "stopped"}:
        return "completed"
    if state == "stale":
        return "stale"
    return "attention"


def activity_sort_rank(item: dict[str, Any]) -> int:
    state = _text(item.get("activity_state"))
    return {
        "running": 7,
        "paused": 6,
        "waiting": 5,
        "stale": 4,
        "failed": 3,
        "stopped": 2,
        "completed": 1,
    }.get(state, 0)


def activity_is_monitor_visible(item: dict[str, Any]) -> bool:
    state = _text(item.get("activity_state"))
    return state in {"running", "waiting", "paused", "stale"} or bool(item.get("action_required") is True)


def _is_user_stopped(*, status: str, terminal_reason: str, control_state: str) -> bool:
    if terminal_reason in STOPPED_REASONS:
        return True
    if status in STOPPED_STATUSES:
        return True
    if status == "aborted" and terminal_reason in STOPPED_REASONS:
        return True
    return control_state in {"stopped", "cancelled", "canceled", "user_aborted"}


def _is_resumable(
    item: dict[str, Any],
    *,
    state: ActivityState,
    control_context: RuntimeActivityControlContext | None,
) -> tuple[bool, str]:
    if control_context and control_context.resumable is not None:
        return bool(control_context.resumable), control_context.reason or "control_context"
    capability = dict(item.get("control_capability") or {})
    if "can_resume_task" in capability:
        return bool(capability.get("can_resume_task")), str(capability.get("control_reason") or "control_capability")
    if "is_resumable" in capability:
        return bool(capability.get("is_resumable")), str(capability.get("control_reason") or "control_capability")
    control_state = _text(item.get("control_state") or dict(item.get("runtime_control") or {}).get("state"))
    if control_state == "paused" or _text(item.get("status")) == "paused":
        return True, "paused_task"
    return False, "not_resumable"


def _is_interruptible(
    item: dict[str, Any],
    *,
    state: ActivityState,
    control_context: RuntimeActivityControlContext | None,
) -> tuple[bool, str]:
    if control_context and control_context.interruptible is not None:
        return bool(control_context.interruptible), control_context.reason or "control_context"
    capability = dict(item.get("control_capability") or {})
    if "can_pause_task" in capability:
        return bool(capability.get("can_pause_task")), str(capability.get("control_reason") or "control_capability")
    if "is_interruptible" in capability:
        return bool(capability.get("is_interruptible")), str(capability.get("control_reason") or "control_capability")
    if state != "running":
        return False, "not_running"
    task_run_id = _text(item.get("task_run_id"))
    if not task_run_id:
        return False, "missing_task_run_id"
    if task_run_id.startswith("turnrun:") or _text(item.get("execution_runtime_kind")) == "single_agent_turn":
        return False, "turn_run_stream"
    return True, "running_task"


def _activity_label(item: dict[str, Any], *, state: ActivityState) -> str:
    explicit = _plain_text(item.get("activity_label") or dict(item.get("activity") or {}).get("activity_label"))
    if explicit:
        return explicit
    status = _text(item.get("status"))
    lifecycle = _text(item.get("lifecycle"))
    if state == "running":
        return "运行中"
    if state == "paused":
        return "已暂停"
    if state == "waiting":
        if status == "waiting_approval" or lifecycle == "waiting_approval":
            return "等待确认"
        if status == "blocked" or lifecycle in {"blocked", "action_required"}:
            return "等待处理"
        return "等待继续"
    if state == "stopped":
        return "已停止"
    if state == "failed":
        return "失败"
    if state == "completed":
        return "已完成"
    if state == "stale":
        return "等待检查"
    return "待命"


def _tone(state: ActivityState) -> ActivityTone:
    if state == "running":
        return "active"
    if state == "failed":
        return "attention"
    if state == "completed":
        return "done"
    return "neutral"


def _default_control_reason(state: ActivityState, *, is_resumable: bool, is_interruptible: bool) -> str:
    if is_resumable:
        return "resumable"
    if is_interruptible:
        return "interruptible"
    if state in {"completed", "failed", "stopped"}:
        return "terminal"
    if state in {"waiting", "paused"}:
        return "waiting_not_resumable"
    if state == "stale":
        return "stale_not_resumable"
    return "not_available"


def _first_text(*values: str) -> str:
    for value in values:
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _plain_text(value: Any) -> str:
    return str(value or "").strip()
