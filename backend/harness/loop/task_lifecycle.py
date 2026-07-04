from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from harness.task_run_contract_normalization import contract_string_tuple

from .model_action_protocol import ModelActionRequest

@dataclass(frozen=True, slots=True)
class TaskRunContract:
    contract_id: str
    contract_source: str
    user_visible_goal: str = ""
    task_run_goal: str = ""
    container_contract: dict[str, Any] = field(default_factory=dict)
    work_modes: tuple[dict[str, Any], ...] = ()
    primary_work_mode_instance_id: str = ""
    active_work_mode_refs: tuple[str, ...] = ()
    required_artifacts: tuple[dict[str, Any], ...] = ()
    required_verifications: tuple[dict[str, Any], ...] = ()
    completion_criteria: tuple[str, ...] = ()
    working_scope: dict[str, Any] = field(default_factory=dict)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    permission_requirements: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    created_from_packet_ref: str = ""
    source_contract_ref: str = ""
    external_plan_ref: str = ""
    task_environment_id: str = ""
    runtime_profile: dict[str, Any] = field(default_factory=dict)
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    graph_slot: dict[str, Any] = field(default_factory=dict)
    origin: dict[str, Any] = field(default_factory=dict)
    goal_contract: dict[str, Any] = field(default_factory=dict)
    plan_contract: dict[str, Any] = field(default_factory=dict)
    lifecycle_contract: dict[str, Any] = field(default_factory=dict)
    environment_contract: dict[str, Any] = field(default_factory=dict)
    feedback_contract: dict[str, Any] = field(default_factory=dict)
    memory_contract: dict[str, Any] = field(default_factory=dict)
    acceptance_contract: dict[str, Any] = field(default_factory=dict)
    runtime_requirements: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.loop.task_run_contract"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.task_run_contract":
            raise ValueError("TaskRunContract authority must be harness.loop.task_run_contract")
        if not self.contract_id:
            raise ValueError("TaskRunContract requires contract_id")
        if not self.goal_contract:
            object.__setattr__(self, "goal_contract", _goal_contract_from_parts(self))
        if not self.plan_contract:
            object.__setattr__(self, "plan_contract", _plan_contract_from_parts(self))
        if not self.lifecycle_contract:
            object.__setattr__(self, "lifecycle_contract", _lifecycle_contract_from_parts(self))
        if not self.environment_contract:
            object.__setattr__(self, "environment_contract", _environment_contract_from_parts(self))
        if not self.feedback_contract:
            object.__setattr__(self, "feedback_contract", _feedback_contract_from_parts(self))
        if not self.acceptance_contract:
            object.__setattr__(self, "acceptance_contract", _acceptance_contract_from_parts(self))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_artifacts"] = [dict(item) for item in self.required_artifacts]
        payload["required_verifications"] = [dict(item) for item in self.required_verifications]
        payload["completion_criteria"] = list(self.completion_criteria)
        payload["work_modes"] = [dict(item) for item in self.work_modes]
        payload["active_work_mode_refs"] = list(self.active_work_mode_refs)
        payload["container_contract"] = dict(self.container_contract or {})
        payload["goal_contract"] = dict(self.goal_contract or {})
        payload["plan_contract"] = dict(self.plan_contract or {})
        payload["lifecycle_contract"] = dict(self.lifecycle_contract or {})
        payload["environment_contract"] = dict(self.environment_contract or {})
        payload["feedback_contract"] = dict(self.feedback_contract or {})
        payload["memory_contract"] = dict(self.memory_contract or {})
        payload["acceptance_contract"] = dict(self.acceptance_contract or {})
        payload["runtime_requirements"] = dict(self.runtime_requirements or {})
        return payload


