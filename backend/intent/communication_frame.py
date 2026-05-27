from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

USER_POSTURES = {"ask", "explore", "execute", "correct", "continue", "review", "dissatisfied", "conversation"}
AGENT_POSTURES = {
    "answer",
    "clarify",
    "plan_first",
    "execute",
    "review_first",
    "repair_understanding",
    "continue_task",
}
COLLABORATION_MODES = {"conversation", "planning", "implementation", "verification", "long_task"}
CLARIFICATION_POLICIES = {"ask_now", "proceed_with_assumption", "no_clarification_needed"}
PROGRESS_POLICIES = {"none", "brief_updates", "todo_required"}
FINAL_RESPONSE_CONTRACTS = {
    "direct_answer",
    "implementation_report",
    "findings_first",
    "verification_report",
    "planning_report",
}


@dataclass(frozen=True, slots=True)
class CommunicationFrame:
    frame_id: str
    user_posture: str
    agent_posture: str
    collaboration_mode: str
    clarification_policy: str
    progress_policy: str
    final_response_contract: str
    latest_user_instruction_priority: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)
    authority: str = "intent.communication_frame"

    def __post_init__(self) -> None:
        if self.authority != "intent.communication_frame":
            raise ValueError("CommunicationFrame authority must be intent.communication_frame")
        if not self.frame_id:
            raise ValueError("CommunicationFrame requires frame_id")
        if self.user_posture not in USER_POSTURES:
            raise ValueError(f"Invalid user_posture: {self.user_posture}")
        if self.agent_posture not in AGENT_POSTURES:
            raise ValueError(f"Invalid agent_posture: {self.agent_posture}")
        if self.collaboration_mode not in COLLABORATION_MODES:
            raise ValueError(f"Invalid collaboration_mode: {self.collaboration_mode}")
        if self.clarification_policy not in CLARIFICATION_POLICIES:
            raise ValueError(f"Invalid clarification_policy: {self.clarification_policy}")
        if self.progress_policy not in PROGRESS_POLICIES:
            raise ValueError(f"Invalid progress_policy: {self.progress_policy}")
        if self.final_response_contract not in FINAL_RESPONSE_CONTRACTS:
            raise ValueError(f"Invalid final_response_contract: {self.final_response_contract}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = dict(self.evidence or {})
        return payload


def build_communication_frame(
    message: str,
    *,
    user_provided_flow: tuple[str, ...] | list[str] = (),
    ambiguity_points: tuple[str, ...] | list[str] = (),
    forbidden_actions: tuple[str, ...] | list[str] = (),
    query_understanding: dict[str, Any] | None = None,
) -> CommunicationFrame:
    text = str(message or "").strip()
    query = dict(query_understanding or {})
    action_request = dict(query.get("agent_turn_action_request") or {})
    task_contract = dict(query.get("task_contract_seed") or query.get("task_requirement_contract") or {})
    action_type = str(action_request.get("action_type") or "").strip()
    user_posture = _user_posture_from_runtime(action_type=action_type, task_contract=task_contract)
    agent_posture = _agent_posture(
        action_type=action_type,
        ambiguity_points=tuple(ambiguity_points or ()),
        forbidden_actions=tuple(forbidden_actions or ()),
    )
    mode = _collaboration_mode(
        action_type=action_type,
        task_contract=task_contract,
        user_provided_flow=tuple(user_provided_flow or ()),
    )
    return CommunicationFrame(
        frame_id=f"communication:{_slug(text)[:48] or 'runtime'}",
        user_posture=user_posture,
        agent_posture=agent_posture,
        collaboration_mode=mode,
        clarification_policy=_clarification_policy(
            agent_posture=agent_posture,
            ambiguity_points=tuple(ambiguity_points or ()),
            forbidden_actions=tuple(forbidden_actions or ()),
        ),
        progress_policy=_progress_policy(mode=mode, user_provided_flow=tuple(user_provided_flow or ())),
        final_response_contract=_final_response_contract(task_contract=task_contract, mode=mode),
        latest_user_instruction_priority=True,
        evidence={
            "agent_turn_action_request_ref": str(action_request.get("request_id") or ""),
            "task_contract_ref": str(task_contract.get("contract_id") or ""),
        },
    )


def _user_posture_from_runtime(*, action_type: str, task_contract: dict[str, Any]) -> str:
    if action_type == "ask_user":
        return "ask"
    if action_type == "block":
        return "dissatisfied" if task_contract else "conversation"
    if action_type == "request_task_run":
        return "execute"
    return "conversation"


def _agent_posture(
    *,
    action_type: str,
    ambiguity_points: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
) -> str:
    if action_type == "block":
        return "repair_understanding"
    if action_type == "ask_user" or ambiguity_points:
        return "clarify"
    if "modify_workspace" in set(forbidden_actions):
        return "plan_first"
    if action_type == "request_task_run":
        return "execute"
    return "answer"


def _collaboration_mode(
    *,
    action_type: str,
    task_contract: dict[str, Any],
    user_provided_flow: tuple[str, ...],
) -> str:
    if action_type == "request_task_run":
        if _contract_requires_verification(task_contract):
            return "verification"
        return "long_task" if len(user_provided_flow) >= 3 else "implementation"
    return "conversation"


def _clarification_policy(
    *,
    agent_posture: str,
    ambiguity_points: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
) -> str:
    if agent_posture == "clarify":
        return "ask_now"
    if ambiguity_points or forbidden_actions:
        return "proceed_with_assumption"
    return "no_clarification_needed"


def _progress_policy(*, mode: str, user_provided_flow: tuple[str, ...]) -> str:
    if mode == "long_task" or len(user_provided_flow) >= 3:
        return "todo_required"
    if mode in {"implementation", "verification"}:
        return "brief_updates"
    return "none"


def _final_response_contract(*, task_contract: dict[str, Any], mode: str) -> str:
    if mode == "verification" or _contract_requires_verification(task_contract):
        return "verification_report"
    if mode == "planning":
        return "planning_report"
    if mode in {"implementation", "long_task"}:
        return "implementation_report"
    return "direct_answer"


def _contract_requires_verification(task_contract: dict[str, Any]) -> bool:
    actions = {
        str(item).strip()
        for item in list(task_contract.get("required_actions") or [])
        if str(item).strip()
    }
    return bool(actions.intersection({"run_verification", "run_browser_verification", "validate_deliverables"}))


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"


