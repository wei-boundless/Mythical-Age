from __future__ import annotations

import time
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Awaitable, Callable, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from orchestration.runtime_directive import RuntimeDirective
from output_boundary.boundary import sanitize_visible_assistant_content
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
    turn_count: int = 0
    model_call_count: int = 0
    main_context: dict[str, Any] = field(default_factory=dict)
    task_summary_refs: list[dict[str, Any]] = field(default_factory=list)
    bundle_summary_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AutonomousTaskGoalContract:
    contract_id: str
    goal: str
    required_material_paths: list[str] = field(default_factory=list)
    required_output_paths: list[str] = field(default_factory=list)
    material_types: list[str] = field(default_factory=list)
    required_tool_kinds: list[str] = field(default_factory=list)
    required_output_kinds: list[str] = field(default_factory=list)
    requires_material_review: bool = False
    requires_write_output: bool = False
    requires_verification_command: bool = False
    requires_delegation: bool = False
    response_must_include: list[str] = field(default_factory=list)
    forbidden_visible_markers: list[str] = field(default_factory=list)
    authority: str = "orchestration.autonomous_task_goal_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AutonomousTaskActionTracker:
    tool_names: list[str] = field(default_factory=list)
    read_material_paths: list[str] = field(default_factory=list)
    searched_material_refs: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=list)
    edit_paths: list[str] = field(default_factory=list)
    terminal_commands: list[str] = field(default_factory=list)
    delegation_observation_count: int = 0
    tool_observation_count: int = 0
    artifact_observation_count: int = 0

    @property
    def write_observation_count(self) -> int:
        return len(self.write_paths) + len(self.edit_paths)

    @property
    def verification_command_count(self) -> int:
        return len(self.terminal_commands)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AutonomousTaskContractGateDecision:
    allowed: bool
    error: str = ""
    message: str = ""
    repair_instruction: str = ""
    next_required_tool_names: tuple[str, ...] = ()


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
        max_tool_calls_per_task_run = max(
            max_tool_calls,
            int(tool_policy.get("max_tool_calls_per_task_run") or max_tool_calls),
        )
        max_tool_rounds = max(1, int(tool_policy.get("max_tool_rounds_per_task_run") or 1))
        max_delegate_calls = max(0, int(delegation_policy.get("max_delegate_calls_per_task_run") or 0))
        goal_contract = _build_goal_contract(
            task_run_id=task_run_id,
            user_message=user_message,
            selected_recipe_payload=selected_recipe_payload,
        )
        plan = _standard_control_plan(
            user_message=user_message,
            selected_recipe_payload=selected_recipe_payload,
            goal_contract=goal_contract,
        )
        start_event = self.event_log.append(
            task_run_id,
            "autonomous_task_started",
            payload={
                "mode": autonomy_mode,
                "runtime_driver": "autonomous_task_run",
                "goal": user_message,
                "goal_contract": goal_contract.to_dict(),
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
                "max_tool_calls_per_round": max_tool_calls,
                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                "max_tool_rounds_per_task_run": max_tool_rounds,
                "plan_source": "goal_contract_runtime_policy",
                "goal_contract": goal_contract.to_dict(),
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
                    "ledger_backed_plan_budgeted_tool_or_delegation_observations"
                    if tool_execution_enabled
                    else "ledger_backed_plan_and_model_closeout"
                ),
                "standard_mode_scope": (
                    "ledger_backed_plan_budgeted_tool_or_delegation_observations"
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
            max_tool_rounds=max_tool_rounds,
        )
        model_messages = _with_autonomous_task_instruction(
            list(getattr(context_snapshot, "model_messages", ()) or ()),
            mode=autonomy_mode,
            plan_items=plan,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_names=allowed_tool_names,
            max_tool_calls=max_tool_calls,
            max_tool_calls_per_task_run=max_tool_calls_per_task_run,
            max_tool_rounds=max_tool_rounds,
            max_delegate_calls=max_delegate_calls,
            goal_contract=goal_contract,
        )
        write_output_required = bool(goal_contract.requires_write_output)
        pending_tool_calls: list[dict[str, Any]] = []
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        delegation_observation_count = 0
        write_observation_count = 0
        action_tracker = AutonomousTaskActionTracker()
        tool_call_budget_exceeded = False
        write_budget_reserved = False
        contract_gate_blocked = False
        action_observation_refs: list[str] = []
        action_step_completed = False
        conversation_messages: list[Any] = list(model_messages)
        while outcome.terminal_reason == "completed":
            round_index = int(outcome.turn_count or 0) + 1
            if round_index > max_tool_rounds:
                tool_call_budget_exceeded = True
                budget_event = self.event_log.append(
                    task_run_id,
                    "loop_error",
                    payload={
                        "error": "autonomous_task_tool_round_budget_exceeded",
                        "message": "自主任务工具观察轮次已达上限，停止继续请求工具。",
                        "max_tool_rounds_per_task_run": max_tool_rounds,
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": budget_event.to_dict()}
                break
            outcome.turn_count = round_index
            outcome.model_call_count += 1
            round_tool_calls: list[dict[str, Any]] = []
            round_tool_messages: list[ToolMessage] = []
            round_write_budget_reserved = False
            assistant_tool_call_content = ""
            assistant_tool_call_kwargs: dict[str, Any] = {}
            if round_index > 1:
                followup_event = self.event_log.append(
                    task_run_id,
                    "loop_iteration_started",
                    payload={
                        "transition": "autonomous_task_continue_after_tool_result",
                        "turn_count": round_index,
                        "tool_call_count": len(pending_tool_calls),
                        "tool_observation_count": tool_observation_count,
                        "delegation_observation_count": delegation_observation_count,
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=conversation_messages,
                directive=safe_directive,
                tool_instances=model_tool_instances,
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                event_type = str(event.get("type") or "")
                if event_type == "tool_call_requested":
                    requested_tool_name = str(event.get("tool_name") or dict(event.get("tool_call") or {}).get("name") or "")
                    contract_gate = _contract_gate_tool_request(
                        goal_contract=goal_contract,
                        tracker=action_tracker,
                        requested_tool_name=requested_tool_name,
                        allowed_tool_names=allowed_tool_names,
                    )
                    if not contract_gate.allowed:
                        contract_gate_blocked = True
                        tool_call_budget_exceeded = True
                        if "write_file" in contract_gate.next_required_tool_names:
                            write_budget_reserved = True
                            round_write_budget_reserved = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": contract_gate.error,
                                "message": contract_gate.message,
                                "tool_name": requested_tool_name,
                                "goal_contract": goal_contract.to_dict(),
                                "action_tracker": action_tracker.to_dict(),
                                "next_required_tool_names": list(contract_gate.next_required_tool_names),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    if (
                        write_output_required
                        and write_observation_count <= 0
                        and "write_file" in set(allowed_tool_names)
                        and len(pending_tool_calls) >= max(1, max_tool_calls_per_task_run - 1)
                        and requested_tool_name != "write_file"
                    ):
                        tool_call_budget_exceeded = True
                        write_budget_reserved = True
                        round_write_budget_reserved = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "autonomous_task_write_budget_reserved",
                                "message": "用户目标要求写入产物，运行时保留最后工具预算给 write_file，阻断继续泛化读搜。",
                                "tool_name": requested_tool_name,
                                "write_output_required": True,
                                "write_observation_count": write_observation_count,
                                "remaining_tool_budget": max_tool_calls_per_task_run - len(pending_tool_calls),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    if requested_tool_name == "delegate_to_agent" and (
                        not delegation_enabled or delegation_observation_count >= max_delegate_calls
                    ):
                        tool_call_budget_exceeded = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "autonomous_task_delegation_budget_exceeded",
                                "message": "自主任务委派次数已达上限，超出预算的委派请求未执行。",
                                "max_delegate_calls_per_task_run": max_delegate_calls,
                                "tool_name": requested_tool_name,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    if len(round_tool_calls) >= max_tool_calls or len(pending_tool_calls) >= max_tool_calls_per_task_run:
                        tool_call_budget_exceeded = True
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "autonomous_task_tool_call_budget_exceeded",
                                "message": "自主任务工具调用次数已达上限，超出预算的工具请求未执行。",
                                "max_tool_calls_per_round": max_tool_calls,
                                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                                "tool_name": requested_tool_name,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": blocked_event.to_dict()}
                        continue
                    tool_call = dict(event.get("tool_call") or {})
                    if tool_call:
                        round_tool_calls.append(tool_call)
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
                        if str(observation_payload.get("tool_name") or "") in {"write_file", "edit_file"}:
                            write_observation_count += 1
                        _record_contract_observation(action_tracker, observation_payload)
                        message = ToolMessage(
                            content=str(observation_payload.get("result") or ""),
                            tool_call_id=str(
                                observation_payload.get("tool_call_id")
                                or dict(event.get("tool_call") or {}).get("id")
                                or getattr(runtime_event, "event_id", "")
                            ),
                        )
                        round_tool_messages.append(message)
                        tool_messages.append(message)
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

            if round_write_budget_reserved and outcome.terminal_reason == "completed" and not round_tool_messages:
                if outcome.turn_count < max_tool_rounds:
                    repair_instruction = _contract_repair_instruction(
                        goal_contract=goal_contract,
                        tracker=action_tracker,
                        gate_decision=contract_gate if "contract_gate" in locals() else None,
                    )
                    conversation_messages = [
                        *conversation_messages,
                        {
                            "role": "system",
                            "content": repair_instruction,
                        },
                    ]
                    outcome.final_content = ""
                    continue
                tool_call_budget_exceeded = True

            if round_tool_messages and outcome.terminal_reason == "completed":
                observation_state_event = self.event_log.append(
                    task_run_id,
                    "autonomous_task_state_changed",
                    payload={
                        "from_state": "action_dispatched" if not action_step_completed else "step_evaluated",
                        "to_state": "observation_received",
                        "mode": autonomy_mode,
                        "tool_observation_count": tool_observation_count,
                        "delegation_observation_count": delegation_observation_count,
                        "round_tool_observation_count": len(round_tool_messages),
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": observation_state_event.to_dict()}
                if not action_step_completed:
                    outcome.state, outcome.ledger = self._complete_standard_action_step_after_observation(
                        state=outcome.state,
                        ledger=outcome.ledger,
                        plan=plan,
                        task_contract_ref=task_contract_ref,
                        observation_refs=tuple(action_observation_refs),
                        autonomy_mode=autonomy_mode,
                    )
                    action_step_completed = True
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
                write_guidance = ""
                if (
                    write_output_required
                    and write_observation_count <= 0
                    and "write_file" in set(allowed_tool_names)
                ):
                    write_guidance = (
                        "用户目标包含写入/保存/产出文件要求；如果核心材料已经足够，"
                        "下一步应优先使用 write_file 在 sandbox overlay 中产出草案文件，"
                        "不要把剩余预算继续消耗在泛化搜索上。"
                    )
                contract_guidance = _contract_followup_guidance(goal_contract=goal_contract, tracker=action_tracker)
                conversation_messages = [
                    *conversation_messages,
                    AIMessage(
                        content=assistant_tool_call_content,
                        tool_calls=round_tool_calls,
                        additional_kwargs=assistant_tool_call_kwargs,
                    ),
                    *round_tool_messages,
                    {
                        "role": "system",
                        "content": (
                            "你已经收到上一轮真实工具观察结果。"
                            "如果还需要读文件、修改、验证或委派，请继续使用真实工具调用接口；"
                            "如果已经满足用户目标，请直接收口。"
                            f"{write_guidance}"
                            f"{contract_guidance}"
                            "不要把工具调用、DSML、JSON schema 或内部协议当作回答文本输出。"
                        ),
                    },
                ]
                outcome.final_content = ""
                continue

            if _contains_tool_call_markup(outcome.final_content):
                if (
                    tool_execution_enabled
                    and len(pending_tool_calls) < max_tool_calls_per_task_run
                    and outcome.turn_count < max_tool_rounds
                ):
                    repair_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "autonomous_task_tool_markup_repair_requested",
                            "message": "模型把工具调用写成了可见文本，运行时要求重新用真实工具接口执行或基于已有证据收口。",
                            "tool_call_count": len(pending_tool_calls),
                            "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                    conversation_messages = [
                        *conversation_messages,
                        {
                            "role": "assistant",
                            "content": outcome.final_content,
                        },
                        {
                            "role": "system",
                            "content": (
                                "上一条回复无效：你把工具调用写进了最终文本，但运行时没有执行它。"
                                "如果需要操作，请现在使用真实工具调用接口；如果不需要工具，请只总结已真实发生的观察。"
                            ),
                        },
                    ]
                    outcome.final_content = ""
                    continue
                outcome.terminal_reason = "tool_call_markup_leaked"
            break

        if (
            tool_call_budget_exceeded
            and outcome.terminal_reason == "completed"
            and not str(outcome.final_content or "").strip()
        ):
            closeout_started_event = self.event_log.append(
                task_run_id,
                "autonomous_task_budget_closeout_started",
                payload={
                    "mode": autonomy_mode,
                    "reason": "tool_budget_exhausted",
                    "tool_call_count": len(pending_tool_calls),
                    "tool_observation_count": tool_observation_count,
                    "delegation_observation_count": delegation_observation_count,
                    "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                    "max_tool_rounds_per_task_run": max_tool_rounds,
                    "write_budget_reserved": bool(write_budget_reserved),
                },
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": closeout_started_event.to_dict()}
            closeout_messages = [
                *conversation_messages,
                {
                    "role": "system",
                    "content": (
                        "工具预算已经耗尽，禁止继续请求任何工具或委派。"
                        "现在必须只基于已经真实返回的工具观察结果完成最终收口。"
                        "如果证据不足，明确写出限制；如果用户要求写入但尚未写入，说明尚未完成写入，"
                        "不要假装已写入。最终回答需要覆盖：目标、已完成的观察、结构性结论、"
                        "回归/测试建议或后续修复步骤。"
                        "不要输出 DSML、tool_calls、invoke、工具参数或任何伪工具调用文本。"
                    ),
                },
            ]
            outcome.model_call_count += 1
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=closeout_messages,
                directive=_model_only_directive(safe_directive, mode=autonomy_mode),
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

        if _contains_tool_call_markup(outcome.final_content):
            sanitized_final_content = _strip_tool_call_markup(outcome.final_content)
            if sanitized_final_content and sanitized_final_content != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized_final_content
            else:
                markup_repair_event = self.event_log.append(
                    task_run_id,
                    "autonomous_task_markup_closeout_repair_started",
                    payload={
                        "mode": autonomy_mode,
                        "reason": "tool_call_markup_in_closeout",
                        "tool_call_count": len(pending_tool_calls),
                        "tool_observation_count": tool_observation_count,
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": markup_repair_event.to_dict()}
                repair_messages = [
                    *conversation_messages,
                    {
                        "role": "system",
                        "content": (
                            "上一条最终收口无效，因为它仍然包含伪工具调用或 DSML。"
                            "工具预算已经关闭，禁止继续请求工具。"
                            "请只用普通中文输出最终结论，不要包含任何工具名、参数块、XML、DSML 或 invoke。"
                            "必须基于已有真实观察说明结论和限制。"
                        ),
                    },
                ]
                outcome.model_call_count += 1
                async for event in model_response_executor.stream(
                    user_message=user_message,
                    model_messages=repair_messages,
                    directive=_model_only_directive(safe_directive, mode=autonomy_mode),
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
                        outcome.final_content = _strip_tool_call_markup(str(event.get("content") or ""))
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
                if _contains_tool_call_markup(outcome.final_content) or not str(outcome.final_content or "").strip():
                    outcome.final_content = ""
                    outcome.terminal_reason = "tool_call_markup_leaked"

        final_protocol_leak_detected = _contains_tool_call_markup(outcome.final_content)
        if final_protocol_leak_detected:
            sanitized = _sanitize_final_content(outcome.final_content)
            if sanitized != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized

        if (
            tool_call_budget_exceeded
            and outcome.terminal_reason == "completed"
            and not str(outcome.final_content or "").strip()
        ):
            outcome.terminal_reason = "tool_loop_budget_exceeded"

        verification_ready_event = self.event_log.append(
            task_run_id,
            "autonomous_task_state_changed",
            payload={"from_state": "step_evaluated", "to_state": "verification_ready", "mode": autonomy_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": verification_ready_event.to_dict()}
        verification = _verify_goal_contract(
            mode=autonomy_mode,
            outcome=outcome,
            plan=plan,
            goal_contract=goal_contract,
            tracker=action_tracker,
            tool_execution_enabled=tool_execution_enabled,
            tool_call_count=len(pending_tool_calls),
            tool_observation_count=tool_observation_count,
            delegation_enabled=delegation_enabled,
            delegation_observation_count=delegation_observation_count,
            write_output_required=write_output_required,
            write_observation_count=write_observation_count,
            write_budget_reserved=write_budget_reserved,
            tool_budget_exhausted=tool_call_budget_exceeded,
            contract_gate_blocked=contract_gate_blocked,
            protocol_leak_detected=final_protocol_leak_detected,
        )
        if _should_repair_contract_closeout(verification):
            repair_started_event = self.event_log.append(
                task_run_id,
                "autonomous_task_contract_closeout_repair_started",
                payload={
                    "mode": autonomy_mode,
                    "missing_response_terms": list(verification.get("missing_response_terms") or []),
                    "protocol_leak_detected": bool(verification.get("protocol_leak_detected") is True),
                    "tool_call_count": len(pending_tool_calls),
                    "tool_observation_count": tool_observation_count,
                },
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": repair_started_event.to_dict()}
            repair_messages = [
                *conversation_messages,
                {
                    "role": "assistant",
                    "content": str(outcome.final_content or ""),
                },
                {
                    "role": "system",
                    "content": _contract_closeout_repair_instruction(
                        goal_contract=goal_contract,
                        verification=verification,
                    ),
                },
            ]
            outcome.model_call_count += 1
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=repair_messages,
                directive=_model_only_directive(safe_directive, mode=autonomy_mode),
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
                    outcome.final_content = _sanitize_final_content(str(event.get("content") or ""))
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
            final_protocol_leak_detected = bool(final_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content))
            verification = _verify_goal_contract(
                mode=autonomy_mode,
                outcome=outcome,
                plan=plan,
                goal_contract=goal_contract,
                tracker=action_tracker,
                tool_execution_enabled=tool_execution_enabled,
                tool_call_count=len(pending_tool_calls),
                tool_observation_count=tool_observation_count,
                delegation_enabled=delegation_enabled,
                delegation_observation_count=delegation_observation_count,
                write_output_required=write_output_required,
                write_observation_count=write_observation_count,
                write_budget_reserved=write_budget_reserved,
                tool_budget_exhausted=tool_call_budget_exceeded,
                contract_gate_blocked=contract_gate_blocked,
                protocol_leak_detected=final_protocol_leak_detected,
            )
        if (
            outcome.terminal_reason in {"completed", "tool_loop_budget_exceeded"}
            and not bool(verification.get("passed") is True)
        ):
            outcome.terminal_reason = "partial_contract_failed"
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


def _build_goal_contract(
    *,
    task_run_id: str,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
) -> AutonomousTaskGoalContract:
    _ = selected_recipe_payload
    goal = str(user_message or "").strip()
    output_paths = _extract_goal_output_paths(goal)
    material_paths = [
        path for path in _extract_goal_material_paths(goal) if not _same_path_member(path, output_paths)
    ]
    material_types = _dedupe_strings([_path_suffix(path) for path in material_paths if _path_suffix(path)])
    requires_write = _goal_text_requires_write_output(goal, material_paths=material_paths, output_paths=output_paths)
    requires_verify = _goal_text_requires_verification_command(goal)
    requires_delegation = _goal_text_requires_delegation(goal, material_types=material_types)
    requires_material_review = bool(material_paths)
    required_tool_kinds: list[str] = []
    if requires_material_review:
        required_tool_kinds.append("read_material")
    if requires_write:
        required_tool_kinds.append("write_output")
    if requires_verify:
        required_tool_kinds.append("verify_command")
    if requires_delegation:
        required_tool_kinds.append("delegate_review")
    required_output_kinds = ["final_answer"]
    if requires_write:
        required_output_kinds.append("sandbox_file")
    return AutonomousTaskGoalContract(
        contract_id=f"autonomous-goal-contract:{task_run_id}",
        goal=goal,
        required_material_paths=material_paths,
        required_output_paths=output_paths,
        material_types=material_types,
        required_tool_kinds=required_tool_kinds,
        required_output_kinds=required_output_kinds,
        requires_material_review=requires_material_review,
        requires_write_output=requires_write,
        requires_verification_command=requires_verify,
        requires_delegation=requires_delegation,
        response_must_include=_response_terms_from_goal(goal),
        forbidden_visible_markers=_forbidden_visible_markers(),
    )


def _extract_goal_material_paths(text: str) -> list[str]:
    return _dedupe_strings(
        [
            path
            for path, prefix in _path_mentions_with_prefix(text)
            if not _prefix_indicates_output_path(prefix)
        ]
    )


def _extract_goal_output_paths(text: str) -> list[str]:
    return _dedupe_strings(
        [
            path
            for path, prefix in _path_mentions_with_prefix(text)
            if _prefix_indicates_output_path(prefix)
        ]
    )


def _path_mentions_with_prefix(text: str) -> list[tuple[str, str]]:
    normalized = str(text or "")
    suffixes = "py|json|md|txt|csv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx"
    patterns = [
        re.compile(
            rf"(?P<path>(?:[\w.\-\u4e00-\u9fff]+[\\/])[\w.\-\u4e00-\u9fff /\\:：()（）]+?\.({suffixes}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?<![\w/\\.-])(?P<path>[\w.\-\u4e00-\u9fff]+\.({suffixes}))(?![\w/\\.-])",
            re.IGNORECASE,
        ),
    ]
    mentions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(normalized):
            path = _clean_path_mention(str(match.group("path") or ""))
            if not path or path in seen:
                continue
            seen.add(path)
            prefix = normalized[max(0, match.start() - 18) : match.start()]
            mentions.append((path, prefix))
    return mentions


def _clean_path_mention(path: str) -> str:
    return str(path or "").strip().strip("`'\"“”‘’（）()[]{}，。；;、")


def _prefix_indicates_output_path(prefix: str) -> bool:
    return any(
        marker in str(prefix or "")
        for marker in (
            "写入",
            "保存",
            "生成",
            "产出",
            "输出到",
            "落到",
            "创建",
            "新建",
        )
    )


def _same_path_member(path: str, paths: list[str]) -> bool:
    normalized = _normalize_path_for_match(path)
    return any(normalized == _normalize_path_for_match(item) for item in paths)


def _path_suffix(path: str) -> str:
    text = str(path or "").strip()
    if "." not in text:
        return ""
    suffix = "." + text.rsplit(".", 1)[-1].lower()
    return suffix if len(suffix) > 1 else ""


def _goal_text_requires_write_output(
    text: str,
    *,
    material_paths: list[str],
    output_paths: list[str],
) -> bool:
    normalized = str(text or "").lower()
    if any(
        marker in normalized
        for marker in (
            "写入",
            "保存",
            "产出",
            "生成文件",
            "草案文件",
            "实施草案",
            "创建文件",
            "新建文件",
            "sandbox overlay 中完成",
            "sandbox overlay",
        )
    ):
        return True
    if output_paths:
        return True
    code_or_config_target = any(_path_suffix(path) in {".py", ".ts", ".tsx", ".js", ".jsx", ".json"} for path in material_paths)
    return code_or_config_target and any(marker in normalized for marker in ("修复", "改掉", "修改", "编辑"))


def _goal_text_requires_verification_command(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        marker in normalized
        for marker in (
            "运行命令",
            "命令验证",
            "运行一个命令",
            "运行一个只读命令",
            "powershell",
            "terminal",
            "shell",
        )
    )


def _goal_text_requires_delegation(text: str, *, material_types: list[str]) -> bool:
    normalized = str(text or "").lower()
    if any(marker in normalized for marker in ("必须委派", "需要委派", "交给子 agent", "交给子agent")):
        return True
    specialist_types = {".pdf", ".xlsx", ".xls", ".docx", ".pptx"}
    return bool(specialist_types.intersection(set(material_types)))


def _response_terms_from_goal(text: str) -> list[str]:
    normalized = str(text or "")
    terms: list[str] = []
    for marker in (
        "结构",
        "根因",
        "回归",
        "治理",
        "库存",
        "行动",
        "后端",
        "前端",
        "测试",
        "超时",
        "原因",
        "验证",
    ):
        if marker.lower() in normalized.lower():
            terms.append(marker)
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){1,4}\b", normalized):
        terms.append(match.group(0).strip())
    for match in re.finditer(r"\b[A-Z0-9][A-Z0-9-]{3,}\b", normalized):
        terms.append(match.group(0).strip())
    for match in re.finditer(r"必须包含([^。；;\n]+)", normalized):
        chunk = match.group(1)
        for part in re.split(r"[、,，和与]", chunk):
            value = part.strip(" ：:。；;，,")
            if value:
                terms.append(value)
    return _dedupe_strings(terms)[:10]


def _forbidden_visible_markers() -> list[str]:
    return [
        "<｜｜DSML",
        "｜｜parameter",
        "tool_calls",
        "invoke name=",
        "<tool_call",
        'name="read_file"',
        'name="search_text"',
        'name="search_files"',
        'name="delegate_to_agent"',
    ]


def _material_review_summary(contract: AutonomousTaskGoalContract) -> str:
    if contract.required_material_paths:
        return "必须先取得这些材料的真实观察：" + "、".join(contract.required_material_paths[:6])
    return "复核当前可见上下文和能力边界。"


def _produce_output_summary(contract: AutonomousTaskGoalContract) -> str:
    if contract.required_output_paths:
        return "必须通过 write_file/edit_file 产出：" + "、".join(contract.required_output_paths[:4])
    return "必须通过 write_file 或 edit_file 形成用户要求的真实产物；不能只在最终回答里声称已产出。"


def _synthesis_summary(contract: AutonomousTaskGoalContract) -> str:
    terms = "、".join(contract.response_must_include)
    if terms:
        return f"最终回答必须覆盖验收词：{terms}；并说明真实完成项、限制和下一步。"
    return "最终回答必须基于真实观察说明完成项、结论、限制和下一步。"


def _required_operations_for_contract_materials(contract: AutonomousTaskGoalContract) -> list[str]:
    operations = ["op.read_file", "op.search_files", "op.search_text"]
    if any(suffix in {".json", ".yaml", ".yml", ".toml"} for suffix in contract.material_types):
        operations.insert(0, "op.read_structured_file")
    if contract.requires_delegation:
        operations.append("op.delegate_to_agent")
    return _dedupe_strings(operations)


def _goal_contract_instruction(goal_contract: AutonomousTaskGoalContract | None) -> str:
    if goal_contract is None:
        return ""
    lines: list[str] = ["目标契约："]
    if goal_contract.required_material_paths:
        lines.append("必须取得真实材料观察：" + "、".join(goal_contract.required_material_paths[:6]) + "。")
    if goal_contract.requires_write_output:
        lines.append("用户要求真实写入或修改产物；必须使用 write_file 或 edit_file，不能只口头声称完成。")
    if goal_contract.requires_verification_command:
        lines.append("用户要求命令验证；完成写入或修改后必须使用 terminal 返回真实验证结果。")
    if goal_contract.requires_delegation:
        lines.append("如主 Agent 不能稳定读取专业材料，只能通过 delegate_to_agent 发起受控材料核对，并综合回传证据。")
    if goal_contract.response_must_include:
        lines.append("最终回答必须覆盖：" + "、".join(goal_contract.response_must_include) + "。")
    lines.append("最终回答不得包含 DSML、tool_calls、invoke、工具参数或伪工具调用。")
    return "\n".join(lines) + "\n"


def _standard_control_plan(
    *,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
    goal_contract: AutonomousTaskGoalContract | None = None,
) -> list[dict[str, Any]]:
    _ = selected_recipe_payload
    goal = str(user_message or "").strip()
    contract = goal_contract or _build_goal_contract(
        task_run_id="unknown",
        user_message=user_message,
        selected_recipe_payload=selected_recipe_payload,
    )
    plan: list[dict[str, Any]] = [
        {
            "plan_item_id": "autonomous.goal_lock",
            "title": "锁定任务目标、边界和验收口径",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": goal[:200],
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
    ]
    if contract.requires_material_review:
        plan.append(
            {
                "plan_item_id": "autonomous.material_review",
                "title": "读取或检索指定材料",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _material_review_summary(contract),
                "required_operations": _required_operations_for_contract_materials(contract),
                "material_paths": list(contract.required_material_paths),
                "contract_required": True,
            }
        )
    else:
        plan.append(
            {
                "plan_item_id": "autonomous.context_review",
                "title": "复核当前可见上下文和能力边界",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "确认当前阶段只使用已装配上下文和真实工具观察，不声称未发生的执行。",
                "required_operations": ["op.model_response"],
                "contract_required": False,
            }
        )
    if contract.requires_write_output:
        plan.append(
            {
                "plan_item_id": "autonomous.produce_output",
                "title": "产出用户要求的文件或修改",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _produce_output_summary(contract),
                "required_operations": ["op.write_file", "op.edit_file"],
                "output_paths": list(contract.required_output_paths),
                "contract_required": True,
            }
        )
    if contract.requires_verification_command:
        plan.append(
            {
                "plan_item_id": "autonomous.verify_output",
                "title": "运行命令验证真实结果",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "使用 terminal 运行只读或沙箱内验证命令，并把真实结果纳入最终结论。",
                "required_operations": ["op.shell"],
                "contract_required": True,
            }
        )
    if contract.requires_delegation:
        plan.append(
            {
                "plan_item_id": "autonomous.delegation_review",
                "title": "受控委派专业材料核对",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "仅在主 Agent 工具无法稳定读取专业材料时，委派受限子 Agent 返回 evidence packet。",
                "required_operations": ["op.delegate_to_agent"],
                "contract_required": True,
            }
        )
    plan.extend(
        [
        {
            "plan_item_id": "autonomous.synthesize_answer",
            "title": "综合证据形成用户可读结论",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": _synthesis_summary(contract),
            "required_operations": ["op.model_response"],
            "response_must_include": list(contract.response_must_include),
            "contract_required": True,
        },
        {
            "plan_item_id": "autonomous.final_check",
            "title": "完成结论、自检和下一步建议",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": "按目标契约检查材料、写入、验证、协议边界和最终回答是否满足验收。",
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
        ]
    )
    return plan


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
    max_tool_rounds: int = 1,
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
            "controlled_tool_rounds": max(1, int(max_tool_rounds or 1)),
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
        max_tool_calls_per_task_run=0,
        max_tool_rounds=0,
        goal_contract=None,
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
    max_tool_calls_per_task_run: int = 0,
    max_tool_rounds: int = 0,
    max_delegate_calls: int = 0,
    goal_contract: AutonomousTaskGoalContract | None = None,
) -> list[Any]:
    plan_lines = "\n".join(
        f"- {item['title']}: {item['summary']}"
        for item in plan_items
        if str(item.get("title") or "").strip()
    )
    allowed_tools = [str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()]
    contract_line = _goal_contract_instruction(goal_contract)
    if tool_execution_enabled:
        write_guidance = ""
        if "write_file" in set(allowed_tools):
            write_guidance = (
                "如果用户明确要求写入、保存、产出草案文件或在 sandbox overlay 中交付文件，"
                "在读到核心材料后应尽快调用 write_file 产出文件；不要把工具预算耗尽在泛化搜索上。"
            )
        tool_line = (
            "当前模式已开放预算受控的真实工具观察；只能基于真实工具结果写结论。"
            f"可用工具：{', '.join(allowed_tools) or '无'}。"
            f"每轮最多请求 {max(1, int(max_tool_calls or 1))} 个工具调用，"
            f"整个任务最多请求 {max(1, int(max_tool_calls_per_task_run or max_tool_calls or 1))} 个工具调用，"
            f"最多推进 {max(1, int(max_tool_rounds or 1))} 轮。"
            "如果还没有完成用户目标，可以在下一轮继续使用真实工具；如果已经完成，请直接收口。"
            f"{write_guidance}"
            "不要把工具调用、DSML、JSON schema 或内部协议写进可见回答。"
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
        f"{contract_line}"
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
        if step_id and any(
            token in step_id
            for token in (
                "material_review",
                "context_review",
                "produce_output",
                "verify_output",
                "delegation_review",
                "execute",
                "inspect",
                "analysis",
            )
        ):
            return step_id
    for item in items:
        step_id = str(item.get("plan_item_id") or item.get("step_id") or "").strip()
        if step_id and "goal" not in step_id:
            return step_id
    return str(dict(items[0]).get("plan_item_id") or dict(items[0]).get("step_id") or "").strip() if items else ""


def _goal_requires_write_output(plan: list[dict[str, Any]]) -> bool:
    text = " ".join(
        str(part or "")
        for item in list(plan or [])
        if isinstance(item, dict)
        for part in (
            item.get("title"),
            item.get("summary"),
        )
    ).lower()
    return any(
        marker in text
        for marker in (
            "写入",
            "保存",
            "产出",
            "生成文件",
            "草案文件",
            "sandbox overlay",
            "write_file",
        )
    )


def _record_contract_observation(
    tracker: AutonomousTaskActionTracker,
    observation_payload: dict[str, Any],
) -> None:
    tool_name = str(observation_payload.get("tool_name") or "").strip()
    if not tool_name:
        return
    tracker.tool_observation_count += 1
    tracker.tool_names = _dedupe_strings([*tracker.tool_names, tool_name])
    tool_args = dict(observation_payload.get("tool_args") or {})
    path = _clean_path_mention(str(tool_args.get("path") or ""))
    if tool_name in {"read_file", "read_structured_file"}:
        if path:
            tracker.read_material_paths = _dedupe_strings([*tracker.read_material_paths, path])
    elif tool_name in {"search_files", "search_text", "glob_paths"}:
        query = str(tool_args.get("query") or tool_args.get("pattern") or "").strip()
        if query:
            tracker.searched_material_refs = _dedupe_strings([*tracker.searched_material_refs, query])
    elif tool_name == "write_file":
        if path:
            tracker.write_paths = _dedupe_strings([*tracker.write_paths, path])
        tracker.artifact_observation_count += 1
    elif tool_name == "edit_file":
        if path:
            tracker.edit_paths = _dedupe_strings([*tracker.edit_paths, path])
        tracker.artifact_observation_count += 1
    elif tool_name == "terminal":
        command = str(tool_args.get("command") or "").strip()
        if command:
            tracker.terminal_commands = _dedupe_strings([*tracker.terminal_commands, command[:240]])
    elif tool_name == "delegate_to_agent":
        tracker.delegation_observation_count += 1


def _contract_gate_tool_request(
    *,
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
    requested_tool_name: str,
    allowed_tool_names: list[str] | tuple[str, ...],
) -> AutonomousTaskContractGateDecision:
    tool_name = str(requested_tool_name or "").strip()
    allowed = set(str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip())
    read_tools = {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths"}
    if goal_contract.requires_write_output and tracker.write_observation_count <= 0:
        if _material_review_satisfied(goal_contract, tracker):
            write_tools = tuple(name for name in ("write_file", "edit_file") if name in allowed)
            if tool_name in read_tools or tool_name == "delegate_to_agent":
                return AutonomousTaskContractGateDecision(
                    allowed=False,
                    error="autonomous_task_goal_contract_requires_write",
                    message="目标契约要求产出真实文件或修改；材料观察已经足够，继续读搜或委派会偏离目标。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tracker=tracker,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=write_tools,
                )
            if write_tools and tool_name not in write_tools:
                return AutonomousTaskContractGateDecision(
                    allowed=False,
                    error="autonomous_task_goal_contract_requires_write",
                    message="目标契约要求下一步使用 write_file 或 edit_file 形成真实产物。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tracker=tracker,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=write_tools,
                )
    if (
        goal_contract.requires_verification_command
        and tracker.write_observation_count > 0
        and tracker.verification_command_count <= 0
        and "terminal" in allowed
        and tool_name in read_tools.union({"write_file", "edit_file", "delegate_to_agent"})
    ):
        return AutonomousTaskContractGateDecision(
            allowed=False,
            error="autonomous_task_goal_contract_requires_verification",
            message="目标契约要求写入或修改后运行命令验证；下一步必须使用 terminal 返回真实验证结果。",
            repair_instruction=_contract_repair_instruction(
                goal_contract=goal_contract,
                tracker=tracker,
                next_required_tool_names=("terminal",),
            ),
            next_required_tool_names=("terminal",),
        )
    return AutonomousTaskContractGateDecision(allowed=True)


def _contract_repair_instruction(
    *,
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
    gate_decision: AutonomousTaskContractGateDecision | None = None,
    next_required_tool_names: tuple[str, ...] = (),
) -> str:
    if gate_decision is not None and gate_decision.repair_instruction:
        return gate_decision.repair_instruction
    required_tools = tuple(next_required_tool_names or _next_required_tools(goal_contract, tracker))
    if "write_file" in required_tools or "edit_file" in required_tools:
        output_hint = (
            "目标路径：" + "、".join(goal_contract.required_output_paths)
            if goal_contract.required_output_paths
            else "请在 sandbox overlay 中选择清晰的输出路径。"
        )
        return (
            "上一轮请求已被目标契约拦截。用户目标要求真实产出文件或修改。"
            f"{output_hint}"
            "下一步只能使用 write_file 或 edit_file；不要再请求 read_file、search_files、search_text 或委派。"
            "如果确实无法写入，请只用普通中文说明阻塞原因，不要伪造工具调用。"
        )
    if "terminal" in required_tools:
        return (
            "上一轮请求已被目标契约拦截。用户目标要求命令验证。"
            "下一步只能使用 terminal 运行验证命令，并基于真实输出收口；不要继续读搜或改写。"
        )
    return (
        "上一轮请求已被目标契约拦截。请回到用户目标，只使用真实工具完成缺失动作；"
        "如果无法继续，直接说明缺失证据和阻塞原因。"
    )


def _contract_followup_guidance(
    *,
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
) -> str:
    required_tools = _next_required_tools(goal_contract, tracker)
    if not required_tools:
        return ""
    return "目标契约下一步仍缺少：" + "、".join(required_tools) + "。"


def _next_required_tools(
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
) -> tuple[str, ...]:
    if goal_contract.requires_write_output and tracker.write_observation_count <= 0 and _material_review_satisfied(goal_contract, tracker):
        return ("write_file", "edit_file")
    if goal_contract.requires_verification_command and tracker.write_observation_count > 0 and tracker.verification_command_count <= 0:
        return ("terminal",)
    if goal_contract.requires_material_review and not _material_review_satisfied(goal_contract, tracker):
        return ("read_file", "read_structured_file", "search_files", "search_text")
    return ()


def _material_review_satisfied(
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
) -> bool:
    if not goal_contract.requires_material_review:
        return True
    if not goal_contract.required_material_paths:
        return bool(tracker.read_material_paths or tracker.searched_material_refs or tracker.delegation_observation_count)
    for path in goal_contract.required_material_paths:
        if _material_path_observed(path, tracker):
            continue
        return False
    return True


def _material_path_observed(path: str, tracker: AutonomousTaskActionTracker) -> bool:
    normalized = _normalize_path_for_match(path)
    base = normalized.rsplit("/", 1)[-1]
    for item in tracker.read_material_paths:
        observed = _normalize_path_for_match(item)
        observed_base = observed.rsplit("/", 1)[-1]
        if observed == normalized or observed.endswith("/" + normalized):
            return True
        if normalized.endswith("/" + observed) or (base and observed_base == base):
            return True
    return any(base and base in _normalize_path_for_match(item) for item in tracker.searched_material_refs)


def _normalize_path_for_match(path: str) -> str:
    return str(path or "").strip().strip("`'\"“”‘’").replace("\\", "/").lower()


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


def _contains_tool_call_markup(content: str) -> bool:
    text = str(content or "")
    lowered = text.lower()
    return any(
        marker in text or marker in lowered
        for marker in (
            "<｜｜DSML｜｜tool_calls>",
            "<｜｜DSML｜｜invoke",
            "<tool_call",
            "</tool_call",
            '"tool_calls"',
            "'tool_calls'",
            "invoke name=",
            "name=\"read_file\"",
            "name=\"search_text\"",
            "name=\"search_files\"",
            "name=\"delegate_to_agent\"",
            "｜｜parameter",
            "｜｜invoke",
        )
    )


def _strip_tool_call_markup(content: str) -> str:
    text = str(content or "").replace("\r\n", "\n")
    for marker in ("<｜｜DSML｜｜tool_calls>", "<｜｜DSML｜｜invoke", "<tool_call"):
        index = text.find(marker)
        if index >= 0:
            text = text[:index]
    lines: list[str] = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(
            marker in line or marker in lowered
            for marker in (
                "<｜｜DSML",
                "</｜｜DSML",
                "｜｜parameter",
                "｜｜invoke",
                "tool_calls",
                "invoke name=",
                "name=\"read_file\"",
                "name=\"search_text\"",
                "name=\"search_files\"",
                "name=\"delegate_to_agent\"",
            )
        ):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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


def _verify_goal_contract(
    *,
    mode: str,
    outcome: AutonomousTaskRunOutcome,
    plan: list[dict[str, Any]],
    goal_contract: AutonomousTaskGoalContract,
    tracker: AutonomousTaskActionTracker,
    tool_execution_enabled: bool,
    tool_call_count: int,
    tool_observation_count: int,
    delegation_enabled: bool,
    delegation_observation_count: int,
    write_output_required: bool,
    write_observation_count: int,
    write_budget_reserved: bool,
    tool_budget_exhausted: bool,
    contract_gate_blocked: bool,
    protocol_leak_detected: bool,
) -> dict[str, Any]:
    final_content = str(outcome.final_content or "").strip()
    missing_required_actions: list[str] = []
    missing_material_paths = [
        path for path in goal_contract.required_material_paths if not _material_path_observed(path, tracker)
    ]
    if missing_material_paths:
        missing_required_actions.append("read_material")
    if goal_contract.requires_write_output and tracker.write_observation_count <= 0:
        missing_required_actions.append("write_output")
    if goal_contract.requires_verification_command and tracker.verification_command_count <= 0:
        missing_required_actions.append("verify_command")
    if goal_contract.requires_delegation and tracker.delegation_observation_count <= 0:
        missing_required_actions.append("delegate_review")
    missing_response_terms = [
        term for term in goal_contract.response_must_include if term and term.lower() not in final_content.lower()
    ]
    protocol_leak = bool(protocol_leak_detected or _contains_tool_call_markup(final_content))
    contract_passed = bool(
        final_content
        and not protocol_leak
        and not missing_required_actions
        and not missing_response_terms
    )
    terminal_passed = outcome.terminal_reason == "completed"
    return {
        "mode": mode,
        "passed": bool(contract_passed and terminal_passed),
        "contract_passed": contract_passed,
        "goal_contract": goal_contract.to_dict(),
        "missing_required_actions": _dedupe_strings(missing_required_actions),
        "missing_material_paths": missing_material_paths,
        "missing_response_terms": missing_response_terms,
        "protocol_leak_detected": protocol_leak,
        "checks": {
            "has_final_content": bool(final_content),
            "ledger_backed_plan": outcome.ledger is not None,
            "dynamic_plan_item_count": len(plan),
            "tool_execution_enabled": tool_execution_enabled,
            "tool_call_count": tool_call_count,
            "tool_observation_count": tool_observation_count,
            "delegation_enabled": delegation_enabled,
            "delegation_observation_count": delegation_observation_count,
            "write_output_required": bool(write_output_required),
            "write_observation_count": write_observation_count,
            "artifact_observation_count": tracker.artifact_observation_count,
            "verification_command_count": tracker.verification_command_count,
            "write_budget_reserved": bool(write_budget_reserved),
            "tool_budget_exhausted": bool(tool_budget_exhausted),
            "contract_gate_blocked": bool(contract_gate_blocked),
            "contract_passed": bool(contract_passed),
            "missing_required_actions": _dedupe_strings(missing_required_actions),
            "missing_response_terms": list(missing_response_terms),
            "protocol_leak_detected": protocol_leak,
            "tool_claim_guard": "event_guarded" if tool_execution_enabled else "prompt_guarded",
            "summary_check_required": True,
            "action_tracker": tracker.to_dict(),
        },
    }


def _should_repair_contract_closeout(verification: dict[str, Any]) -> bool:
    if bool(verification.get("passed") is True):
        return False
    missing_required_actions = list(verification.get("missing_required_actions") or [])
    if missing_required_actions:
        return False
    missing_response_terms = list(verification.get("missing_response_terms") or [])
    return bool(missing_response_terms or verification.get("protocol_leak_detected") is True)


def _contract_closeout_repair_instruction(
    *,
    goal_contract: AutonomousTaskGoalContract,
    verification: dict[str, Any],
) -> str:
    missing_terms = [str(item) for item in list(verification.get("missing_response_terms") or []) if str(item).strip()]
    term_line = "必须补齐这些验收词：" + "、".join(missing_terms) + "。" if missing_terms else ""
    return (
        "上一条最终回答没有通过目标契约验收。工具预算已经关闭，禁止再请求任何工具或委派。"
        "你已经拿到真实观察，必须只基于已返回的材料观察完成综合收口。"
        f"{term_line}"
        "请直接给最终答案：先给失败归类，再给结构性根因，再给应该补的回归测试。"
        "不要写“我将”“继续查看”“跳到某部分”这类过程话术。"
        "不要包含 DSML、tool_calls、invoke、工具参数或伪工具调用。"
    )


def _sanitize_final_content(content: str) -> str:
    return sanitize_visible_assistant_content(_strip_tool_call_markup(content)).strip()


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
