from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.loop.task_run_recovery_state import recovery_state_for_task_run
from harness.loop.work_rollout import work_rollout_ref, work_rollout_summary
from harness.runtime.control_events import runtime_signal_from_event_payload
from harness.runtime.runtime_gateway import (
    CONTROL_SIGNAL_PUBLISHED_EVENT,
)
from harness.task_run_state_view import task_run_state_view
from harness.task_run_status import is_stopped_or_terminal_task_run

from .record import (
    ContinuationRecord,
    InterruptedTurnContinuationRecord,
    continuation_id_for_task_run,
    continuation_id_for_turn_run,
    now_timestamp,
)


_RECOVERABLE_TURN_CONTROL_SIGNAL_KINDS = frozenset(
    {
        "tool_budget_exhausted",
        "consecutive_tool_failures",
        "model_protocol_violation",
        "final_output_not_committable",
        "agent_contract_feedback_required",
    }
)
_RECOVERABLE_TURN_TERMINAL_REASONS = frozenset(
    {
        "single_turn_tool_iteration_limit",
        "single_turn_consecutive_tool_failures",
        "single_agent_turn_protocol_error",
        "final_output_not_committable",
        "session_output_commit_not_committed",
        "agent_contract_feedback_required",
    }
)


@dataclass(frozen=True, slots=True)
class ContinuationSelection:
    record: ContinuationRecord | None = None
    interrupted_turn: InterruptedTurnContinuationRecord | None = None
    reason: str = ""
    authority: str = "harness.continuation.selector"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict() if self.record is not None else {},
            "interrupted_turn": self.interrupted_turn.to_dict() if self.interrupted_turn is not None else {},
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
    candidates = sorted(
        task_runs,
        key=lambda item: (float(getattr(item, "updated_at", 0.0) or 0.0), float(getattr(item, "created_at", 0.0) or 0.0)),
        reverse=True,
    )
    selected_record: ContinuationRecord | None = None
    for task_run in candidates:
        view = task_run_state_view(task_run)
        if bool(view.get("graph_controlled")):
            continue
        record = _record_from_task_run(runtime_host, task_run=task_run, view=view)
        if record is not None:
            selected_record = record
            break
    selected_interrupted_turn = _latest_interrupted_turn_record(runtime_host, session_id=normalized_session_id)
    if selected_record is not None or selected_interrupted_turn is not None:
        return ContinuationSelection(
            record=selected_record,
            interrupted_turn=selected_interrupted_turn,
            reason=_selection_reason(task_record=selected_record, interrupted_turn=selected_interrupted_turn),
        )
    if not task_runs:
        return ContinuationSelection(reason="session_task_run_missing_or_interrupted_turn_missing")
    return ContinuationSelection(reason="no_supported_session_task_or_interrupted_turn")


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


def _latest_interrupted_turn_record(runtime_host: Any, *, session_id: str) -> InterruptedTurnContinuationRecord | None:
    turn_runs = [
        item
        for item in list(getattr(runtime_host.state_index, "list_session_turn_runs", lambda _session_id: [])(session_id) or [])
        if str(getattr(item, "execution_runtime_kind", "") or "") == "single_agent_turn"
    ]
    if not turn_runs:
        return None
    candidates = sorted(
        turn_runs,
        key=lambda item: (float(getattr(item, "updated_at", 0.0) or 0.0), float(getattr(item, "created_at", 0.0) or 0.0)),
        reverse=True,
    )
    return _record_from_interrupted_turn_run(runtime_host, candidates[0])


