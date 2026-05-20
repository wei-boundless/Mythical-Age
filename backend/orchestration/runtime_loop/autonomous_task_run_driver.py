from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from orchestration.runtime_directive import RuntimeDirective
from tasks.run_models import (
    TaskRunLedger,
    advance_task_run_ledger,
    append_plan_item_step,
    complete_task_run_step,
    current_task_step_run,
    find_task_step_run,
    next_pending_step_run,
    start_task_run_step,
    update_task_run_step_diagnostics,
)

from .models import RuntimeLoopState


RuntimeEventBuilder = Callable[..., Any]
ExecutorEventAdapter = Callable[..., Awaitable[Iterable[Any]]]
StateWithLedger = Callable[..., RuntimeLoopState]


@dataclass(slots=True)
class AutonomousTaskRunOutcome:
    ledger: TaskRunLedger | None
    state: RuntimeLoopState
    result_refs: list[str] = field(default_factory=list)
    final_content: str = ""
    final_answer_metadata: dict[str, Any] = field(default_factory=dict)
    terminal_reason: str = "completed"
    turn_count: int = 1
    model_call_count: int = 0
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = field(default_factory=list)


class AutonomousTaskRunDriver:
    """Runtime driver for graphless autonomous task execution.

    The driver owns autonomous task control states, while TaskRunLoop still owns
    the shared event log, checkpoints, ledger, TaskResult, and commit gates.
    """

    def __init__(
        self,
        *,
        event_log: Any,
        events_from_executor_event: ExecutorEventAdapter,
        record_task_run_step_event: RuntimeEventBuilder,
        record_task_run_ledger_updated: RuntimeEventBuilder,
        state_with_task_run_ledger: StateWithLedger,
        write_checkpoint_event: Callable[..., Any],
    ) -> None:
        self.event_log = event_log
        self.events_from_executor_event = events_from_executor_event
        self.record_task_run_step_event = record_task_run_step_event
        self.record_task_run_ledger_updated = record_task_run_ledger_updated
        self.state_with_task_run_ledger = state_with_task_run_ledger
        self.write_checkpoint_event = write_checkpoint_event
        self._ledger_transition_events: list[Any] = []

    async def run_simple_stream(
        self,
        *,
        outcome: AutonomousTaskRunOutcome,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        task_contract_ref: str,
        selected_recipe_payload: dict[str, Any],
        context_snapshot: Any,
        directive: RuntimeDirective,
        resource_policy: Any,
        model_response_executor: Any,
        runtime_context_manager: Any,
        model_stream_policy: dict[str, Any] | None = None,
        resolved_model_spec: Any | None = None,
        tool_runtime_executor: Any | None = None,
        runtime_tool_instances: list[Any] | None = None,
        allowed_search_sources: set[str] | None = None,
        sandbox_policy: dict[str, Any] | None = None,
    ):
        _ = runtime_tool_instances
        task_run_id = outcome.state.task_run_id
        plan = _simple_control_plan(user_message=user_message, selected_recipe_payload=selected_recipe_payload)
        start_event = self.event_log.append(
            task_run_id,
            "autonomous_task_started",
            payload={
                "mode": "simple",
                "runtime_driver": "autonomous_task_run",
                "goal": user_message,
                "plan_item_count": len(plan),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": start_event.to_dict()}
        state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "initialized", "to_state": "goal_locked", "mode": "simple"},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        outcome.state, outcome.ledger = self._complete_current_and_advance(
            state=outcome.state,
            ledger=outcome.ledger,
            reason="autonomous_task_goal_locked",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"autonomous_state": "goal_locked"},
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}

        plan_event = self.event_log.append(
            task_run_id,
            "autonomous_task_plan_drafted",
            payload={
                "mode": "simple",
                "plan_items": plan,
                "delegation_enabled": False,
                "tool_execution_enabled": False,
                "plan_source": "runtime_control_policy",
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": plan_event.to_dict()}
        state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "goal_locked", "to_state": "plan_drafted", "mode": "simple"},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        outcome.state, outcome.ledger = self._complete_current_and_advance(
            state=outcome.state,
            ledger=outcome.ledger,
            reason="autonomous_task_plan_drafted",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"autonomous_state": "plan_drafted", "plan_items": plan},
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}

        finalizing_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "plan_drafted", "to_state": "finalizing", "mode": "simple"},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": finalizing_event.to_dict()}
        executor_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={
                "executor_type": "model",
                "runtime_channel": "autonomous_task_run",
                "autonomy_mode": "simple",
                "tool_execution_enabled": False,
                "delegation_enabled": False,
            },
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

        safe_directive = _model_only_directive(directive)
        model_messages = _with_simple_autonomous_task_instruction(
            list(getattr(context_snapshot, "model_messages", ()) or ()),
            plan_items=plan,
        )
        outcome.model_call_count = 1
        async for event in model_response_executor.stream(
            user_message=user_message,
            model_messages=model_messages,
            directive=safe_directive,
            tool_instances=[],
            model_stream_policy=model_stream_policy,
            model_spec=resolved_model_spec,
        ):
            runtime_events = await self.events_from_executor_event(
                task_run_id,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=resource_policy,
                current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                runtime_context_manager=runtime_context_manager,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                event=event,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
            )
            for runtime_event in runtime_events:
                _adopt_runtime_event_ref(outcome, runtime_event)
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            event_type = str(event.get("type") or "")
            if event_type == "done":
                outcome.final_content = str(event.get("content") or "")
                outcome.final_answer_metadata = _answer_metadata_from_done_event(event)
                outcome.main_context = dict(event.get("main_context") or {})
                outcome.task_summary_refs = [
                    dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                ]
                outcome.bundle_summary_refs = [
                    dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                ]
            elif event_type == "error":
                outcome.terminal_reason = "executor_failed"
                yield event
            else:
                yield event

        verification = {
            "mode": "simple",
            "passed": bool(outcome.final_content and outcome.terminal_reason == "completed"),
            "checks": {
                "has_final_content": bool(outcome.final_content),
                "tool_claim_guard": "prompt_guarded",
                "summary_check_required": True,
            },
        }
        verify_event = self.event_log.append(
            task_run_id,
            "autonomous_task_verification_checked",
            payload={"verification": verification},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": verify_event.to_dict()}
        committed_state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={
                "from_state": "finalizing",
                "to_state": "ready_for_commit",
                "mode": "simple",
                "terminal_reason": outcome.terminal_reason,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": committed_state_event.to_dict()}
        if not outcome.final_content and outcome.terminal_reason == "completed":
            outcome.terminal_reason = "executor_failed"

    async def run_standard_stream(
        self,
        *,
        outcome: AutonomousTaskRunOutcome,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        task_contract_ref: str,
        selected_recipe_payload: dict[str, Any],
        context_snapshot: Any,
        directive: RuntimeDirective,
        resource_policy: Any,
        model_response_executor: Any,
        runtime_context_manager: Any,
        model_stream_policy: dict[str, Any] | None = None,
        resolved_model_spec: Any | None = None,
        tool_runtime_executor: Any | None = None,
        runtime_tool_instances: list[Any] | None = None,
        allowed_search_sources: set[str] | None = None,
        sandbox_policy: dict[str, Any] | None = None,
    ):
        task_run_id = outcome.state.task_run_id
        autonomy_mode = _standard_execution_mode(selected_recipe_payload)
        policy = _autonomous_policy(selected_recipe_payload)
        tool_policy = dict(policy.get("tool_execution_policy") or {})
        delegation_policy = dict(policy.get("delegation_policy") or {})
        delegation_enabled = bool(delegation_policy.get("enabled") is True)
        allowed_tool_names = _allowed_tool_names_from_policy(
            tool_policy,
            runtime_tool_instances=runtime_tool_instances,
            delegation_enabled=delegation_enabled,
        )
        tool_execution_enabled = bool(tool_policy.get("enabled") is True) and bool(
            tool_runtime_executor is not None and allowed_tool_names
        )
        model_tool_instances = (
            [
                tool
                for tool in list(runtime_tool_instances or [])
                if str(getattr(tool, "name", "") or "").strip() in set(allowed_tool_names)
            ]
            if tool_execution_enabled
            else []
        )
        max_tool_calls = max(1, int(tool_policy.get("max_tool_calls_per_round") or 1))
        max_delegate_calls = max(0, int(delegation_policy.get("max_delegate_calls_per_task_run") or 0))
        plan = _standard_control_plan(user_message=user_message, selected_recipe_payload=selected_recipe_payload)
        start_event = self.event_log.append(
            task_run_id,
            "autonomous_task_started",
            payload={
                "mode": autonomy_mode,
                "runtime_driver": "autonomous_task_run",
                "goal": user_message,
                "plan_item_count": len(plan),
                "policy": policy,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": start_event.to_dict()}
        state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "initialized", "to_state": "goal_locked", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        outcome.state, outcome.ledger = self._complete_current_and_advance(
            state=outcome.state,
            ledger=outcome.ledger,
            reason="autonomous_task_goal_locked",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"autonomous_state": "goal_locked", "autonomy_mode": autonomy_mode},
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}

        if outcome.ledger is not None:
            before_step_ids = {item.step_id for item in outcome.ledger.step_runs}
            final_step_id = _first_finalize_step_id(outcome.ledger)
            for item in plan:
                outcome.ledger = append_plan_item_step(
                    outcome.ledger,
                    plan_item=item,
                    before_step_id=final_step_id,
                    diagnostics={
                        "transition_reason": "autonomous_task_plan_drafted",
                        "autonomy_mode": autonomy_mode,
                    },
                )
            added_steps = [
                item for item in outcome.ledger.step_runs if item.step_id not in before_step_ids
            ]
            for step in added_steps:
                step_event = self.record_task_run_step_event(
                    outcome.state.task_run_id,
                    event_type="step_added",
                    step_run=step,
                    ledger=outcome.ledger,
                    reason="autonomous_task_plan_drafted",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"autonomy_mode": autonomy_mode},
                )
                yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
            ledger_event = self.record_task_run_ledger_updated(
                outcome.state.task_run_id,
                ledger=outcome.ledger,
                reason="autonomous_task_plan_drafted",
                refs={"task_contract_ref": task_contract_ref},
                diagnostics={"autonomy_mode": autonomy_mode, "dynamic_plan_step_count": len(added_steps)},
            )
            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
            outcome.state = self.state_with_task_run_ledger(
                outcome.state,
                outcome.ledger,
                diagnostics={
                    "last_step_transition": "autonomous_task_plan_drafted",
                    "autonomy_mode": autonomy_mode,
                },
            )
            checkpoint_event = self.write_checkpoint_event(outcome.state, event_offset=ledger_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}

        plan_event = self.event_log.append(
            task_run_id,
            "autonomous_task_plan_drafted",
            payload={
                "mode": autonomy_mode,
                "plan_items": plan,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "plan_source": "runtime_control_policy",
                "ledger_backed": outcome.ledger is not None,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": plan_event.to_dict()}
        state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "goal_locked", "to_state": "plan_drafted", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        outcome.state, outcome.ledger = self._prepare_standard_action_step(
            state=outcome.state,
            ledger=outcome.ledger,
            plan=plan,
            task_contract_ref=task_contract_ref,
            autonomy_mode=autonomy_mode,
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}
        step_selected_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "plan_drafted", "to_state": "step_selected", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": step_selected_event.to_dict()}

        finalizing_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "step_selected", "to_state": "action_dispatched", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": finalizing_event.to_dict()}
        executor_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={
                "executor_type": "model",
                "runtime_channel": "autonomous_task_run",
                "autonomy_mode": autonomy_mode,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
                "autonomous_mode_scope": (
                    "ledger_backed_plan_one_round_tool_or_delegation_observation"
                    if tool_execution_enabled
                    else "ledger_backed_plan_and_model_closeout"
                ),
                "standard_mode_scope": (
                    "ledger_backed_plan_one_round_tool_or_delegation_observation"
                    if tool_execution_enabled
                    else "ledger_backed_plan_and_model_closeout"
                ),
            },
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

        safe_directive = _autonomous_task_directive(
            directive,
            mode=autonomy_mode,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_operation_refs=list(tool_policy.get("allowed_operation_refs") or ()),
        )
        model_messages = _with_autonomous_task_instruction(
            list(getattr(context_snapshot, "model_messages", ()) or ()),
            mode=autonomy_mode,
            plan_items=plan,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_names=allowed_tool_names,
            max_tool_calls=max_tool_calls,
            max_delegate_calls=max_delegate_calls,
        )
        outcome.model_call_count = 1
        pending_tool_calls: list[dict[str, Any]] = []
        assistant_tool_call_content = ""
        assistant_tool_call_kwargs: dict[str, Any] = {}
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        delegation_observation_count = 0
        tool_call_budget_exceeded = False
        action_observation_refs: list[str] = []
        async for event in model_response_executor.stream(
            user_message=user_message,
            model_messages=model_messages,
            directive=safe_directive,
            tool_instances=model_tool_instances,
            model_stream_policy=model_stream_policy,
            model_spec=resolved_model_spec,
        ):
            event_type = str(event.get("type") or "")
            if event_type == "tool_call_requested":
                requested_tool_name = str(event.get("tool_name") or dict(event.get("tool_call") or {}).get("name") or "")
                if requested_tool_name == "delegate_to_agent" and (
                    not delegation_enabled or delegation_observation_count >= max_delegate_calls
                ):
                    tool_call_budget_exceeded = True
                    blocked_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "autonomous_task_delegation_budget_exceeded",
                            "message": "标准自主任务本轮只允许有限委派，超出预算的委派请求未执行。",
                            "max_delegate_calls_per_task_run": max_delegate_calls,
                            "tool_name": requested_tool_name,
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                    continue
                if len(pending_tool_calls) >= max_tool_calls:
                    tool_call_budget_exceeded = True
                    blocked_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "autonomous_task_tool_call_budget_exceeded",
                            "message": "标准自主任务本轮只允许有限工具调用，超出预算的工具请求未执行。",
                            "max_tool_calls_per_round": max_tool_calls,
                            "tool_name": str(event.get("tool_name") or ""),
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                    continue
                tool_call = dict(event.get("tool_call") or {})
                if tool_call:
                    pending_tool_calls.append(tool_call)
                assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                if event_kwargs:
                    assistant_tool_call_kwargs.update(event_kwargs)
            runtime_events = await self.events_from_executor_event(
                task_run_id,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=resource_policy,
                current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                runtime_context_manager=runtime_context_manager,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                event=event,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
            )
            for runtime_event in runtime_events:
                _adopt_runtime_event_ref(outcome, runtime_event)
                observation_payload = _tool_observation_payload(runtime_event)
                if observation_payload:
                    tool_observation_count += 1
                    observation_ref = _runtime_event_observation_ref(runtime_event)
                    if observation_ref:
                        action_observation_refs.append(observation_ref)
                    if str(observation_payload.get("tool_name") or "") == "delegate_to_agent":
                        delegation_observation_count += 1
                    tool_messages.append(
                        ToolMessage(
                            content=str(observation_payload.get("result") or ""),
                            tool_call_id=str(
                                observation_payload.get("tool_call_id")
                                or dict(event.get("tool_call") or {}).get("id")
                                or getattr(runtime_event, "event_id", "")
                            ),
                        )
                    )
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            if event_type == "done":
                outcome.final_content = str(event.get("content") or "")
                outcome.final_answer_metadata = _answer_metadata_from_done_event(event)
                outcome.main_context = dict(event.get("main_context") or {})
                outcome.task_summary_refs = [
                    dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                ]
                outcome.bundle_summary_refs = [
                    dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                ]
            elif event_type == "error":
                outcome.terminal_reason = "executor_failed"
                yield event
            else:
                yield event

        if tool_observation_count > 0 and outcome.terminal_reason == "completed":
            observation_state_event = self.event_log.append(
                task_run_id,
                "autonomous_task_state_changed",
                payload={
                    "from_state": "action_dispatched",
                    "to_state": "observation_received",
                    "mode": autonomy_mode,
                    "tool_observation_count": tool_observation_count,
                    "delegation_observation_count": delegation_observation_count,
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": observation_state_event.to_dict()}
            outcome.state, outcome.ledger = self._complete_standard_action_step_after_observation(
                state=outcome.state,
                ledger=outcome.ledger,
                plan=plan,
                task_contract_ref=task_contract_ref,
                observation_refs=tuple(action_observation_refs),
                autonomy_mode=autonomy_mode,
            )
            for runtime_event in self._ledger_transition_events:
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            evaluated_state_event = self.event_log.append(
                task_run_id,
                "autonomous_task_state_changed",
                payload={
                    "from_state": "observation_received",
                    "to_state": "step_evaluated",
                    "mode": autonomy_mode,
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": evaluated_state_event.to_dict()}

        if (
            tool_execution_enabled
            and pending_tool_calls
            and tool_messages
            and outcome.terminal_reason == "completed"
            and not tool_call_budget_exceeded
        ):
            followup_event = self.event_log.append(
                task_run_id,
                "loop_iteration_started",
                payload={
                    "transition": "autonomous_task_continue_after_tool_result",
                    "turn_count": 2,
                    "tool_call_count": len(pending_tool_calls),
                    "tool_observation_count": tool_observation_count,
                    "delegation_observation_count": delegation_observation_count,
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            outcome.turn_count = 2
            outcome.model_call_count = 2
            followup_messages = [
                *model_messages,
                AIMessage(
                    content=assistant_tool_call_content,
                    tool_calls=pending_tool_calls,
                    additional_kwargs=assistant_tool_call_kwargs,
                ),
                *tool_messages,
                {
                    "role": "system",
                    "content": (
                        "你已经收到本轮真实工具观察结果。现在不要再请求工具或委派子 Agent。"
                        "请只基于这些观察、当前上下文和用户目标完成收口；如果证据不足，请明确说明限制。"
                    ),
                },
            ]
            followup_directive = _model_only_directive(directive, mode=f"{autonomy_mode}_tool_followup")
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=followup_messages,
                directive=followup_directive,
                tool_instances=[],
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                runtime_events = await self.events_from_executor_event(
                    task_run_id,
                    user_message=user_message,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
                    current_step_id=outcome.ledger.current_step_id if outcome.ledger is not None else outcome.state.current_step_id,
                    runtime_context_manager=runtime_context_manager,
                    model_response_executor=model_response_executor,
                    tool_runtime_executor=tool_runtime_executor,
                    event=event,
                    allowed_search_sources=allowed_search_sources,
                    sandbox_policy=sandbox_policy,
                )
                for runtime_event in runtime_events:
                    _adopt_runtime_event_ref(outcome, runtime_event)
                    yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                event_type = str(event.get("type") or "")
                if event_type == "done":
                    outcome.final_content = str(event.get("content") or "")
                    outcome.final_answer_metadata = _answer_metadata_from_done_event(event)
                    outcome.main_context = dict(event.get("main_context") or {})
                    outcome.task_summary_refs = [
                        dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                    ]
                    outcome.bundle_summary_refs = [
                        dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                    ]
                elif event_type == "tool_call_requested":
                    outcome.terminal_reason = "tool_loop_budget_exceeded"
                    blocked_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "autonomous_task_nested_tool_call_blocked",
                            "message": "标准自主任务的首版工具闭环只允许一轮工具观察，二次工具请求已被阻止。",
                            "tool_name": str(event.get("tool_name") or ""),
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": followup_directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                elif event_type == "error":
                    outcome.terminal_reason = "executor_failed"
                    yield event
                else:
                    yield event
        elif tool_call_budget_exceeded and outcome.terminal_reason == "completed":
            outcome.terminal_reason = "tool_loop_budget_exceeded"

        verification_ready_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "step_evaluated", "to_state": "verification_ready", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": verification_ready_event.to_dict()}
        verification = {
            "mode": autonomy_mode,
            "passed": bool(outcome.final_content and outcome.terminal_reason == "completed"),
            "checks": {
                "has_final_content": bool(outcome.final_content),
                "ledger_backed_plan": outcome.ledger is not None,
                "dynamic_plan_item_count": len(plan),
                "tool_execution_enabled": tool_execution_enabled,
                "tool_call_count": len(pending_tool_calls),
                "tool_observation_count": tool_observation_count,
                "delegation_enabled": delegation_enabled,
                "delegation_observation_count": delegation_observation_count,
                "tool_claim_guard": "event_guarded" if tool_execution_enabled else "prompt_guarded",
                "summary_check_required": True,
            },
        }
        verify_event = self.event_log.append(
            task_run_id,
            "autonomous_task_verification_checked",
            payload={"verification": verification},
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "autonomous.final_check"},
        )
        yield {"type": "runtime_loop_event", "event": verify_event.to_dict()}
        outcome.state, outcome.ledger = self._complete_standard_final_check_after_verification(
            state=outcome.state,
            ledger=outcome.ledger,
            task_contract_ref=task_contract_ref,
            verification_event_ref=f"runtime_event:{verify_event.event_id}",
            observation_refs=tuple(action_observation_refs),
            result_refs=tuple(outcome.result_refs),
            final_content=outcome.final_content,
            verification_passed=bool(verification.get("passed") is True),
            autonomy_mode=autonomy_mode,
        )
        for runtime_event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        finalizing_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "verification_ready", "to_state": "finalizing", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": finalizing_event.to_dict()}
        committed_state_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={
                "from_state": "finalizing",
                "to_state": "ready_for_commit",
                "mode": autonomy_mode,
                "terminal_reason": outcome.terminal_reason,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": committed_state_event.to_dict()}
        if not outcome.final_content and outcome.terminal_reason == "completed":
            outcome.terminal_reason = "executor_failed"

    def _complete_current_and_advance(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        current = current_task_step_run(ledger)
        if current is not None and current.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=current.step_id,
                started_at=time.time(),
                diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
            )
            current = current_task_step_run(ledger)
            if current is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=current,
                        ledger=ledger,
                        reason=reason,
                        refs=refs,
                    )
                )
        if current is not None and current.status == "running":
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                output_refs=(),
                executor_ref=current.executor_ref or "autonomous_task_run",
                diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason=reason,
                        refs=refs,
                    )
                )
        ledger = advance_task_run_ledger(
            ledger,
            started_at=time.time(),
            executor_ref="autonomous_task_run",
            diagnostics={"transition_reason": reason, **dict(diagnostics or {})},
        )
        entered = current_task_step_run(ledger)
        if entered is not None and entered.status == "running":
            self._ledger_transition_events.append(
                self.record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered,
                    ledger=ledger,
                    reason=reason,
                    refs=refs,
                )
            )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason=reason,
            refs=refs,
            diagnostics=diagnostics,
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={"last_step_transition": reason},
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _prepare_standard_action_step(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        plan: list[dict[str, Any]],
        task_contract_ref: str,
        autonomy_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        action_step_id = _standard_action_step_id(plan)
        if not action_step_id:
            return state, ledger

        current = current_task_step_run(ledger)
        if current is not None and current.step_id != action_step_id:
            if current.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    started_at=time.time(),
                    executor_ref="autonomous_task_run",
                    diagnostics={"transition_reason": "autonomous_task_action_step_selected", "autonomy_mode": autonomy_mode},
                )
                current = current_task_step_run(ledger)
                if current is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=current,
                            ledger=ledger,
                            reason="autonomous_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"autonomy_mode": autonomy_mode},
                        )
                    )
            if current is not None and current.status == "running":
                ledger = complete_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    completed_at=time.time(),
                    output_refs=(f"autonomous_control_step:{current.step_id}",),
                    executor_ref=current.executor_ref or "autonomous_task_run",
                    diagnostics={
                        "transition_reason": "autonomous_task_action_step_selected",
                        "autonomy_mode": autonomy_mode,
                    },
                )
                completed = find_task_step_run(ledger, current.step_id)
                if completed is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_completed",
                            step_run=completed,
                            ledger=ledger,
                            reason="autonomous_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"autonomy_mode": autonomy_mode},
                        )
                    )

        for item in plan:
            step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
            if not step_id or step_id == action_step_id:
                break
            step = find_task_step_run(ledger, step_id)
            if step is None or step.status in {"completed", "failed", "skipped"}:
                continue
            if step.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=step.step_id,
                    started_at=time.time(),
                    executor_ref="autonomous_task_run",
                    diagnostics={"transition_reason": "autonomous_task_prerequisite_step_completed", "autonomy_mode": autonomy_mode},
                )
                entered = current_task_step_run(ledger)
                if entered is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=entered,
                            ledger=ledger,
                            reason="autonomous_task_prerequisite_step_completed",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"autonomy_mode": autonomy_mode},
                        )
                    )
            current = current_task_step_run(ledger)
            if current is None or current.status != "running":
                continue
            ledger = update_task_run_step_diagnostics(
                ledger,
                step_id=current.step_id,
                diagnostics={
                    "autonomous_state": "step_evaluated",
                    "transition_reason": "autonomous_task_prerequisite_step_completed",
                    "autonomy_mode": autonomy_mode,
                    "execution_scope": "goal_and_scope_locked",
                },
            )
            current = current_task_step_run(ledger)
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id if current is not None else None,
                completed_at=time.time(),
                output_refs=(f"autonomous_plan_item:{current.step_id}",) if current is not None else (),
                executor_ref="autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_prerequisite_step_completed",
                    "autonomy_mode": autonomy_mode,
                    "execution_scope": "goal_and_scope_locked",
                },
            )
            completed = find_task_step_run(ledger, current.step_id if current is not None else "")
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="autonomous_task_prerequisite_step_completed",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"autonomy_mode": autonomy_mode},
                    )
                )

        action_step = find_task_step_run(ledger, action_step_id)
        if action_step is not None and action_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=action_step.step_id,
                started_at=time.time(),
                executor_ref="autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_action_step_selected",
                    "autonomous_state": "step_selected",
                    "autonomy_mode": autonomy_mode,
                    "execution_scope": "controlled_tool_or_delegation_observation",
                },
            )
            entered = current_task_step_run(ledger)
            if entered is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=entered,
                        ledger=ledger,
                        reason="autonomous_task_action_step_selected",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"autonomy_mode": autonomy_mode},
                    )
                )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="autonomous_task_action_step_selected",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"autonomy_mode": autonomy_mode},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "autonomous_task_action_step_selected",
                "autonomous_state": "step_selected",
                "autonomy_mode": autonomy_mode,
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _complete_standard_action_step_after_observation(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        plan: list[dict[str, Any]],
        task_contract_ref: str,
        observation_refs: tuple[str, ...],
        autonomy_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        action_step_id = _standard_action_step_id(plan)
        current = current_task_step_run(ledger)
        if current is None or current.step_id != action_step_id:
            action_step = find_task_step_run(ledger, action_step_id)
            if action_step is None:
                return state, ledger
            if action_step.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=action_step.step_id,
                    started_at=time.time(),
                    executor_ref="autonomous_task_run",
                    diagnostics={
                        "transition_reason": "autonomous_task_observation_received",
                        "autonomy_mode": autonomy_mode,
                    },
                )
                current = current_task_step_run(ledger)
            else:
                current = action_step
        if current is not None and current.status == "running":
            deduped_observation_refs = tuple(_dedupe_strings(observation_refs))
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                observation_refs=deduped_observation_refs,
                output_refs=tuple(f"autonomous_observation:{ref}" for ref in deduped_observation_refs),
                executor_ref=current.executor_ref or "autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_observation_received",
                    "autonomous_state": "step_evaluated",
                    "autonomy_mode": autonomy_mode,
                    "execution_scope": "controlled_observation_completed",
                },
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="autonomous_task_observation_received",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"autonomy_mode": autonomy_mode},
                    )
                )
        ledger = advance_task_run_ledger(
            ledger,
            started_at=time.time(),
            executor_ref="autonomous_task_run",
            diagnostics={
                "transition_reason": "autonomous_task_step_evaluated",
                "autonomous_state": "step_evaluated",
                "autonomy_mode": autonomy_mode,
            },
        )
        entered = current_task_step_run(ledger)
        if entered is not None and entered.status == "running":
            self._ledger_transition_events.append(
                self.record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered,
                    ledger=ledger,
                    reason="autonomous_task_step_evaluated",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"autonomy_mode": autonomy_mode},
                )
            )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="autonomous_task_step_evaluated",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"autonomy_mode": autonomy_mode, "observation_ref_count": len(observation_refs)},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "autonomous_task_step_evaluated",
                "autonomous_state": "step_evaluated",
                "autonomy_mode": autonomy_mode,
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger

    def _complete_standard_final_check_after_verification(
        self,
        *,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        task_contract_ref: str,
        verification_event_ref: str,
        observation_refs: tuple[str, ...],
        result_refs: tuple[str, ...],
        final_content: str,
        verification_passed: bool,
        autonomy_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        final_step_id = "autonomous.final_check"
        if find_task_step_run(ledger, final_step_id) is None:
            return state, ledger

        evidence_refs = tuple(_dedupe_strings([*observation_refs, verification_event_ref]))
        final_output_refs = tuple(_dedupe_strings([verification_event_ref, *result_refs]))
        refs = {
            "task_contract_ref": task_contract_ref,
            "verification_ref": verification_event_ref,
        }
        now = time.time()

        while True:
            current = current_task_step_run(ledger)
            if current is None or current.step_id == final_step_id:
                break
            if current.status == "pending":
                ledger = start_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    started_at=now,
                    executor_ref="autonomous_task_run",
                    diagnostics={
                        "transition_reason": "autonomous_task_pre_verification_step_completed",
                        "autonomous_state": "verification_ready",
                        "autonomy_mode": autonomy_mode,
                    },
                )
                entered = current_task_step_run(ledger)
                if entered is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=entered,
                            ledger=ledger,
                            reason="autonomous_task_pre_verification_step_completed",
                            refs=refs,
                            diagnostics={"autonomy_mode": autonomy_mode},
                        )
                    )
                current = current_task_step_run(ledger)
            if current is None or current.step_id == final_step_id:
                break
            if current.status != "running":
                break
            current_observation_refs = tuple(_dedupe_strings(observation_refs))
            current_output_refs = tuple(
                _dedupe_strings(
                    [
                        f"autonomous_plan_item:{current.step_id}",
                        *current_observation_refs,
                    ]
                )
            )
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id,
                completed_at=time.time(),
                observation_refs=current_observation_refs,
                output_refs=current_output_refs,
                executor_ref=current.executor_ref or "autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_pre_verification_step_completed",
                    "autonomous_state": "verification_ready",
                    "autonomy_mode": autonomy_mode,
                    "execution_scope": "model_observation_ready_for_final_check",
                },
            )
            completed = find_task_step_run(ledger, current.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="autonomous_task_pre_verification_step_completed",
                        refs=refs,
                        diagnostics={"autonomy_mode": autonomy_mode},
                    )
                )

        final_step = find_task_step_run(ledger, final_step_id)
        if final_step is not None and final_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=final_step.step_id,
                started_at=time.time(),
                executor_ref="autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_verification_started",
                    "autonomous_state": "verification_ready",
                    "autonomy_mode": autonomy_mode,
                    "verification_ref": verification_event_ref,
                },
            )
            entered = current_task_step_run(ledger)
            if entered is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_entered",
                        step_run=entered,
                        ledger=ledger,
                        reason="autonomous_task_verification_started",
                        refs=refs,
                        diagnostics={"autonomy_mode": autonomy_mode},
                    )
                )
            final_step = current_task_step_run(ledger)

        if final_step is not None and final_step.status == "running":
            ledger = complete_task_run_step(
                ledger,
                step_id=final_step.step_id,
                completed_at=time.time(),
                observation_refs=evidence_refs,
                output_refs=final_output_refs or evidence_refs,
                step_result_ref=verification_event_ref,
                executor_ref=final_step.executor_ref or "autonomous_task_run",
                diagnostics={
                    "transition_reason": "autonomous_task_verification_completed",
                    "autonomous_state": "verification_ready",
                    "autonomy_mode": autonomy_mode,
                    "verification_ref": verification_event_ref,
                    "verification_passed": bool(verification_passed),
                    "final_content_chars": len(str(final_content or "")),
                    "observation_ref_count": len(evidence_refs),
                },
            )
            completed = find_task_step_run(ledger, final_step.step_id)
            if completed is not None:
                self._ledger_transition_events.append(
                    self.record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_completed",
                        step_run=completed,
                        ledger=ledger,
                        reason="autonomous_task_verification_completed",
                        refs=refs,
                        diagnostics={"autonomy_mode": autonomy_mode, "verification_passed": bool(verification_passed)},
                    )
                )

        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="autonomous_task_verification_completed",
            refs={**refs, "task_step_ref": final_step_id},
            diagnostics={
                "autonomy_mode": autonomy_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "autonomous_task_verification_completed",
                "autonomous_state": "verification_ready",
                "autonomy_mode": autonomy_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger


def _simple_control_plan(
    *,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    _ = selected_recipe_payload
    goal = str(user_message or "").strip()
    return [
        {
            "plan_item_id": "simple.goal",
            "title": "锁定目标与边界",
            "action_kind": "main_agent",
            "summary": goal[:160],
        },
        {
            "plan_item_id": "simple.answer",
            "title": "基于当前可见上下文完成回答",
            "action_kind": "main_agent",
            "summary": "不声称未发生的工具、检索、测试或写入。",
        },
        {
            "plan_item_id": "simple.check",
            "title": "自检结论和限制",
            "action_kind": "main_agent",
            "summary": "检查是否给出结论、证据边界和后续建议。",
        },
    ]


def _standard_control_plan(
    *,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    _ = selected_recipe_payload
    goal = str(user_message or "").strip()
    return [
        {
            "plan_item_id": "autonomous.goal_lock",
            "title": "锁定任务目标、边界和验收口径",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": goal[:200],
            "required_operations": ["op.model_response"],
        },
        {
            "plan_item_id": "autonomous.context_review",
            "title": "复核当前可见上下文和能力边界",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": "确认当前阶段只使用已装配上下文，不声称额外工具或子 Agent 执行。",
            "required_operations": ["op.model_response"],
        },
        {
            "plan_item_id": "autonomous.final_check",
            "title": "完成结论、自检和下一步建议",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": "输出目标理解、执行计划、当前结论、限制和可继续推进的步骤。",
            "required_operations": ["op.model_response"],
        },
    ]


def _model_only_directive(directive: RuntimeDirective, *, mode: str = "simple") -> RuntimeDirective:
    return replace(
        directive,
        operation_refs=("op.model_response",),
        diagnostics={
            **dict(directive.diagnostics or {}),
            "autonomous_task_mode": mode,
            "model_only": True,
            "delegation_disabled": True,
            "tool_execution_disabled": True,
        },
    )


def _autonomous_task_directive(
    directive: RuntimeDirective,
    *,
    mode: str,
    tool_execution_enabled: bool,
    delegation_enabled: bool,
    allowed_tool_operation_refs: list[str] | tuple[str, ...] | None = None,
) -> RuntimeDirective:
    if not tool_execution_enabled:
        return _model_only_directive(directive, mode=mode)
    operation_refs = tuple(
        _dedupe_strings(
            [
                "op.model_response",
                *list(allowed_tool_operation_refs or ()),
            ]
        )
    )
    return replace(
        directive,
        operation_refs=operation_refs,
        diagnostics={
            **dict(directive.diagnostics or {}),
            "autonomous_task_mode": mode,
            "model_only": False,
            "delegation_disabled": not delegation_enabled,
            "tool_execution_enabled": True,
            "controlled_tool_rounds": 1,
            "auto_delegate_model_answer": False,
        },
    )


def _with_simple_autonomous_task_instruction(
    model_messages: list[Any],
    *,
    plan_items: list[dict[str, Any]],
) -> list[Any]:
    return _with_autonomous_task_instruction(
        model_messages,
        mode="simple",
        plan_items=plan_items,
        tool_execution_enabled=False,
        delegation_enabled=False,
        allowed_tool_names=[],
        max_tool_calls=0,
    )


def _with_autonomous_task_instruction(
    model_messages: list[Any],
    *,
    mode: str,
    plan_items: list[dict[str, Any]],
    tool_execution_enabled: bool,
    delegation_enabled: bool,
    allowed_tool_names: list[str] | tuple[str, ...] | None = None,
    max_tool_calls: int = 0,
    max_delegate_calls: int = 0,
) -> list[Any]:
    plan_lines = "\n".join(
        f"- {item['title']}: {item['summary']}"
        for item in plan_items
        if str(item.get("title") or "").strip()
    )
    allowed_tools = [str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()]
    if tool_execution_enabled:
        tool_line = (
            "当前模式已开放一轮受控工具观察；只能基于真实工具结果写结论。"
            f"可用工具：{', '.join(allowed_tools) or '无'}。"
            f"本轮最多请求 {max(1, int(max_tool_calls or 1))} 个工具调用；工具结果返回后必须直接收口，不要继续请求工具。"
        )
    else:
        tool_line = "当前模式不会向你开放工具执行；不要声称执行了未发生的检索、测试、文件读取、写入或验证。"
    delegation_line = (
        (
            "当前模式允许受控委派子 Agent；只能基于真实委派回传写结论。"
            f"委派必须通过 delegate_to_agent 工具发起，最多 {max(1, int(max_delegate_calls or 1))} 次。"
            "委派指令要写成给专业同事派活：说明目标、范围、禁止扩大范围、期望返回 summary/answer_candidate/evidence_refs/limitations。"
            "子 Agent 回传只是 evidence packet，最终用户回答必须由你综合收口。"
        )
        if delegation_enabled
        else "当前模式不会向你开放子 Agent 委派；不要声称有子 Agent 已完成工作。"
    )
    instruction = (
        f"你是当前任务的主执行 Agent，正在使用自主任务 {mode} 模式。\n"
        "请先锁定用户目标和边界，再按运行时计划完成收口。\n"
        f"{tool_line}\n"
        f"{delegation_line}\n"
        "如果当前可见上下文不足，请明确说明限制，并给出下一步建议。\n"
        "请在最终回答中覆盖：目标理解、运行计划、当前结论、限制或下一步。\n"
        f"运行时计划：\n{plan_lines}"
    )
    if not model_messages:
        return [{"role": "system", "content": instruction}]
    messages = list(model_messages)
    insert_at = len(messages)
    last_role = ""
    if isinstance(messages[-1], dict):
        last_role = str(messages[-1].get("role") or "")
    else:
        last_role = str(getattr(messages[-1], "type", "") or getattr(messages[-1], "role", "") or "")
    if last_role == "user" or last_role == "human":
        insert_at = max(0, len(messages) - 1)
    messages.insert(insert_at, {"role": "system", "content": instruction})
    return messages


def _autonomous_policy(selected_recipe_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    return {
        "runtime_limits": dict(metadata.get("runtime_limits") or {}),
        "checkpoint_policy": dict(metadata.get("checkpoint_policy") or {}),
        "delegation_policy": dict(metadata.get("delegation_policy") or {}),
        "tool_execution_policy": dict(metadata.get("tool_execution_policy") or {}),
        "verification_policy": dict(metadata.get("verification_policy") or {}),
    }


def _standard_execution_mode(selected_recipe_payload: dict[str, Any]) -> str:
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    mode = str(metadata.get("autonomy_mode") or metadata.get("default_autonomy_mode") or "standard").strip().lower()
    return mode if mode in {"standard", "managed"} else "standard"


def _first_finalize_step_id(ledger: TaskRunLedger | None) -> str:
    if ledger is None:
        return ""
    for step in ledger.step_runs:
        if str(step.step_kind or "") == "finalize":
            return step.step_id
    return ""


def _standard_action_step_id(plan: list[dict[str, Any]]) -> str:
    items = [dict(item) for item in list(plan or []) if isinstance(item, dict)]
    for item in items:
        step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
        if step_id and any(token in step_id for token in ("context_review", "execute", "inspect", "analysis")):
            return step_id
    for item in items:
        step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
        if step_id and "goal" not in step_id:
            return step_id
    return str(dict(items[0]).get("plan_item_id") or dict(items[0]).get("step_id") or "").strip() if items else ""


def _answer_metadata_from_done_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_channel": str(event.get("answer_channel") or ""),
        "answer_source": str(event.get("answer_source") or "runtime_directive:model_response"),
        "answer_canonical_state": str(event.get("answer_canonical_state") or ""),
        "answer_persist_policy": str(event.get("answer_persist_policy") or ""),
        "answer_finalization_policy": str(event.get("answer_finalization_policy") or ""),
        "answer_fallback_reason": str(event.get("answer_fallback_reason") or ""),
    }


def _allowed_tool_names_from_policy(
    tool_policy: dict[str, Any],
    *,
    runtime_tool_instances: list[Any] | None,
    delegation_enabled: bool = False,
) -> list[str]:
    configured = [
        str(item or "").strip()
        for item in list(tool_policy.get("allowed_tool_names") or [])
        if str(item or "").strip()
    ]
    if not configured:
        configured = [
            str(getattr(tool, "name", "") or "").strip()
            for tool in list(runtime_tool_instances or [])
            if str(getattr(tool, "name", "") or "").strip()
        ]
    denied = {
        str(item or "").strip()
        for item in list(tool_policy.get("denied_tool_names") or ([] if delegation_enabled else ["delegate_to_agent"]))
        if str(item or "").strip()
    }
    available = {
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(runtime_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    }
    result: list[str] = []
    seen: set[str] = set()
    for name in configured:
        if name in denied or name not in available or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _dedupe_strings(values: list[Any] | tuple[Any, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _tool_observation_payload(runtime_event: Any) -> dict[str, Any]:
    if str(getattr(runtime_event, "event_type", "") or "") != "executor_observation_received":
        return {}
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    observation = dict(payload.get("observation") or {})
    if observation.get("observation_type") != "tool_result":
        return {}
    observation_payload = dict(observation.get("payload") or {})
    return observation_payload if observation_payload else {}


def _runtime_event_observation_ref(runtime_event: Any) -> str:
    refs = dict(getattr(runtime_event, "refs", {}) or {})
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    observation = dict(payload.get("observation") or {})
    return str(
        refs.get("observation_ref")
        or observation.get("observation_id")
        or getattr(runtime_event, "event_id", "")
        or ""
    ).strip()


def _adopt_runtime_event_ref(outcome: AutonomousTaskRunOutcome, runtime_event: Any) -> None:
    event_type = str(getattr(runtime_event, "event_type", "") or "")
    refs = dict(getattr(runtime_event, "refs", {}) or {})
    payload = dict(getattr(runtime_event, "payload", {}) or {})
    if event_type == "executor_observation_received":
        observation_ref = str(refs.get("observation_ref") or getattr(runtime_event, "event_id", "") or "")
        if observation_ref:
            outcome.result_refs.append(observation_ref)
    elif event_type == "output_boundary_applied":
        outcome.result_refs.append(f"output_boundary:{getattr(runtime_event, 'event_id', '')}")
    elif event_type == "commit_gate_checked":
        commit_ref = str(
            refs.get("commit_gate_ref")
            or dict(payload.get("commit_gate") or {}).get("gate_id")
            or getattr(runtime_event, "event_id", "")
        )
        outcome.result_refs.append(f"commit_gate:{commit_ref}")
