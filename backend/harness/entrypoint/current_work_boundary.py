from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from harness.loop.active_work import ActiveWorkTurnDecision


CurrentWorkBoundaryAction = Literal[
    "no_current_work",
    "current_work_control_required",
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "new_independent_turn_allowed",
    "replace_current_work",
    "ask_user",
    "block",
]

_ACTIONS: set[str] = {
    "no_current_work",
    "current_work_control_required",
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "new_independent_turn_allowed",
    "replace_current_work",
    "ask_user",
    "block",
}
_CONTROL_ACTIONS = {
    "continue_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "answer_then_continue_active_work",
    "pause_active_work",
    "stop_active_work",
}
_STEER_ALLOWED_ACTIONS = _CONTROL_ACTIONS | {"ask_user", "block", "replace_current_work"}
_TERMINAL_TASK_STATUSES = {"completed", "success", "failed", "aborted", "cancelled", "canceled", "error", "stopped", "user_aborted"}


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryInput:
    turn_input_facts: dict[str, Any]
    active_turn_record: dict[str, Any] = field(default_factory=dict)
    active_turn_check: dict[str, Any] = field(default_factory=dict)
    active_work_context: dict[str, Any] = field(default_factory=dict)
    current_task_collision_candidate: dict[str, Any] = field(default_factory=dict)
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
    allowed_next_actions: tuple[str, ...] = ()
    forbidden_next_actions: tuple[str, ...] = ()
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
        payload = asdict(self)
        payload["allowed_next_actions"] = list(self.allowed_next_actions)
        payload["forbidden_next_actions"] = list(self.forbidden_next_actions)
        return payload

    def to_active_work_turn_decision(self) -> ActiveWorkTurnDecision:
        action = self.action if self.action in _CONTROL_ACTIONS else "ask_user"
        return ActiveWorkTurnDecision(
            action=action,  # type: ignore[arg-type]
            response=self.response,
            appended_instruction=self.appended_instruction,
            reason=self.reason,
            relation_to_current_work="current_work" if self.action in _CONTROL_ACTIONS else self.relation_to_current_work,
            evidence=self.evidence,
            turn_response_policy="answer_then_active_work" if self.action == "answer_then_continue_active_work" else "active_work_only",
            user_turn_kind="command",
            answer_obligation=self.public_response_obligation,
            continuation_strategy=self.continuation_strategy,
            accepted=self.action in _CONTROL_ACTIONS,
            denied_reason="" if self.action in _CONTROL_ACTIONS else "current_work_boundary_action_not_control",
        )


@dataclass(frozen=True, slots=True)
class CurrentWorkBoundaryReceipt:
    receipt_id: str
    decision_id: str
    boundary_action: str
    execution_route: str
    active_work_ref: dict[str, Any] = field(default_factory=dict)
    task_run_ref: str = ""
    turn_ref: str = ""
    runtime_branch_ref: dict[str, Any] = field(default_factory=dict)
    allowed_action_types_for_next_packet: tuple[str, ...] = ()
    active_work_control_payload: dict[str, Any] = field(default_factory=dict)
    replacement_policy: dict[str, Any] = field(default_factory=dict)
    public_projection_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    enforced: bool = True
    authority: str = "harness.entrypoint.current_work_boundary_receipt"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_action_types_for_next_packet"] = list(self.allowed_action_types_for_next_packet)
        return payload