def _record_from_interrupted_turn_run(runtime_host: Any, turn_run: Any) -> InterruptedTurnContinuationRecord | None:
    turn_run_id = str(getattr(turn_run, "turn_run_id", "") or "").strip()
    session_id = str(getattr(turn_run, "session_id", "") or "").strip()
    turn_id = str(getattr(turn_run, "turn_id", "") or "").strip()
    if not turn_run_id or not session_id or not turn_id:
        return None
    diagnostics = dict(getattr(turn_run, "diagnostics", {}) or {})
    terminal_reason = str(
        getattr(turn_run, "terminal_reason", "")
        or diagnostics.get("terminal_reason")
        or diagnostics.get("terminal_reason_detail")
        or ""
    ).strip()
    status = str(getattr(turn_run, "status", "") or diagnostics.get("terminal_status") or "").strip()
    gateway_signal = _latest_turn_runtime_control_signal_from_gateway(
        runtime_host,
        turn_run_id=turn_run_id,
    )
    interruption_kind = _interrupted_turn_kind(
        terminal_reason=terminal_reason,
        status=status,
        diagnostics=diagnostics,
        runtime_control_signal=gateway_signal,
    )
    if not interruption_kind:
        return None
    latest_signal = dict(gateway_signal or {})
    feedback = dict(diagnostics.get("latest_agent_contract_feedback") or {})
    latest_progress = _first_text(
        diagnostics.get("latest_public_progress_note"),
        diagnostics.get("latest_step_summary"),
        feedback.get("agent_feedback"),
        dict(feedback.get("structured_signal") or {}).get("message"),
        latest_signal.get("message"),
        terminal_reason,
        status,
    )
    latest_step = _first_text(
        diagnostics.get("latest_step"),
        diagnostics.get("latest_tool_batch_event"),
        diagnostics.get("terminal_event_type"),
    )
    visible_stream = dict(diagnostics.get("assistant_visible_stream_continuity") or {})
    visible_prefix = str(visible_stream.get("content") or "").strip()
    event_cursor = _int_value(getattr(turn_run, "latest_event_offset", -1), -1)
    control_version = _int_value(diagnostics.get("continuation_control_version"), 0)
    now = now_timestamp()
    return InterruptedTurnContinuationRecord(
        continuation_id=continuation_id_for_turn_run(turn_run_id, event_cursor=event_cursor, control_version=control_version),
        session_id=session_id,
        turn_run_id=turn_run_id,
        turn_id=turn_id,
        previous_stream_run_id=str(diagnostics.get("stream_run_id") or ""),
        interruption_kind=interruption_kind,
        terminal_status=status,
        terminal_reason=terminal_reason,
        latest_progress=latest_progress,
        latest_step=latest_step,
        next_recommended_step=_interrupted_turn_next_step(interruption_kind),
        visible_assistant_prefix=visible_prefix,
        visible_assistant_prefix_sha256=str(visible_stream.get("content_sha256") or ""),
        visible_assistant_prefix_truncated=bool(visible_stream.get("truncated_from_start") is True),
        visible_assistant_prefix_utf8_bytes=_int_value(visible_stream.get("content_utf8_bytes"), 0),
        event_log_ref=turn_run_id,
        event_cursor=event_cursor,
        model_visible_summary=_interrupted_turn_model_visible_summary(
            latest_progress=latest_progress,
            latest_step=latest_step,
            interruption_kind=interruption_kind,
            terminal_reason=terminal_reason,
            status=status,
            visible_assistant_prefix_present=bool(visible_prefix),
        ),
        created_at=now,
        updated_at=float(getattr(turn_run, "updated_at", 0.0) or now),
        diagnostics={
            "terminal_reason": terminal_reason,
            "terminal_status": status,
            "latest_runtime_control_signal_kind": str(latest_signal.get("signal_kind") or ""),
            "latest_step_status": str(diagnostics.get("latest_step_status") or ""),
            "has_agent_contract_feedback": bool(feedback),
        },
    )


