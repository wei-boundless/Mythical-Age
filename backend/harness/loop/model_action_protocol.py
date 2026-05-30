from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ModelActionType = Literal["respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"]


@dataclass(frozen=True, slots=True)
class ModelActionRequest:
    request_id: str
    turn_id: str
    action_type: ModelActionType
    public_progress_note: str = ""
    final_answer: str = ""
    user_question: str = ""
    blocking_reason: str = ""
    tool_call: dict[str, Any] = field(default_factory=dict)
    task_contract_seed: dict[str, Any] = field(default_factory=dict)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    permission_request: dict[str, Any] = field(default_factory=dict)
    engagement_request: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.model_action_request"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.model_action_request":
            raise ValueError("ModelActionRequest authority must be harness.loop.model_action_request")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["tool_call"] = dict(self.tool_call or {})
        payload["completion_contract"] = dict(self.completion_contract or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["engagement_request"] = dict(self.engagement_request or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


def model_action_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
    require_public_progress_note: bool = False,
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    raw = dict(payload or {})
    errors: list[str] = []
    authority = str(raw.get("authority") or "harness.loop.model_action_request").strip()
    if authority != "harness.loop.model_action_request":
        errors.append("invalid_authority")
    action_type = str(raw.get("action_type") or "").strip()
    if action_type not in {"respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "block"}:
        errors.append(f"action_type_unsupported:{action_type}")
    raw_turn_id = str(raw.get("turn_id") or turn_id).strip()
    if raw_turn_id != str(turn_id or "").strip():
        errors.append("turn_id_mismatch")
    tool_call = raw.get("tool_call") or {}
    task_contract_seed = raw.get("task_contract_seed") or {}
    completion_contract = raw.get("completion_contract") or {}
    permission_request = raw.get("permission_request") or {}
    engagement_request = raw.get("engagement_request") or {}
    if not isinstance(tool_call, dict):
        errors.append("tool_call_must_be_object")
        tool_call = {}
    if not isinstance(task_contract_seed, dict):
        errors.append("task_contract_seed_must_be_object")
        task_contract_seed = {}
    if not isinstance(completion_contract, dict):
        errors.append("completion_contract_must_be_object")
        completion_contract = {}
    if not isinstance(permission_request, dict):
        errors.append("permission_request_must_be_object")
        permission_request = {}
    if not isinstance(engagement_request, dict):
        errors.append("engagement_request_must_be_object")
        engagement_request = {}
    final_answer = str(raw.get("final_answer") or "").strip()
    user_question = str(raw.get("user_question") or "").strip()
    blocking_reason = str(raw.get("blocking_reason") or "").strip()
    public_progress_note = _public_progress_note(raw.get("public_progress_note"))
    if require_public_progress_note and not public_progress_note:
        errors.append("public_progress_note_required")
    if action_type == "respond" and not final_answer:
        errors.append("final_answer_required_for_respond")
    if action_type == "ask_user" and not user_question:
        errors.append("user_question_required_for_ask_user")
    if action_type == "block" and not blocking_reason:
        errors.append("blocking_reason_required_for_block")
    if action_type == "tool_call":
        tool_name = str(tool_call.get("tool_name") or tool_call.get("name") or "").strip()
        tool_args = tool_call.get("args") or tool_call.get("tool_args") or {}
        if not tool_name:
            errors.append("tool_name_required_for_tool_call")
        if not isinstance(tool_args, dict):
            errors.append("tool_args_must_be_object")
    if action_type == "request_task_run" and not task_contract_seed:
        errors.append("task_contract_seed_required_for_request_task_run")
    if action_type == "request_registered_engagement":
        plan_id = str(engagement_request.get("plan_id") or raw.get("plan_id") or "").strip()
        if not plan_id:
            errors.append("plan_id_required_for_request_registered_engagement")
    if errors:
        return None, {
            "status": "invalid",
            "validation_errors": errors,
            "authority": "harness.loop.model_action_protocol",
        }
    return ModelActionRequest(
        request_id=str(raw.get("request_id") or f"model-action:{turn_id}:1"),
        turn_id=raw_turn_id,
        action_type=action_type,  # type: ignore[arg-type]
        public_progress_note=public_progress_note,
        final_answer=final_answer,
        user_question=user_question,
        blocking_reason=blocking_reason,
        tool_call=dict(tool_call),
        task_contract_seed=dict(task_contract_seed),
        completion_contract=dict(completion_contract),
        permission_request=dict(permission_request),
        engagement_request=dict(engagement_request),
        diagnostics=dict(raw.get("diagnostics") or {}),
    ), {
        "status": "accepted",
        "validation_errors": [],
        "authority": "harness.loop.model_action_protocol",
    }


def _public_progress_note(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for source, replacement in (
        ("runtime packet", "上下文"),
        ("RuntimeInvocationPacket", "上下文"),
        ("TaskRun", "当前工作"),
        ("task run", "当前工作"),
        ("执行器", "处理流程"),
        ("回灌", "交回"),
    ):
        text = text.replace(source, replacement)
    text = " ".join(text.split())
    return text[:160].rstrip()
