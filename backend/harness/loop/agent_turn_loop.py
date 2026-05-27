from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage

from task_system.tasks.run_models import task_run_step_count

from harness.loop.agent_execution.followup_cycle import build_initial_followup_messages, build_next_followup_messages
from harness.loop.agent_execution.model_loop import ModelToolCallAccumulator
from runtime.memory.observation_aggregator import ObservationAggregator
from runtime.shared.loop_control import check_runtime_loop_control
from runtime.shared.models import RuntimeLoopState
from runtime.shared.tool_repetition_guard import ToolRepetitionGuard
from harness.runtime.context import bundle_items_from_runtime_contract, is_retrieval_task_mode
from .agent_event_application import ModelTurnApplicationState
from .agent_model_turn import AgentModelTurnInput, run_agent_model_turn


@dataclass(slots=True)
class AgentTurnLoopInput:
    runtime_host: Any
    state: RuntimeLoopState
    runtime_task_ledger: Any
    result_refs: list[str]
    initial_final_main_context: dict[str, Any]
    initial_final_task_summary_refs: list[dict[str, Any]]
    task_id: str
    user_message: str
    task_operation: dict[str, Any]
    resource_policy: Any
    runtime_context_manager: Any
    model_response_executor: Any
    tool_runtime_executor: Any | None
    context_model_messages: list[Any]
    directive: Any
    runtime_tool_instances: list[Any]
    model_stream_policy: dict[str, Any] | None
    resolved_model_spec: Any | None
    allowed_search_sources: set[str]
    sandbox_policy: dict[str, Any]
    file_management_policy: dict[str, Any]
    start_task_run: Any
    selected_recipe_payload: dict[str, Any]
    task_spec_payload: dict[str, Any]
    effective_limits: Any
    task_contract_ref: str


@dataclass(slots=True)
class AgentTurnLoopResult:
    state: RuntimeLoopState
    runtime_task_ledger: Any
    result_refs: list[str]
    final_content: str
    final_answer_metadata: dict[str, Any]
    run_outcome: dict[str, Any]
    terminal_reason: str
    final_main_context: dict[str, Any]
    final_task_summary_refs: list[dict[str, Any]]
    final_bundle_summary_refs: list[dict[str, Any]]
    current_bundle_items: list[dict[str, Any]]
    executed_bundle_ordinals: list[int]
    observation_aggregator: ObservationAggregator
    tool_observation_count: int
    turn_count: int
    tool_call_count: int
    approval_waiting: bool = False
    retrieval_followup_observed: bool = False


