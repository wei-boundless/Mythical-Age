from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from harness.task_run_status import is_stopped_or_terminal_task_run


CurrentWorkBoundaryAction = Literal[
    "no_current_work",
    "current_work_control_required",
    "current_work_unavailable",
    "new_independent_turn_allowed",
    "ask_user",
    "block",
]


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryInput:
    turn_input_facts: dict[str, Any]
    active_turn_record: dict[str, Any] = field(default_factory=dict)
    active_turn_check: dict[str, Any] = field(default_factory=dict)
    active_work_context: dict[str, Any] = field(default_factory=dict)
    request_active_turn_policy: str = "auto"
    active_turn_input_policy: str = "auto"
    expected_active_turn_id: str = ""
    runtime_branch: dict[str, Any] = field(default_factory=dict)
    control_capabilities: dict[str, Any] = field(default_factory=dict)
    context_policy: dict[str, Any] = field(default_factory=dict)
    editor_context_summary: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.entrypoint.current_work_boundary_input"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryDecision:
    decision_id: str
    turn_id: str
    session_id: str
    action: CurrentWorkBoundaryAction
    relation_to_current_work: str = "none"
    active_work_id: str = ""
    task_run_id: str = ""
    expected_active_turn_id: str = ""
    actual_active_turn_id: str = ""
    reason: str = ""
    evidence: str = ""
    public_response_obligation: str = "runtime_control_status"
    requires_model_boundary_decision: bool = False
    response: str = ""
    appended_instruction: str = ""
    continuation_strategy: str = ""
    active_turn_check: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.entrypoint.current_work_boundary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryReceipt:
    receipt_id: str
    decision_id: str
    boundary_decision: str
    active_work_ref: dict[str, Any] = field(default_factory=dict)
    task_run_ref: str = ""
    turn_ref: str = ""
    runtime_branch_ref: dict[str, Any] = field(default_factory=dict)
    operation_availability: dict[str, bool] = field(default_factory=dict)
    observation_state: str = "available"
    state_reason: str = ""
    expected_active_turn_id: str = ""
    actual_active_turn_id: str = ""
    public_projection_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.entrypoint.current_work_boundary_receipt"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_current_work_boundary_input(
    *,
    turn_input_facts: Any,
    active_turn_record: Any | None = None,
    active_turn_check: dict[str, Any] | None = None,
    active_work_context: Any | None = None,
    request_active_turn_policy: str = "auto",
    active_turn_input_policy: str = "auto",
    expected_active_turn_id: str = "",
    runtime_branch: dict[str, Any] | None = None,
    control_capabilities: dict[str, Any] | None = None,
    context_policy: dict[str, Any] | None = None,
    editor_context_summary: dict[str, Any] | None = None,
) -> CurrentWorkBoundaryInput:
    return CurrentWorkBoundaryInput(
        turn_input_facts=_payload_from_object(turn_input_facts),
        active_turn_record=_payload_from_object(active_turn_record),
        active_turn_check=dict(active_turn_check or {}),
        active_work_context=_payload_from_object(active_work_context),
        request_active_turn_policy=str(request_active_turn_policy or "auto").strip() or "auto",
        active_turn_input_policy=str(active_turn_input_policy or "auto").strip() or "auto",
        expected_active_turn_id=str(expected_active_turn_id or "").strip(),
        runtime_branch=dict(runtime_branch or {}),
        control_capabilities=dict(control_capabilities or {}),
        context_policy=dict(context_policy or {}),
        editor_context_summary=dict(editor_context_summary or {}),
    )


