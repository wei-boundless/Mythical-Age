from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage

from capability_system.tool_authorization import resolve_tool_operation_id
from task_system.tasks.run_models import TaskRunLedger, current_task_step_run

from harness.loop.agent_execution.model_loop import ModelToolCallAccumulator
from harness.loop.agent_execution.model_turn_effects import classify_raw_model_event, classify_runtime_event
from harness.loop.agent_execution.observation_flow import (
    apply_observation_aggregation,
    record_tool_observation_projection,
)
from runtime.memory.observation_aggregator import ObservationAggregator
from runtime.shared.models import RuntimeLoopState, TaskRun
from runtime.shared.tool_repetition_guard import ToolRepetitionGuard


@dataclass(slots=True)
class ModelTurnApplicationState:
    loop_state: RuntimeLoopState
    runtime_task_ledger: TaskRunLedger | None
    result_refs: list[str]
    final_content: str
    final_answer_metadata: dict[str, Any]
    terminal_reason: str
    final_main_context: dict[str, Any]
    final_task_summary_refs: list[dict[str, Any]]
    final_bundle_summary_refs: list[dict[str, Any]]
    tool_observation_count: int
    executed_bundle_ordinals: list[int]
    repeated_tool_halt: bool
    approval_waiting: bool = False


async def apply_model_turn_event(
    runtime_host: Any,
    *,
    application: ModelTurnApplicationState,
    model_turn_event: Any,
    start_task_run: TaskRun,
    tool_call_accumulator: ModelToolCallAccumulator,
    collected_tool_messages: list[ToolMessage] | None,
    observation_aggregator: ObservationAggregator,
    current_bundle_items: list[dict[str, Any]],
    tool_repetition_guard: ToolRepetitionGuard | None,
    selected_recipe_payload: dict[str, Any],
    user_message: str,
    preserve_answer_metadata: bool = False,
    merge_existing_metadata: bool = False,
    apply_tool_call_transition: bool = False,
    project_tool_observation: bool = True,
    apply_projection_only_when_present: bool = False,
    fail_running_step_on_executor_error: bool = False,
    fail_running_step_on_loop_error: bool = False,
    tool_result_transition_reason: str = "tool_result_received",
    tool_result_transition_diagnostics: dict[str, Any] | None = None,
    emit_entered_step_for_tool_result: bool = True,
    update_done_only_without_pending_tool_calls: bool = False,
):
    event = dict(model_turn_event.raw_event or {})
    if event.get("type") == "tool_call_requested":
        tool_call_accumulator.ingest_event(event)
    for runtime_event in list(model_turn_event.runtime_events or []):
        runtime_effect = classify_runtime_event(runtime_event)
        if runtime_effect.result_ref:
            application.result_refs.append(runtime_effect.result_ref)
        if runtime_effect.event_type == "tool_call_requested" and apply_tool_call_transition:
            (
                application.loop_state,
                application.runtime_task_ledger,
                transition_events,
            ) = runtime_host._apply_tool_call_step_transition(
                state=application.loop_state,
                runtime_task_ledger=application.runtime_task_ledger,
                result_refs=application.result_refs,
                operation_id=runtime_effect.operation_id,
                action_request_ref=str(runtime_event.refs.get("action_request_ref") or runtime_event.event_id),
            )
            for transition_event in transition_events:
                yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
        elif runtime_effect.event_type == "executor_observation_received":
            async for emitted_event in apply_model_observation_effect(
                runtime_host,
                application=application,
                runtime_effect=runtime_effect,
                runtime_event=runtime_event,
                tool_call_accumulator=tool_call_accumulator,
                collected_tool_messages=collected_tool_messages,
                observation_aggregator=observation_aggregator,
                current_bundle_items=current_bundle_items,
                tool_repetition_guard=tool_repetition_guard,
                selected_recipe_payload=selected_recipe_payload,
                user_message=user_message,
                project_tool_observation=project_tool_observation,
                apply_projection_only_when_present=apply_projection_only_when_present,
                fail_running_step_on_executor_error=fail_running_step_on_executor_error,
                tool_result_transition_reason=tool_result_transition_reason,
                tool_result_transition_diagnostics=tool_result_transition_diagnostics,
                emit_entered_step_for_tool_result=emit_entered_step_for_tool_result,
            ):
                yield emitted_event
        elif runtime_effect.event_type == "loop_error":
            application.terminal_reason = "executor_failed"
            if fail_running_step_on_loop_error:
                runtime_error = runtime_effect.runtime_error or "executor_failed"
                runtime_observation = dict(runtime_effect.runtime_error_observation or {})
                runtime_observation_payload = dict(runtime_observation.get("payload") or {})
                current_step = current_task_step_run(application.runtime_task_ledger)
                error_diagnostics = {
                    "last_error": {
                        "message": runtime_error,
                        "code": str(runtime_observation_payload.get("code") or ""),
                        "provider": str(runtime_observation_payload.get("provider") or ""),
                        "model": str(runtime_observation_payload.get("model") or ""),
                        "detail": str(runtime_observation_payload.get("detail") or ""),
                        "source": str(runtime_event.payload.get("answer_source") or runtime_observation.get("source") or ""),
                        "observation_ref": str(runtime_event.refs.get("observation_ref") or ""),
                        "step_id": str(current_step.step_id if current_step is not None else ""),
                    },
                }
                application.loop_state = runtime_host._state_with_task_run_ledger(
                    application.loop_state,
                    application.runtime_task_ledger,
                    diagnostics=error_diagnostics,
                )
                if (
                    application.runtime_task_ledger is not None
                    and current_step is not None
                    and current_step.status == "running"
                ):
                    (
                        application.loop_state,
                        application.runtime_task_ledger,
                        transition_events,
                    ) = runtime_host._apply_failed_step_transition(
                        state=application.loop_state,
                        runtime_task_ledger=application.runtime_task_ledger,
                        reason="loop_error",
                        failure_reason=runtime_error,
                        result_refs=application.result_refs,
                        diagnostics=error_diagnostics,
                        ledger_diagnostics={"terminal_reason": "executor_failed"},
                    )
                    for transition_event in transition_events:
                        yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
        elif runtime_effect.event_type == "approval_waiting":
            approval_state = dict(runtime_effect.approval_state or {})
            (
                application.loop_state,
                approval_event,
                checkpoint_event,
                _task_run,
            ) = runtime_host._enter_waiting_approval(
                task_run_id=application.loop_state.task_run_id,
                approval_state=approval_state,
                current_state=application.loop_state,
                current_task_run=start_task_run,
                existing_approval_event=runtime_event,
            )
            application.approval_waiting = True
            yield {"type": "runtime_loop_event", "event": approval_event.to_dict()}
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
            yield {
                "type": "approval_waiting",
                "approval": approval_state,
                "task_run_id": application.loop_state.task_run_id,
            }
            return
        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}

    raw_effect = classify_raw_model_event(
        event,
        current_final_content=application.final_content,
        current_answer_metadata=application.final_answer_metadata,
        preserve_answer_metadata=preserve_answer_metadata,
        merge_existing_metadata=merge_existing_metadata,
    )
    if raw_effect.event_type == "done":
        if (
            not update_done_only_without_pending_tool_calls
            or not tool_call_accumulator.pending_tool_calls
        ):
            application.final_content = raw_effect.final_content
            if raw_effect.final_answer_metadata is not None:
                application.final_answer_metadata = dict(raw_effect.final_answer_metadata)
    elif raw_effect.terminal_reason:
        application.terminal_reason = raw_effect.terminal_reason
    if raw_effect.should_yield:
        yield event