async def run_agent_turn_loop(
    turn_input: AgentTurnLoopInput,
) -> AsyncIterator[dict[str, Any] | AgentTurnLoopResult]:
    """Execute the model/tool turn loop for one already-authorized agent invocation."""

    item = turn_input
    state = item.state
    runtime_task_ledger = item.runtime_task_ledger
    result_refs = item.result_refs
    final_content = ""
    final_answer_metadata: dict[str, Any] = {}
    run_outcome: dict[str, Any] = {}
    terminal_reason = "completed"
    preserve_final_answer_metadata = False

    final_main_context: dict[str, Any] = dict(item.initial_final_main_context or {})
    final_task_summary_refs: list[dict[str, Any]] = [
        dict(entry) for entry in list(item.initial_final_task_summary_refs or [])
    ]
    final_bundle_summary_refs: list[dict[str, Any]] = []
    observation_aggregator = ObservationAggregator()
    current_bundle_items = bundle_items_from_runtime_contract(
        task_spec_payload=item.task_spec_payload,
    )
    tool_call_accumulator = ModelToolCallAccumulator()
    tool_messages: list[ToolMessage] = []
    tool_observation_count = 0
    executed_bundle_ordinals: list[int] = []
    tool_repetition_guard = ToolRepetitionGuard()
    repeated_tool_halt = False

    executor_event = item.runtime_host.event_log.append(
        state.task_run_id,
        "executor_started",
        payload={"executor_type": "model", "runtime_channel": "agent_runtime"},
        refs={"task_contract_ref": item.task_contract_ref, "directive_ref": item.directive.directive_id},
    )
    yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

    turn_application = ModelTurnApplicationState(
        loop_state=state,
        runtime_task_ledger=runtime_task_ledger,
        result_refs=result_refs,
        final_content=final_content,
        final_answer_metadata=final_answer_metadata,
        terminal_reason=terminal_reason,
        final_main_context=final_main_context,
        final_task_summary_refs=final_task_summary_refs,
        final_bundle_summary_refs=final_bundle_summary_refs,
        tool_observation_count=tool_observation_count,
        executed_bundle_ordinals=executed_bundle_ordinals,
        repeated_tool_halt=repeated_tool_halt,
    )
    async for emitted_event in run_agent_model_turn(
        AgentModelTurnInput(
            runtime_host=item.runtime_host,
            execution_engine=item.runtime_host.execution_engine,
            application=turn_application,
            task_run_id=state.task_run_id,
            user_message=item.user_message,
            task_id=item.task_id,
            task_operation=item.task_operation,
            resource_policy=item.resource_policy,
            current_step_id_provider=lambda: (
                turn_application.runtime_task_ledger.current_step_id
                if turn_application.runtime_task_ledger is not None
                else turn_application.loop_state.current_step_id
            ),
            runtime_context_manager=item.runtime_context_manager,
            model_response_executor=item.model_response_executor,
            tool_runtime_executor=item.tool_runtime_executor,
            model_messages=list(item.context_model_messages),
            directive=item.directive,
            runtime_tool_instances=item.runtime_tool_instances,
            model_stream_policy=item.model_stream_policy,
            resolved_model_spec=item.resolved_model_spec,
            allowed_search_sources=item.allowed_search_sources,
            sandbox_policy=item.sandbox_policy,
            file_management_policy=item.file_management_policy,
            start_task_run=item.start_task_run,
            tool_call_accumulator=tool_call_accumulator,
            collected_tool_messages=tool_messages,
            observation_aggregator=observation_aggregator,
            current_bundle_items=current_bundle_items,
            tool_repetition_guard=tool_repetition_guard,
            selected_recipe_payload=item.selected_recipe_payload,
            preserve_answer_metadata=preserve_final_answer_metadata,
            apply_tool_call_transition=True,
            apply_projection_only_when_present=True,
        )
    ):
        yield emitted_event

    state = turn_application.loop_state
    runtime_task_ledger = turn_application.runtime_task_ledger
    result_refs = turn_application.result_refs
    final_content = turn_application.final_content
    final_answer_metadata = dict(turn_application.final_answer_metadata)
    run_outcome = _run_outcome_from_answer_metadata(final_answer_metadata)
    terminal_reason = turn_application.terminal_reason
    final_main_context = dict(turn_application.final_main_context)
    final_task_summary_refs = [dict(entry) for entry in turn_application.final_task_summary_refs]
    final_bundle_summary_refs = [dict(entry) for entry in turn_application.final_bundle_summary_refs]
    tool_observation_count = turn_application.tool_observation_count
    executed_bundle_ordinals = list(turn_application.executed_bundle_ordinals)
    repeated_tool_halt = turn_application.repeated_tool_halt

    turn_count = 1
    model_call_count = 1
    retrieval_followup_observed = False
    if turn_application.approval_waiting:
        yield _turn_loop_result(
            state=state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_content=final_content,
            final_answer_metadata=final_answer_metadata,
            run_outcome=run_outcome,
            terminal_reason=terminal_reason,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            final_bundle_summary_refs=final_bundle_summary_refs,
            current_bundle_items=current_bundle_items,
            executed_bundle_ordinals=executed_bundle_ordinals,
            observation_aggregator=observation_aggregator,
            tool_observation_count=tool_observation_count,
            turn_count=turn_count,
            tool_call_count=len(tool_call_accumulator.pending_tool_calls),
            approval_waiting=True,
            retrieval_followup_observed=retrieval_followup_observed,
        )
        return

    if len(tool_call_accumulator.pending_tool_calls) > 1 and terminal_reason == "completed":
        final_content = ""
        final_answer_metadata = {}
        preserve_final_answer_metadata = False

    followup_messages: list[Any] = []
    if tool_call_accumulator.pending_tool_calls and tool_messages and terminal_reason == "completed":
        followup_messages = build_initial_followup_messages(
            context_model_messages=list(item.context_model_messages),
            tool_call_accumulator=tool_call_accumulator,
            tool_messages=tool_messages,
            user_message=item.user_message,
            aggregation=observation_aggregator.snapshot(),
            current_bundle_items=current_bundle_items,
            remaining_model_calls=max(item.effective_limits.max_model_calls - model_call_count, 0),
        )

    while followup_messages and terminal_reason == "completed":
        turn_count += 1
        model_call_count += 1
        loop_state_for_control = RuntimeLoopState(
            task_run_id=state.task_run_id,
            status="running",
            transition="continue_after_tool_result",
            turn_count=turn_count,
            step_count=task_run_step_count(runtime_task_ledger),
            current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
            agent_id=state.agent_id,
            agent_profile_id=state.agent_profile_id,
            runtime_lane=state.runtime_lane,
            task_agent_binding_ref=state.task_agent_binding_ref,
            task_template_id=state.task_template_id,
            task_spec_ref=state.task_spec_ref,
            task_result_ref=state.task_result_ref,
            skill_workflow_ref=state.skill_workflow_ref,
            health_issue_ref=state.health_issue_ref,
            memory_state_ref=state.memory_state_ref,
            context_snapshot_ref=state.context_snapshot_ref,
            projection_ref=state.projection_ref,
            prompt_manifest_ref=state.prompt_manifest_ref,
            token_pressure=dict(state.token_pressure),
            diagnostics=dict(state.diagnostics),
        )
        followup_control = check_runtime_loop_control(
            loop_state_for_control,
            limits=item.effective_limits,
            started_at=item.start_task_run.created_at,
            model_call_count=model_call_count - 1,
            event_count=len(item.runtime_host.event_log.list_events(state.task_run_id)),
        )
        followup_control_event = item.runtime_host.event_log.append(
            state.task_run_id,
            "loop_control_checked",
            payload={"control": followup_control.to_dict()},
            refs={"task_contract_ref": item.task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": followup_control_event.to_dict()}
        yield {"type": "runtime_loop_control", "control": followup_control.to_dict()}
        if not followup_control.allowed:
            terminal_reason = followup_control.reason
            if not final_content:
                final_answer_metadata = {
                    "answer_channel": "orchestration_fail_closed",
                    "answer_source": "runtime_loop_control",
                    "answer_canonical_state": "no_agent_final_answer",
                    "answer_persist_policy": "persist_debug_only",
                    "answer_finalization_policy": "none",
                    "answer_fallback_reason": str(followup_control.reason or "runtime_loop_control"),
                }
            break

        followup_event = item.runtime_host.event_log.append(
            state.task_run_id,
            "loop_iteration_started",
            payload={
                "transition": "continue_after_tool_result",
                "turn_count": turn_count,
                "step_count": task_run_step_count(runtime_task_ledger),
                "tool_result_count": len([message for message in followup_messages if isinstance(message, ToolMessage)]),
            },
        )
        yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
        state = item.runtime_host._state_with_task_run_ledger(
            state,
            runtime_task_ledger,
            transition="continue_after_tool_result",
            result_refs=result_refs,
        )
        next_tool_call_accumulator = ModelToolCallAccumulator()
        next_tool_messages: list[ToolMessage] = []
        turn_application = ModelTurnApplicationState(
            loop_state=state,
            runtime_task_ledger=runtime_task_ledger,
            result_refs=result_refs,
            final_content=final_content,
            final_answer_metadata=final_answer_metadata,
            terminal_reason=terminal_reason,
            final_main_context=final_main_context,
            final_task_summary_refs=final_task_summary_refs,
            final_bundle_summary_refs=final_bundle_summary_refs,
            tool_observation_count=tool_observation_count,
            executed_bundle_ordinals=executed_bundle_ordinals,
            repeated_tool_halt=repeated_tool_halt,
        )
        async for emitted_event in run_agent_model_turn(
            AgentModelTurnInput(
                runtime_host=item.runtime_host,
                execution_engine=item.runtime_host.execution_engine,
                application=turn_application,
                task_run_id=state.task_run_id,
                user_message=item.user_message,
                task_id=item.task_id,
                task_operation=item.task_operation,
                resource_policy=item.resource_policy,
                current_step_id_provider=lambda: (
                    turn_application.runtime_task_ledger.current_step_id
                    if turn_application.runtime_task_ledger is not None
                    else turn_application.loop_state.current_step_id
                ),
                runtime_context_manager=item.runtime_context_manager,
                model_response_executor=item.model_response_executor,
                tool_runtime_executor=item.tool_runtime_executor,
                model_messages=followup_messages,
                directive=item.directive,
                runtime_tool_instances=item.runtime_tool_instances,
                model_stream_policy=item.model_stream_policy,
                resolved_model_spec=item.resolved_model_spec,
                allowed_search_sources=item.allowed_search_sources,
                sandbox_policy=item.sandbox_policy,
                file_management_policy=item.file_management_policy,
                start_task_run=item.start_task_run,
                tool_call_accumulator=next_tool_call_accumulator,
                collected_tool_messages=next_tool_messages,
                observation_aggregator=observation_aggregator,
                current_bundle_items=current_bundle_items,
                tool_repetition_guard=tool_repetition_guard,
                selected_recipe_payload=item.selected_recipe_payload,
                preserve_answer_metadata=preserve_final_answer_metadata,
                fail_running_step_on_executor_error=True,
                fail_running_step_on_loop_error=True,
            )
        ):
            yield emitted_event

        state = turn_application.loop_state
        runtime_task_ledger = turn_application.runtime_task_ledger
        result_refs = turn_application.result_refs
        final_content = turn_application.final_content
        final_answer_metadata = dict(turn_application.final_answer_metadata)
        run_outcome = _run_outcome_from_answer_metadata(final_answer_metadata, fallback=run_outcome)
        terminal_reason = turn_application.terminal_reason
        final_main_context = dict(turn_application.final_main_context)
        final_task_summary_refs = [dict(entry) for entry in turn_application.final_task_summary_refs]
        final_bundle_summary_refs = [dict(entry) for entry in turn_application.final_bundle_summary_refs]
        tool_observation_count = turn_application.tool_observation_count
        executed_bundle_ordinals = list(turn_application.executed_bundle_ordinals)
        repeated_tool_halt = turn_application.repeated_tool_halt

        if turn_application.approval_waiting:
            yield _turn_loop_result(
                state=state,
                runtime_task_ledger=runtime_task_ledger,
                result_refs=result_refs,
                final_content=final_content,
                final_answer_metadata=final_answer_metadata,
                run_outcome=run_outcome,
                terminal_reason=terminal_reason,
                final_main_context=final_main_context,
                final_task_summary_refs=final_task_summary_refs,
                final_bundle_summary_refs=final_bundle_summary_refs,
                current_bundle_items=current_bundle_items,
                executed_bundle_ordinals=executed_bundle_ordinals,
                observation_aggregator=observation_aggregator,
                tool_observation_count=tool_observation_count,
                turn_count=turn_count,
                tool_call_count=len(tool_call_accumulator.pending_tool_calls),
                approval_waiting=True,
                retrieval_followup_observed=retrieval_followup_observed,
            )
            return

        if (
            next_tool_call_accumulator.pending_tool_calls
            and next_tool_messages
            and terminal_reason == "completed"
            and tool_observation_count > 0
            and is_retrieval_task_mode(str(item.task_spec_payload.get("task_mode") or ""))
        ):
            retrieval_followup_observed = True
        if next_tool_call_accumulator.pending_tool_calls and next_tool_messages and terminal_reason == "completed":
            if repeated_tool_halt:
                terminal_reason = "repeated_tool_halt"
                if not final_content:
                    final_answer_metadata = {
                        "answer_channel": "orchestration_fail_closed",
                        "answer_source": "runtime_loop_control",
                        "answer_canonical_state": "no_agent_final_answer",
                        "answer_persist_policy": "persist_debug_only",
                        "answer_finalization_policy": "none",
                        "answer_fallback_reason": "repeated_tool_halt",
                    }
                followup_messages = []
                break
            followup_messages = build_next_followup_messages(
                previous_messages=followup_messages,
                tool_call_accumulator=next_tool_call_accumulator,
                tool_messages=next_tool_messages,
                user_message=item.user_message,
                aggregation=observation_aggregator.snapshot(),
                current_bundle_items=current_bundle_items,
                remaining_model_calls=max(item.effective_limits.max_model_calls - model_call_count, 0),
            )
            continue
        followup_messages = []

    yield _turn_loop_result(
        state=state,
        runtime_task_ledger=runtime_task_ledger,
        result_refs=result_refs,
        final_content=final_content,
        final_answer_metadata=final_answer_metadata,
        run_outcome=run_outcome,
        terminal_reason=terminal_reason,
        final_main_context=final_main_context,
        final_task_summary_refs=final_task_summary_refs,
        final_bundle_summary_refs=final_bundle_summary_refs,
        current_bundle_items=current_bundle_items,
        executed_bundle_ordinals=executed_bundle_ordinals,
        observation_aggregator=observation_aggregator,
        tool_observation_count=tool_observation_count,
        turn_count=turn_count,
        tool_call_count=len(tool_call_accumulator.pending_tool_calls),
        approval_waiting=False,
        retrieval_followup_observed=retrieval_followup_observed,
    )


def _turn_loop_result(
    *,
    state: RuntimeLoopState,
    runtime_task_ledger: Any,
    result_refs: list[str],
    final_content: str,
    final_answer_metadata: dict[str, Any],
    run_outcome: dict[str, Any],
    terminal_reason: str,
    final_main_context: dict[str, Any],
    final_task_summary_refs: list[dict[str, Any]],
    final_bundle_summary_refs: list[dict[str, Any]],
    current_bundle_items: list[dict[str, Any]],
    executed_bundle_ordinals: list[int],
    observation_aggregator: ObservationAggregator,
    tool_observation_count: int,
    turn_count: int,
    tool_call_count: int,
    approval_waiting: bool,
    retrieval_followup_observed: bool,
) -> AgentTurnLoopResult:
    return AgentTurnLoopResult(
        state=state,
        runtime_task_ledger=runtime_task_ledger,
        result_refs=result_refs,
        final_content=final_content,
        final_answer_metadata=dict(final_answer_metadata),
        run_outcome=dict(run_outcome),
        terminal_reason=terminal_reason,
        final_main_context=dict(final_main_context),
        final_task_summary_refs=[dict(entry) for entry in final_task_summary_refs],
        final_bundle_summary_refs=[dict(entry) for entry in final_bundle_summary_refs],
        current_bundle_items=[dict(entry) for entry in current_bundle_items],
        executed_bundle_ordinals=list(executed_bundle_ordinals),
        observation_aggregator=observation_aggregator,
        tool_observation_count=tool_observation_count,
        turn_count=turn_count,
        tool_call_count=tool_call_count,
        approval_waiting=approval_waiting,
        retrieval_followup_observed=retrieval_followup_observed,
    )


def _run_outcome_from_answer_metadata(
    final_answer_metadata: dict[str, Any],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(final_answer_metadata or {})
    explicit = metadata.get("run_outcome")
    if isinstance(explicit, dict):
        return dict(explicit)
    completion = metadata.get("completion")
    if isinstance(completion, dict):
        return dict(completion)
    return dict(fallback or {})
