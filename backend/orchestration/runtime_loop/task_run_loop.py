from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage

from operations import OperationGate, OperationGatePipelineContext, build_default_operation_registry
from output_boundary.boundary import AssistantOutputBoundary
from tasks.run_models import (
    TaskRunLedger,
    TaskStepRun,
    advance_task_run_ledger,
    build_task_run_ledger,
    complete_task_run_step,
    current_task_step_run,
    fail_task_run_step,
    find_task_step_run,
    next_pending_step_run,
    project_task_result_from_ledger,
    skip_task_run_step,
    start_task_run_step,
    step_supports_operation,
    task_run_step_count,
    task_run_terminal_status,
    terminalize_task_run_ledger,
)
from tasks.spec_models import TaskSpec
from tasks.step_models import StepInputBinding, TaskStepBlueprint
from tasks.template_models import TaskTemplate, TaskValidationRule
from tools.authorization import resolve_tool_operation_id

from context_management.projection import (
    ContextProjection,
    projection_from_bound_answer,
    projection_from_bundle_answer,
    projection_from_file_work,
)
from ..commit_gate import build_assistant_session_message_commit_decision, build_task_run_final_commit_decision
from .action_request import (
    build_executor_error_observation,
    build_model_response_observation,
    build_tool_action_request,
    build_tool_result_observation,
)
from .checkpoint import RuntimeCheckpoint, RuntimeCheckpointStore
from .context_manager import RuntimeContextManager
from .execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
    build_execution_receipt,
    build_idempotency_token,
    build_request_fingerprint,
    derive_replay_policy,
)
from .event_log import RuntimeEventLog
from .loop_control import RuntimeLoopLimits, check_runtime_loop_control
from .model_adoption import build_model_response_runtime_adoption
from .models import RuntimeLoopState, TaskRun
from .observation_aggregator import ObservationAggregation, ObservationAggregator
from .safety import build_task_safety_validators
from .stage_projection import StageProjectionCycle
from .state_index import RuntimeStateIndex
from .trace_reader import RuntimeLoopTraceReader
from .tool_adoption import build_tool_request_runtime_adoption
from .tool_repetition_guard import ToolRepetitionGuard


@dataclass(frozen=True, slots=True)
class TaskRunLoopStartResult:
    task_run: TaskRun
    loop_state: RuntimeLoopState
    checkpoint: RuntimeCheckpoint
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run": self.task_run.to_dict(),
            "loop_state": self.loop_state.to_dict(),
            "checkpoint": self.checkpoint.to_dict(),
            "events": [dict(item) for item in self.events],
        }


