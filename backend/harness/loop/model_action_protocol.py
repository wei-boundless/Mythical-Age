from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ModelActionType = Literal[
    "respond",
    "ask_user",
    "tool_call",
    "request_task_run",
    "request_registered_engagement",
    "active_work_control",
    "block",
]
TaskExecutionModelActionType = Literal["respond", "ask_user", "tool_call", "block"]


@dataclass(frozen=True, slots=True)
class ModelActionRequest:
    request_id: str
    turn_id: str
    action_type: ModelActionType
    public_progress_note: str = ""
    public_action_state: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    user_question: str = ""
    blocking_reason: str = ""
    tool_call: dict[str, Any] = field(default_factory=dict)
    selected_skill_ids: tuple[str, ...] = ()
    task_contract_seed: dict[str, Any] = field(default_factory=dict)
    completion_contract: dict[str, Any] = field(default_factory=dict)
    permission_request: dict[str, Any] = field(default_factory=dict)
    engagement_request: dict[str, Any] = field(default_factory=dict)
    active_work_control: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.model_action_request"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.model_action_request":
            raise ValueError("ModelActionRequest authority must be harness.loop.model_action_request")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["selected_skill_ids"] = list(self.selected_skill_ids)
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["tool_call"] = dict(self.tool_call or {})
        payload["public_action_state"] = dict(self.public_action_state or {})
        payload["completion_contract"] = dict(self.completion_contract or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["engagement_request"] = dict(self.engagement_request or {})
        payload["active_work_control"] = dict(self.active_work_control or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class TaskExecutionModelActionRequest:
    request_id: str
    turn_id: str
    action_type: TaskExecutionModelActionType
    public_progress_note: str = ""
    public_action_state: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""
    user_question: str = ""
    blocking_reason: str = ""
    tool_call: dict[str, Any] = field(default_factory=dict)
    tool_calls: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.model_action_request"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.model_action_request":
            raise ValueError("TaskExecutionModelActionRequest authority must be harness.loop.model_action_request")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tool_call"] = dict(self.tool_call or {})
        payload["tool_calls"] = [dict(item) for item in tuple(self.tool_calls or ())]
        payload["public_action_state"] = dict(self.public_action_state or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


AnyModelActionRequest = ModelActionRequest | TaskExecutionModelActionRequest


def model_action_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
    require_public_progress_note: bool = False,
    require_public_action_state: bool = False,
    allowed_action_types: tuple[str, ...] | set[str] | None = None,
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    raw = dict(payload or {})
    errors: list[str] = []
    authority = str(raw.get("authority") or "harness.loop.model_action_request").strip()
    if authority != "harness.loop.model_action_request":
        errors.append("invalid_authority")
    action_type = str(raw.get("action_type") or "").strip()
    if action_type not in {"respond", "ask_user", "tool_call", "request_task_run", "request_registered_engagement", "active_work_control", "block"}:
        errors.append(f"action_type_unsupported:{action_type}")
    allowed = {str(item) for item in list(allowed_action_types or ()) if str(item)}
    if allowed and action_type and action_type not in allowed:
        errors.append(f"action_type_not_allowed_for_context:{action_type}")
    raw_turn_id = str(raw.get("turn_id") or turn_id).strip()
    if raw_turn_id != str(turn_id or "").strip():
        errors.append("turn_id_mismatch")
    tool_call = raw.get("tool_call") or {}
    selected_skill_ids = _string_tuple(raw.get("selected_skill_ids"))
    task_contract_seed = raw.get("task_contract_seed") or {}
    completion_contract = raw.get("completion_contract") or {}
    permission_request = raw.get("permission_request") or {}
    engagement_request = raw.get("engagement_request") or {}
    active_work_control = raw.get("active_work_control") or {}
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
    if not isinstance(active_work_control, dict):
        errors.append("active_work_control_must_be_object")
        active_work_control = {}
    final_answer = str(raw.get("final_answer") or "").strip()
    user_question = str(raw.get("user_question") or "").strip()
    blocking_reason = str(raw.get("blocking_reason") or "").strip()
    public_progress_note = _public_progress_note(raw.get("public_progress_note"))
    public_action_state = _public_action_state(raw.get("public_action_state"))
    if require_public_progress_note and not public_progress_note:
        errors.append("public_progress_note_required")
    if require_public_action_state and not _has_public_action_state(public_action_state):
        errors.append("public_action_state_required")
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
    if action_type == "active_work_control":
        action = str(active_work_control.get("action") or raw.get("action") or "").strip()
        if not action:
            errors.append("active_work_action_required")
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
        public_action_state=public_action_state,
        final_answer=final_answer,
        user_question=user_question,
        blocking_reason=blocking_reason,
        tool_call=dict(tool_call),
        selected_skill_ids=selected_skill_ids,
        task_contract_seed=dict(task_contract_seed),
        completion_contract=dict(completion_contract),
        permission_request=dict(permission_request),
        engagement_request=dict(engagement_request),
        active_work_control=dict(active_work_control),
        diagnostics=dict(raw.get("diagnostics") or {}),
    ), {
        "status": "accepted",
        "validation_errors": [],
        "authority": "harness.loop.model_action_protocol",
    }


_TASK_EXECUTION_CROSS_CONTEXT_FIELDS = (
    "selected_skill_ids",
    "task_contract_seed",
    "completion_contract",
    "permission_request",
    "engagement_request",
    "active_work_control",
    "plan_id",
)


def task_execution_action_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
    require_public_progress_note: bool = True,
    require_public_action_state: bool = True,
    allowed_action_types: tuple[str, ...] | set[str] | None = None,
) -> tuple[TaskExecutionModelActionRequest | None, dict[str, Any]]:
    raw = dict(payload or {})
    task_tool_calls, tool_call_errors = _task_execution_tool_calls(raw)
    if task_tool_calls:
        raw["tool_call"] = dict(task_tool_calls[0])
    forbidden_errors = [
        f"field_not_allowed_for_task_execution:{field}"
        for field in _TASK_EXECUTION_CROSS_CONTEXT_FIELDS
        if _has_non_empty_value(raw.get(field))
    ]
    action_request, diagnostics = model_action_request_from_payload(
        raw,
        turn_id=turn_id,
        require_public_progress_note=require_public_progress_note,
        require_public_action_state=require_public_action_state,
        allowed_action_types=tuple(allowed_action_types or ("respond", "ask_user", "tool_call", "block")),
    )
    if forbidden_errors:
        validation_errors = [
            *forbidden_errors,
            *tool_call_errors,
            *list(dict(diagnostics or {}).get("validation_errors") or []),
        ]
        return None, {
            "status": "invalid",
            "validation_errors": validation_errors,
            "authority": "harness.loop.model_action_protocol",
        }
    if action_request is None:
        if tool_call_errors:
            return None, {
                **dict(diagnostics or {}),
                "status": "invalid",
                "validation_errors": [
                    *tool_call_errors,
                    *list(dict(diagnostics or {}).get("validation_errors") or []),
                ],
                "authority": "harness.loop.model_action_protocol",
            }
        return None, diagnostics
    if tool_call_errors:
        return None, {
            "status": "invalid",
            "validation_errors": tool_call_errors,
            "authority": "harness.loop.model_action_protocol",
        }
    if action_request.action_type not in {"respond", "ask_user", "tool_call", "block"}:
        return None, {
            "status": "invalid",
            "validation_errors": [f"action_type_not_allowed_for_task_execution:{action_request.action_type}"],
            "authority": "harness.loop.model_action_protocol",
        }
    if action_request.action_type == "tool_call" and not task_tool_calls:
        task_tool_calls = (dict(action_request.tool_call or {}),) if action_request.tool_call else ()
    return TaskExecutionModelActionRequest(
        request_id=action_request.request_id,
        turn_id=action_request.turn_id,
        action_type=action_request.action_type,  # type: ignore[arg-type]
        public_progress_note=action_request.public_progress_note,
        public_action_state=dict(action_request.public_action_state or {}),
        final_answer=action_request.final_answer,
        user_question=action_request.user_question,
        blocking_reason=action_request.blocking_reason,
        tool_call=dict(action_request.tool_call or {}),
        tool_calls=tuple(dict(item) for item in task_tool_calls),
        diagnostics=dict(action_request.diagnostics or {}),
    ), {
        "status": "accepted",
        "validation_errors": [],
        "authority": "harness.loop.model_action_protocol",
    }


def _public_progress_note(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    return text[:160].rstrip()


_PUBLIC_ACTION_COMPLETION_STATUSES = {"working", "waiting_for_tool", "verifying", "ready_to_finish", "blocked"}
_PUBLIC_ACTION_VISIBLE_STATUSES = {"thinking", "waiting_for_tool", "tool_returned", "responding", "blocked"}


def _public_action_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    current_judgment = _public_progress_note(value.get("current_judgment"))
    next_action = _public_progress_note(value.get("next_action"))
    completion_status = str(value.get("completion_status") or "").strip()
    visible_status = str(value.get("visible_status") or "").strip()
    evidence_refs = _string_tuple(value.get("evidence_refs"))
    open_risks = _string_tuple(value.get("open_risks"))
    if visible_status in _PUBLIC_ACTION_VISIBLE_STATUSES:
        normalized["visible_status"] = visible_status
    if current_judgment:
        normalized["current_judgment"] = current_judgment[:220].rstrip()
    if next_action:
        normalized["next_action"] = next_action[:220].rstrip()
    if completion_status in _PUBLIC_ACTION_COMPLETION_STATUSES:
        normalized["completion_status"] = completion_status
    if evidence_refs:
        normalized["evidence_refs"] = list(evidence_refs[:8])
    if open_risks:
        normalized["open_risks"] = list(open_risks[:6])
    return normalized


def _has_public_action_state(state: dict[str, Any]) -> bool:
    return any(
        bool(state.get(key))
        for key in (
            "visible_status",
            "completion_status",
            "evidence_refs",
            "open_risks",
            "current_judgment",
            "next_action",
        )
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


def _task_execution_tool_calls(raw: dict[str, Any]) -> tuple[tuple[dict[str, Any], ...], list[str]]:
    if str(raw.get("action_type") or "").strip() != "tool_call":
        return (), []
    errors: list[str] = []
    raw_tool_calls = raw.get("tool_calls")
    raw_tool_call = raw.get("tool_call")
    if _has_non_empty_value(raw_tool_calls) and _has_non_empty_value(raw_tool_call):
        errors.append("tool_call_and_tool_calls_cannot_both_be_present")
    calls: list[Any]
    if isinstance(raw_tool_calls, list):
        calls = list(raw_tool_calls)
    elif _has_non_empty_value(raw_tool_calls):
        errors.append("tool_calls_must_be_array")
        calls = []
    else:
        calls = []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(calls):
        if not isinstance(item, dict):
            errors.append(f"tool_calls[{index}]_must_be_object")
            continue
        payload = dict(item)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
        tool_args = payload.get("args") if payload.get("args") is not None else payload.get("tool_args")
        if not tool_name:
            errors.append(f"tool_calls[{index}].tool_name_required")
        if tool_args is None:
            tool_args = {}
        if not isinstance(tool_args, dict):
            errors.append(f"tool_calls[{index}].args_must_be_object")
            tool_args = {}
        payload["tool_name"] = tool_name
        payload["name"] = tool_name
        payload["args"] = dict(tool_args)
        payload.pop("tool_args", None)
        normalized.append(payload)
    if not normalized:
        errors.append("tool_calls_required_for_tool_call")
    return tuple(normalized), errors
