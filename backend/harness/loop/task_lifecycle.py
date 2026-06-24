from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

from runtime.shared.models import AgentRun, TaskRun
from harness.task_run_status import is_stopped_or_terminal_task_run, is_terminal_task_run_status
from harness.task_contract_normalization import contract_string_tuple

from .presentation import error_event, turn_completed_event
from .model_action_protocol import ModelActionRequest
from .turn_to_task_context_handoff import record_turn_to_task_context_handoff


TaskLifecycleStatus = Literal["created", "admitted", "running", "waiting_executor", "waiting_approval", "completed", "failed", "blocked", "aborted"]
CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
InitializeTaskTodo = Callable[..., dict[str, Any] | None]
ScheduleTaskRunExecutor = Callable[..., Any]

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


@dataclass(frozen=True, slots=True)
class TaskLifecycleRecord:
    task_run_id: str
    contract_ref: str
    status: TaskLifecycleStatus
    created_at: float
    updated_at: float
    terminal_reason: str = ""
    acceptance_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    authority: str = "harness.loop.task_lifecycle"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["acceptance_refs"] = list(self.acceptance_refs)
        payload["observation_refs"] = list(self.observation_refs)
        return payload


def contract_from_action_request(
    action_request: ModelActionRequest,
    *,
    packet_ref: str,
    task_environment_id: str = "",
) -> tuple[TaskRunContract | None, list[str]]:
    seed = _seed_with_layered_contract_aliases(dict(getattr(action_request, "task_run_contract_seed", {}) or action_request.task_contract_seed or {}))
    errors: list[str] = []
    if "container_contract" not in seed or "work_modes" not in seed:
        seed = _legacy_seed_to_task_run_contract_seed(seed)
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
    subcontracts = _task_contract_layers(
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
        contract_source="model_request",
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
        goal_contract=subcontracts["goal_contract"],
        plan_contract=subcontracts["plan_contract"],
        lifecycle_contract=subcontracts["lifecycle_contract"],
        environment_contract=subcontracts["environment_contract"],
        feedback_contract=subcontracts["feedback_contract"],
        memory_contract=dict(seed.get("memory_contract") or {}),
        acceptance_contract=subcontracts["acceptance_contract"],
        runtime_requirements=runtime_requirements,
    )
    return contract, []


