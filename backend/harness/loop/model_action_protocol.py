from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ModelActionType = Literal[
    "respond",
    "ask_user",
    "tool_call",
    "request_task_run",
    "active_work_control",
    "resume_recoverable_work",
    "block",
]
TaskExecutionModelActionType = Literal["respond", "ask_user", "tool_call", "block"]


def _ensure_tool_call_id(tool_call: dict[str, Any] | None, *, request_id: Any, ordinal: int | None = None) -> dict[str, Any]:
    from runtime.shared.tool_identity import ensure_tool_call_id

    return ensure_tool_call_id(tool_call, request_id=request_id, ordinal=ordinal)


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
    active_work_control: dict[str, Any] = field(default_factory=dict)
    recovery_resume: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.model_action_request"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.model_action_request":
            raise ValueError("ModelActionRequest authority must be harness.loop.model_action_request")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["task_contract_seed"] = dict(self.task_contract_seed or {})
        payload["tool_call"] = dict(self.tool_call or {})
        payload["public_action_state"] = dict(self.public_action_state or {})
        payload["completion_contract"] = dict(self.completion_contract or {})
        payload["permission_request"] = dict(self.permission_request or {})
        payload["active_work_control"] = dict(self.active_work_control or {})
        payload["recovery_resume"] = dict(self.recovery_resume or {})
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
    public_response_required: bool = False,
    allowed_action_types: tuple[str, ...] | set[str] | None = None,
) -> tuple[ModelActionRequest | None, dict[str, Any]]:
    raw = dict(payload or {})
    errors: list[str] = []
    authority = str(raw.get("authority") or "harness.loop.model_action_request").strip()
    if authority != "harness.loop.model_action_request":
        errors.append("invalid_authority")
    action_type = str(raw.get("action_type") or "").strip()
    if action_type not in {"respond", "ask_user", "tool_call", "request_task_run", "active_work_control", "resume_recoverable_work", "block"}:
        errors.append(f"action_type_unsupported:{action_type}")
    allowed = {str(item) for item in list(allowed_action_types or ()) if str(item)}
    if allowed and action_type and action_type not in allowed:
        errors.append(f"action_type_not_allowed_for_context:{action_type}")
    raw_turn_id = str(raw.get("turn_id") or turn_id).strip()
    if raw_turn_id != str(turn_id or "").strip():
        errors.append("turn_id_mismatch")
    request_id = str(raw.get("request_id") or f"model-action:{turn_id}:1")
    tool_call = raw.get("tool_call") or {}
    raw_selected_skill_ids = _string_tuple(raw.get("selected_skill_ids"))
    task_contract_seed = raw.get("task_contract_seed") or {}
    completion_contract = raw.get("completion_contract") or {}
    permission_request = raw.get("permission_request") or {}
    active_work_control = raw.get("active_work_control") or {}
    recovery_resume = raw.get("recovery_resume") or {}
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
    if not isinstance(active_work_control, dict):
        errors.append("active_work_control_must_be_object")
        active_work_control = {}
    if not isinstance(recovery_resume, dict):
        errors.append("recovery_resume_must_be_object")
        recovery_resume = {}
    selected_skill_ids = raw_selected_skill_ids
    if action_type == "request_task_run" and isinstance(task_contract_seed, dict):
        normalized_seed, seed_errors, seed_gaps, canonical_selected_skill_ids = _normalize_task_contract_seed(task_contract_seed)
        if raw_selected_skill_ids:
            seed_errors.append("selected_skill_ids_not_allowed_for_request_task_run")
        seed_errors.extend(
            _request_task_run_contract_boundary_errors(
                raw=raw,
                task_contract_seed=normalized_seed,
                completion_contract=completion_contract,
            )
        )
        task_contract_seed = normalized_seed
        selected_skill_ids = canonical_selected_skill_ids
        errors.extend(seed_errors)
        contract_gaps: list[str] = list(seed_gaps)
    else:
        contract_gaps = []
    final_answer = str(raw.get("final_answer") or "").strip()
    user_question = str(raw.get("user_question") or "").strip()
    blocking_reason = str(raw.get("blocking_reason") or "").strip()
    public_progress_note = _public_progress_note(raw.get("public_progress_note"))
    public_action_state = _public_action_state(raw.get("public_action_state"))
    has_model_public_response = _has_model_public_response(
        action_type=action_type,
        public_progress_note=public_progress_note,
        public_action_state=public_action_state,
        final_answer=final_answer,
        user_question=user_question,
        blocking_reason=blocking_reason,
    )
    if _public_feedback_claims_task_lifecycle(
        public_progress_note=public_progress_note,
        public_action_state=public_action_state,
    ) and action_type != "request_task_run":
        errors.append("public_task_lifecycle_claim_requires_request_task_run")
    if public_response_required and not has_model_public_response:
        errors.append("public_response_required")
    if require_public_progress_note and not public_progress_note:
        if not public_response_required:
            if action_type == "tool_call" or not has_model_public_response:
                contract_gaps.append(
                    "public_progress_note_missing_for_tool_call"
                    if action_type == "tool_call"
                    else "public_progress_note_missing"
                )
        else:
            errors.append("public_progress_note_required")
    if require_public_action_state and not _has_public_action_state(public_action_state):
        if not public_response_required:
            contract_gaps.append(
                "public_action_state_missing_for_tool_call"
                if action_type == "tool_call"
                else "public_action_state_missing"
            )
        else:
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
        tool_call = _ensure_tool_call_id(dict(tool_call), request_id=request_id)
    if action_type == "request_task_run" and not task_contract_seed:
        errors.append("task_contract_seed_required_for_request_task_run")
    if action_type == "request_task_run":
        if not public_progress_note:
            errors.append("public_progress_note_required_for_request_task_run")
        if not _has_public_action_state(public_action_state):
            errors.append("public_action_state_required_for_request_task_run")
        if _has_non_empty_value(tool_call):
            errors.append("tool_call_not_allowed_for_request_task_run")
    if action_type == "active_work_control":
        from harness.loop.active_work import active_work_action_from_payload, active_work_action_is_allowed

        raw_action = str(dict(active_work_control).get("action") or "").strip()
        action = active_work_action_from_payload({"action": raw_action})
        if not action:
            errors.append("active_work_action_required")
        elif action != raw_action:
            errors.append("active_work_action_must_be_canonical")
        elif not active_work_action_is_allowed(action):
            errors.append("active_work_action_not_allowed")
    if action_type == "resume_recoverable_work":
        resume_payload = dict(recovery_resume or {})
        if not str(resume_payload.get("task_run_id") or "").strip():
            errors.append("recovery_resume.task_run_id_required")
        if not str(resume_payload.get("continuation_id") or "").strip():
            errors.append("recovery_resume.continuation_id_required")
    if errors:
        return None, {
            "status": "invalid",
            "validation_errors": errors,
            "authority": "harness.loop.model_action_protocol",
        }
    normalized_diagnostics = dict(raw.get("diagnostics") or {})
    if contract_gaps:
        normalized_diagnostics["contract_gaps"] = [
            *list(normalized_diagnostics.get("contract_gaps") or []),
            *contract_gaps,
        ]
    return ModelActionRequest(
        request_id=request_id,
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
        active_work_control=dict(active_work_control),
        recovery_resume=dict(recovery_resume),
        diagnostics=normalized_diagnostics,
    ), {
        "status": "accepted",
        "validation_errors": [],
        "contract_gaps": contract_gaps,
        "authority": "harness.loop.model_action_protocol",
    }


