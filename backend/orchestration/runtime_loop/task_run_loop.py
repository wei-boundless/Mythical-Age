from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from capability_system import build_default_operation_registry
from capability_system.local_mcp_registry import get_local_mcp_unit, get_local_mcp_unit_for_template
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.resource_gate import OperationGate, OperationGatePipelineContext
from project_layout import ProjectLayout
from output_boundary.boundary import AssistantOutputBoundary
from tasks.flow_registry import TaskFlowRegistry
from tasks.coordination_graph_compiler import compile_coordination_graph_spec
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
from capability_system.tool_authorization import resolve_tool_operation_id

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
from .coordination_flow import (
    build_coordination_flow_state,
    build_coordination_node_status_map,
    finalize_coordination_flow_state,
)
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
from .langgraph_coordination_runner import LangGraphCoordinationRunner
from .model_adoption import build_model_response_runtime_adoption
from .models import (
    AgentHandoffEnvelope,
    AgentRun,
    AgentRunResult,
    CoordinationMergeResult,
    CoordinationNodeRun,
    CoordinationRun,
    RuntimeLoopState,
    TaskRun,
)
from .observation_aggregator import ObservationAggregation, ObservationAggregator
from .safety import build_task_safety_validators
from .stage_projection import StageProjectionCycle
from .state_index import RuntimeStateIndex
from .trace_reader import RuntimeLoopTraceReader
from .tool_adoption import build_tool_request_runtime_adoption
from .tool_repetition_guard import ToolRepetitionGuard
from ..worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from ..worker_agent_factory import WorkerAgentFactory
from evidence import MCPExecutionPlan, MCPRequest