def _seed_with_layered_contract_aliases(seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(seed or {})
    if "container_contract" in payload or "work_modes" in payload:
        return payload
    goal = dict(payload.get("goal_contract") or {}) if isinstance(payload.get("goal_contract"), dict) else {}
    if "user_visible_goal" not in payload and _has_value(goal.get("user_visible_goal")):
        payload["user_visible_goal"] = goal.get("user_visible_goal")
    if "task_run_goal" not in payload and _has_value(goal.get("task_run_goal") or goal.get("agent_goal")):
        payload["task_run_goal"] = goal.get("task_run_goal") or goal.get("agent_goal")

    environment = dict(payload.get("environment_contract") or {}) if isinstance(payload.get("environment_contract"), dict) else {}
    for key in ("working_scope", "permission_requirements"):
        if key not in payload and isinstance(environment.get(key), dict):
            payload[key] = dict(environment.get(key) or {})

    acceptance = dict(payload.get("acceptance_contract") or {}) if isinstance(payload.get("acceptance_contract"), dict) else {}
    for key in ("completion_criteria", "required_artifacts", "artifact_requirements", "required_verifications", "verification_requirements"):
        if key not in payload and _has_value(acceptance.get(key)):
            payload[key] = acceptance.get(key)

    plan = dict(payload.get("plan_contract") or {}) if isinstance(payload.get("plan_contract"), dict) else {}
    if "plan_ref" not in payload and _has_value(plan.get("plan_id")):
        payload["plan_ref"] = plan.get("plan_id")
    return payload


def _legacy_seed_to_task_run_contract_seed(seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(seed or {})
    goal = dict(payload.get("goal_contract") or {}) if isinstance(payload.get("goal_contract"), dict) else {}
    plan = dict(payload.get("plan_contract") or {}) if isinstance(payload.get("plan_contract"), dict) else {}
    working_scope = dict(payload.get("working_scope") or {})
    user_visible_goal = _first_text(payload.get("user_visible_goal"), goal.get("user_visible_goal"))
    task_run_goal = _first_text(payload.get("task_run_goal"), goal.get("task_run_goal"), goal.get("agent_goal"), user_visible_goal)
    primary_kind = "goal" if user_visible_goal or task_run_goal or goal.get("success_definition") else "plan"
    primary_contract = (
        {
            "user_visible_goal": user_visible_goal,
            "task_run_goal": task_run_goal,
            "success_definition": _first_text(goal.get("success_definition"), payload.get("success_definition")),
            "non_goals": list(_string_tuple(goal.get("non_goals") or payload.get("non_goals"))),
            "completion_evidence": list(_string_tuple(goal.get("completion_evidence") or payload.get("completion_evidence"))),
            "working_scope": working_scope,
        }
        if primary_kind == "goal"
        else {
            "strategy_summary": _first_text(plan.get("strategy_summary"), "按已有计划推进当前持续任务。"),
            "major_steps": list(_string_tuple(plan.get("major_steps") or plan.get("steps"))),
            "plan_status": _first_text(plan.get("plan_status"), "agent_managed"),
            "replan_policy": dict(plan.get("replan_policy") or {}),
            "working_scope": working_scope,
        }
    )
    primary_ref = f"work-mode:{primary_kind}:primary"
    work_modes: list[dict[str, Any]] = [
        {
            "mode_instance_id": primary_ref,
            "mode_kind": primary_kind,
            "mode_role": "primary",
            "status": "draft",
            "depends_on_mode_refs": [],
            "contract": primary_contract,
        }
    ]
    if primary_kind != "plan" and plan:
        work_modes.append(
            {
                "mode_instance_id": "work-mode:plan:supporting",
                "mode_kind": "plan",
                "mode_role": "supporting",
                "status": "draft",
                "depends_on_mode_refs": [primary_ref],
                "contract": {
                    "strategy_summary": _first_text(plan.get("strategy_summary"), ""),
                    "major_steps": list(_string_tuple(plan.get("major_steps") or plan.get("steps"))),
                    "plan_status": _first_text(plan.get("plan_status"), "agent_managed"),
                    "replan_policy": dict(plan.get("replan_policy") or {}),
                    "working_scope": working_scope,
                },
            }
        )
    return {
        "contract_version": "task_run_contract_v1",
        "container_contract": {
            "entry_reason": _first_text(payload.get("entry_reason"), "当前工作需要持续任务生命周期。"),
            "continuity_required": True,
            "control_required": True,
            "projection_required": True,
            "checkpoint_required": True,
            "minimum_viable_next_step": _first_text(payload.get("minimum_viable_next_step"), "推进当前 primary Work Mode 的下一步。"),
            "primary_work_mode_ref": primary_ref,
            "supporting_mode_refs": [str(item.get("mode_instance_id") or "") for item in work_modes[1:]],
            "mode_transition_policy": {"agent_may_propose_transition": True, "system_may_infer_transition": False, "requires_accepted_event": True},
        },
        "work_modes": work_modes,
        "lifecycle_contract": dict(payload.get("lifecycle_contract") or {}),
        "feedback_contract": dict(payload.get("feedback_contract") or {}),
        "memory_contract": dict(payload.get("memory_contract") or {}),
        "acceptance_contract": dict(payload.get("acceptance_contract") or {"acceptance_mode": "checkpoint"}),
        "runtime_requirements": {"permission_requirements": dict(payload.get("permission_requirements") or {})},
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


def _task_contract_layers(
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
            or ["stable_lifecycle_guidance", "dynamic_runtime_context", "task_plan_context", "tail_user_steer"],
            "steer_policy": dict(raw.get("steer_policy") or {"identity_binding": "active_turn_or_task_run_required", "binding_failure": "fail_closed"}),
            "verification_feedback_policy": dict(raw.get("verification_feedback_policy") or {"feeds_acceptance_contract": True}),
            "budget_feedback_policy": dict(raw.get("budget_feedback_policy") or {"tool_or_context_limit_triggers_closeout_recover": True}),
            "feedback_priority": list(_string_tuple(raw.get("feedback_priority")))
            or ["user_steer", "safety_boundary", "verification_signal", "recovery_signal", "tool_observation", "runtime_observation"],
            "feedback_identity_binding": _first_text(raw.get("feedback_identity_binding"), "active_turn_or_task_run_required"),
            "acceptance_feedback_ref": "acceptance_contract" if acceptance_contract else "",
            "authority": "harness.loop.task_run_contract.feedback_contract",
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


def current_session_task_run(runtime_host: Any, *, session_id: str) -> Any | None:
    state_index = getattr(runtime_host, "state_index", None)
    list_task_runs = getattr(state_index, "list_session_task_runs", None)
    if not callable(list_task_runs):
        return None
    try:
        task_runs = list(list_task_runs(session_id) or [])
    except Exception:
        return None
    candidates = [
        item
        for item in task_runs
        if _is_current_session_task_run(item, runtime_host=runtime_host)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_current_session_task_sort_key, reverse=True)[0]


def _is_current_session_task_run(task_run: Any, *, runtime_host: Any | None = None) -> bool:
    if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
        return False
    status = str(getattr(task_run, "status", "") or "").strip()
    if is_terminal_task_run_status(status):
        return False
    if is_stopped_or_terminal_task_run(task_run, runtime_host=runtime_host):
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    origin = dict(diagnostics.get("origin") or {})
    origin_kind = str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()
    if origin_kind == "graph_node_assigned":
        return False
    return not bool(
        diagnostics.get("coordination_stage_id")
        or diagnostics.get("stage_request_id")
        or diagnostics.get("stage_idempotency_key")
        or diagnostics.get("graph_node_id")
        or diagnostics.get("graph_work_order_id")
    )


def _current_session_task_sort_key(task_run: Any) -> tuple[int, float, float]:
    status = str(getattr(task_run, "status", "") or "").strip()
    status_rank = {
        "running": 6,
        "created": 5,
        "waiting_executor": 4,
        "waiting_approval": 3,
        "blocked": 2,
    }.get(status, 0)
    return (
        status_rank,
        float(getattr(task_run, "updated_at", 0.0) or 0.0),
        float(getattr(task_run, "created_at", 0.0) or 0.0),
    )


def start_task_lifecycle(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    task_id: str,
    action_request: ModelActionRequest,
    contract: TaskRunContract,
    agent_profile_ref: str,
    model_selection: dict[str, Any] | None = None,
    runtime_assembly: Any | None = None,
    editor_context: dict[str, Any] | None = None,
    start_context_handoff: dict[str, Any] | None = None,
) -> tuple[TaskRun, AgentRun, TaskLifecycleRecord, list[dict[str, Any]]]:
    now = time.time()
    task_run_id = f"taskrun:{turn_id}:{uuid.uuid4().hex[:8]}"
    agent_run_id = f"agrun:{task_run_id}:main"
    origin = _task_lifecycle_origin(action_request=action_request, turn_id=turn_id)
    contract = _contract_with_origin(contract, origin)
    model_selection_snapshot = _model_selection_snapshot(model_selection)
    runtime_permission_mode = runtime_task_permission_mode(runtime_assembly)
    editor_context_snapshot = _task_editor_context_snapshot(editor_context, turn_id=turn_id)
    contract_ref = runtime_host.runtime_objects.put_object(
        "task_run_contract",
        contract.contract_id,
        contract.to_dict(),
    )
    task_run = TaskRun(
        task_run_id=task_run_id,
        session_id=session_id,
        task_id=task_id or f"task:{turn_id}",
        task_contract_ref=contract_ref,
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        execution_runtime_kind="single_agent_task",
        status="created",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "action_request_ref": action_request.request_id,
            "origin": origin,
            **origin,
            "contract": contract.to_dict(),
            "task_run_contract": contract.to_dict(),
            "primary_work_mode_instance_id": contract.primary_work_mode_instance_id,
            "active_work_mode_refs": list(contract.active_work_mode_refs),
            "runtime_contract": _runtime_contract_from_task_run_contract(
                contract,
            ),
            "skill_activation": {
                "selected_skill_ids": [],
                "selection_source": "runtime",
                "selection_reason": "",
                "expanded_skill_refs": [],
                "rejected_skill_ids": [],
                "authority": "harness.loop.task_run_runtime_contract.skill_activation",
            },
            "model_selection": model_selection_snapshot,
            "runtime_permission_mode": runtime_permission_mode,
            **(
                {
                    "editor_context": editor_context_snapshot,
                    "editor_context_binding": {
                        "scope": "task_run",
                        "source": "parent_turn",
                        "turn_id": turn_id,
                        "authority": "harness.loop.single_agent_task_editor_context_snapshot",
                    },
                }
                if editor_context_snapshot
                else {}
            ),
            "runtime_permission_binding": {
                "scope": "task_run",
                "source": "turn_runtime_assembly",
                "turn_id": turn_id,
                "authority": "harness.loop.single_agent_task_permission_snapshot",
            },
            "model_selection_binding": {
                "scope": "task_run",
                "source": "agent_turn",
                "turn_id": turn_id,
                "authority": "harness.loop.single_agent_task_model_selection",
            },
        },
    )
    handoff_record = record_turn_to_task_context_handoff(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        task_run_id=task_run_id,
        task_id=task_run.task_id,
        start_context_handoff=dict(start_context_handoff or {}),
    )
    task_run = replace(
        task_run,
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "turn_to_task_context_handoff_ref": handoff_record.handoff_ref,
            "turn_to_task_context_handoff": {
                "handoff_id": handoff_record.handoff_id,
                "source_packet_ref": str(handoff_record.payload.get("source_packet_ref") or ""),
                "inherited_observation_count": len(list(handoff_record.payload.get("inherited_observations") or [])),
                "inherited_file_state_count": len(list(handoff_record.payload.get("inherited_file_state_snapshot") or [])),
                "inherited_memory_context_refs": dict(handoff_record.payload.get("inherited_memory_context_refs") or {}),
                "authority": "harness.loop.turn_to_task_context_handoff",
            },
        },
    )
    agent_run = AgentRun(
        agent_run_id=agent_run_id,
        task_run_id=task_run_id,
        agent_id="agent:0",
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        status="pending",
        execution_runtime_kind="single_agent_task",
        created_at=now,
        updated_at=now,
        diagnostics={"turn_id": turn_id, "contract_ref": contract_ref, "origin": origin, **origin},
    )
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status="created",
        created_at=now,
        updated_at=now,
    )
    lifecycle_ref = runtime_host.runtime_objects.put_object(
        "task_lifecycle",
        task_run_id,
        lifecycle.to_dict(),
    )
    runtime_host.state_index.upsert_task_run(task_run)
    runtime_host.state_index.upsert_agent_run(agent_run)
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        try:
            if active_registry.resolve_current(session_id) is None:
                active_registry.start(
                    session_id=session_id,
                    turn_id=turn_id,
                    state="starting",
                )
            active_registry.bind_task_run(
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                state="starting",
            )
        except Exception:
            pass
    started_event = runtime_host.event_log.append(
        task_run_id,
        "task_run_lifecycle_started",
        payload={
            "task_run": task_run.to_dict(),
            "agent_run": agent_run.to_dict(),
            "contract": contract.to_dict(),
            "lifecycle": lifecycle.to_dict(),
        },
        refs={
            "turn_ref": turn_id,
            "action_request_ref": action_request.request_id,
            "task_contract_ref": contract_ref,
            "task_run_contract_ref": contract_ref,
            "task_lifecycle_ref": lifecycle_ref,
            "turn_to_task_context_handoff_ref": handoff_record.handoff_ref,
        },
    )
    return task_run, agent_run, lifecycle, [
        {"type": "task_run_lifecycle_event", "event": handoff_record.event.to_dict()},
        {"type": "harness_run_started", "task_run": task_run.to_dict(), "event": started_event.to_dict()},
        {"type": "task_run_lifecycle_started", "event": started_event.to_dict()},
    ]


def finish_task_lifecycle(
    runtime_host: Any,
    *,
    task_run: TaskRun,
    lifecycle: TaskLifecycleRecord,
    status: Literal["completed", "failed", "blocked", "aborted"],
    terminal_reason: str,
    observation_refs: tuple[str, ...] = (),
    before_state_commit: Callable[[TaskRun, TaskLifecycleRecord, dict[str, Any]], None] | None = None,
) -> tuple[TaskRun, TaskLifecycleRecord, dict[str, Any]]:
    now = time.time()
    updated_task = replace(
        task_run,
        status=status,  # type: ignore[arg-type]
        updated_at=now,
        terminal_reason=terminal_reason,  # type: ignore[arg-type]
    )
    updated_lifecycle = replace(
        lifecycle,
        status=status,
        updated_at=now,
        terminal_reason=terminal_reason,
        observation_refs=_dedupe_tuple((*lifecycle.observation_refs, *observation_refs)),
    )
    if before_state_commit is None:
        runtime_host.state_index.upsert_task_run(updated_task)
        lifecycle_ref = runtime_host.runtime_objects.put_object(
            "task_lifecycle",
            task_run.task_run_id,
            updated_lifecycle.to_dict(),
        )
        event = runtime_host.event_log.append(
            task_run.task_run_id,
            "task_run_lifecycle_finished",
            payload={"task_run": updated_task.to_dict(), "lifecycle": updated_lifecycle.to_dict()},
            refs={"task_lifecycle_ref": lifecycle_ref},
        )
    else:
        lifecycle_ref = runtime_host.runtime_objects.put_object(
            "task_lifecycle",
            task_run.task_run_id,
            updated_lifecycle.to_dict(),
        )
        event = runtime_host.event_log.append(
            task_run.task_run_id,
            "task_run_lifecycle_finished",
            payload={"task_run": updated_task.to_dict(), "lifecycle": updated_lifecycle.to_dict()},
            refs={"task_lifecycle_ref": lifecycle_ref},
        )
        before_state_commit(updated_task, updated_lifecycle, event.to_dict())
        runtime_host.state_index.upsert_task_run(updated_task)
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        try:
            active_registry.complete_bound_task(
                session_id=updated_task.session_id,
                task_run_id=updated_task.task_run_id,
                terminal_reason=terminal_reason,
            )
        except Exception:
            pass
    return updated_task, updated_lifecycle, event.to_dict()


def task_launch_supervision_policy(runtime_assembly: Any) -> dict[str, Any]:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    profile = dict(payload.get("profile") or {})
    lifecycle = dict(profile.get("task_lifecycle_policy") or {})
    supervision = lifecycle.get("task_launch_supervision", lifecycle.get("launch_supervision"))
    if isinstance(supervision, dict):
        return _normalize_task_launch_supervision_policy(supervision, default_enabled=True)
    if supervision is True:
        return _normalize_task_launch_supervision_policy({}, default_enabled=True)
    return _normalize_task_launch_supervision_policy({}, default_enabled=False)


def requires_task_launch_supervision(policy: dict[str, Any]) -> bool:
    return bool(policy.get("enabled", False))


def wait_task_launch_supervision(
    runtime_host: Any,
    *,
    task_run: TaskRun,
    lifecycle: TaskLifecycleRecord,
    gate_policy: dict[str, Any],
) -> tuple[TaskRun, TaskLifecycleRecord, dict[str, Any]]:
    now = time.time()
    gate_state = {
        "status": "pending",
        "gate_type": str(gate_policy.get("gate_type") or "task_launch_supervision"),
        "mode": "supervision",
        "task_run_id": task_run.task_run_id,
        "created_at": now,
        "user_prompt": str(gate_policy.get("user_prompt") or "任务已准备启动。你可以提出建议，或直接通过。"),
        "allow_direct_pass": bool(gate_policy.get("allow_direct_pass", True)),
        "authority": "agent_runtime_profile.task_launch_supervision",
    }
    updated_task = replace(
        task_run,
        status="waiting_approval",
        updated_at=now,
        terminal_reason="",
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "wait_reason": "task_launch_supervision",
            "pending_launch_gate": gate_state,
        },
    )
    updated_lifecycle = replace(
        lifecycle,
        status="waiting_approval",
        updated_at=now,
        terminal_reason="",
    )
    runtime_host.state_index.upsert_task_run(updated_task)
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        try:
            active_registry.bind_task_run(
                session_id=updated_task.session_id,
                turn_id=str(dict(updated_task.diagnostics or {}).get("turn_id") or ""),
                task_run_id=updated_task.task_run_id,
                state="waiting_approval",
            )
        except Exception:
            pass
    lifecycle_ref = runtime_host.runtime_objects.put_object(
        "task_lifecycle",
        task_run.task_run_id,
        updated_lifecycle.to_dict(),
    )
    event = runtime_host.event_log.append(
        task_run.task_run_id,
        "task_launch_supervision_waiting",
        payload={
            "task_run": updated_task.to_dict(),
            "lifecycle": updated_lifecycle.to_dict(),
            "gate": gate_state,
        },
        refs={"task_lifecycle_ref": lifecycle_ref},
    )
    return updated_task, updated_lifecycle, event.to_dict()