_TASK_EXECUTION_CROSS_CONTEXT_FIELDS = (
    "selected_skill_ids",
    "task_contract_seed",
    "completion_contract",
    "permission_request",
    "engagement_request",
    "active_work_control",
    "recovery_resume",
    "plan_id",
)


def task_execution_action_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    turn_id: str,
    require_public_progress_note: bool = True,
    require_public_action_state: bool = True,
    public_response_required: bool = False,
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
        public_response_required=public_response_required,
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
        "contract_gaps": list(dict(action_request.diagnostics or {}).get("contract_gaps") or []),
        "authority": "harness.loop.model_action_protocol",
    }


def _public_progress_note(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    return text[:160].rstrip()


_CANONICAL_HANDOFF_REQUIRED_OBJECTS = (
    "working_scope",
)
_REQUEST_TASK_RUN_SYSTEM_SETTING_FIELDS = (
    "capability_intent",
    "skill_intent",
    "observation_contract",
)
_REQUEST_TASK_RUN_SEED_TEXT_FIELDS = ("user_visible_goal", "task_run_goal")
_REQUEST_TASK_RUN_SEED_COMPLETION_FIELDS = (
    "completion_criteria",
    "required_artifacts",
    "artifact_requirements",
    "required_verifications",
    "verification_requirements",
)
_REQUEST_TASK_RUN_SEED_LAYER_FIELDS = (
    "goal_contract",
    "plan_contract",
    "lifecycle_contract",
    "environment_contract",
    "feedback_contract",
    "acceptance_contract",
)
_REQUEST_TASK_RUN_TOP_LEVEL_CONTRACT_FIELDS = (
    *_REQUEST_TASK_RUN_SEED_TEXT_FIELDS,
    *_REQUEST_TASK_RUN_SEED_COMPLETION_FIELDS,
    *_CANONICAL_HANDOFF_REQUIRED_OBJECTS,
    *_REQUEST_TASK_RUN_SEED_LAYER_FIELDS,
)


def _normalize_task_contract_seed(seed: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str], tuple[str, ...]]:
    payload, layer_errors = _seed_with_layered_contract_aliases(dict(seed or {}))
    errors: list[str] = []
    errors.extend(layer_errors)
    gaps: list[str] = []
    for legacy_key in ("resource_contract", "resource_requirements", "selected_skill_ids"):
        if _has_non_empty_value(payload.get(legacy_key)):
            errors.append(f"legacy_task_contract_field_not_allowed:{legacy_key}")
        payload.pop(legacy_key, None)
    for key in _REQUEST_TASK_RUN_SYSTEM_SETTING_FIELDS:
        if _has_non_empty_value(payload.get(key)):
            errors.append(f"system_execution_field_not_allowed_in_task_contract:{key}")
        payload.pop(key, None)
    for key in _CANONICAL_HANDOFF_REQUIRED_OBJECTS:
        if key not in payload:
            errors.append(f"{key}_required_for_request_task_run")
            payload[key] = {}
        elif not isinstance(payload.get(key), dict):
            errors.append(f"{key}_must_be_object")
            payload[key] = {}
    working_scope = _normalize_working_scope(dict(payload.get("working_scope") or {}))
    payload["working_scope"] = working_scope
    payload["goal_contract"] = _normalized_goal_contract(payload)
    payload["plan_contract"] = _normalized_plan_contract(payload)
    payload["lifecycle_contract"] = _normalized_lifecycle_contract(payload)
    payload["environment_contract"] = _normalized_environment_contract(payload)
    payload["feedback_contract"] = _normalized_feedback_contract(payload)
    payload["acceptance_contract"] = _normalized_acceptance_contract(payload)
    return payload, errors, gaps, ()


