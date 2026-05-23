from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage

from runtime.tool_runtime.provider_tool_call_adapter import tool_calls_for_langchain_messages
from orchestration.runtime_directive import RuntimeDirective
from task_system.tasks.run_models import (
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

from ..contracts.deliverable_validator import validate_deliverable
from ..memory.evidence_packet import build_evidence_packet
from ..shared.models import RuntimeLoopState
from ..contracts.obligation_validation import validate_obligations
from .evidence_closeout import (
    _adopt_runtime_event_ref,
    _answer_metadata_from_done_event,
    _artifact_output_refs_from_observation,
    _artifact_output_refs_from_tool_payload,
    _build_artifact_delivery_auto_write_observation,
    _build_artifact_delivery_evidence_closeout_answer,
    _build_code_fix_evidence_closeout_answer,
    _build_evidence_closeout_answer,
    _build_generic_evidence_closeout_answer,
    _contains_tool_call_markup,
    _event_protocol_leak_detected,
    _evidence_packet_prompt,
    _normalize_professional_verification,
    _professional_closeout_repair_instruction,
    _runtime_event_observation_ref,
    _sanitize_final_content,
    _should_apply_artifact_delivery_evidence_closeout,
    _should_apply_code_fix_evidence_closeout,
    _should_apply_evidence_closeout,
    _should_apply_generic_evidence_closeout,
    _should_apply_protocol_leak_evidence_closeout,
    _should_auto_write_artifact_delivery_after_blocked_tool,
    _should_repair_professional_closeout,
    _strip_tool_call_markup,
    _tool_observation_payload,
)
from .goal_contract import (
    ProfessionalTaskGoalContract,
    _dedupe_strings,
    _goal_contract_from_semantic_contract,
    _semantic_control_plan,
)
from .completion_judgment import build_verification_review, judge_completion
from .run_session import build_professional_run_session
from .model_sidecars import invoke_readonly_planner_draft, invoke_readonly_verifier_review
from .plan_coverage import review_plan_coverage
from .runtime_policy import (
    _allowed_tool_names_from_policy,
    _first_finalize_step_id,
    _model_only_directive,
    _professional_runtime_policy,
    _professional_task_directive,
    _standard_action_step_id,
    _with_professional_task_instruction,
)
from .state_machine import initial_professional_run_state, unsatisfied_obligations_from_verification
from .tool_contract_gate import (
    _compact_professional_recovery_messages,
    _contract_followup_guidance,
    _contract_gate_tool_request,
    _contract_repair_instruction,
    _model_tools_for_required_next_step,
    _next_required_tools,
    _tool_call_options_for_round,
)
from ..memory.tool_observation_ledger import ToolObservationLedger, build_tool_observation_record


RuntimeEventBuilder = Callable[..., Any]
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

class ProfessionalTaskRunDriver:
    """Runtime driver for graphless interaction-mode task execution.

    The driver owns professional task control states, while TaskRunLoop still owns
    the shared event log, checkpoints, ledger, TaskResult, and commit gates.
    """

    def __init__(
        self,
        *,
        event_log: Any,
        execution_engine: Any,
        record_task_run_step_event: RuntimeEventBuilder,
        record_task_run_ledger_updated: RuntimeEventBuilder,
        state_with_task_run_ledger: StateWithLedger,
        write_checkpoint_event: Callable[..., Any],
    ) -> None:
        self.event_log = event_log
        self.execution_engine = execution_engine
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
        recipe_metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
        agent_plan_draft = dict(recipe_metadata.get("agent_plan_draft") or {})
        plan_coverage_review = dict(recipe_metadata.get("plan_coverage_review") or {})
        sidecar_policy = _professional_sidecar_policy(
            task_operation=task_operation,
            selected_recipe_payload=selected_recipe_payload,
        )
        sidecar_invoker = _sidecar_invoker(model_response_executor, enabled=bool(sidecar_policy.get("enabled") is True))
        planner_sidecar_diagnostics = {
            "sidecar_name": "readonly_planner",
            "sidecar_status": (
                "not_enabled"
                if not bool(sidecar_policy.get("enabled") is True)
                else "not_invoked_model_runtime_not_sidecar_capable"
                if sidecar_invoker is None
                else "pending"
            ),
            "model_call_performed": False,
        }
        if sidecar_invoker is not None and bool(sidecar_policy.get("planner_enabled") is True):
            planner_plan, planner_sidecar_diagnostics = await invoke_readonly_planner_draft(
                invoker=sidecar_invoker,
                task_id=task_id,
                semantic_contract=semantic_contract,
                domain_playbook=dict(dict(semantic_contract.get("diagnostics") or {}).get("task_domain_binding") or {}),
                workspace_observations=[],
                model_spec=resolved_model_spec,
            )
            if planner_plan is not None:
                candidate_plan = planner_plan.to_dict()
                candidate_coverage = review_plan_coverage(
                    task_id=task_id,
                    semantic_contract=semantic_contract,
                    agent_plan_draft=candidate_plan,
                ).to_dict()
                if candidate_coverage.get("passed") is True:
                    agent_plan_draft = candidate_plan
                    plan_coverage_review = candidate_coverage
                    plan = _control_plan_from_agent_plan_draft(
                        agent_plan_draft=agent_plan_draft,
                        fallback_plan=plan,
                    )
                else:
                    planner_sidecar_diagnostics = {
                        **dict(planner_sidecar_diagnostics or {}),
                        "model_plan_rejected_by_coverage_gate": True,
                        "candidate_plan_coverage_review": candidate_coverage,
                    }
        elif sidecar_invoker is not None:
            planner_sidecar_diagnostics = {
                **planner_sidecar_diagnostics,
                "sidecar_status": "not_enabled",
            }
        planner_event = self.event_log.append(
            task_run_id,
            "professional_task_readonly_planner_checked",
            payload={
                "interaction_mode": interaction_mode,
                "sidecar_policy": sidecar_policy,
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "planner_sidecar_diagnostics": planner_sidecar_diagnostics,
                "plan_item_count": len(plan),
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": planner_event.to_dict()}
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
                "plan_source": (
                    "model_agent_plan_draft"
                    if str(agent_plan_draft.get("source") or "") == "model_agent_plan_draft"
                    else "semantic_task_contract"
                ),
                "agent_plan_draft": agent_plan_draft,
                "plan_coverage_review": plan_coverage_review,
                "planner_sidecar_diagnostics": planner_sidecar_diagnostics,
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
            async for event in self.execution_engine.stream_raw_model_events(
                user_message=user_message,
                model_response_executor=model_response_executor,
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
                runtime_events = await self.execution_engine.translate_event(
                    task_run_id=task_run_id,
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
            async for event in self.execution_engine.stream_raw_model_events(
                user_message=user_message,
                model_response_executor=model_response_executor,
                model_messages=closeout_messages,
                directive=_model_only_directive(safe_directive, mode=interaction_mode),
                tool_instances=[],
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                if _event_protocol_leak_detected(event):
                    closeout_protocol_leak_detected = True
                runtime_events = await self.execution_engine.translate_event(
                    task_run_id=task_run_id,
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
        verification_review = build_verification_review(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            deliverable_validation=deliverable_validation,
            obligation_validation=obligation_validation,
        )
        completion_judgment = judge_completion(
            task_run_id=task_run_id,
            semantic_contract=semantic_contract,
            evidence_packet=evidence_packet.to_dict(),
            verification_review=verification_review,
            terminal_reason=outcome.terminal_reason,
        )
        verification["verification_review"] = verification_review.to_dict()
        verification["completion_judgment"] = completion_judgment.to_dict()
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
            async for event in self.execution_engine.stream_raw_model_events(
                user_message=user_message,
                model_response_executor=model_response_executor,
                model_messages=repair_messages,
                directive=_model_only_directive(safe_directive, mode=interaction_mode),
                tool_instances=[],
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                runtime_events = await self.execution_engine.translate_event(
                    task_run_id=task_run_id,
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
            verification_review = build_verification_review(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                deliverable_validation=deliverable_validation,
                obligation_validation=obligation_validation,
            )
            verifier_sidecar_diagnostics = {
                "sidecar_name": "readonly_verifier",
                "sidecar_status": (
                    "not_enabled"
                    if not bool(sidecar_policy.get("enabled") is True) or not bool(sidecar_policy.get("verifier_enabled") is True)
                    else "not_invoked_model_runtime_not_sidecar_capable"
                    if sidecar_invoker is None
                    else "pending"
                ),
                "model_call_performed": False,
            }
            if sidecar_invoker is not None and bool(sidecar_policy.get("verifier_enabled") is True):
                model_verification_review, verifier_sidecar_diagnostics = await invoke_readonly_verifier_review(
                    invoker=sidecar_invoker,
                    task_run_id=task_run_id,
                    semantic_contract=semantic_contract,
                    evidence_packet=evidence_packet.to_dict(),
                    agent_plan_draft=agent_plan_draft,
                    deliverable_validation=deliverable_validation,
                    obligation_validation=obligation_validation,
                    model_spec=resolved_model_spec,
                )
                if model_verification_review is not None:
                    verification_review = model_verification_review
            completion_judgment = judge_completion(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                verification_review=verification_review,
                terminal_reason=outcome.terminal_reason,
            )
            verification["verification_review"] = verification_review.to_dict()
            verification["completion_judgment"] = completion_judgment.to_dict()
            verification["verifier_sidecar_diagnostics"] = verifier_sidecar_diagnostics
        if outcome.terminal_reason in {"completed", "tool_loop_budget_exceeded"} and not bool(verification.get("passed") is True):
            outcome.terminal_reason = "partial_contract_failed"
            completion_judgment = judge_completion(
                task_run_id=task_run_id,
                semantic_contract=semantic_contract,
                evidence_packet=evidence_packet.to_dict(),
                verification_review=verification.get("verification_review"),
                terminal_reason=outcome.terminal_reason,
            )
            verification["completion_judgment"] = completion_judgment.to_dict()
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
        outcome.final_answer_metadata = {
            **dict(outcome.final_answer_metadata or {}),
            "verification_review": dict(verification.get("verification_review") or {}),
            "completion_judgment": dict(verification.get("completion_judgment") or {}),
            "verifier_sidecar_diagnostics": dict(verification.get("verifier_sidecar_diagnostics") or {}),
        }
        verify_event = self.event_log.append(
            task_run_id,
            "professional_task_deliverable_validation_checked",
            payload={"verification": verification},
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.validate_deliverable"},
        )
        yield {"type": "runtime_loop_event", "event": verify_event.to_dict()}
        completion_judgment_event = self.event_log.append(
            task_run_id,
            "professional_task_completion_judged",
            payload={
                "completion_judgment": dict(verification.get("completion_judgment") or {}),
                "verification_review": dict(verification.get("verification_review") or {}),
                "verifier_sidecar_diagnostics": dict(verification.get("verifier_sidecar_diagnostics") or {}),
            },
            refs={"task_contract_ref": task_contract_ref, "task_step_ref": "professional.completion_judgment"},
        )
        yield {"type": "runtime_loop_event", "event": completion_judgment_event.to_dict()}
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


def _professional_sidecar_policy(
    *,
    task_operation: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
) -> dict[str, Any]:
    current_turn = dict(task_operation.get("current_turn_context") or {})
    recipe_metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    mode_policy = dict(recipe_metadata.get("mode_policy") or {})
    raw_policy = {
        **dict(mode_policy.get("model_sidecar_policy") or {}),
        **dict(recipe_metadata.get("model_sidecar_policy") or {}),
        **dict(current_turn.get("model_sidecar_policy") or {}),
    }
    enabled = _enabled_flag(raw_policy, "enabled", default=False)
    planner_enabled = enabled and _enabled_flag(raw_policy, "planner_enabled", default=True)
    verifier_enabled = enabled and _enabled_flag(raw_policy, "verifier_enabled", default=True)
    return {
        "enabled": enabled,
        "planner_enabled": planner_enabled,
        "verifier_enabled": verifier_enabled,
        "policy_source": str(raw_policy.get("authority") or "runtime.model_sidecar_policy"),
        "readonly": True,
    }


def _enabled_flag(policy: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in policy:
        return default
    value = policy.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value is True)


def _sidecar_invoker(model_response_executor: Any, *, enabled: bool) -> Any | None:
    if not enabled:
        return None
    model_runtime = getattr(model_response_executor, "model_runtime", None)
    if getattr(model_runtime, "supports_structured_sidecars", False) is not True:
        return None
    invoker = getattr(model_runtime, "invoke_messages", None)
    return invoker if callable(invoker) else None


def _control_plan_from_agent_plan_draft(
    *,
    agent_plan_draft: dict[str, Any],
    fallback_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps = [dict(item) for item in list(agent_plan_draft.get("steps") or []) if isinstance(item, dict)]
    converted: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("step_id") or f"model_plan_step_{index}").strip()
        converted.append(
            {
                "plan_item_id": f"professional.model_plan.{step_id}",
                "title": str(step.get("title") or step_id).strip() or step_id,
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": str(step.get("purpose") or step.get("title") or step_id).strip(),
                "required_operations": list(step.get("required_operations") or ["op.model_response"]),
                "expected_outputs": list(step.get("expected_outputs") or []),
                "evidence_expectations": list(step.get("evidence_expectations") or []),
                "contract_refs": list(step.get("contract_refs") or []),
                "contract_required": True,
            }
        )
    if not converted:
        return list(fallback_plan or [])
    if not any("validate" in str(item.get("plan_item_id") or "") for item in converted):
        converted.append(
            {
                "plan_item_id": "professional.validate_deliverable",
                "title": "按交付物验证最终回答",
                "step_kind": "plan_item",
                "executor_type": "model",
                "action_kind": "main_agent",
                "summary": "检查语义交付物、证据对齐、协议泄漏和未支持声明。",
                "required_operations": ["op.model_response"],
                "contract_required": True,
            }
        )
    return converted














