def _interrupted_turn_kind(
    *,
    terminal_reason: str,
    status: str,
    diagnostics: dict[str, Any],
    runtime_control_signal: dict[str, Any],
) -> str:
    reason = str(terminal_reason or "").strip()
    signal_kind = str(dict(runtime_control_signal or {}).get("signal_kind") or "").strip()
    if reason in _RECOVERABLE_TURN_TERMINAL_REASONS:
        if reason == "single_turn_tool_iteration_limit":
            return "tool_budget_exhausted"
        if reason == "single_turn_consecutive_tool_failures":
            return "consecutive_tool_failures"
        if reason == "agent_contract_feedback_required":
            return "agent_contract_feedback_required"
        return "interrupted_turn_runtime_boundary"
    if signal_kind in _RECOVERABLE_TURN_CONTROL_SIGNAL_KINDS:
        return signal_kind
    if dict(diagnostics.get("latest_agent_contract_feedback") or {}):
        return "agent_contract_feedback_required"
    if str(status or "").strip() in {"failed", "aborted"} and reason in _RECOVERABLE_TURN_TERMINAL_REASONS:
        return "interrupted_turn_runtime_boundary"
    return ""


def _latest_turn_runtime_control_signal_from_gateway(
    runtime_host: Any,
    *,
    turn_run_id: str,
) -> dict[str, Any]:
    normalized_turn_run_id = str(turn_run_id or "").strip()
    if not normalized_turn_run_id:
        return {}
    event_log = getattr(runtime_host, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return {}
    try:
        events = list(list_events(normalized_turn_run_id) or [])
    except Exception:
        return {}
    for event in reversed(events):
        if getattr(event, "event_type", "") != CONTROL_SIGNAL_PUBLISHED_EVENT:
            continue
        signal = runtime_signal_from_event_payload(dict(getattr(event, "payload", {}) or {}))
        if signal is None:
            continue
        if signal.signal_type != "control.signal.requested":
            continue
        if signal.scope.turn_run_id and signal.scope.turn_run_id != normalized_turn_run_id:
            continue
        return dict(signal.payload or {})
    return {}


def _interrupted_turn_next_step(interruption_kind: str) -> str:
    if interruption_kind == "tool_budget_exhausted":
        return "继续上一轮普通对话工作；优先复用当前 packet 中未过期的 exact read evidence，并接续已公开但未提交的 assistant 前缀。"
    if interruption_kind == "agent_contract_feedback_required":
        return "继续上一轮普通对话工作；根据合同反馈产出合法 action，不要让系统代写用户正文，不要重复已公开前缀。"
    return "继续上一轮普通对话工作；把该记录当作同一 session 的连续上下文，必要时再读取缺失或过期证据。"


def _interrupted_turn_model_visible_summary(
    *,
    latest_progress: str,
    latest_step: str,
    interruption_kind: str,
    terminal_reason: str,
    status: str,
    visible_assistant_prefix_present: bool = False,
) -> str:
    parts = ["上下文：上一轮普通对话 turn 在运行边界中断，属于同一会话的可延续工作上下文。"]
    if visible_assistant_prefix_present:
        parts.append("已公开输出：上一轮存在已显示给用户但尚未最终提交的 assistant 正文前缀，本轮需要从该前缀之后继续，不要重复。")
    if latest_progress:
        parts.append(f"已确认进度：{latest_progress}")
    if latest_step:
        parts.append(f"最近步骤：{latest_step}")
    if interruption_kind:
        parts.append(f"中断类型：{interruption_kind}")
    if terminal_reason:
        parts.append(f"结束原因：{terminal_reason}")
    if status:
        parts.append(f"当前状态：{status}")
    parts.append("证据规则：优先复用本次 packet 可见的 exact read evidence；只有证据缺失、stale 或文件已变更时才重新读取。")
    return "\n".join(parts)


def _selection_reason(
    *,
    task_record: ContinuationRecord | None,
    interrupted_turn: InterruptedTurnContinuationRecord | None,
) -> str:
    if task_record is not None and interrupted_turn is not None:
        return "latest_session_task_run_and_interrupted_turn_selected"
    if task_record is not None:
        return "latest_session_task_run_selected"
    return "latest_interrupted_single_agent_turn_selected"


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
