from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable

from harness.loop.model_action_protocol import ModelActionRequest
from harness.loop.presentation import error_event, final_answer_event
from harness.loop.task_lifecycle import (
    TaskRunContract,
    contract_from_action_request,
    start_task_lifecycle,
    task_launch_supervision_policy,
    wait_task_launch_supervision,
)


CommitAssistantMessage = Callable[[str, dict[str, Any]], Awaitable[Any]]
InitializeTaskTodo = Callable[[str, str, dict[str, Any]], dict[str, Any] | None]
ScheduleTaskRunExecutor = Callable[..., Any]


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
    turn_route: Any,
    answer_source: str,
    scheduler: str,
    max_steps: int,
    commit_assistant_message: CommitAssistantMessage,
    initialize_task_todo: InitializeTaskTodo,
    schedule_task_run_executor: ScheduleTaskRunExecutor,
) -> AsyncIterator[dict[str, Any]]:
    contract, contract_errors = contract_from_action_request(
        action_request,
        packet_ref=str(action_request.diagnostics.get("packet_ref") or f"native-turn:{turn_id}"),
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
        turn_route=turn_route,
        answer_source=answer_source,
        scheduler=scheduler,
        task_id=task_selection.get("selected_task_id") or task_selection.get("task_id") or f"task:{turn_id}",
        scheduled_status_text="我会按这个目标继续推进。",
        scheduled_control_text="你可以直接说暂停、继续或停止；进展会汇总在当前会话里。",
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
    turn_route: Any,
    answer_source: str,
    scheduler: str,
    task_id: str,
    scheduled_status_text: str,
    scheduled_control_text: str,
    max_steps: int,
    commit_assistant_message: CommitAssistantMessage,
    initialize_task_todo: InitializeTaskTodo,
    schedule_task_run_executor: ScheduleTaskRunExecutor,
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
    )
    for event in lifecycle_events:
        yield event

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
        content = task_run_handoff_content(
            contract=contract.to_dict(),
            status_text=str(launch_gate_policy.get("user_prompt") or "任务合同已就绪，正在等待确认后继续。"),
            control_text="确认前，我会先停在这里。",
        )
        await commit_task_control_message(
            commit_assistant_message,
            session_id=session_id,
            turn_id=turn_id,
            content=content,
            answer_source=f"{answer_source}.supervision",
        )
        yield final_answer_event(
            content=content,
            answer_source=f"{answer_source}.supervision",
            terminal_reason="task_launch_supervision",
            extra={
                "turn_route": turn_route.to_dict(),
                "task_run": {"task_run_id": gated_task.task_run_id, "status": gated_task.status},
            },
        )
        return

    schedule_task_run_executor(
        task_run.task_run_id,
        scheduler=scheduler,
        turn_id=turn_id,
        max_steps=max_steps,
    )
    content = task_run_handoff_content(
        contract=contract.to_dict(),
        status_text=scheduled_status_text,
        control_text=scheduled_control_text,
    )
    await commit_task_control_message(
        commit_assistant_message,
        session_id=session_id,
        turn_id=turn_id,
        content=content,
        answer_source=answer_source,
    )
    yield final_answer_event(
        content=content,
        answer_source=answer_source,
        terminal_reason="task_executor_scheduled",
        extra={
            "turn_route": turn_route.to_dict(),
            "task_run": {"task_run_id": task_run.task_run_id, "status": "running"},
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


async def commit_task_control_message(
    commit_assistant_message: CommitAssistantMessage,
    *,
    session_id: str,
    turn_id: str,
    content: str,
    answer_source: str,
) -> None:
    await commit_assistant_message(
        session_id,
        {
            "role": "assistant",
            "content": content,
            "turn_id": turn_id,
            "answer_channel": "task_control",
            "answer_source": answer_source,
            "answer_canonical_state": "final",
            "answer_persist_policy": "persist_canonical",
            "answer_finalization_policy": "assistant_final",
        },
    )


def task_run_handoff_content(*, contract: dict[str, Any], status_text: str, control_text: str) -> str:
    goal = _first_contract_text(
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
        "我会把这件事继续推进。",
    )
    criteria = list(_contract_string_tuple(contract.get("completion_criteria")))[:2]
    artifacts = [
        str(item.get("user_visible_name") or item.get("artifact_kind") or item).strip()
        for item in list(contract.get("required_artifacts") or [])[:2]
        if isinstance(item, dict)
    ]
    verifications = [
        str(item.get("user_visible_name") or item.get("verification_kind") or item).strip()
        for item in list(contract.get("required_verifications") or [])[:2]
        if isinstance(item, dict)
    ]
    lines = [f"我会按这个目标推进：{goal}"]
    scope_parts: list[str] = []
    if criteria:
        scope_parts.append("完成标准：" + "；".join(criteria))
    if artifacts:
        scope_parts.append("产物：" + "、".join(item for item in artifacts if item))
    if verifications:
        scope_parts.append("验证：" + "、".join(item for item in verifications if item))
    if scope_parts:
        lines.append("；".join(scope_parts) + "。")
    lines.append(status_text.strip())
    if control_text.strip():
        lines.append(control_text.strip())
    return "\n".join(line for line in lines if line.strip())


def _contract_string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple, set)):
        return ()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return tuple(result)


def _first_contract_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