def _seed_with_layered_contract_aliases(seed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    payload = dict(seed or {})
    errors: list[str] = []
    layers: dict[str, dict[str, Any]] = {}
    for key in _REQUEST_TASK_RUN_SEED_LAYER_FIELDS:
        value = payload.get(key)
        if value is None:
            layers[key] = {}
            continue
        if not isinstance(value, dict):
            errors.append(f"{key}_must_be_object")
            payload[key] = {}
            layers[key] = {}
            continue
        layers[key] = dict(value)

    goal = layers["goal_contract"]
    if "user_visible_goal" not in payload and _has_non_empty_value(goal.get("user_visible_goal")):
        payload["user_visible_goal"] = goal.get("user_visible_goal")
    if "task_run_goal" not in payload:
        task_goal = goal.get("task_run_goal") or goal.get("agent_goal")
        if _has_non_empty_value(task_goal):
            payload["task_run_goal"] = task_goal

    environment = layers["environment_contract"]
    for key in ("working_scope", "permission_requirements"):
        if key not in payload and isinstance(environment.get(key), dict):
            payload[key] = dict(environment.get(key) or {})
    for key in ("capability_intent", "skill_intent"):
        if _has_non_empty_value(environment.get(key)):
            errors.append(f"system_execution_field_not_allowed_in_task_contract:environment_contract.{key}")

    feedback = layers["feedback_contract"]
    for key in ("observation_policy", "observation_contract"):
        if _has_non_empty_value(feedback.get(key)):
            errors.append(f"system_execution_field_not_allowed_in_task_contract:feedback_contract.{key}")

    acceptance = layers["acceptance_contract"]
    for key in _REQUEST_TASK_RUN_SEED_COMPLETION_FIELDS:
        if key not in payload and _has_non_empty_value(acceptance.get(key)):
            payload[key] = acceptance.get(key)

    plan = layers["plan_contract"]
    if "plan_ref" not in payload and _has_non_empty_value(plan.get("plan_id")):
        payload["plan_ref"] = plan.get("plan_id")
    return payload, errors


def _normalized_goal_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("goal_contract") or {})
    payload = {
        "user_visible_goal": str(seed.get("user_visible_goal") or raw.get("user_visible_goal") or "").strip(),
        "task_run_goal": str(seed.get("task_run_goal") or raw.get("task_run_goal") or raw.get("agent_goal") or "").strip(),
        "non_goals": list(_string_tuple(raw.get("non_goals") or seed.get("non_goals"))),
        "success_definition": _public_progress_note(raw.get("success_definition") or seed.get("success_definition")),
        "completion_evidence": list(_string_tuple(raw.get("completion_evidence") or seed.get("completion_evidence"))),
        "authority": "harness.loop.model_action_protocol.goal_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _normalized_plan_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("plan_contract") or {})
    payload = {
        "plan_id": str(raw.get("plan_id") or seed.get("plan_ref") or seed.get("external_plan_ref") or "").strip(),
        "plan_version": str(raw.get("plan_version") or "").strip(),
        "plan_status": str(raw.get("plan_status") or raw.get("approval_state") or "agent_managed").strip(),
        "strategy_summary": _public_progress_note(raw.get("strategy_summary")),
        "major_steps": list(_string_tuple(raw.get("major_steps") or raw.get("steps"))),
        "allowed_plan_operations": list(_string_tuple(raw.get("allowed_plan_operations") or raw.get("allowed_operations"))),
        "replan_policy": dict(raw.get("replan_policy") or {}) if isinstance(raw.get("replan_policy"), dict) else {},
        "authority": "harness.loop.model_action_protocol.plan_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _normalized_lifecycle_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("lifecycle_contract") or {})
    payload = {
        "pause_policy": dict(raw.get("pause_policy") or {}) if isinstance(raw.get("pause_policy"), dict) else {},
        "resume_policy": dict(raw.get("resume_policy") or {}) if isinstance(raw.get("resume_policy"), dict) else {},
        "stop_policy": dict(raw.get("stop_policy") or {}) if isinstance(raw.get("stop_policy"), dict) else {},
        "replan_policy": dict(raw.get("replan_policy") or {}) if isinstance(raw.get("replan_policy"), dict) else {},
        "tool_limit_closeout_policy": dict(raw.get("tool_limit_closeout_policy") or {}) if isinstance(raw.get("tool_limit_closeout_policy"), dict) else {},
        "failure_recovery_policy": dict(raw.get("failure_recovery_policy") or seed.get("recovery_policy") or {}) if isinstance(raw.get("failure_recovery_policy") or seed.get("recovery_policy"), dict) else {},
        "terminal_policy": dict(raw.get("terminal_policy") or {}) if isinstance(raw.get("terminal_policy"), dict) else {},
        "authority": "harness.loop.model_action_protocol.lifecycle_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _normalized_environment_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("environment_contract") or {})
    payload = {
        "working_scope": dict(seed.get("working_scope") or raw.get("working_scope") or {}),
        "permission_requirements": dict(seed.get("permission_requirements") or raw.get("permission_requirements") or {}),
        "resource_requirements": dict(raw.get("resource_requirements") or {}),
        "safety_boundaries": list(_string_tuple(raw.get("safety_boundaries") or seed.get("safety_boundaries"))),
        "authority": "harness.loop.model_action_protocol.environment_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _normalized_feedback_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("feedback_contract") or {})
    payload = {
        "feedback_sources": list(
            _string_tuple(
                raw.get("feedback_sources")
                or ("tool_observation", "runtime_observation", "user_steer", "lifecycle_signal", "budget_signal", "verification_signal", "recovery_signal")
            )
        ),
        "dynamic_context_slots": list(_string_tuple(raw.get("dynamic_context_slots") or ("dynamic_runtime_context", "task_plan_context", "tail_user_steer"))),
        "steer_policy": dict(raw.get("steer_policy") or {}) if isinstance(raw.get("steer_policy"), dict) else {},
        "verification_feedback_policy": dict(raw.get("verification_feedback_policy") or {}) if isinstance(raw.get("verification_feedback_policy"), dict) else {},
        "budget_feedback_policy": dict(raw.get("budget_feedback_policy") or {}) if isinstance(raw.get("budget_feedback_policy"), dict) else {},
        "feedback_identity_binding": str(raw.get("feedback_identity_binding") or "active_turn_or_task_run_required").strip(),
        "authority": "harness.loop.model_action_protocol.feedback_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _normalized_acceptance_contract(seed: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("acceptance_contract") or {})
    payload = {
        "completion_criteria": list(_string_tuple(seed.get("completion_criteria") or raw.get("completion_criteria"))),
        "required_artifacts": _dict_list(seed.get("required_artifacts") or seed.get("artifact_requirements") or raw.get("required_artifacts") or raw.get("artifact_requirements")),
        "required_verifications": _dict_list(seed.get("required_verifications") or seed.get("verification_requirements") or raw.get("required_verifications") or raw.get("verification_requirements")),
        "verification_gate": dict(raw.get("verification_gate") or {}) if isinstance(raw.get("verification_gate"), dict) else {},
        "final_answer_requirements": list(_string_tuple(raw.get("final_answer_requirements"))),
        "evidence_refs_required": bool(raw.get("evidence_refs_required") is not False),
        "authority": "harness.loop.model_action_protocol.acceptance_contract",
    }
    return {key: value for key, value in payload.items() if value not in ("", [], {}, None)}


def _request_task_run_contract_boundary_errors(
    *,
    raw: dict[str, Any],
    task_contract_seed: dict[str, Any],
    completion_contract: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in _REQUEST_TASK_RUN_TOP_LEVEL_CONTRACT_FIELDS:
        if _has_non_empty_value(raw.get(field)):
            errors.append(f"field_must_be_inside_task_contract_seed:{field}")
    for field in _REQUEST_TASK_RUN_SYSTEM_SETTING_FIELDS:
        if _has_non_empty_value(raw.get(field)):
            errors.append(f"system_execution_field_not_allowed_in_task_contract:{field}")
    if isinstance(raw.get("payload"), dict):
        errors.append("payload_wrapper_not_allowed_for_request_task_run")
    for field in _REQUEST_TASK_RUN_SEED_TEXT_FIELDS:
        if not str(task_contract_seed.get(field) or "").strip():
            errors.append(f"{field}_required_for_request_task_run")
    working_scope = task_contract_seed.get("working_scope")
    target_objects = dict(working_scope or {}).get("target_objects") if isinstance(working_scope, dict) else ()
    if not isinstance(working_scope, dict) or not list(_dict_or_string_items(target_objects)):
        errors.append("working_scope.target_objects_required_for_request_task_run")
    if not _has_request_task_run_completion_evidence(
        task_contract_seed=task_contract_seed,
        completion_contract=completion_contract,
    ):
        errors.append("completion_evidence_required_for_request_task_run")
    return errors


def _has_request_task_run_completion_evidence(
    *,
    task_contract_seed: dict[str, Any],
    completion_contract: dict[str, Any],
) -> bool:
    return any(
        _has_non_empty_value(value)
        for value in (
            task_contract_seed.get("completion_criteria"),
            task_contract_seed.get("required_artifacts"),
            task_contract_seed.get("artifact_requirements"),
            task_contract_seed.get("required_verifications"),
            task_contract_seed.get("verification_requirements"),
            completion_contract.get("completion_criteria"),
            completion_contract.get("artifact_requirements"),
            completion_contract.get("required_verifications"),
        )
    )


def _normalize_working_scope(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_objects": list(_dict_or_string_items(value.get("target_objects"))),
        "workspace_refs": list(_string_tuple(value.get("workspace_refs"))),
        "source_refs": list(_string_tuple(value.get("source_refs"))),
        "excluded_scope": list(_string_tuple(value.get("excluded_scope"))),
        "known_constraints": list(_string_tuple(value.get("known_constraints"))),
    }


def _dict_or_string_items(value: Any) -> tuple[Any, ...]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    result: list[Any] = []
    for item in raw_values:
        if isinstance(item, dict):
            cleaned = {str(key): val for key, val in item.items() if str(key).strip() and val not in (None, "", [], {})}
            if cleaned:
                result.append(cleaned)
            continue
        text = str(item or "").strip()
        if text:
            result.append(text)
    return tuple(result)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    raw_values = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    return [dict(item) for item in raw_values if isinstance(item, dict)]


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


def _has_model_public_response(
    *,
    action_type: str,
    public_progress_note: str,
    public_action_state: dict[str, Any],
    final_answer: str,
    user_question: str,
    blocking_reason: str,
) -> bool:
    if public_progress_note:
        return True
    if str(dict(public_action_state or {}).get("current_judgment") or "").strip():
        return True
    if action_type == "respond":
        return bool(str(final_answer or "").strip())
    if action_type == "ask_user":
        return bool(str(user_question or "").strip())
    if action_type == "block":
        return bool(str(blocking_reason or "").strip())
    return False


_TASK_LIFECYCLE_CLAIM_PHRASES = (
    "我会开启长任务",
    "我要开启长任务",
    "我将开启长任务",
    "让我开启长任务",
    "准备开启长任务",
    "开始一个长任务",
    "开启一个长任务",
    "启动长任务",
    "进入长任务",
    "我会开启一个长任务",
    "我要开启一个长任务",
    "我将开启一个长任务",
    "让我开启一个长任务",
    "准备开启一个长任务",
    "我会申请进入持续任务",
    "我要申请进入持续任务",
    "我将申请进入持续任务",
    "申请进入持续任务",
    "进入持续任务生命周期",
    "启动持续任务生命周期",
    "开启持续任务生命周期",
    "创建持续任务",
    "创建 task",
    "start task",
    "start a task",
    "create task",
    "create a task",
    "request task run",
)


def _public_feedback_claims_task_lifecycle(
    *,
    public_progress_note: str,
    public_action_state: dict[str, Any],
) -> bool:
    texts = [
        public_progress_note,
        str(dict(public_action_state or {}).get("current_judgment") or ""),
        str(dict(public_action_state or {}).get("next_action") or ""),
    ]
    normalized = " ".join(" ".join(str(text or "").split()).lower() for text in texts if str(text or "").strip())
    if not normalized:
        return False
    if any(phrase in normalized for phrase in ("不进入持续任务", "不开启长任务", "不启动长任务", "不创建 task")):
        return False
    return any(phrase.lower() in normalized for phrase in _TASK_LIFECYCLE_CLAIM_PHRASES)


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
    elif isinstance(raw_tool_call, dict):
        calls = [dict(raw_tool_call)]
    elif _has_non_empty_value(raw_tool_call):
        errors.append("tool_call_must_be_object")
        calls = []
    else:
        calls = []
    normalized: list[dict[str, Any]] = []
    request_id = str(raw.get("request_id") or "task-model-action").strip()
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
        payload = _ensure_tool_call_id(payload, request_id=request_id, ordinal=index)
        normalized.append(payload)
    if not normalized:
        errors.append("tool_calls_required_for_tool_call")
    return tuple(normalized), errors
