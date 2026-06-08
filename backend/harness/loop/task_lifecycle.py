from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

from runtime.shared.models import AgentRun, TaskRun
from runtime.output_boundary import canonical_output_decision_for_final_text

from .presentation import error_event, final_answer_event
from .model_action_protocol import ModelActionRequest


TaskLifecycleStatus = Literal["created", "admitted", "running", "waiting_executor", "waiting_approval", "completed", "failed", "blocked", "aborted"]
CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
InitializeTaskTodo = Callable[..., dict[str, Any] | None]
ScheduleTaskRunExecutor = Callable[..., Any]

_CURRENT_SESSION_TASK_TERMINAL_STATUSES = {
    "completed",
    "success",
    "failed",
    "error",
    "aborted",
    "cancelled",
    "canceled",
    "stopped",
    "user_aborted",
}


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
    source_contract_ref: str = ""
    external_plan_ref: str = ""
    task_environment_id: str = ""
    runtime_profile: dict[str, Any] = field(default_factory=dict)
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    graph_slot: dict[str, Any] = field(default_factory=dict)
    origin: dict[str, Any] = field(default_factory=dict)
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
    task_environment_id: str = "",
) -> tuple[TaskRunContract | None, list[str]]:
    seed = dict(action_request.task_contract_seed or {})
    errors: list[str] = []
    user_visible_goal = _first_text(seed.get("user_visible_goal"))
    task_run_goal = _first_text(seed.get("task_run_goal"))
    if not user_visible_goal:
        errors.append("task_goal_required")
    if not task_run_goal:
        errors.append("task_run_goal_required")
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
    runtime_profile = _runtime_profile_with_execution_permit_allowed_operations(
        dict(seed.get("runtime_profile") or {}),
        allowed_operations=_explicit_allowed_operations_from_contract_seed(seed),
    )
    contract = TaskRunContract(
        contract_id=f"task-contract:{uuid.uuid4().hex[:12]}",
        contract_source="model_request",
        user_visible_goal=user_visible_goal,
        task_run_goal=task_run_goal,
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
        source_contract_ref=str(seed.get("source_contract_ref") or seed.get("contract_ref") or "").strip(),
        external_plan_ref=str(seed.get("external_plan_ref") or seed.get("plan_ref") or "").strip(),
        task_environment_id=str(task_environment_id or "").strip(),
        runtime_profile=runtime_profile,
        prompt_contract=dict(seed.get("prompt_contract") or {}),
        graph_slot=dict(seed.get("graph_slot") or {}),
    )
    return contract, []


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
        if _is_current_session_task_run(item)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_current_session_task_sort_key, reverse=True)[0]


def _is_current_session_task_run(task_run: Any) -> bool:
    if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
        return False
    status = str(getattr(task_run, "status", "") or "").strip()
    if status in _CURRENT_SESSION_TASK_TERMINAL_STATUSES:
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = diagnostics.get("runtime_control") if isinstance(diagnostics.get("runtime_control"), dict) else {}
    control_state = str(dict(control or {}).get("state") or "").strip()
    if control_state == "stopped":
        return False
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


async def _emit_current_session_task_handoff(
    *,
    runtime_host: Any,
    current_task: Any,
    session_id: str,
    turn_id: str,
    answer_source: str,
    runtime_branch: dict[str, Any],
    commit_assistant_message: CommitAssistantMessage,
    api_protocol_prefix_messages: list[dict[str, Any]] | None,
) -> AsyncIterator[dict[str, Any]]:
    content = _current_session_task_handoff_content(current_task)
    source = f"{answer_source}.current_session_task"
    await commit_task_control_message(
        commit_assistant_message,
        session_id=session_id,
        turn_id=turn_id,
        content=content,
        answer_source=source,
        api_protocol_prefix_messages=api_protocol_prefix_messages,
    )
    task_payload = _task_run_payload(current_task)
    yield {
        "type": "task_run_lifecycle_reused_current",
        "task_run": task_payload,
        "status": str(task_payload.get("status") or ""),
        "terminal_reason": "session_active_task_exists",
        "authority": "harness.loop.task_lifecycle.current_session_task_guard",
    }
    yield final_answer_event(
        content=content,
        answer_channel="task_control",
        answer_source=source,
        terminal_reason="session_active_task_exists",
        extra={
            "runtime_branch": dict(runtime_branch or {}),
            "task_run": {
                "task_run_id": str(task_payload.get("task_run_id") or ""),
                "status": str(task_payload.get("status") or ""),
            },
            **_active_turn_event_payload(runtime_host=runtime_host, session_id=session_id),
        },
    )