class TaskRunLoop:
    """Single-agent loop owner.

    This first slice only creates the durable loop trace. Model/tool execution
    will be connected one system at a time after this event/checkpoint spine is
    stable.
    """

    def __init__(
        self,
        root_dir: Path,
        *,
        operation_gate: OperationGate | None = None,
        limits: RuntimeLoopLimits | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.event_log = RuntimeEventLog(self.root_dir)
        self.checkpoints = RuntimeCheckpointStore(self.root_dir)
        self.execution_store = RuntimeExecutionStore(self.root_dir)
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.trace_reader = RuntimeLoopTraceReader(self.state_index, self.event_log, self.checkpoints)
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()

    @staticmethod
    def _apply_observation_aggregation(
        aggregation: ObservationAggregation,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        return (
            dict(aggregation.projection.main_context),
            [dict(item) for item in aggregation.projection.task_summary_refs],
            [dict(item) for item in aggregation.projection.bundle_summary_refs],
        )

    def list_session_traces(self, session_id: str) -> dict[str, Any]:
        return self.trace_reader.list_session_task_runs(session_id)

    def get_trace(
        self,
        task_run_id: str,
        *,
        include_payloads: bool = False,
        include_model_messages: bool = False,
    ) -> dict[str, Any] | None:
        return self.trace_reader.get_task_run_trace(
            task_run_id,
            include_payloads=include_payloads,
            include_model_messages=include_model_messages,
        )

    def start(
        self,
        *,
        session_id: str,
        task_id: str,
        task_contract_ref: str = "",
        agent_id: str = "agent:0",
        agent_profile_id: str = "main_interactive_agent",
        runtime_lane: str = "full_interactive",
        task_agent_binding_ref: str = "",
        skill_workflow_ref: str = "",
        health_issue_ref: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> TaskRunLoopStartResult:
        now = time.time()
        task_run_id = f"taskrun:{session_id}:{task_id}:{uuid.uuid4().hex[:8]}"
        started = self.event_log.append(
            task_run_id,
            "task_run_started",
            payload={
                "session_id": session_id,
                "task_id": task_id,
                "task_contract_ref": task_contract_ref,
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_lane": runtime_lane,
                "task_agent_binding_ref": task_agent_binding_ref,
                "skill_workflow_ref": skill_workflow_ref,
                "health_issue_ref": health_issue_ref,
                "single_agent": True,
                "multi_agent_enabled": False,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        iteration = self.event_log.append(
            task_run_id,
            "loop_iteration_started",
            payload={
                "transition": "start",
                "turn_count": 0,
                "step_count": 0,
            },
        )
        state = RuntimeLoopState(
            task_run_id=task_run_id,
            status="running",
            transition="start",
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            runtime_lane=runtime_lane,
            task_agent_binding_ref=task_agent_binding_ref,
            task_template_id="",
            task_spec_ref="",
            task_result_ref="",
            skill_workflow_ref=skill_workflow_ref,
            health_issue_ref=health_issue_ref,
            diagnostics={
                "loop_owner": "OrchestrationSystem.TaskRunLoop",
                "loop_phase": "event_checkpoint_spine",
                "query_runtime_role": "adapter_only",
                "loop_limits": self.limits.to_dict(),
                **dict(diagnostics or {}),
            },
        )
        checkpoint = self.checkpoints.write(
            state,
            event_offset=iteration.offset,
            execution_refs=(),
            execution_state_ref="",
            execution_summary=self.execution_store.build_summary(task_run_id),
        )
        checkpoint_event = self.event_log.append(
            task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "execution_summary": checkpoint.execution_summary,
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )
        task_run = TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=task_id,
            task_contract_ref=task_contract_ref,
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            runtime_lane=runtime_lane,
            status="running",
            created_at=now,
            updated_at=time.time(),
            latest_event_offset=checkpoint_event.offset,
            latest_checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={
                "loop_owner": "OrchestrationSystem.TaskRunLoop",
                "single_agent": True,
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_lane": runtime_lane,
                "task_agent_binding_ref": task_agent_binding_ref,
                "skill_workflow_ref": skill_workflow_ref,
                "health_issue_ref": health_issue_ref,
                "multi_agent_enabled": False,
                "loop_limits": self.limits.to_dict(),
                **dict(diagnostics or {}),
            },
        )
        self.state_index.upsert_task_run(task_run)
        return TaskRunLoopStartResult(
            task_run=task_run,
            loop_state=state,
            checkpoint=checkpoint,
            events=(started.to_dict(), iteration.to_dict(), checkpoint_event.to_dict()),
        )

    async def run_single_agent_stream(
        self,
        *,
        session_id: str,
        task_id: str,
        user_message: str,
        history: list[dict[str, Any]],
        source: str,
        agent_runtime_chain: Any,
        model_response_executor: Any,
        runtime_context_manager: RuntimeContextManager,
        stage_projection_cycle: StageProjectionCycle | None = None,
        memory_intent: Any | None = None,
        task_selection: dict[str, Any] | None = None,
        assistant_message_committer: Callable[[dict[str, Any]], Any] | None = None,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
        agent_runtime_profile: Any | None = None,
    ):
        """Run the current single-agent lane inside the TaskRunLoop trace spine."""

        start = self.start(
            session_id=session_id,
            task_id=task_id,
            diagnostics={"runtime_channel": "single_agent_runtime"},
        )
        state = start.loop_state
        yield {
            "type": "runtime_loop_started",
            "task_run": start.task_run.to_dict(),
            "checkpoint": start.checkpoint.to_dict(),
            "events": [dict(item) for item in start.events],
        }
        for event in start.events:
            yield {"type": "runtime_loop_event", "event": dict(event)}

        chain_runtime = agent_runtime_chain.build_runtime(
            session_id=session_id,
            task_id=task_id,
            message=user_message,
            source=source,
            task_selection=dict(task_selection or {}),
        )
        task_operation = dict(chain_runtime.get("task_operation") or {})
        task_contract = dict(task_operation.get("task_contract") or {})
        task_intent_contract = dict(task_operation.get("task_intent_contract") or {})
        template_match = dict(task_operation.get("template_match") or {})
        selected_template_payload = dict(task_operation.get("selected_template") or {})
        bundle_spec_payload = dict(task_operation.get("bundle_spec") or {})
        task_spec_payload = dict(task_operation.get("task_spec") or {})
        task_execution_assembly_payload = dict(task_operation.get("task_execution_assembly") or {})
        task_projection_binding_payload = dict(task_operation.get("task_projection_binding") or {})
        task_flow_contract_binding_payload = dict(task_operation.get("task_flow_contract_binding") or {})
        task_agent_adoption_plan_payload = dict(task_operation.get("task_agent_adoption_plan") or {})
        task_memory_request_profile_payload = dict(task_operation.get("task_memory_request_profile") or {})
        task_communication_protocol_payload = dict(task_operation.get("task_communication_protocol") or {})
        coordination_task_payload = dict(task_operation.get("coordination_task_record") or {})
        memory_view = dict(chain_runtime.get("memory_runtime_view") or {})
        context_policy = dict(chain_runtime.get("context_policy_result") or {})

        task_contract_ref = str(task_contract.get("task_id") or task_id)
        runtime_task_ledger = _build_initial_task_run_ledger(
            task_run_id=state.task_run_id,
            task_contract_ref=task_contract_ref,
            task_spec_payload=task_spec_payload,
            selected_template_payload=selected_template_payload,
        )
        if runtime_task_ledger is not None:
            runtime_task_ledger = start_task_run_step(
                runtime_task_ledger,
                started_at=time.time(),
                diagnostics={"transition_reason": "task_contract_built"},
            )
        task_event = self.event_log.append(
            state.task_run_id,
            "task_contract_built",
            payload={
                "task_contract": task_contract,
                "task_intent_contract": task_intent_contract,
                "template_match": template_match,
                "selected_template": selected_template_payload,
                "bundle_spec": bundle_spec_payload,
                "task_spec": task_spec_payload,
                "task_execution_assembly": task_execution_assembly_payload,
                "task_projection_binding": task_projection_binding_payload,
                "task_flow_contract_binding": task_flow_contract_binding_payload,
                "task_agent_adoption_plan": task_agent_adoption_plan_payload,
                "task_memory_request_profile": task_memory_request_profile_payload,
                "task_communication_protocol": task_communication_protocol_payload,
                "coordination_task_record": coordination_task_payload,
                "task_run_ledger": runtime_task_ledger.to_dict() if runtime_task_ledger is not None else {},
                "source": source,
            },
            refs={
                "task_contract_ref": task_contract_ref,
                "task_intent_ref": str(task_intent_contract.get("task_intent_id") or ""),
                "template_match_ref": str(template_match.get("match_id") or ""),
                "task_template_id": str(selected_template_payload.get("template_id") or ""),
                "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
                "task_execution_assembly_ref": str(task_execution_assembly_payload.get("assembly_id") or ""),
                "task_projection_binding_ref": str(task_projection_binding_payload.get("binding_id") or ""),
                "task_flow_contract_binding_ref": str(task_flow_contract_binding_payload.get("binding_id") or ""),
                "task_agent_adoption_plan_ref": str(task_agent_adoption_plan_payload.get("plan_id") or ""),
                "task_memory_request_profile_ref": str(task_memory_request_profile_payload.get("profile_id") or ""),
                "task_communication_protocol_ref": str(task_communication_protocol_payload.get("protocol_id") or ""),
                "coordination_task_ref": str(coordination_task_payload.get("coordination_task_id") or ""),
                "bundle_spec_ref": str(bundle_spec_payload.get("bundle_id") or ""),
                "task_run_ledger_ref": runtime_task_ledger.ledger_id if runtime_task_ledger is not None else "",
            },
        )
        yield {"type": "runtime_loop_event", "event": task_event.to_dict()}
        if runtime_task_ledger is not None:
            current_step = current_task_step_run(runtime_task_ledger)
            if current_step is not None:
                step_event = self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=current_step,
                    ledger=runtime_task_ledger,
                    reason="task_contract_built",
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
                ledger_event = self._record_task_run_ledger_updated(
                    state.task_run_id,
                    ledger=runtime_task_ledger,
                    reason="task_contract_built",
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
        current_turn_context = dict(task_operation.get("current_turn_context") or {})
        if current_turn_context:
            current_turn_event = self.event_log.append(
                state.task_run_id,
                "current_turn_context_resolved",
                payload={
                    "current_turn_context": current_turn_context,
                    "execution_mode": str(current_turn_context.get("execution_mode") or ""),
                    "bundle_id": str(current_turn_context.get("bundle_id") or ""),
                    "bundle_item_count": len(list(current_turn_context.get("bundle_items") or [])),
                    "followup_target_count": len(list(current_turn_context.get("followup_target_refs") or [])),
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": current_turn_event.to_dict()}
        memory_event = self.event_log.append(
            state.task_run_id,
            "memory_runtime_view_built",
            payload={
                "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
                "conversation_candidate_count": _diagnostic_int(memory_view, "conversation_candidate_count"),
                "state_candidate_count": _diagnostic_int(memory_view, "state_candidate_count"),
                "long_term_candidate_count": _diagnostic_int(memory_view, "long_term_candidate_count"),
            },
            refs={"memory_runtime_view_ref": str(memory_view.get("view_id") or "")},
        )
        yield {"type": "runtime_loop_event", "event": memory_event.to_dict()}
        projection_cycle = stage_projection_cycle or StageProjectionCycle()
        stage_projection = projection_cycle.build_from_task_operation(
            task_operation,
        )
        projection_event = self.event_log.append(
            state.task_run_id,
            "stage_projection_built",
            payload={"stage_projection": stage_projection.to_dict()},
            refs={
                "projection_ref": stage_projection.projection_ref,
                "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
            },
        )
        yield {"type": "runtime_loop_event", "event": projection_event.to_dict()}

        context_snapshot = runtime_context_manager.prepare_model_context(
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            history=history,
            memory_intent=memory_intent,
            memory_runtime_view=memory_view,
            context_policy_result=context_policy,
            stage_projection_snapshot=stage_projection,
        )
        context_event = self.event_log.append(
            state.task_run_id,
            "context_snapshot_built",
            payload={
                "context_snapshot": context_snapshot.to_dict(),
                "context_policy_result": context_policy,
            },
            refs={
                "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
                "context_snapshot_ref": context_snapshot.snapshot_id,
                "context_policy_ref": context_snapshot.context_policy_ref,
                "projection_ref": stage_projection.projection_ref,
                "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
            },
        )
        yield {"type": "runtime_loop_event", "event": context_event.to_dict()}
        invariant_report = runtime_context_manager.check_invariants(context_snapshot)
        invariant_event = self.event_log.append(
            state.task_run_id,
            "context_invariant_checked",
            payload={"invariant_report": invariant_report.to_dict()},
            refs={
                "context_snapshot_ref": context_snapshot.snapshot_id,
                "invariant_report_ref": invariant_report.report_id,
            },
        )
        yield {"type": "runtime_loop_event", "event": invariant_event.to_dict()}
        yield {"type": "runtime_context_invariant", "report": invariant_report.to_dict()}

        state = RuntimeLoopState(
            task_run_id=state.task_run_id,
            status="running",
            transition="start",
            turn_count=1,
            step_count=task_run_step_count(runtime_task_ledger),
            current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else "",
            agent_id=state.agent_id,
            agent_profile_id=state.agent_profile_id,
            runtime_lane=state.runtime_lane,
            task_agent_binding_ref=state.task_agent_binding_ref,
            task_template_id=str(selected_template_payload.get("template_id") or ""),
            task_spec_ref=str(task_spec_payload.get("task_spec_ref") or ""),
            task_result_ref="",
            skill_workflow_ref=state.skill_workflow_ref,
            health_issue_ref=state.health_issue_ref,
            memory_state_ref=str(memory_view.get("view_id") or ""),
            context_snapshot_ref=context_snapshot.snapshot_id,
            projection_ref=stage_projection.projection_ref,
            prompt_manifest_ref=stage_projection.prompt_manifest_ref,
            token_pressure=dict(context_snapshot.token_pressure),
            diagnostics={
                **dict(state.diagnostics),
                "task_contract_ref": task_contract_ref,
                "runtime_chain_built": True,
                "runtime_context_manager_applied": True,
                "stage_projection_cycle_applied": True,
                "context_invariant_checked": True,
                "context_needs_compaction": invariant_report.needs_compaction,
                "task_template_id": str(selected_template_payload.get("template_id") or ""),
                "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
            },
        )
        checkpoint = self._write_checkpoint_event(state, event_offset=invariant_event.offset)
        yield {"type": "runtime_loop_event", "event": checkpoint.to_dict()}

        control_decision = check_runtime_loop_control(
            state,
            limits=self.limits,
            started_at=start.task_run.created_at,
            model_call_count=0,
            event_count=len(self.event_log.list_events(state.task_run_id)),
        )
        control_event = self.event_log.append(
            state.task_run_id,
            "loop_control_checked",
            payload={"control": control_decision.to_dict()},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": control_event.to_dict()}
        yield {"type": "runtime_loop_control", "control": control_decision.to_dict()}
        if not control_decision.allowed:
            yield {
                "type": "error",
                "error": control_decision.reason,
                "content": control_decision.message or "RuntimeLoop 控制策略终止了本轮任务。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "runtime_loop_control",
            }
            if runtime_task_ledger is not None and current_task_step_run(runtime_task_ledger) is not None:
                active_step = current_task_step_run(runtime_task_ledger)
                runtime_task_ledger = fail_task_run_step(
                    runtime_task_ledger,
                    step_id=active_step.step_id if active_step is not None else None,
                    completed_at=time.time(),
                    failure_reason=control_decision.reason,
                    diagnostics={"transition_reason": "runtime_loop_control"},
                )
                failed_step = current_task_step_run(runtime_task_ledger)
                if failed_step is not None:
                    step_failed_event = self._record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_failed",
                        step_run=failed_step,
                        ledger=runtime_task_ledger,
                        reason="runtime_loop_control",
                    )
                    yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                ledger_event = self._record_task_run_ledger_updated(
                    state.task_run_id,
                    ledger=runtime_task_ledger,
                    reason="runtime_loop_control",
                    diagnostics={"terminal_reason": control_decision.reason},
                )
                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                state = self._state_with_task_run_ledger(
                    state,
                    runtime_task_ledger,
                    diagnostics={"last_step_transition": "runtime_loop_control"},
                )
                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
            terminal_state = state.with_status(
                "failed",
                transition="stop_after_final_output",
                terminal_reason=control_decision.reason,
                diagnostics={"runtime_loop_control": control_decision.to_dict()},
            )
            terminal_event = self.event_log.append(
                terminal_state.task_run_id,
                "loop_terminal",
                payload={
                    "terminal_reason": terminal_state.terminal_reason,
                    "status": terminal_state.status,
                    "runtime_loop_control": control_decision.to_dict(),
                },
            )
            yield {"type": "runtime_loop_event", "event": terminal_event.to_dict()}
            checkpoint_event = self._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
            self._upsert_finished_task_run(
                start_task_run=start.task_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                diagnostics={"runtime_loop_control_reason": control_decision.reason},
            )
            return

        directive, resource_policy = build_model_response_runtime_adoption(
            task_operation,
            operation_registry=self.operation_gate.registry,
            agent_runtime_profile=agent_runtime_profile,
        )
        task_safety_envelope = dict(dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}).get(
            "safety_envelope",
            {},
        )
        task_safety_validators = build_task_safety_validators(
            root_dir=self.root_dir,
            safety_envelope=task_safety_envelope,
        )
        runtime_tool_instances = self._tool_instances_for_resource_policy(tool_instances, resource_policy)
        directive_event = self.event_log.append(
            state.task_run_id,
            "runtime_directive_issued",
            payload={
                "directive": directive.to_dict(),
                "resource_policy": resource_policy.to_dict(),
            },
            refs={
                "directive_ref": directive.directive_id,
                "resource_policy_ref": resource_policy.policy_id,
            },
        )
        yield {"type": "runtime_loop_event", "event": directive_event.to_dict()}
        yield {
            "type": "runtime_directive",
            "directive": directive.to_dict(),
            "resource_policy": resource_policy.to_dict(),
        }
        gate_result = self.operation_gate.check(
            "op.model_response",
            resource_policy=resource_policy,
            directive_ref=directive.directive_id,
            context=OperationGatePipelineContext(
                operation_input={"operation_id": "op.model_response"},
                validators=task_safety_validators,
            ),
        )
        gate_event = self.event_log.append(
            state.task_run_id,
            "operation_gate_checked",
            payload={"gate": gate_result.to_dict()},
            refs={
                "operation_id": gate_result.operation_id,
                "directive_ref": directive.directive_id,
            },
        )
        yield {"type": "runtime_loop_event", "event": gate_event.to_dict()}
        yield {"type": "operation_gate", "gate": gate_result.to_dict()}
        if not gate_result.allowed:
            error_event = {
                "type": "error",
                "error": gate_result.reason,
                "content": "OperationGate 未放行模型回答，本轮停止执行。",
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "operation_gate",
            }
            yield error_event
            if runtime_task_ledger is not None and current_task_step_run(runtime_task_ledger) is not None:
                active_step = current_task_step_run(runtime_task_ledger)
                runtime_task_ledger = fail_task_run_step(
                    runtime_task_ledger,
                    step_id=active_step.step_id if active_step is not None else None,
                    completed_at=time.time(),
                    failure_reason="blocked_by_gate",
                    diagnostics={"transition_reason": "operation_gate", "operation_id": gate_result.operation_id},
                )
                failed_step = current_task_step_run(runtime_task_ledger)
                if failed_step is not None:
                    step_failed_event = self._record_task_run_step_event(
                        state.task_run_id,
                        event_type="step_failed",
                        step_run=failed_step,
                        ledger=runtime_task_ledger,
                        reason="operation_gate",
                        refs={"operation_id": gate_result.operation_id},
                    )
                    yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                ledger_event = self._record_task_run_ledger_updated(
                    state.task_run_id,
                    ledger=runtime_task_ledger,
                    reason="operation_gate",
                    refs={"operation_id": gate_result.operation_id},
                    diagnostics={"terminal_reason": "blocked_by_gate"},
                )
                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                state = self._state_with_task_run_ledger(
                    state,
                    runtime_task_ledger,
                    diagnostics={"last_step_transition": "operation_gate"},
                )
                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
            terminal_state = state.with_status(
                "blocked",
                transition="stop_after_final_output",
                terminal_reason="blocked_by_gate",
                diagnostics={"operation_gate_reason": gate_result.reason},
            )
            terminal_event = self.event_log.append(
                terminal_state.task_run_id,
                "loop_terminal",
                payload={
                    "terminal_reason": terminal_state.terminal_reason,
                    "status": terminal_state.status,
                    "operation_gate_reason": gate_result.reason,
                },
            )
            yield {"type": "runtime_loop_event", "event": terminal_event.to_dict()}
            checkpoint_event = self._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
            self._upsert_finished_task_run(
                start_task_run=start.task_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                diagnostics={"operation_gate_reason": gate_result.reason},
            )
            return

        executor_event = self.event_log.append(
            state.task_run_id,
            "executor_started",
            payload={"executor_type": "model", "runtime_channel": "single_agent_runtime"},
            refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
        )
        yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}

        final_content = ""
        final_answer_metadata: dict[str, Any] = {}
        terminal_reason = "completed"
        result_refs: list[str] = []
        final_main_context: dict[str, Any] = {}
        final_task_summary_refs: list[dict[str, Any]] = []
        final_bundle_summary_refs: list[dict[str, Any]] = []
        observation_aggregator = ObservationAggregator()
        current_bundle_items = _bundle_items_from_runtime_contract(
            task_spec_payload=task_spec_payload,
        )
        pending_tool_calls: list[dict[str, Any]] = []
        assistant_tool_call_content = ""
        assistant_tool_call_kwargs: dict[str, Any] = {}
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        executed_bundle_ordinals: list[int] = []
        tool_repetition_guard = ToolRepetitionGuard()
        repeated_tool_halt = False
        direct_tool_finalized = False
        async for event in model_response_executor.stream(
            user_message=user_message,
            model_messages=list(context_snapshot.model_messages),
            directive=directive,
            tool_instances=runtime_tool_instances,
        ):
            if event.get("type") == "tool_call_requested":
                tool_call = dict(event.get("tool_call") or {})
                if tool_call:
                    pending_tool_calls.append(tool_call)
                assistant_tool_call_content = str(event.get("assistant_content") or assistant_tool_call_content)
                event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                if event_kwargs:
                    assistant_tool_call_kwargs.update(event_kwargs)
            runtime_events = await self._events_from_executor_event(
                state.task_run_id,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=resource_policy,
                current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
                runtime_context_manager=runtime_context_manager,
                tool_runtime_executor=tool_runtime_executor,
                event=event,
            )
            for runtime_event in runtime_events:
                if runtime_event.event_type == "tool_call_requested":
                    operation_id = str(runtime_event.refs.get("operation_id") or "")
                    current_step = current_task_step_run(runtime_task_ledger)
                    next_step = next_pending_step_run(
                        runtime_task_ledger,
                        start_after_step_id=current_step.step_id if current_step is not None else "",
                    )
                    if (
                        runtime_task_ledger is not None
                        and current_step is not None
                        and current_step.status == "running"
                        and current_step.executor_type == "model"
                        and current_step.step_kind == "understand"
                        and next_step is not None
                    ):
                        runtime_task_ledger = complete_task_run_step(
                            runtime_task_ledger,
                            step_id=current_step.step_id,
                            completed_at=time.time(),
                            output_refs=(str(runtime_event.refs.get("action_request_ref") or runtime_event.event_id),),
                            executor_ref=operation_id or current_step.executor_ref,
                            diagnostics={
                                "transition_reason": "tool_call_requested",
                                "operation_id": operation_id,
                            },
                        )
                        completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                        if completed_step is not None:
                            step_completed_event = self._record_task_run_step_event(
                                state.task_run_id,
                                event_type="step_completed",
                                step_run=completed_step,
                                ledger=runtime_task_ledger,
                                reason="tool_call_requested",
                                refs={"operation_id": operation_id},
                            )
                            yield {"type": "runtime_loop_event", "event": step_completed_event.to_dict()}
                        runtime_task_ledger = advance_task_run_ledger(
                            runtime_task_ledger,
                            started_at=time.time(),
                            diagnostics={
                                "transition_reason": "tool_call_requested",
                                "operation_id": operation_id,
                            },
                        )
                        entered_step = current_task_step_run(runtime_task_ledger)
                        ledger_event = self._record_task_run_ledger_updated(
                            state.task_run_id,
                            ledger=runtime_task_ledger,
                            reason="tool_call_requested",
                            refs={"operation_id": operation_id},
                        )
                        yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                        if entered_step is not None and entered_step.step_id != current_step.step_id:
                            step_entered_event = self._record_task_run_step_event(
                                state.task_run_id,
                                event_type="step_entered",
                                step_run=entered_step,
                                ledger=runtime_task_ledger,
                                reason="tool_call_requested",
                                refs={"operation_id": operation_id},
                            )
                            yield {"type": "runtime_loop_event", "event": step_entered_event.to_dict()}
                        state = self._state_with_task_run_ledger(
                            state,
                            runtime_task_ledger,
                            result_refs=result_refs,
                            diagnostics={"last_step_transition": "tool_call_requested"},
                        )
                        checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                elif runtime_event.event_type == "executor_observation_received":
                    observation_ref = str(runtime_event.refs.get("observation_ref") or runtime_event.event_id)
                    result_refs.append(observation_ref)
                    observation = dict(runtime_event.payload.get("observation") or {})
                    if observation.get("observation_type") == "tool_result":
                        tool_observation_count += 1
                        observation_payload = dict(observation.get("payload") or {})
                        matched_ordinal = _match_bundle_ordinal_for_tool_observation(
                            bundle_items=current_bundle_items,
                            tool_name=str(observation_payload.get("tool_name") or ""),
                            tool_args=dict(observation_payload.get("tool_args") or {}),
                            executed_ordinals=executed_bundle_ordinals,
                        )
                        if matched_ordinal > 0 and matched_ordinal not in executed_bundle_ordinals:
                            executed_bundle_ordinals.append(matched_ordinal)
                        projected_main_context, projected_task_summary_refs = _project_file_work_context_from_tool_observation(
                            observation_payload
                        )
                        if projected_main_context or projected_task_summary_refs:
                            projection = projection_from_file_work(
                                projected_main_context,
                                projected_task_summary_refs,
                                bundle_items=current_bundle_items,
                            )
                            aggregation = observation_aggregator.add_projection(
                                projection,
                                tool_name=str(observation_payload.get("tool_name") or ""),
                            )
                            (
                                final_main_context,
                                final_task_summary_refs,
                                final_bundle_summary_refs,
                            ) = self._apply_observation_aggregation(aggregation)
                        repeated_tool_halt = repeated_tool_halt or tool_repetition_guard.record(
                            str(observation_payload.get("tool_name") or ""),
                            dict(observation_payload.get("tool_args") or {}),
                        )
                        tool_messages.append(
                            ToolMessage(
                                content=str(observation_payload.get("result") or ""),
                                tool_call_id=str(observation_payload.get("tool_call_id") or observation_ref),
                            )
                        )
                        direct_tool_answer_metadata = _direct_tool_answer_from_observation(
                            user_message=user_message,
                            observation_payload=observation_payload,
                        )
                        if direct_tool_answer_metadata is not None:
                            final_content = direct_tool_answer_metadata["content"]
                            final_answer_metadata = {
                                "answer_channel": direct_tool_answer_metadata["answer_channel"],
                                "answer_source": direct_tool_answer_metadata["answer_source"],
                                "answer_canonical_state": direct_tool_answer_metadata["answer_canonical_state"],
                                "answer_persist_policy": direct_tool_answer_metadata["answer_persist_policy"],
                                "answer_finalization_policy": direct_tool_answer_metadata["answer_finalization_policy"],
                                "answer_fallback_reason": direct_tool_answer_metadata["answer_fallback_reason"],
                            }
                            direct_tool_finalized = len(pending_tool_calls) <= 1 and not current_bundle_items
                        operation_id = resolve_tool_operation_id(
                            str(observation_payload.get("tool_name") or ""),
                            definitions_by_name=self.tool_authorization_index.definitions_by_name,
                        )
                        current_step = current_task_step_run(runtime_task_ledger)
                        if (
                            runtime_task_ledger is not None
                            and current_step is not None
                            and current_step.status == "running"
                            and current_step.executor_type in {"tool", "worker", "agent"}
                            and step_supports_operation(current_step, operation_id)
                        ):
                            runtime_task_ledger = complete_task_run_step(
                                runtime_task_ledger,
                                step_id=current_step.step_id,
                                completed_at=time.time(),
                                observation_refs=(observation_ref,),
                                output_refs=(observation_ref,),
                                step_result_ref=observation_ref,
                                executor_ref=str(observation_payload.get("tool_name") or operation_id),
                                diagnostics={
                                    "transition_reason": "tool_result_received",
                                    "operation_id": operation_id,
                                },
                            )
                            completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                            if completed_step is not None:
                                step_completed_event = self._record_task_run_step_event(
                                    state.task_run_id,
                                    event_type="step_completed",
                                    step_run=completed_step,
                                    ledger=runtime_task_ledger,
                                    reason="tool_result_received",
                                    refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                )
                                yield {"type": "runtime_loop_event", "event": step_completed_event.to_dict()}
                            runtime_task_ledger = advance_task_run_ledger(
                                runtime_task_ledger,
                                started_at=time.time(),
                                diagnostics={
                                    "transition_reason": "tool_result_received",
                                    "operation_id": operation_id,
                                },
                            )
                            ledger_event = self._record_task_run_ledger_updated(
                                state.task_run_id,
                                ledger=runtime_task_ledger,
                                reason="tool_result_received",
                                refs={"operation_id": operation_id, "observation_ref": observation_ref},
                            )
                            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                            entered_step = current_task_step_run(runtime_task_ledger)
                            if entered_step is not None and entered_step.step_id != current_step.step_id:
                                step_entered_event = self._record_task_run_step_event(
                                    state.task_run_id,
                                    event_type="step_entered",
                                    step_run=entered_step,
                                    ledger=runtime_task_ledger,
                                    reason="tool_result_received",
                                    refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                )
                                yield {"type": "runtime_loop_event", "event": step_entered_event.to_dict()}
                            state = self._state_with_task_run_ledger(
                                state,
                                runtime_task_ledger,
                                result_refs=result_refs,
                                diagnostics={"last_step_transition": "tool_result_received"},
                            )
                            checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                    elif observation.get("observation_type") == "executor_error":
                        terminal_reason = "executor_failed"
                        current_step = current_task_step_run(runtime_task_ledger)
                        if (
                            runtime_task_ledger is not None
                            and current_step is not None
                            and current_step.status == "running"
                            and current_step.executor_type in {"tool", "worker", "agent"}
                        ):
                            error_text = str(dict(observation.get("payload") or {}).get("error") or "executor_failed")
                            runtime_task_ledger = fail_task_run_step(
                                runtime_task_ledger,
                                step_id=current_step.step_id,
                                completed_at=time.time(),
                                failure_reason=error_text,
                                observation_refs=(observation_ref,),
                                output_refs=(observation_ref,),
                                step_result_ref=observation_ref,
                                executor_ref=str(observation.get("source") or current_step.executor_ref),
                                diagnostics={"transition_reason": "executor_error_observation"},
                            )
                            failed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                            if failed_step is not None:
                                step_failed_event = self._record_task_run_step_event(
                                    state.task_run_id,
                                    event_type="step_failed",
                                    step_run=failed_step,
                                    ledger=runtime_task_ledger,
                                    reason="executor_error_observation",
                                    refs={"observation_ref": observation_ref},
                                )
                                yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                            ledger_event = self._record_task_run_ledger_updated(
                                state.task_run_id,
                                ledger=runtime_task_ledger,
                                reason="executor_error_observation",
                                refs={"observation_ref": observation_ref},
                                diagnostics={"terminal_reason": "executor_failed"},
                            )
                            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                            state = self._state_with_task_run_ledger(
                                state,
                                runtime_task_ledger,
                                result_refs=result_refs,
                                diagnostics={"last_step_transition": "executor_error_observation"},
                            )
                            checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                elif runtime_event.event_type == "loop_error":
                    terminal_reason = "executor_failed"
                    current_step = current_task_step_run(runtime_task_ledger)
                    if (
                        runtime_task_ledger is not None
                        and current_step is not None
                        and current_step.status == "running"
                        and current_step.executor_type in {"tool", "worker", "agent"}
                    ):
                        error_text = str(runtime_event.payload.get("error") or "executor_failed")
                        runtime_task_ledger = fail_task_run_step(
                            runtime_task_ledger,
                            step_id=current_step.step_id,
                            completed_at=time.time(),
                            failure_reason=error_text,
                            diagnostics={"transition_reason": "loop_error"},
                        )
                        failed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                        if failed_step is not None:
                            step_failed_event = self._record_task_run_step_event(
                                state.task_run_id,
                                event_type="step_failed",
                                step_run=failed_step,
                                ledger=runtime_task_ledger,
                                reason="loop_error",
                            )
                            yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                        ledger_event = self._record_task_run_ledger_updated(
                            state.task_run_id,
                            ledger=runtime_task_ledger,
                            reason="loop_error",
                            diagnostics={"terminal_reason": "executor_failed"},
                        )
                        yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                        state = self._state_with_task_run_ledger(
                            state,
                            runtime_task_ledger,
                            result_refs=result_refs,
                            diagnostics={"last_step_transition": "loop_error"},
                        )
                        checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                elif runtime_event.event_type == "output_boundary_applied":
                    result_refs.append(f"output_boundary:{runtime_event.event_id}")
                elif runtime_event.event_type == "commit_gate_checked":
                    commit_ref = str(
                        runtime_event.refs.get("commit_gate_ref")
                        or dict(runtime_event.payload.get("commit_gate") or {}).get("gate_id")
                        or runtime_event.event_id
                    )
                    result_refs.append(f"commit_gate:{commit_ref}")
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            if event.get("type") == "done":
                final_content = str(event.get("content") or "")
                final_answer_metadata = {
                    "answer_channel": str(event.get("answer_channel") or ""),
                    "answer_source": str(event.get("answer_source") or ""),
                    "answer_canonical_state": str(event.get("answer_canonical_state") or ""),
                    "answer_persist_policy": str(event.get("answer_persist_policy") or ""),
                    "answer_finalization_policy": str(event.get("answer_finalization_policy") or ""),
                    "answer_fallback_reason": str(event.get("answer_fallback_reason") or ""),
                }
            elif event.get("type") == "error":
                terminal_reason = "executor_failed"
            if event.get("type") != "done":
                yield event

        turn_count = 1
        model_call_count = 1
        followup_messages: list[Any] = []
        if len(pending_tool_calls) > 1 and terminal_reason == "completed":
            direct_tool_finalized = False
            final_content = ""
            final_answer_metadata = {}
        if pending_tool_calls and tool_messages and terminal_reason == "completed" and not direct_tool_finalized:
            followup_messages = [
                *list(context_snapshot.model_messages),
                AIMessage(
                    content=assistant_tool_call_content,
                    tool_calls=pending_tool_calls,
                    additional_kwargs=assistant_tool_call_kwargs,
                ),
                *tool_messages,
            ]
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
                limits=self.limits,
                started_at=start.task_run.created_at,
                model_call_count=model_call_count - 1,
                event_count=len(self.event_log.list_events(state.task_run_id)),
            )
            followup_control_event = self.event_log.append(
                state.task_run_id,
                "loop_control_checked",
                payload={"control": followup_control.to_dict()},
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": followup_control_event.to_dict()}
            yield {"type": "runtime_loop_control", "control": followup_control.to_dict()}
            if not followup_control.allowed:
                terminal_reason = followup_control.reason
                if not final_content:
                    final_content = _build_runtime_budget_exhausted_message(
                        followup_control.message,
                        tool_observation_count=tool_observation_count,
                    )
                    final_answer_metadata = _runtime_budget_exhausted_answer_metadata()
                break
            followup_event = self.event_log.append(
                state.task_run_id,
                "loop_iteration_started",
                payload={
                    "transition": "continue_after_tool_result",
                    "turn_count": turn_count,
                    "step_count": task_run_step_count(runtime_task_ledger),
                    "tool_result_count": len([item for item in followup_messages if isinstance(item, ToolMessage)]),
                },
            )
            yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            state = self._state_with_task_run_ledger(
                state,
                runtime_task_ledger,
                transition="continue_after_tool_result",
                result_refs=result_refs,
            )
            next_pending_tool_calls: list[dict[str, Any]] = []
            next_assistant_tool_call_content = ""
            next_assistant_tool_call_kwargs: dict[str, Any] = {}
            next_tool_messages: list[ToolMessage] = []
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=followup_messages,
                directive=directive,
                tool_instances=runtime_tool_instances,
            ):
                if event.get("type") == "tool_call_requested":
                    tool_call = dict(event.get("tool_call") or {})
                    if tool_call:
                        next_pending_tool_calls.append(tool_call)
                    next_assistant_tool_call_content = str(
                        event.get("assistant_content") or next_assistant_tool_call_content
                    )
                    event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                    if event_kwargs:
                        next_assistant_tool_call_kwargs.update(event_kwargs)
                runtime_events = await self._events_from_executor_event(
                    state.task_run_id,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=resource_policy,
                current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
                runtime_context_manager=runtime_context_manager,
                tool_runtime_executor=tool_runtime_executor,
                event=event,
                )
                for runtime_event in runtime_events:
                    if runtime_event.event_type == "executor_observation_received":
                        observation_ref = str(runtime_event.refs.get("observation_ref") or runtime_event.event_id)
                        result_refs.append(observation_ref)
                        observation = dict(runtime_event.payload.get("observation") or {})
                        if observation.get("observation_type") == "tool_result":
                            tool_observation_count += 1
                            observation_payload = dict(observation.get("payload") or {})
                            matched_ordinal = _match_bundle_ordinal_for_tool_observation(
                                bundle_items=current_bundle_items,
                                tool_name=str(observation_payload.get("tool_name") or ""),
                                tool_args=dict(observation_payload.get("tool_args") or {}),
                                executed_ordinals=executed_bundle_ordinals,
                            )
                            if matched_ordinal > 0 and matched_ordinal not in executed_bundle_ordinals:
                                executed_bundle_ordinals.append(matched_ordinal)
                            projected_main_context, projected_task_summary_refs = _project_file_work_context_from_tool_observation(
                                observation_payload
                            )
                            if projected_main_context or projected_task_summary_refs:
                                projection = projection_from_file_work(
                                    projected_main_context,
                                    projected_task_summary_refs,
                                    bundle_items=current_bundle_items,
                                )
                                aggregation = observation_aggregator.add_projection(
                                    projection,
                                    tool_name=str(observation_payload.get("tool_name") or ""),
                                )
                            (
                                final_main_context,
                                final_task_summary_refs,
                                final_bundle_summary_refs,
                            ) = self._apply_observation_aggregation(observation_aggregator.snapshot())
                            repeated_tool_halt = repeated_tool_halt or tool_repetition_guard.record(
                                str(observation_payload.get("tool_name") or ""),
                                dict(observation_payload.get("tool_args") or {}),
                            )
                            next_tool_messages.append(
                                ToolMessage(
                                    content=str(observation_payload.get("result") or ""),
                                    tool_call_id=str(observation_payload.get("tool_call_id") or observation_ref),
                                )
                            )
                            operation_id = resolve_tool_operation_id(
                                str(observation_payload.get("tool_name") or ""),
                                definitions_by_name=self.tool_authorization_index.definitions_by_name,
                            )
                            current_step = current_task_step_run(runtime_task_ledger)
                            if (
                                runtime_task_ledger is not None
                                and current_step is not None
                                and current_step.status == "running"
                                and current_step.executor_type in {"tool", "worker", "agent"}
                                and step_supports_operation(current_step, operation_id)
                            ):
                                runtime_task_ledger = complete_task_run_step(
                                    runtime_task_ledger,
                                    step_id=current_step.step_id,
                                    completed_at=time.time(),
                                    observation_refs=(observation_ref,),
                                    output_refs=(observation_ref,),
                                    step_result_ref=observation_ref,
                                    executor_ref=str(observation_payload.get("tool_name") or operation_id),
                                    diagnostics={
                                        "transition_reason": "tool_result_received",
                                        "operation_id": operation_id,
                                    },
                                )
                                completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                                if completed_step is not None:
                                    step_completed_event = self._record_task_run_step_event(
                                        state.task_run_id,
                                        event_type="step_completed",
                                        step_run=completed_step,
                                        ledger=runtime_task_ledger,
                                        reason="tool_result_received",
                                        refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                    )
                                    yield {"type": "runtime_loop_event", "event": step_completed_event.to_dict()}
                                runtime_task_ledger = advance_task_run_ledger(
                                    runtime_task_ledger,
                                    started_at=time.time(),
                                    diagnostics={
                                        "transition_reason": "tool_result_received",
                                        "operation_id": operation_id,
                                    },
                                )
                                ledger_event = self._record_task_run_ledger_updated(
                                    state.task_run_id,
                                    ledger=runtime_task_ledger,
                                    reason="tool_result_received",
                                    refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                )
                                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                                entered_step = current_task_step_run(runtime_task_ledger)
                                if entered_step is not None and entered_step.step_id != current_step.step_id:
                                    step_entered_event = self._record_task_run_step_event(
                                        state.task_run_id,
                                        event_type="step_entered",
                                        step_run=entered_step,
                                        ledger=runtime_task_ledger,
                                        reason="tool_result_received",
                                        refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                    )
                                    yield {"type": "runtime_loop_event", "event": step_entered_event.to_dict()}
                                state = self._state_with_task_run_ledger(
                                    state,
                                    runtime_task_ledger,
                                    result_refs=result_refs,
                                    diagnostics={"last_step_transition": "tool_result_received"},
                                )
                                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                                yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                        elif observation.get("observation_type") == "executor_error":
                            terminal_reason = "executor_failed"
                            current_step = current_task_step_run(runtime_task_ledger)
                            if (
                                runtime_task_ledger is not None
                                and current_step is not None
                                and current_step.status == "running"
                                and current_step.executor_type in {"tool", "worker", "agent"}
                            ):
                                error_text = str(dict(observation.get("payload") or {}).get("error") or "executor_failed")
                                runtime_task_ledger = fail_task_run_step(
                                    runtime_task_ledger,
                                    step_id=current_step.step_id,
                                    completed_at=time.time(),
                                    failure_reason=error_text,
                                    observation_refs=(observation_ref,),
                                    output_refs=(observation_ref,),
                                    step_result_ref=observation_ref,
                                    executor_ref=str(observation.get("source") or current_step.executor_ref),
                                    diagnostics={"transition_reason": "executor_error_observation"},
                                )
                                failed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                                if failed_step is not None:
                                    step_failed_event = self._record_task_run_step_event(
                                        state.task_run_id,
                                        event_type="step_failed",
                                        step_run=failed_step,
                                        ledger=runtime_task_ledger,
                                        reason="executor_error_observation",
                                        refs={"observation_ref": observation_ref},
                                    )
                                    yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                                ledger_event = self._record_task_run_ledger_updated(
                                    state.task_run_id,
                                    ledger=runtime_task_ledger,
                                    reason="executor_error_observation",
                                    refs={"observation_ref": observation_ref},
                                    diagnostics={"terminal_reason": "executor_failed"},
                                )
                                yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                                state = self._state_with_task_run_ledger(
                                    state,
                                    runtime_task_ledger,
                                    result_refs=result_refs,
                                    diagnostics={"last_step_transition": "executor_error_observation"},
                                )
                                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                                yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                    elif runtime_event.event_type == "loop_error":
                        terminal_reason = "executor_failed"
                        current_step = current_task_step_run(runtime_task_ledger)
                        if (
                            runtime_task_ledger is not None
                            and current_step is not None
                            and current_step.status == "running"
                            and current_step.executor_type in {"tool", "worker", "agent"}
                        ):
                            error_text = str(runtime_event.payload.get("error") or "executor_failed")
                            runtime_task_ledger = fail_task_run_step(
                                runtime_task_ledger,
                                step_id=current_step.step_id,
                                completed_at=time.time(),
                                failure_reason=error_text,
                                diagnostics={"transition_reason": "loop_error"},
                            )
                            failed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                            if failed_step is not None:
                                step_failed_event = self._record_task_run_step_event(
                                    state.task_run_id,
                                    event_type="step_failed",
                                    step_run=failed_step,
                                    ledger=runtime_task_ledger,
                                    reason="loop_error",
                                )
                                yield {"type": "runtime_loop_event", "event": step_failed_event.to_dict()}
                            ledger_event = self._record_task_run_ledger_updated(
                                state.task_run_id,
                                ledger=runtime_task_ledger,
                                reason="loop_error",
                                diagnostics={"terminal_reason": "executor_failed"},
                            )
                            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                            state = self._state_with_task_run_ledger(
                                state,
                                runtime_task_ledger,
                                result_refs=result_refs,
                                diagnostics={"last_step_transition": "loop_error"},
                            )
                            checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                    elif runtime_event.event_type == "output_boundary_applied":
                        result_refs.append(f"output_boundary:{runtime_event.event_id}")
                    elif runtime_event.event_type == "commit_gate_checked":
                        commit_ref = str(
                            runtime_event.refs.get("commit_gate_ref")
                            or dict(runtime_event.payload.get("commit_gate") or {}).get("gate_id")
                            or runtime_event.event_id
                        )
                        result_refs.append(f"commit_gate:{commit_ref}")
                    yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                if event.get("type") == "done":
                    final_content = str(event.get("content") or "")
                    final_answer_metadata = {
                        "answer_channel": str(event.get("answer_channel") or ""),
                        "answer_source": str(event.get("answer_source") or ""),
                        "answer_canonical_state": str(event.get("answer_canonical_state") or ""),
                        "answer_persist_policy": str(event.get("answer_persist_policy") or ""),
                        "answer_finalization_policy": str(event.get("answer_finalization_policy") or ""),
                        "answer_fallback_reason": str(event.get("answer_fallback_reason") or ""),
                    }
                elif event.get("type") == "error":
                    terminal_reason = "executor_failed"
                if event.get("type") != "done":
                    yield event
            if next_pending_tool_calls and next_tool_messages and terminal_reason == "completed":
                if repeated_tool_halt and final_content:
                    followup_messages = []
                    break
                if repeated_tool_halt:
                    synthesized = _forced_tool_synthesis_answer(
                        user_message=user_message,
                        final_task_summary_refs=final_task_summary_refs,
                        final_main_context=final_main_context,
                    )
                    if synthesized:
                        final_content = synthesized
                        final_answer_metadata = _forced_synthesis_answer_metadata(source="runtime_loop.repeated_tool_halt")
                        followup_messages = []
                        break
                followup_messages = [
                    *followup_messages,
                    AIMessage(
                        content=next_assistant_tool_call_content,
                        tool_calls=next_pending_tool_calls,
                        additional_kwargs=next_assistant_tool_call_kwargs,
                    ),
                    *next_tool_messages,
                ]
                continue
            followup_messages = []

        terminal_state = state.with_status(
            "completed" if terminal_reason == "completed" else "failed",
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            diagnostics={"final_content_chars": len(final_content)},
        )
        if final_content and not (final_main_context or final_task_summary_refs):
            bound_projection = projection_from_bound_answer(
                content=final_content,
                current_turn_context=current_turn_context,
                existing_task_summary_refs=final_task_summary_refs,
                existing_main_context=final_main_context,
            )
            if bound_projection.main_context or bound_projection.task_summary_refs:
                aggregation = observation_aggregator.add_projection(bound_projection, tool_name="bound_answer")
                (
                    final_main_context,
                    final_task_summary_refs,
                    final_bundle_summary_refs,
                ) = self._apply_observation_aggregation(aggregation)
        if current_bundle_items and final_content:
            bundle_projection = projection_from_bundle_answer(
                content=final_content,
                bundle_items=current_bundle_items,
                existing_task_summary_refs=final_task_summary_refs,
                existing_main_context=final_main_context,
                executed_ordinals=executed_bundle_ordinals,
            )
            if bundle_projection.bundle_summary_refs:
                aggregation = observation_aggregator.add_projection(bundle_projection, tool_name="bundle_answer")
                (
                    final_main_context,
                    final_task_summary_refs,
                    final_bundle_summary_refs,
                ) = self._apply_observation_aggregation(aggregation)
        assistant_commit = build_assistant_session_message_commit_decision(
            session_id=session_id,
            task_run_id=terminal_state.task_run_id,
            task_id=task_id,
            content=final_content,
            **final_answer_metadata,
        )
        output_refs = [
            item["task_id"]
            for item in final_task_summary_refs
            if str(item.get("task_id") or "").strip()
        ]
        output_refs.extend(
            item["task_id"]
            for item in final_bundle_summary_refs
            if str(item.get("task_id") or "").strip()
        )
        final_task_run_ledger, ledger_transitions = _finalize_runtime_task_run_ledger(
            ledger=runtime_task_ledger,
            terminal_reason=terminal_reason,
            final_content=final_content,
            output_refs=tuple(_dedupe_refs([*result_refs, *output_refs])),
        )
        if final_task_run_ledger is not None:
            for transition in ledger_transitions:
                step_run = transition["step_run"]
                step_event = self._record_task_run_step_event(
                    terminal_state.task_run_id,
                    event_type=transition["event_type"],
                    step_run=step_run,
                    ledger=final_task_run_ledger,
                    reason=transition["reason"],
                    diagnostics=dict(transition.get("diagnostics") or {}),
                )
                yield {"type": "runtime_loop_event", "event": step_event.to_dict()}
            ledger_event = self._record_task_run_ledger_updated(
                terminal_state.task_run_id,
                ledger=final_task_run_ledger,
                reason="terminal_projection",
                diagnostics={"terminal_reason": terminal_reason},
            )
            yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
            terminal_state = self._state_with_task_run_ledger(
                terminal_state,
                final_task_run_ledger,
                result_refs=result_refs,
                diagnostics={"last_step_transition": "terminal_projection"},
            )
            checkpoint_event = self._write_checkpoint_event(terminal_state, event_offset=ledger_event.offset)
            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
        task_result = (
            project_task_result_from_ledger(
                final_task_run_ledger,
                result_id=f"taskresult:{terminal_state.task_run_id}",
                status="completed" if terminal_reason == "completed" else "failed",
                terminal_reason=terminal_reason,
                result_refs=tuple(_dedupe_refs(result_refs)),
                output_refs=tuple(_dedupe_refs(output_refs)),
                final_outputs={
                    "final_answer": final_content,
                    "main_context": dict(final_main_context),
                    "task_summary_refs": [dict(item) for item in final_task_summary_refs],
                    "bundle_summary_refs": [dict(item) for item in final_bundle_summary_refs],
                    "answer_metadata": dict(final_answer_metadata),
                },
                diagnostics={
                    "tool_observation_count": int(tool_observation_count or 0),
                    "final_content_chars": len(str(final_content or "")),
                    "bundle_result_count": len(final_bundle_summary_refs),
                    "task_summary_count": len(final_task_summary_refs),
                },
            )
            if final_task_run_ledger is not None
            else None
        )
        if final_task_run_ledger is not None and final_task_run_ledger.ledger_id not in result_refs:
            result_refs.append(final_task_run_ledger.ledger_id)
        if task_result is not None and task_result.result_id not in result_refs:
            result_refs.append(task_result.result_id)
        assistant_commit_applied = False
        assistant_commit_result: Any = None
        if assistant_commit.commit_allowed and assistant_message_committer is not None:
            assistant_payload = dict(assistant_commit.commit_candidate.payload)
            if final_main_context:
                assistant_payload["main_context"] = dict(final_main_context)
            if final_task_summary_refs:
                assistant_payload["task_summary_refs"] = [dict(item) for item in final_task_summary_refs]
            if final_bundle_summary_refs:
                assistant_payload["bundle_summary_refs"] = [dict(item) for item in final_bundle_summary_refs]
            assistant_commit_result = assistant_message_committer(assistant_payload)
            if inspect.isawaitable(assistant_commit_result):
                assistant_commit_result = await assistant_commit_result
            assistant_commit_applied = True
        assistant_commit_summary = _commit_result_summary(assistant_commit_result)
        memory_commit_state = _memory_commit_state_from_assistant_commit_result(assistant_commit_result)
        assistant_commit_event = self.event_log.append(
            terminal_state.task_run_id,
            "commit_gate_checked",
            payload={
                "commit_decision": assistant_commit.to_dict(),
                "commit_applied": assistant_commit_applied,
                "commit_result": assistant_commit_summary,
                "memory_commit_state": memory_commit_state,
            },
            refs={
                "commit_gate_ref": assistant_commit.gate_id,
                "commit_type": assistant_commit.commit_type,
                "commit_scope": "assistant_final_message_only",
            },
        )
        result_refs.append(f"commit_gate:{assistant_commit.gate_id}")
        yield {"type": "runtime_loop_event", "event": assistant_commit_event.to_dict()}
        yield {
            "type": "runtime_assistant_session_commit",
            "commit_gate": assistant_commit.to_dict(),
            "commit_applied": assistant_commit_applied,
        }
        final_commit = build_task_run_final_commit_decision(
            task_run_id=terminal_state.task_run_id,
            task_id=task_id,
            task_spec_ref=task_result.task_spec_ref if task_result is not None else "",
            template_id=task_result.template_id if task_result is not None else "",
            terminal_reason=terminal_state.terminal_reason,
            final_content_chars=len(final_content),
            task_result=task_result.to_dict() if task_result is not None else None,
        )
        commit_event = self.event_log.append(
            terminal_state.task_run_id,
            "commit_gate_checked",
            payload={"commit_decision": final_commit.to_dict()},
            refs={
                "commit_gate_ref": final_commit.gate_id,
                "commit_type": final_commit.commit_type,
            },
        )
        result_refs.append(f"commit_gate:{final_commit.gate_id}")
        yield {"type": "runtime_loop_event", "event": commit_event.to_dict()}
        yield {"type": "runtime_task_result_commit", "commit_gate": final_commit.to_dict()}
        yield {
            "type": "done",
            "content": final_content,
            "main_context": dict(final_main_context),
            "task_summary_refs": [dict(item) for item in final_task_summary_refs],
            "bundle_summary_refs": [dict(item) for item in final_bundle_summary_refs],
            "followup_mode": str(final_main_context.get("followup_mode") or ""),
            "followup_target_task_id": str(final_main_context.get("followup_target_task_id") or ""),
            "followup_target_task_ids": list(final_main_context.get("followup_target_task_ids") or []),
            **final_answer_metadata,
            "persist_policy": "committed" if terminal_reason == "completed" else "progress_only",
            "terminal_reason": terminal_reason,
            "commit_gate": assistant_commit.to_dict(),
            "task_result_commit": final_commit.to_dict(),
            "task_run_ledger": final_task_run_ledger.to_dict() if final_task_run_ledger is not None else {},
            "task_result": task_result.to_dict() if task_result is not None else {},
            "output_commit": {
                "state": "committed" if assistant_commit_applied else "not_applied",
                "assistant_commit_applied": assistant_commit_applied,
                "assistant_commit": assistant_commit.to_dict(),
                "task_result_commit": final_commit.to_dict(),
                "memory": dict(memory_commit_state),
                "file_work_context_writeback": bool(final_main_context or final_task_summary_refs),
            },
            "legacy_query_chain_removed": True,
        }
        terminal_state = RuntimeLoopState(
            task_run_id=terminal_state.task_run_id,
            status=terminal_state.status,
            turn_count=turn_count,
            step_count=task_run_step_count(final_task_run_ledger),
            current_step_id=final_task_run_ledger.current_step_id if final_task_run_ledger is not None else terminal_state.current_step_id,
            agent_id=terminal_state.agent_id,
            agent_profile_id=terminal_state.agent_profile_id,
            runtime_lane=terminal_state.runtime_lane,
            task_agent_binding_ref=terminal_state.task_agent_binding_ref,
            task_template_id=final_task_run_ledger.template_id if final_task_run_ledger is not None else terminal_state.task_template_id,
            task_spec_ref=final_task_run_ledger.task_spec_ref if final_task_run_ledger is not None else terminal_state.task_spec_ref,
            task_result_ref=task_result.result_id if task_result is not None else "",
            skill_workflow_ref=terminal_state.skill_workflow_ref,
            health_issue_ref=terminal_state.health_issue_ref,
            transition=terminal_state.transition,
            terminal_reason=terminal_state.terminal_reason,
            messages_ref=terminal_state.messages_ref,
            context_snapshot_ref=terminal_state.context_snapshot_ref,
            memory_state_ref=terminal_state.memory_state_ref,
            projection_ref=terminal_state.projection_ref,
            prompt_manifest_ref=terminal_state.prompt_manifest_ref,
            pending_action_requests=terminal_state.pending_action_requests,
            pending_approval_state=terminal_state.pending_approval_state,
            denial_tracking_state=terminal_state.denial_tracking_state,
            token_pressure=terminal_state.token_pressure,
            compaction_state=terminal_state.compaction_state,
            result_refs=tuple(result_refs),
            commit_state={
                "assistant_session_message": assistant_commit.to_dict(),
                "assistant_session_write_applied": assistant_commit_applied,
                "task_result_final": final_commit.to_dict(),
                "task_run_ledger": final_task_run_ledger.to_dict() if final_task_run_ledger is not None else {},
                "task_result": task_result.to_dict() if task_result is not None else {},
                "assistant_session_write_allowed": assistant_commit.commit_allowed,
                **memory_commit_state,
                "artifact_write_allowed": False,
            },
            diagnostics={
                **dict(terminal_state.diagnostics),
                "result_ref_count": len(result_refs),
            },
        )
        terminal_event = self.event_log.append(
            terminal_state.task_run_id,
            "loop_terminal",
            payload={
                "terminal_reason": terminal_state.terminal_reason,
                "status": terminal_state.status,
                "final_content_chars": len(final_content),
                "task_result": task_result.to_dict() if task_result is not None else {},
            },
        )
        yield {"type": "runtime_loop_event", "event": terminal_event.to_dict()}
        checkpoint_event = self._write_checkpoint_event(terminal_state, event_offset=terminal_event.offset)
        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
        self._upsert_finished_task_run(
            start_task_run=start.task_run,
            task_contract_ref=task_contract_ref,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            diagnostics={"final_content_chars": len(final_content)},
        )

    def _upsert_finished_task_run(
        self,
        *,
        start_task_run: TaskRun,
        task_contract_ref: str,
        terminal_state: RuntimeLoopState,
        checkpoint_event: Any,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=start_task_run.task_run_id,
                session_id=start_task_run.session_id,
                task_id=start_task_run.task_id,
                task_contract_ref=task_contract_ref,
                agent_id=start_task_run.agent_id,
                agent_profile_id=start_task_run.agent_profile_id,
                runtime_lane=start_task_run.runtime_lane,
                status=terminal_state.status,
                created_at=start_task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                terminal_reason=terminal_state.terminal_reason,
                diagnostics={
                    **dict(start_task_run.diagnostics),
                    **dict(diagnostics or {}),
                },
            )
        )

    def _write_checkpoint_event(self, state: RuntimeLoopState, *, event_offset: int):
        execution_summary = self.execution_store.build_summary(state.task_run_id)
        execution_refs = tuple(str(item) for item in list(execution_summary.get("execution_refs") or []))
        execution_state_ref = str(execution_summary.get("latest_execution_id") or "")
        checkpoint = self.checkpoints.write(
            state,
            event_offset=event_offset,
            execution_refs=execution_refs,
            execution_state_ref=execution_state_ref,
            execution_summary=execution_summary,
        )
        return self.event_log.append(
            state.task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "execution_summary": execution_summary,
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )

    def _state_with_task_run_ledger(
        self,
        state: RuntimeLoopState,
        ledger: TaskRunLedger | None,
        *,
        transition: str | None = None,
        task_result_ref: str | None = None,
        result_refs: list[str] | tuple[str, ...] | None = None,
        status: str | None = None,
        terminal_reason: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        commit_state: dict[str, Any] | None = None,
    ) -> RuntimeLoopState:
        merged_diagnostics = dict(state.diagnostics)
        if diagnostics:
            merged_diagnostics.update(diagnostics)
        return RuntimeLoopState(
            task_run_id=state.task_run_id,
            status=status or state.status,
            turn_count=state.turn_count,
            step_count=task_run_step_count(ledger),
            current_step_id=ledger.current_step_id if ledger is not None else state.current_step_id,
            agent_id=state.agent_id,
            agent_profile_id=state.agent_profile_id,
            runtime_lane=state.runtime_lane,
            task_agent_binding_ref=state.task_agent_binding_ref,
            task_template_id=ledger.template_id if ledger is not None else state.task_template_id,
            task_spec_ref=ledger.task_spec_ref if ledger is not None else state.task_spec_ref,
            task_result_ref=task_result_ref if task_result_ref is not None else state.task_result_ref,
            skill_workflow_ref=state.skill_workflow_ref,
            health_issue_ref=state.health_issue_ref,
            transition=transition or state.transition,
            terminal_reason=terminal_reason if terminal_reason is not None else state.terminal_reason,
            messages_ref=state.messages_ref,
            context_snapshot_ref=state.context_snapshot_ref,
            memory_state_ref=state.memory_state_ref,
            projection_ref=state.projection_ref,
            prompt_manifest_ref=state.prompt_manifest_ref,
            pending_action_requests=state.pending_action_requests,
            pending_approval_state=state.pending_approval_state,
            denial_tracking_state=state.denial_tracking_state,
            token_pressure=state.token_pressure,
            compaction_state=state.compaction_state,
            result_refs=tuple(result_refs) if result_refs is not None else state.result_refs,
            commit_state=dict(commit_state or state.commit_state),
            diagnostics=merged_diagnostics,
        )

    def _record_task_run_step_event(
        self,
        task_run_id: str,
        *,
        event_type: str,
        step_run: TaskStepRun,
        ledger: TaskRunLedger,
        reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ):
        payload = {
            "step_run": step_run.to_dict(),
            "task_run_ledger": ledger.to_dict(),
            "reason": reason,
        }
        if diagnostics:
            payload["diagnostics"] = dict(diagnostics)
        return self.event_log.append(
            task_run_id,
            event_type,
            payload=payload,
            refs={
                "task_run_ledger_ref": ledger.ledger_id,
                "task_step_ref": step_run.step_id,
                **dict(refs or {}),
            },
        )

    def _record_task_run_ledger_updated(
        self,
        task_run_id: str,
        *,
        ledger: TaskRunLedger,
        reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ):
        payload = {
            "task_run_ledger": ledger.to_dict(),
            "reason": reason,
        }
        if diagnostics:
            payload["diagnostics"] = dict(diagnostics)
        return self.event_log.append(
            task_run_id,
            "task_run_ledger_updated",
            payload=payload,
            refs={
                "task_run_ledger_ref": ledger.ledger_id,
                "current_step_id": str(ledger.current_step_id or ""),
                **dict(refs or {}),
            },
        )

    def _record_execution_event(
        self,
        task_run_id: str,
        *,
        event_type: str,
        record: OperationExecutionRecord,
        reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ):
        payload = {
            "execution_record": record.to_dict(),
            "reason": reason,
        }
        if diagnostics:
            payload["diagnostics"] = dict(diagnostics)
        return self.event_log.append(
            task_run_id,
            event_type,
            payload=payload,
            refs={
                "execution_ref": record.execution_id,
                "action_request_ref": record.request_ref,
                "directive_ref": record.directive_ref,
                "operation_id": record.operation_id,
                "task_step_ref": record.step_id,
                **dict(refs or {}),
            },
        )

    def _prepare_tool_execution(
        self,
        *,
        task_run_id: str,
        step_id: str,
        action_request: Any,
        directive_ref: str,
        operation_id: str,
        descriptor: Any,
        tool_name: str,
    ) -> tuple[OperationExecutionRecord, list[Any], str]:
        request_fingerprint = build_request_fingerprint(
            step_id=step_id,
            operation_id=operation_id,
            payload=dict(action_request.payload or {}),
        )
        idempotency_token = build_idempotency_token(
            task_run_id=task_run_id,
            step_id=step_id,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
        )
        replay_policy = derive_replay_policy(descriptor)
        existing = self.execution_store.find_by_fingerprint(
            task_run_id=task_run_id,
            step_id=step_id,
            operation_id=operation_id,
            request_fingerprint=request_fingerprint,
        )
        record = self.execution_store.create_record(
            task_run_id=task_run_id,
            step_id=step_id,
            action_request=action_request,
            directive_ref=directive_ref,
            operation_id=operation_id,
            executor_type="tool",
            replay_policy=replay_policy,
            request_fingerprint=request_fingerprint,
            idempotency_token=idempotency_token,
            diagnostics={"tool_name": tool_name},
        )
        events = [
            self._record_execution_event(
                task_run_id,
                event_type="execution_record_created",
                record=record,
                reason="tool_call_requested",
            )
        ]
        if existing is None or existing.execution_id == record.execution_id:
            return record, events, "dispatch"
        if replay_policy == "reuse_completed_result" and existing.status in {"completed", "reused_completed_result"}:
            record = self.execution_store.mark_reused(
                record,
                result_ref=existing.result_ref,
                result_payload=dict(existing.result_payload or {}),
                diagnostics={"source_execution_id": existing.execution_id},
            )
            events.append(
                self._record_execution_event(
                    task_run_id,
                    event_type="recovery_replay_decided",
                    record=record,
                    reason="reuse_completed_result",
                    diagnostics={"source_execution_id": existing.execution_id},
                )
            )
            events.append(
                self._record_execution_event(
                    task_run_id,
                    event_type="execution_result_reused",
                    record=record,
                    reason="reuse_completed_result",
                    diagnostics={"source_execution_id": existing.execution_id},
                )
            )
            return record, events, "reuse_completed_result"
        if replay_policy in {"deny_auto_replay", "manual_recovery_required"} and existing.status in {
            "completed",
            "dispatched",
            "reused_completed_result",
        }:
            record = self.execution_store.mark_replay_suppressed(
                record,
                error="replay_denied",
                diagnostics={"source_execution_id": existing.execution_id},
            )
            events.append(
                self._record_execution_event(
                    task_run_id,
                    event_type="recovery_replay_decided",
                    record=record,
                    reason="deny_auto_replay",
                    diagnostics={"source_execution_id": existing.execution_id},
                )
            )
            events.append(
                self._record_execution_event(
                    task_run_id,
                    event_type="replay_guard_triggered",
                    record=record,
                    reason="deny_auto_replay",
                    diagnostics={"source_execution_id": existing.execution_id},
                )
            )
            return record, events, "deny_auto_replay"
        return record, events, "dispatch"

    def _tool_instances_for_resource_policy(self, tool_instances: list[Any] | None, resource_policy: Any) -> list[Any]:
        from tools.authorization import build_authorized_tool_set

        allowed_operations = {
            self.operation_gate.registry.normalize_id(operation_id)
            for operation_id in [
                *tuple(getattr(resource_policy, "allowed_operations", ()) or ()),
                *tuple(getattr(resource_policy, "requires_approval_operations", ()) or ()),
            ]
        }
        authorized = build_authorized_tool_set(
            tool_instances=tool_instances,
            definitions_by_name=self.tool_authorization_index.definitions_by_name,
            allowed_operations=allowed_operations,
            runtime_lane="main_runtime",
        )
        return list(authorized.instances)

    def _build_tool_authorization_index(self):
        from tools.authorization import build_tool_authorization_index
        from tools.definitions import get_tool_definitions

        return build_tool_authorization_index(get_tool_definitions())

    async def _events_from_executor_event(
        self,
        task_run_id: str,
        *,
        task_id: str,
        task_operation: dict[str, Any],
        adopted_resource_policy: Any,
        current_step_id: str,
        runtime_context_manager: RuntimeContextManager,
        tool_runtime_executor: Any | None,
        event: dict[str, Any],
    ):
        event_type = str(event.get("type") or "")
        if event_type == "runtime_directive":
            return [
                self.event_log.append(
                task_run_id,
                "runtime_directive_issued",
                payload={
                    "directive": dict(event.get("directive") or {}),
                    "resource_policy": dict(event.get("resource_policy") or {}),
                },
                refs={
                    "directive_ref": str(dict(event.get("directive") or {}).get("directive_id") or ""),
                    "resource_policy_ref": str(dict(event.get("resource_policy") or {}).get("policy_id") or ""),
                },
                )
            ]
        if event_type == "operation_gate":
            gate = dict(event.get("gate") or {})
            return [
                self.event_log.append(
                task_run_id,
                "operation_gate_checked",
                payload={"gate": gate},
                refs={"operation_id": str(gate.get("operation_id") or "")},
                )
            ]
        if event_type == "answer_candidate":
            observation = build_model_response_observation(task_run_id, event)
            context_record = runtime_context_manager.record_observation(observation)
            return [
                self.event_log.append(
                task_run_id,
                "executor_observation_received",
                payload={
                    "observation": observation.to_dict(),
                    "context_record": context_record.to_dict(),
                    "source": observation.source,
                    "content_chars": observation.content_chars,
                },
                refs={
                    "directive_ref": observation.directive_ref,
                    "observation_ref": observation.observation_id,
                },
                )
            ]
        if event_type == "tool_call_requested":
            from tools.authorization import resolve_tool_operation_id

            action_request = build_tool_action_request(task_run_id, event, step_id=current_step_id)
            requested_event = self.event_log.append(
                task_run_id,
                "tool_call_requested",
                payload={"action_request": action_request.to_dict()},
                refs={
                    "action_request_ref": action_request.request_id,
                    "directive_ref": action_request.directive_ref,
                    "operation_id": action_request.operation_id,
                },
            )
            operation_id = self.operation_gate.registry.normalize_id(
                action_request.operation_id
                or resolve_tool_operation_id(
                    str(action_request.payload.get("tool_name") or ""),
                    definitions_by_name=self.tool_authorization_index.definitions_by_name,
                )
            )
            descriptor = self.operation_gate.registry.get_operation(operation_id)
            tool_directive, tool_policy = build_tool_request_runtime_adoption(
                action_request=action_request,
                task_id=task_id,
                task_operation=task_operation,
                operation_id=operation_id,
                operation_descriptor=descriptor,
                adopted_resource_policy=adopted_resource_policy,
            )
            directive_event = self.event_log.append(
                task_run_id,
                "runtime_directive_issued",
                payload={
                    "directive": tool_directive.to_dict(),
                    "resource_policy": tool_policy.to_dict(),
                    "dispatch_enabled": "pending_operation_gate",
                },
                refs={
                    "action_request_ref": action_request.request_id,
                    "directive_ref": tool_directive.directive_id,
                    "resource_policy_ref": tool_policy.policy_id,
                },
            )
            gate_result = self.operation_gate.check(
                operation_id,
                resource_policy=tool_policy,
                directive_ref=tool_directive.directive_id,
                context=OperationGatePipelineContext(
                    operation_input={
                        "operation_id": operation_id,
                        **dict(action_request.payload.get("tool_call") or {}),
                    },
                    validators=build_task_safety_validators(
                        root_dir=self.root_dir,
                        safety_envelope=dict(
                            dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}
                        ).get("safety_envelope", {}),
                    ),
                ),
            )
            gate_event = self.event_log.append(
                task_run_id,
                "operation_gate_checked",
                payload={
                    "gate": gate_result.to_dict(),
                    "dispatch_enabled": bool(gate_result.allowed and tool_runtime_executor is not None),
                    "tool_preflight_only": False,
                },
                refs={
                    "action_request_ref": action_request.request_id,
                    "operation_id": gate_result.operation_id,
                    "directive_ref": tool_directive.directive_id,
                },
            )
            events = [requested_event, directive_event, gate_event]
            if gate_result.allowed and tool_runtime_executor is not None:
                step_id = str(current_step_id or action_request.step_id or "")
                tool_name = str(action_request.payload.get("tool_name") or "")
                execution_record, execution_events, execution_decision = self._prepare_tool_execution(
                    task_run_id=task_run_id,
                    step_id=step_id,
                    action_request=action_request,
                    directive_ref=tool_directive.directive_id,
                    operation_id=operation_id,
                    descriptor=descriptor,
                    tool_name=tool_name,
                )
                events.extend(execution_events)
                if execution_decision == "reuse_completed_result":
                    reused_payload = dict(execution_record.result_payload or {})
                    reused_observation = build_tool_result_observation(
                        task_run_id=task_run_id,
                        request_ref=action_request.request_id,
                        directive_ref=tool_directive.directive_id,
                        tool_name=str(reused_payload.get("tool_name") or tool_name),
                        tool_call_id=str(
                            reused_payload.get("tool_call_id")
                            or dict(action_request.payload.get("tool_call") or {}).get("id")
                            or action_request.request_id
                        ),
                        tool_args=dict(reused_payload.get("tool_args") or dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
                        result=reused_payload.get("result") or "",
                        truncated=bool(reused_payload.get("truncated") is True),
                        execution_receipt=build_execution_receipt(
                            execution_record,
                            reused_previous_result=True,
                        ).to_dict(),
                        result_ref=str(execution_record.result_ref or ""),
                    )
                    context_record = runtime_context_manager.record_observation(reused_observation)
                    tool_result_event = self.event_log.append(
                        task_run_id,
                        "tool_result_received",
                        payload={
                            "observation": reused_observation.to_dict(),
                            "context_record": context_record.to_dict(),
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "directive_ref": tool_directive.directive_id,
                            "observation_ref": reused_observation.observation_id,
                            "execution_ref": execution_record.execution_id,
                        },
                    )
                    observation_event = self.event_log.append(
                        task_run_id,
                        "executor_observation_received",
                        payload={
                            "observation": reused_observation.to_dict(),
                            "context_record": context_record.to_dict(),
                            "source": reused_observation.source,
                            "content_chars": reused_observation.content_chars,
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "directive_ref": tool_directive.directive_id,
                            "observation_ref": reused_observation.observation_id,
                            "execution_ref": execution_record.execution_id,
                        },
                    )
                    events.extend([tool_result_event, observation_event])
                    return events
                if execution_decision == "deny_auto_replay":
                    error_message = "Tool execution replay denied because the operation is not replay-safe."
                    error_event = self.event_log.append(
                        task_run_id,
                        "loop_error",
                        payload={
                            "error": error_message,
                            "answer_source": "runtime_execution_replay_guard",
                            "execution_record": execution_record.to_dict(),
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "directive_ref": tool_directive.directive_id,
                            "execution_ref": execution_record.execution_id,
                            "operation_id": operation_id,
                        },
                    )
                    events.append(error_event)
                    return events
                dispatch_event = self._record_execution_event(
                    task_run_id,
                    event_type="execution_dispatch_started",
                    record=execution_record,
                    reason="tool_dispatch_started",
                )
                events.append(dispatch_event)
                max_chars = int(dict(gate_result.diagnostics or {}).get("max_result_size_chars") or 0)
                execution_outcome = await tool_runtime_executor.run(
                    task_run_id=task_run_id,
                    action_request=action_request,
                    directive=tool_directive,
                    execution_record=execution_record,
                    execution_store=self.execution_store,
                    max_result_size_chars=max_chars,
                )
                final_record = execution_outcome.get("execution_record")
                if isinstance(final_record, OperationExecutionRecord):
                    events.append(
                        self._record_execution_event(
                            task_run_id,
                            event_type="execution_result_recorded",
                            record=final_record,
                            reason="tool_execution_finished",
                        )
                    )
                observation = execution_outcome.get("observation")
                if observation is not None:
                    context_record = runtime_context_manager.record_observation(observation)
                    if observation.observation_type == "tool_result":
                        tool_result_event = self.event_log.append(
                            task_run_id,
                            "tool_result_received",
                            payload={
                                "observation": observation.to_dict(),
                                "context_record": context_record.to_dict(),
                            },
                            refs={
                                "action_request_ref": action_request.request_id,
                                "directive_ref": tool_directive.directive_id,
                                "observation_ref": observation.observation_id,
                                "execution_ref": str(getattr(final_record, "execution_id", "") or ""),
                            },
                        )
                        events.append(tool_result_event)
                    observation_event = self.event_log.append(
                        task_run_id,
                        "executor_observation_received",
                        payload={
                            "observation": observation.to_dict(),
                            "context_record": context_record.to_dict(),
                            "source": observation.source,
                            "content_chars": observation.content_chars,
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "directive_ref": tool_directive.directive_id,
                            "observation_ref": observation.observation_id,
                            "execution_ref": str(getattr(final_record, "execution_id", "") or ""),
                        },
                    )
                    events.append(observation_event)
            return events
        if event_type == "output_boundary":
            return [
                self.event_log.append(
                task_run_id,
                "output_boundary_applied",
                payload={"output": dict(event.get("output") or {})},
                )
            ]
        if event_type == "runtime_commit_gate":
            commit_gate = dict(event.get("commit_gate") or {})
            return [
                self.event_log.append(
                task_run_id,
                "commit_gate_checked",
                payload={"commit_gate": commit_gate},
                refs={
                    "commit_gate_ref": str(commit_gate.get("gate_id") or ""),
                    "commit_type": str(commit_gate.get("commit_type") or ""),
                },
                )
            ]
        if event_type == "error":
            observation = build_executor_error_observation(task_run_id, event)
            context_record = runtime_context_manager.record_observation(observation)
            return [
                self.event_log.append(
                task_run_id,
                "loop_error",
                payload={
                    "observation": observation.to_dict(),
                    "context_record": context_record.to_dict(),
                    "error": str(event.get("error") or ""),
                    "answer_source": str(event.get("answer_source") or ""),
                },
                refs={"observation_ref": observation.observation_id},
                )
            ]
        return []


def _build_initial_task_run_ledger(
    *,
    task_run_id: str,
    task_contract_ref: str,
    task_spec_payload: dict[str, Any],
    selected_template_payload: dict[str, Any],
) -> TaskRunLedger | None:
    task_spec = _task_spec_from_payload(task_spec_payload)
    selected_template = _task_template_from_payload(selected_template_payload)
    if task_spec is None or selected_template is None:
        return None
    return build_task_run_ledger(
        task_run_id=task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec=task_spec,
        selected_template=selected_template,
        status="running",
    )


def _finalize_runtime_task_run_ledger(
    *,
    ledger: TaskRunLedger | None,
    terminal_reason: str,
    final_content: str,
    output_refs: tuple[str, ...],
) -> tuple[TaskRunLedger | None, list[dict[str, Any]]]:
    if ledger is None:
        return None, []
    transitions: list[dict[str, Any]] = []
    finalized = ledger
    if terminal_reason == "completed":
        while True:
            current_step = current_task_step_run(finalized)
            if (
                current_step is not None
                and current_step.status == "running"
                and current_step.stop_policy == "allow_unverified_completion"
                and current_step.executor_type in {"tool", "worker", "agent"}
            ):
                finalized = skip_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    completed_at=time.time(),
                    diagnostics={"transition_reason": "allow_unverified_completion"},
                )
                skipped_step = find_task_step_run(finalized, current_step.step_id)
                if skipped_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_skipped",
                            "step_run": skipped_step,
                            "reason": "allow_unverified_completion",
                        }
                    )
                    continue
            if current_step is None:
                next_step = next_pending_step_run(finalized)
                if next_step is None:
                    break
                if next_step.stop_policy == "allow_unverified_completion":
                    finalized = skip_task_run_step(
                        finalized,
                        step_id=next_step.step_id,
                        completed_at=time.time(),
                        diagnostics={"transition_reason": "allow_unverified_completion"},
                    )
                    skipped_step = find_task_step_run(finalized, next_step.step_id)
                    if skipped_step is not None:
                        transitions.append(
                            {
                                "event_type": "step_skipped",
                                "step_run": skipped_step,
                                "reason": "allow_unverified_completion",
                            }
                        )
                    continue
                if final_content and next_step.executor_type == "model":
                    finalized = start_task_run_step(
                        finalized,
                        step_id=next_step.step_id,
                        started_at=time.time(),
                        diagnostics={"transition_reason": "terminal_finalize"},
                    )
                    entered_step = current_task_step_run(finalized)
                    if entered_step is not None:
                        transitions.append(
                            {
                                "event_type": "step_entered",
                                "step_run": entered_step,
                                "reason": "terminal_finalize",
                            }
                        )
                    continue
                break
            if current_step.status == "pending" and final_content and current_step.executor_type == "model":
                finalized = start_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    started_at=time.time(),
                    diagnostics={"transition_reason": "terminal_finalize"},
                )
                entered_step = current_task_step_run(finalized)
                if entered_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_entered",
                            "step_run": entered_step,
                            "reason": "terminal_finalize",
                        }
                    )
                continue
            if final_content:
                finalized = complete_task_run_step(
                    finalized,
                    step_id=current_step.step_id,
                    completed_at=time.time(),
                    output_refs=output_refs,
                    step_result_ref=output_refs[0] if output_refs else "",
                    executor_ref=current_step.executor_ref,
                    diagnostics={"transition_reason": "terminal_finalize"},
                )
                completed_step = find_task_step_run(finalized, current_step.step_id)
                if completed_step is not None:
                    transitions.append(
                        {
                            "event_type": "step_completed",
                            "step_run": completed_step,
                            "reason": "terminal_finalize",
                        }
                    )
                continue
            break
        finalized = terminalize_task_run_ledger(
            finalized,
            status="completed",
            current_step_id="",
            diagnostics={"terminal_reason": terminal_reason},
        )
        return finalized, transitions

    current_step = current_task_step_run(finalized)
    if current_step is not None and current_step.status == "running":
        finalized = fail_task_run_step(
            finalized,
            step_id=current_step.step_id,
            completed_at=time.time(),
            failure_reason=terminal_reason,
            output_refs=output_refs,
            step_result_ref=output_refs[0] if output_refs else "",
            diagnostics={"transition_reason": "terminal_failure"},
        )
        failed_step = find_task_step_run(finalized, current_step.step_id)
        if failed_step is not None:
            transitions.append(
                {
                    "event_type": "step_failed",
                    "step_run": failed_step,
                    "reason": "terminal_failure",
                }
            )
    finalized = terminalize_task_run_ledger(
        finalized,
        status=task_run_terminal_status(terminal_reason),
        current_step_id=finalized.current_step_id,
        diagnostics={"terminal_reason": terminal_reason},
    )
    return finalized, transitions


