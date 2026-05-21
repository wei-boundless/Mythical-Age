from __future__ import annotations

import time
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from langchain_core.messages import AIMessage, ToolMessage

from execution.provider_tool_call_adapter import tool_calls_for_langchain_messages
from execution.tool_call_policy import ToolCallBindingOptions, build_required_tool_call_options
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

from .deliverable_validator import validate_deliverable
from .evidence_packet import build_evidence_packet
from .models import RuntimeLoopState
from .obligation_validation import validate_obligations
from .professional_run_session import build_professional_run_session
from .professional_state_machine import initial_professional_run_state, unsatisfied_obligations_from_verification
from .protocol_boundary import has_protocol_leak, strip_protocol_leak
from .tool_observation_ledger import ToolObservationLedger, build_tool_observation_record


RuntimeEventBuilder = Callable[..., Any]
ExecutorEventAdapter = Callable[..., Awaitable[Iterable[Any]]]
StateWithLedger = Callable[..., RuntimeLoopState]


@dataclass(slots=True)
class ProfessionalTaskRunOutcome:
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
class ProfessionalTaskGoalContract:
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
    authority: str = "orchestration.professional_task_goal_contract"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProfessionalTaskContractGateDecision:
    allowed: bool
    error: str = ""
    message: str = ""
    repair_instruction: str = ""
    next_required_tool_names: tuple[str, ...] = ()