@dataclass(frozen=True, slots=True)
class TaskRunLoopStartResult:
    task_run: TaskRun
    agent_run: AgentRun
    coordination_run: CoordinationRun | None
    loop_state: RuntimeLoopState
    checkpoint: RuntimeCheckpoint
    events: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_run": self.task_run.to_dict(),
            "agent_run": self.agent_run.to_dict(),
            "coordination_run": self.coordination_run.to_dict() if self.coordination_run is not None else None,
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
        backend_dir: Path | None = None,
        operation_gate: OperationGate | None = None,
        limits: RuntimeLoopLimits | None = None,
        evidence_orchestrator: Any | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        if backend_dir is None:
            self.backend_dir = ProjectLayout.from_backend_dir(self.root_dir).backend_dir
        else:
            self.backend_dir = Path(backend_dir)
        self.event_log = RuntimeEventLog(self.root_dir)
        self.checkpoints = RuntimeCheckpointStore(self.root_dir)
        self.execution_store = RuntimeExecutionStore(self.root_dir)
        self.state_index = RuntimeStateIndex(self.root_dir)
        self.trace_reader = RuntimeLoopTraceReader(self.state_index, self.event_log, self.checkpoints)
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()
        self.task_flow_registry = TaskFlowRegistry(self.backend_dir)
        self.agent_registry = AgentRegistry(self.backend_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.backend_dir)
        self.worker_agent_factory = WorkerAgentFactory(self.backend_dir)
        self.langgraph_coordination_runner = LangGraphCoordinationRunner()
        self.evidence_orchestrator = evidence_orchestrator

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
        adoption_mode: str = "adopt_existing",
        coordination_task_ref: str = "",
        coordinator_agent_id: str = "",
        topology_template_id: str = "",
        communication_protocol_id: str = "",
        handoff_policy: str = "",
        failure_policy: str = "",
        merge_policy: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> TaskRunLoopStartResult:
        now = time.time()
        task_run_id = f"taskrun:{session_id}:{task_id}:{uuid.uuid4().hex[:8]}"
        agent_run_id = f"agrun:{task_run_id}:main"
        coordination_run = (
            CoordinationRun(
                coordination_run_id=f"coordrun:{task_run_id}:primary",
                task_run_id=task_run_id,
                coordination_task_ref=coordination_task_ref,
                coordinator_agent_id=coordinator_agent_id or agent_id,
                topology_template_id=topology_template_id,
                communication_protocol_id=communication_protocol_id,
                handoff_policy=handoff_policy,
                failure_policy=failure_policy,
                merge_policy=merge_policy,
                status="running",
                created_at=now,
                updated_at=now,
                diagnostics={
                    "coordination_candidate": True,
                    "task_agent_binding_ref": task_agent_binding_ref,
                },
            )
            if coordination_task_ref
            else None
        )
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
                "single_agent": coordination_run is None,
                "multi_agent_enabled": coordination_run is not None,
                "coordination_task_ref": coordination_task_ref,
                "adoption_mode": adoption_mode,
            },
            refs={"task_contract_ref": task_contract_ref},
        )
        agent_run = AgentRun(
            agent_run_id=agent_run_id,
            task_run_id=task_run_id,
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            role="main_executor" if coordination_run is None else "coordinator",
            spawn_mode=adoption_mode,
            context_scope="task_default",
            runtime_lane=runtime_lane,
            coordination_run_ref=coordination_run.coordination_run_id if coordination_run is not None else "",
            status="running",
            created_at=now,
            updated_at=now,
            diagnostics={
                "task_agent_binding_ref": task_agent_binding_ref,
                "skill_workflow_ref": skill_workflow_ref,
                "health_issue_ref": health_issue_ref,
            },
        )
        agent_run_event = self.event_log.append(
            task_run_id,
            "agent_run_created",
            payload={"agent_run": agent_run.to_dict()},
            refs={"agent_run_ref": agent_run.agent_run_id},
        )
        coordination_run_event = None
        if coordination_run is not None:
            coordination_run_event = self.event_log.append(
                task_run_id,
                "coordination_run_created",
                payload={"coordination_run": coordination_run.to_dict()},
                refs={"coordination_run_ref": coordination_run.coordination_run_id},
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
            agent_runs=(agent_run,),
            coordination_runs=((coordination_run,) if coordination_run is not None else ()),
        )
        checkpoint_event = self.event_log.append(
            task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "execution_summary": checkpoint.execution_summary,
                "runtime_objects_summary": checkpoint.runtime_objects_summary,
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
                "single_agent": coordination_run is None,
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_lane": runtime_lane,
                "task_agent_binding_ref": task_agent_binding_ref,
                "skill_workflow_ref": skill_workflow_ref,
                "health_issue_ref": health_issue_ref,
                "main_agent_run_ref": agent_run.agent_run_id,
                "adoption_mode": adoption_mode,
                "coordination_task_ref": coordination_task_ref,
                "multi_agent_enabled": coordination_run is not None,
                "loop_limits": self.limits.to_dict(),
                **dict(diagnostics or {}),
            },
        )
        self.state_index.upsert_task_run(task_run)
        self.state_index.upsert_agent_run(agent_run)
        if coordination_run is not None:
            self.state_index.upsert_coordination_run(coordination_run)
        ordered_events = [started.to_dict(), agent_run_event.to_dict()]
        if coordination_run_event is not None:
            ordered_events.append(coordination_run_event.to_dict())
        ordered_events.extend((iteration.to_dict(), checkpoint_event.to_dict()))
        return TaskRunLoopStartResult(
            task_run=task_run,
            agent_run=agent_run,
            coordination_run=coordination_run,
            loop_state=state,
            checkpoint=checkpoint,
            events=tuple(ordered_events),
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
            "agent_run": start.agent_run.to_dict(),
            "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
            "checkpoint": start.checkpoint.to_dict(),
            "events": [dict(item) for item in start.events],
        }
        for event in start.events:
            yield {"type": "runtime_loop_event", "event": dict(event)}

        chain_runtime = agent_runtime_chain.build_runtime(
            session_id=session_id,
            task_id=task_id,
            turn_id=str(dict(task_selection or {}).get("turn_id") or ""),
            message=user_message,
            source=source,
            task_selection=dict(task_selection or {}),
            agent_runtime_profile=agent_runtime_profile,
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
        task_execution_policy_payload = dict(task_operation.get("task_execution_policy") or {})
        task_agent_adoption_plan_payload = dict(task_operation.get("task_agent_adoption_plan") or {})
        task_memory_request_profile_payload = dict(task_operation.get("task_memory_request_profile") or {})
        task_communication_protocol_payload = dict(task_operation.get("task_communication_protocol") or {})
        coordination_task_payload = dict(task_operation.get("coordination_task_record") or {})
        task_body_orchestration_payload = dict(chain_runtime.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {})
        agent_runtime_spec_payload = dict(chain_runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
        memory_view = dict(chain_runtime.get("memory_runtime_view") or {})
        context_policy = dict(chain_runtime.get("context_policy_result") or {})
        adoption_mode = str(task_agent_adoption_plan_payload.get("adoption_mode") or "adopt_existing")
        effective_limits = _runtime_limits_from_task_operation(task_operation, fallback=self.limits)
        result_refs: list[str] = []
        final_main_context: dict[str, Any] = {}
        final_task_summary_refs: list[dict[str, Any]] = []

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
                "task_execution_policy": task_execution_policy_payload,
                "task_agent_adoption_plan": task_agent_adoption_plan_payload,
                "task_memory_request_profile": task_memory_request_profile_payload,
                "task_communication_protocol": task_communication_protocol_payload,
                "coordination_task_record": coordination_task_payload,
                "task_body_orchestration": task_body_orchestration_payload,
                "agent_runtime_spec": agent_runtime_spec_payload,
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
                "task_execution_policy_ref": str(task_execution_policy_payload.get("execution_policy_id") or task_execution_policy_payload.get("plan_id") or ""),
                "task_agent_adoption_plan_ref": str(task_agent_adoption_plan_payload.get("plan_id") or ""),
                "task_memory_request_profile_ref": str(task_memory_request_profile_payload.get("profile_id") or ""),
                "task_communication_protocol_ref": str(task_communication_protocol_payload.get("protocol_id") or ""),
                "coordination_task_ref": str(coordination_task_payload.get("coordination_task_id") or ""),
                "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
                "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
                "bundle_spec_ref": str(bundle_spec_payload.get("bundle_id") or ""),
                "task_run_ledger_ref": runtime_task_ledger.ledger_id if runtime_task_ledger is not None else "",
            },
        )
        yield {"type": "runtime_loop_event", "event": task_event.to_dict()}
        runtime_object_events = self._sync_runtime_objects_after_task_contract(
            start_result=start,
            event_offset=task_event.offset,
            adoption_mode=adoption_mode,
            task_agent_binding_ref=str(task_execution_assembly_payload.get("task_agent_binding_ref") or ""),
            coordination_task_payload=coordination_task_payload,
            communication_protocol_payload=task_communication_protocol_payload,
            task_agent_adoption_plan_payload=task_agent_adoption_plan_payload,
            effective_limits=effective_limits,
        )
        for runtime_event in runtime_object_events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        current_worker_spawn_results = self.state_index.list_task_worker_spawn_results(state.task_run_id)
        current_worker_agent_runs = [
            item
            for item in self.state_index.list_task_agent_runs(state.task_run_id)
            if str(item.spawn_mode or "") == "worker_spawn"
        ]
        runtime_execution_facts = {
            "worker_spawn_summary": {
                "spawn_request_count": len(self.state_index.list_task_worker_spawn_requests(state.task_run_id)),
                "spawn_result_count": len(current_worker_spawn_results),
                "spawned_agent_ids": [
                    str(item.spawned_agent_id or "")
                    for item in current_worker_spawn_results
                    if str(item.status or "") == "spawned" and str(item.spawned_agent_id or "")
                ],
                "blocked_spawn_count": sum(
                    1 for item in current_worker_spawn_results if str(item.status or "") == "blocked"
                ),
                "worker_agent_run_ids": [
                    str(item.agent_run_id or "")
                    for item in current_worker_agent_runs
                    if str(item.agent_run_id or "")
                ],
            }
        }
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
        query_understanding = dict(task_operation.get("query_understanding") or {})
        retrieval_results: list[dict[str, Any]] | None = None
        if self._should_run_template_mcp_phase(
            query_understanding=query_understanding,
            selected_template_payload=selected_template_payload,
        ):
            mcp_outcome = await self._run_template_mcp_phase(
                task_run_id=state.task_run_id,
                session_id=session_id,
                task_id=task_id,
                user_message=user_message,
                current_turn_context=current_turn_context,
                query_understanding=query_understanding,
                selected_template_payload=selected_template_payload,
                task_contract_ref=task_contract_ref,
                runtime_task_ledger=runtime_task_ledger,
                state=state,
            )
            runtime_task_ledger = mcp_outcome["ledger"]
            state = mcp_outcome["state"]
            retrieval_results = mcp_outcome["retrieval_results"]
            result_refs.extend(list(mcp_outcome["result_refs"]))
            final_main_context.update(dict(mcp_outcome["main_context"]))
            final_task_summary_refs.extend(list(mcp_outcome["task_summary_refs"]))
            for event in mcp_outcome["events"]:
                yield event
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
        stage_projection = projection_cycle.build_from_orchestration(
            task_id=task_id,
            task_body_orchestration=task_body_orchestration_payload,
            agent_runtime_spec=agent_runtime_spec_payload,
        )
        projection_event = self.event_log.append(
            state.task_run_id,
            "stage_projection_built",
            payload={
                "stage_projection": stage_projection.to_dict(),
                "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
                "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            },
            refs={
                "projection_ref": stage_projection.projection_ref,
                "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
                "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
                "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
            },
        )
        yield {"type": "runtime_loop_event", "event": projection_event.to_dict()}

        effective_context_policy = (
            self._rebuild_context_policy_with_retrieval(
                agent_runtime_chain=agent_runtime_chain,
                session_id=session_id,
                user_message=user_message,
                memory_intent=memory_intent,
                task_operation=task_operation,
                retrieval_results=retrieval_results,
            )
            if retrieval_results
            else context_policy
        )
        context_snapshot = runtime_context_manager.prepare_model_context(
            session_id=session_id,
            task_id=task_id,
            user_message=user_message,
            history=history,
            memory_intent=memory_intent,
            memory_runtime_view=memory_view,
            context_policy_result=effective_context_policy,
            stage_projection_snapshot=stage_projection,
            runtime_execution_facts=runtime_execution_facts,
        )
        context_event = self.event_log.append(
            state.task_run_id,
            "context_snapshot_built",
            payload={
                "context_snapshot": context_snapshot.to_dict(),
                "context_policy_result": effective_context_policy,
            },
            refs={
                "memory_runtime_view_ref": str(memory_view.get("view_id") or ""),
                "context_snapshot_ref": context_snapshot.snapshot_id,
                "context_policy_ref": context_snapshot.context_policy_ref,
                "projection_ref": stage_projection.projection_ref,
                "prompt_manifest_ref": stage_projection.prompt_manifest_ref,
                "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
                "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
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
                "effective_loop_limits": effective_limits.to_dict(),
                "runtime_context_manager_applied": True,
                "stage_projection_cycle_applied": True,
                "task_body_orchestration_ref": str(task_body_orchestration_payload.get("orchestration_id") or ""),
                "agent_runtime_spec_ref": str(agent_runtime_spec_payload.get("runtime_spec_id") or ""),
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
            limits=effective_limits,
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
                start_agent_run=start.agent_run,
                start_coordination_run=start.coordination_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                final_content="",
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
                start_agent_run=start.agent_run,
                start_coordination_run=start.coordination_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                final_content="",
                diagnostics={"operation_gate_reason": gate_result.reason},
            )
            return

        final_content = ""
        final_answer_metadata: dict[str, Any] = {}
        terminal_reason = "completed"
        if final_main_context and self._final_main_context_can_finalize(
            selected_template_payload=selected_template_payload,
            retrieval_results=retrieval_results,
        ):
            final_content = str(final_main_context.get("answer") or "")
            if not final_content:
                final_content = str(
                    final_main_context.get("resolved_answer")
                    or final_main_context.get("canonical_answer")
                    or ""
                )
            if not final_content and final_task_summary_refs:
                final_content = str(final_task_summary_refs[0].get("summary") or "")
            if final_content:
                final_answer_metadata = {
                    "answer_channel": "answer_candidate",
                    "answer_source": str(final_main_context.get("answer_source") or "runtime_mcp"),
                    "answer_canonical_state": "stable_answer",
                    "answer_persist_policy": "persist_canonical",
                    "answer_finalization_policy": "none",
                    "answer_fallback_reason": "",
                }
        preserve_final_answer_metadata = bool(final_content and final_answer_metadata)

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
        builtin_tool_lane_finalized = False
        if not final_content:
            executor_event = self.event_log.append(
                state.task_run_id,
                "executor_started",
                payload={"executor_type": "model", "runtime_channel": "single_agent_runtime"},
                refs={"task_contract_ref": task_contract_ref, "directive_ref": directive.directive_id},
            )
            yield {"type": "runtime_loop_event", "event": executor_event.to_dict()}
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
                            builtin_tool_lane_answer_metadata = None
                            if _template_allows_tool_observation_finalization(selected_template_payload):
                                builtin_tool_lane_answer_metadata = _builtin_tool_lane_answer_from_observation(
                                    user_message=user_message,
                                    observation_payload=observation_payload,
                                )
                            if builtin_tool_lane_answer_metadata is not None:
                                final_content = builtin_tool_lane_answer_metadata["content"]
                                final_answer_metadata = {
                                    "answer_channel": builtin_tool_lane_answer_metadata["answer_channel"],
                                    "answer_source": builtin_tool_lane_answer_metadata["answer_source"],
                                    "answer_canonical_state": builtin_tool_lane_answer_metadata["answer_canonical_state"],
                                    "answer_persist_policy": builtin_tool_lane_answer_metadata["answer_persist_policy"],
                                    "answer_finalization_policy": builtin_tool_lane_answer_metadata["answer_finalization_policy"],
                                    "answer_fallback_reason": builtin_tool_lane_answer_metadata["answer_fallback_reason"],
                                }
                                builtin_tool_lane_finalized = len(pending_tool_calls) <= 1 and not current_bundle_items
                            operation_id = resolve_tool_operation_id(
                                str(observation_payload.get("tool_name") or ""),
                                definitions_by_name=self.tool_authorization_index.definitions_by_name,
                            )
                            current_step = current_task_step_run(runtime_task_ledger)
                            if (
                                runtime_task_ledger is not None
                                and current_step is not None
                                and current_step.status == "running"
                                and current_step.executor_type in {"tool", "mcp", "agent"}
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
                    elif runtime_event.event_type == "loop_error":
                        terminal_reason = "executor_failed"
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
                    if not preserve_final_answer_metadata:
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
                elif event.get("type") == "error":
                    terminal_reason = "executor_failed"
                if event.get("type") != "done":
                    yield event

        turn_count = 1
        model_call_count = 1
        followup_messages: list[Any] = []
        if len(pending_tool_calls) > 1 and terminal_reason == "completed":
            builtin_tool_lane_finalized = False
            final_content = ""
            final_answer_metadata = {}
            preserve_final_answer_metadata = False
        if pending_tool_calls and tool_messages and terminal_reason == "completed" and not builtin_tool_lane_finalized:
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
                limits=effective_limits,
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
                                and current_step.executor_type in {"tool", "mcp", "agent"}
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
                                and current_step.executor_type in {"tool", "mcp", "agent"}
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
                            and current_step.executor_type in {"tool", "mcp", "agent"}
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
                    if not preserve_final_answer_metadata:
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
                    final_content = _build_repeated_tool_halt_message(
                        tool_observation_count=tool_observation_count,
                    )
                    final_answer_metadata = _repeated_tool_halt_answer_metadata()
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

        artifact_validation = _validate_required_artifact_file(
            root_dir=self.root_dir,
            selected_template_payload=selected_template_payload,
            final_content=final_content,
            result_refs=tuple(result_refs),
            event_log_events=[item.to_dict() for item in self.event_log.list_events(state.task_run_id)],
        )
        if (
            not artifact_validation["passed"]
            and terminal_reason == "completed"
            and _requires_write_file_artifact(selected_template_payload)
            and tool_runtime_executor is not None
        ):
            repair_tool_instances = [
                tool
                for tool in list(runtime_tool_instances)
                if str(getattr(tool, "name", "") or "").strip() == "write_file"
            ]
            if not repair_tool_instances:
                repair_tool_instances = list(runtime_tool_instances)
            repair_attempt = 0
            while (
                not artifact_validation["passed"]
                and terminal_reason == "completed"
                and repair_attempt < 2
            ):
                repair_attempt += 1
                repair_messages = _build_required_artifact_write_messages(
                    model_messages=list(context_snapshot.model_messages),
                    user_message=user_message,
                    task_spec_payload=task_spec_payload,
                    final_content=final_content,
                    selected_template_payload=selected_template_payload,
                )
                repair_event = self.event_log.append(
                    state.task_run_id,
                    "required_artifact_write_repair_started",
                    payload={
                        "attempt": repair_attempt,
                        "reason": artifact_validation["reason"],
                        "target_path": _required_artifact_target_path(task_spec_payload=task_spec_payload, user_message=user_message),
                        "final_content_chars": len(final_content),
                        "allowed_tool_names": [str(getattr(tool, "name", "") or "") for tool in repair_tool_instances],
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": repair_event.to_dict()}
                repair_pending_tool_calls: list[dict[str, Any]] = []
                repair_assistant_tool_call_content = ""
                repair_assistant_tool_call_kwargs: dict[str, Any] = {}
                async for event in model_response_executor.stream(
                    user_message=user_message,
                    model_messages=repair_messages,
                    directive=directive,
                    tool_instances=repair_tool_instances,
                ):
                    if event.get("type") == "tool_call_requested":
                        tool_call = dict(event.get("tool_call") or {})
                        if tool_call:
                            repair_pending_tool_calls.append(tool_call)
                        repair_assistant_tool_call_content = str(
                            event.get("assistant_content") or repair_assistant_tool_call_content
                        )
                        event_kwargs = dict(event.get("assistant_additional_kwargs") or {})
                        if event_kwargs:
                            repair_assistant_tool_call_kwargs.update(event_kwargs)
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
                                operation_id = resolve_tool_operation_id(
                                    str(observation_payload.get("tool_name") or ""),
                                    definitions_by_name=self.tool_authorization_index.definitions_by_name,
                                )
                                current_step = current_task_step_run(runtime_task_ledger)
                                if (
                                    runtime_task_ledger is not None
                                    and current_step is not None
                                    and current_step.status == "running"
                                    and current_step.executor_type in {"tool", "mcp", "agent"}
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
                                            "transition_reason": "required_artifact_write_repair",
                                            "operation_id": operation_id,
                                            "repair_attempt": repair_attempt,
                                        },
                                    )
                                    completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                                    if completed_step is not None:
                                        step_completed_event = self._record_task_run_step_event(
                                            state.task_run_id,
                                            event_type="step_completed",
                                            step_run=completed_step,
                                            ledger=runtime_task_ledger,
                                            reason="required_artifact_write_repair",
                                            refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                        )
                                        yield {"type": "runtime_loop_event", "event": step_completed_event.to_dict()}
                                    runtime_task_ledger = advance_task_run_ledger(
                                        runtime_task_ledger,
                                        started_at=time.time(),
                                        diagnostics={
                                            "transition_reason": "required_artifact_write_repair",
                                            "operation_id": operation_id,
                                            "repair_attempt": repair_attempt,
                                        },
                                    )
                                    ledger_event = self._record_task_run_ledger_updated(
                                        state.task_run_id,
                                        ledger=runtime_task_ledger,
                                        reason="required_artifact_write_repair",
                                        refs={"operation_id": operation_id, "observation_ref": observation_ref},
                                    )
                                    yield {"type": "runtime_loop_event", "event": ledger_event.to_dict()}
                                    state = self._state_with_task_run_ledger(
                                        state,
                                        runtime_task_ledger,
                                        result_refs=result_refs,
                                        diagnostics={"last_step_transition": "required_artifact_write_repair"},
                                    )
                                    checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                                    yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                            elif observation.get("observation_type") == "executor_error":
                                terminal_reason = "executor_failed"
                        elif runtime_event.event_type == "output_boundary_applied":
                            result_refs.append(f"output_boundary:{runtime_event.event_id}")
                        elif runtime_event.event_type == "commit_gate_checked":
                            commit_ref = str(
                                runtime_event.refs.get("commit_gate_ref")
                                or dict(runtime_event.payload.get("commit_gate") or {}).get("gate_id")
                                or runtime_event.event_id
                            )
                            result_refs.append(f"commit_gate:{commit_ref}")
                        elif runtime_event.event_type == "loop_error":
                            terminal_reason = "executor_failed"
                        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                    if event.get("type") == "done" and not repair_pending_tool_calls:
                        final_content = str(event.get("content") or final_content)
                        final_answer_metadata = {
                            "answer_channel": str(event.get("answer_channel") or final_answer_metadata.get("answer_channel") or ""),
                            "answer_source": str(event.get("answer_source") or final_answer_metadata.get("answer_source") or ""),
                            "answer_canonical_state": str(event.get("answer_canonical_state") or final_answer_metadata.get("answer_canonical_state") or ""),
                            "answer_persist_policy": str(event.get("answer_persist_policy") or final_answer_metadata.get("answer_persist_policy") or ""),
                            "answer_finalization_policy": str(event.get("answer_finalization_policy") or final_answer_metadata.get("answer_finalization_policy") or ""),
                            "answer_fallback_reason": str(event.get("answer_fallback_reason") or final_answer_metadata.get("answer_fallback_reason") or ""),
                        }
                    elif event.get("type") == "error":
                        terminal_reason = "executor_failed"
                    if event.get("type") != "done":
                        yield event
                artifact_validation = _validate_required_artifact_file(
                    root_dir=self.root_dir,
                    selected_template_payload=selected_template_payload,
                    final_content=final_content,
                    result_refs=tuple(result_refs),
                    event_log_events=[item.to_dict() for item in self.event_log.list_events(state.task_run_id)],
                )
                repair_done_event = self.event_log.append(
                    state.task_run_id,
                    "required_artifact_write_repair_finished",
                    payload={
                        "attempt": repair_attempt,
                        "validation": artifact_validation,
                        "tool_call_count": len(repair_pending_tool_calls),
                        "assistant_content_chars": len(repair_assistant_tool_call_content),
                        "assistant_additional_kwargs": repair_assistant_tool_call_kwargs,
                    },
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": repair_done_event.to_dict()}

        if (
            artifact_validation["passed"]
            and terminal_reason == "executor_failed"
            and _requires_write_file_artifact(selected_template_payload)
        ):
            terminal_reason = "completed"
            final_content = _build_artifact_success_fallback_answer(
                selected_template_payload=selected_template_payload,
                artifact_validation=artifact_validation,
                final_task_summary_refs=final_task_summary_refs,
                final_main_context=final_main_context,
            )
            final_answer_metadata = {
                **_artifact_success_fallback_answer_metadata(),
            }
            recovery_event = self.event_log.append(
                state.task_run_id,
                "artifact_success_fallback_finalized",
                payload={
                    "reason": "model_followup_failed_after_required_artifact_write",
                    "artifact_validation": artifact_validation,
                    "final_content_chars": len(final_content),
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": recovery_event.to_dict()}

        if not artifact_validation["passed"] and terminal_reason == "completed":
            terminal_reason = "artifact_validation_failed"
            final_answer_metadata = {
                **dict(final_answer_metadata),
                "answer_channel": "orchestration_fail_closed",
                "answer_source": "task_artifact_validation",
                "answer_canonical_state": "artifact_validation_failed",
            }
            final_content = (
                "任务未通过验收：要求产出真实文件，但未检测到合格的 write_file 产物。"
                f" 原因：{artifact_validation['reason']}"
            )

        artifact_validation_event = self.event_log.append(
            state.task_run_id,
            "task_artifact_validation_checked",
            payload={"validation": artifact_validation},
            refs={"task_contract_ref": task_contract_ref},
        )
        yield {"type": "runtime_loop_event", "event": artifact_validation_event.to_dict()}

        terminal_state = state.with_status(
            "completed" if terminal_reason == "completed" else "failed",
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            diagnostics={"final_content_chars": len(final_content), "artifact_validation": artifact_validation},
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
            start_agent_run=start.agent_run,
            start_coordination_run=start.coordination_run,
            task_contract_ref=task_contract_ref,
            terminal_state=terminal_state,
            checkpoint_event=checkpoint_event,
            final_content=final_content,
            diagnostics={"final_content_chars": len(final_content)},
        )

    def _upsert_finished_task_run(
        self,
        *,
        start_task_run: TaskRun,
        start_agent_run: AgentRun,
        start_coordination_run: CoordinationRun | None,
        task_contract_ref: str,
        terminal_state: RuntimeLoopState,
        checkpoint_event: Any,
        final_content: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        existing_task_run = self.state_index.get_task_run(start_task_run.task_run_id)
        base_task_run = existing_task_run or start_task_run
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=base_task_run.task_run_id,
                session_id=base_task_run.session_id,
                task_id=base_task_run.task_id,
                task_contract_ref=task_contract_ref,
                agent_id=base_task_run.agent_id,
                agent_profile_id=base_task_run.agent_profile_id,
                runtime_lane=base_task_run.runtime_lane,
                status=terminal_state.status,
                created_at=base_task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                terminal_reason=terminal_state.terminal_reason,
                diagnostics={
                    **dict(base_task_run.diagnostics),
                    **dict(diagnostics or {}),
                },
            )
        )
        agent_run_result = AgentRunResult(
            agent_run_result_id=f"agresult:{start_agent_run.agent_run_id}",
            agent_run_id=start_agent_run.agent_run_id,
            task_run_id=start_agent_run.task_run_id,
            agent_id=start_agent_run.agent_id,
            status="completed" if terminal_state.status == "completed" else "failed",
            output_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
            summary=final_content[:280],
            created_at=time.time(),
            diagnostics={
                "terminal_reason": terminal_state.terminal_reason,
                "task_contract_ref": task_contract_ref,
            },
        )
        self.state_index.upsert_agent_run(
            AgentRun(
                agent_run_id=start_agent_run.agent_run_id,
                task_run_id=start_agent_run.task_run_id,
                agent_id=start_agent_run.agent_id,
                agent_profile_id=start_agent_run.agent_profile_id,
                role=start_agent_run.role,
                spawn_mode=start_agent_run.spawn_mode,
                context_scope=start_agent_run.context_scope,
                runtime_lane=start_agent_run.runtime_lane,
                parent_agent_run_ref=start_agent_run.parent_agent_run_ref,
                coordination_run_ref=start_agent_run.coordination_run_ref,
                status="completed" if terminal_state.status == "completed" else "failed",
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                result_ref=agent_run_result.agent_run_result_id,
                created_at=start_agent_run.created_at,
                updated_at=time.time(),
                diagnostics={
                    **dict(start_agent_run.diagnostics),
                    "terminal_reason": terminal_state.terminal_reason,
                },
            )
        )
        self.state_index.upsert_agent_run_result(agent_run_result)
        current_agent_runs = self.state_index.list_task_agent_runs(start_task_run.task_run_id)
        for agent_run in current_agent_runs:
            if agent_run.agent_run_id == start_agent_run.agent_run_id:
                continue
            participant_status = "completed" if terminal_state.status == "completed" else "failed"
            participant_result = AgentRunResult(
                agent_run_result_id=f"agresult:{agent_run.agent_run_id}",
                agent_run_id=agent_run.agent_run_id,
                task_run_id=agent_run.task_run_id,
                agent_id=agent_run.agent_id,
                status=participant_status,
                output_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                summary=final_content[:200],
                created_at=time.time(),
                diagnostics={
                    "terminal_reason": terminal_state.terminal_reason,
                    "derived_from_coordination_finalize": True,
                    "parent_agent_run_ref": agent_run.parent_agent_run_ref,
                },
            )
            self.state_index.upsert_agent_run_result(participant_result)
            self.state_index.upsert_agent_run(
                AgentRun(
                    agent_run_id=agent_run.agent_run_id,
                    task_run_id=agent_run.task_run_id,
                    agent_id=agent_run.agent_id,
                    agent_profile_id=agent_run.agent_profile_id,
                    role=agent_run.role,
                    spawn_mode=agent_run.spawn_mode,
                    context_scope=agent_run.context_scope,
                    runtime_lane=agent_run.runtime_lane,
                    parent_agent_run_ref=agent_run.parent_agent_run_ref,
                    coordination_run_ref=agent_run.coordination_run_ref,
                    status=participant_status,
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                    result_ref=participant_result.agent_run_result_id,
                    created_at=agent_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(agent_run.diagnostics),
                        "terminal_reason": terminal_state.terminal_reason,
                    },
                )
            )
        current_coordination_runs = self.state_index.list_task_coordination_runs(start_task_run.task_run_id)
        target_coordination_run = current_coordination_runs[0] if current_coordination_runs else start_coordination_run
        worker_spawn_results = self.state_index.list_task_worker_spawn_results(start_task_run.task_run_id)
        worker_agent_runs = [
            item
            for item in self.state_index.list_task_agent_runs(start_task_run.task_run_id)
            if str(item.spawn_mode or "") == "worker_spawn"
        ]
        worker_spawn_summary = {
            "spawn_request_count": len(self.state_index.list_task_worker_spawn_requests(start_task_run.task_run_id)),
            "spawn_result_count": len(worker_spawn_results),
            "spawned_agent_ids": [
                str(item.spawned_agent_id or "")
                for item in worker_spawn_results
                if str(item.status or "") == "spawned" and str(item.spawned_agent_id or "")
            ],
            "blocked_spawn_count": sum(1 for item in worker_spawn_results if str(item.status or "") == "blocked"),
            "worker_agent_run_ids": [str(item.agent_run_id or "") for item in worker_agent_runs if str(item.agent_run_id or "")],
        }
        if target_coordination_run is not None:
            finalized_flow, unresolved_issue_refs = finalize_coordination_flow_state(
                dict(target_coordination_run.diagnostics.get("coordination_flow") or {}),
                accepted=terminal_state.status == "completed",
                final_result_ref=agent_run_result.agent_run_result_id,
            )
            finalized_node_status_map = build_coordination_node_status_map(finalized_flow)
            merge_result = CoordinationMergeResult(
                merge_result_id=f"coordmerge:{target_coordination_run.coordination_run_id}",
                coordination_run_id=target_coordination_run.coordination_run_id,
                task_run_id=target_coordination_run.task_run_id,
                merge_policy=target_coordination_run.merge_policy or "coordinator_final_merge",
                final_result_ref=agent_run_result.agent_run_result_id,
                accepted=terminal_state.status == "completed",
                unresolved_issue_refs=unresolved_issue_refs,
                created_at=time.time(),
                diagnostics={
                    "terminal_reason": terminal_state.terminal_reason,
                    "final_agent_run_result_ref": agent_run_result.agent_run_result_id,
                    "coordination_flow": finalized_flow,
                },
            )
            self.state_index.upsert_coordination_merge_result(merge_result)
            self.event_log.append(
                start_task_run.task_run_id,
                "coordination_merge_result_created",
                payload={"coordination_merge_result": merge_result.to_dict()},
                refs={"coordination_merge_result_ref": merge_result.merge_result_id},
            )
            if finalized_flow:
                self.event_log.append(
                    start_task_run.task_run_id,
                    "coordination_flow_finalized",
                    payload={"coordination_flow": finalized_flow},
                    refs={"coordination_run_ref": target_coordination_run.coordination_run_id},
                )
            current_node_runs = self.state_index.list_coordination_node_runs(target_coordination_run.coordination_run_id)
            for node_run in current_node_runs:
                node_flow = dict(finalized_node_status_map.get(node_run.node_id) or {})
                updated_node_run = CoordinationNodeRun(
                    node_run_id=node_run.node_run_id,
                    coordination_run_id=node_run.coordination_run_id,
                    task_run_id=node_run.task_run_id,
                    node_id=node_run.node_id,
                    role=node_run.role,
                    assigned_agent_id=node_run.assigned_agent_id,
                    assigned_agent_run_ref=node_run.assigned_agent_run_ref,
                    status=str(node_flow.get("node_run_status") or node_run.status),
                    handoff_count=node_run.handoff_count,
                    latest_handoff_ref=node_run.latest_handoff_ref,
                    created_at=node_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(node_run.diagnostics),
                        "stage_id": str(node_flow.get("stage_id") or node_run.diagnostics.get("stage_id") or ""),
                        "message_type": str(node_flow.get("message_type") or node_run.diagnostics.get("message_type") or ""),
                        "stage_status": str(node_flow.get("stage_status") or node_run.diagnostics.get("stage_status") or ""),
                    },
                )
                self.state_index.upsert_coordination_node_run(updated_node_run)
                self.event_log.append(
                    start_task_run.task_run_id,
                    "coordination_node_run_updated",
                    payload={"coordination_node_run": updated_node_run.to_dict()},
                    refs={"coordination_node_run_ref": updated_node_run.node_run_id},
                )
            self.state_index.upsert_coordination_run(
                CoordinationRun(
                    coordination_run_id=target_coordination_run.coordination_run_id,
                    task_run_id=target_coordination_run.task_run_id,
                    coordination_task_ref=target_coordination_run.coordination_task_ref,
                    coordinator_agent_id=target_coordination_run.coordinator_agent_id,
                    topology_template_id=target_coordination_run.topology_template_id,
                    communication_protocol_id=target_coordination_run.communication_protocol_id,
                    handoff_policy=target_coordination_run.handoff_policy,
                    failure_policy=target_coordination_run.failure_policy,
                    merge_policy=target_coordination_run.merge_policy,
                    status="completed" if terminal_state.status == "completed" else "failed",
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                    latest_merge_result_ref=merge_result.merge_result_id,
                    created_at=target_coordination_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(target_coordination_run.diagnostics),
                        "terminal_reason": terminal_state.terminal_reason,
                        "coordination_flow": finalized_flow,
                        "worker_spawn_summary": worker_spawn_summary,
                    },
                )
            )
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
                    **dict(self.state_index.get_task_run(start_task_run.task_run_id).diagnostics if self.state_index.get_task_run(start_task_run.task_run_id) else {}),
                    **dict(diagnostics or {}),
                    "worker_spawn_summary": worker_spawn_summary,
                },
            )
        )

    def _write_checkpoint_event(self, state: RuntimeLoopState, *, event_offset: int):
        execution_summary = self.execution_store.build_summary(state.task_run_id)
        execution_refs = tuple(str(item) for item in list(execution_summary.get("execution_refs") or []))
        execution_state_ref = str(execution_summary.get("latest_execution_id") or "")
        agent_runs = tuple(self.state_index.list_task_agent_runs(state.task_run_id))
        coordination_runs = tuple(self.state_index.list_task_coordination_runs(state.task_run_id))
        checkpoint = self.checkpoints.write(
            state,
            event_offset=event_offset,
            execution_refs=execution_refs,
            execution_state_ref=execution_state_ref,
            execution_summary=execution_summary,
            agent_runs=agent_runs,
            coordination_runs=coordination_runs,
        )
        return self.event_log.append(
            state.task_run_id,
            "checkpoint_written",
            payload={
                "checkpoint_id": checkpoint.checkpoint_id,
                "event_offset": checkpoint.event_offset,
                "checksum": checkpoint.checksum,
                "execution_summary": execution_summary,
                "runtime_objects_summary": checkpoint.runtime_objects_summary,
            },
            refs={"checkpoint_ref": checkpoint.checkpoint_id},
        )

    def _sync_runtime_objects_after_task_contract(
        self,
        *,
        start_result: TaskRunLoopStartResult,
        event_offset: int,
        adoption_mode: str,
        task_agent_binding_ref: str,
        coordination_task_payload: dict[str, Any],
        communication_protocol_payload: dict[str, Any],
        task_agent_adoption_plan_payload: dict[str, Any] | None = None,
        effective_limits: RuntimeLoopLimits | None = None,
    ) -> tuple[Any, ...]:
        events: list[Any] = []
        adoption_plan_payload = dict(task_agent_adoption_plan_payload or {})
        effective_limits_payload = effective_limits.to_dict() if effective_limits is not None else None
        if effective_limits_payload is not None:
            current_task_run = self.state_index.get_task_run(start_result.task_run.task_run_id) or start_result.task_run
            self.state_index.upsert_task_run(
                TaskRun(
                    task_run_id=current_task_run.task_run_id,
                    session_id=current_task_run.session_id,
                    task_id=current_task_run.task_id,
                    task_contract_ref=current_task_run.task_contract_ref,
                    agent_id=current_task_run.agent_id,
                    agent_profile_id=current_task_run.agent_profile_id,
                    runtime_lane=current_task_run.runtime_lane,
                    status=current_task_run.status,
                    created_at=current_task_run.created_at,
                    updated_at=time.time(),
                    latest_event_offset=current_task_run.latest_event_offset,
                    latest_checkpoint_ref=current_task_run.latest_checkpoint_ref,
                    terminal_reason=current_task_run.terminal_reason,
                    diagnostics={
                        **dict(current_task_run.diagnostics),
                        "loop_limits": effective_limits_payload,
                        "effective_loop_limits": effective_limits_payload,
                    },
                )
            )
        coordination_run_id = f"coordrun:{start_result.task_run.task_run_id}:primary"
        updated_agent_run = AgentRun(
            agent_run_id=start_result.agent_run.agent_run_id,
            task_run_id=start_result.agent_run.task_run_id,
            agent_id=start_result.agent_run.agent_id,
            agent_profile_id=start_result.agent_run.agent_profile_id,
            role="coordinator" if coordination_task_payload else start_result.agent_run.role,
            spawn_mode=adoption_mode,
            context_scope=start_result.agent_run.context_scope,
            runtime_lane=start_result.agent_run.runtime_lane,
            parent_agent_run_ref=start_result.agent_run.parent_agent_run_ref,
            coordination_run_ref=(
                start_result.agent_run.coordination_run_ref
                or (coordination_run_id if coordination_task_payload else "")
            ),
            status="running",
            latest_checkpoint_ref=start_result.agent_run.latest_checkpoint_ref,
            result_ref=start_result.agent_run.result_ref,
            created_at=start_result.agent_run.created_at,
            updated_at=time.time(),
            diagnostics={
                **dict(start_result.agent_run.diagnostics),
                "adoption_mode": adoption_mode,
                "task_agent_binding_ref": task_agent_binding_ref,
            },
        )
        self.state_index.upsert_agent_run(updated_agent_run)
        events.append(
            self.event_log.append(
                start_result.task_run.task_run_id,
                "agent_run_updated",
                payload={"agent_run": updated_agent_run.to_dict()},
                refs={"agent_run_ref": updated_agent_run.agent_run_id},
            )
        )
        current_coordination_run: CoordinationRun | None = None
        if coordination_task_payload:
            topology_template_payload = self._resolve_topology_template(
                str(coordination_task_payload.get("topology_template_id") or "")
            )
            coordination_flow = build_coordination_flow_state(
                coordination_task_payload=coordination_task_payload,
                topology_template=topology_template_payload,
                communication_protocol_payload=communication_protocol_payload,
            )
            coordination_run = CoordinationRun(
                coordination_run_id=coordination_run_id,
                task_run_id=start_result.task_run.task_run_id,
                coordination_task_ref=str(coordination_task_payload.get("coordination_task_id") or ""),
                coordinator_agent_id=str(coordination_task_payload.get("coordinator_agent_id") or updated_agent_run.agent_id),
                topology_template_id=str(coordination_task_payload.get("topology_template_id") or ""),
                communication_protocol_id=str(communication_protocol_payload.get("protocol_id") or ""),
                handoff_policy=str(coordination_task_payload.get("handoff_policy") or ""),
                failure_policy=str(coordination_task_payload.get("conflict_resolution_policy") or ""),
                merge_policy=str(coordination_task_payload.get("output_merge_policy") or ""),
                status="running",
                latest_checkpoint_ref="",
                created_at=time.time(),
                updated_at=time.time(),
                diagnostics={
                    "shared_context_policy": str(coordination_task_payload.get("shared_context_policy") or ""),
                    "memory_sharing_policy": str(coordination_task_payload.get("memory_sharing_policy") or ""),
                    "coordination_flow": coordination_flow,
                },
            )
            self.state_index.upsert_coordination_run(coordination_run)
            events.append(
                self.event_log.append(
                    start_result.task_run.task_run_id,
                    "coordination_run_created",
                    payload={"coordination_run": coordination_run.to_dict()},
                    refs={"coordination_run_ref": coordination_run.coordination_run_id},
                )
            )
            if coordination_flow:
                events.append(
                    self.event_log.append(
                        start_result.task_run.task_run_id,
                        "coordination_flow_registered",
                        payload={"coordination_flow": coordination_flow},
                        refs={"coordination_run_ref": coordination_run.coordination_run_id},
                    )
                )
            current_coordination_run = coordination_run
        else:
            existing_coordination_runs = self.state_index.list_task_coordination_runs(start_result.task_run.task_run_id)
            current_coordination_run = existing_coordination_runs[0] if existing_coordination_runs else None

        spawn_events, current_coordination_run = self._sync_worker_spawn_runtime_objects(
            task_run_id=start_result.task_run.task_run_id,
            parent_agent_run=updated_agent_run,
            coordination_run=current_coordination_run,
            adoption_mode=adoption_mode,
            task_agent_binding_ref=task_agent_binding_ref,
            adoption_plan_payload=adoption_plan_payload,
            event_offset=event_offset,
        )
        events.extend(spawn_events)

        if current_coordination_run is not None:
            coordination_events = self._sync_coordination_runtime_objects(
                task_run_id=start_result.task_run.task_run_id,
                coordinator_agent_run=updated_agent_run,
                coordination_run=current_coordination_run,
                communication_protocol_payload=communication_protocol_payload,
            )
            events.extend(coordination_events)
        return tuple(events)

    def _sync_worker_spawn_runtime_objects(
        self,
        *,
        task_run_id: str,
        parent_agent_run: AgentRun,
        coordination_run: CoordinationRun | None,
        adoption_mode: str,
        task_agent_binding_ref: str,
        adoption_plan_payload: dict[str, Any],
        event_offset: int,
    ) -> tuple[list[Any], CoordinationRun | None]:
        events: list[Any] = []
        allow_spawn = bool(adoption_plan_payload.get("allow_worker_agent_spawn") is True)
        blueprint_id = str(adoption_plan_payload.get("worker_agent_blueprint_id") or "").strip()
        if not allow_spawn:
            if blueprint_id:
                blocked_result = WorkerAgentSpawnResult(
                    spawn_result_id=f"spawnresult:{task_run_id}:blocked",
                    spawn_request_id=f"spawnreq:{task_run_id}:blocked",
                    task_run_id=task_run_id,
                    parent_agent_run_ref=parent_agent_run.agent_run_id,
                    blueprint_id=blueprint_id,
                    status="blocked",
                    created_at=time.time(),
                    diagnostics={
                        "reason": "worker_spawn_disabled_by_execution_policy",
                        "task_agent_binding_ref": task_agent_binding_ref,
                        "event_offset": event_offset,
                    },
                )
                self.state_index.upsert_worker_spawn_result(blocked_result)
                events.append(
                    self.event_log.append(
                        task_run_id,
                        "worker_agent_spawn_completed",
                        payload={"worker_spawn_result": blocked_result.to_dict()},
                        refs={"spawn_result_ref": blocked_result.spawn_result_id},
                    )
                )
            return events, coordination_run
        if not blueprint_id:
            blocked_result = WorkerAgentSpawnResult(
                spawn_result_id=f"spawnresult:{task_run_id}:blocked",
                spawn_request_id=f"spawnreq:{task_run_id}:blocked",
                task_run_id=task_run_id,
                parent_agent_run_ref=parent_agent_run.agent_run_id,
                blueprint_id="",
                status="blocked",
                created_at=time.time(),
                diagnostics={
                    "reason": "missing_worker_blueprint",
                    "task_agent_binding_ref": task_agent_binding_ref,
                    "event_offset": event_offset,
                },
            )
            self.state_index.upsert_worker_spawn_result(blocked_result)
            events.append(
                self.event_log.append(
                    task_run_id,
                    "worker_agent_spawn_completed",
                    payload={"worker_spawn_result": blocked_result.to_dict()},
                    refs={"spawn_result_ref": blocked_result.spawn_result_id},
                )
            )
            return events, coordination_run
        blueprint = self.worker_agent_factory.get_blueprint(blueprint_id)
        if blueprint is None:
            blocked_result = WorkerAgentSpawnResult(
                spawn_result_id=f"spawnresult:{task_run_id}:blocked",
                spawn_request_id=f"spawnreq:{task_run_id}:blocked",
                task_run_id=task_run_id,
                parent_agent_run_ref=parent_agent_run.agent_run_id,
                blueprint_id=blueprint_id,
                status="blocked",
                created_at=time.time(),
                diagnostics={
                    "reason": "worker_blueprint_not_found",
                    "task_agent_binding_ref": task_agent_binding_ref,
                    "event_offset": event_offset,
                },
            )
            self.state_index.upsert_worker_spawn_result(blocked_result)
            events.append(
                self.event_log.append(
                    task_run_id,
                    "worker_agent_spawn_completed",
                    payload={"worker_spawn_result": blocked_result.to_dict()},
                    refs={"spawn_result_ref": blocked_result.spawn_result_id},
                )
            )
            return events, coordination_run
        existing_results = self.state_index.list_task_worker_spawn_results(task_run_id)
        already_spawned = next(
            (
                item
                for item in existing_results
                if item.blueprint_id == blueprint_id and item.parent_agent_run_ref == parent_agent_run.agent_run_id and item.status == "spawned"
            ),
            None,
        )
        if already_spawned is not None:
            return events, coordination_run
        existing_count = len(existing_results) + 1
        requested_agent_name = self._render_worker_agent_name(
            naming_rule=str(adoption_plan_payload.get("worker_agent_naming_rule") or "").strip(),
            blueprint_template=blueprint.agent_name_template,
            index=existing_count,
        )
        spawn_request = WorkerAgentSpawnRequest(
            spawn_request_id=f"spawnreq:{task_run_id}:{existing_count}",
            task_run_id=task_run_id,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            blueprint_id=blueprint_id,
            requested_agent_name=requested_agent_name,
            runtime_lane=(
                blueprint.default_runtime_lanes[0]
                if blueprint.default_runtime_lanes
                else parent_agent_run.runtime_lane
            ),
            context_scope=parent_agent_run.context_scope,
            requested_by_agent_id=parent_agent_run.agent_id,
            spawn_reason="task_agent_adoption_plan_authorized",
            requested_at=time.time(),
            diagnostics={
                "adoption_mode": adoption_mode,
                "task_agent_binding_ref": task_agent_binding_ref,
                "event_offset": event_offset,
            },
        )
        self.state_index.upsert_worker_spawn_request(spawn_request)
        events.append(
            self.event_log.append(
                task_run_id,
                "worker_agent_spawn_requested",
                payload={"worker_spawn_request": spawn_request.to_dict()},
                refs={"spawn_request_ref": spawn_request.spawn_request_id},
            )
        )
        provisioned = self.worker_agent_factory.provision_worker_agent(
            request=spawn_request,
            requested_agent_name=requested_agent_name,
            task_scope=blueprint.allowed_task_modes,
        )
        child_agent_run = AgentRun(
            agent_run_id=f"agrun:{task_run_id}:worker:{existing_count}",
            task_run_id=task_run_id,
            agent_id=provisioned.agent.agent_id,
            agent_profile_id=provisioned.runtime_profile.agent_profile_id,
            role="worker_participant",
            spawn_mode="worker_spawn",
            context_scope=spawn_request.context_scope,
            runtime_lane=spawn_request.runtime_lane,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            coordination_run_ref=coordination_run.coordination_run_id if coordination_run is not None else "",
            status="pending",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={
                "spawn_request_ref": spawn_request.spawn_request_id,
                "worker_blueprint_id": blueprint_id,
            },
        )
        self.state_index.upsert_agent_run(child_agent_run)
        finalized_spawn_result = WorkerAgentSpawnResult(
            spawn_result_id=provisioned.spawn_result.spawn_result_id,
            spawn_request_id=provisioned.spawn_result.spawn_request_id,
            task_run_id=provisioned.spawn_result.task_run_id,
            parent_agent_run_ref=provisioned.spawn_result.parent_agent_run_ref,
            blueprint_id=provisioned.spawn_result.blueprint_id,
            spawned_agent_id=provisioned.spawn_result.spawned_agent_id,
            spawned_agent_run_ref=child_agent_run.agent_run_id,
            spawned_agent_profile_id=provisioned.spawn_result.spawned_agent_profile_id,
            status=provisioned.spawn_result.status,
            created_at=provisioned.spawn_result.created_at,
            diagnostics={
                **dict(provisioned.spawn_result.diagnostics),
                "task_agent_binding_ref": task_agent_binding_ref,
            },
        )
        self.state_index.upsert_worker_spawn_result(finalized_spawn_result)
        events.append(
            self.event_log.append(
                task_run_id,
                "agent_run_created",
                payload={"agent_run": child_agent_run.to_dict()},
                refs={"agent_run_ref": child_agent_run.agent_run_id},
            )
        )
        events.append(
            self.event_log.append(
                task_run_id,
                "worker_agent_spawn_completed",
                payload={"worker_spawn_result": finalized_spawn_result.to_dict()},
                refs={"spawn_result_ref": finalized_spawn_result.spawn_result_id},
            )
        )
        if coordination_run is None and self._adoption_mode_allows_projection(adoption_mode):
            coordination_run = CoordinationRun(
                coordination_run_id=f"coordrun:{task_run_id}:spawn",
                task_run_id=task_run_id,
                coordination_task_ref=f"coord.auto:{task_run_id}",
                coordinator_agent_id=parent_agent_run.agent_id,
                topology_template_id="",
                communication_protocol_id="",
                handoff_policy="runtime_authorized_handoff",
                failure_policy="fail_closed",
                merge_policy="coordinator_final_merge",
                status="running",
                created_at=time.time(),
                updated_at=time.time(),
                diagnostics={
                    "autogenerated": True,
                    "reason": "worker_spawn_authorized_without_coordination_task",
                },
            )
            self.state_index.upsert_coordination_run(coordination_run)
            events.append(
                self.event_log.append(
                    task_run_id,
                    "coordination_run_created",
                    payload={"coordination_run": coordination_run.to_dict()},
                    refs={"coordination_run_ref": coordination_run.coordination_run_id},
                )
            )
            self.state_index.upsert_agent_run(
                AgentRun(
                    agent_run_id=child_agent_run.agent_run_id,
                    task_run_id=child_agent_run.task_run_id,
                    agent_id=child_agent_run.agent_id,
                    agent_profile_id=child_agent_run.agent_profile_id,
                    role=child_agent_run.role,
                    spawn_mode=child_agent_run.spawn_mode,
                    context_scope=child_agent_run.context_scope,
                    runtime_lane=child_agent_run.runtime_lane,
                    parent_agent_run_ref=child_agent_run.parent_agent_run_ref,
                    coordination_run_ref=coordination_run.coordination_run_id,
                    status=child_agent_run.status,
                    latest_checkpoint_ref=child_agent_run.latest_checkpoint_ref,
                    result_ref=child_agent_run.result_ref,
                    created_at=child_agent_run.created_at,
                    updated_at=time.time(),
                    diagnostics=dict(child_agent_run.diagnostics),
                )
            )
        return events, coordination_run

    def _sync_coordination_runtime_objects(
        self,
        *,
        task_run_id: str,
        coordinator_agent_run: AgentRun,
        coordination_run: CoordinationRun,
        communication_protocol_payload: dict[str, Any],
        ) -> tuple[Any, ...]:
        events: list[Any] = []
        existing_node_runs = {item.node_id: item for item in self.state_index.list_coordination_node_runs(coordination_run.coordination_run_id)}
        existing_agent_runs = {item.agent_run_id: item for item in self.state_index.list_task_agent_runs(task_run_id)}
        topology_template = self._resolve_topology_template(coordination_run.topology_template_id)
        coordination_task = self.task_flow_registry.get_coordination_task(coordination_run.coordination_task_ref)
        communication_protocol = self.task_flow_registry.get_task_communication_protocol(coordination_run.communication_protocol_id)
        specific_tasks = tuple(self.task_flow_registry.list_specific_task_records())
        coordination_flow = dict(coordination_run.diagnostics.get("coordination_flow") or {})
        node_status_map = build_coordination_node_status_map(coordination_flow)
        emitted_stage_ids: set[str] = set()
        protocol_message_types = tuple(str(item).strip() for item in list(communication_protocol_payload.get("message_types") or []) if str(item).strip())
        handoff_message_type = protocol_message_types[0] if protocol_message_types else "structured_handoff"
        worker_nodes: list[dict[str, Any]] = []
        for item in self.state_index.list_task_worker_spawn_results(task_run_id):
            if item.status != "spawned":
                continue
            worker_nodes.append(
                {
                    "node_id": f"worker_{item.spawned_agent_id.replace(':', '_')}",
                    "agent_id": item.spawned_agent_id,
                    "lane": "",
                    "role": "worker_participant",
                }
            )
        graph_spec = (
            compile_coordination_graph_spec(
                coordination_task=coordination_task,
                specific_tasks=specific_tasks,
                topology_template=self.task_flow_registry.get_topology_template(coordination_run.topology_template_id),
                communication_protocol=communication_protocol,
            )
            if coordination_task is not None
            else None
        )
        graph_result = (
            self.langgraph_coordination_runner.run(
                task_run_id=task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                graph_spec=graph_spec,
            )
            if graph_spec is not None
            else None
        )
        nodes = (
            [dict(item) for item in list(graph_result.graph_spec.get("nodes") or [])]
            if graph_result is not None
            else list(topology_template.get("nodes") or [])
        )
        if not nodes:
            nodes = [
                {
                    "node_id": "coordinator",
                    "agent_id": coordinator_agent_run.agent_id,
                    "lane": coordinator_agent_run.runtime_lane,
                    "role": "coordinator",
                }
            ]
            nodes.extend(worker_nodes)
        node_agent_run_by_node_id: dict[str, AgentRun] = {}
        for index, node in enumerate(nodes, start=1):
            node_id = str(node.get("node_id") or f"node_{index}").strip()
            assigned_agent_id = str(node.get("agent_id") or "").strip() or coordinator_agent_run.agent_id
            role = str(node.get("role") or ("coordinator" if assigned_agent_id == coordinator_agent_run.agent_id else "participant")).strip()
            runtime_lane = str(node.get("lane") or "").strip()
            if assigned_agent_id == coordinator_agent_run.agent_id:
                assigned_agent_run = coordinator_agent_run
            else:
                assigned_agent_run = next(
                    (
                        item
                        for item in existing_agent_runs.values()
                        if item.agent_id == assigned_agent_id and item.parent_agent_run_ref == coordinator_agent_run.agent_run_id
                    ),
                    None,
                )
                if assigned_agent_run is None:
                    runtime_profile = self.agent_runtime_registry.get_profile(assigned_agent_id)
                    assigned_agent_run = AgentRun(
                        agent_run_id=f"agrun:{task_run_id}:participant:{node_id}",
                        task_run_id=task_run_id,
                        agent_id=assigned_agent_id,
                        agent_profile_id=(
                            runtime_profile.agent_profile_id
                            if runtime_profile is not None
                            else f"{assigned_agent_id.removeprefix('agent:').replace(':', '_')}_runtime"
                        ),
                        role=role,
                        spawn_mode="coordination_participant",
                        context_scope=coordinator_agent_run.context_scope,
                        runtime_lane=runtime_lane or coordinator_agent_run.runtime_lane,
                        parent_agent_run_ref=coordinator_agent_run.agent_run_id,
                        coordination_run_ref=coordination_run.coordination_run_id,
                        status="pending",
                        created_at=time.time(),
                        updated_at=time.time(),
                        diagnostics={"node_id": node_id, "autocreated": True},
                    )
                    self.state_index.upsert_agent_run(assigned_agent_run)
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "agent_run_created",
                            payload={"agent_run": assigned_agent_run.to_dict()},
                            refs={"agent_run_ref": assigned_agent_run.agent_run_id},
                        )
                    )
            node_agent_run_by_node_id[node_id] = assigned_agent_run
            if node_id not in existing_node_runs:
                node_flow = dict(node_status_map.get(node_id) or {})
                node_run = CoordinationNodeRun(
                    node_run_id=f"coordnode:{coordination_run.coordination_run_id}:{node_id}",
                    coordination_run_id=coordination_run.coordination_run_id,
                    task_run_id=task_run_id,
                    node_id=node_id,
                    role=role,
                    assigned_agent_id=assigned_agent_run.agent_id,
                    assigned_agent_run_ref=assigned_agent_run.agent_run_id,
                    status=str(node_flow.get("node_run_status") or ("pending" if role != "coordinator" else "running")),
                    created_at=time.time(),
                    updated_at=time.time(),
                    diagnostics={
                        "lane": runtime_lane or assigned_agent_run.runtime_lane,
                        "coordination_engine": "langgraph" if graph_result is not None else "legacy",
                        "graph_node_type": str(node.get("node_type") or ""),
                        "graph_task_id": str(node.get("task_id") or ""),
                        **(
                            {
                                "stage_id": str(node_flow.get("stage_id") or ""),
                                "message_type": str(node_flow.get("message_type") or ""),
                                "stage_status": str(node_flow.get("stage_status") or ""),
                            }
                            if node_flow
                            else {}
                        ),
                    },
                )
                self.state_index.upsert_coordination_node_run(node_run)
                events.append(
                    self.event_log.append(
                        task_run_id,
                        "coordination_node_run_created",
                        payload={"coordination_node_run": node_run.to_dict()},
                        refs={"coordination_node_run_ref": node_run.node_run_id},
                    )
                )
                stage_id = str(node_flow.get("stage_id") or "").strip()
                if stage_id and stage_id not in emitted_stage_ids:
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "coordination_stage_updated",
                            payload={
                                "stage": {
                                    "stage_id": stage_id,
                                    "node_id": node_id,
                                    "message_type": str(node_flow.get("message_type") or ""),
                                    "status": str(node_flow.get("stage_status") or ""),
                                }
                            },
                            refs={"coordination_run_ref": coordination_run.coordination_run_id},
                        )
                    )
                    emitted_stage_ids.add(stage_id)
            else:
                existing = existing_node_runs[node_id]
                node_flow = dict(node_status_map.get(node_id) or {})
                target_status = str(node_flow.get("node_run_status") or existing.status)
                target_stage_id = str(node_flow.get("stage_id") or existing.diagnostics.get("stage_id") or "")
                target_message_type = str(node_flow.get("message_type") or existing.diagnostics.get("message_type") or "")
                target_stage_status = str(node_flow.get("stage_status") or existing.diagnostics.get("stage_status") or "")
                if (
                    target_status != existing.status
                    or target_stage_id != str(existing.diagnostics.get("stage_id") or "")
                    or target_stage_status != str(existing.diagnostics.get("stage_status") or "")
                ):
                    updated = CoordinationNodeRun(
                        node_run_id=existing.node_run_id,
                        coordination_run_id=existing.coordination_run_id,
                        task_run_id=existing.task_run_id,
                        node_id=existing.node_id,
                        role=existing.role,
                        assigned_agent_id=existing.assigned_agent_id,
                        assigned_agent_run_ref=existing.assigned_agent_run_ref,
                        status=target_status,
                        handoff_count=existing.handoff_count,
                        latest_handoff_ref=existing.latest_handoff_ref,
                        created_at=existing.created_at,
                        updated_at=time.time(),
                        diagnostics={
                            **dict(existing.diagnostics),
                            "coordination_engine": "langgraph" if graph_result is not None else str(existing.diagnostics.get("coordination_engine") or "legacy"),
                            "stage_id": target_stage_id,
                            "message_type": target_message_type,
                            "stage_status": target_stage_status,
                        },
                    )
                    self.state_index.upsert_coordination_node_run(updated)
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "coordination_node_run_updated",
                            payload={"coordination_node_run": updated.to_dict()},
                            refs={"coordination_node_run_ref": updated.node_run_id},
                        )
                    )
                if target_stage_id and target_stage_id not in emitted_stage_ids:
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "coordination_stage_updated",
                            payload={
                                "stage": {
                                    "stage_id": target_stage_id,
                                    "node_id": node_id,
                                    "message_type": target_message_type,
                                    "status": target_stage_status,
                                }
                            },
                            refs={"coordination_run_ref": coordination_run.coordination_run_id},
                        )
                    )
                    emitted_stage_ids.add(target_stage_id)
        existing_handoffs = {
            item.handoff_id: item
            for item in self.state_index.list_coordination_handoffs(coordination_run.coordination_run_id)
        }
        edges = (
            [dict(item) for item in list(graph_result.graph_spec.get("edges") or [])]
            if graph_result is not None
            else list(topology_template.get("edges") or [])
        )
        if not edges and len(node_agent_run_by_node_id) > 1:
            for node_id, agent_run in node_agent_run_by_node_id.items():
                if node_id == "coordinator":
                    continue
                edges.append({"from": node_id, "to": "coordinator", "policy": coordination_run.handoff_policy or "filtered_handoff"})
        for index, edge in enumerate(edges, start=1):
            source_node_id = str(edge.get("from") or edge.get("source_node_id") or edge.get("source") or "").strip()
            target_node_id = str(edge.get("to") or edge.get("target_node_id") or edge.get("target") or "").strip()
            source_agent_run = node_agent_run_by_node_id.get(source_node_id)
            target_agent_run = node_agent_run_by_node_id.get(target_node_id)
            if source_agent_run is None or target_agent_run is None:
                continue
            handoff_id = f"handoff:{coordination_run.coordination_run_id}:{index}"
            if handoff_id in existing_handoffs:
                continue
            handoff = AgentHandoffEnvelope(
                handoff_id=handoff_id,
                task_run_id=task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                source_agent_run_ref=source_agent_run.agent_run_id,
                target_agent_run_ref=target_agent_run.agent_run_id,
                protocol_id=coordination_run.communication_protocol_id,
                message_type=handoff_message_type,
                payload_ref=f"handoff_payload:{handoff_id}",
                ack_state="pending",
                created_at=time.time(),
                diagnostics={
                    "handoff_policy": str(edge.get("policy") or edge.get("mode") or coordination_run.handoff_policy or ""),
                    "coordination_engine": "langgraph" if graph_result is not None else "legacy",
                    "edge_mode": str(edge.get("mode") or edge.get("policy") or ""),
                },
            )
            self.state_index.upsert_handoff_envelope(handoff)
            events.append(
                self.event_log.append(
                    task_run_id,
                    "handoff_envelope_created",
                    payload={"handoff_envelope": handoff.to_dict()},
                    refs={"handoff_ref": handoff.handoff_id},
                )
            )
        if graph_result is not None:
            self.state_index.upsert_coordination_run(
                CoordinationRun(
                    coordination_run_id=coordination_run.coordination_run_id,
                    task_run_id=coordination_run.task_run_id,
                    coordination_task_ref=coordination_run.coordination_task_ref,
                    coordinator_agent_id=coordination_run.coordinator_agent_id,
                    topology_template_id=coordination_run.topology_template_id,
                    communication_protocol_id=coordination_run.communication_protocol_id,
                    handoff_policy=coordination_run.handoff_policy,
                    failure_policy=coordination_run.failure_policy,
                    merge_policy=coordination_run.merge_policy,
                    status=coordination_run.status,
                    latest_checkpoint_ref=coordination_run.latest_checkpoint_ref,
                    latest_merge_result_ref=coordination_run.latest_merge_result_ref,
                    created_at=coordination_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(coordination_run.diagnostics),
                        "coordination_engine": "langgraph",
                        "coordination_graph_spec": graph_result.graph_spec,
                        "langgraph_diagnostics": dict(graph_result.diagnostics),
                    },
                )
            )
        return tuple(events)

    def _resolve_topology_template(self, template_id: str) -> dict[str, Any]:
        target = str(template_id or "").strip()
        if not target:
            return {}
        match = next((item for item in self.task_flow_registry.list_topology_templates() if item.template_id == target), None)
        return match.to_dict() if match is not None else {}

    @staticmethod
    def _render_worker_agent_name(*, naming_rule: str, blueprint_template: str, index: int) -> str:
        template = naming_rule or blueprint_template or "工作Agent {n}"
        safe_template = template.replace("{index}", "{n}")
        try:
            rendered = safe_template.format(n=index)
        except Exception:
            rendered = f"{template} {index}"
        return str(rendered or f"工作Agent {index}").strip()

    @staticmethod
    def _adoption_mode_allows_projection(adoption_mode: str) -> bool:
        return str(adoption_mode or "").strip() in {"adopt_with_projection", "spawn_worker_allowed"}

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
        from capability_system.tool_authorization import build_authorized_tool_set

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

    def _should_run_template_mcp_phase(
        self,
        *,
        query_understanding: dict[str, Any],
        selected_template_payload: dict[str, Any],
    ) -> bool:
        template_id = str(selected_template_payload.get("template_id") or "").strip()
        if get_local_mcp_unit_for_template(template_id) is not None:
            return True
        source_kind = str(query_understanding.get("source_kind") or "").strip()
        preferred_skill = str(query_understanding.get("preferred_skill") or "").strip()
        return preferred_skill == "rag-skill" and source_kind == "knowledge_base"

    def _rebuild_context_policy_with_retrieval(
        self,
        *,
        agent_runtime_chain: Any,
        session_id: str,
        user_message: str,
        memory_intent: Any | None,
        task_operation: dict[str, Any],
        retrieval_results: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
        context_policy_result = agent_runtime_chain.build_context_policy_result(
            session_id=session_id,
            message=user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            retrieval_results=retrieval_results,
        )
        if context_policy_result is None:
            return {}
        if hasattr(context_policy_result, "to_dict"):
            return dict(context_policy_result.to_dict())
        return dict(context_policy_result)

    async def _run_template_mcp_phase(
        self,
        *,
        task_run_id: str,
        session_id: str,
        task_id: str,
        user_message: str,
        current_turn_context: dict[str, Any],
        query_understanding: dict[str, Any],
        selected_template_payload: dict[str, Any],
        task_contract_ref: str,
        runtime_task_ledger: TaskRunLedger | None,
        state: RuntimeLoopState,
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        result_refs: list[str] = []
        main_context: dict[str, Any] = {}
        task_summary_refs: list[dict[str, Any]] = []
        retrieval_results: list[dict[str, Any]] = []
        if self.evidence_orchestrator is None:
            return {
                "events": events,
                "ledger": runtime_task_ledger,
                "state": state,
                "result_refs": result_refs,
                "main_context": main_context,
                "task_summary_refs": task_summary_refs,
                "retrieval_results": retrieval_results,
            }

        mcp_route, operation_id, bindings, constraints, answer_source = self._template_mcp_request_parts(
            user_message=user_message,
            current_turn_context=current_turn_context,
            query_understanding=query_understanding,
            selected_template_payload=selected_template_payload,
        )
        retrieval_event = self.event_log.append(
            task_run_id,
            "executor_started",
            payload={"executor_type": "mcp", "runtime_channel": "single_agent_runtime", "mcp_route": mcp_route},
            refs={"task_contract_ref": task_contract_ref, "operation_id": operation_id},
        )
        events.append({"type": "runtime_loop_event", "event": retrieval_event.to_dict()})

        mcp_request = MCPRequest(
            request_id=f"mcpreq:{task_id}:{mcp_route}",
            session_id=session_id,
            query=str(query_understanding.get("parameters", {}).get("query") or user_message),
            mcp_route=mcp_route,
            task_frame={
                "task_id": task_id,
                "route": str(query_understanding.get("route") or query_understanding.get("route_hint") or "rag"),
                "preferred_skill": str(query_understanding.get("preferred_skill") or ""),
                "task_kind": str(query_understanding.get("task_kind") or ""),
            },
            bindings=bindings,
            constraints=constraints,
            owner_task_id=task_id,
            arbitration_reason=f"runtime_{mcp_route}_pre_execution",
            message_id=f"{task_id}:{mcp_route}",
        )
        mcp_plan = MCPExecutionPlan(
            mcp_route=mcp_route,
            request=mcp_request,
            expected_result="canonical",
            fallback_execution_kind="none",
            cutover_mode="primary",
        )

        done_event: dict[str, Any] | None = None
        async for event in self.evidence_orchestrator.stream_execution(
            session_id=session_id,
            execution=None,
            mcp_plan=mcp_plan,
            main_context={},
            trace=None,
        ):
            if event.get("type") == "retrieval":
                retrieval_results = [dict(item) for item in list(event.get("results") or [])]
            if event.get("type") == "done":
                done_event = dict(event)
                continue
            events.append(dict(event))

        if done_event is not None:
            result_ref = f"mcp_result:{mcp_request.request_id}"
            result_refs.append(result_ref)
            main_context = dict(done_event.get("main_context") or {})
            task_summary_refs = [dict(item) for item in list(done_event.get("task_summary_refs") or [])]
            current_step = current_task_step_run(runtime_task_ledger)
            if (
                runtime_task_ledger is not None
                and current_step is not None
                and current_step.status == "running"
                and current_step.executor_type == "mcp"
                and step_supports_operation(current_step, operation_id)
            ):
                runtime_task_ledger = complete_task_run_step(
                    runtime_task_ledger,
                    step_id=current_step.step_id,
                    completed_at=time.time(),
                    observation_refs=(result_ref,),
                    output_refs=(result_ref,),
                    step_result_ref=result_ref,
                    executor_ref=operation_id,
                    diagnostics={"transition_reason": f"{mcp_route}_mcp_completed"},
                )
                completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
                if completed_step is not None:
                    step_completed_event = self._record_task_run_step_event(
                        task_run_id,
                        event_type="step_completed",
                        step_run=completed_step,
                        ledger=runtime_task_ledger,
                        reason=f"{mcp_route}_mcp_completed",
                        refs={"operation_id": operation_id},
                    )
                    events.append({"type": "runtime_loop_event", "event": step_completed_event.to_dict()})
                runtime_task_ledger = advance_task_run_ledger(
                    runtime_task_ledger,
                    started_at=time.time(),
                    diagnostics={"transition_reason": f"{mcp_route}_mcp_completed"},
                )
                ledger_event = self._record_task_run_ledger_updated(
                    task_run_id,
                    ledger=runtime_task_ledger,
                    reason=f"{mcp_route}_mcp_completed",
                    refs={"operation_id": operation_id},
                )
                events.append({"type": "runtime_loop_event", "event": ledger_event.to_dict()})
                entered_step = current_task_step_run(runtime_task_ledger)
                if entered_step is not None and entered_step.step_id != current_step.step_id:
                    step_entered_event = self._record_task_run_step_event(
                        task_run_id,
                        event_type="step_entered",
                        step_run=entered_step,
                        ledger=runtime_task_ledger,
                        reason=f"{mcp_route}_mcp_completed",
                        refs={"operation_id": operation_id},
                    )
                    events.append({"type": "runtime_loop_event", "event": step_entered_event.to_dict()})
                state = self._state_with_task_run_ledger(
                    state,
                    runtime_task_ledger,
                    result_refs=result_refs,
                    diagnostics={"last_step_transition": f"{mcp_route}_mcp_completed"},
                )
                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                events.append({"type": "runtime_loop_event", "event": checkpoint_event.to_dict()})

            if main_context:
                main_context.setdefault("answer_source", answer_source)

        return {
            "events": events,
            "ledger": runtime_task_ledger,
            "state": state,
            "result_refs": result_refs,
            "main_context": main_context,
            "task_summary_refs": task_summary_refs,
            "retrieval_results": retrieval_results,
        }

    def _template_mcp_request_parts(
        self,
        *,
        user_message: str,
        current_turn_context: dict[str, Any],
        query_understanding: dict[str, Any],
        selected_template_payload: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        template_id = str(selected_template_payload.get("template_id") or "").strip()
        unit = get_local_mcp_unit_for_template(template_id)
        parameters = dict(query_understanding.get("tool_input") or query_understanding.get("parameters") or {})
        bindings: dict[str, Any] = {}
        constraints: dict[str, Any] = {}
        if unit is not None:
            path_key = str(unit.request_path_parameter or "").strip()
            binding_key = str(unit.followup_binding_key or "").strip()
            if path_key and binding_key and binding_key != "current_turn_context":
                path = str(parameters.get(path_key) or "").strip()
                bindings = {binding_key: path} if path else {}
                constraints = {path_key: path} if path else {}
            if unit.request_mode_parameter:
                mode_key = str(unit.request_mode_parameter).strip()
                mode = str(parameters.get(mode_key) or unit.request_default_mode or "").strip()
                if mode:
                    constraints[mode_key] = mode
            if binding_key == "current_turn_context":
                bindings = {"current_turn_context": dict(current_turn_context or {})}
            return unit.route, unit.operation_id, bindings, constraints, unit.answer_source
        bindings = {"current_turn_context": dict(current_turn_context or {})}
        retrieval_unit = get_local_mcp_unit("retrieval")
        if retrieval_unit is not None:
            return retrieval_unit.route, retrieval_unit.operation_id, bindings, {}, retrieval_unit.answer_source
        return "retrieval", "op.mcp_retrieval", bindings, {}, "runtime_rag_mcp"

    def _final_main_context_can_finalize(
        self,
        *,
        selected_template_payload: dict[str, Any],
        retrieval_results: list[dict[str, Any]] | None,
    ) -> bool:
        template_id = str(selected_template_payload.get("template_id") or "").strip()
        unit = get_local_mcp_unit_for_template(template_id)
        if unit is not None and unit.route != "retrieval":
            return True
        return bool(retrieval_results)

    def _build_tool_authorization_index(self):
        from capability_system.tool_authorization import build_tool_authorization_index
        from capability_system.tool_definitions import get_tool_definitions

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
            from capability_system.tool_authorization import resolve_tool_operation_id

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
                and current_step.executor_type in {"tool", "mcp", "agent"}
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


def _template_allows_tool_observation_finalization(selected_template_payload: dict[str, Any]) -> bool:
    selected_template = _task_template_from_payload(selected_template_payload)
    if selected_template is None:
        return True
    return not _template_requires_model_finalize(selected_template)


def _template_requires_model_finalize(selected_template: TaskTemplate) -> bool:
    return any(
        str(step.executor_type or "") == "model" and str(step.step_kind or "") == "finalize"
        for step in selected_template.step_blueprints
    )


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
            selected_skill_ids=tuple(str(item) for item in list(payload.get("selected_skill_ids") or [])),
            operation_requirement_ref=str(payload.get("operation_requirement_ref") or ""),
            safety_envelope=dict(payload.get("safety_envelope") or {}),
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


def _runtime_limits_from_task_operation(
    task_operation: dict[str, Any],
    *,
    fallback: RuntimeLoopLimits,
) -> RuntimeLoopLimits:
    task_spec = dict(task_operation.get("task_spec") or {})
    task_assembly = dict(task_operation.get("task_execution_assembly") or {})
    adoption_plan = dict(task_operation.get("task_execution_policy") or task_operation.get("task_agent_adoption_plan") or {})
    metadata = dict(task_assembly.get("metadata") or {})
    constraints = dict(task_spec.get("constraints") or {})
    policy_metadata = dict(adoption_plan.get("metadata") or {})
    limits = {
        **dict(metadata.get("runtime_limits") or {}),
        **dict(policy_metadata.get("runtime_limits") or {}),
        **dict(constraints.get("runtime_limits") or {}),
    }
    if not limits:
        return fallback
    return RuntimeLoopLimits.from_policy(limits, fallback=fallback)


def _validate_required_artifact_file(
    *,
    root_dir: Path,
    selected_template_payload: dict[str, Any],
    final_content: str,
    result_refs: tuple[str, ...],
    event_log_events: list[dict[str, Any]],
) -> dict[str, Any]:
    rules = [
        dict(item)
        for item in list(selected_template_payload.get("validation_rules") or [])
        if str(dict(item).get("validation_kind") or "") == "artifact_file_required"
        and str(dict(item).get("severity") or "") == "error"
    ]
    if not rules:
        return {
            "passed": True,
            "required": False,
            "reason": "no artifact_file_required validation rule",
        }
    successful_writes = _successful_write_file_paths(root_dir=root_dir, event_log_events=event_log_events)
    existing_writes = [item for item in successful_writes if Path(item["absolute_path"]).exists()]
    passed = bool(existing_writes)
    return {
        "passed": passed,
        "required": True,
        "reason": "required artifact file exists" if passed else "write_file was required but no successful existing artifact file was found",
        "rule_ids": [str(item.get("rule_id") or "") for item in rules],
        "successful_write_count": len(successful_writes),
        "existing_write_count": len(existing_writes),
        "artifacts": existing_writes,
        "final_content_chars": len(str(final_content or "")),
        "result_ref_count": len(result_refs),
    }


def _requires_write_file_artifact(selected_template_payload: dict[str, Any]) -> bool:
    if "op.write_file" not in set(str(item) for item in list(selected_template_payload.get("required_operations") or [])):
        return False
    return any(
        str(dict(item).get("validation_kind") or "") == "artifact_file_required"
        and str(dict(item).get("severity") or "") == "error"
        for item in list(selected_template_payload.get("validation_rules") or [])
        if isinstance(item, dict)
    )


def _build_required_artifact_write_messages(
    *,
    model_messages: list[Any],
    user_message: str,
    task_spec_payload: dict[str, Any],
    final_content: str,
    selected_template_payload: dict[str, Any],
) -> list[Any]:
    target_path = _required_artifact_target_path(task_spec_payload=task_spec_payload, user_message=user_message)
    task_title = str(selected_template_payload.get("title") or selected_template_payload.get("task_mode") or "artifact task")
    if target_path:
        path_line = f"目标文件：{target_path}"
    else:
        path_line = "目标文件：请从用户消息中的明确路径选择唯一目标文件。"
    content_source = str(final_content or "").strip()
    if not content_source:
        content_source = str(task_spec_payload.get("user_goal") or user_message or "").strip()
    repair_instruction = (
        "上一轮没有产生正式 write_file 工具证据，因此任务仍未通过。"
        "现在必须只调用 write_file 工具写入真实文件，不要用普通回答替代工具调用。\n"
        f"任务：{task_title}\n"
        f"{path_line}\n"
        "文件内容必须是可验收的完整任务产物，不是状态说明。"
        "如果上一轮回答包含可用内容，请扩展成文件正文；如果不够，请根据任务目标生成完整正文。\n"
        "工具参数要求：path 使用目标文件路径，content 使用完整文件内容。"
        "不要声称已写入，必须发出 write_file 工具调用。\n\n"
        f"用户原始要求：\n{user_message}\n\n"
        f"上一轮模型输出：\n{content_source}"
    )
    return [
        *list(model_messages),
        HumanMessage(content=repair_instruction),
    ]


def _required_artifact_target_path(*, task_spec_payload: dict[str, Any], user_message: str) -> str:
    inputs = dict(task_spec_payload.get("inputs") or {})
    tool_input = dict(inputs.get("tool_input") or {})
    for value in (
        tool_input.get("path"),
        inputs.get("explicit_workspace_path"),
        inputs.get("output_path"),
        inputs.get("target_path"),
    ):
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return _extract_workspace_path_from_text(user_message)


def _extract_workspace_path_from_text(text: str) -> str:
    normalized = str(text or "").replace("\\", "/")
    for suffix in (".md", ".txt", ".json", ".html", ".css", ".js", ".py", ".tsx", ".ts"):
        marker = normalized.find(suffix)
        if marker < 0:
            continue
        start = marker
        while start > 0 and normalized[start - 1] not in {" ", "\n", "\t", "，", "。", "：", ":", "`", "\"", "'", "写", "入"}:
            start -= 1
        candidate = normalized[start : marker + len(suffix)].strip("`'\"，。；;：:()（）[]【】")
        if "/" in candidate and not candidate.startswith(("http://", "https://")):
            return candidate
    return ""


def _successful_write_file_paths(
    *,
    root_dir: Path,
    event_log_events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    workspace_root = _workspace_root_from_runtime_root(root_dir)
    artifacts: list[dict[str, str]] = []
    for raw_event in event_log_events:
        event = _unwrap_runtime_event(raw_event)
        if str(event.get("event_type") or "") not in {"tool_result_received", "executor_observation_received"}:
            continue
        observation = dict(dict(event.get("payload") or {}).get("observation") or {})
        if observation.get("observation_type") != "tool_result":
            continue
        payload = dict(observation.get("payload") or {})
        if str(payload.get("tool_name") or "") != "write_file":
            continue
        result = str(payload.get("result") or "")
        if not _tool_result_indicates_write_success(result):
            continue
        tool_args = dict(payload.get("tool_args") or {})
        raw_path = str(tool_args.get("path") or "").strip()
        if not raw_path:
            raw_path = _path_from_write_result(result)
        if not raw_path:
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = workspace_root / str(raw_path).replace("\\", "/").strip().strip("/")
        candidate = candidate.resolve()
        try:
            relative_path = candidate.relative_to(workspace_root).as_posix()
        except ValueError:
            relative_path = candidate.as_posix()
        artifacts.append(
            {
                "path": relative_path,
                "absolute_path": candidate.as_posix(),
                "observation_ref": str(event.get("refs", {}).get("observation_ref") or ""),
            }
        )
    unique: dict[str, dict[str, str]] = {}
    for item in artifacts:
        unique[item["absolute_path"]] = item
    return list(unique.values())


def _workspace_root_from_runtime_root(root_dir: Path) -> Path:
    root = Path(root_dir).resolve()
    if root.name == "backend" and root.parent.exists():
        return root.parent.resolve()
    if root.name == "runtime_state" and root.parent.name == "storage" and root.parent.parent.exists():
        return root.parent.parent.resolve()
    if root.name == "storage" and root.parent.exists():
        return root.parent.resolve()
    return root


def _unwrap_runtime_event(event: dict[str, Any]) -> dict[str, Any]:
    """Accept both ledger JSONL events and exported runtime_loop_event wrappers."""
    payload = dict(event or {})
    wrapped_event = payload.get("event")
    if isinstance(wrapped_event, dict) and wrapped_event.get("event_type"):
        return dict(wrapped_event)
    return payload


def _tool_result_indicates_write_success(result: str) -> bool:
    text = str(result or "")
    lowered = text.lower()
    return "write succeeded" in lowered or "wrote file" in lowered or "successfully wrote" in lowered


def _path_from_write_result(result: str) -> str:
    text = str(result or "").strip()
    for marker in ("Write succeeded:", "write succeeded:", "Wrote file:", "wrote file:"):
        if marker in text:
            return text.split(marker, 1)[1].strip().splitlines()[0].strip()
    return ""


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


def _repeated_tool_halt_answer_metadata() -> dict[str, str]:
    return {
        "answer_channel": "answer_candidate",
        "answer_source": "runtime_loop_control",
        "answer_canonical_state": "progress_only",
        "answer_persist_policy": "persist_debug_only",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "repeated_tool_halt",
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


def _artifact_success_fallback_answer_metadata(*, source: str = "runtime_loop.artifact_success_fallback") -> dict[str, str]:
    return {
        "answer_channel": "tool_visible_summary",
        "answer_source": source,
        "answer_canonical_state": "stable_answer",
        "answer_persist_policy": "persist_canonical",
        "answer_finalization_policy": "none",
        "answer_fallback_reason": "artifact_success_fallback",
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


def _build_repeated_tool_halt_message(*, tool_observation_count: int = 0) -> str:
    evidence_text = (
        f"已经连续收到了 {tool_observation_count} 条相似工具结果"
        if tool_observation_count > 0
        else "已经连续触发了相似工具调用"
    )
    return (
        f"{evidence_text}，继续重复读取不会带来新的信息，所以我先停止本轮重复工具调用。"
        "你可以直接继续基于当前已绑定对象提问，我会从现有上下文继续收口。"
    )


def _build_artifact_success_fallback_answer(
    *,
    selected_template_payload: dict[str, Any],
    artifact_validation: dict[str, Any],
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    artifact_items = [
        str(dict(item).get("path") or "").strip()
        for item in list(artifact_validation.get("artifacts") or [])
        if str(dict(item).get("path") or "").strip()
    ]
    task_title = str(
        selected_template_payload.get("title")
        or selected_template_payload.get("task_mode")
        or selected_template_payload.get("template_id")
        or "任务"
    ).strip()
    summary = _forced_tool_synthesis_answer(
        user_message="",
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    )
    lines = [f"{task_title}已完成真实产物写入。"]
    if artifact_items:
        lines.append("产物文件：")
        lines.extend(f"- {item}" for item in artifact_items[:6])
    if summary:
        lines.append(summary)
    else:
        lines.append("本轮所需 artifact 已通过 write_file 写入并通过存在性校验。")
    lines.append("模型后续收口阶段中断，但正式产物已经落盘，可基于现有产物继续下一阶段。")
    return "\n".join(lines)


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


def _builtin_tool_lane_answer_from_observation(
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
        route="builtin_tool_lane",
        execution_posture="builtin_tool_lane",
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
        "answer_source": f"builtin_tool_lane.{tool_name}",
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
    if tool_name in {"mcp_pdf", "pdf"}:
        return _project_pdf_tool_context(tool_args=tool_args, result_text=result_text)
    if tool_name in {"mcp_structured_data", "structured_data"}:
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
