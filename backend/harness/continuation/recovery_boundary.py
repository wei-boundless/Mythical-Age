from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .record import ContinuationRecord, continuation_record_from_payload


RecoveryBoundaryAction = Literal[
    "no_recoverable_work",
    "recoverable_work_available",
    "resume_recoverable_work",
    "confirm_recoverable_work",
    "recoverable_work_unavailable",
    "recent_work_read_only",
    "block",
]


@dataclass(frozen=True, slots=True)
class RecoveryBoundaryInput:
    session_id: str
    turn_id: str
    recovery_input_policy: str = "auto"
    expected_task_run_id: str = ""
    expected_continuation_id: str = ""
    continuation_record: dict[str, Any] = field(default_factory=dict)
    current_work_boundary_receipt: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.continuation.recovery_boundary_input"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RecoveryBoundaryDecision:
    decision_id: str
    session_id: str
    turn_id: str
    action: RecoveryBoundaryAction
    continuation_id: str = ""
    expected_continuation_id: str = ""
    task_run_id: str = ""
    expected_task_run_id: str = ""
    resume_strategy: str = "unavailable"
    reason: str = ""
    evidence: str = ""
    public_response_obligation: str = "runtime_status"
    response: str = ""
    continuation_record: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.continuation.recovery_boundary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RecoveryBoundaryReceipt:
    receipt_id: str
    decision_id: str
    boundary_decision: str
    continuation_ref: str = ""
    task_run_ref: str = ""
    recovery_packet_ref: str = ""
    operation_availability: dict[str, bool] = field(default_factory=dict)
    resume_execution_route: str = ""
    expected_continuation_id: str = ""
    expected_task_run_id: str = ""
    state_reason: str = ""
    public_projection_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    enforced: bool = False
    authority: str = "harness.continuation.recovery_boundary_receipt"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_recovery_boundary_input(
    *,
    session_id: str,
    turn_id: str,
    recovery_input_policy: str = "auto",
    expected_task_run_id: str = "",
    expected_continuation_id: str = "",
    continuation_record: Any | None = None,
    current_work_boundary_receipt: dict[str, Any] | None = None,
) -> RecoveryBoundaryInput:
    return RecoveryBoundaryInput(
        session_id=str(session_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
        recovery_input_policy=str(recovery_input_policy or "auto").strip().lower() or "auto",
        expected_task_run_id=str(expected_task_run_id or "").strip(),
        expected_continuation_id=str(expected_continuation_id or "").strip(),
        continuation_record=_payload_from_object(continuation_record),
        current_work_boundary_receipt=dict(current_work_boundary_receipt or {}),
    )


def decide_recovery_boundary(boundary_input: RecoveryBoundaryInput) -> RecoveryBoundaryDecision:
    record = continuation_record_from_payload(boundary_input.continuation_record)
    policy = str(boundary_input.recovery_input_policy or "auto").strip().lower() or "auto"
    current_receipt = dict(boundary_input.current_work_boundary_receipt or {})
    current_ops = dict(current_receipt.get("operation_availability") or {})
    if current_ops.get("active_work_control") is True:
        return _decision(boundary_input, "no_recoverable_work", reason="live_active_work_has_priority")
    if record is None:
        return _decision(boundary_input, "no_recoverable_work", reason="continuation_record_missing")
    if record.state == "terminal_read_only":
        return _decision(
            boundary_input,
            "recent_work_read_only",
            record=record,
            reason="latest_task_terminal_read_only",
            response=_status_response(record),
        )
    if policy != "resume":
        return _decision(
            boundary_input,
            "recoverable_work_available",
            record=record,
            reason="recoverable_work_requires_explicit_resume_policy",
            response=_status_response(record),
        )
    if not boundary_input.expected_task_run_id or not boundary_input.expected_continuation_id:
        return _decision(
            boundary_input,
            "confirm_recoverable_work",
            record=record,
            reason="expected_recovery_handle_missing",
            response="检测到可恢复任务，但本次请求缺少 continuation_id 或 task_run_id，未执行续跑。",
        )
    if boundary_input.expected_task_run_id != record.task_run_id:
        return _decision(
            boundary_input,
            "recoverable_work_unavailable",
            record=record,
            reason="expected_task_run_mismatch",
            response="可恢复任务状态已经变化，本次续跑请求没有执行。",
        )
    if boundary_input.expected_continuation_id != record.continuation_id:
        return _decision(
            boundary_input,
            "recoverable_work_unavailable",
            record=record,
            reason="expected_continuation_mismatch",
            response="可恢复任务状态已经刷新，本次续跑请求没有执行。",
        )
    if record.resume_allowed is not True:
        return _decision(
            boundary_input,
            "confirm_recoverable_work",
            record=record,
            reason="continuation_not_directly_resumable",
            response=_status_response(record),
        )
    return _decision(
        boundary_input,
        "resume_recoverable_work",
        record=record,
        reason="recovery_boundary_ready",
        response="已接入恢复断点，我会从原任务进度继续调度。",
    )


def recovery_boundary_receipt_from_decision(decision: RecoveryBoundaryDecision) -> RecoveryBoundaryReceipt:
    can_resume = decision.action == "resume_recoverable_work"
    return RecoveryBoundaryReceipt(
        receipt_id=f"rbreceipt:{decision.turn_id}:{decision.decision_id.rsplit(':', 1)[-1]}",
        decision_id=decision.decision_id,
        boundary_decision=decision.action,
        continuation_ref=decision.continuation_id,
        task_run_ref=decision.task_run_id,
        operation_availability={
            "resume_recoverable_work": can_resume,
        },
        resume_execution_route="task_executor_controller.schedule" if can_resume else "",
        expected_continuation_id=decision.expected_continuation_id,
        expected_task_run_id=decision.expected_task_run_id,
        state_reason=decision.reason,
        public_projection_policy={
            "answer_channel": "conversation",
            "public_response_obligation": decision.public_response_obligation,
        },
        diagnostics={"decision": decision.to_dict()},
        enforced=can_resume,
    )


def _decision(
    boundary_input: RecoveryBoundaryInput,
    action: RecoveryBoundaryAction,
    *,
    record: ContinuationRecord | None = None,
    reason: str,
    response: str = "",
) -> RecoveryBoundaryDecision:
    now_key = int(time.time() * 1000)
    return RecoveryBoundaryDecision(
        decision_id=f"rbd:{boundary_input.turn_id}:{now_key}",
        session_id=boundary_input.session_id,
        turn_id=boundary_input.turn_id,
        action=action,
        continuation_id=str(record.continuation_id if record is not None else ""),
        expected_continuation_id=boundary_input.expected_continuation_id,
        task_run_id=str(record.task_run_id if record is not None else ""),
        expected_task_run_id=boundary_input.expected_task_run_id,
        resume_strategy=str(record.resume_strategy if record is not None else "unavailable"),
        reason=reason,
        evidence=str(record.model_visible_summary if record is not None else ""),
        public_response_obligation="direct_response_required" if action in {"confirm_recoverable_work", "recoverable_work_unavailable"} else "runtime_status",
        response=response,
        continuation_record=record.to_dict() if record is not None else {},
        diagnostics={
            "recovery_input_policy": boundary_input.recovery_input_policy,
            "current_work_boundary_receipt": dict(boundary_input.current_work_boundary_receipt or {}),
        },
    )


def _status_response(record: ContinuationRecord) -> str:
    if record.state == "terminal_read_only":
        return f"最近任务状态：{record.latest_progress or record.task_status or '已结束'}。这条记录只能只读参考，不能直接续跑。"
    return f"检测到可恢复任务：{record.user_visible_goal or record.task_run_id}。{record.latest_progress or '任务停在可恢复边界。'}"


def _payload_from_object(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}