async def start_task_lifecycle_from_action_request(
    *,
    runtime_host: Any,
    session_id: str,
    turn_id: str,
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
    action_request: ModelActionRequest,
    agent_runtime_profile: Any,
    runtime_assembly: Any,
    runtime_branch: dict[str, Any],
    answer_source: str,
    scheduler: str,
    max_steps: int,
    commit_assistant_message: CommitAssistantMessage,
    initialize_task_todo: InitializeTaskTodo,
    schedule_task_run_executor: ScheduleTaskRunExecutor,
    editor_context: dict[str, Any] | None = None,
    start_context_handoff: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    api_protocol_prefix_messages = _api_protocol_prefix_from_action_request(action_request)
    contract, contract_errors = contract_from_action_request(
        action_request,
        packet_ref=str(action_request.diagnostics.get("packet_ref") or f"single-agent-turn:{turn_id}"),
        task_environment_id=runtime_task_environment_id(runtime_assembly),
    )
    if contract is None:
        content = "任务目标或验收边界还不完整，当前不能启动持续处理。"
        yield error_event(
            content=content,
            code="task_contract_invalid",
            reason=";".join(contract_errors) or "task_contract_invalid",
        )
        return

    async for event in start_task_lifecycle_from_contract(
        runtime_host=runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        model_selection=model_selection,
        action_request=action_request,
        contract=contract,
        agent_runtime_profile=agent_runtime_profile,
        runtime_assembly=runtime_assembly,
        runtime_branch=runtime_branch,
        editor_context=editor_context,
        answer_source=answer_source,
        scheduler=scheduler,
        task_id=runtime_contract.get("selected_task_id") or runtime_contract.get("task_id") or f"task:{turn_id}",
        max_steps=max_steps,
        commit_assistant_message=commit_assistant_message,
        initialize_task_todo=initialize_task_todo,
        schedule_task_run_executor=schedule_task_run_executor,
        start_context_handoff=dict(start_context_handoff or {}),
    ):
        yield event


async def start_task_lifecycle_from_contract(
    *,
    runtime_host: Any,
    session_id: str,
    turn_id: str,
    model_selection: dict[str, Any],
    action_request: ModelActionRequest,
    contract: TaskRunContract,
    agent_runtime_profile: Any,
    runtime_assembly: Any,
    runtime_branch: dict[str, Any],
    answer_source: str,
    scheduler: str,
    task_id: str,
    max_steps: int,
    commit_assistant_message: CommitAssistantMessage,
    initialize_task_todo: InitializeTaskTodo,
    schedule_task_run_executor: ScheduleTaskRunExecutor,
    editor_context: dict[str, Any] | None = None,
    start_context_handoff: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    agent_profile_ref = str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent")
    task_run, _agent_run, lifecycle, lifecycle_events = start_task_lifecycle(
        runtime_host,
        session_id=session_id,
        turn_id=turn_id,
        task_id=str(task_id or f"task:{turn_id}"),
        action_request=action_request,
        contract=contract,
        agent_profile_ref=agent_profile_ref,
        model_selection=dict(model_selection or {}),
        runtime_assembly=runtime_assembly,
        editor_context=editor_context,
        start_context_handoff=dict(start_context_handoff or {}),
    )
    for event in lifecycle_events:
        yield event
    started_summary = ""
    started_summary_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "step": "task_lifecycle_started",
            "status": "running",
            "summary": started_summary,
            "public_progress_note": started_summary,
            "visibility": "internal",
            "presentation_source": "task_lifecycle.start",
        },
        refs={"task_run_ref": task_run.task_run_id, "turn_ref": turn_id},
    )
    yield {"type": "task_run_lifecycle_event", "event": started_summary_event.to_dict()}

    todo_event = initialize_task_todo(
        session_id=session_id,
        task_run_id=task_run.task_run_id,
        contract=contract.to_dict(),
    )
    if todo_event is not None:
        yield {"type": "task_run_lifecycle_event", "event": todo_event}

    launch_gate_policy = task_launch_supervision_policy(runtime_assembly)
    if launch_gate_policy.get("enabled"):
        gated_task, _gated_lifecycle, gate_event = wait_task_launch_supervision(
            runtime_host,
            task_run=task_run,
            lifecycle=lifecycle,
            gate_policy=launch_gate_policy,
        )
        yield {"type": "task_run_lifecycle_event", "event": gate_event}
        yield turn_completed_event(
            status="completed",
            terminal_reason="task_launch_supervision",
            task_run_id=gated_task.task_run_id,
            completion_state="task_launch_supervision",
        )
        return

    schedule_result = schedule_task_run_executor(
        task_run.task_run_id,
        scheduler=scheduler,
        turn_id=turn_id,
        max_steps=max_steps,
    )
    if not dict(schedule_result or {}).get("ok"):
        reason = str(dict(schedule_result or {}).get("reason") or "task_executor_schedule_failed")
        failed_task, _failed_lifecycle, failed_event = finish_task_lifecycle(
            runtime_host,
            task_run=task_run,
            lifecycle=lifecycle,
            status="failed",
            terminal_reason=reason,
        )
        yield {"type": "task_run_lifecycle_event", "event": failed_event}
        content = f"任务已经建立，但启动处理时失败：{_public_schedule_failure_reason(reason)}"
        yield error_event(
            content=content,
            code="task_executor_schedule_failed",
            reason=reason,
            extra={
                "runtime_branch": dict(runtime_branch or {}),
                "task_run": {"task_run_id": failed_task.task_run_id, "status": failed_task.status},
            },
        )
        return
    scheduled_summary = ""
    scheduled_summary_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "step": "task_executor_scheduled",
            "status": "running",
            "summary": scheduled_summary,
            "public_progress_note": scheduled_summary,
            "visibility": "internal",
            "presentation_source": "task_lifecycle.schedule",
        },
        refs={"task_run_ref": task_run.task_run_id, "turn_ref": turn_id},
    )
    yield {"type": "task_run_lifecycle_event", "event": scheduled_summary_event.to_dict()}
    yield turn_completed_event(
        status="completed",
        terminal_reason="task_executor_scheduled",
        task_run_id=task_run.task_run_id,
        completion_state="task_executor_scheduled",
    )