def contract_from_action_request(
    action_request: ModelActionRequest,
    *,
    packet_ref: str,
    task_environment_id: str = "",
) -> tuple[TaskRunContract | None, list[str]]:
    seed = dict(getattr(action_request, "task_run_contract_seed", {}) or {})
    errors: list[str] = []
    errors.extend(_legacy_task_run_contract_seed_errors(seed))
    if _is_compact_task_start_intent(seed):
        seed = _compact_seed_to_task_run_contract_seed(seed)
    elif "container_contract" not in seed or "work_modes" not in seed:
        errors.append("task_run_contract_seed_requires_container_contract_and_work_modes_or_compact_task_start_intent")
    container_contract = dict(seed.get("container_contract") or {})
    work_modes = _dict_tuple(seed.get("work_modes"))
    primary_mode = _primary_work_mode(work_modes, container_contract=container_contract)
    if not primary_mode:
        errors.append("primary_work_mode_required")
    primary_mode_contract = dict(primary_mode.get("contract") or {}) if primary_mode else {}
    primary_work_mode_instance_id = str(primary_mode.get("mode_instance_id") or "") if primary_mode else ""
    user_visible_goal, task_run_goal = _derived_task_goal_from_modes(
        container_contract=container_contract,
        primary_mode=primary_mode,
        work_modes=work_modes,
    )
    acceptance_contract_seed = dict(seed.get("acceptance_contract") or {})
    criteria = _string_tuple(
        acceptance_contract_seed.get("completion_criteria")
        or seed.get("completion_criteria")
        or dict(action_request.completion_contract or {}).get("completion_criteria")
    )
    required_artifacts = _dict_tuple(
        seed.get("required_artifacts")
        or seed.get("artifact_requirements")
        or acceptance_contract_seed.get("required_artifacts")
        or acceptance_contract_seed.get("artifact_requirements")
        or dict(action_request.completion_contract or {}).get("artifact_requirements")
    )
    required_verifications = _dict_tuple(
        seed.get("required_verifications")
        or seed.get("verification_requirements")
        or acceptance_contract_seed.get("required_verifications")
        or acceptance_contract_seed.get("verification_requirements")
        or dict(action_request.completion_contract or {}).get("required_verifications")
    )
    acceptance_mode = str(acceptance_contract_seed.get("acceptance_mode") or "").strip()
    if acceptance_mode in {"strict", "best_effort"} and not criteria and not required_artifacts and not required_verifications:
        errors.append("completion_evidence_required")
    working_scope, canonical_errors = _canonical_handoff_fields(seed, primary_mode_contract=primary_mode_contract)
    errors.extend(canonical_errors)
    if errors:
        return None, errors
    runtime_requirements = dict(seed.get("runtime_requirements") or {})
    runtime_profile = _runtime_profile_with_execution_permit_allowed_operations({}, allowed_operations=None)
    permission_requirements = dict(
        runtime_requirements.get("permission_requirements") or action_request.permission_request or {}
    )
    source_contract_ref = str(seed.get("source_contract_ref") or seed.get("contract_ref") or container_contract.get("source_ref") or "").strip()
    external_plan_ref = str(_external_plan_ref_from_modes(work_modes) or seed.get("external_plan_ref") or seed.get("plan_ref") or "").strip()
    task_environment_ref = str(task_environment_id or "").strip()
    acceptance_policy = dict(seed.get("acceptance_policy") or {})
    recovery_policy = dict(seed.get("recovery_policy") or {})
    projection_seed = {
        **seed,
        "goal_contract": _goal_contract_seed_from_modes(
            work_modes,
            user_visible_goal=user_visible_goal,
            task_run_goal=task_run_goal,
        ),
        "plan_contract": _plan_contract_seed_from_modes(work_modes),
        "working_scope": working_scope,
    }
    contract_layers = _task_run_contract_layers(
        seed=projection_seed,
        user_visible_goal=user_visible_goal,
        task_run_goal=task_run_goal,
        completion_criteria=criteria,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        working_scope=working_scope,
        permission_requirements=permission_requirements,
        acceptance_policy=acceptance_policy,
        recovery_policy=recovery_policy,
        external_plan_ref=external_plan_ref,
        source_contract_ref=source_contract_ref,
        task_environment_id=task_environment_ref,
    )
    contract = TaskRunContract(
        contract_id=f"task-run-contract:{uuid.uuid4().hex[:12]}",
        contract_source="model_action_request",
        user_visible_goal=user_visible_goal,
        task_run_goal=task_run_goal,
        container_contract=container_contract,
        work_modes=work_modes,
        primary_work_mode_instance_id=primary_work_mode_instance_id,
        active_work_mode_refs=tuple(str(item.get("mode_instance_id") or "") for item in work_modes if str(item.get("mode_instance_id") or "").strip()),
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        completion_criteria=criteria,
        working_scope=working_scope,
        resource_requirements={},
        permission_requirements=permission_requirements,
        acceptance_policy=acceptance_policy,
        recovery_policy=recovery_policy,
        created_from_packet_ref=packet_ref,
        source_contract_ref=source_contract_ref,
        external_plan_ref=external_plan_ref,
        task_environment_id=task_environment_ref,
        runtime_profile=runtime_profile,
        prompt_contract=dict(seed.get("prompt_contract") or {}),
        graph_slot=dict(seed.get("graph_slot") or {}),
        origin=_task_lifecycle_origin(action_request=action_request, turn_id=action_request.turn_id),
        goal_contract=contract_layers["goal_contract"],
        plan_contract=contract_layers["plan_contract"],
        lifecycle_contract=contract_layers["lifecycle_contract"],
        environment_contract=contract_layers["environment_contract"],
        feedback_contract=contract_layers["feedback_contract"],
        memory_contract=dict(seed.get("memory_contract") or {}),
        acceptance_contract=contract_layers["acceptance_contract"],
        runtime_requirements=runtime_requirements,
    )
    return contract, []