def decide_current_work_boundary(boundary_input: CurrentWorkBoundaryInput) -> CurrentWorkBoundaryDecision:
    facts = dict(boundary_input.turn_input_facts or {})
    session_id = str(facts.get("session_id") or "").strip()
    turn_id = str(facts.get("turn_id") or "").strip()
    policy = str(boundary_input.active_turn_input_policy or facts.get("active_turn_input_policy") or "auto").strip().lower() or "auto"
    expected_turn_id = str(boundary_input.expected_active_turn_id or facts.get("expected_active_turn_id") or "").strip()
    active_work = dict(boundary_input.active_work_context or {})
    active_check = dict(boundary_input.active_turn_check or {})
    actual_turn_id = str(active_check.get("actual_turn_id") or active_check.get("turn_id") or active_work.get("active_work_id") or "").strip()
    task_run_id = str(active_check.get("actual_task_run_id") or active_work.get("task_run_id") or "").strip()
    if policy == "steer":
        if not expected_turn_id:
            return _decision(
                session_id=session_id,
                turn_id=turn_id,
                action="current_work_unavailable",
                relation="stale_or_missing_active_turn",
                reason="expected_active_turn_unavailable",
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。",
                expected_turn_id=expected_turn_id,
                actual_turn_id=actual_turn_id,
                task_run_id=task_run_id,
                active_work=active_work,
                active_check=active_check,
                boundary_input=boundary_input,
            )
        if not active_work:
            return _decision(
                session_id=session_id,
                turn_id=turn_id,
                action="current_work_unavailable",
                relation="stale_or_missing_active_turn",
                reason="active_turn_steer_not_running",
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。",
                expected_turn_id=expected_turn_id,
                actual_turn_id=actual_turn_id,
                task_run_id=task_run_id,
                active_work=active_work,
                active_check=active_check,
                boundary_input=boundary_input,
            )
        if active_check and active_check.get("accepted") is False:
            return _decision(
                session_id=session_id,
                turn_id=turn_id,
                action="current_work_unavailable",
                relation="stale_or_missing_active_turn",
                reason=str(active_check.get("denied_reason") or "expected_active_turn_mismatch"),
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。",
                expected_turn_id=expected_turn_id,
                actual_turn_id=actual_turn_id,
                task_run_id=task_run_id,
                active_work=active_work,
                active_check=active_check,
                boundary_input=boundary_input,
            )
    if not active_work:
        return _decision(
            session_id=session_id,
            turn_id=turn_id,
            action="no_current_work",
            relation="none",
            reason="no_active_turn_bound_current_work",
            expected_turn_id=expected_turn_id,
            actual_turn_id=actual_turn_id,
            task_run_id=task_run_id,
            active_work=active_work,
            active_check=active_check,
            boundary_input=boundary_input,
        )
    if str(active_work.get("authority") or "") != "harness.runtime.active_turn_context":
        return _decision(
            session_id=session_id,
            turn_id=turn_id,
            action="current_work_unavailable" if policy == "steer" else "new_independent_turn_allowed",
            relation="read_only_active_work_context",
            reason="active_work_context_not_active_turn_bound",
            response="当前任务状态不可作为可控制工作处理。",
            expected_turn_id=expected_turn_id,
            actual_turn_id=actual_turn_id,
            task_run_id=task_run_id,
            active_work=active_work,
            active_check=active_check,
            boundary_input=boundary_input,
        )
    if _terminal_active_work(active_work):
        return _decision(
            session_id=session_id,
            turn_id=turn_id,
            action="new_independent_turn_allowed" if policy != "steer" else "current_work_unavailable",
            relation="terminal_active_work_read_only",
            reason="active_work_terminal",
            response="当前任务已经结束，不能继续控制这条运行。",
            expected_turn_id=expected_turn_id,
            actual_turn_id=actual_turn_id,
            task_run_id=task_run_id,
            active_work=active_work,
            active_check=active_check,
            boundary_input=boundary_input,
        )
    if policy != "steer":
        return _decision(
            session_id=session_id,
            turn_id=turn_id,
            action="new_independent_turn_allowed",
            relation="active_work_present_without_steer_policy",
            reason="active_work_control_requires_steer_policy",
            expected_turn_id=expected_turn_id,
            actual_turn_id=actual_turn_id,
            task_run_id=task_run_id,
            active_work=active_work,
            active_check=active_check,
            boundary_input=boundary_input,
        )
    return _decision(
        session_id=session_id,
        turn_id=turn_id,
        action="current_work_control_required",
        relation="active_turn_bound_current_work",
        reason="active_work_boundary_ready",
        expected_turn_id=expected_turn_id,
        actual_turn_id=actual_turn_id,
        task_run_id=task_run_id,
        active_work=active_work,
        active_check=active_check,
        boundary_input=boundary_input,
        requires_model=False,
    )


