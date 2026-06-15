from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.loop.task_run_recovery_state import recovery_state_for_task_run
from harness.loop.work_rollout import work_rollout_ref, work_rollout_summary
from harness.task_run_state_view import task_run_state_view
from harness.task_run_status import is_stopped_or_terminal_task_run

from .record import ContinuationRecord, continuation_id_for_task_run, now_timestamp


@dataclass(frozen=True, slots=True)
class ContinuationSelection:
    record: ContinuationRecord | None = None
    reason: str = ""
    authority: str = "harness.continuation.selector"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict() if self.record is not None else {},
            "reason": self.reason,
            "authority": self.authority,
        }


def select_session_continuation(
    runtime_host: Any,
    *,
    session_id: str,
    active_work_present: bool = False,
) -> ContinuationSelection:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return ContinuationSelection(reason="session_id_missing")
    if active_work_present:
        return ContinuationSelection(reason="live_active_work_present")
    task_runs = [
        item
        for item in list(getattr(runtime_host.state_index, "list_session_task_runs", lambda _session_id: [])(normalized_session_id) or [])
        if str(getattr(item, "execution_runtime_kind", "") or "") == "single_agent_task"
    ]
    if not task_runs:
        return ContinuationSelection(reason="session_task_run_missing")
    candidates = sorted(
        task_runs,
        key=lambda item: (float(getattr(item, "updated_at", 0.0) or 0.0), float(getattr(item, "created_at", 0.0) or 0.0)),
        reverse=True,
    )
    for task_run in candidates:
        view = task_run_state_view(task_run)
        if bool(view.get("graph_controlled")):
            continue
        record = _record_from_task_run(runtime_host, task_run=task_run, view=view)
        if record is not None:
            return ContinuationSelection(record=record, reason="latest_session_task_run_selected")
    return ContinuationSelection(reason="no_supported_session_task_run")


