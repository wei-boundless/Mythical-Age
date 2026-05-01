from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, ToolMessage

from operations import OperationGate, build_default_operation_registry

from ..commit_gate import build_assistant_session_message_commit_decision, build_task_run_final_commit_decision
from .action_request import (
    build_executor_error_observation,
    build_model_response_observation,
    build_tool_action_request,
)
from .checkpoint import RuntimeCheckpoint, RuntimeCheckpointStore
from .context_manager import RuntimeContextManager
from .event_log import RuntimeEventLog
from .loop_control import RuntimeLoopLimits, check_runtime_loop_control
from .model_adoption import build_model_response_runtime_adoption
from .models import RuntimeLoopState, TaskRun
from .stage_projection import StageProjectionCycle
from .state_index import RuntimeStateIndex
from .trace_reader import RuntimeLoopTraceReader
from .tool_adoption import build_tool_request_runtime_adoption


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
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.trace_reader = RuntimeLoopTraceReader(self.state_index, self.event_log, self.checkpoints)
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()

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
        agent_id: str = "agent:main",
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
        checkpoint = self.checkpoints.write(state, event_offset=iteration.offset)
        checkpoint_event = self.event_log.append(
            task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
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
        assistant_message_committer: Callable[[dict[str, Any]], Any] | None = None,
        tool_runtime_executor: Any | None = None,
        tool_instances: list[Any] | None = None,
        agent_capability_profile: Any | None = None,
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
        )
        task_operation = dict(chain_runtime.get("task_operation") or {})
        task_contract = dict(task_operation.get("task_contract") or {})
        memory_view = dict(chain_runtime.get("memory_runtime_view") or {})
        context_policy = dict(chain_runtime.get("context_policy_result") or {})

        task_contract_ref = str(task_contract.get("task_id") or task_id)
        task_event = self.event_log.append(
            state.task_run_id,
            "task_contract_built",
            payload={
                "task_contract": task_contract,
                "source": source,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": task_event.to_dict()}
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
            step_count=0,
            agent_id=state.agent_id,
            agent_profile_id=state.agent_profile_id,
            runtime_lane=state.runtime_lane,
            task_agent_binding_ref=state.task_agent_binding_ref,
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
            agent_capability_profile=agent_capability_profile,
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
        pending_tool_calls: list[dict[str, Any]] = []
        assistant_tool_call_content = ""
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
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
            runtime_events = await self._events_from_executor_event(
                state.task_run_id,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=resource_policy,
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
                        tool_messages.append(
                            ToolMessage(
                                content=str(observation_payload.get("result") or ""),
                                tool_call_id=str(observation_payload.get("tool_call_id") or observation_ref),
                            )
                        )
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
            yield event

        turn_count = 1
        model_call_count = 1
        followup_messages: list[Any] = []
        if pending_tool_calls and tool_messages and terminal_reason == "completed":
            followup_messages = [
                *list(context_snapshot.model_messages),
                AIMessage(content=assistant_tool_call_content, tool_calls=pending_tool_calls),
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
                step_count=max(0, turn_count - 1),
                agent_id=state.agent_id,
                agent_profile_id=state.agent_profile_id,
                runtime_lane=state.runtime_lane,
                task_agent_binding_ref=state.task_agent_binding_ref,
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
                    "step_count": max(0, turn_count - 1),
                    "tool_result_count": len([item for item in followup_messages if isinstance(item, ToolMessage)]),
                },
            )
            yield {"type": "runtime_loop_event", "event": followup_event.to_dict()}
            next_pending_tool_calls: list[dict[str, Any]] = []
            next_assistant_tool_call_content = ""
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
                runtime_events = await self._events_from_executor_event(
                    state.task_run_id,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
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
                            next_tool_messages.append(
                                ToolMessage(
                                    content=str(observation_payload.get("result") or ""),
                                    tool_call_id=str(observation_payload.get("tool_call_id") or observation_ref),
                                )
                            )
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
                yield event
            if next_pending_tool_calls and next_tool_messages and terminal_reason == "completed":
                followup_messages = [
                    *followup_messages,
                    AIMessage(
                        content=next_assistant_tool_call_content,
                        tool_calls=next_pending_tool_calls,
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
        assistant_commit = build_assistant_session_message_commit_decision(
            session_id=session_id,
            task_run_id=terminal_state.task_run_id,
            task_id=task_id,
            content=final_content,
            **final_answer_metadata,
        )
        assistant_commit_applied = False
        assistant_commit_result: Any = None
        if assistant_commit.commit_allowed and assistant_message_committer is not None:
            assistant_commit_result = assistant_message_committer(dict(assistant_commit.commit_candidate.payload))
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
        if terminal_reason != "completed" and final_content:
            yield {
                "type": "done",
                "content": final_content,
                "main_context": {},
                "task_summary_refs": [],
                **final_answer_metadata,
                "persist_policy": "progress_only",
                "terminal_reason": terminal_reason,
            }
        final_commit = build_task_run_final_commit_decision(
            task_run_id=terminal_state.task_run_id,
            task_id=task_id,
            terminal_reason=terminal_state.terminal_reason,
            final_content_chars=len(final_content),
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
        terminal_state = RuntimeLoopState(
            task_run_id=terminal_state.task_run_id,
            status=terminal_state.status,
            turn_count=turn_count,
            step_count=max(0, turn_count - 1),
            current_step_id=terminal_state.current_step_id,
            agent_id=terminal_state.agent_id,
            agent_profile_id=terminal_state.agent_profile_id,
            runtime_lane=terminal_state.runtime_lane,
            task_agent_binding_ref=terminal_state.task_agent_binding_ref,
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
        checkpoint = self.checkpoints.write(state, event_offset=event_offset)
        return self.event_log.append(
            state.task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )

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

            action_request = build_tool_action_request(task_run_id, event)
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
                max_chars = int(dict(gate_result.diagnostics or {}).get("max_result_size_chars") or 0)
                observation = await tool_runtime_executor.run(
                    task_run_id=task_run_id,
                    action_request=action_request,
                    directive=tool_directive,
                    max_result_size_chars=max_chars,
                )
                context_record = runtime_context_manager.record_observation(observation)
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
                    },
                )
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
                    },
                )
                events.extend([tool_result_event, observation_event])
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


def _runtime_budget_exhausted_answer_metadata() -> dict[str, str]:
    return {
        "answer_channel": "answer_candidate",
        "answer_source": "runtime_loop_control",
        "answer_canonical_state": "progress_only",
        "answer_persist_policy": "persist_debug_only",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "runtime_budget_exhausted",
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