def current_work_boundary_receipt_from_decision(decision: CurrentWorkBoundaryDecision) -> CurrentWorkBoundaryReceipt:
    control_capabilities = dict(decision.diagnostics.get("control_capabilities") or {})
    may_control_active_work = bool(control_capabilities.get("may_control_active_work") is not False)
    operation_availability = {
        "active_work_control": decision.action == "current_work_control_required" and may_control_active_work,
    }
    observation_state = (
        "controllable_current_work"
        if operation_availability["active_work_control"]
        else ("no_current_work" if decision.action == "no_current_work" else "read_only_or_unavailable")
    )
    return CurrentWorkBoundaryReceipt(
        receipt_id=f"cwreceipt:{decision.turn_id}:{decision.decision_id.rsplit(':', 1)[-1]}",
        decision_id=decision.decision_id,
        boundary_decision=decision.action,
        active_work_ref={
            "active_work_id": decision.active_work_id,
            "task_run_id": decision.task_run_id,
            "actual_active_turn_id": decision.actual_active_turn_id,
        },
        task_run_ref=decision.task_run_id,
        turn_ref=decision.turn_id,
        runtime_branch_ref=dict(decision.diagnostics.get("runtime_branch") or {}),
        operation_availability=operation_availability,
        observation_state=observation_state,
        state_reason=decision.reason,
        expected_active_turn_id=decision.expected_active_turn_id,
        actual_active_turn_id=decision.actual_active_turn_id,
        public_projection_policy={
            "answer_channel": "conversation",
            "public_response_obligation": decision.public_response_obligation,
        },
        diagnostics={
            "decision": decision.to_dict(),
            "active_turn_check": dict(decision.active_turn_check or {}),
        },
    )


def current_work_boundary_receipt_allows_active_work_control(
    receipt: dict[str, Any] | CurrentWorkBoundaryReceipt | None,
) -> bool:
    payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {})
    operations = dict(payload.get("operation_availability") or {})
    return bool(operations.get("active_work_control") is True)


def _decision(
    *,
    session_id: str,
    turn_id: str,
    action: CurrentWorkBoundaryAction,
    relation: str,
    reason: str,
    expected_turn_id: str,
    actual_turn_id: str,
    task_run_id: str,
    active_work: dict[str, Any],
    active_check: dict[str, Any],
    boundary_input: CurrentWorkBoundaryInput,
    response: str = "",
    evidence: str = "",
    appended_instruction: str = "",
    continuation_strategy: str = "",
    requires_model: bool = False,
    diagnostics: dict[str, Any] | None = None,
) -> CurrentWorkBoundaryDecision:
    now_key = int(time.time() * 1000)
    return CurrentWorkBoundaryDecision(
        decision_id=f"cwbd:{turn_id}:{now_key}",
        session_id=session_id,
        turn_id=turn_id,
        action=action,
        relation_to_current_work=relation,
        active_work_id=str(active_work.get("active_work_id") or "").strip(),
        task_run_id=task_run_id,
        expected_active_turn_id=expected_turn_id,
        actual_active_turn_id=actual_turn_id,
        reason=reason,
        evidence=evidence,
        public_response_obligation="direct_response_required" if action == "current_work_unavailable" else "runtime_control_status",
        requires_model_boundary_decision=requires_model,
        response=response,
        appended_instruction=appended_instruction,
        continuation_strategy=continuation_strategy,
        active_turn_check=dict(active_check or {}),
        diagnostics={
            "runtime_branch": dict(boundary_input.runtime_branch or {}),
            "control_capabilities": dict(boundary_input.control_capabilities or {}),
            "active_turn_input_policy": str(boundary_input.active_turn_input_policy or ""),
            **dict(diagnostics or {}),
        },
    )


def _payload_from_object(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _terminal_active_work(active_work: dict[str, Any]) -> bool:
    return is_stopped_or_terminal_task_run(active_work)