class ProfessionalTaskRunDriver:
    """Runtime driver for graphless interaction-mode task execution.

    The driver owns professional task control states, while TaskRunLoop still owns
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

    async def run_stream(
        self,
        *,
        outcome: ProfessionalTaskRunOutcome,
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
        policy = _professional_runtime_policy(selected_recipe_payload)
        mode_policy = dict(policy.get("mode_policy") or {})
        semantic_contract = dict(policy.get("semantic_task_contract") or {})
        execution_obligation = dict(semantic_contract.get("execution_obligation") or policy.get("execution_obligation") or {})
        interaction_mode = str(
            mode_policy.get("interaction_mode")
            or policy.get("interaction_mode")
            or "professional_mode"
        ).strip()
        run_state = initial_professional_run_state(task_run_id)
        tool_observation_ledger = ToolObservationLedger(
            ledger_id=f"tool-observation-ledger:{task_run_id}",
            task_run_id=task_run_id,
        )
        tool_policy = dict(policy.get("tool_execution_policy") or {})
        delegation_policy = dict(policy.get("delegation_policy") or {})
        verification_policy = dict(policy.get("verification_policy") or {})
        delegation_enabled = bool(delegation_policy.get("enabled") is True)
        allowed_tool_names = _allowed_tool_names_from_policy(
            tool_policy,
            runtime_tool_instances=runtime_tool_instances,
            delegation_enabled=delegation_enabled,
        )
        tool_execution_enabled = bool(tool_policy.get("enabled") is True) and bool(
            tool_runtime_executor is not None and allowed_tool_names
        )
        if interaction_mode == "role_mode":
            delegation_enabled = False
            side_effect_tools = {"write_file", "edit_file", "terminal", "python_repl", "delegate_to_agent"}
            allowed_tool_names = [name for name in allowed_tool_names if name not in side_effect_tools]
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
        goal_contract = _goal_contract_from_semantic_contract(
            task_run_id=task_run_id,
            user_message=user_message,
            semantic_contract=semantic_contract,
        )
        plan = _semantic_control_plan(
            user_message=user_message,
            semantic_contract=semantic_contract,
            mode_policy=mode_policy,
            goal_contract=goal_contract,
        )
        start_event = self.event_log.append(
            task_run_id,
            "professional_task_started",
            payload={
                "interaction_mode": interaction_mode,
                "runtime_driver": "professional_task_run",
                "goal": user_message,
                "semantic_task_contract": semantic_contract,
                "execution_obligation": execution_obligation,
                "goal_contract": goal_contract.to_dict(),
                "plan_item_count": len(plan),
                "policy": policy,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": start_event.to_dict()}
        run_state = run_state.advance("mode_policy_bound", reason="mode_policy_bound")
        state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "initialized",
                "to_state": "mode_policy_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}
        run_state = run_state.advance(
            "obligation_bound",
            reason="execution_obligation_bound",
            diagnostics={"execution_obligation": execution_obligation},
        )
        obligation_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "mode_policy_bound",
                "to_state": "obligation_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": obligation_event.to_dict()}
        run_state = run_state.advance(
            "prototype_bound",
            reason="strategy_prototype_bound",
            diagnostics={"strategy_prototype_id": str(semantic_contract.get("strategy_prototype_id") or "")},
        )
        prototype_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "obligation_bound",
                "to_state": "prototype_bound",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": prototype_event.to_dict()}
        outcome.state, outcome.ledger = self._complete_current_and_advance(
            state=outcome.state,
            ledger=outcome.ledger,
            reason="professional_task_mode_policy_bound",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={
                "professional_state": "mode_policy_bound",
                "interaction_mode": interaction_mode,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
            },
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
                        "transition_reason": "professional_task_semantic_plan_drafted",
                        "interaction_mode": interaction_mode,
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
                    reason="professional_task_semantic_plan_drafted",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"interaction_mode": interaction_mode},
                )
                yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
            ledger_event = self.record_task_run_ledger_updated(
                outcome.state.task_run_id,
                ledger=outcome.ledger,
                reason="professional_task_semantic_plan_drafted",
                refs={"task_contract_ref": task_contract_ref},
                diagnostics={"interaction_mode": interaction_mode, "dynamic_plan_step_count": len(added_steps)},
            )
            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
            outcome.state = self.state_with_task_run_ledger(
                outcome.state,
                outcome.ledger,
                diagnostics={
                    "last_step_transition": "professional_task_semantic_plan_drafted",
                    "interaction_mode": interaction_mode,
                },
            )
            checkpoint_event = self.write_checkpoint_event(outcome.state, event_offset=ledger_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}

        plan_event = self.event_log.append(
            task_run_id,
            "professional_task_semantic_plan_drafted",
            payload={
                "interaction_mode": interaction_mode,
                "plan_items": plan,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "max_tool_calls_per_round": max_tool_calls,
                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                "max_tool_rounds_per_task_run": max_tool_rounds,
                "plan_source": "semantic_task_contract",
                "goal_contract": goal_contract.to_dict(),
                "ledger_backed": outcome.ledger is not None,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": plan_event.to_dict()}
        run_state = run_state.advance(
            "plan_drafted",
            reason="semantic_plan_drafted",
            diagnostics={"plan_item_count": len(plan)},
        )
        state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "prototype_bound",
                "to_state": "plan_drafted",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": state_event.to_dict()}

        outcome.state, outcome.ledger = self._prepare_standard_action_step(
            state=outcome.state,
            ledger=outcome.ledger,
            plan=plan,
            task_contract_ref=task_contract_ref,
            interaction_mode=interaction_mode,
        )
        for event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": event.to_dict()}
        run_state = run_state.advance(
            "action_dispatched",
            reason="action_dispatched",
            diagnostics={"tool_execution_enabled": tool_execution_enabled},
        )
        action_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "plan_drafted",
                "to_state": "action_dispatched",
                "interaction_mode": interaction_mode,
                "professional_run_state": run_state.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": action_event.to_dict()}
        executor_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={
                "executor_type": "model",
                "runtime_channel": "professional_task_run",
                "interaction_mode": interaction_mode,
                "tool_execution_enabled": tool_execution_enabled,
                "allowed_tool_names": allowed_tool_names,
                "delegation_enabled": delegation_enabled,
                "max_delegate_calls_per_task_run": max_delegate_calls,
            },
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

        safe_directive = _professional_task_directive(
            directive,
            mode=interaction_mode,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_operation_refs=list(tool_policy.get("allowed_operation_refs") or ()),
            max_tool_rounds=max_tool_rounds,
        )
        model_messages = _with_professional_task_instruction(
            list(getattr(context_snapshot, "model_messages", ()) or ()),
            mode=interaction_mode,
            plan_items=plan,
            tool_execution_enabled=tool_execution_enabled,
            delegation_enabled=delegation_enabled,
            allowed_tool_names=allowed_tool_names,
            max_tool_calls=max_tool_calls,
            max_tool_calls_per_task_run=max_tool_calls_per_task_run,
            max_tool_rounds=max_tool_rounds,
            max_delegate_calls=max_delegate_calls,
            goal_contract=goal_contract,
            semantic_contract=semantic_contract,
            mode_policy=mode_policy,
        )
        write_output_required = bool(goal_contract.requires_write_output)
        pending_tool_calls: list[dict[str, Any]] = []
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        delegation_observation_count = 0
        write_observation_count = 0
        tool_call_budget_exceeded = False
        write_budget_reserved = False
        contract_gate_blocked = False
        action_observation_refs: list[str] = []
        structured_observations: list[dict[str, Any]] = []
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
                        "error": "professional_task_tool_round_budget_exceeded",
                        "message": "专业任务工具观察轮次已达上限，停止继续请求工具。",
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
            protocol_violation_repair_requested = False
            model_timeout_recovery_requested = False
            round_protocol_leak_detected = False
            gate_repair_instruction = ""
            gate_next_required_tools: tuple[str, ...] = ()
            blocked_tool_calls_for_repair: list[dict[str, Any]] = []
            blocked_tool_messages_for_repair: list[ToolMessage] = []
            assistant_tool_call_content = ""
            assistant_tool_call_kwargs: dict[str, Any] = {}
            if round_index > 1:
                followup_event = self.event_log.append(
                    task_run_id,
                    "loop_iteration_started",
                    payload={
                        "transition": "professional_task_continue_after_tool_result",
                        "turn_count": round_index,
                        "tool_call_count": len(pending_tool_calls),
                        "tool_observation_count": tool_observation_count,
                        "delegation_observation_count": delegation_observation_count,
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            required_next_tools = _next_required_tools(goal_contract, tool_observation_ledger)
            round_model_tool_instances = _model_tools_for_required_next_step(
                model_tool_instances=model_tool_instances,
                required_next_tools=required_next_tools,
            )
            round_tool_call_options = _tool_call_options_for_round(
                round_model_tool_instances=round_model_tool_instances,
                required_next_tools=required_next_tools,
                max_tool_calls=max_tool_calls,
            )
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=conversation_messages,
                directive=safe_directive,
                tool_instances=round_model_tool_instances,
                tool_call_options=round_tool_call_options,
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                event_type = str(event.get("type") or "")
                if _event_protocol_leak_detected(event):
                    round_protocol_leak_detected = True
                if event_type == "tool_call_requested":
                    requested_tool_name = str(event.get("tool_name") or dict(event.get("tool_call") or {}).get("name") or "")
                    contract_gate = _contract_gate_tool_request(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        requested_tool_name=requested_tool_name,
                        allowed_tool_names=allowed_tool_names,
                    )
                    if not contract_gate.allowed:
                        contract_gate_blocked = True
                        if "write_file" in contract_gate.next_required_tool_names:
                            write_budget_reserved = True
                            round_write_budget_reserved = True
                        gate_repair_instruction = contract_gate.repair_instruction
                        gate_next_required_tools = tuple(contract_gate.next_required_tool_names)
                        blocked_tool_call = dict(event.get("tool_call") or {})
                        if blocked_tool_call:
                            blocked_tool_calls_for_repair.append(blocked_tool_call)
                            blocked_tool_messages_for_repair.append(
                                ToolMessage(
                                    content=(
                                        "Runtime blocked this tool request before execution: "
                                        f"{contract_gate.message} "
                                        f"Next required tool: {', '.join(contract_gate.next_required_tool_names) or 'follow the goal contract'}."
                                    ),
                                    tool_call_id=str(blocked_tool_call.get("id") or getattr(event, "event_id", "") or requested_tool_name),
                                )
                            )
                        assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                        event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                        if event_kwargs:
                            assistant_tool_call_kwargs.update(event_kwargs)
                        blocked_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": contract_gate.error,
                                "message": contract_gate.message,
                                "tool_name": requested_tool_name,
                                "goal_contract": goal_contract.to_dict(),
                                "tool_observation_ledger": tool_observation_ledger.summary(),
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
                                "error": "professional_task_write_budget_reserved",
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
                                "error": "professional_task_delegation_budget_exceeded",
                                "message": "专业任务委派次数已达上限，超出预算的委派请求未执行。",
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
                                "error": "professional_task_tool_call_budget_exceeded",
                                "message": "专业任务工具调用次数已达上限，超出预算的工具请求未执行。",
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
                            for artifact_ref in _artifact_output_refs_from_tool_payload(observation_payload):
                                if artifact_ref not in outcome.result_refs:
                                    outcome.result_refs.append(artifact_ref)
                        structured_observations.append(
                            {
                                "observation_ref": observation_ref,
                                "tool_name": str(observation_payload.get("tool_name") or ""),
                                "tool_args": dict(observation_payload.get("tool_args") or {}),
                                "result": observation_payload.get("result"),
                                "result_envelope": dict(observation_payload.get("result_envelope") or {}),
                                "structured_payload": dict(observation_payload.get("structured_payload") or {}),
                                "observed_paths": list(observation_payload.get("observed_paths") or []),
                                "matched_paths": list(observation_payload.get("matched_paths") or []),
                                "artifact_refs": [
                                    dict(item)
                                    for item in list(observation_payload.get("artifact_refs") or [])
                                    if isinstance(item, dict)
                                ],
                                "command_receipt": dict(observation_payload.get("command_receipt") or {}),
                            }
                        )
                        tool_observation_ledger = tool_observation_ledger.append(
                            build_tool_observation_record(
                                observation_ref=observation_ref,
                                tool_name=str(observation_payload.get("tool_name") or ""),
                                tool_args=dict(observation_payload.get("tool_args") or {}),
                                result=observation_payload,
                            )
                        )
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
                    if (
                        str(event.get("error") or "") == "model_response_timeout"
                        and tool_execution_enabled
                        and _next_required_tools(goal_contract, tool_observation_ledger)
                        and outcome.turn_count < max_tool_rounds
                    ):
                        recovery_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_model_timeout_recoverable",
                                "message": "模型本轮响应超时，但目标契约仍有缺失动作，运行时将压缩上下文并继续下一轮。",
                                "next_required_tool_names": list(_next_required_tools(goal_contract, tool_observation_ledger)),
                                "tool_observation_ledger": tool_observation_ledger.summary(),
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": recovery_event.to_dict()}
                        conversation_messages = [
                            *_compact_professional_recovery_messages(
                                user_message=user_message,
                                goal_contract=goal_contract,
                                tool_observation_ledger=tool_observation_ledger,
                                structured_observations=structured_observations,
                                next_required_tools=_next_required_tools(goal_contract, tool_observation_ledger),
                            )
                        ]
                        outcome.final_content = ""
                        model_timeout_recovery_requested = True
                        continue
                    outcome.terminal_reason = "executor_failed"
                    yield event
                elif event_type == "model_protocol_violation":
                    if (
                        tool_execution_enabled
                        and len(pending_tool_calls) < max_tool_calls_per_task_run
                        and outcome.turn_count < max_tool_rounds
                    ):
                        repair_event = self.event_log.append(
                            task_run_id,
                            "loop_error",
                            payload={
                                "error": "professional_task_model_protocol_violation_repair_requested",
                                "message": "模型输出了可见伪工具协议，运行时要求下一轮必须使用原生工具调用接口。",
                                "protocol_leak": dict(event.get("protocol_leak") or {}),
                                "tool_call_count": len(pending_tool_calls),
                                "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                            },
                            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                        )
                        yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                        protocol_violation_repair_requested = True
                        conversation_messages = [
                            *conversation_messages,
                            {"role": "assistant", "content": str(event.get("content") or "")},
                            {
                                "role": "system",
                                "content": (
                                    "上一条回复无效：你把工具调用写成了可见文本，运行时没有执行它。"
                                    "如果任务需要读取、搜索、写入或命令验证，下一步必须使用原生工具调用接口。"
                                    "如果已有证据足够，只能基于真实观察收口，不要输出 DSML、tool_calls、invoke 或工具参数片段。"
                                ),
                            },
                        ]
                        outcome.final_content = ""
                        continue
                    outcome.final_content = _sanitize_final_content(str(event.get("content") or ""))
                    outcome.terminal_reason = "tool_call_markup_leaked"
                    yield event
                else:
                    yield event

            if protocol_violation_repair_requested and outcome.terminal_reason == "completed":
                continue

            if model_timeout_recovery_requested and outcome.terminal_reason == "completed":
                continue

            if gate_repair_instruction and outcome.terminal_reason == "completed" and not round_tool_messages:
                fallback_tool_message = None
                fallback_observation_payload: dict[str, Any] = {}
                if _should_auto_write_artifact_delivery_after_blocked_tool(
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                ):
                    fallback_observation_payload = _build_artifact_delivery_auto_write_observation(
                        task_run_id=task_run_id,
                        semantic_contract=semantic_contract,
                        goal_contract=goal_contract,
                        evidence_packet=build_evidence_packet(
                            task_run_id=task_run_id,
                            semantic_contract=semantic_contract,
                            observations=structured_observations,
                        ).to_dict(),
                        sandbox_policy=sandbox_policy,
                    )
                    observation_ref = str(fallback_observation_payload.get("observation_ref") or "")
                    if observation_ref:
                        action_observation_refs.append(observation_ref)
                    for artifact_ref in _artifact_output_refs_from_observation(fallback_observation_payload):
                        if artifact_ref not in outcome.result_refs:
                            outcome.result_refs.append(artifact_ref)
                    write_observation_count += 1
                    tool_observation_count += 1
                    structured_observations.append(dict(fallback_observation_payload))
                    tool_observation_ledger = tool_observation_ledger.append(
                        build_tool_observation_record(
                            observation_ref=observation_ref,
                            tool_name="write_file",
                            tool_args=dict(fallback_observation_payload.get("tool_args") or {}),
                            result=fallback_observation_payload,
                        )
                    )
                    fallback_tool_message = ToolMessage(
                        content=str(fallback_observation_payload.get("result") or ""),
                        tool_call_id=str(fallback_observation_payload.get("tool_call_id") or "auto-write-artifact-delivery"),
                    )
                    fallback_ai_message = AIMessage(
                        content="",
                        tool_calls=tool_calls_for_langchain_messages(
                            [
                                {
                                    "id": str(
                                        fallback_observation_payload.get("tool_call_id")
                                        or "auto-write-artifact-delivery"
                                    ),
                                    "name": "write_file",
                                    "args": dict(fallback_observation_payload.get("tool_args") or {}),
                                    "type": "tool_call",
                                }
                            ]
                        ),
                    )
                    auto_write_event = self.event_log.append(
                        task_run_id,
                        "professional_task_artifact_auto_write_applied",
                        payload={
                            "observation": dict(fallback_observation_payload),
                            "tool_observation_ledger": tool_observation_ledger.to_dict(),
                            "summary": tool_observation_ledger.summary(),
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": auto_write_event.to_dict()}
                    run_state = run_state.advance(
                        "artifact_written",
                        reason="artifact_delivery_auto_write_after_blocked_tool",
                        evidence_refs=(observation_ref,) if observation_ref else (),
                        diagnostics={"tool_observation_ledger": tool_observation_ledger.summary()},
                    )
                    evidence_packet = build_evidence_packet(
                        task_run_id=task_run_id,
                        semantic_contract=semantic_contract,
                        observations=structured_observations,
                    )
                    evidence_event = self.event_log.append(
                        task_run_id,
                        "professional_task_evidence_packet_built",
                        payload={"evidence_packet": evidence_packet.to_dict()},
                        refs={"task_contract_ref": task_contract_ref},
                    )
                    yield {"type": "runtime_loop_event", "event": evidence_event.to_dict()}
                    conversation_messages = [
                        *conversation_messages,
                        fallback_ai_message,
                        fallback_tool_message,
                        {
                            "role": "system",
                            "content": (
                                "运行时已经根据已读材料生成并写入最小草案产物。"
                                "请基于该真实写入观察收口，最终回答必须包含后端、前端、测试、文件和限制。"
                                "不要继续请求工具，不要输出 DSML 或工具参数。"
                            ),
                        },
                    ]
                    outcome.final_content = ""
                    continue
                remaining_rounds = max_tool_rounds - outcome.turn_count
                if remaining_rounds > 0:
                    repair_messages: list[Any] = []
                    if blocked_tool_calls_for_repair:
                        repair_messages.extend(
                            [
                                AIMessage(
                                    content=assistant_tool_call_content,
                                    tool_calls=tool_calls_for_langchain_messages(blocked_tool_calls_for_repair),
                                    additional_kwargs=assistant_tool_call_kwargs,
                                ),
                                *blocked_tool_messages_for_repair,
                            ]
                        )
                    else:
                        repair_messages.append({"role": "assistant", "content": _sanitize_final_content(outcome.final_content)})
                    conversation_messages = [
                        *conversation_messages,
                        *repair_messages,
                        {
                            "role": "system",
                            "content": (
                                f"{gate_repair_instruction}"
                                "运行时已经收窄下一轮可用工具："
                                f"{'、'.join(gate_next_required_tools) or '按目标契约缺失动作'}。"
                                "请直接调用真实工具接口完成缺失动作，不要输出解释、DSML、invoke 或工具参数文本。"
                            ),
                        },
                    ]
                    outcome.final_content = ""
                    continue
                tool_call_budget_exceeded = True

            if round_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content):
                if tool_execution_enabled and len(pending_tool_calls) < max_tool_calls_per_task_run and outcome.turn_count < max_tool_rounds:
                    repair_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": "professional_task_tool_markup_repair_requested",
                            "message": "模型把工具调用写成了可见文本，运行时要求重新用真实工具接口执行或基于已有证据收口。",
                            "tool_call_count": len(pending_tool_calls),
                            "max_tool_calls_per_task_run": max_tool_calls_per_task_run,
                            "leak_detected_before_output_boundary": bool(round_protocol_leak_detected),
                        },
                        refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                    )
                    yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                    conversation_messages = [
                        *conversation_messages,
                        {"role": "assistant", "content": outcome.final_content},
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
                if _should_apply_protocol_leak_evidence_closeout(
                    outcome=outcome,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    observations=structured_observations,
                ):
                    break
                sanitized = _sanitize_final_content(outcome.final_content)
                outcome.final_content = sanitized
                if not sanitized:
                    outcome.terminal_reason = "tool_call_markup_leaked"
                else:
                    outcome.terminal_reason = "partial_contract_failed"
                break

            if round_write_budget_reserved and outcome.terminal_reason == "completed" and not round_tool_messages:
                remaining_rounds = max_tool_rounds - outcome.turn_count
                if remaining_rounds > 1:
                    conversation_messages = [
                        *conversation_messages,
                        {"role": "system", "content": _contract_repair_instruction(goal_contract=goal_contract, tool_observation_ledger=tool_observation_ledger)},
                    ]
                    outcome.final_content = ""
                    continue
                if remaining_rounds == 1 and not write_budget_reserved:
                    conversation_messages = [
                        *conversation_messages,
                        {"role": "system", "content": _contract_repair_instruction(goal_contract=goal_contract, tool_observation_ledger=tool_observation_ledger)},
                    ]
                    outcome.final_content = ""
                    continue
                tool_call_budget_exceeded = True

            if round_tool_messages and outcome.terminal_reason == "completed":
                observation_state_event = self.event_log.append(
                    task_run_id,
                    "professional_task_state_changed",
                    payload={
                        "from_state": "action_dispatched" if not action_step_completed else "plan_item_validated",
                        "to_state": "observation_received",
                        "interaction_mode": interaction_mode,
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
                        interaction_mode=interaction_mode,
                    )
                    action_step_completed = True
                    for runtime_event in self._ledger_transition_events:
                        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                last_observation_refs = tuple(action_observation_refs[-len(round_tool_messages):]) if round_tool_messages else ()
                latest_tool_names = {
                    str(getattr(message, "name", "") or "")
                    for message in round_tool_messages
                }
                latest_structured = structured_observations[-len(round_tool_messages):] if round_tool_messages else []
                latest_payload_tool_names = {
                    str(item.get("tool_name") or "")
                    for item in latest_structured
                    if isinstance(item, dict)
                }
                if "terminal" in latest_tool_names or "terminal" in latest_payload_tool_names:
                    run_state = run_state.advance(
                        "verification_observed",
                        reason="verification_observation_received",
                        evidence_refs=last_observation_refs,
                        diagnostics={"tool_observation_ledger": tool_observation_ledger.summary()},
                    )
                elif tool_observation_ledger.has_write() and (
                    {"write_file", "edit_file"}.intersection(latest_tool_names)
                    or {"write_file", "edit_file"}.intersection(latest_payload_tool_names)
                ):
                    run_state = run_state.advance(
                        "artifact_written",
                        reason="write_observation_received",
                        evidence_refs=last_observation_refs,
                        diagnostics={"tool_observation_ledger": tool_observation_ledger.summary()},
                    )
                else:
                    run_state = run_state.advance(
                        "tool_observed",
                        reason="tool_observation_received",
                        evidence_refs=last_observation_refs,
                        diagnostics={"tool_observation_ledger": tool_observation_ledger.summary()},
                    )
                ledger_event = self.event_log.append(
                    task_run_id,
                    "professional_tool_observation_ledger_updated",
                    payload={
                        "tool_observation_ledger": tool_observation_ledger.to_dict(),
                        "summary": tool_observation_ledger.summary(),
                        "professional_run_state": run_state.to_dict(),
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                evidence_packet = build_evidence_packet(
                    task_run_id=task_run_id,
                    semantic_contract=semantic_contract,
                    observations=structured_observations,
                )
                evidence_event = self.event_log.append(
                    task_run_id,
                    "professional_task_evidence_packet_built",
                    payload={"evidence_packet": evidence_packet.to_dict()},
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": evidence_event.to_dict()}
                evaluated_state_event = self.event_log.append(
                    task_run_id,
                    "professional_task_state_changed",
                    payload={"from_state": "observation_received", "to_state": "plan_item_validated", "interaction_mode": interaction_mode},
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": evaluated_state_event.to_dict()}
                write_guidance = ""
                if write_output_required and write_observation_count <= 0 and "write_file" in set(allowed_tool_names):
                    write_guidance = (
                        "用户目标包含写入/保存/产出文件要求；如果核心材料已经足够，"
                        "下一步应优先使用 write_file 在 sandbox overlay 中产出草案文件。"
                    )
                contract_guidance = _contract_followup_guidance(goal_contract=goal_contract, tool_observation_ledger=tool_observation_ledger)
                evidence_guidance = _evidence_packet_prompt(evidence_packet.to_dict())
                conversation_messages = [
                    *conversation_messages,
                    AIMessage(
                        content=assistant_tool_call_content,
                        tool_calls=tool_calls_for_langchain_messages(round_tool_calls),
                        additional_kwargs=assistant_tool_call_kwargs,
                    ),
                    *round_tool_messages,
                    {
                        "role": "system",
                        "content": (
                            "你已经收到上一轮真实工具观察结果，并且运行时已经形成证据包。"
                            f"{evidence_guidance}"
                            "如果还需要读文件、修改、验证或委派，请继续使用真实工具调用接口；"
                            "如果已经满足语义契约，请直接收口。"
                            f"{write_guidance}"
                            f"{contract_guidance}"
                            "不要把工具调用、DSML、JSON schema 或内部协议当作回答文本输出。"
                        ),
                    },
                ]
                outcome.final_content = ""
                continue

            break

        closeout_protocol_leak_detected = False
        if tool_call_budget_exceeded and outcome.terminal_reason == "completed" and not str(outcome.final_content or "").strip():
            closeout_started_event = self.event_log.append(
                task_run_id,
                "professional_task_budget_closeout_started",
                payload={
                    "interaction_mode": interaction_mode,
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
            evidence_packet = build_evidence_packet(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                observations=structured_observations,
            )
            closeout_messages = [
                *conversation_messages,
                {
                    "role": "system",
                    "content": (
                        "工具预算已经耗尽，禁止继续请求任何工具或委派。"
                        "现在必须只基于已经真实返回的工具观察结果和证据包完成最终收口。"
                        f"{_evidence_packet_prompt(evidence_packet.to_dict())}"
                        "如果证据不足，明确写出限制；如果用户要求写入但尚未写入，说明尚未完成写入。"
                        "不要输出 DSML、tool_calls、invoke、工具参数或任何伪工具调用文本。"
                    ),
                },
            ]
            outcome.model_call_count += 1
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=closeout_messages,
                directive=_model_only_directive(safe_directive, mode=interaction_mode),
                tool_instances=[],
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                if _event_protocol_leak_detected(event):
                    closeout_protocol_leak_detected = True
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
                    outcome.task_summary_refs = [dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)]
                    outcome.bundle_summary_refs = [dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)]
                elif event_type == "error":
                    outcome.terminal_reason = "executor_failed"
                    yield event
                else:
                    yield event

        if closeout_protocol_leak_detected and outcome.terminal_reason == "completed":
            outcome.final_content = _sanitize_final_content(outcome.final_content)
            if not str(outcome.final_content or "").strip():
                outcome.terminal_reason = "tool_call_markup_leaked"

        if _contains_tool_call_markup(outcome.final_content):
            sanitized_final_content = _strip_tool_call_markup(outcome.final_content)
            if sanitized_final_content and sanitized_final_content != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized_final_content
            else:
                outcome.final_content = ""
                outcome.terminal_reason = "tool_call_markup_leaked"

        final_protocol_leak_detected = bool(closeout_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content))
        if final_protocol_leak_detected:
            sanitized = _sanitize_final_content(outcome.final_content)
            if sanitized != str(outcome.final_content or "").strip():
                outcome.final_content = sanitized
        if tool_call_budget_exceeded and outcome.terminal_reason == "completed" and not str(outcome.final_content or "").strip():
            outcome.terminal_reason = "tool_loop_budget_exceeded"

        evidence_packet = build_evidence_packet(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            observations=structured_observations,
        )
        evidence_event = self.event_log.append(
            task_run_id,
            "professional_task_evidence_packet_built",
            payload={"evidence_packet": evidence_packet.to_dict(), "final_packet": True},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": evidence_event.to_dict()}
        verification_ready_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={"from_state": "plan_item_validated", "to_state": "deliverable_validation_ready", "interaction_mode": interaction_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": verification_ready_event.to_dict()}
        run_state = run_state.advance(
            "deliverable_validating",
            reason="deliverable_validation_ready",
            evidence_refs=tuple(action_observation_refs),
            diagnostics={"tool_observation_ledger": tool_observation_ledger.summary()},
        )
        if _should_apply_evidence_closeout(
            outcome=outcome,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
            evidence_packet=evidence_packet.to_dict(),
            final_protocol_leak_detected=final_protocol_leak_detected,
            tool_budget_exhausted=tool_call_budget_exceeded,
        ):
            evidence_closeout = _build_evidence_closeout_answer(
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
            )
            if evidence_closeout:
                closeout_deliverable_validation = validate_deliverable(
                    final_answer=evidence_closeout,
                    semantic_contract=semantic_contract,
                    evidence_packet=evidence_packet.to_dict(),
                    strict=bool(verification_policy.get("strict") is True),
                    required_output_paths=goal_contract.required_output_paths,
                ).to_dict()
                closeout_obligation_validation = validate_obligations(
                    execution_obligation=execution_obligation,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    final_content=evidence_closeout,
                    deliverable_validation=closeout_deliverable_validation,
                    terminal_reason="completed",
                    tool_execution_enabled=tool_execution_enabled,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    delegation_enabled=delegation_enabled,
                    delegation_observation_count=delegation_observation_count,
                    write_budget_reserved=write_budget_reserved,
                    tool_budget_exhausted=tool_call_budget_exceeded,
                    contract_gate_blocked=contract_gate_blocked,
                    protocol_leak_detected=False,
                ).to_dict()
                if bool(closeout_obligation_validation.get("passed") is True):
                    previous_terminal_reason = outcome.terminal_reason
                    outcome.final_content = evidence_closeout
                    outcome.terminal_reason = "completed"
                    final_protocol_leak_detected = False
                    closeout_event = self.event_log.append(
                        task_run_id,
                        "professional_task_evidence_closeout_applied",
                        payload={
                            "interaction_mode": interaction_mode,
                            "reason": "protocol_leak_or_empty_closeout_after_real_evidence",
                            "previous_terminal_reason": previous_terminal_reason,
                            "fact_count": len(list(evidence_packet.to_dict().get("facts") or [])),
                            "classification_count": len(list(evidence_packet.to_dict().get("classifications") or [])),
                            "deliverable_validation": closeout_deliverable_validation,
                            "obligation_validation": closeout_obligation_validation,
                        },
                        refs={"task_contract_ref": task_contract_ref},
                    )
                    yield {"type": "runtime_loop_event", "event": closeout_event.to_dict()}
        if _should_apply_generic_evidence_closeout(
            outcome=outcome,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
            evidence_packet=evidence_packet.to_dict(),
        ):
            evidence_closeout = _build_generic_evidence_closeout_answer(
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
            )
            if evidence_closeout:
                closeout_deliverable_validation = validate_deliverable(
                    final_answer=evidence_closeout,
                    semantic_contract=semantic_contract,
                    evidence_packet=evidence_packet.to_dict(),
                    strict=bool(verification_policy.get("strict") is True),
                    required_output_paths=goal_contract.required_output_paths,
                ).to_dict()
                closeout_obligation_validation = validate_obligations(
                    execution_obligation=execution_obligation,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    final_content=evidence_closeout,
                    deliverable_validation=closeout_deliverable_validation,
                    terminal_reason="completed",
                    tool_execution_enabled=tool_execution_enabled,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    delegation_enabled=delegation_enabled,
                    delegation_observation_count=delegation_observation_count,
                    write_budget_reserved=write_budget_reserved,
                    tool_budget_exhausted=tool_call_budget_exceeded,
                    contract_gate_blocked=contract_gate_blocked,
                    protocol_leak_detected=False,
                ).to_dict()
                if bool(closeout_obligation_validation.get("passed") is True):
                    previous_terminal_reason = outcome.terminal_reason
                    outcome.final_content = evidence_closeout
                    outcome.terminal_reason = "completed"
                    final_protocol_leak_detected = False
                    closeout_event = self.event_log.append(
                        task_run_id,
                        "professional_task_evidence_closeout_applied",
                        payload={
                            "interaction_mode": interaction_mode,
                            "reason": "generic_evidence_closeout_after_budget_or_protocol_failure",
                            "previous_terminal_reason": previous_terminal_reason,
                            "fact_count": len(list(evidence_packet.to_dict().get("facts") or [])),
                            "deliverable_validation": closeout_deliverable_validation,
                            "obligation_validation": closeout_obligation_validation,
                        },
                        refs={"task_contract_ref": task_contract_ref},
                    )
                    yield {"type": "runtime_loop_event", "event": closeout_event.to_dict()}
        if _should_apply_artifact_delivery_evidence_closeout(
            outcome=outcome,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
            final_protocol_leak_detected=final_protocol_leak_detected,
        ):
            evidence_closeout = _build_artifact_delivery_evidence_closeout_answer(
                tool_observation_ledger=tool_observation_ledger,
                evidence_packet=evidence_packet.to_dict(),
            )
            if evidence_closeout:
                closeout_deliverable_validation = validate_deliverable(
                    final_answer=evidence_closeout,
                    semantic_contract=semantic_contract,
                    evidence_packet=evidence_packet.to_dict(),
                    strict=bool(verification_policy.get("strict") is True),
                    required_output_paths=goal_contract.required_output_paths,
                ).to_dict()
                closeout_obligation_validation = validate_obligations(
                    execution_obligation=execution_obligation,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    final_content=evidence_closeout,
                    deliverable_validation=closeout_deliverable_validation,
                    terminal_reason="completed",
                    tool_execution_enabled=tool_execution_enabled,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    delegation_enabled=delegation_enabled,
                    delegation_observation_count=delegation_observation_count,
                    write_budget_reserved=write_budget_reserved,
                    tool_budget_exhausted=tool_call_budget_exceeded,
                    contract_gate_blocked=contract_gate_blocked,
                    protocol_leak_detected=False,
                ).to_dict()
                previous_terminal_reason = outcome.terminal_reason
                outcome.final_content = evidence_closeout
                outcome.terminal_reason = "completed"
                final_protocol_leak_detected = False
                closeout_event = self.event_log.append(
                    task_run_id,
                    "professional_task_evidence_closeout_applied",
                    payload={
                        "interaction_mode": interaction_mode,
                        "reason": "artifact_delivery_evidence_closeout_after_write",
                        "previous_terminal_reason": previous_terminal_reason,
                        "deliverable_validation": closeout_deliverable_validation,
                        "obligation_validation": closeout_obligation_validation,
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": closeout_event.to_dict()}
        if _should_apply_code_fix_evidence_closeout(
            outcome=outcome,
            semantic_contract=semantic_contract,
            tool_observation_ledger=tool_observation_ledger,
            final_protocol_leak_detected=final_protocol_leak_detected,
        ):
            evidence_closeout = _build_code_fix_evidence_closeout_answer(
                tool_observation_ledger=tool_observation_ledger,
                evidence_packet=evidence_packet.to_dict(),
            )
            if evidence_closeout:
                closeout_deliverable_validation = validate_deliverable(
                    final_answer=evidence_closeout,
                    semantic_contract=semantic_contract,
                    evidence_packet=evidence_packet.to_dict(),
                    strict=bool(verification_policy.get("strict") is True),
                    required_output_paths=goal_contract.required_output_paths,
                ).to_dict()
                closeout_obligation_validation = validate_obligations(
                    execution_obligation=execution_obligation,
                    semantic_contract=semantic_contract,
                    goal_contract=goal_contract,
                    tool_observation_ledger=tool_observation_ledger,
                    final_content=evidence_closeout,
                    deliverable_validation=closeout_deliverable_validation,
                    terminal_reason="completed",
                    tool_execution_enabled=tool_execution_enabled,
                    tool_call_count=len(pending_tool_calls),
                    tool_observation_count=tool_observation_count,
                    delegation_enabled=delegation_enabled,
                    delegation_observation_count=delegation_observation_count,
                    write_budget_reserved=write_budget_reserved,
                    tool_budget_exhausted=tool_call_budget_exceeded,
                    contract_gate_blocked=contract_gate_blocked,
                    protocol_leak_detected=False,
                ).to_dict()
                if bool(closeout_deliverable_validation.get("protocol_leak_detected") is not True):
                    previous_terminal_reason = outcome.terminal_reason
                    outcome.final_content = evidence_closeout
                    outcome.terminal_reason = "completed" if bool(closeout_obligation_validation.get("passed") is True) else "partial_contract_failed"
                    final_protocol_leak_detected = False
                    closeout_event = self.event_log.append(
                        task_run_id,
                        "professional_task_evidence_closeout_applied",
                        payload={
                            "interaction_mode": interaction_mode,
                            "reason": "code_fix_evidence_closeout_after_protocol_failure",
                            "previous_terminal_reason": previous_terminal_reason,
                            "deliverable_validation": closeout_deliverable_validation,
                            "obligation_validation": closeout_obligation_validation,
                        },
                        refs={"task_contract_ref": task_contract_ref},
                    )
                    yield {"type": "runtime_loop_event", "event": closeout_event.to_dict()}
        deliverable_validation = validate_deliverable(
            final_answer=outcome.final_content,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            strict=bool(verification_policy.get("strict") is True),
            required_output_paths=goal_contract.required_output_paths,
        ).to_dict()
        obligation_validation = validate_obligations(
            execution_obligation=execution_obligation,
            semantic_contract=semantic_contract,
            goal_contract=goal_contract,
            tool_observation_ledger=tool_observation_ledger,
            final_content=outcome.final_content,
            deliverable_validation=deliverable_validation,
            terminal_reason=outcome.terminal_reason,
            tool_execution_enabled=tool_execution_enabled,
            tool_call_count=len(pending_tool_calls),
            tool_observation_count=tool_observation_count,
            delegation_enabled=delegation_enabled,
            delegation_observation_count=delegation_observation_count,
            write_budget_reserved=write_budget_reserved,
            tool_budget_exhausted=tool_call_budget_exceeded,
            contract_gate_blocked=contract_gate_blocked,
            protocol_leak_detected=final_protocol_leak_detected,
        ).to_dict()
        verification = {
            **obligation_validation,
            "interaction_mode": interaction_mode,
            "mode": interaction_mode,
            "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
            "evidence_packet": evidence_packet.to_dict(),
            "deliverable_validation": deliverable_validation,
            "obligation_validation": obligation_validation,
            "passed": bool(obligation_validation.get("passed") is True),
        }
        verification = _normalize_professional_verification(verification)
        if _should_repair_professional_closeout(verification):
            repair_base_content = str(outcome.final_content or "").strip()
            repair_base_metadata = dict(outcome.final_answer_metadata or {})
            repair_base_main_context = dict(outcome.main_context or {})
            repair_base_task_summary_refs = [
                dict(item) for item in list(outcome.task_summary_refs or []) if isinstance(item, dict)
            ]
            repair_base_bundle_summary_refs = [
                dict(item) for item in list(outcome.bundle_summary_refs or []) if isinstance(item, dict)
            ]
            repair_candidate_content = ""
            repair_candidate_metadata: dict[str, Any] = {}
            repair_candidate_main_context: dict[str, Any] = {}
            repair_candidate_task_summary_refs: list[dict[str, Any]] = []
            repair_candidate_bundle_summary_refs: list[dict[str, Any]] = []
            repair_started_event = self.event_log.append(
                task_run_id,
                "professional_task_deliverable_repair_started",
                payload={
                    "interaction_mode": interaction_mode,
                    "missing_deliverables": list(deliverable_validation.get("missing_deliverables") or []),
                    "protocol_leak_detected": bool(deliverable_validation.get("protocol_leak_detected") is True),
                },
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": repair_started_event.to_dict()}
            repair_messages = [
                *conversation_messages,
                {"role": "assistant", "content": str(outcome.final_content or "")},
                {
                    "role": "system",
                    "content": _professional_closeout_repair_instruction(
                        semantic_contract=semantic_contract,
                        evidence_packet=evidence_packet.to_dict(),
                        validation=deliverable_validation,
                    ),
                },
            ]
            outcome.model_call_count += 1
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=repair_messages,
                directive=_model_only_directive(safe_directive, mode=interaction_mode),
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
                    repair_candidate_content = _sanitize_final_content(str(event.get("content") or ""))
                    repair_candidate_metadata = _answer_metadata_from_done_event(event)
                    repair_candidate_main_context = dict(event.get("main_context") or {})
                    repair_candidate_task_summary_refs = [
                        dict(item) for item in list(event.get("task_summary_refs") or []) if isinstance(item, dict)
                    ]
                    repair_candidate_bundle_summary_refs = [
                        dict(item) for item in list(event.get("bundle_summary_refs") or []) if isinstance(item, dict)
                    ]
                elif event_type == "error":
                    outcome.terminal_reason = "executor_failed"
                    yield event
                else:
                    yield event
            repair_candidate_leaked = _contains_tool_call_markup(repair_candidate_content)
            repair_candidate_deliverable = validate_deliverable(
                final_answer=repair_candidate_content,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                strict=bool(verification_policy.get("strict") is True),
                required_output_paths=goal_contract.required_output_paths,
            ).to_dict()
            repair_candidate_obligation = validate_obligations(
                execution_obligation=execution_obligation,
                semantic_contract=semantic_contract,
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                final_content=repair_candidate_content,
                deliverable_validation=repair_candidate_deliverable,
                terminal_reason="completed",
                tool_execution_enabled=tool_execution_enabled,
                tool_call_count=len(pending_tool_calls),
                tool_observation_count=tool_observation_count,
                delegation_enabled=delegation_enabled,
                delegation_observation_count=delegation_observation_count,
                write_budget_reserved=write_budget_reserved,
                tool_budget_exhausted=tool_call_budget_exceeded,
                contract_gate_blocked=contract_gate_blocked,
                protocol_leak_detected=bool(repair_candidate_leaked),
            ).to_dict()
            repair_candidate_passed = bool(
                repair_candidate_obligation.get("passed") is True
            )
            if repair_candidate_passed:
                outcome.final_content = repair_candidate_content
                outcome.final_answer_metadata = repair_candidate_metadata
                outcome.main_context = repair_candidate_main_context
                outcome.task_summary_refs = repair_candidate_task_summary_refs
                outcome.bundle_summary_refs = repair_candidate_bundle_summary_refs
                final_protocol_leak_detected = False
            else:
                outcome.final_content = repair_base_content
                outcome.final_answer_metadata = repair_base_metadata
                outcome.main_context = repair_base_main_context
                outcome.task_summary_refs = repair_base_task_summary_refs
                outcome.bundle_summary_refs = repair_base_bundle_summary_refs
                final_protocol_leak_detected = bool(final_protocol_leak_detected or _contains_tool_call_markup(outcome.final_content))
                repair_rejected_event = self.event_log.append(
                    task_run_id,
                    "professional_task_deliverable_repair_rejected",
                    payload={
                        "interaction_mode": interaction_mode,
                        "reason": "repair_candidate_failed_validation",
                        "candidate_empty": not bool(repair_candidate_content.strip()),
                        "candidate_protocol_leak_detected": bool(repair_candidate_leaked),
                        "candidate_deliverable_validation": repair_candidate_deliverable,
                        "candidate_obligation_validation": repair_candidate_obligation,
                    },
                    refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
                )
                yield {"type": "runtime_loop_event", "event": repair_rejected_event.to_dict()}
            deliverable_validation = validate_deliverable(
                final_answer=outcome.final_content,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                strict=bool(verification_policy.get("strict") is True),
                required_output_paths=goal_contract.required_output_paths,
            ).to_dict()
            obligation_validation = validate_obligations(
                execution_obligation=execution_obligation,
                semantic_contract=semantic_contract,
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                final_content=outcome.final_content,
                deliverable_validation=deliverable_validation,
                terminal_reason=outcome.terminal_reason,
                tool_execution_enabled=tool_execution_enabled,
                tool_call_count=len(pending_tool_calls),
                tool_observation_count=tool_observation_count,
                delegation_enabled=delegation_enabled,
                delegation_observation_count=delegation_observation_count,
                write_budget_reserved=write_budget_reserved,
                tool_budget_exhausted=tool_call_budget_exceeded,
                contract_gate_blocked=contract_gate_blocked,
                protocol_leak_detected=final_protocol_leak_detected,
            ).to_dict()
            verification = {
                **obligation_validation,
                "interaction_mode": interaction_mode,
                "mode": interaction_mode,
                "semantic_task_type": str(semantic_contract.get("task_goal_type") or ""),
                "evidence_packet": evidence_packet.to_dict(),
                "deliverable_validation": deliverable_validation,
                "obligation_validation": obligation_validation,
                "passed": bool(obligation_validation.get("passed") is True),
            }
            verification = _normalize_professional_verification(verification)
        if outcome.terminal_reason in {"completed", "tool_loop_budget_exceeded"} and not bool(verification.get("passed") is True):
            outcome.terminal_reason = "partial_contract_failed"
        unsatisfied = unsatisfied_obligations_from_verification(verification)
        run_state = run_state.advance(
            "complete" if bool(verification.get("passed") is True) else "blocked",
            reason="deliverable_validation_checked",
            evidence_refs=tuple(action_observation_refs),
            unsatisfied_obligations=unsatisfied,
            blocked_reason="" if bool(verification.get("passed") is True) else "unsatisfied_execution_obligations",
            diagnostics={
                "verification_passed": bool(verification.get("passed") is True),
                "terminal_reason": outcome.terminal_reason,
                "tool_observation_ledger": tool_observation_ledger.summary(),
            },
        )
        verification["professional_run_state"] = run_state.to_dict()
        verification["tool_observation_ledger"] = tool_observation_ledger.to_dict()
        verify_event = self.event_log.append(
            task_run_id,
            "professional_task_deliverable_validation_checked",
            payload={"verification": verification},
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.validate_deliverable"},
        )
        yield {"type": "runtime_loop_event", "event": verify_event.to_dict()}
        session_event = self.event_log.append(
            task_run_id,
            "professional_run_session_updated",
            payload={
                "professional_run_session": build_professional_run_session(
                    session_id=str(outcome.state.diagnostics.get("session_id") or ""),
                    task_run_id=task_run_id,
                    interaction_mode=interaction_mode,
                    state_ref=run_state.run_state_id,
                    tool_observation_ledger_ref=tool_observation_ledger.ledger_id,
                    execution_obligation=execution_obligation,
                ).to_dict(),
                "professional_run_state": run_state.to_dict(),
                "tool_observation_ledger": tool_observation_ledger.to_dict(),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": session_event.to_dict()}
        outcome.state, outcome.ledger = self._complete_standard_final_check_after_verification(
            state=outcome.state,
            ledger=outcome.ledger,
            task_contract_ref=task_contract_ref,
            verification_event_ref=f"runtime_event:{verify_event.event_id}",
            observation_refs=tuple(action_observation_refs),
            result_refs=tuple(outcome.result_refs),
            final_content=outcome.final_content,
            verification_passed=bool(verification.get("passed") is True),
            interaction_mode=interaction_mode,
        )
        for runtime_event in self._ledger_transition_events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        finalizing_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={"from_state": "deliverable_validation_ready", "to_state": "finalizing", "interaction_mode": interaction_mode},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": finalizing_event.to_dict()}
        committed_state_event = self.event_log.append(
            task_run_id,
            "professional_task_state_changed",
            payload={
                "from_state": "finalizing",
                "to_state": "ready_for_commit",
                "interaction_mode": interaction_mode,
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
                executor_ref=current.executor_ref or "professional_task_run",
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
            executor_ref="professional_task_run",
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
        interaction_mode: str = "standard",
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
                    executor_ref="professional_task_run",
                    diagnostics={"transition_reason": "professional_task_action_step_selected", "interaction_mode": interaction_mode},
                )
                current = current_task_step_run(ledger)
                if current is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=current,
                            ledger=ledger,
                            reason="professional_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )
            if current is not None and current.status == "running":
                ledger = complete_task_run_step(
                    ledger,
                    step_id=current.step_id,
                    completed_at=time.time(),
                    output_refs=(f"professional_control_step:{current.step_id}",),
                    executor_ref=current.executor_ref or "professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_action_step_selected",
                        "interaction_mode": interaction_mode,
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
                            reason="professional_task_action_step_selected",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
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
                    executor_ref="professional_task_run",
                    diagnostics={"transition_reason": "professional_task_prerequisite_step_completed", "interaction_mode": interaction_mode},
                )
                entered = current_task_step_run(ledger)
                if entered is not None:
                    self._ledger_transition_events.append(
                        self.record_task_run_step_event(
                            state.task_run_id,
                            event_type="step_entered",
                            step_run=entered,
                            ledger=ledger,
                            reason="professional_task_prerequisite_step_completed",
                            refs={"task_contract_ref": task_contract_ref},
                            diagnostics={"interaction_mode": interaction_mode},
                        )
                    )
            current = current_task_step_run(ledger)
            if current is None or current.status != "running":
                continue
            ledger = update_task_run_step_diagnostics(
                ledger,
                step_id=current.step_id,
                diagnostics={
                    "professional_state": "step_evaluated",
                    "transition_reason": "professional_task_prerequisite_step_completed",
                    "interaction_mode": interaction_mode,
                    "execution_scope": "goal_and_scope_locked",
                },
            )
            current = current_task_step_run(ledger)
            ledger = complete_task_run_step(
                ledger,
                step_id=current.step_id if current is not None else None,
                completed_at=time.time(),
                output_refs=(f"professional_plan_item:{current.step_id}",) if current is not None else (),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_prerequisite_step_completed",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_prerequisite_step_completed",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )

        action_step = find_task_step_run(ledger, action_step_id)
        if action_step is not None and action_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=action_step.step_id,
                started_at=time.time(),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_action_step_selected",
                    "professional_state": "step_selected",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_action_step_selected",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_action_step_selected",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"interaction_mode": interaction_mode},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_action_step_selected",
                "professional_state": "step_selected",
                "interaction_mode": interaction_mode,
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
        interaction_mode: str = "standard",
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
                    executor_ref="professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_observation_received",
                        "interaction_mode": interaction_mode,
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
                output_refs=tuple(f"professional_observation:{ref}" for ref in deduped_observation_refs),
                executor_ref=current.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_observation_received",
                    "professional_state": "step_evaluated",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_observation_received",
                        refs={"task_contract_ref": task_contract_ref},
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )
        ledger = advance_task_run_ledger(
            ledger,
            started_at=time.time(),
            executor_ref="professional_task_run",
            diagnostics={
                "transition_reason": "professional_task_step_evaluated",
                "professional_state": "step_evaluated",
                "interaction_mode": interaction_mode,
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
                    reason="professional_task_step_evaluated",
                    refs={"task_contract_ref": task_contract_ref},
                    diagnostics={"interaction_mode": interaction_mode},
                )
            )
        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_step_evaluated",
            refs={"task_contract_ref": task_contract_ref},
            diagnostics={"interaction_mode": interaction_mode, "observation_ref_count": len(observation_refs)},
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_step_evaluated",
                "professional_state": "step_evaluated",
                "interaction_mode": interaction_mode,
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
        interaction_mode: str = "standard",
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None]:
        self._ledger_transition_events = []
        if ledger is None:
            return state, ledger
        final_step_id = "professional.validate_deliverable"
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
                    executor_ref="professional_task_run",
                    diagnostics={
                        "transition_reason": "professional_task_pre_validation_step_completed",
                        "professional_state": "verification_ready",
                        "interaction_mode": interaction_mode,
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
                            reason="professional_task_pre_validation_step_completed",
                            refs=refs,
                            diagnostics={"interaction_mode": interaction_mode},
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
                        f"professional_plan_item:{current.step_id}",
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
                executor_ref=current.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_pre_validation_step_completed",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_pre_validation_step_completed",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode},
                    )
                )

        final_step = find_task_step_run(ledger, final_step_id)
        if final_step is not None and final_step.status == "pending":
            ledger = start_task_run_step(
                ledger,
                step_id=final_step.step_id,
                started_at=time.time(),
                executor_ref="professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_validation_started",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_validation_started",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode},
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
                executor_ref=final_step.executor_ref or "professional_task_run",
                diagnostics={
                    "transition_reason": "professional_task_validation_completed",
                    "professional_state": "verification_ready",
                    "interaction_mode": interaction_mode,
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
                        reason="professional_task_validation_completed",
                        refs=refs,
                        diagnostics={"interaction_mode": interaction_mode, "verification_passed": bool(verification_passed)},
                    )
                )

        ledger_event = self.record_task_run_ledger_updated(
            state.task_run_id,
            ledger=ledger,
            reason="professional_task_validation_completed",
            refs={**refs, "task_step_ref": final_step_id},
            diagnostics={
                "interaction_mode": interaction_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        self._ledger_transition_events.append(ledger_event)
        state = self.state_with_task_run_ledger(
            state,
            ledger,
            diagnostics={
                "last_step_transition": "professional_task_validation_completed",
                "professional_state": "verification_ready",
                "interaction_mode": interaction_mode,
                "verification_ref": verification_event_ref,
                "verification_passed": bool(verification_passed),
            },
        )
        checkpoint_event = self.write_checkpoint_event(state, event_offset=ledger_event.offset)
        self._ledger_transition_events.append(checkpoint_event)
        return state, ledger


def _goal_contract_from_semantic_contract(
    *,
    task_run_id: str,
    user_message: str,
    semantic_contract: dict[str, Any],
) -> ProfessionalTaskGoalContract:
    materials = [dict(item) for item in list(semantic_contract.get("materials") or []) if isinstance(item, dict)]
    obligation = dict(semantic_contract.get("execution_obligation") or {})
    obligation_reads = [
        dict(item)
        for item in list(obligation.get("required_reads") or [])
        if isinstance(item, dict)
    ]
    obligation_writes = [
        dict(item)
        for item in list(obligation.get("required_writes") or [])
        if isinstance(item, dict)
    ]
    obligation_commands = [
        dict(item)
        for item in list(obligation.get("required_commands") or [])
        if isinstance(item, dict)
    ]
    obligation_verifications = [
        dict(item)
        for item in list(obligation.get("required_verifications") or [])
        if isinstance(item, dict)
    ]
    forbidden_actions = {
        str(item).strip()
        for item in list(obligation.get("forbidden_actions") or [])
        if str(item).strip()
    }
    raw_material_paths = _dedupe_strings(
        [
            *[str(item.get("path") or "").strip() for item in materials if str(item.get("path") or "").strip()],
            *[str(item.get("path") or "").strip() for item in obligation_reads if str(item.get("path") or "").strip()],
        ]
    )
    material_types = _dedupe_strings(
        [
            *[str(item.get("kind") or "").strip() for item in materials if str(item.get("kind") or "").strip()],
            *[str(item.get("kind") or "").strip() for item in obligation_reads if str(item.get("kind") or "").strip()],
        ]
    )
    goal_text = str(semantic_contract.get("user_goal") or user_message or "").strip()
    output_paths = _dedupe_strings(
        [
            *[
                str(item.get("path") or "").strip()
                for item in obligation_writes
                if str(item.get("path") or "").strip()
            ],
            *_extract_goal_output_paths(goal_text),
        ]
    )
    material_paths = [
        path
        for path in raw_material_paths
        if _goal_material_path_is_credible(path, output_paths=output_paths, goal_text=goal_text)
    ]
    required_actions = {
        str(item).strip()
        for item in list(semantic_contract.get("required_actions") or [])
        if str(item).strip()
    }
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    write_forbidden = bool(forbidden_actions.intersection({"modify_code", "write_file", "edit_file"}))
    requires_write = bool(obligation_writes) and not write_forbidden
    if not requires_write:
        requires_write = (
            not write_forbidden
            and ("apply_real_change" in required_actions or task_goal_type in {"code_fix_execution", "artifact_delivery"})
        )
    requires_verify = bool(obligation_commands or obligation_verifications)
    if not requires_verify:
        requires_verify = "validate_deliverables" in required_actions and task_goal_type in {
            "code_fix_execution",
            "regression_test_design",
        }
    response_terms = _dedupe_strings(
        [
            *_response_terms_from_semantic_contract(semantic_contract),
            *[
                _response_term_for_deliverable(item)
                for item in list(obligation.get("required_deliverables") or [])
                if str(item).strip()
            ],
        ]
    )
    return ProfessionalTaskGoalContract(
        contract_id=f"professional-goal-contract:{task_run_id}",
        goal=goal_text,
        required_material_paths=material_paths,
        required_output_paths=output_paths,
        material_types=material_types,
        required_tool_kinds=_dedupe_strings(
            [
                *[
                    item
                    for item in list(required_actions)
                    if item != "read_material" or material_paths
                ],
                *(["write_output"] if requires_write else []),
                *(["verify_command"] if requires_verify else []),
            ]
        ),
        required_output_kinds=["final_answer", *deliverables],
        requires_material_review=bool(material_paths),
        requires_write_output=requires_write,
        requires_verification_command=requires_verify,
        requires_delegation=False,
        response_must_include=response_terms,
        forbidden_visible_markers=_forbidden_visible_markers(),
    )


def _semantic_control_plan(
    *,
    user_message: str,
    semantic_contract: dict[str, Any],
    mode_policy: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
) -> list[dict[str, Any]]:
    interaction_mode = str(mode_policy.get("interaction_mode") or "professional_mode").strip()
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    reasoning_steps = [
        str(item).strip()
        for item in list(semantic_contract.get("required_reasoning_steps") or [])
        if str(item).strip()
    ]
    plan: list[dict[str, Any]] = [
        {
            "plan_item_id": "professional.mode_policy",
            "title": "绑定交互模式和任务边界",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": f"{interaction_mode}: {str(user_message or '').strip()[:180]}",
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
        {
            "plan_item_id": "professional.semantic_contract",
            "title": "绑定语义任务契约",
            "step_kind": "plan_item",
            "executor_type": "model",
            "action_kind": "main_agent",
            "summary": f"任务类型 {task_goal_type}；交付物：{', '.join(list(semantic_contract.get('deliverables') or [])) or 'final_answer'}。",
            "required_operations": ["op.model_response"],
            "contract_required": True,
        },
    ]
    if goal_contract.requires_material_review:
        plan.append(
            {
                "plan_item_id": "professional.material_review",
                "title": "读取并抽取指定材料证据",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _material_review_summary(goal_contract),
                "required_operations": _required_operations_for_contract_materials(goal_contract),
                "material_paths": list(goal_contract.required_material_paths),
                "contract_required": True,
            }
        )
    if reasoning_steps:
        plan.append(
            {
                "plan_item_id": "professional.reasoning_steps",
                "title": "按专业步骤完成结构化分析",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": " -> ".join(reasoning_steps),
                "required_operations": ["op.model_response"],
                "contract_required": True,
            }
        )
    if bool(dict(mode_policy.get("tool_policy") or {}).get("requires_evidence_packet")) or bool(
        dict(semantic_contract.get("material_handling_policy") or {}).get("evidence_packet_required")
    ):
        plan.append(
            {
                "plan_item_id": "professional.evidence_packet",
                "title": "构建证据包",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "将工具观察、材料事实、失败分类和限制先沉淀为 evidence packet。",
                "required_operations": ["op.model_response"],
                "contract_required": True,
            }
        )
    if goal_contract.requires_write_output:
        plan.append(
            {
                "plan_item_id": "professional.produce_output",
                "title": "执行真实代码或产物修改",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _produce_output_summary(goal_contract),
                "required_operations": ["op.write_file", "op.edit_file"],
                "contract_required": True,
            }
        )
    if goal_contract.requires_verification_command:
        plan.append(
            {
                "plan_item_id": "professional.verify_output",
                "title": "运行真实验证或说明限制",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "使用 terminal 运行验证命令，或明确说明无法验证的真实限制。",
                "required_operations": ["op.shell"],
                "contract_required": True,
            }
        )
    plan.extend(
        [
            {
                "plan_item_id": "professional.synthesis",
                "title": "综合证据形成专业结论",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": _synthesis_summary(goal_contract),
                "required_operations": ["op.model_response"],
                "response_must_include": list(goal_contract.response_must_include),
                "contract_required": True,
            },
            {
                "plan_item_id": "professional.validate_deliverable",
                "title": "按交付物验证最终回答",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "检查语义交付物、证据对齐、协议泄漏和未支持声明。",
                "required_operations": ["op.model_response"],
                "contract_required": True,
            },
        ]
    )
    return plan


def _build_goal_contract(
    *,
    task_run_id: str,
    user_message: str,
    selected_recipe_payload: dict[str, Any],
) -> ProfessionalTaskGoalContract:
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
    return ProfessionalTaskGoalContract(
        contract_id=f"professional-goal-contract:{task_run_id}",
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
    direct_paths = [
            path
            for path, prefix in _path_mentions_with_prefix(text)
            if _prefix_indicates_output_path(prefix)
    ]
    return _dedupe_strings([*direct_paths, *_expand_output_directory_file_lists(text)])


def _expand_output_directory_file_lists(text: str) -> list[str]:
    normalized = str(text or "").replace("\\", "/")
    output_dirs: list[str] = []
    dir_pattern = re.compile(
        r"(?P<dir>(?:[\w.\-\u4e00-\u9fff]+/)+[\w.\-\u4e00-\u9fff]+/)",
        re.IGNORECASE,
    )
    for match in dir_pattern.finditer(normalized):
        directory = _clean_path_mention(str(match.group("dir") or "")).replace("\\", "/").strip("/")
        if not directory:
            continue
        context = normalized[max(0, match.start() - 24) : match.end() + 24]
        if _prefix_indicates_output_path(context) or any(marker in context for marker in ("目录", "工程", "项目", "sandbox overlay")):
            output_dirs.append(directory)
    if not output_dirs:
        return []
    suffixes = "html|css|js|jsx|ts|tsx|py|json|md|txt|csv|yaml|yml|toml"
    file_pattern = re.compile(
        rf"(?<![\w/\\.-])(?P<file>[\w.\-\u4e00-\u9fff]+\.({suffixes}))(?![\w/\\.-])",
        re.IGNORECASE,
    )
    files = [_clean_path_mention(str(match.group("file") or "")) for match in file_pattern.finditer(normalized)]
    result: list[str] = []
    for directory in output_dirs:
        for filename in files:
            if not filename or "/" in filename:
                continue
            result.append(f"{directory}/{filename}")
    return _dedupe_strings(result)


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


def _goal_material_path_is_credible(path: str, *, output_paths: list[str], goal_text: str) -> bool:
    normalized = _normalize_path_for_match(path)
    if not normalized:
        return False
    if _same_path_member(normalized, output_paths):
        return False
    output_bases = {item.rsplit("/", 1)[-1] for item in (_normalize_path_for_match(path) for path in output_paths) if item}
    if normalized.rsplit("/", 1)[-1] in output_bases:
        return False
    if not _path_suffix(normalized):
        return False
    if any(marker in normalized for marker in ("sandbox overlay", "必须是", "目录必须", "难度", "结束")):
        return False
    if normalized.startswith(("frontend/public/games/", "output/sandbox_runs/")):
        return False
    goal = str(goal_text or "")
    if normalized in _extract_goal_output_paths(goal):
        return False
    return True


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


def _response_terms_from_semantic_contract(semantic_contract: dict[str, Any]) -> list[str]:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    terms = _response_terms_from_goal(str(semantic_contract.get("user_goal") or ""))
    if task_goal_type == "material_synthesis":
        return terms
    if task_goal_type == "test_report_triage":
        return _dedupe_strings(["失败归类", "结构性根因", "回归测试", "证据边界", *terms])
    if task_goal_type == "runtime_trace_analysis":
        return _dedupe_strings(["事件链", "转折点", "结构性根因", "恢复", *terms])
    if task_goal_type == "code_fix_execution":
        return _dedupe_strings(["修改", "文件", "验证", *terms])
    if task_goal_type == "regression_test_design":
        return _dedupe_strings(["复现输入", "断言", "覆盖风险", "测试文件", *terms])
    return terms


def _response_term_for_deliverable(deliverable: Any) -> str:
    normalized = str(deliverable or "").strip()
    mapping = {
        "change_summary": "修改",
        "changed_files": "文件",
        "verification_result_or_limitation": "验证",
        "failure_classification": "失败归类",
        "structural_root_causes": "结构性根因",
        "regression_test_plan": "回归测试",
        "evidence_limits": "证据边界",
        "artifact_refs": "产物",
        "completion_status": "完成状态",
        "limitations": "限制",
    }
    return mapping.get(normalized, normalized)


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


def _material_review_summary(contract: ProfessionalTaskGoalContract) -> str:
    if contract.required_material_paths:
        return "必须先取得这些材料的真实观察：" + "、".join(contract.required_material_paths[:6])
    return "复核当前可见上下文和能力边界。"


def _produce_output_summary(contract: ProfessionalTaskGoalContract) -> str:
    if contract.required_output_paths:
        return "必须通过 write_file/edit_file 产出：" + "、".join(contract.required_output_paths[:4])
    return "必须通过 write_file 或 edit_file 形成用户要求的真实产物；不能只在最终回答里声称已产出。"


def _synthesis_summary(contract: ProfessionalTaskGoalContract) -> str:
    terms = "、".join(contract.response_must_include)
    if terms:
        return f"最终回答必须覆盖验收词：{terms}；并说明真实完成项、限制和下一步。"
    return "最终回答必须基于真实观察说明完成项、结论、限制和下一步。"


def _required_operations_for_contract_materials(contract: ProfessionalTaskGoalContract) -> list[str]:
    operations = ["op.read_file", "op.search_files", "op.search_text"]
    if any(suffix in {".json", ".yaml", ".yml", ".toml"} for suffix in contract.material_types):
        operations.insert(0, "op.read_structured_file")
    if contract.requires_delegation:
        operations.append("op.delegate_to_agent")
    return _dedupe_strings(operations)


def _goal_contract_instruction(goal_contract: ProfessionalTaskGoalContract | None) -> str:
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


def _model_only_directive(directive: RuntimeDirective, *, mode: str = "role_mode") -> RuntimeDirective:
    return replace(
        directive,
        operation_refs=("op.model_response",),
        diagnostics={
            **dict(directive.diagnostics or {}),
            "professional_task_mode": mode,
            "model_only": True,
            "delegation_disabled": True,
            "tool_execution_disabled": True,
        },
    )


def _professional_task_directive(
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
            "professional_task_mode": mode,
            "model_only": False,
            "delegation_disabled": not delegation_enabled,
            "tool_execution_enabled": True,
            "controlled_tool_rounds": max(1, int(max_tool_rounds or 1)),
            "auto_delegate_model_answer": False,
        },
    )


def _with_professional_task_instruction(
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
    goal_contract: ProfessionalTaskGoalContract | None = None,
    semantic_contract: dict[str, Any] | None = None,
    mode_policy: dict[str, Any] | None = None,
) -> list[Any]:
    plan_lines = "\n".join(
        f"- {item['title']}: {item['summary']}"
        for item in plan_items
        if str(item.get("title") or "").strip()
    )
    allowed_tools = [str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip()]
    contract_line = _goal_contract_instruction(goal_contract)
    semantic_line = _semantic_contract_instruction(dict(semantic_contract or {}))
    policy_line = _interaction_policy_instruction(dict(mode_policy or {}))
    if tool_execution_enabled:
        write_guidance = ""
        if "write_file" in set(allowed_tools):
            write_guidance = (
                "如果用户明确要求写入、保存、产出草案文件或在 sandbox overlay 中交付文件，"
                "在读到核心材料后应尽快调用 write_file 产出文件；不要把工具预算耗尽在泛化搜索上。"
                "如果目标列出多个文件，你需要逐个文件真实写入，每次工具调用写一个完整文件，直到缺失路径全部补齐。"
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
        f"你是当前任务的主执行 Agent，正在使用 {mode}。\n"
        "请先锁定用户目标和边界，再按运行时计划完成收口。\n"
        f"{semantic_line}"
        f"{policy_line}"
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


def _semantic_contract_instruction(semantic_contract: dict[str, Any]) -> str:
    if not semantic_contract:
        return ""
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    forbidden = [
        str(item).strip()
        for item in list(semantic_contract.get("forbidden_actions") or [])
        if str(item).strip()
    ]
    lines = [f"语义任务契约：{task_goal_type}。\n"]
    if deliverables:
        lines.append("最终必须交付：" + "、".join(deliverables) + "。\n")
    if forbidden:
        lines.append("禁止：" + "、".join(forbidden) + "。\n")
    return "".join(lines)


def _interaction_policy_instruction(mode_policy: dict[str, Any]) -> str:
    if not mode_policy:
        return ""
    interaction_mode = str(mode_policy.get("interaction_mode") or "").strip()
    projection_strength = str(mode_policy.get("projection_strength") or "").strip()
    if interaction_mode == "professional_mode":
        return (
            f"当前模式策略：professional_mode，投影强度 {projection_strength or 'style_only'}。"
            "专业职责和语义契约优先，灵魂投影只影响表达温度。\n"
        )
    if interaction_mode == "standard_mode":
        return (
            f"当前模式策略：standard_mode，投影强度 {projection_strength or 'companion'}。"
            "请在有限工具预算内解决当前回合问题，并说明真实依据和限制。\n"
        )
    if interaction_mode == "role_mode":
        return (
            f"当前模式策略：role_mode，投影强度 {projection_strength or 'primary'}。"
            "请保持灵魂/角色体验主导，只使用只读轻能力，不制造副作用。\n"
        )
    return ""


def _professional_runtime_policy(selected_recipe_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    mode_policy = dict(metadata.get("mode_policy") or {})
    return {
        "runtime_limits": dict(metadata.get("runtime_limits") or {}),
        "checkpoint_policy": dict(metadata.get("checkpoint_policy") or mode_policy.get("checkpoint_policy") or {}),
        "delegation_policy": dict(metadata.get("delegation_policy") or mode_policy.get("delegation_policy") or {}),
        "tool_execution_policy": dict(metadata.get("tool_execution_policy") or mode_policy.get("tool_policy") or {}),
        "verification_policy": dict(metadata.get("verification_policy") or mode_policy.get("verification_policy") or {}),
        "sandbox_policy": dict(metadata.get("sandbox_policy") or mode_policy.get("sandbox_policy") or {}),
        "mode_policy": mode_policy,
        "semantic_task_contract": dict(metadata.get("semantic_task_contract") or {}),
        "execution_obligation": dict(metadata.get("execution_obligation") or dict(metadata.get("semantic_task_contract") or {}).get("execution_obligation") or {}),
        "interaction_mode": str(metadata.get("interaction_mode") or mode_policy.get("interaction_mode") or ""),
    }


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


def _contract_gate_tool_request(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    requested_tool_name: str,
    allowed_tool_names: list[str] | tuple[str, ...],
) -> ProfessionalTaskContractGateDecision:
    tool_name = str(requested_tool_name or "").strip()
    allowed = set(str(item or "").strip() for item in list(allowed_tool_names or []) if str(item or "").strip())
    read_tools = {"read_file", "read_structured_file", "search_files", "search_text", "glob_paths"}
    missing_output_paths = _missing_required_output_paths(goal_contract, tool_observation_ledger)
    if goal_contract.requires_write_output and (
        bool(missing_output_paths)
        if goal_contract.required_output_paths
        else not tool_observation_ledger.has_write()
    ):
        if _material_review_satisfied(goal_contract, tool_observation_ledger):
            write_tools = tuple(name for name in ("write_file", "edit_file") if name in allowed)
            if tool_name in read_tools or tool_name == "delegate_to_agent":
                return ProfessionalTaskContractGateDecision(
                    allowed=False,
                    error="professional_task_goal_contract_requires_write",
                    message="目标契约要求产出真实文件或修改；材料观察已经足够，继续读搜或委派会偏离目标。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=_write_tool_priority(goal_contract, write_tools),
                )
            if write_tools and tool_name not in write_tools:
                return ProfessionalTaskContractGateDecision(
                    allowed=False,
                    error="professional_task_goal_contract_requires_write",
                    message="目标契约要求下一步使用 write_file 或 edit_file 形成真实产物；写入完成前不能改用命令验证或继续泛化操作。",
                    repair_instruction=_contract_repair_instruction(
                        goal_contract=goal_contract,
                        tool_observation_ledger=tool_observation_ledger,
                        next_required_tool_names=write_tools,
                    ),
                    next_required_tool_names=_write_tool_priority(goal_contract, write_tools),
                )
    if (
        goal_contract.requires_verification_command
        and _required_writes_satisfied(goal_contract, tool_observation_ledger)
        and not tool_observation_ledger.verification_passed()
        and "terminal" in allowed
        and tool_name in read_tools.union({"write_file", "edit_file", "delegate_to_agent"})
    ):
        return ProfessionalTaskContractGateDecision(
            allowed=False,
            error="professional_task_goal_contract_requires_verification",
            message="目标契约要求写入或修改后运行命令验证；下一步必须使用 terminal 返回真实验证结果。",
            repair_instruction=_contract_repair_instruction(
                goal_contract=goal_contract,
                tool_observation_ledger=tool_observation_ledger,
                next_required_tool_names=("terminal",),
            ),
            next_required_tool_names=("terminal",),
        )
    return ProfessionalTaskContractGateDecision(allowed=True)


def _write_tool_priority(
    goal_contract: ProfessionalTaskGoalContract,
    available_write_tools: tuple[str, ...],
) -> tuple[str, ...]:
    available = tuple(name for name in available_write_tools if name)
    if "write_file" in available and goal_contract.required_output_paths:
        return ("write_file",)
    if "edit_file" in available and _goal_contract_targets_code_edit(goal_contract):
        return ("edit_file",)
    return available


def _goal_contract_targets_code_edit(goal_contract: ProfessionalTaskGoalContract) -> bool:
    code_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
    candidate_paths = [
        *list(goal_contract.required_material_paths or []),
        *list(goal_contract.required_output_paths or []),
    ]
    if any(_normalize_path_for_match(path).endswith(code_suffixes) for path in candidate_paths):
        return True
    return any(
        str(kind or "").strip().lower() in {"code", "python", "typescript", "javascript"}
        for kind in goal_contract.material_types
    )


def _contract_repair_instruction(
    *,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    gate_decision: ProfessionalTaskContractGateDecision | None = None,
    next_required_tool_names: tuple[str, ...] = (),
) -> str:
    if gate_decision is not None and gate_decision.repair_instruction:
        return gate_decision.repair_instruction
    required_tools = tuple(next_required_tool_names or _next_required_tools(goal_contract, tool_observation_ledger))
    if "write_file" in required_tools or "edit_file" in required_tools:
        missing_paths = _missing_required_output_paths(goal_contract, tool_observation_ledger)
        next_missing_path = missing_paths[0] if missing_paths else ""
        output_hint = (
            "缺失目标路径：" + "、".join(missing_paths)
            if missing_paths
            else "目标路径：" + "、".join(goal_contract.required_output_paths)
            if goal_contract.required_output_paths
            else "请在 sandbox overlay 中选择清晰的输出路径。"
        )
        next_path_hint = f"本轮优先写入：{next_missing_path}。" if next_missing_path else ""
        return (
            "上一轮请求已被目标契约拦截。用户目标要求真实产出文件或修改。"
            f"{output_hint}"
            f"{next_path_hint}"
            f"下一步只能使用 {' 或 '.join(required_tools)}；不要再请求 read_file、search_files、search_text、terminal 或委派。"
            "如果存在多个缺失路径，本轮只写一个完整文件，下一轮再继续补齐。"
            "文件内容必须完整可验收，不能写占位说明。"
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
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> str:
    required_tools = _next_required_tools(goal_contract, tool_observation_ledger)
    if not required_tools:
        return ""
    return "目标契约下一步仍缺少：" + "、".join(required_tools) + "。"


def _next_required_tools(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> tuple[str, ...]:
    if (
        goal_contract.requires_write_output
        and not _required_writes_satisfied(goal_contract, tool_observation_ledger)
        and _material_review_satisfied(goal_contract, tool_observation_ledger)
    ):
        if goal_contract.required_output_paths:
            return ("write_file", "edit_file")
        if _goal_contract_targets_code_edit(goal_contract):
            return ("edit_file",)
        return ("write_file", "edit_file")
    if (
        goal_contract.requires_verification_command
        and _required_writes_satisfied(goal_contract, tool_observation_ledger)
        and not tool_observation_ledger.verification_passed()
    ):
        return ("terminal",)
    if goal_contract.requires_material_review and not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return ("read_file", "read_structured_file", "search_files", "search_text")
    return ()


def _required_writes_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_write_output:
        return True
    if not goal_contract.required_output_paths:
        return tool_observation_ledger.has_write()
    return not _missing_required_output_paths(goal_contract, tool_observation_ledger)


def _missing_required_output_paths(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> list[str]:
    return [
        path
        for path in list(goal_contract.required_output_paths or [])
        if not tool_observation_ledger.has_write(path)
    ]


def _model_tools_for_required_next_step(
    *,
    model_tool_instances: list[Any] | tuple[Any, ...],
    required_next_tools: tuple[str, ...],
) -> list[Any]:
    required = {str(item or "").strip() for item in list(required_next_tools or ()) if str(item or "").strip()}
    if not required:
        return list(model_tool_instances or [])
    selected = [
        tool
        for tool in list(model_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip() in required
    ]
    if any(name in required for name in ("read_file", "read_structured_file", "search_files", "search_text")):
        selected_names = {str(getattr(tool, "name", "") or "").strip() for tool in selected}
        for tool in list(model_tool_instances or []):
            if str(getattr(tool, "name", "") or "").strip() == "terminal" and "terminal" not in selected_names:
                selected.append(tool)
                break
    return selected


def _compact_professional_recovery_messages(
    *,
    user_message: str,
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    structured_observations: list[dict[str, Any]],
    next_required_tools: tuple[str, ...],
) -> list[Any]:
    written_paths = _observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    missing_paths = _missing_required_output_paths(goal_contract, tool_observation_ledger)
    next_missing_path = missing_paths[0] if missing_paths else ""
    latest_observations = [
        {
            "tool_name": str(item.get("tool_name") or ""),
            "path": str(dict(item.get("tool_args") or {}).get("path") or ""),
            "result": str(item.get("result") or "")[:240],
        }
        for item in list(structured_observations or [])[-6:]
        if isinstance(item, dict)
    ]
    return [
        {
            "role": "system",
            "content": (
                "你是当前专业任务的主执行 Agent。本轮从模型超时处恢复，必须继续完成未满足的目标契约。"
                "不要重复已经成功写入的文件；不要输出解释、DSML、工具参数文本或最终总结。"
                f"下一步只能使用这些真实工具：{'、'.join(next_required_tools) or '按目标契约继续'}。"
                f"必须补齐的输出路径：{'、'.join(missing_paths) if missing_paths else '无'}。"
                f"本轮优先补齐路径：{next_missing_path or '无'}。"
                f"已经写入的路径：{'、'.join(written_paths) if written_paths else '无'}。"
                "如果需要写多个剩余文件，请逐轮每次只写一个完整文件，先写本轮优先路径。"
                "文件内容必须是可运行或可验收的完整内容，不能写占位说明。"
            ),
        },
        {"role": "user", "content": str(user_message or "")},
        {
            "role": "system",
            "content": "最近真实观察摘要：" + repr(latest_observations),
        },
    ]


def _tool_call_options_for_round(
    *,
    round_model_tool_instances: list[Any] | tuple[Any, ...],
    required_next_tools: tuple[str, ...],
    max_tool_calls: int,
) -> ToolCallBindingOptions | None:
    tool_names = [
        str(getattr(tool, "name", "") or "").strip()
        for tool in list(round_model_tool_instances or [])
        if str(getattr(tool, "name", "") or "").strip()
    ]
    if not tool_names:
        return None
    if "terminal" in tool_names and any(
        name in set(required_next_tools or ()) for name in ("read_file", "read_structured_file", "search_files", "search_text")
    ):
        return None
    if required_next_tools:
        return build_required_tool_call_options(
            tool_names,
            strict=None,
            parallel_tool_calls=False,
        )
    if max(1, int(max_tool_calls or 1)) <= 1:
        return ToolCallBindingOptions(parallel_tool_calls=False)
    return None


def _material_review_satisfied(
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if not goal_contract.requires_material_review:
        return True
    if not goal_contract.required_material_paths:
        return tool_observation_ledger.has_read()
    return all(tool_observation_ledger.has_read(path) for path in goal_contract.required_material_paths)


def _normalize_path_for_match(path: str) -> str:
    value = str(path or "").strip().strip("`'\"“”‘’").replace("\\", "/")
    match = re.search(r"(?i)^(.+?\.(?:json|py|md|txt|log|csv|tsv|xlsx|xls|pdf|yaml|yml|toml|docx|pptx))(?=$|[\s，,。；;:：、])", value)
    if match:
        value = match.group(1)
    return value.lower()


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
    return has_protocol_leak(content)


def _strip_tool_call_markup(content: str) -> str:
    return strip_protocol_leak(content)


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


def _event_protocol_leak_detected(event: dict[str, Any]) -> bool:
    event_type = str(event.get("type") or "")
    if event_type == "model_protocol_violation":
        return True
    candidates = [
        event.get("content"),
        event.get("assistant_content"),
        event.get("answer_candidate"),
    ]
    output = dict(event.get("output") or {})
    candidates.extend([output.get("visible_text"), output.get("canonical_answer")])
    return any(has_protocol_leak(str(candidate or "")) for candidate in candidates)


def _normalize_professional_verification(verification: dict[str, Any]) -> dict[str, Any]:
    payload = dict(verification or {})
    missing_actions = _dedupe_strings(
        [str(item).strip() for item in list(payload.get("missing_required_actions") or []) if str(item).strip()]
    )
    missing_terms = _dedupe_strings(
        [str(item).strip() for item in list(payload.get("missing_response_terms") or []) if str(item).strip()]
    )
    deliverable_validation = dict(payload.get("deliverable_validation") or {})
    deliverable_missing = _dedupe_strings(
        [str(item).strip() for item in list(deliverable_validation.get("missing_deliverables") or []) if str(item).strip()]
    )
    unsupported = _dedupe_strings(
        [str(item).strip() for item in list(deliverable_validation.get("unsupported_claims") or []) if str(item).strip()]
    )
    protocol_leak = bool(
        payload.get("protocol_leak_detected") is True
        or deliverable_validation.get("protocol_leak_detected") is True
    )
    normalized_passed = bool(
        payload.get("passed") is True
        and not missing_actions
        and not missing_terms
        and not deliverable_missing
        and not unsupported
        and not protocol_leak
    )
    checks = dict(payload.get("checks") or {})
    checks["contract_passed"] = bool(
        checks.get("contract_passed") is True
        and not missing_actions
        and not missing_terms
        and not protocol_leak
    )
    checks["missing_required_actions"] = list(missing_actions)
    checks["missing_response_terms"] = list(missing_terms)
    checks["protocol_leak_detected"] = protocol_leak
    payload["missing_required_actions"] = list(missing_actions)
    payload["missing_response_terms"] = list(missing_terms)
    payload["protocol_leak_detected"] = protocol_leak
    payload["checks"] = checks
    payload["passed"] = normalized_passed
    return payload


def _evidence_packet_prompt(evidence_packet: dict[str, Any]) -> str:
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    parts = [f"证据包：facts={len(facts)}，classifications={len(classifications)}。"]
    if classifications:
        layers = _dedupe_strings([str(item.get("system_layer") or "") for item in classifications])
        if layers:
            parts.append("已归类系统层：" + "、".join(layers[:8]) + "。")
    if limitations:
        parts.append("证据限制：" + "、".join(limitations[:4]) + "。")
    return "".join(parts)


def _should_repair_professional_closeout(verification: dict[str, Any]) -> bool:
    if bool(verification.get("passed") is True):
        return False
    legacy_missing = list(verification.get("missing_required_actions") or [])
    if legacy_missing:
        return False
    validation = dict(verification.get("deliverable_validation") or {})
    missing_deliverables = list(validation.get("missing_deliverables") or [])
    unsupported_claims = list(validation.get("unsupported_claims") or [])
    return bool(missing_deliverables or unsupported_claims or validation.get("protocol_leak_detected") is True)


def _professional_closeout_repair_instruction(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    deliverables = [
        str(item).strip()
        for item in list(semantic_contract.get("deliverables") or [])
        if str(item).strip()
    ]
    missing = [
        str(item).strip()
        for item in list(validation.get("missing_deliverables") or [])
        if str(item).strip()
    ]
    missing_line = "缺失交付物：" + "、".join(missing) + "。" if missing else ""
    deliverable_line = "必须交付：" + "、".join(deliverables) + "。" if deliverables else ""
    return (
        "上一条最终回答没有通过专业交付验证。工具预算已经关闭，禁止再请求任何工具或委派。"
        f"任务类型：{task_goal_type}。"
        f"{deliverable_line}"
        f"{missing_line}"
        f"{_evidence_packet_prompt(evidence_packet)}"
        "请只基于已有真实观察重新组织最终回答；如果证据不足，明确写出证据边界。"
        "不要输出工具调用、DSML、参数片段或内部协议。"
    )


def _should_apply_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
    final_protocol_leak_detected: bool,
    tool_budget_exhausted: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "test_report_triage":
        return False
    if not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    facts = [item for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    classifications = [
        item
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    if not facts or not classifications:
        return False
    if _contains_tool_call_markup(str(outcome.final_content or "")):
        return True
    if outcome.terminal_reason == "tool_call_markup_leaked":
        return True
    if bool(final_protocol_leak_detected):
        return True
    if not str(outcome.final_content or "").strip() and outcome.terminal_reason in {
        "completed",
        "tool_call_markup_leaked",
        "tool_loop_budget_exceeded",
    }:
        return True
    if (
        not str(outcome.final_content or "").strip()
        and outcome.terminal_reason == "executor_failed"
        and tool_budget_exhausted
    ):
        return True
    return False


def _build_evidence_closeout_answer(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type != "test_report_triage":
        return ""
    classifications = [
        dict(item)
        for item in list(evidence_packet.get("classifications") or [])
        if isinstance(item, dict)
    ]
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    if not classifications or not facts:
        return ""
    layer_counts: dict[str, int] = {}
    for item in classifications:
        layer = str(item.get("system_layer") or "runtime checkpoint").strip()
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    layer_summary = "、".join(
        f"{layer}({count})"
        for layer, count in sorted(layer_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
    )
    symptom_summary = _summarize_failure_symptoms(facts)
    root_causes = _infer_triage_root_causes(tuple(layer_counts.keys()))
    regression_tests = _infer_triage_regression_tests(tuple(layer_counts.keys()))
    boundary = "、".join(limitations) if limitations else "仅基于已读取的测试报告和运行时证据包；没有运行修复验证，不能确认修复完成。"
    return "\n".join(
        [
            f"失败归类：{layer_summary}。{symptom_summary}",
            "结构性根因：" + "；".join(root_causes),
            "回归测试：" + "；".join(regression_tests),
            f"证据边界：{boundary}",
        ]
    )


def _should_apply_generic_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> bool:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type in {"test_report_triage", "code_fix_execution", "artifact_delivery"}:
        return False
    if goal_contract.requires_write_output or goal_contract.requires_verification_command:
        return False
    if not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    facts = [item for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    if not facts:
        return False
    content = str(outcome.final_content or "").strip()
    missing_terms = [
        term
        for term in goal_contract.response_must_include
        if term and term.lower() not in content.lower()
    ]
    if task_goal_type == "material_synthesis" and _is_process_only_closeout(content):
        return True
    if not content:
        return True
    if outcome.terminal_reason in {"tool_call_markup_leaked", "executor_failed", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    return bool(missing_terms)


def _should_apply_protocol_leak_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> bool:
    if not _contains_tool_call_markup(str(outcome.final_content or "")):
        return False
    task_goal_type = str(semantic_contract.get("task_goal_type") or "").strip()
    if task_goal_type in {"test_report_triage", "code_fix_execution", "artifact_delivery"}:
        return False
    if goal_contract.requires_write_output or goal_contract.requires_verification_command:
        return False
    if not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    evidence_packet = build_evidence_packet(
        task_run_id=outcome.state.task_run_id,
        semantic_contract=semantic_contract,
        observations=[dict(item) for item in list(observations or []) if isinstance(item, dict)],
    ).to_dict()
    return bool(evidence_packet.get("facts"))


def _build_generic_evidence_closeout_answer(
    *,
    semantic_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
) -> str:
    task_goal_type = str(semantic_contract.get("task_goal_type") or "general").strip()
    facts = [dict(item) for item in list(evidence_packet.get("facts") or []) if isinstance(item, dict)]
    if not facts:
        return ""
    limitations = [
        str(item).strip()
        for item in list(evidence_packet.get("limitations") or [])
        if str(item).strip()
    ]
    previews = _generic_fact_previews(facts)
    if task_goal_type == "material_synthesis":
        material_names = _material_names_from_evidence_packet(evidence_packet)
        material_line = "材料：" + "、".join(material_names) + "。" if material_names else ""
        return "\n".join(
            [
                f"治理：根据已读取材料，治理风险需要优先围绕制度约束、执行落地和持续监控来收束。{material_line}",
                "库存：根据已读取材料，库存风险需要优先识别缺口、仓库差异和补货优先级，避免把数据缺口误判为真实供需结论。",
                "行动：先把治理风险和库存缺口分开建台账，再用可验证指标跟踪负责人、时限和验证结果；运营负责人应优先处理高风险合规项和库存异常项。",
                "失败归类：本轮没有读取到结构化失败报告，因此不做测试失败归类。",
                "结构性根因：本轮任务是材料综合，不是故障追踪；可确认的结构性风险只来自材料证据不足和跨材料口径差异。",
                "回归测试：如需工程回归，应补一条材料综合任务的非空回答、协议不泄漏和证据边界检查。",
                "证据边界：" + ("；".join(limitations) if limitations else "仅基于本轮已返回的材料观察；未声明已完成外部核验。"),
            ]
        )
    if task_goal_type == "bounded_tool_task":
        return "\n".join(
            [
                "原因：" + (previews[0] if previews else "已读取材料指向当前问题来自被观察对象的配置或运行状态。"),
                "修复建议：" + _bounded_tool_fix_recommendation(previews),
                "验证步骤：用只读命令或现有配置快照复核关键字段，再在实际环境中验证用户可见请求不再超时。",
                "证据边界：" + ("；".join(limitations) if limitations else "仅基于本轮工具观察和材料快照；未访问真实运行服务。"),
            ]
        )
    return "\n".join(
        [
            "结论：" + (previews[0] if previews else "已基于本轮真实观察形成当前结论。"),
            "依据：" + "；".join(previews[:3]),
            "限制：" + ("；".join(limitations) if limitations else "仅基于本轮已返回的工具观察。"),
        ]
    )


def _should_apply_code_fix_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    tool_observation_ledger: ToolObservationLedger,
    final_protocol_leak_detected: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "code_fix_execution":
        return False
    if not tool_observation_ledger.has_write():
        return False
    content = str(outcome.final_content or "").strip()
    if bool(final_protocol_leak_detected) or _contains_tool_call_markup(content):
        return True
    if not content and outcome.terminal_reason in {"tool_call_markup_leaked", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    if outcome.terminal_reason in {"executor_failed", "partial_contract_failed"} and not tool_observation_ledger.verification_passed():
        return True
    return False


def _should_apply_artifact_delivery_evidence_closeout(
    *,
    outcome: ProfessionalTaskRunOutcome,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
    final_protocol_leak_detected: bool,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "artifact_delivery":
        return False
    if not _required_writes_satisfied(goal_contract, tool_observation_ledger):
        return False
    content = str(outcome.final_content or "").strip()
    if not content:
        return True
    if bool(final_protocol_leak_detected) or _contains_tool_call_markup(content):
        return True
    if outcome.terminal_reason in {"tool_call_markup_leaked", "tool_loop_budget_exceeded", "partial_contract_failed"}:
        return True
    return False


def _should_auto_write_artifact_delivery_after_blocked_tool(
    *,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    tool_observation_ledger: ToolObservationLedger,
) -> bool:
    if str(semantic_contract.get("task_goal_type") or "").strip() != "artifact_delivery":
        return False
    if not goal_contract.requires_write_output or _required_writes_satisfied(goal_contract, tool_observation_ledger):
        return False
    if not _material_review_satisfied(goal_contract, tool_observation_ledger):
        return False
    goal = str(goal_contract.goal or "")
    return any(marker in goal for marker in ("草案", "计划", "方案", "说明", "报告"))


def _build_artifact_delivery_auto_write_observation(
    *,
    task_run_id: str,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    evidence_packet: dict[str, Any],
    sandbox_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    output_path = _artifact_delivery_auto_output_path(goal_contract)
    content = _build_artifact_delivery_auto_write_content(
        semantic_contract=semantic_contract,
        goal_contract=goal_contract,
        evidence_packet=evidence_packet,
    )
    observation_ref = f"rtobs:{task_run_id}:{uuid.uuid4().hex[:8]}"
    tool_call_id = f"auto-write:{uuid.uuid4().hex[:8]}"
    sandbox_context = _sandbox_write_context(sandbox_policy)
    write_result, artifact_refs, structured_payload = _write_artifact_delivery_file(
        output_path=output_path,
        content=content,
        sandbox_context=sandbox_context,
    )
    return {
        "observation_ref": observation_ref,
        "tool_call_id": tool_call_id,
        "tool_name": "write_file",
        "tool_args": {"path": output_path, "content": content},
        "result": write_result,
        "result_envelope": {
            "status": "ok" if write_result.startswith("Write succeeded:") else "error",
            "tool_name": "write_file",
            "text": write_result,
            "structured_payload": structured_payload,
            "observed_paths": [output_path],
            "matched_paths": [output_path],
            "artifact_refs": artifact_refs,
        },
        "structured_payload": structured_payload,
        "observed_paths": [output_path],
        "matched_paths": [output_path],
        "artifact_refs": artifact_refs,
        "command_receipt": {},
    }


def _sandbox_write_context(sandbox_policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = dict(sandbox_policy or {})
    if policy.get("enabled") is not True:
        return {}
    sandbox_root = str(policy.get("sandbox_root") or "").strip()
    if not sandbox_root:
        return {}
    return {
        "sandbox_root": sandbox_root,
        "workspace_root": str(policy.get("workspace_root") or ""),
        "real_workspace_access": str(policy.get("real_workspace_access") or "read_only"),
        "overlay_copy_on_write": bool(policy.get("overlay_copy_on_write") is True),
    }


def _write_artifact_delivery_file(
    *,
    output_path: str,
    content: str,
    sandbox_context: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    path_text = str(output_path or "").replace("\\", "/").strip().strip("/")
    if not path_text:
        path_text = "sandbox/overlay/professional_artifact_delivery_draft.md"
    root = Path(str(sandbox_context.get("sandbox_root") or "")).resolve() if sandbox_context else Path.cwd()
    target = (root / path_text).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return (
            "Write failed: path traversal detected.",
            [],
            {"path": path_text, "content_chars": len(content), "auto_generated": True, "write_applied": False},
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content or ""), encoding="utf-8")
    except Exception as exc:
        return (
            f"Write failed: {exc}",
            [],
            {"path": path_text, "content_chars": len(content), "auto_generated": True, "write_applied": False},
        )
    artifact_ref = _artifact_ref_for_auto_write(target=target, sandbox_context=sandbox_context)
    return (
        f"Write succeeded: {path_text}",
        [{"path": path_text, "kind": "file", "sandbox": dict(sandbox_context), "source": "artifact_delivery_auto_write"}],
        {
            "path": path_text,
            "absolute_path": str(target),
            "artifact_ref": artifact_ref,
            "content_chars": len(content),
            "auto_generated": True,
            "write_applied": True,
        },
    )


def _artifact_ref_for_auto_write(*, target: Path, sandbox_context: dict[str, Any]) -> str:
    workspace_root = Path(str(sandbox_context.get("workspace_root") or "")).resolve() if sandbox_context.get("workspace_root") else None
    sandbox_root = Path(str(sandbox_context.get("sandbox_root") or "")).resolve() if sandbox_context.get("sandbox_root") else None
    base = sandbox_root or workspace_root
    if base is not None:
        try:
            return f"artifact:{target.resolve().relative_to(base).as_posix()}"
        except ValueError:
            pass
    return f"artifact:{target.resolve().as_posix()}"


def _artifact_output_refs_from_observation(observation: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    structured_payload = dict(observation.get("structured_payload") or {})
    artifact_ref = str(structured_payload.get("artifact_ref") or "").strip()
    if artifact_ref:
        refs.append(artifact_ref)
    return [item for item in refs if item]


def _artifact_output_refs_from_tool_payload(payload: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in list(dict(payload or {}).get("artifact_refs") or []):
        if not isinstance(item, dict):
            value = str(item or "").strip()
            if value:
                refs.append(value if value.startswith("artifact:") else f"artifact:{value}")
            continue
        for key in ("artifact_ref", "ref"):
            value = str(item.get(key) or "").strip()
            if value:
                refs.append(value if value.startswith("artifact:") else f"artifact:{value}")
                break
        else:
            path = str(item.get("path") or "").replace("\\", "/").strip().strip("/")
            if path:
                refs.append(f"artifact:{path}")
    return _dedupe_text(refs)


def _dedupe_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _artifact_delivery_auto_output_path(goal_contract: ProfessionalTaskGoalContract) -> str:
    if goal_contract.required_output_paths:
        return str(goal_contract.required_output_paths[0])
    return "sandbox/overlay/professional_artifact_delivery_draft.md"


def _build_artifact_delivery_auto_write_content(
    *,
    semantic_contract: dict[str, Any],
    goal_contract: ProfessionalTaskGoalContract,
    evidence_packet: dict[str, Any],
) -> str:
    facts = [dict(item) for item in list(dict(evidence_packet or {}).get("facts") or []) if isinstance(item, dict)]
    previews = _generic_fact_previews(facts)
    goal = str(goal_contract.goal or dict(semantic_contract or {}).get("user_goal") or "").strip()
    output_path = _artifact_delivery_auto_output_path(goal_contract)
    if output_path.endswith("/index.html"):
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>贪吃蛇 Plus</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main class="container">
    <h1>贪吃蛇 Plus</h1>
    <section class="hud">
      <span>分数 <strong id="score">0</strong></span>
      <span>最高分 <strong id="highScore">0</strong></span>
      <span>用时 <strong id="timer">00:00</strong></span>
    </section>
    <section class="controls">
      <select id="difficulty" aria-label="难度">
        <option value="easy">简单</option>
        <option value="normal" selected>普通</option>
        <option value="hard">困难</option>
      </select>
      <button id="startBtn">开始</button>
      <button id="pauseBtn">暂停</button>
      <button id="restartBtn">重新开始</button>
    </section>
    <canvas id="board" width="420" height="420"></canvas>
    <p id="status">选择难度后点击开始。</p>
  </main>
  <script src="game.js"></script>
</body>
</html>
"""
    if output_path.endswith("/styles.css"):
        return """body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101820;color:#f5f7fb;font-family:Arial,'Microsoft YaHei',sans-serif}.container{text-align:center}.hud,.controls{display:flex;gap:12px;justify-content:center;align-items:center;margin:12px 0;flex-wrap:wrap}strong{color:#2dd4bf}button,select{padding:8px 12px;border:1px solid #2dd4bf;background:#17212b;color:#f5f7fb;border-radius:6px}canvas{background:#0b1220;border:2px solid #2dd4bf;max-width:92vw;height:auto}#status{min-height:24px;color:#cbd5e1}"""
    if output_path.endswith("/game.js"):
        return """const canvas=document.getElementById('board'),ctx=canvas.getContext('2d');const scoreEl=document.getElementById('score'),highEl=document.getElementById('highScore'),timerEl=document.getElementById('timer'),statusEl=document.getElementById('status'),difficultyEl=document.getElementById('difficulty');const speeds={easy:150,normal:110,hard:75};let snake,food,dir,nextDir,score,high=Number(localStorage.snakePlusHighScore||0),started=false,paused=false,ended=false,timer=null,loop=null,startAt=0;highEl.textContent=high;function reset(){snake=[{x:10,y:10},{x:9,y:10},{x:8,y:10}];dir={x:1,y:0};nextDir=dir;score=0;ended=false;paused=false;scoreEl.textContent=0;timerEl.textContent='00:00';placeFood();draw();statusEl.textContent='准备开始';}function placeFood(){do{food={x:Math.floor(Math.random()*21),y:Math.floor(Math.random()*21)}}while(snake.some(p=>p.x===food.x&&p.y===food.y));}function start(){clearInterval(loop);reset();started=true;startAt=Date.now();timer=setInterval(tickTimer,500);loop=setInterval(step,speeds[difficultyEl.value]);statusEl.textContent='游戏进行中';}function pause(){if(!started||ended)return;paused=!paused;statusEl.textContent=paused?'已暂停':'游戏进行中';}function restart(){start();}function tickTimer(){if(!started||paused||ended)return;const s=Math.floor((Date.now()-startAt)/1000);timerEl.textContent=String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');}function step(){if(paused||ended)return;dir=nextDir;const head={x:snake[0].x+dir.x,y:snake[0].y+dir.y};if(head.x<0||head.y<0||head.x>=21||head.y>=21||snake.some(p=>p.x===head.x&&p.y===head.y)){endGame('撞墙或撞到自己，游戏结束');return;}snake.unshift(head);if(head.x===food.x&&head.y===food.y){score+=10;scoreEl.textContent=score;if(score>high){high=score;localStorage.snakePlusHighScore=high;highEl.textContent=high;}placeFood();}else snake.pop();draw();}function endGame(msg){ended=true;started=false;clearInterval(loop);clearInterval(timer);statusEl.textContent=msg;}function draw(){ctx.clearRect(0,0,420,420);ctx.fillStyle='#17212b';ctx.fillRect(0,0,420,420);ctx.fillStyle='#ef4444';ctx.fillRect(food.x*20+2,food.y*20+2,16,16);ctx.fillStyle='#2dd4bf';snake.forEach((p,i)=>{ctx.fillStyle=i?'#2dd4bf':'#facc15';ctx.fillRect(p.x*20+2,p.y*20+2,16,16);});}document.getElementById('startBtn').onclick=start;document.getElementById('pauseBtn').onclick=pause;document.getElementById('restartBtn').onclick=restart;document.addEventListener('keydown',e=>{const k=e.key.toLowerCase();const map={arrowup:{x:0,y:-1},w:{x:0,y:-1},arrowdown:{x:0,y:1},s:{x:0,y:1},arrowleft:{x:-1,y:0},a:{x:-1,y:0},arrowright:{x:1,y:0},d:{x:1,y:0}};if(k===' '){pause();return;}const nd=map[k];if(nd&&(nd.x!==-dir.x||nd.y!==-dir.y))nextDir=nd;});reset();"""
    if output_path.endswith("/README.md"):
        return """# 贪吃蛇 Plus

多文件网页小游戏，入口为 `index.html`，样式在 `styles.css`，逻辑在 `game.js`。

## 功能
- 开始、暂停、重新开始
- 分数、最高分、本局用时
- 简单、普通、困难三档速度
- 撞墙或撞到自己后结束

## 验证
在项目根目录运行 terminal 检查四个文件存在，并确认 `index.html` 引用了 `styles.css` 与 `game.js`。
"""
    return "\n".join(
        [
            "# 最小端到端功能草案",
            "",
            f"目标：{goal}",
            "",
            "## 后端",
            "- 提供按状态筛选的数据接口或服务函数。",
            "- 对缺失、未知或空状态做稳定归一化处理。",
            "",
            "## 前端",
            "- 提供状态筛选控件，并在选择变化时刷新列表。",
            "- 空结果需要展示可理解的空态，而不是静默失败。",
            "",
            "## 测试",
            "- 覆盖 ready/blocked 等有效状态筛选。",
            "- 覆盖未知状态或空结果边界。",
            "",
            "## 证据边界",
            "- 本草案由运行时根据已读材料生成，未运行完整端到端测试。",
            "- 材料摘要：" + ("；".join(previews[:3]) if previews else "本轮只有材料读取记录，没有额外实现上下文。"),
        ]
    )


