from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from runtime.shared.models import AgentRun, TaskRun

from .model_action_protocol import ModelActionRequest


TaskLifecycleStatus = Literal["created", "admitted", "running", "waiting_executor", "waiting_approval", "completed", "failed", "blocked"]


@dataclass(frozen=True, slots=True)
class TaskRunContract:
    contract_id: str
    contract_source: str
    user_visible_goal: str
    task_run_goal: str
    required_artifacts: tuple[dict[str, Any], ...] = ()
    required_verifications: tuple[dict[str, Any], ...] = ()
    completion_criteria: tuple[str, ...] = ()
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    permission_requirements: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    recovery_policy: dict[str, Any] = field(default_factory=dict)
    created_from_packet_ref: str = ""
    authority: str = "harness.loop.task_run_contract"

    def __post_init__(self) -> None:
        if self.authority != "harness.loop.task_run_contract":
            raise ValueError("TaskRunContract authority must be harness.loop.task_run_contract")
        if not self.contract_id:
            raise ValueError("TaskRunContract requires contract_id")
        if not self.user_visible_goal:
            raise ValueError("TaskRunContract requires user_visible_goal")
        if not self.task_run_goal:
            raise ValueError("TaskRunContract requires task_run_goal")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_artifacts"] = [dict(item) for item in self.required_artifacts]
        payload["required_verifications"] = [dict(item) for item in self.required_verifications]
        payload["completion_criteria"] = list(self.completion_criteria)
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
) -> tuple[TaskRunContract | None, list[str]]:
    seed = dict(action_request.task_contract_seed or {})
    errors: list[str] = []
    goal = _first_text(
        seed.get("user_visible_goal"),
        seed.get("task_run_goal"),
        seed.get("goal"),
        seed.get("objective"),
    )
    if not goal:
        errors.append("task_goal_required")
    criteria = _string_tuple(
        seed.get("completion_criteria")
        or dict(action_request.completion_contract or {}).get("completion_criteria")
    )
    required_artifacts = _dict_tuple(
        seed.get("required_artifacts")
        or seed.get("artifact_requirements")
        or dict(action_request.completion_contract or {}).get("artifact_requirements")
    )
    required_verifications = _dict_tuple(
        seed.get("required_verifications")
        or seed.get("verification_requirements")
        or dict(action_request.completion_contract or {}).get("required_verifications")
    )
    if not criteria and not required_artifacts and not required_verifications:
        errors.append("completion_evidence_required")
    if errors:
        return None, errors
    contract = TaskRunContract(
        contract_id=f"task-contract:{uuid.uuid4().hex[:12]}",
        contract_source="model_request",
        user_visible_goal=goal,
        task_run_goal=goal,
        required_artifacts=required_artifacts,
        required_verifications=required_verifications,
        completion_criteria=criteria,
        resource_requirements=dict(seed.get("resource_requirements") or seed.get("resource_contract") or {}),
        permission_requirements=dict(
            seed.get("permission_requirements") or action_request.permission_request or {}
        ),
        acceptance_policy=dict(seed.get("acceptance_policy") or {}),
        recovery_policy=dict(seed.get("recovery_policy") or {}),
        created_from_packet_ref=packet_ref,
    )
    return contract, []


def start_task_lifecycle(
    runtime_host: Any,
    *,
    session_id: str,
    turn_id: str,
    task_id: str,
    action_request: ModelActionRequest,
    contract: TaskRunContract,
    agent_profile_ref: str,
) -> tuple[TaskRun, AgentRun, TaskLifecycleRecord, list[dict[str, Any]]]:
    now = time.time()
    task_run_id = f"taskrun:{turn_id}:{uuid.uuid4().hex[:8]}"
    agent_run_id = f"agrun:{task_run_id}:main"
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
        status="waiting_executor",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "action_request_ref": action_request.request_id,
            "contract": contract.to_dict(),
        },
    )
    agent_run = AgentRun(
        agent_run_id=agent_run_id,
        task_run_id=task_run_id,
        agent_id="agent:0",
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        status="waiting_executor",
        execution_runtime_kind="single_agent_task",
        created_at=now,
        updated_at=now,
        diagnostics={"turn_id": turn_id, "contract_ref": contract_ref},
    )
    lifecycle = TaskLifecycleRecord(
        task_run_id=task_run_id,
        contract_ref=contract_ref,
        status="waiting_executor",
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
            "task_lifecycle_ref": lifecycle_ref,
        },
    )
    return task_run, agent_run, lifecycle, [
        {"type": "harness_run_started", "task_run": task_run.to_dict(), "event": started_event.to_dict()},
        {"type": "task_run_lifecycle_started", "event": started_event.to_dict()},
    ]


def finish_task_lifecycle(
    runtime_host: Any,
    *,
    task_run: TaskRun,
    lifecycle: TaskLifecycleRecord,
    status: Literal["completed", "failed", "blocked"],
    terminal_reason: str,
    observation_refs: tuple[str, ...] = (),
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
        terminal_reason="task_launch_supervision",
        diagnostics={
            **dict(task_run.diagnostics or {}),
            "pending_launch_gate": gate_state,
        },
    )
    updated_lifecycle = replace(
        lifecycle,
        status="waiting_approval",
        updated_at=now,
        terminal_reason="task_launch_supervision",
    )
    runtime_host.state_index.upsert_task_run(updated_task)
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


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    raw = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    return _dedupe_tuple(tuple(str(item or "").strip() for item in raw if str(item or "").strip()))


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        values = []
    return tuple(dict(item) for item in values if isinstance(item, dict))


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