def _record_from_task_run(runtime_host: Any, *, task_run: Any, view: dict[str, Any]) -> ContinuationRecord | None:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not task_run_id or not session_id:
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    recovery_state = recovery_state_for_task_run(task_run)
    work_state = str(view.get("task_work_state") or "")
    status = str(getattr(task_run, "status", "") or view.get("task_status") or "")
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or diagnostics.get("terminal_reason") or "")
    terminal = bool(is_stopped_or_terminal_task_run(task_run))
    state = "none"
    resume_strategy = "unavailable"
    resume_allowed = False
    requires_user_confirmation = False
    if not terminal and bool(recovery_state.executable):
        state = "recoverable"
        resume_strategy = "same_run_resume"
        resume_allowed = True
    elif not terminal and work_state == "paused":
        state = "paused"
        resume_strategy = "same_run_resume" if bool(recovery_state.same_run_resumable) else "ask_user_confirm"
        resume_allowed = bool(recovery_state.executable)
        requires_user_confirmation = not resume_allowed
    elif not terminal and work_state == "waiting_approval":
        state = "waiting_approval"
        resume_strategy = "require_approval"
        resume_allowed = bool(recovery_state.executable)
        requires_user_confirmation = True
    elif not terminal and work_state in {"ready_to_continue", "waiting_user"} and bool(view.get("recoverable")):
        state = "recoverable"
        resume_strategy = "same_run_resume" if bool(recovery_state.same_run_resumable) else "ask_user_confirm"
        resume_allowed = bool(recovery_state.executable)
        requires_user_confirmation = not resume_allowed
    elif terminal or work_state in {"completed", "failed", "stopped"}:
        state = "terminal_read_only"
    else:
        return None

    rollout = work_rollout_summary(runtime_host, task_run)
    contract = _load_contract(runtime_host, str(getattr(task_run, "task_contract_ref", "") or ""))
    latest_progress = _first_text(
        diagnostics.get("latest_public_progress_note"),
        rollout.get("latest_progress"),
        diagnostics.get("latest_step_summary"),
        diagnostics.get("summary"),
        view.get("control_reason"),
        terminal_reason,
        status,
    )
    latest_step = _first_text(diagnostics.get("latest_step"), rollout.get("latest_step_title"))
    goal = _first_text(
        diagnostics.get("goal"),
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
        rollout.get("logical_work_id"),
        getattr(task_run, "task_id", ""),
    )
    event_cursor = _int_value(getattr(task_run, "latest_event_offset", -1), -1)
    control_version = _int_value(diagnostics.get("continuation_control_version"), 0)
    artifact_refs = _artifact_refs(rollout=rollout, diagnostics=diagnostics)
    model_visible_summary = _model_visible_summary(
        goal=goal,
        latest_progress=latest_progress,
        latest_step=latest_step,
        recovery_cause=str(view.get("recovery_cause") or ""),
        terminal_reason=terminal_reason,
        status=status,
    )
    now = now_timestamp()
    return ContinuationRecord(
        continuation_id=continuation_id_for_task_run(task_run_id, event_cursor=event_cursor, control_version=control_version),
        session_id=session_id,
        task_run_id=task_run_id,
        previous_turn_id=str(diagnostics.get("turn_id") or diagnostics.get("latest_interaction_turn_id") or ""),
        previous_active_turn_id=str(diagnostics.get("active_turn_id") or diagnostics.get("turn_id") or ""),
        previous_stream_run_id=str(diagnostics.get("stream_run_id") or ""),
        state=state,  # type: ignore[arg-type]
        resume_allowed=resume_allowed,
        resume_strategy=resume_strategy,
        recovery_cause=str(view.get("recovery_cause") or ""),
        task_status=status,
        executor_status=str(view.get("executor_status") or diagnostics.get("executor_status") or ""),
        control_state=str(view.get("control_state") or ""),
        user_visible_goal=goal,
        latest_progress=latest_progress,
        last_completed_step=latest_step,
        next_recommended_step=_next_recommended_step(state=state, resume_allowed=resume_allowed),
        task_contract_ref=str(getattr(task_run, "task_contract_ref", "") or ""),
        work_rollout_ref=work_rollout_ref(task_run_id),
        event_log_ref=task_run_id,
        event_cursor=event_cursor,
        artifact_refs=tuple(artifact_refs),
        model_visible_summary=model_visible_summary,
        requires_user_confirmation=requires_user_confirmation,
        control_version=control_version,
        created_at=now,
        updated_at=float(getattr(task_run, "updated_at", 0.0) or now),
        diagnostics={
            "task_work_state": work_state,
            "terminal_reason": terminal_reason,
            "task_run_state_view": dict(view),
            "recovery_state": {
                "recoverable": bool(recovery_state.recoverable),
                "same_run_resumable": bool(recovery_state.same_run_resumable),
                "executable": bool(recovery_state.executable),
                "reason": str(recovery_state.reason or ""),
                "authority": recovery_state.authority,
            },
        },
    )


def _load_contract(runtime_host: Any, ref: str) -> dict[str, Any]:
    if not ref:
        return {}
    try:
        return dict(runtime_host.runtime_objects.get_object(ref) or {})
    except Exception:
        return {}


def _artifact_refs(*, rollout: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(rollout.get("artifact_refs") or diagnostics.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
        elif str(item or "").strip():
            refs.append({"artifact_ref": str(item).strip()})
    return refs[:8]


def _next_recommended_step(*, state: str, resume_allowed: bool) -> str:
    if state == "terminal_read_only":
        return "只读说明最近任务结果；不要续跑该任务。"
    if resume_allowed:
        return "使用已校验的 continuation handle 恢复原 task_run，并在下一次模型调用中核对文件状态与未完成验收项。"
    return "先向用户说明当前任务需要确认或授权，不能自动续跑。"


def _model_visible_summary(
    *,
    goal: str,
    latest_progress: str,
    latest_step: str,
    recovery_cause: str,
    terminal_reason: str,
    status: str,
) -> str:
    parts = []
    if goal:
        parts.append(f"任务目标：{goal}")
    if latest_progress:
        parts.append(f"已确认进度：{latest_progress}")
    if latest_step:
        parts.append(f"最近步骤：{latest_step}")
    if recovery_cause:
        parts.append(f"中断原因：{recovery_cause}")
    if terminal_reason:
        parts.append(f"结束原因：{terminal_reason}")
    if status:
        parts.append(f"当前状态：{status}")
    return "\n".join(parts)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