def _task_spec_from_payload(payload: dict[str, Any]) -> TaskSpec | None:
    if not payload:
        return None
    try:
        return TaskSpec(
            task_id=str(payload.get("task_id") or ""),
            task_spec_ref=str(payload.get("task_spec_ref") or ""),
            template_id=str(payload.get("template_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_goal=str(payload.get("user_goal") or ""),
            inputs=dict(payload.get("inputs") or {}),
            bindings=dict(payload.get("bindings") or {}),
            constraints=dict(payload.get("constraints") or {}),
            current_turn_context_ref=str(payload.get("current_turn_context_ref") or ""),
            task_intent_ref=str(payload.get("task_intent_ref") or ""),
            template_match_ref=str(payload.get("template_match_ref") or ""),
            bundle_spec_ref=str(payload.get("bundle_spec_ref") or ""),
            bundle_item_ref=str(payload.get("bundle_item_ref") or ""),
            requested_outputs=tuple(str(item) for item in list(payload.get("requested_outputs") or [])),
            step_input_bindings=tuple(
                _step_input_binding_from_payload(item)
                for item in list(payload.get("step_input_bindings") or [])
            ),
            selected_agent_id=str(payload.get("selected_agent_id") or "agent:0"),
            selected_skill_ids=tuple(str(item) for item in list(payload.get("selected_skill_ids") or [])),
            operation_requirement_ref=str(payload.get("operation_requirement_ref") or ""),
            status=str(payload.get("status") or "selected"),
        )
    except ValueError:
        return None


def _task_template_from_payload(payload: dict[str, Any]) -> TaskTemplate | None:
    if not payload:
        return None
    try:
        return TaskTemplate(
            template_id=str(payload.get("template_id") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            task_family=str(payload.get("task_family") or ""),
            task_mode=str(payload.get("task_mode") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
            allowed_agent_ids=tuple(str(item) for item in list(payload.get("allowed_agent_ids") or ["agent:0"])),
            required_capability_tags=tuple(str(item) for item in list(payload.get("required_capability_tags") or [])),
            required_operations=tuple(str(item) for item in list(payload.get("required_operations") or [])),
            optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or [])),
            step_blueprints=tuple(_task_step_blueprint_from_payload(item) for item in list(payload.get("step_blueprints") or [])),
            validation_rules=tuple(_task_validation_rule_from_payload(item) for item in list(payload.get("validation_rules") or [])),
            ui_manifest=dict(payload.get("ui_manifest") or {}),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )
    except ValueError:
        return None


def _task_step_blueprint_from_payload(payload: Any) -> TaskStepBlueprint:
    data = dict(payload or {})
    return TaskStepBlueprint(
        step_id=str(data.get("step_id") or ""),
        title=str(data.get("title") or ""),
        step_kind=str(data.get("step_kind") or ""),
        executor_type=str(data.get("executor_type") or ""),
        required_operations=tuple(str(item) for item in list(data.get("required_operations") or [])),
        optional_operations=tuple(str(item) for item in list(data.get("optional_operations") or [])),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        output_contract_id=str(data.get("output_contract_id") or ""),
        stop_policy=str(data.get("stop_policy") or "on_success"),
        retry_policy=dict(data.get("retry_policy") or {}),
    )


def _step_input_binding_from_payload(payload: Any) -> StepInputBinding:
    data = dict(payload or {})
    return StepInputBinding(
        step_id=str(data.get("step_id") or ""),
        input_refs=tuple(str(item) for item in list(data.get("input_refs") or [])),
        inherited_parent_refs=tuple(str(item) for item in list(data.get("inherited_parent_refs") or [])),
        private_state_refs=tuple(str(item) for item in list(data.get("private_state_refs") or [])),
        output_writebacks=dict(data.get("output_writebacks") or {}),
        binding_policy=str(data.get("binding_policy") or "inherit_parent_context"),
    )


def _bundle_items_from_runtime_contract(
    *,
    task_spec_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    bundle_spec = dict(dict(task_spec_payload.get("inputs") or {}).get("bundle_spec") or {})
    bundle_spec_items = [
        dict(item)
        for item in list(bundle_spec.get("items") or [])
        if isinstance(item, dict)
    ]
    return [
        {
            **item,
            "bundle_id": str(bundle_spec.get("bundle_id") or item.get("bundle_id") or ""),
        }
        for item in bundle_spec_items
    ]


def _task_validation_rule_from_payload(payload: Any) -> TaskValidationRule:
    data = dict(payload or {})
    return TaskValidationRule(
        rule_id=str(data.get("rule_id") or ""),
        title=str(data.get("title") or ""),
        validation_kind=str(data.get("validation_kind") or ""),
        severity=str(data.get("severity") or "warning"),
        parameters=dict(data.get("parameters") or {}),
        message=str(data.get("message") or ""),
    )


def _dedupe_refs(values: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        refs.append(item)
    return refs


def _runtime_budget_exhausted_answer_metadata() -> dict[str, str]:
    return {
        "answer_channel": "answer_candidate",
        "answer_source": "runtime_loop_control",
        "answer_canonical_state": "progress_only",
        "answer_persist_policy": "persist_debug_only",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "runtime_budget_exhausted",
    }


def _forced_synthesis_answer_metadata(*, source: str = "runtime_loop_synthesis") -> dict[str, str]:
    return {
        "answer_channel": "tool_visible_summary",
        "answer_source": source,
        "answer_canonical_state": "stable_answer",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "",
    }


def _build_runtime_budget_exhausted_message(message: str = "", *, tool_observation_count: int = 0) -> str:
    reason = str(message or "").strip()
    if "max_runtime_seconds" in reason:
        reason_text = "本轮运行时间达到上限"
    elif "max_model_calls" in reason:
        reason_text = "本轮模型续写次数达到上限"
    elif "max_events" in reason:
        reason_text = "本轮链路事件数量达到上限"
    else:
        reason_text = "本轮运行预算达到上限"
    evidence_text = (
        f"已经收到 {tool_observation_count} 条工具结果"
        if tool_observation_count > 0
        else "还没有收到可用于总结的工具结果"
    )
    return (
        f"{reason_text}，所以先停止继续调用工具。{evidence_text}，但模型还没有把这些结果收口成最终回答。"
        "请直接继续问“基于已读取内容总结”，我会从现有上下文继续收口。"
    )


def _forced_tool_synthesis_answer(
    *,
    user_message: str,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    if not final_task_summary_refs:
        return ""
    active_constraints = dict(final_main_context.get("active_constraints") or {})
    source = str(active_constraints.get("active_pdf") or active_constraints.get("active_dataset") or "").strip()
    summaries: list[str] = []
    for item in final_task_summary_refs[-3:]:
        summary = _clean_text(item.get("summary"))
        if not summary:
            continue
        summaries.append(summary)
    if not summaries:
        return ""
    if len(summaries) == 1:
        body = summaries[0]
    else:
        body = "\n".join(f"{index}. {summary}" for index, summary in enumerate(summaries, start=1))
    prefix = "基于已读取结果"
    if source:
        prefix += f"（{source}）"
    if user_message:
        prefix += "，"
    else:
        prefix += "："
    return f"{prefix}{body}"


def _direct_tool_answer_from_observation(
    *,
    user_message: str,
    observation_payload: dict[str, Any],
) -> dict[str, str] | None:
    tool_name = str(observation_payload.get("tool_name") or "").strip()
    result_text = str(observation_payload.get("result") or "").strip()
    if not tool_name or not result_text:
        return None
    boundary = AssistantOutputBoundary()
    boundary.ingest_tool_result(tool_name, result_text)
    boundary.finalize_segment()
    response = boundary.build_response(
        route="tool",
        execution_posture="direct_tool",
        user_message=user_message,
        tool_name=tool_name,
        retrieval_results=None,
    )
    content = str(response.canonical_answer or "").strip()
    if not content or response.fallback_reason:
        return None
    if response.selected_channel not in {"tool_visible_summary", "answer_candidate"}:
        return None
    return {
        "content": content,
        "answer_channel": str(response.selected_channel or "answer_candidate"),
        "answer_source": f"direct_tool.{tool_name}",
        "answer_canonical_state": str(response.canonical_state or "stable_answer"),
        "answer_persist_policy": str(response.persist_policy or "persist_canonical"),
        "answer_finalization_policy": str(response.finalization_policy or "none"),
        "answer_fallback_reason": "",
    }


def _project_file_work_context_from_tool_observation(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tool_name = str(payload.get("tool_name") or "").strip()
    tool_args = dict(payload.get("tool_args") or {})
    result_text = str(payload.get("result") or "").strip()
    if not result_text or str(payload.get("truncated") or "").lower() == "true":
        return {}, []
    if tool_name == "pdf_analysis":
        return _project_pdf_tool_context(tool_args=tool_args, result_text=result_text)
    if tool_name == "structured_data_analysis":
        return _project_structured_data_tool_context(tool_args=tool_args, result_text=result_text)
    return {}, []


def _project_pdf_tool_context(*, tool_args: dict[str, Any], result_text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _clean_text(tool_args.get("path"))
    query = _clean_text(tool_args.get("query"))
    if not path:
        path = _extract_tool_output_field(result_text, ("PDF", "文件", "path", "source"))
    canonical_payload = _parse_tool_canonical_payload(result_text, "PDF_CANONICAL_RESULT::")
    if not path and canonical_payload:
        path = _clean_text(canonical_payload.get("source"))
    if not path or _looks_like_failed_tool_result(result_text):
        return {}, []
    object_handle_id = _stable_file_work_id("source:pdf", path)
    result_handle_id = _stable_file_work_id("result:pdf_answer", f"{path}:{query}:{result_text[:160]}")
    pages = _extract_page_numbers(result_text)
    if not pages and canonical_payload:
        pages = [
            int(page)
            for page in list(canonical_payload.get("pages") or [])
            if _safe_positive_int(page) is not None
        ][:12]
    if not pages and canonical_payload:
        metadata = dict(canonical_payload.get("metadata") or {})
        target_page = _safe_positive_int(metadata.get("target_page"))
        if target_page is not None:
            pages = [target_page]
    subset_handle_id = (
        _stable_file_work_id("subset:pdf_pages", f"{path}:{','.join(str(page) for page in pages)}")
        if pages
        else ""
    )
    mode = _clean_text(tool_args.get("mode")) or ("page" if pages else "document")
    active_constraints: dict[str, Any] = {
        "active_pdf": path,
        "active_pdf_mode": mode,
        "source_kind": "pdf",
    }
    if pages:
        active_constraints["active_pdf_pages"] = pages
    main_context = {
        "active_goal": query,
        "active_work_item": "pdf",
        "active_binding_identity": _binding_identity(path),
        "active_object_handle_id": object_handle_id,
        "active_result_handle_id": result_handle_id,
        "active_subset_handle_id": subset_handle_id,
        "followup_mode": "binding_ref",
        "followup_resolution_source": "tool_observation_projection",
        "followup_target_task_id": result_handle_id,
        "followup_target_task_ids": [result_handle_id],
        "followup_binding_key": "active_pdf",
        "followup_binding_identity": _binding_identity(path),
        "active_constraints": active_constraints,
    }
    summary_source = _clean_text(canonical_payload.get("summary")) if canonical_payload else ""
    degraded_reason = _clean_text(canonical_payload.get("degraded_reason")) if canonical_payload else ""
    summary = _compact_summary(summary_source or result_text)
    if degraded_reason and degraded_reason not in summary:
        summary = _compact_summary(f"{summary} degraded_reason={degraded_reason}")
    task_summary = {
        "task_id": result_handle_id,
        "query": query,
        "summary": summary,
        "task_kind": "pdf",
        "key_points": [
            f"pdf={path}",
            f"pdf_mode={mode}",
            *([f"pdf_pages={','.join(str(page) for page in pages)}"] if pages else []),
            f"artifact={path}#analysis",
        ],
    }
    return main_context, [task_summary]


def _project_structured_data_tool_context(
    *,
    tool_args: dict[str, Any],
    result_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _clean_text(tool_args.get("path"))
    query = _clean_text(tool_args.get("query"))
    if not path:
        path = _extract_tool_output_field(result_text, ("数据集", "文件", "path", "source"))
    if not path or _looks_like_failed_tool_result(result_text):
        return {}, []
    object_handle_id = _stable_file_work_id("source:dataset", path)
    result_handle_id = _stable_file_work_id("result:structured_answer", f"{path}:{query}:{result_text[:160]}")
    subset_labels = _extract_ranked_labels(result_text)
    subset_handle_id = (
        _stable_file_work_id("subset:structured_selection", f"{path}:{'|'.join(subset_labels)}")
        if subset_labels
        else ""
    )
    active_constraints: dict[str, Any] = {
        "active_dataset": path,
        "source_kind": "dataset",
    }
    if subset_labels:
        active_constraints["subset_labels"] = subset_labels
    main_context = {
        "active_goal": query,
        "active_work_item": "structured_data",
        "active_binding_identity": _binding_identity(path),
        "active_object_handle_id": object_handle_id,
        "active_result_handle_id": result_handle_id,
        "active_subset_handle_id": subset_handle_id,
        "followup_mode": "binding_ref",
        "followup_resolution_source": "tool_observation_projection",
        "followup_target_task_id": result_handle_id,
        "followup_target_task_ids": [result_handle_id],
        "followup_binding_key": "active_dataset",
        "followup_binding_identity": _binding_identity(path),
        "active_constraints": active_constraints,
    }
    summary = _compact_summary(result_text)
    task_summary = {
        "task_id": result_handle_id,
        "query": query,
        "summary": summary,
        "task_kind": "structured_data",
        "key_points": [
            f"dataset={path}",
            *([f"subset={','.join(subset_labels[:8])}"] if subset_labels else []),
            f"artifact={path}#analysis",
        ],
    }
    return main_context, [task_summary]


def _stable_file_work_id(prefix: str, value: str) -> str:
    import hashlib

    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _parse_tool_canonical_payload(value: str, marker: str) -> dict[str, Any]:
    import json

    text = str(value or "").strip()
    if marker not in text:
        return {}
    raw = text.split(marker, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _binding_identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _compact_summary(value: str, max_chars: int = 280) -> str:
    return " ".join(str(value or "").split()).strip()[:max_chars]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _looks_like_failed_tool_result(value: str) -> bool:
    text = str(value or "").strip().lower()
    failure_markers = (
        "failed:",
        "分析失败",
        "explicit path is required",
        "file does not exist",
        "文件不存在",
        "unavailable",
    )
    return any(marker in text for marker in failure_markers)


def _extract_page_numbers(value: str) -> list[int]:
    import re

    pages: list[int] = []
    for match in re.finditer(r"(?:第\s*|page\s*|p\.?\s*)(\d{1,4})\s*(?:页)?", str(value or ""), flags=re.IGNORECASE):
        try:
            page = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if page > 0 and page not in pages:
            pages.append(page)
    return pages[:12]


def _extract_ranked_labels(value: str) -> list[str]:
    import re

    labels: list[str] = []
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells or set("".join(cells)) <= {"-", " "}:
                continue
            for cell in cells[:3]:
                if _looks_like_label(cell) and cell not in labels:
                    labels.append(cell)
                    break
        else:
            match = re.match(r"^\s*(?:\d+[\.、)]\s*)?([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-]{1,24})", line)
            if match:
                label = match.group(1).strip()
                if _looks_like_label(label) and label not in labels:
                    labels.append(label)
        if len(labels) >= 12:
            break
    return labels


def _looks_like_label(value: str) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 32:
        return False
    blocked = {
        "排名",
        "姓名",
        "部门",
        "职位",
        "城市",
        "薪资",
        "仓库",
        "商品",
        "库存",
        "结果",
        "排名姓名",
    }
    if text in blocked:
        return False
    if set(text) <= {"-", " "}:
        return False
    return True


def _extract_tool_output_field(value: str, labels: tuple[str, ...]) -> str:
    import re

    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = rf"(?:{label_pattern})\s*[:：]\s*([^\s,，;；]+)"
    match = re.search(pattern, str(value or ""), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _diagnostic_int(payload: dict[str, Any], key: str) -> int:
    diagnostics = dict(payload.get("diagnostics") or {})
    try:
        return int(diagnostics.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _commit_result_summary(result: Any) -> dict[str, Any]:
    if result is None:
        return {"applied_count": 0}
    if isinstance(result, list):
        return {"applied_count": len(result)}
    if isinstance(result, dict):
        return {"applied_count": 1, "keys": sorted(str(key) for key in result.keys())}
    return {"applied_count": 1, "result_type": type(result).__name__}


def _memory_commit_state_from_assistant_commit_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {
            "memory_write_allowed": False,
            "session_memory_refresh_applied": False,
            "durable_memory_commit_applied": False,
            "session_memory_chars": 0,
            "durable_saved_count": 0,
        }
    session_memory_chars = _safe_int(result.get("session_memory_chars"))
    durable_saved_count = _safe_int(result.get("durable_saved_count"))
    return {
        "memory_write_allowed": True,
        "session_memory_refresh_applied": session_memory_chars > 0,
        "durable_memory_commit_applied": durable_saved_count >= 0,
        "session_memory_chars": session_memory_chars,
        "durable_saved_count": durable_saved_count,
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _match_bundle_ordinal_for_tool_observation(
    *,
    bundle_items: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
    executed_ordinals: list[int],
) -> int:
    normalized_tool = str(tool_name or "").strip()
    if not normalized_tool or not bundle_items:
        return 0
    normalized_path = str(tool_args.get("path") or "").strip()
    normalized_query = str(tool_args.get("query") or "").strip().lower()
    matching_items = [
        dict(item)
        for item in bundle_items
        if str(item.get("required_tool") or "").strip() == normalized_tool
    ]
    if not matching_items:
        return 0
    if normalized_path:
        for item in matching_items:
            binding = item.get("target_binding")
            if not isinstance(binding, dict):
                continue
            binding_path = str(dict(binding.get("metadata") or {}).get("path") or "").strip()
            if binding_path and binding_path == normalized_path:
                return _safe_int(item.get("ordinal"))
    if normalized_query:
        for item in matching_items:
            user_text = str(item.get("user_text") or "").strip().lower()
            if user_text and (user_text in normalized_query or normalized_query in user_text):
                return _safe_int(item.get("ordinal"))
    executed = {value for value in executed_ordinals if _safe_int(value) > 0}
    for item in matching_items:
        ordinal = _safe_int(item.get("ordinal"))
        if ordinal > 0 and ordinal not in executed:
            return ordinal
    return _safe_int(matching_items[0].get("ordinal"))