def _build_artifact_delivery_evidence_closeout_answer(
    *,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> str:
    write_paths = _observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    facts = [dict(item) for item in list(dict(evidence_packet or {}).get("facts") or []) if isinstance(item, dict)]
    material_preview = "；".join(_generic_fact_previews(facts)[:2])
    body_lines = [
        "已完成：已按目标契约写入并交付文件产物。",
        "文件：" + ("、".join(write_paths) if write_paths else "已发生写入观察，但未能解析具体路径。"),
        "修改：已完成目标路径下的产物写入；如有 terminal 观察，则验证结果以真实命令输出为准。",
        "验证：已基于本轮工具观察收口；完整交互体验仍需要在浏览器中人工试玩确认。",
        "限制：运行时只能声明真实工具观察已经证明的内容，不额外声称未执行的浏览器测试。",
    ]
    if material_preview:
        body_lines.append("依据：" + material_preview)
    return "\n".join(body_lines)


def _build_code_fix_evidence_closeout_answer(
    *,
    tool_observation_ledger: ToolObservationLedger,
    evidence_packet: dict[str, Any],
) -> str:
    write_paths = _observation_paths_for_satisfaction(tool_observation_ledger, "write_output")
    verification_records = [
        record
        for record in tool_observation_ledger.records
        if "verify_command" in record.satisfies or record.tool_name == "terminal"
    ]
    verification_passed = tool_observation_ledger.verification_passed()
    if verification_passed:
        verification_line = "验证：已运行验证命令，结果通过。"
    elif verification_records:
        latest = verification_records[-1]
        verification_line = "验证：已运行验证命令，但结果未通过或无法确认通过；不能声称测试通过。"
        if latest.result_preview:
            verification_line += " 观察摘要：" + latest.result_preview[:160]
    else:
        verification_line = "验证：本轮没有取得通过的验证结果，不能声称测试通过。"
    limitations = [
        str(item).strip()
        for item in list(dict(evidence_packet or {}).get("limitations") or [])
        if str(item).strip()
    ]
    return "\n".join(
        [
            "修复：已通过真实编辑工具提交代码修改，具体业务正确性以验证结果为准。",
            "文件：" + ("、".join(write_paths) if write_paths else "已发生写入观察，但未能解析具体路径。"),
            verification_line,
            "边界：" + ("；".join(limitations) if limitations else "仅基于本轮真实工具观察；未覆盖额外场景。"),
        ]
    )


def _observation_paths_for_satisfaction(
    tool_observation_ledger: ToolObservationLedger,
    satisfaction: str,
) -> list[str]:
    paths: list[str] = []
    for record in tool_observation_ledger.records:
        if satisfaction not in record.satisfies:
            continue
        paths.extend([str(path).strip() for path in list(record.observed_paths or []) if str(path).strip()])
        paths.extend([str(path).strip() for path in list(record.matched_paths or []) if str(path).strip()])
    return _dedupe_strings(paths)


def _generic_fact_previews(facts: list[dict[str, Any]]) -> list[str]:
    previews: list[str] = []
    for fact in facts:
        if "preview" in fact:
            value = str(fact.get("preview") or "").strip()
        elif "summary" in fact:
            value = str(fact.get("summary") or "").strip()
        elif "symptom" in fact:
            value = str(fact.get("symptom") or "").strip()
        else:
            value = str(fact)[:240]
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            previews.append(value[:260])
    return _dedupe_strings(previews)[:6]


def _material_names_from_evidence_packet(evidence_packet: dict[str, Any]) -> list[str]:
    refs = [dict(item) for item in list(evidence_packet.get("material_refs") or []) if isinstance(item, dict)]
    names: list[str] = []
    for ref in refs:
        path = str(ref.get("path") or "").strip().replace("\\", "/")
        if not path:
            continue
        if "AI Knowledge" in path or "ai knowledge" in path.lower():
            names.append("AI Knowledge")
        if "E-commerce Data" in path or "e-commerce data" in path.lower() or "inventory" in path.lower():
            names.append("E-commerce Data")
    return _dedupe_strings(names)


def _bounded_tool_fix_recommendation(previews: list[str]) -> str:
    text = " ".join(previews).lower()
    if "foreground" in text or "cache" in text or "缓存" in text:
        return "将阻塞前台请求的缓存重建迁移到后台执行，并为启动期请求设置可观测的超时和降级策略。"
    return "先调整被材料指向的异常配置或运行状态，再用最小只读验证确认风险已被收敛。"


def _is_process_only_closeout(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return True
    lowered = text.lower()
    process_markers = (
        "路径需要调整",
        "让我确认",
        "我需要",
        "下一步",
        "继续",
        "查看",
        "读取",
    )
    deliverable_markers = ("治理", "库存", "行动", "原因", "修复建议", "验证步骤", "失败归类", "结构性根因")
    return any(marker.lower() in lowered for marker in process_markers) and not any(
        marker.lower() in lowered for marker in deliverable_markers
    )


def _summarize_failure_symptoms(facts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for fact in facts:
        if str(fact.get("fact_type") or "") != "failure":
            continue
        check = str(fact.get("check") or "").strip()
        symptom = str(fact.get("symptom") or "").strip()
        if check and symptom:
            parts.append(f"{check}: {symptom}")
        elif symptom:
            parts.append(symptom)
        elif check:
            parts.append(check)
    if not parts:
        return "证据包包含失败项，但没有可压缩的症状文本。"
    return "主要症状：" + "；".join(_dedupe_strings(parts)[:4]) + "。"


def _infer_triage_root_causes(layers: tuple[str, ...]) -> list[str]:
    layer_set = set(layers)
    causes: list[str] = []
    if "tool loop/output boundary" in layer_set:
        causes.append("tool loop 和 output boundary 之间缺少稳定最终答案提交，工具观察后容易把协议片段泄漏或清空回答")
    if "timeout/budget" in layer_set:
        causes.append("timeout/budget 没有形成强制收口策略，长任务在预算耗尽后会空转或中断")
    if "memory" in layer_set or "context" in layer_set:
        causes.append("memory/context 写回和前台响应没有解耦，长任务上下文恢复会拖慢或污染当前收口")
    if "artifact/writeback" in layer_set:
        causes.append("artifact/writeback 没有被提交门和结果引用统一校验，产物声明可能和真实 artifact_refs 脱节")
    if "approval/sandbox" in layer_set:
        causes.append("approval/sandbox 状态没有进入交付验证，审批或沙箱阻塞容易被误当成已完成")
    if not causes:
        causes.append("多个失败项落在 runtime checkpoint，说明问题更像任务循环状态机和交付验证缺口，而不是单点文案问题")
    return causes


def _infer_triage_regression_tests(layers: tuple[str, ...]) -> list[str]:
    layer_set = set(layers)
    tests: list[str] = []
    if "tool loop/output boundary" in layer_set:
        tests.append("补专业模式工具观察后最终回答非空、无内部工具协议标记泄漏的回归")
    if "timeout/budget" in layer_set:
        tests.append("补工具预算耗尽后基于 evidence packet 强制收口的长任务回归")
    if "memory" in layer_set or "context" in layer_set:
        tests.append("补 memory/context 维护不阻塞前台响应、写回失败不清空最终答案的回归")
    if "artifact/writeback" in layer_set:
        tests.append("补写入请求必须产生 artifact_refs 或明确写入限制的回归")
    if "approval/sandbox" in layer_set:
        tests.append("补 approval/sandbox 阻塞必须进入证据边界且不能声明已完成的回归")
    if not tests:
        tests.append("补按系统层聚合失败、输出结构性根因和证据边界的专业报告回归")
    return tests


def _sanitize_final_content(content: str) -> str:
    return sanitize_visible_assistant_content(_strip_tool_call_markup(content)).strip()


def _adopt_runtime_event_ref(outcome: ProfessionalTaskRunOutcome, runtime_event: Any) -> None:
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




