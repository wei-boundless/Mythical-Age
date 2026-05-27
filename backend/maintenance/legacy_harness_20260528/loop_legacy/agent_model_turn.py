from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage

from harness.loop_legacy.agent_execution.model_loop import ModelToolCallAccumulator
from runtime.memory.observation_aggregator import ObservationAggregator
from runtime.shared.tool_repetition_guard import ToolRepetitionGuard
from .agent_event_application import ModelTurnApplicationState, apply_model_turn_event


@dataclass(slots=True)
class AgentModelTurnInput:
    runtime_host: Any
    execution_engine: Any
    application: ModelTurnApplicationState
    task_run_id: str
    user_message: str
    task_id: str
    task_operation: dict[str, Any]
    resource_policy: Any
    current_step_id_provider: Callable[[], str]
    runtime_context_manager: Any
    model_response_executor: Any
    tool_runtime_executor: Any | None
    model_messages: list[Any]
    directive: Any
    runtime_tool_instances: list[Any]
    model_stream_policy: dict[str, Any] | None
    resolved_model_spec: Any | None
    allowed_search_sources: set[str]
    sandbox_policy: dict[str, Any]
    file_management_policy: dict[str, Any]
    start_task_run: Any
    tool_call_accumulator: ModelToolCallAccumulator
    collected_tool_messages: list[ToolMessage]
    observation_aggregator: ObservationAggregator
    current_bundle_items: list[dict[str, Any]]
    tool_repetition_guard: ToolRepetitionGuard | None
    selected_recipe_payload: dict[str, Any]
    preserve_answer_metadata: bool = False
    apply_tool_call_transition: bool = False
    apply_projection_only_when_present: bool = False
    fail_running_step_on_executor_error: bool = False
    fail_running_step_on_loop_error: bool = False


async def run_agent_model_turn(model_turn_input: AgentModelTurnInput) -> AsyncIterator[dict[str, Any]]:
    """Execute one model turn inside AgentHarness and apply loop effects."""

    item = model_turn_input
    async for model_turn_event in item.execution_engine.stream_model_turn(
        task_run_id=item.task_run_id,
        user_message=item.user_message,
        task_id=item.task_id,
        task_operation=item.task_operation,
        adopted_resource_policy=item.resource_policy,
        current_step_id_provider=item.current_step_id_provider,
        runtime_context_manager=item.runtime_context_manager,
        model_response_executor=item.model_response_executor,
        tool_runtime_executor=item.tool_runtime_executor,
        model_messages=list(item.model_messages),
        directive=item.directive,
        tool_instances=item.runtime_tool_instances,
        model_stream_policy=item.model_stream_policy,
        model_spec=item.resolved_model_spec,
        allowed_search_sources=item.allowed_search_sources,
        sandbox_policy=item.sandbox_policy,
        file_management_policy=item.file_management_policy,
    ):
        async for emitted_event in apply_model_turn_event(
            item.runtime_host,
            application=item.application,
            model_turn_event=model_turn_event,
            start_task_run=item.start_task_run,
            tool_call_accumulator=item.tool_call_accumulator,
            collected_tool_messages=item.collected_tool_messages,
            observation_aggregator=item.observation_aggregator,
            current_bundle_items=item.current_bundle_items,
            tool_repetition_guard=item.tool_repetition_guard,
            selected_recipe_payload=item.selected_recipe_payload,
            user_message=item.user_message,
            preserve_answer_metadata=item.preserve_answer_metadata,
            apply_tool_call_transition=item.apply_tool_call_transition,
            apply_projection_only_when_present=item.apply_projection_only_when_present,
            fail_running_step_on_executor_error=item.fail_running_step_on_executor_error,
            fail_running_step_on_loop_error=item.fail_running_step_on_loop_error,
        ):
            yield emitted_event
        if item.application.approval_waiting:
            return