def _current_session_task_handoff_content(task_run: Any) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    contract = dict(diagnostics.get("contract") or {})
    goal = _first_text(
        diagnostics.get("goal"),
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
        getattr(task_run, "task_id", ""),
    )
    latest = _first_text(
        diagnostics.get("latest_public_progress_note"),
        diagnostics.get("latest_step_summary"),
        diagnostics.get("summary"),
    )
    status = str(getattr(task_run, "status", "") or "").strip()
    lines = ["当前会话已经有一个未完成任务，我不会再启动第二个任务。"]
    if goal:
        lines.append(f"当前处理的是：{goal}")
    if latest:
        lines.append(f"最近进展：{latest}")
    if status in {"waiting_executor", "blocked"}:
        lines.append("你可以继续、暂停、停止，或补充新的要求；系统会回到这个任务上处理。")
    elif status in {"created", "running"}:
        lines.append("当前任务仍在处理中，新的进展会继续更新在这个会话里。")
    return "\n".join(line for line in lines if line.strip())


def _task_run_payload(task_run: Any) -> dict[str, Any]:
    if hasattr(task_run, "to_dict"):
        try:
            return dict(task_run.to_dict())
        except Exception:
            pass
    return dict(task_run or {}) if isinstance(task_run, dict) else {}


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
        status="waiting_executor",
        created_at=now,
        updated_at=now,
        diagnostics={
            "turn_id": turn_id,
            "action_request_ref": action_request.request_id,
            "origin": origin,
            **origin,
            "contract": contract.to_dict(),
            "runtime_contract": _runtime_contract_from_task_run_contract(
                contract,
                selected_skill_ids=action_request.selected_skill_ids,
            ),
            "selected_skill_ids": list(action_request.selected_skill_ids),
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
    agent_run = AgentRun(
        agent_run_id=agent_run_id,
        task_run_id=task_run_id,
        agent_id="agent:0",
        agent_profile_id=agent_profile_ref or "main_interactive_agent",
        status="waiting_executor",
        execution_runtime_kind="single_agent_task",
        created_at=now,
        updated_at=now,
        diagnostics={"turn_id": turn_id, "contract_ref": contract_ref, "origin": origin, **origin},
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
    active_registry = getattr(runtime_host, "active_turn_registry", None)
    if active_registry is not None:
        try:
            active_registry.bind_task_run(
                session_id=session_id,
                turn_id=turn_id,
                task_run_id=task_run_id,
                state="waiting_executor",
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
    status: Literal["completed", "failed", "blocked", "aborted"],
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


async def start_task_lifecycle_from_action_request(
    *,
    runtime_host: Any,
    session_id: str,
    turn_id: str,
    task_selection: dict[str, Any],
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
) -> AsyncIterator[dict[str, Any]]:
    api_protocol_prefix_messages = _api_protocol_prefix_from_action_request(action_request)
    current_task = current_session_task_run(runtime_host, session_id=session_id)
    if current_task is not None:
        async for event in _emit_current_session_task_handoff(
            runtime_host=runtime_host,
            current_task=current_task,
            session_id=session_id,
            turn_id=turn_id,
            answer_source=answer_source,
            runtime_branch=runtime_branch,
            commit_assistant_message=commit_assistant_message,
            api_protocol_prefix_messages=api_protocol_prefix_messages,
        ):
            yield event
        return
    contract, contract_errors = contract_from_action_request(
        action_request,
        packet_ref=str(action_request.diagnostics.get("packet_ref") or f"single-agent-turn:{turn_id}"),
        task_environment_id=runtime_task_environment_id(runtime_assembly),
    )
    if contract is None:
        content = "任务目标或验收边界还不完整，当前不能启动持续处理。"
        await commit_task_control_message(
            commit_assistant_message,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            answer_source=f"{answer_source}.invalid_contract",
            api_protocol_prefix_messages=_api_protocol_prefix_from_action_request(action_request),
        )
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
        task_id=task_selection.get("selected_task_id") or task_selection.get("task_id") or f"task:{turn_id}",
        max_steps=max_steps,
        commit_assistant_message=commit_assistant_message,
        initialize_task_todo=initialize_task_todo,
        schedule_task_run_executor=schedule_task_run_executor,
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
) -> AsyncIterator[dict[str, Any]]:
    api_protocol_prefix_messages = _api_protocol_prefix_from_action_request(action_request)
    current_task = current_session_task_run(runtime_host, session_id=session_id)
    if current_task is not None:
        async for event in _emit_current_session_task_handoff(
            runtime_host=runtime_host,
            current_task=current_task,
            session_id=session_id,
            turn_id=turn_id,
            answer_source=answer_source,
            runtime_branch=runtime_branch,
            commit_assistant_message=commit_assistant_message,
            api_protocol_prefix_messages=api_protocol_prefix_messages,
        ):
            yield event
        return
    agent_profile_ref = str(getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent")
    opening_content = task_run_opening_message(
        action_request=action_request,
        contract=contract.to_dict(),
        fallback=_task_opening_fallback(contract.to_dict()),
    )
    yield assistant_text_event(
        content=opening_content,
        answer_channel="task_control",
        answer_source=answer_source,
    )
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
    )
    for event in lifecycle_events:
        yield event
    started_summary = "已接手任务，正在整理执行步骤。"
    started_summary_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "step": "task_lifecycle_started",
            "status": "running",
            "summary": started_summary,
            "public_progress_note": started_summary,
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
        content = opening_content
        await commit_task_control_message(
            commit_assistant_message,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            answer_source=f"{answer_source}.supervision",
            api_protocol_prefix_messages=api_protocol_prefix_messages,
        )
        yield final_answer_event(
            content=content,
            answer_channel="task_control",
            answer_source=f"{answer_source}.supervision",
            terminal_reason="task_launch_supervision",
            extra={
                "runtime_branch": dict(runtime_branch or {}),
                "task_run": {"task_run_id": gated_task.task_run_id, "status": gated_task.status},
                **_active_turn_event_payload(runtime_host=runtime_host, session_id=session_id),
            },
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
        await commit_task_control_message(
            commit_assistant_message,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            answer_source=f"{answer_source}.schedule_failed",
            api_protocol_prefix_messages=api_protocol_prefix_messages,
        )
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
    scheduled_summary = "任务执行器已接管，正在推进第一步。"
    scheduled_summary_event = runtime_host.event_log.append(
        task_run.task_run_id,
        "step_summary_recorded",
        payload={
            "step": "task_executor_scheduled",
            "status": "running",
            "summary": scheduled_summary,
            "public_progress_note": scheduled_summary,
            "presentation_source": "task_lifecycle.schedule",
        },
        refs={"task_run_ref": task_run.task_run_id, "turn_ref": turn_id},
    )
    yield {"type": "task_run_lifecycle_event", "event": scheduled_summary_event.to_dict()}
    content = opening_content
    await commit_task_control_message(
        commit_assistant_message,
        session_id=session_id,
        turn_id=turn_id,
        content=content,
        answer_source=answer_source,
        api_protocol_prefix_messages=api_protocol_prefix_messages,
    )
    yield final_answer_event(
        content=content,
        answer_channel="task_control",
        answer_source=answer_source,
        terminal_reason="task_executor_scheduled",
        extra={
            "runtime_branch": dict(runtime_branch or {}),
            "task_run": {"task_run_id": task_run.task_run_id, "status": "running"},
            **_active_turn_event_payload(runtime_host=runtime_host, session_id=session_id),
        },
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


async def commit_task_control_message(
    commit_assistant_message: CommitAssistantMessage,
    *,
    session_id: str,
    turn_id: str,
    content: str,
    answer_source: str,
    api_protocol_prefix_messages: list[dict[str, Any]] | None = None,
) -> None:
    protocol_messages = [dict(item) for item in list(api_protocol_prefix_messages or []) if isinstance(item, dict)]
    if protocol_messages:
        protocol_messages.append({"role": "assistant", "content": content, "turn_id": turn_id})
    decision = canonical_output_decision_for_final_text(
        content,
        answer_channel="task_control",
        answer_source=answer_source,
        execution_posture="task_control",
    )
    await commit_assistant_message(
        session_id,
        {
            "role": "assistant",
            "content": decision.content,
            "turn_id": turn_id,
            **decision.to_payload(),
            "api_protocol_messages": protocol_messages,
        },
    )


def assistant_text_event(*, content: str, answer_channel: str, answer_source: str) -> dict[str, Any]:
    return {
        "type": "assistant_text",
        "content": str(content or "").strip(),
        "answer_channel": answer_channel,
        "answer_source": answer_source,
    }


def _active_turn_event_payload(*, runtime_host: Any | None, session_id: str) -> dict[str, Any]:
    active_registry = getattr(runtime_host, "active_turn_registry", None) if runtime_host is not None else None
    if active_registry is None:
        return {}
    try:
        active_turn = active_registry.snapshot(session_id)
    except Exception:
        active_turn = None
    if active_turn is None:
        return {}
    return {"active_turn": active_turn.to_dict() if hasattr(active_turn, "to_dict") else dict(active_turn)}


def _api_protocol_prefix_from_action_request(action_request: ModelActionRequest) -> list[dict[str, Any]]:
    diagnostics = dict(action_request.diagnostics or {})
    return [
        dict(item)
        for item in list(diagnostics.get("api_protocol_prefix_messages") or [])
        if isinstance(item, dict)
    ]


def task_run_opening_message(*, action_request: ModelActionRequest, contract: dict[str, Any], fallback: str) -> str:
    """Return the user-visible assistant prose for a task handoff."""

    note = _first_text(getattr(action_request, "public_progress_note", ""))
    if note and not _is_generic_task_opening(note):
        return note
    goal = _first_text(contract.get("user_visible_goal"), contract.get("task_run_goal"))
    if goal:
        return f"我会开始处理：{goal}"
    return str(fallback or "").strip()


def _task_opening_fallback(contract: dict[str, Any]) -> str:
    goal = _first_text(contract.get("user_visible_goal"), contract.get("task_run_goal"))
    if goal:
        return f"我会开始处理：{goal}"
    return "我会开始处理这个任务，并把关键进展更新在这里。"


def _is_generic_task_opening(value: str) -> bool:
    normalized = " ".join(str(value or "").split()).strip()
    return normalized in {
        "正在建立任务运行。",
        "正在处理当前请求。",
        "已接收明确任务合同，正在启动任务。",
    }


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


def _runtime_contract_from_task_run_contract(
    contract: TaskRunContract,
    *,
    selected_skill_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    runtime_profile = dict(contract.runtime_profile or {})
    allowed_operations = _explicit_allowed_operations_from_contract(contract)
    runtime_contract = {
        "runtime_profile": runtime_profile,
        "authority": "harness.loop.task_run_runtime_contract",
    }
    if allowed_operations is not None:
        runtime_contract["allowed_operations"] = list(allowed_operations)
    if contract.task_environment_id:
        runtime_contract["task_environment_id"] = contract.task_environment_id
    if selected_skill_ids:
        runtime_contract["selected_skill_ids"] = list(selected_skill_ids)
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
            "output_contract": {
                "required_artifacts": [dict(item) for item in contract.required_artifacts],
                "required_verifications": [dict(item) for item in contract.required_verifications],
                "completion_criteria": list(contract.completion_criteria),
            },
            "acceptance_policy": dict(contract.acceptance_policy or {}),
            "recovery_policy": dict(contract.recovery_policy or {}),
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