def runtime_task_environment_id(runtime_assembly: Any) -> str:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    environment = dict(payload.get("task_environment") or {})
    return str(
        environment.get("environment_id")
        or environment.get("task_environment_id")
        or ""
    ).strip()


def runtime_task_permission_mode(runtime_assembly: Any) -> str:
    payload = runtime_assembly.to_dict() if hasattr(runtime_assembly, "to_dict") else dict(runtime_assembly or {})
    return str(payload.get("permission_mode") or "full_access").strip() or "full_access"


def _api_protocol_prefix_from_action_request(action_request: ModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    return [
        dict(item)
        for item in list(diagnostics.get("api_protocol_prefix_messages") or [])
        if isinstance(item, dict)
    ]

def _normalize_task_launch_supervision_policy(policy: dict[str, Any], *, default_enabled: bool) -> dict[str, Any]:
    enabled = bool(policy.get("enabled", default_enabled))
    return {
        **dict(policy or {}),
        "enabled": enabled,
        "mode": "supervision" if enabled else "auto",
        "gate_type": str(policy.get("gate_type") or "task_launch_supervision"),
        "allow_direct_pass": bool(policy.get("allow_direct_pass", True)),
        "user_prompt": str(
            policy.get("user_prompt")
            or "任务已准备启动。你可以提出建议，或直接通过。"
        ),
        "authority": "agent_runtime_profile.task_lifecycle_policy",
    }


def _task_editor_context_snapshot(value: Any, *, turn_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}
    payload = _truncate_task_editor_context(dict(value), max_chars=60000)
    if not isinstance(payload, dict) or not payload:
        return {}
    return {
        **payload,
        "snapshot_binding": {
            "source": "parent_turn",
            "turn_id": str(turn_id or "").strip(),
            "authority": "harness.loop.single_agent_task_editor_context_snapshot",
        },
    }


def _truncate_task_editor_context(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[: max(0, int(max_chars or 0))]
    if isinstance(value, dict):
        remaining = max(0, int(max_chars or 0))
        result: dict[str, Any] = {}
        for key, item in value.items():
            if remaining <= 0:
                break
            truncated = _truncate_task_editor_context(item, max_chars=remaining)
            result[str(key)] = truncated
            remaining -= len(str(truncated))
        return result
    if isinstance(value, list):
        remaining = max(0, int(max_chars or 0))
        result: list[Any] = []
        for item in value:
            if remaining <= 0:
                break
            truncated = _truncate_task_editor_context(item, max_chars=remaining)
            result.append(truncated)
            remaining -= len(str(truncated))
        return result
    return value


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


def _model_selection_snapshot(model_selection: dict[str, Any] | None) -> dict[str, Any]:
    return dict(model_selection) if isinstance(model_selection, dict) else {}


def _dedupe_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _runtime_contract_from_task_run_contract(contract: TaskRunContract) -> dict[str, Any]:
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
        "task_contract": {
            "goal_contract": dict(contract.goal_contract or {}),
            "plan_contract": dict(contract.plan_contract or {}),
            "lifecycle_contract": dict(contract.lifecycle_contract or {}),
            "environment_contract": dict(contract.environment_contract or {}),
            "feedback_contract": dict(contract.feedback_contract or {}),
            "acceptance_contract": dict(contract.acceptance_contract or {}),
            "derived_from": "task_run_contract.work_modes",
            "authority": "harness.loop.task_run_runtime_contract.derived_task_contract_projection",
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


def _public_schedule_failure_reason(reason: str) -> str:
    value = str(reason or "").strip()
    if value == "task_run_not_found":
        return "没有找到刚创建的任务记录。"
    if value.startswith("not_executable:"):
        return "当前任务状态不允许启动执行。"
    if value == "already_running":
        return "任务已经在运行中。"
    return "执行器未能接管任务。"


def _task_lifecycle_origin(*, action_request: ModelActionRequest, turn_id: str) -> dict[str, str]:
    diagnostics = dict(action_request.diagnostics or {})
    return {
        "origin_kind": str(diagnostics.get("origin_kind") or "agent_requested"),
        "origin_authority": str(diagnostics.get("origin_authority") or "harness.agent_loop"),
        "origin_ref": str(action_request.request_id or ""),
        "parent_run_ref": str(turn_id or ""),
    }


def _contract_with_origin(contract: TaskRunContract, origin: dict[str, Any]) -> TaskRunContract:
    if dict(contract.origin or {}) == dict(origin or {}):
        return contract
    return replace(contract, origin=dict(origin or {}))
