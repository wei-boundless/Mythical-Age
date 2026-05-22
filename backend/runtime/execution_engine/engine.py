from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .event_translation import (
    append_executor_error_observation,
    append_model_answer_observation,
    append_simple_executor_event,
)
from .tool_loop import handle_tool_call_requested_event


@dataclass(slots=True)
class ModelTurnEvent:
    raw_event: dict[str, Any]
    runtime_events: list[Any]


@dataclass(slots=True)
class RuntimeExecutionEngine:
    """Run model turns and translate executor events into runtime trace events."""

    event_log: Any
    definitions_by_name: dict[str, Any]
    operation_gate: Any
    permission_mode_provider: Callable[[], str]
    root_dir: Any
    execution_store: Any
    record_execution_event: Callable[..., Any]
    build_pending_approval_state: Callable[..., dict[str, Any]]
    list_parent_agent_runs: Callable[[str], list[Any]]
    build_delegation_request: Callable[..., Any]
    execute_delegation: Callable[..., Any]

    async def translate_event(
        self,
        *,
        task_run_id: str,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        adopted_resource_policy: Any,
        current_step_id: str,
        runtime_context_manager: Any,
        model_response_executor: Any,
        tool_runtime_executor: Any | None,
        event: dict[str, Any],
        allowed_search_sources: set[str] | None = None,
        sandbox_policy: dict[str, Any] | None = None,
    ) -> list[Any]:
        return await translate_executor_event(
            event_log=self.event_log,
            task_run_id=task_run_id,
            user_message=user_message,
            task_id=task_id,
            task_operation=task_operation,
            adopted_resource_policy=adopted_resource_policy,
            current_step_id=current_step_id,
            runtime_context_manager=runtime_context_manager,
            model_response_executor=model_response_executor,
            tool_runtime_executor=tool_runtime_executor,
            event=event,
            definitions_by_name=self.definitions_by_name,
            operation_gate=self.operation_gate,
            permission_mode=self.permission_mode_provider(),
            root_dir=self.root_dir,
            allowed_search_sources=allowed_search_sources,
            sandbox_policy=sandbox_policy,
            execution_store=self.execution_store,
            record_execution_event=self.record_execution_event,
            build_pending_approval_state=self.build_pending_approval_state,
            list_parent_agent_runs=self.list_parent_agent_runs,
            build_delegation_request=self.build_delegation_request,
            execute_delegation=self.execute_delegation,
        )

    async def stream_model_turn(
        self,
        *,
        task_run_id: str,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        adopted_resource_policy: Any,
        current_step_id_provider: Callable[[], str],
        runtime_context_manager: Any,
        model_response_executor: Any,
        tool_runtime_executor: Any | None,
        model_messages: list[Any],
        directive: Any,
        tool_instances: list[Any],
        model_stream_policy: dict[str, Any] | None = None,
        model_spec: Any = None,
        allowed_search_sources: set[str] | None = None,
        sandbox_policy: dict[str, Any] | None = None,
    ):
        async for raw_event in self.stream_raw_model_events(
            user_message=user_message,
            model_response_executor=model_response_executor,
            model_messages=model_messages,
            directive=directive,
            tool_instances=tool_instances,
            model_stream_policy=model_stream_policy,
            model_spec=model_spec,
        ):
            runtime_events = await self.translate_event(
                task_run_id=task_run_id,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=adopted_resource_policy,
                current_step_id=str(current_step_id_provider() or ""),
                runtime_context_manager=runtime_context_manager,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                event=raw_event,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
            )
            yield ModelTurnEvent(raw_event=raw_event, runtime_events=list(runtime_events or []))

    async def stream_raw_model_events(
        self,
        *,
        user_message: str,
        model_response_executor: Any,
        model_messages: list[Any],
        directive: Any,
        tool_instances: list[Any],
        model_stream_policy: dict[str, Any] | None = None,
        model_spec: Any = None,
        tool_call_options: dict[str, Any] | None = None,
    ):
        stream_kwargs = {
            "user_message": user_message,
            "model_messages": model_messages,
            "directive": directive,
            "tool_instances": tool_instances,
            "model_stream_policy": model_stream_policy,
            "model_spec": model_spec,
        }
        if tool_call_options is not None:
            stream_kwargs["tool_call_options"] = tool_call_options
        async for event in model_response_executor.stream(**stream_kwargs):
            yield dict(event or {})


async def translate_executor_event(
    *,
    event_log: Any,
    task_run_id: str,
    user_message: str,
    task_id: str,
    task_operation: dict[str, Any],
    adopted_resource_policy: Any,
    current_step_id: str,
    runtime_context_manager: Any,
    model_response_executor: Any,
    tool_runtime_executor: Any | None,
    event: dict[str, Any],
    definitions_by_name: dict[str, Any],
    operation_gate: Any,
    permission_mode: str,
    root_dir: Any,
    allowed_search_sources: set[str] | None = None,
    sandbox_policy: dict[str, Any] | None = None,
    execution_store: Any = None,
    record_execution_event: Callable[..., Any] | None = None,
    build_pending_approval_state: Callable[..., dict[str, Any]] | None = None,
    list_parent_agent_runs: Callable[[str], list[Any]] | None = None,
    build_delegation_request: Callable[..., Any] | None = None,
    execute_delegation: Callable[..., Any] | None = None,
) -> list[Any]:
    event_type = str(event.get("type") or "")
    simple_events = append_simple_executor_event(event_log, task_run_id, event)
    if simple_events is not None:
        return simple_events
    if event_type == "answer_candidate":
        return append_model_answer_observation(
            event_log=event_log,
            runtime_context_manager=runtime_context_manager,
            task_run_id=task_run_id,
            event=event,
        )
    if event_type == "tool_call_requested":
        if (
            execution_store is None
            or record_execution_event is None
            or build_pending_approval_state is None
            or list_parent_agent_runs is None
            or build_delegation_request is None
            or execute_delegation is None
        ):
            raise ValueError("tool_call_requested requires execution-engine dispatch dependencies")
        return await handle_tool_call_requested_event(
            event_log=event_log,
            runtime_context_manager=runtime_context_manager,
            task_run_id=task_run_id,
            event=event,
            current_step_id=current_step_id,
            task_id=task_id,
            task_operation=task_operation,
            adopted_resource_policy=adopted_resource_policy,
            user_message=user_message,
            model_response_executor=model_response_executor,
            tool_runtime_executor=tool_runtime_executor,
            definitions_by_name=definitions_by_name,
            operation_gate=operation_gate,
            permission_mode=permission_mode,
            root_dir=root_dir,
            allowed_search_sources=allowed_search_sources,
            sandbox_policy=sandbox_policy,
            execution_store=execution_store,
            record_execution_event=record_execution_event,
            build_pending_approval_state=build_pending_approval_state,
            list_parent_agent_runs=list_parent_agent_runs,
            build_delegation_request=build_delegation_request,
            execute_delegation=execute_delegation,
        )
    if event_type == "error":
        return append_executor_error_observation(
            event_log=event_log,
            runtime_context_manager=runtime_context_manager,
            task_run_id=task_run_id,
            event=event,
        )
    return []