def build_current_work_boundary_input(
    *,
    turn_input_facts: Any,
    active_turn_record: Any | None = None,
    active_turn_check: dict[str, Any] | None = None,
    active_work_context: Any | None = None,
    current_task_collision_candidate: Any | None = None,
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
        current_task_collision_candidate=_payload_from_object(current_task_collision_candidate),
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
                action="block",
                relation="stale_or_missing_active_turn",
                reason="expected_active_turn_unavailable",
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
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
                action="block",
                relation="stale_or_missing_active_turn",
                reason="active_turn_steer_not_running",
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
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
                action="block",
                relation="stale_or_missing_active_turn",
                reason=str(active_check.get("denied_reason") or "expected_active_turn_mismatch"),
                response="当前任务状态已变化，这条补充没有接入正在运行的任务。请刷新后重试。",
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
            action="block" if policy == "steer" else "new_independent_turn_allowed",
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
            action="new_independent_turn_allowed" if policy != "steer" else "block",
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
    return _decision(
        session_id=session_id,
        turn_id=turn_id,
        action="current_work_control_required",
        relation="active_turn_bound_current_work",
        reason="semantic_boundary_decision_required",
        expected_turn_id=expected_turn_id,
        actual_turn_id=actual_turn_id,
        task_run_id=task_run_id,
        active_work=active_work,
        active_check=active_check,
        boundary_input=boundary_input,
        requires_model=True,
    )


def current_work_boundary_decision_from_payload(
    payload: dict[str, Any] | None,
    *,
    boundary_input: CurrentWorkBoundaryInput,
) -> CurrentWorkBoundaryDecision:
    raw = dict(payload or {})
    hard = decide_current_work_boundary(boundary_input)
    if hard.action != "current_work_control_required":
        return hard
    action = _normalize_action(raw.get("action") or raw.get("boundary_action"))
    if not action:
        return _model_boundary_denied(boundary_input, hard, "boundary_action_required")
    if action not in _ACTIONS or action in {"no_current_work", "current_work_control_required"}:
        return _model_boundary_denied(boundary_input, hard, f"boundary_action_not_allowed:{action}")
    policy = str(boundary_input.active_turn_input_policy or "auto").strip().lower() or "auto"
    if policy == "steer" and action not in _STEER_ALLOWED_ACTIONS:
        return _model_boundary_denied(boundary_input, hard, f"steer_boundary_action_not_allowed:{action}")
    relation = _normalize_relation(raw.get("relation_to_current_work") or raw.get("relation"))
    if action in _CONTROL_ACTIONS | {"replace_current_work"}:
        relation = "current_work" if relation == "ambiguous" else relation
    if action in _CONTROL_ACTIONS and relation != "current_work":
        return _model_boundary_denied(boundary_input, hard, "current_work_relation_required")
    reason = str(raw.get("reason") or "").strip() or action
    return _decision(
        session_id=hard.session_id,
        turn_id=hard.turn_id,
        action=action,  # type: ignore[arg-type]
        relation=relation,
        reason=reason,
        response=str(raw.get("response") or raw.get("public_response") or "").strip(),
        appended_instruction=str(raw.get("appended_instruction") or "").strip(),
        continuation_strategy=str(raw.get("continuation_strategy") or "").strip(),
        evidence=str(raw.get("evidence") or "").strip(),
        expected_turn_id=hard.expected_active_turn_id,
        actual_turn_id=hard.actual_active_turn_id,
        task_run_id=hard.task_run_id,
        active_work=dict(boundary_input.active_work_context or {}),
        active_check=dict(boundary_input.active_turn_check or {}),
        boundary_input=boundary_input,
        diagnostics={"model_payload": raw},
    )


def current_work_boundary_receipt_from_decision(decision: CurrentWorkBoundaryDecision) -> CurrentWorkBoundaryReceipt:
    route = _execution_route_for_action(decision.action)
    active_payload = {}
    if decision.action in _CONTROL_ACTIONS:
        active_payload = {
            "action": decision.action,
            "response": decision.response,
            "appended_instruction": decision.appended_instruction,
            "continuation_strategy": decision.continuation_strategy,
            "relation_to_current_work": "current_work",
            "evidence": decision.evidence,
            "reason": decision.reason,
            "resolved_action": decision.action,
        }
    return CurrentWorkBoundaryReceipt(
        receipt_id=f"cwbr:{decision.turn_id}:{decision.decision_id.rsplit(':', 1)[-1]}",
        decision_id=decision.decision_id,
        boundary_action=decision.action,
        execution_route=route,
        active_work_ref={
            "active_work_id": decision.active_work_id,
            "task_run_id": decision.task_run_id,
            "actual_active_turn_id": decision.actual_active_turn_id,
        },
        task_run_ref=decision.task_run_id,
        turn_ref=decision.turn_id,
        runtime_branch_ref=dict(decision.diagnostics.get("runtime_branch") or {}),
        allowed_action_types_for_next_packet=decision.allowed_next_actions,
        active_work_control_payload=active_payload,
        replacement_policy=_replacement_policy(decision),
        public_projection_policy={
            "answer_channel": "runtime_control" if route != "ordinary_turn" else "conversation",
            "public_response_obligation": decision.public_response_obligation,
        },
        diagnostics={
            "decision": decision.to_dict(),
            "active_turn_check": dict(decision.active_turn_check or {}),
        },
    )


def boundary_receipt_allows_active_work_control(receipt: dict[str, Any] | CurrentWorkBoundaryReceipt | None) -> bool:
    payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt or {})
    return str(payload.get("boundary_action") or "") in _CONTROL_ACTIONS


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
    allowed, forbidden = _allowed_next_actions(action, boundary_input=boundary_input)
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
        allowed_next_actions=allowed,
        forbidden_next_actions=forbidden,
        reason=reason,
        evidence=evidence,
        public_response_obligation="direct_response_required" if action in {"ask_user", "block"} else "runtime_control_status",
        requires_model_boundary_decision=requires_model,
        response=response,
        appended_instruction=appended_instruction,
        continuation_strategy=continuation_strategy,
        active_turn_check=dict(active_check or {}),
        diagnostics={
            "runtime_branch": dict(boundary_input.runtime_branch or {}),
            "active_turn_input_policy": str(boundary_input.active_turn_input_policy or ""),
            **dict(diagnostics or {}),
        },
    )