async def apply_model_observation_effect(
    runtime_host: Any,
    *,
    application: ModelTurnApplicationState,
    runtime_effect: Any,
    runtime_event: Any,
    tool_call_accumulator: ModelToolCallAccumulator,
    collected_tool_messages: list[ToolMessage] | None,
    observation_aggregator: ObservationAggregator,
    current_bundle_items: list[dict[str, Any]],
    tool_repetition_guard: ToolRepetitionGuard | None,
    selected_recipe_payload: dict[str, Any],
    user_message: str,
    project_tool_observation: bool,
    apply_projection_only_when_present: bool,
    fail_running_step_on_executor_error: bool,
    tool_result_transition_reason: str,
    tool_result_transition_diagnostics: dict[str, Any] | None,
    emit_entered_step_for_tool_result: bool,
):
    observation_ref = runtime_effect.observation_ref
    observation = dict(runtime_effect.observation or {})
    observation_type = str(observation.get("observation_type") or "")
    if observation_type == "tool_result":
        application.tool_observation_count += 1
        observation_payload = dict(runtime_effect.observation_payload or {})
        if project_tool_observation:
            aggregation, matched_ordinal = record_tool_observation_projection(
                observation_aggregator=observation_aggregator,
                observation_payload=observation_payload,
                observation_ref=observation_ref,
                current_bundle_items=current_bundle_items,
                executed_bundle_ordinals=application.executed_bundle_ordinals,
            )
            if matched_ordinal > 0 and matched_ordinal not in application.executed_bundle_ordinals:
                application.executed_bundle_ordinals.append(matched_ordinal)
            if (
                not apply_projection_only_when_present
                or aggregation.projection.main_context
                or aggregation.projection.task_summary_refs
            ):
                (
                    application.final_main_context,
                    application.final_task_summary_refs,
                    application.final_bundle_summary_refs,
                ) = apply_observation_aggregation(aggregation)
        else:
            observation_aggregator.add_tool_observation(
                observation_payload,
                observation_ref=observation_ref,
            )
        if tool_repetition_guard is not None:
            application.repeated_tool_halt = application.repeated_tool_halt or tool_repetition_guard.record(
                str(observation_payload.get("tool_name") or ""),
                dict(observation_payload.get("tool_args") or {}),
            )
        if collected_tool_messages is not None:
            collected_tool_messages.append(
                ToolMessage(
                    content=str(observation_payload.get("result") or ""),
                    tool_call_id=str(observation_payload.get("tool_call_id") or observation_ref),
                )
            )
        operation_id = resolve_tool_operation_id(
            str(observation_payload.get("tool_name") or ""),
            definitions_by_name=runtime_host.tool_authorization_index.definitions_by_name,
        )
        (
            application.loop_state,
            application.runtime_task_ledger,
            transition_events,
        ) = runtime_host._apply_tool_result_step_transition(
            state=application.loop_state,
            runtime_task_ledger=application.runtime_task_ledger,
            result_refs=application.result_refs,
            operation_id=operation_id,
            observation_ref=observation_ref,
            observation_payload=observation_payload,
            reason=tool_result_transition_reason,
            diagnostics=tool_result_transition_diagnostics,
            emit_entered_step=emit_entered_step_for_tool_result,
        )
        for transition_event in transition_events:
            yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
        return

    if observation_type != "executor_error":
        return
    application.terminal_reason = "executor_failed"
    if not fail_running_step_on_executor_error:
        return
    observation_payload = dict(observation.get("payload") or {})
    current_step = current_task_step_run(application.runtime_task_ledger)
    error_text = str(observation_payload.get("error") or "executor_failed")
    error_diagnostics = {
        "last_error": {
            "message": error_text,
            "code": str(observation_payload.get("code") or ""),
            "provider": str(observation_payload.get("provider") or ""),
            "model": str(observation_payload.get("model") or ""),
            "detail": str(observation_payload.get("detail") or ""),
            "source": str(observation.get("source") or ""),
            "observation_ref": observation_ref,
            "step_id": str(current_step.step_id if current_step is not None else ""),
        },
    }
    application.loop_state = runtime_host._state_with_task_run_ledger(
        application.loop_state,
        application.runtime_task_ledger,
        diagnostics=error_diagnostics,
    )
    if (
        application.runtime_task_ledger is not None
        and current_step is not None
        and current_step.status == "running"
        and current_step.executor_type in {"tool", "mcp", "agent"}
    ):
        (
            application.loop_state,
            application.runtime_task_ledger,
            transition_events,
        ) = runtime_host._apply_failed_step_transition(
            state=application.loop_state,
            runtime_task_ledger=application.runtime_task_ledger,
            reason="executor_error_observation",
            refs={"observation_ref": observation_ref},
            failure_reason=error_text,
            observation_refs=(observation_ref,),
            output_refs=(observation_ref,),
            step_result_ref=observation_ref,
            executor_ref=str(observation.get("source") or current_step.executor_ref),
            diagnostics=error_diagnostics,
            ledger_diagnostics={"terminal_reason": "executor_failed"},
            result_refs=application.result_refs,
        )
        for transition_event in transition_events:
            yield {"type": "runtime_loop_event", "event": transition_event.to_dict()}
