from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExecutionMode = Literal[
    "direct_answer",
    "ask_clarification",
    "task_run",
    "block",
]

EXECUTION_MODES = {
    "direct_answer",
    "ask_clarification",
    "task_run",
    "block",
}
NEXT_ACTIONS = {
    "respond",
    "ask_user",
    "launch_task_run",
    "block",
}


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    decision_id: str
    turn_id: str
    execution_mode: ExecutionMode
    next_action: str
    status_code: str = "decision.accepted"
    phase: str = "execution_decision"
    decision_basis_refs: tuple[str, ...] = ()
    blocking_reason: str = ""
    requires_task_run: bool = False
    requires_write: bool = False
    requires_command: bool = False
    requires_browser: bool = False
    requires_network: bool = False
    requires_artifacts: bool = False
    selected_context_refs: tuple[str, ...] = ()
    tool_intent: dict[str, Any] = field(default_factory=dict)
    permission_request: dict[str, Any] = field(default_factory=dict)
    task_contract_seed: dict[str, Any] = field(default_factory=dict)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    clarification_question: str = ""
    confidence: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "agent_runtime.execution_decision"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision_basis_refs"] = list(self.decision_basis_refs)
        payload["selected_context_refs"] = list(self.selected_context_refs)
        payload["tool_intent"] = dict(self.tool_intent or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["completion_contract"] = dict(self.completion_contract or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def execution_decision_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
) -> tuple[ExecutionDecision | None, dict[str, Any]]:
    raw = dict(payload or {})
    if not raw:
        return None, {"decision_status": "absent", "validation_errors": ["execution_decision_absent"]}
    errors: list[str] = []
    authority = str(raw.get("authority") or "agent_runtime.execution_decision").strip()
    if authority != "agent_runtime.execution_decision":
        errors.append("invalid_authority")
    payload_turn_id = str(raw.get("turn_id") or turn_id or "").strip()
    if not payload_turn_id:
        errors.append("turn_id_required")
    elif turn_id and payload_turn_id != turn_id:
        errors.append("turn_id_mismatch")
    execution_mode = str(raw.get("execution_mode") or "").strip()
    if execution_mode not in EXECUTION_MODES:
        errors.append(f"execution_mode_unsupported:{execution_mode}")
    next_action = str(raw.get("next_action") or _default_next_action(execution_mode)).strip()
    if next_action not in NEXT_ACTIONS:
        errors.append(f"next_action_unsupported:{next_action}")
    clarification_question = str(raw.get("clarification_question") or "").strip()
    blocking_reason = str(raw.get("blocking_reason") or raw.get("block_reason") or "").strip()
    requires_task_run = bool(raw.get("requires_task_run") is True or execution_mode == "task_run")
    task_contract_seed = raw.get("task_contract_seed") or {}
    if not isinstance(task_contract_seed, dict):
        errors.append("task_contract_seed_must_be_object")
        task_contract_seed = {}
    completion_contract = raw.get("completion_contract") or {}
    if not isinstance(completion_contract, dict):
        errors.append("completion_contract_must_be_object")
        completion_contract = {}
    permission_request = raw.get("permission_request") or {}
    if not isinstance(permission_request, dict):
        errors.append("permission_request_must_be_object")
        permission_request = {}
    tool_intent = raw.get("tool_intent") or {}
    if not isinstance(tool_intent, dict):
        errors.append("tool_intent_must_be_object")
        tool_intent = {}
    if execution_mode == "ask_clarification" and not clarification_question:
        errors.append("clarification_question_required")
    if execution_mode == "block" and not blocking_reason:
        errors.append("blocking_reason_required")
    if execution_mode == "direct_answer" and requires_task_run:
        errors.append("direct_answer_cannot_require_task_run")
    if execution_mode == "task_run":
        if not requires_task_run:
            errors.append("task_run_requires_task_run_true")
        if not task_contract_seed:
            errors.append("task_contract_seed_required_for_task_run")
    if bool(raw.get("requires_artifacts") is True) and not dict(completion_contract).get("artifact_requirements"):
        errors.append("artifact_requirements_required")
    if errors:
        return None, {
            "decision_status": "rejected_invalid",
            "validation_errors": errors,
            "model_authority_used": False,
        }
    decision = ExecutionDecision(
        decision_id=str(raw.get("decision_id") or f"execution-decision:{payload_turn_id}"),
        turn_id=payload_turn_id,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        next_action=next_action,
        status_code=str(raw.get("status_code") or "decision.accepted").strip(),
        phase=str(raw.get("phase") or "execution_decision").strip(),
        decision_basis_refs=tuple(_sequence(raw.get("decision_basis_refs"))),
        blocking_reason=blocking_reason,
        requires_task_run=requires_task_run,
        requires_write=bool(raw.get("requires_write") is True),
        requires_command=bool(raw.get("requires_command") is True),
        requires_browser=bool(raw.get("requires_browser") is True),
        requires_network=bool(raw.get("requires_network") is True),
        requires_artifacts=bool(raw.get("requires_artifacts") is True),
        selected_context_refs=tuple(_sequence(raw.get("selected_context_refs"))),
        tool_intent=dict(tool_intent),
        permission_request=dict(permission_request),
        task_contract_seed=dict(task_contract_seed),
        completion_contract=dict(completion_contract),
        clarification_question=clarification_question,
        confidence=_confidence(raw.get("confidence")),
        diagnostics=dict(raw.get("diagnostics") or {}),
    )
    return decision, {"decision_status": "accepted", "validation_errors": [], "model_authority_used": True}


def execution_decision_from_model_turn(
    *,
    turn_id: str,
    model_turn_decision: dict[str, Any],
) -> ExecutionDecision:
    decision = dict(model_turn_decision or {})
    action_intent = str(decision.get("action_intent") or "").strip()
    work_mode = str(decision.get("work_mode") or "").strip()
    needs_clarification = bool(decision.get("needs_clarification") is True)
    if needs_clarification:
        mode = "ask_clarification"
    elif action_intent == "block":
        mode = "block"
    elif action_intent == "answer_only" and work_mode == "conversation":
        mode = "direct_answer"
    elif action_intent in {
        "read_context",
        "search_external",
        "edit_workspace",
        "run_command",
        "start_service",
        "use_browser",
        "delegate",
    }:
        mode = "task_run"
    else:
        mode = "direct_answer"
    task_goal_type = str(decision.get("task_goal_type") or "").strip()
    resource_contract = dict(decision.get("resource_contract") or {})
    task_contract_seed = {}
    if mode == "task_run":
        task_contract_seed = {
            "goal": str(decision.get("desired_outcome") or decision.get("user_message") or "").strip(),
            "task_goal_type": task_goal_type,
            "deliverables": list(decision.get("deliverables") or []),
            "completion_criteria": list(decision.get("completion_criteria") or []),
            "resource_contract": resource_contract,
            "authority": "agent_runtime.execution_decision.task_contract_seed",
        }
    return ExecutionDecision(
        decision_id=f"execution-decision:{turn_id}",
        turn_id=turn_id,
        execution_mode=mode,  # type: ignore[arg-type]
        next_action=_default_next_action(mode),
        decision_basis_refs=tuple(
            item for item in (str(decision.get("decision_id") or ""),) if item
        ),
        blocking_reason=str(decision.get("blocking_reason") or "").strip(),
        requires_task_run=mode == "task_run",
        requires_write=action_intent == "edit_workspace",
        requires_command=action_intent in {"run_command", "start_service"},
        requires_browser=action_intent == "use_browser",
        requires_network=action_intent == "search_external",
        requires_artifacts=bool(task_contract_seed.get("deliverables")),
        permission_request={"action_intent": action_intent} if action_intent else {},
        task_contract_seed=task_contract_seed,
        completion_contract={
            "completion_criteria": list(decision.get("completion_criteria") or []),
            "artifact_requirements": list(decision.get("deliverables") or []) if mode == "task_run" else [],
        },
        clarification_question=str(decision.get("clarification_question") or "").strip(),
        confidence=_confidence(decision.get("confidence")),
        diagnostics={"derived_from_model_turn_decision": True},
    )

def _default_next_action(execution_mode: str) -> str:
    return {
        "direct_answer": "respond",
        "ask_clarification": "ask_user",
        "task_run": "launch_task_run",
        "block": "block",
    }.get(str(execution_mode or ""), "respond")


def _sequence(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)