def _legacy_task_run_contract_seed_errors(seed: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    payload = dict(seed or {})
    if _has_value(payload.get("contract_version")):
        errors.append("legacy_task_run_contract_field_not_allowed:contract_version")
    for key in ("goal_contract", "plan_contract", "environment_contract"):
        if _has_value(payload.get(key)):
            errors.append(f"legacy_task_run_contract_field_not_allowed:{key}")
    for key in ("user_visible_goal", "task_run_goal"):
        if _has_value(payload.get(key)):
            errors.append(f"legacy_task_run_contract_field_not_allowed:{key}")
    return errors


def _is_compact_task_start_intent(seed: dict[str, Any]) -> bool:
    payload = dict(seed or {})
    if str(payload.get("contract_shape") or "").strip() == "compact_task_start_intent":
        return True
    compact_keys = {
        "primary_mode",
        "task_shape",
        "minimum_viable_next_step",
        "working_scope",
        "acceptance",
        "mode_payload",
    }
    return bool(compact_keys.intersection(payload)) and not (
        "container_contract" in payload or "work_modes" in payload
    )


def _compact_seed_to_task_run_contract_seed(seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(seed or {})
    primary_kind = str(payload.get("primary_mode") or "plan").strip()
    if primary_kind not in {"goal", "plan"}:
        primary_kind = "plan"
    task_shape = str(payload.get("task_shape") or "standard").strip() or "standard"
    minimum_next_step = _first_text(
        payload.get("minimum_viable_next_step"),
        "推进当前 primary Work Mode 的下一步。",
    )
    working_scope = dict(payload.get("working_scope") or {}) if isinstance(payload.get("working_scope"), dict) else {}
    mode_payload = dict(payload.get("mode_payload") or {}) if isinstance(payload.get("mode_payload"), dict) else {}
    summary = _first_text(mode_payload.get("summary"), minimum_next_step)
    steps = list(_string_tuple(mode_payload.get("steps"))) or [minimum_next_step]
    if primary_kind == "goal":
        primary_contract = {
            "user_visible_goal": summary,
            "task_run_goal": summary,
            "success_definition": _first_text(mode_payload.get("success_definition"), summary),
            "completion_evidence": list(_string_tuple(mode_payload.get("notes"))),
            "working_scope": working_scope,
        }
    else:
        primary_contract = {
            "strategy_summary": summary,
            "major_steps": steps,
            "plan_status": "agent_managed",
            "replan_policy": {},
            "working_scope": working_scope,
        }
    primary_ref = f"work-mode:{primary_kind}:primary"
    acceptance = dict(payload.get("acceptance") or {}) if isinstance(payload.get("acceptance"), dict) else {}
    return {
        "contract_id": "task_run_contract",
        "container_contract": {
            "entry_reason": summary,
            "task_shape": task_shape,
            "continuity_required": True,
            "control_required": True,
            "projection_required": True,
            "checkpoint_required": True,
            "minimum_viable_next_step": minimum_next_step,
            "primary_work_mode_ref": primary_ref,
            "supporting_mode_refs": [],
            "mode_transition_policy": {
                "agent_may_propose_transition": True,
                "system_may_infer_transition": False,
                "requires_accepted_event": True,
            },
        },
        "work_modes": [
            {
                "mode_instance_id": primary_ref,
                "mode_kind": primary_kind,
                "mode_role": "primary",
                "status": "draft",
                "depends_on_mode_refs": [],
                "contract": primary_contract,
                "task_shape": task_shape,
            }
        ],
        "lifecycle_contract": {},
        "feedback_contract": {},
        "memory_contract": {},
        "acceptance_contract": {
            "acceptance_mode": str(acceptance.get("mode") or "checkpoint").strip() or "checkpoint",
            "completion_criteria": list(_string_tuple(acceptance.get("criteria"))),
            "final_answer_requirements": list(_string_tuple(acceptance.get("final_answer_requirements"))),
        },
        "runtime_requirements": {
            "permission_requirements": {},
            "resource_requirements": {},
            "safety_boundaries": list(_string_tuple(payload.get("safety_boundaries"))),
        },
    }


def _primary_work_mode(work_modes: tuple[dict[str, Any], ...], *, container_contract: dict[str, Any]) -> dict[str, Any]:
    primary_ref = str(container_contract.get("primary_work_mode_ref") or "").strip()
    for item in work_modes:
        if primary_ref and str(item.get("mode_instance_id") or "") == primary_ref:
            return dict(item)
    for item in work_modes:
        if str(item.get("mode_role") or "") == "primary":
            return dict(item)
    return {}


def _derived_task_goal_from_modes(
    *,
    container_contract: dict[str, Any],
    primary_mode: dict[str, Any],
    work_modes: tuple[dict[str, Any], ...],
) -> tuple[str, str]:
    primary_contract = dict(primary_mode.get("contract") or {})
    mode_kind = str(primary_mode.get("mode_kind") or "").strip()
    goal_mode = _first_mode(work_modes, "goal")
    goal_contract = dict(goal_mode.get("contract") or {}) if goal_mode else {}
    plan_mode = _first_mode(work_modes, "plan")
    plan_contract = dict(plan_mode.get("contract") or {}) if plan_mode else {}
    todo_mode = _first_mode(work_modes, "todo")
    todo_contract = dict(todo_mode.get("contract") or {}) if todo_mode else {}
    first_todo = _first_todo_title(todo_contract)
    user_visible = _first_text(
        goal_contract.get("user_visible_goal"),
        primary_contract.get("user_visible_goal"),
        primary_contract.get("success_definition"),
        plan_contract.get("strategy_summary"),
        primary_contract.get("strategy_summary"),
        first_todo,
        container_contract.get("entry_reason"),
        f"{mode_kind or 'open_work'} task",
    )
    task_goal = _first_text(
        goal_contract.get("task_run_goal"),
        primary_contract.get("task_run_goal"),
        goal_contract.get("user_visible_goal"),
        primary_contract.get("success_definition"),
        plan_contract.get("strategy_summary"),
        primary_contract.get("strategy_summary"),
        container_contract.get("minimum_viable_next_step"),
        user_visible,
    )
    return user_visible, task_goal


def _first_mode(work_modes: tuple[dict[str, Any], ...], mode_kind: str) -> dict[str, Any]:
    for item in work_modes:
        if str(item.get("mode_kind") or "") == mode_kind:
            return dict(item)
    return {}


def _first_todo_title(todo_contract: dict[str, Any]) -> str:
    for item in list(todo_contract.get("items") or []):
        if not isinstance(item, dict):
            continue
        title = _first_text(item.get("title"), item.get("content"), item.get("summary"))
        if title:
            return title
    return ""


def _goal_contract_seed_from_modes(
    work_modes: tuple[dict[str, Any], ...],
    *,
    user_visible_goal: str,
    task_run_goal: str,
) -> dict[str, Any]:
    goal_mode = _first_mode(work_modes, "goal")
    raw = dict(goal_mode.get("contract") or {}) if goal_mode else {}
    return {
        **raw,
        "user_visible_goal": _first_text(raw.get("user_visible_goal"), user_visible_goal),
        "task_run_goal": _first_text(raw.get("task_run_goal"), raw.get("agent_goal"), task_run_goal),
    }


def _plan_contract_seed_from_modes(work_modes: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    plan_mode = _first_mode(work_modes, "plan")
    raw = dict(plan_mode.get("contract") or {}) if plan_mode else {}
    external_plan_ref = raw.get("external_plan_ref")
    plan_ref = external_plan_ref if isinstance(external_plan_ref, str) else ""
    return {
        "plan_id": _first_text(raw.get("plan_id"), plan_ref, "plan:agent-managed"),
        "plan_version": _first_text(raw.get("plan_version"), "initial"),
        "plan_status": _first_text(raw.get("plan_status"), "agent_managed"),
        "strategy_summary": _first_text(raw.get("strategy_summary"), "Agent manages the task strategy; todo is only the execution cursor."),
        "major_steps": list(_string_tuple(raw.get("major_steps") or raw.get("steps"))),
        "allowed_plan_operations": list(_string_tuple(raw.get("allowed_plan_operations") or raw.get("allowed_operations"))),
        "replan_policy": dict(raw.get("replan_policy") or {}),
    }


def _external_plan_ref_from_modes(work_modes: tuple[dict[str, Any], ...]) -> str:
    raw = dict(_first_mode(work_modes, "plan").get("contract") or {})
    value = raw.get("external_plan_ref")
    if isinstance(value, dict):
        return _first_text(value.get("ref"), value.get("id"))
    return _first_text(value, raw.get("plan_id"))


def _task_run_contract_layers(
    *,
    seed: dict[str, Any],
    user_visible_goal: str,
    task_run_goal: str,
    completion_criteria: tuple[str, ...],
    required_artifacts: tuple[dict[str, Any], ...],
    required_verifications: tuple[dict[str, Any], ...],
    working_scope: dict[str, Any],
    permission_requirements: dict[str, Any],
    acceptance_policy: dict[str, Any],
    recovery_policy: dict[str, Any],
    external_plan_ref: str,
    source_contract_ref: str,
    task_environment_id: str,
) -> dict[str, dict[str, Any]]:
    goal_contract = _goal_contract_from_seed(
        seed,
        user_visible_goal=user_visible_goal,
        task_run_goal=task_run_goal,
        completion_criteria=completion_criteria,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
    )
    acceptance_contract = _acceptance_contract_from_seed(
        seed,
        completion_criteria=completion_criteria,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        acceptance_policy=acceptance_policy,
    )
    plan_contract = _plan_contract_from_seed(
        seed,
        completion_criteria=completion_criteria,
        external_plan_ref=external_plan_ref,
        source_contract_ref=source_contract_ref,
    )
    lifecycle_contract = _lifecycle_contract_from_seed(seed, recovery_policy=recovery_policy)
    environment_contract = _environment_contract_from_seed(
        seed,
        working_scope=working_scope,
        permission_requirements=permission_requirements,
        task_environment_id=task_environment_id,
    )
    feedback_contract = _feedback_contract_from_seed(
        seed,
        acceptance_contract=acceptance_contract,
    )
    return {
        "goal_contract": goal_contract,
        "plan_contract": plan_contract,
        "lifecycle_contract": lifecycle_contract,
        "environment_contract": environment_contract,
        "feedback_contract": feedback_contract,
        "acceptance_contract": acceptance_contract,
    }


def _goal_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _goal_contract_from_seed(
        {},
        user_visible_goal=contract.user_visible_goal,
        task_run_goal=contract.task_run_goal,
        completion_criteria=contract.completion_criteria,
        required_artifacts=contract.required_artifacts,
        required_verifications=contract.required_verifications,
    )


def _plan_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _plan_contract_from_seed(
        {},
        completion_criteria=contract.completion_criteria,
        external_plan_ref=contract.external_plan_ref,
        source_contract_ref=contract.source_contract_ref,
    )


def _lifecycle_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _lifecycle_contract_from_seed({}, recovery_policy=contract.recovery_policy)


def _environment_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _environment_contract_from_seed(
        {},
        working_scope=contract.working_scope,
        permission_requirements=contract.permission_requirements,
        task_environment_id=contract.task_environment_id,
    )


def _feedback_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _feedback_contract_from_seed(
        {},
        acceptance_contract=_acceptance_contract_from_parts(contract),
    )


def _acceptance_contract_from_parts(contract: TaskRunContract) -> dict[str, Any]:
    return _acceptance_contract_from_seed(
        {},
        completion_criteria=contract.completion_criteria,
        required_artifacts=contract.required_artifacts,
        required_verifications=contract.required_verifications,
        acceptance_policy=contract.acceptance_policy,
    )


def _goal_contract_from_seed(
    seed: dict[str, Any],
    *,
    user_visible_goal: str,
    task_run_goal: str,
    completion_criteria: tuple[str, ...],
    required_artifacts: tuple[dict[str, Any], ...],
    required_verifications: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    raw = dict(seed.get("goal_contract") or {}) if isinstance(seed.get("goal_contract"), dict) else {}
    return _drop_empty_payload(
        {
            "user_visible_goal": user_visible_goal,
            "task_run_goal": task_run_goal,
            "agent_goal": task_run_goal,
            "non_goals": list(_string_tuple(raw.get("non_goals") or seed.get("non_goals"))),
            "success_definition": _first_text(raw.get("success_definition"), seed.get("success_definition")),
            "completion_evidence": list(_string_tuple(raw.get("completion_evidence") or seed.get("completion_evidence")))
            or _completion_evidence_descriptors(
                completion_criteria=completion_criteria,
                required_artifacts=required_artifacts,
                required_verifications=required_verifications,
            ),
            "authority": "harness.loop.task_run_contract.goal_contract",
        }
    )


def _plan_contract_from_seed(
    seed: dict[str, Any],
    *,
    completion_criteria: tuple[str, ...],
    external_plan_ref: str,
    source_contract_ref: str,
) -> dict[str, Any]:
    raw = dict(seed.get("plan_contract") or {}) if isinstance(seed.get("plan_contract"), dict) else {}
    plan_id = _first_text(raw.get("plan_id"), external_plan_ref, seed.get("plan_ref"), source_contract_ref, "plan:agent-managed")
    major_steps = list(_string_tuple(raw.get("major_steps") or raw.get("steps"))) or [
        str(item) for item in completion_criteria[:8] if str(item).strip()
    ]
    return _drop_empty_payload(
        {
            "plan_id": plan_id,
            "plan_version": _first_text(raw.get("plan_version"), "initial"),
            "plan_status": _first_text(raw.get("plan_status"), raw.get("approval_state"), "agent_managed"),
            "strategy_summary": _first_text(
                raw.get("strategy_summary"),
                "Agent maintains the strategy, updates todo as an execution cursor, and replans when evidence changes.",
            ),
            "major_steps": major_steps,
            "decision_points": list(_string_tuple(raw.get("decision_points"))),
            "allowed_plan_operations": list(_string_tuple(raw.get("allowed_plan_operations") or raw.get("allowed_operations")))
            or ["create", "update", "replan", "explain_deviation"],
            "replan_policy": dict(raw.get("replan_policy") or {"requires_reason": True, "version_must_change_or_reason_required": True}),
            "authority": "harness.loop.task_run_contract.plan_contract",
        }
    )


def _lifecycle_contract_from_seed(seed: dict[str, Any], *, recovery_policy: dict[str, Any]) -> dict[str, Any]:
    raw = dict(seed.get("lifecycle_contract") or {}) if isinstance(seed.get("lifecycle_contract"), dict) else {}
    return _drop_empty_payload(
        {
            "allowed_states": list(_string_tuple(raw.get("allowed_states")))
            or ["created", "admitted", "running", "waiting_executor", "waiting_approval", "completed", "failed", "blocked", "aborted"],
            "pause_policy": dict(raw.get("pause_policy") or {"allowed": True, "requires_reason": True}),
            "resume_policy": dict(raw.get("resume_policy") or {"allowed": True, "requires_same_task_identity": True}),
            "stop_policy": dict(raw.get("stop_policy") or {"allowed": True, "terminal_reason_required": True}),
            "replan_policy": dict(raw.get("replan_policy") or {"allowed": True, "main_agent_owns_replan": True}),
            "tool_limit_closeout_policy": dict(raw.get("tool_limit_closeout_policy") or {"agent_closeout_required": True, "include_evidence_and_recovery_point": True}),
            "failure_recovery_policy": dict(raw.get("failure_recovery_policy") or recovery_policy or {"recoverable_errors_require_explicit_recovery_action": True}),
            "terminal_policy": dict(raw.get("terminal_policy") or {"completion_requires_acceptance_contract": True}),
            "authority": "harness.loop.task_run_contract.lifecycle_contract",
        }
    )


def _environment_contract_from_seed(
    seed: dict[str, Any],
    *,
    working_scope: dict[str, Any],
    permission_requirements: dict[str, Any],
    task_environment_id: str,
) -> dict[str, Any]:
    raw = dict(seed.get("environment_contract") or {}) if isinstance(seed.get("environment_contract"), dict) else {}
    return _drop_empty_payload(
        {
            "workspace_refs": list(_string_tuple(dict(working_scope or {}).get("workspace_refs"))),
            "target_objects": list(_object_ref_list(dict(working_scope or {}).get("target_objects"))),
            "source_refs": list(_string_tuple(dict(working_scope or {}).get("source_refs"))),
            "excluded_scope": list(_string_tuple(dict(working_scope or {}).get("excluded_scope"))),
            "known_constraints": list(_string_tuple(dict(working_scope or {}).get("known_constraints"))),
            "working_scope": dict(working_scope or {}),
            "permission_requirements": permission_requirements,
            "resource_requirements": dict(raw.get("resource_requirements") or {}),
            "task_environment_id": task_environment_id,
            "safety_boundaries": list(_string_tuple(raw.get("safety_boundaries") or seed.get("safety_boundaries"))),
            "authority": "harness.loop.task_run_contract.environment_contract",
        }
    )


def _feedback_contract_from_seed(
    seed: dict[str, Any],
    *,
    acceptance_contract: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(seed.get("feedback_contract") or {}) if isinstance(seed.get("feedback_contract"), dict) else {}
    return _drop_empty_payload(
        {
            "feedback_sources": list(_string_tuple(raw.get("feedback_sources")))
            or ["tool_observation", "runtime_observation", "user_steer", "lifecycle_signal", "budget_signal", "verification_signal", "recovery_signal"],
            "dynamic_context_slots": list(_string_tuple(raw.get("dynamic_context_slots")))
            or [
                "stable_lifecycle_guidance",
                "dynamic_runtime_context",
                "task_goal_context",
                "task_plan_context",
                "task_todo_context",
                "tail_user_steer",
            ],
            "steer_policy": dict(raw.get("steer_policy") or {"identity_binding": "active_turn_or_task_run_required", "binding_failure": "fail_closed"}),
            "verification_feedback_policy": dict(raw.get("verification_feedback_policy") or {"feeds_acceptance_contract": True}),
            "budget_feedback_policy": dict(raw.get("budget_feedback_policy") or {"tool_or_context_limit_triggers_closeout_recover": True}),
            "feedback_priority": list(_string_tuple(raw.get("feedback_priority")))
            or ["user_steer", "safety_boundary", "verification_signal", "recovery_signal", "tool_observation", "runtime_observation"],
            "feedback_identity_binding": _first_text(raw.get("feedback_identity_binding"), "active_turn_or_task_run_required"),
            "acceptance_feedback_ref": "acceptance_contract" if acceptance_contract else "",
        }
    )


def _acceptance_contract_from_seed(
    seed: dict[str, Any],
    *,
    completion_criteria: tuple[str, ...],
    required_artifacts: tuple[dict[str, Any], ...],
    required_verifications: tuple[dict[str, Any], ...],
    acceptance_policy: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(seed.get("acceptance_contract") or {}) if isinstance(seed.get("acceptance_contract"), dict) else {}
    return _drop_empty_payload(
        {
            "completion_criteria": list(completion_criteria),
            "required_artifacts": [dict(item) for item in required_artifacts],
            "required_verifications": [dict(item) for item in required_verifications],
            "verification_gate": dict(raw.get("verification_gate") or acceptance_policy.get("verification_gate") or {}),
            "final_answer_requirements": list(_string_tuple(raw.get("final_answer_requirements"))),
            "evidence_refs_required": bool(raw.get("evidence_refs_required") is not False),
            "acceptance_policy": acceptance_policy,
            "authority": "harness.loop.task_run_contract.acceptance_contract",
        }
    )


def _completion_evidence_descriptors(
    *,
    completion_criteria: tuple[str, ...],
    required_artifacts: tuple[dict[str, Any], ...],
    required_verifications: tuple[dict[str, Any], ...],
) -> list[str]:
    descriptors: list[str] = []
    if completion_criteria:
        descriptors.append("completion_criteria")
    if required_artifacts:
        descriptors.append("required_artifacts")
    if required_verifications:
        descriptors.append("required_verifications")
    return descriptors


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _canonical_handoff_fields(seed: dict[str, Any], *, primary_mode_contract: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    for legacy_key in (
        "resource_contract",
        "resource_requirements",
        "selected_skill_ids",
        "capability_intent",
        "skill_intent",
        "observation_contract",
    ):
        if _has_value(seed.get(legacy_key)):
            errors.append(f"legacy_task_contract_field_not_allowed:{legacy_key}")
    raw_working_scope = seed.get("working_scope")
    if not isinstance(raw_working_scope, dict):
        raw_working_scope = dict(dict(primary_mode_contract or {}).get("working_scope") or {})
    if not isinstance(raw_working_scope, dict):
        raw_working_scope = {}
    working_scope = {
        "target_objects": list(_object_ref_list(raw_working_scope.get("target_objects"))),
        "workspace_refs": list(_string_tuple(raw_working_scope.get("workspace_refs"))),
        "source_refs": list(_string_tuple(raw_working_scope.get("source_refs"))),
        "excluded_scope": list(_string_tuple(raw_working_scope.get("excluded_scope"))),
        "known_constraints": list(_string_tuple(raw_working_scope.get("known_constraints"))),
    }
    return working_scope, errors


def _object_ref_list(value: Any) -> tuple[Any, ...]:
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


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    return contract_string_tuple(value)


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    return tuple(dict(item) for item in values if isinstance(item, dict))


def runtime_contract_from_task_run_contract(contract: TaskRunContract) -> dict[str, Any]:
    runtime_profile = dict(contract.runtime_profile or {})
    allowed_operations = _explicit_allowed_operations_from_contract(contract)
    runtime_contract = {
        "runtime_profile": runtime_profile,
        "task_run_contract": {
            "container_contract": dict(contract.container_contract or {}),
            "work_modes": [dict(item) for item in contract.work_modes],
            "primary_work_mode_instance_id": contract.primary_work_mode_instance_id,
            "active_work_mode_refs": list(contract.active_work_mode_refs),
            "lifecycle_contract": dict(contract.lifecycle_contract or {}),
            "feedback_contract": dict(contract.feedback_contract or {}),
            "memory_contract": dict(contract.memory_contract or {}),
            "acceptance_contract": dict(contract.acceptance_contract or {}),
            "runtime_requirements": dict(contract.runtime_requirements or {}),
            "authority": "harness.loop.task_run_runtime_contract.task_run_contract",
        },
        "working_scope": dict(contract.environment_contract.get("working_scope") or contract.working_scope or {}),
        "authority": "harness.loop.task_run_runtime_contract",
    }
    if allowed_operations is not None:
        runtime_contract["allowed_operations"] = list(allowed_operations)
    if contract.task_environment_id:
        runtime_contract["task_environment_id"] = contract.task_environment_id
    runtime_contract["skill_activation"] = {
        "selected_skill_ids": [],
        "selection_source": "runtime",
        "selection_reason": "",
        "expanded_skill_refs": [],
        "rejected_skill_ids": [],
        "authority": "harness.loop.task_run_runtime_contract.skill_activation",
    }
    if contract.external_plan_ref:
        runtime_contract["engagement_plan_ref"] = contract.external_plan_ref
    if contract.source_contract_ref:
        runtime_contract["engagement_contract_ref"] = contract.source_contract_ref
        if str(runtime_profile.get("engagement_run_ref") or "").strip():
            runtime_contract["engagement_run_ref"] = str(runtime_profile.get("engagement_run_ref") or "").strip()
        runtime_contract["engagement_contract"] = {
            "contract_id": contract.source_contract_ref,
            "plan_id": contract.external_plan_ref,
            "task_environment_id": contract.task_environment_id,
            "runtime_profile": runtime_profile,
            "execution_strategy": {"kind": "single_agent_task_run"},
            "prompt_contract": dict(contract.prompt_contract or {}),
            "output_contract": dict(contract.acceptance_contract or {}),
            "acceptance_policy": dict(contract.acceptance_contract.get("acceptance_policy") or contract.acceptance_policy or {}),
            "recovery_policy": dict(contract.lifecycle_contract.get("failure_recovery_policy") or contract.recovery_policy or {}),
            "authority": "task_system.engagement_contract_projection",
        }
    return runtime_contract


def _explicit_allowed_operations_from_contract(contract: TaskRunContract) -> tuple[str, ...] | None:
    runtime_profile = dict(contract.runtime_profile or {})
    execution_permit = dict(runtime_profile.get("execution_permit") or {})
    permission_requirements = dict(contract.permission_requirements or {})
    operations: list[str] = []
    seen: set[str] = set()
    for value in (
        runtime_profile.get("allowed_operations"),
        execution_permit.get("allowed_operations"),
        permission_requirements.get("allowed_operations"),
        permission_requirements.get("required_operations"),
        permission_requirements.get("optional_operations"),
    ):
        for operation in _string_tuple(value):
            if operation in seen:
                continue
            seen.add(operation)
            operations.append(operation)
    return tuple(operations) if operations else None


def _explicit_allowed_operations_from_contract_seed(seed: dict[str, Any]) -> tuple[str, ...] | None:
    runtime_profile = dict(seed.get("runtime_profile") or {})
    execution_permit = dict(runtime_profile.get("execution_permit") or {})
    permission_requirements = dict(seed.get("permission_requirements") or seed.get("permission_request") or {})
    operation_requirement = dict(seed.get("operation_requirement") or {})
    operations: list[str] = []
    seen: set[str] = set()
    for value in (
        seed.get("allowed_operations"),
        runtime_profile.get("allowed_operations"),
        execution_permit.get("allowed_operations"),
        permission_requirements.get("allowed_operations"),
        permission_requirements.get("required_operations"),
        permission_requirements.get("optional_operations"),
        operation_requirement.get("allowed_operations"),
        operation_requirement.get("required_operations"),
        operation_requirement.get("optional_operations"),
    ):
        for operation in _string_tuple(value):
            if operation in seen:
                continue
            seen.add(operation)
            operations.append(operation)
    return tuple(operations) if operations else None


def _runtime_profile_with_execution_permit_allowed_operations(
    runtime_profile: dict[str, Any],
    *,
    allowed_operations: tuple[str, ...] | None,
) -> dict[str, Any]:
    if allowed_operations is None:
        return dict(runtime_profile or {})
    profile = dict(runtime_profile or {})
    execution_permit = dict(profile.get("execution_permit") or {})
    execution_permit["allowed_operations"] = list(allowed_operations)
    profile["execution_permit"] = execution_permit
    return profile


def _task_lifecycle_origin(*, action_request: ModelActionRequest, turn_id: str) -> dict[str, str]:
    diagnostics = dict(action_request.diagnostics or {})
    return {
        "origin_kind": str(diagnostics.get("origin_kind") or "agent_requested"),
        "origin_authority": str(diagnostics.get("origin_authority") or "harness.agent_loop"),
        "origin_ref": str(action_request.request_id or ""),
        "parent_run_ref": str(turn_id or ""),
    }