def _model_boundary_denied(
    boundary_input: CurrentWorkBoundaryInput,
    hard: CurrentWorkBoundaryDecision,
    reason: str,
) -> CurrentWorkBoundaryDecision:
    action: CurrentWorkBoundaryAction = "block" if str(boundary_input.active_turn_input_policy or "").lower() == "steer" else "ask_user"
    response = (
        "当前工作关系没有通过边界校验，我需要你明确这是继续当前任务、补充当前任务，还是另开普通请求。"
        if action == "ask_user"
        else "当前补充没有通过当前工作边界校验，未接入正在运行的任务。"
    )
    return _decision(
        session_id=hard.session_id,
        turn_id=hard.turn_id,
        action=action,
        relation="ambiguous",
        reason=reason,
        response=response,
        expected_turn_id=hard.expected_active_turn_id,
        actual_turn_id=hard.actual_active_turn_id,
        task_run_id=hard.task_run_id,
        active_work=dict(boundary_input.active_work_context or {}),
        active_check=dict(boundary_input.active_turn_check or {}),
        boundary_input=boundary_input,
    )


def _allowed_next_actions(
    action: str,
    *,
    boundary_input: CurrentWorkBoundaryInput,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    may_request_task = bool(dict(boundary_input.control_capabilities or {}).get("may_request_task_run") is True)
    if action == "no_current_work":
        allowed = ["respond", "ask_user", "block", "tool_call"]
        if may_request_task:
            allowed.append("request_task_run")
        return tuple(dict.fromkeys(allowed)), ("active_work_control",)
    if action == "new_independent_turn_allowed":
        return ("respond", "ask_user", "block", "tool_call"), ("active_work_control", "request_task_run")
    if action == "replace_current_work":
        return ("request_task_run", "ask_user", "block"), ("active_work_control", "tool_call")
    if action in _CONTROL_ACTIONS:
        return ("active_work_control",), ("tool_call", "request_task_run")
    if action in {"ask_user", "block"}:
        return (action,), ("tool_call", "request_task_run", "active_work_control")
    return (), ("tool_call", "request_task_run", "active_work_control")


def _execution_route_for_action(action: str) -> str:
    if action in {"no_current_work", "new_independent_turn_allowed"}:
        return "ordinary_turn"
    if action == "replace_current_work":
        return "replacement_then_task_request"
    if action in _CONTROL_ACTIONS:
        return "control_only"
    return "terminal"


def _replacement_policy(decision: CurrentWorkBoundaryDecision) -> dict[str, Any]:
    if decision.action != "replace_current_work":
        return {}
    return {
        "replace_task_run_id": decision.task_run_id,
        "replacement_turn_id": decision.turn_id,
        "reason": "current_work_boundary_replace_current_work",
        "authority": "harness.entrypoint.current_work_boundary",
    }


def _payload_from_object(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _terminal_active_work(active_work: dict[str, Any]) -> bool:
    return str(active_work.get("status") or "").strip().lower() in _TERMINAL_TASK_STATUSES


def _normalize_action(value: Any) -> str:
    action = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "continue": "continue_active_work",
        "resume": "continue_active_work",
        "append_instruction": "append_instruction_to_active_work",
        "append": "append_instruction_to_active_work",
        "status": "answer_about_active_work",
        "answer_status": "answer_about_active_work",
        "answer_then_continue": "answer_then_continue_active_work",
        "pause": "pause_active_work",
        "stop": "stop_active_work",
        "replace": "replace_current_work",
        "independent": "new_independent_turn_allowed",
        "new_turn": "new_independent_turn_allowed",
    }
    return aliases.get(action, action)


def _normalize_relation(value: Any) -> str:
    relation = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if relation in {"current", "current_work", "active_work", "same_task", "same_work"}:
        return "current_work"
    if relation in {"independent", "independent_turn", "new_turn", "unrelated"}:
        return "independent_turn"
    return "ambiguous"
