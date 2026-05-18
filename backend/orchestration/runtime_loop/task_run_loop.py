from __future__ import annotations

import inspect
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from capability_system import build_default_operation_registry
from capability_system.local_mcp_registry import get_local_mcp_unit, get_local_mcp_unit_for_source_kind
from capability_system.search_policy import (
    normalize_search_policy,
    operation_allowed_by_search_policy,
    tool_allowed_by_search_policy,
)
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.resource_gate import OperationGate, OperationGatePipelineContext
from project_layout import ProjectLayout
from output_boundary.boundary import AssistantOutputBoundary
from memory_system import WorkingMemoryFinalizer, WorkingMemoryService
from artifact_system import ArtifactRepositoryService
from tasks.flow_registry import TaskFlowRegistry
from tasks.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec
from tasks.task_graph_models import TaskGraphDefinition
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
from tasks.execution_recipe_models import ExecutionRecipe, TaskValidationRule
from capability_system.tool_authorization import resolve_tool_operation_id
from understanding.capability_resolution_view import capability_resolution_view

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
from .langgraph_checkpoint_adapter import LangGraphCheckpointStoreAdapter
from .runtime_object_store import RuntimeObjectStore
from .artifact_refs import ArtifactRefIndex, collect_task_result_output_refs, dedupe_refs as dedupe_artifact_refs
from .agent_delegation_executor import AgentDelegationExecutor
from .langgraph_coordination_runtime import LangGraphCoordinationRuntime, LangGraphCoordinationRuntimeResult
from .project_supervision import (
    build_runtime_status,
    classify_blocker,
    clear_recovered_failure,
    ensure_project_runtime_inputs,
    latest_artifact_files_from_root,
    make_initial_project_ledger,
    make_supervision_record,
    record_progress_unit_commit,
    record_delivery_state,
    record_failure,
)
from .node_execution_request import NodeExecutionRequest, NodeResultReadyEvent
from .task_artifact_materializer import MaterializedTaskArtifacts, materialize_task_artifacts
from .task_graph_monitoring import (
    compact_monitor_snapshot,
    evaluate_task_graph_monitor_snapshot,
)
from .timeline_ledger import TimelineLedgerStore
from .model_adoption import build_model_response_runtime_adoption, build_runtime_capability_state
from .models import (
    AgentDispatchPlan,
    AgentDispatchRecord,
    AgentHandoffEnvelope,
    AgentRun,
    AgentRunResult,
    CoordinationBarrierState,
    CoordinationMergeResult,
    CoordinationNodeRun,
    CoordinationRun,
    ProjectProgressLedger,
    ProjectRuntimeStatus,
    QueuedAgentNotification,
    RuntimeLoopState,
    SupervisionRecord,
    TaskRun,
)
from .observation_aggregator import ObservationAggregation, ObservationAggregator
from .safety import build_task_safety_validators
from .stage_projection import StageProjectionCycle
from .state_index import RuntimeStateIndex
from .trace_reader import RuntimeLoopTraceReader
from .delegation_models import AgentDelegationRequest
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


@dataclass(frozen=True, slots=True)
class FinishedTaskRunResult:
    events: tuple[Any, ...]
    continuation_payload: dict[str, Any] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "continuation_payload", dict(self.continuation_payload or {}))


class TaskRunLoop:
    """Single-agent loop owner.

    This first slice only creates the durable loop trace. Model/tool execution
    will be connected one system at a time after this event/checkpoint spine is
    stable.
    """

    def _resolve_task_graph_view(self, graph_ref: str):
        target = str(graph_ref or "").strip()
        if not target:
            return None
        task_graph = self.task_flow_registry.get_task_graph(target)
        if task_graph is None:
            return None
        return self.task_flow_registry.derive_coordination_task_view_from_graph(task_graph)

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
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.coordination_checkpoints = LangGraphCheckpointStoreAdapter(self.root_dir)
        self.timeline_ledger = TimelineLedgerStore(self.root_dir)
        self.trace_reader = RuntimeLoopTraceReader(
            self.state_index,
            self.event_log,
            self.checkpoints,
            self.coordination_checkpoints,
            self.timeline_ledger,
        )
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()
        self.task_flow_registry = TaskFlowRegistry(self.backend_dir)
        self.agent_registry = AgentRegistry(self.backend_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.backend_dir)
        self.worker_agent_factory = WorkerAgentFactory(self.backend_dir)
        self.langgraph_coordination_runtime = LangGraphCoordinationRuntime(
            root_dir=self.root_dir,
            registry_base_dir=self.backend_dir,
            state_index=self.state_index,
            event_log=self.event_log,
            task_flow_registry=self.task_flow_registry,
            trace_reader=self,
        )
        self.artifact_ref_index = ArtifactRefIndex(self.state_index, self)
        self.evidence_orchestrator = evidence_orchestrator
        self.working_memory = WorkingMemoryService(_working_memory_root_for_loop(self.root_dir))
        self.working_memory_finalizer = WorkingMemoryFinalizer(self.working_memory)
        self.artifact_repository = ArtifactRepositoryService(_artifact_repository_root_for_loop(self.root_dir))

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

    def get_session_live_monitor(self, session_id: str) -> dict[str, Any]:
        return self.trace_reader.get_session_live_monitor(session_id)

    def get_task_run_live_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        return self.trace_reader.get_task_run_live_monitor(task_run_id)

    def get_task_graph_run_monitor(self, task_run_id: str) -> dict[str, Any] | None:
        return self.trace_reader.get_task_graph_run_monitor(task_run_id)

    def get_coordination_run_monitor(self, coordination_run_id: str) -> dict[str, Any] | None:
        return self.trace_reader.get_coordination_run_monitor(coordination_run_id)

    def get_project_runtime_status(self, project_id: str) -> dict[str, Any] | None:
        status = self.state_index.get_project_runtime_status(project_id)
        if status is None:
            return None
        ledger = self.state_index.get_project_progress_ledger(project_id)
        return {
            "project_runtime_status": status.to_dict(),
            "project_progress_ledger": ledger.to_dict() if ledger is not None else None,
            "supervision_records": [item.to_dict() for item in self.state_index.list_project_supervision_records(project_id)[-50:]],
            "authority": "orchestration.project_runtime_status_view",
        }

    def evaluate_task_graph_monitor(
        self,
        task_run_id: str,
        *,
        monitor_node_id: str = "",
        monitor_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        monitor = self.get_task_graph_run_monitor(task_run_id)
        if monitor is None:
            return None
        effective_policy = self._resolve_task_graph_monitor_policy(
            monitor,
            monitor_node_id=monitor_node_id,
            override_policy=dict(monitor_policy or {}),
        )
        effective_node_id = monitor_node_id or str(effective_policy.get("monitor_node_id") or "")
        decision = evaluate_task_graph_monitor_snapshot(
            monitor,
            monitor_node_id=effective_node_id,
            monitor_policy=effective_policy,
        )
        project_id = str(
            dict(monitor.get("project") or {}).get("project_id")
            or dict(decision.observed).get("project_id")
            or task_run_id
        ).strip()
        session_id = str(monitor.get("session_id") or "")
        record = make_supervision_record(
            project_id=project_id,
            session_id=session_id,
            task_run_id=decision.task_run_id,
            coordination_run_id=decision.coordination_run_id,
            issue_type=f"monitor_{decision.reason}",
            issue_summary=decision.summary,
            root_cause=decision.reason,
            repair_action=decision.action,
            followup_status="recorded" if decision.action == "no_action" else "pending_control",
            diagnostics={
                "monitor_node_id": effective_node_id,
                "monitor_policy": effective_policy,
                "monitor_decision": decision.to_dict(),
                "monitor_snapshot": compact_monitor_snapshot(monitor),
            },
        )
        self.state_index.upsert_supervision_record(record)
        return {
            "authority": "orchestration.task_graph_monitor_evaluation",
            "task_run_id": task_run_id,
            "coordination_run_id": decision.coordination_run_id,
            "monitor_node_id": effective_node_id,
            "decision": decision.to_dict(),
            "supervision_record": record.to_dict(),
            "monitor_snapshot": compact_monitor_snapshot(monitor),
        }

    def list_task_graph_monitor_decisions(self, task_run_id: str) -> dict[str, Any]:
        records = self.state_index.list_task_supervision_records(task_run_id)
        decision_records = [
            record.to_dict()
            for record in records
            if dict(record.diagnostics or {}).get("monitor_decision")
        ]
        return {
            "authority": "orchestration.task_graph_monitor_decisions",
            "task_run_id": task_run_id,
            "decisions": [
                dict(dict(item.get("diagnostics") or {}).get("monitor_decision") or {})
                for item in decision_records
            ],
            "supervision_records": decision_records,
        }

    def _resolve_task_graph_monitor_policy(
        self,
        monitor: dict[str, Any],
        *,
        monitor_node_id: str = "",
        override_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        override = dict(override_policy or {})
        topology = dict(monitor.get("topology") or {})
        nodes = [dict(item) for item in list(topology.get("nodes") or []) if isinstance(item, dict)]
        monitor_nodes = [
            node
            for node in nodes
            if str(node.get("node_type") or "") == "runtime_monitor"
            or str(node.get("node_id") or "") == monitor_node_id
        ]
        selected = next(
            (node for node in monitor_nodes if str(node.get("node_id") or "") == monitor_node_id),
            monitor_nodes[0] if monitor_nodes else {},
        )
        metadata = dict(selected.get("metadata") or {})
        policy = {
            **dict(metadata.get("monitor_policy") or {}),
            **dict(selected.get("monitor_policy") or {}),
            **override,
        }
        background = dict(metadata.get("background_policy") or selected.get("background_policy") or {})
        if "stale_after_seconds" not in policy and background.get("stale_after_seconds"):
            policy["stale_after_seconds"] = background.get("stale_after_seconds")
        if "monitor_node_id" not in policy and selected:
            policy["monitor_node_id"] = str(selected.get("node_id") or "")
        return policy

    def get_task_run_artifacts(self, task_run_id: str) -> dict[str, Any]:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return {"task_run_id": task_run_id, "artifact_root": "", "files": [], "authority": "orchestration.task_run_artifacts"}
        diagnostics = dict(task_run.diagnostics or {})
        artifact_materialization = dict(diagnostics.get("artifact_materialization") or {})
        artifact_root = str(artifact_materialization.get("artifact_root") or "")
        files = latest_artifact_files_from_root(self.root_dir.parent, artifact_root)
        return {
            "task_run_id": task_run_id,
            "artifact_root": artifact_root,
            "files": files,
            "created_files": list(artifact_materialization.get("created_files") or []),
            "artifact_refs": list(artifact_materialization.get("artifact_refs") or []),
            "authority": "orchestration.task_run_artifacts",
        }

    def get_task_run_memory_receipts(self, task_run_id: str) -> dict[str, Any]:
        monitor = self.get_task_graph_run_monitor(task_run_id) or {}
        return {
            "task_run_id": task_run_id,
            "memory_operations": list(monitor.get("memory_operations") or []),
            "stage_results": [
                item
                for item in list(monitor.get("stage_results") or [])
                if list(dict(item).get("working_memory_refs") or [])
            ],
            "authority": "orchestration.task_run_memory_receipts",
        }

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
        graph_ref: str = "",
        graph_payload: dict[str, Any] | None = None,
        topology_template_payload: dict[str, Any] | None = None,
        coordinator_agent_id: str = "",
        topology_template_id: str = "",
        communication_protocol_id: str = "",
        handoff_policy: str = "",
        failure_policy: str = "",
        merge_policy: str = "",
        runtime_assembly: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> TaskRunLoopStartResult:
        now = time.time()
        assembly_payload = dict(runtime_assembly or {})
        assembly_ref = str(assembly_payload.get("assembly_id") or "")
        manifest_ref = str(assembly_payload.get("manifest_ref") or "")
        working_memory_refs = _working_memory_refs_from_assembly(assembly_payload)
        working_memory_diag = _working_memory_diagnostics_from_assembly(assembly_payload)
        dispatch_graph_payload = dict(graph_payload or {})
        dispatch_topology_payload = dict(topology_template_payload or {})
        resolved_graph_ref = str(
            graph_ref
            or dispatch_graph_payload.get("graph_id")
            or dispatch_graph_payload.get("task_graph_id")
            or assembly_payload.get("graph_ref")
            or ""
        ).strip()
        task_run_id = f"taskrun:{session_id}:{task_id}:{uuid.uuid4().hex[:8]}"
        agent_run_id = f"agrun:{task_run_id}:main"
        coordination_run = (
            CoordinationRun(
                coordination_run_id=f"coordrun:{task_run_id}:primary",
                task_run_id=task_run_id,
                graph_ref=resolved_graph_ref,
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
                    **dict(diagnostics or {}),
                },
            )
            if resolved_graph_ref
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
                "graph_ref": resolved_graph_ref,
                "adoption_mode": adoption_mode,
                "runtime_assembly_ref": assembly_ref,
                "contract_manifest_ref": manifest_ref,
                "working_memory_refs": working_memory_refs,
            },
            refs={
                "task_contract_ref": task_contract_ref,
                "runtime_assembly_ref": assembly_ref,
                "contract_manifest_ref": manifest_ref,
                "working_memory_ref": ",".join(working_memory_refs),
            },
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
        initial_dispatch_plan = (
            _compile_agent_dispatch_plan_from_graph_payload(
                task_run_id=task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                graph_payload=dispatch_graph_payload,
                topology_template_payload=dispatch_topology_payload,
            )
            if coordination_run is not None
            else None
        )
        dispatch_plan_event = None
        if initial_dispatch_plan is not None:
            dispatch_plan_event = self.event_log.append(
                task_run_id,
                "agent_dispatch_plan_compiled",
                payload={"agent_dispatch_plan": initial_dispatch_plan.to_dict(), "source": "runtime_start"},
                refs={
                    "coordination_run_ref": coordination_run.coordination_run_id,
                    "dispatch_plan_ref": initial_dispatch_plan.dispatch_plan_id,
                },
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
                "runtime_assembly_ref": assembly_ref,
                "contract_manifest_ref": manifest_ref,
                "working_memory_refs": working_memory_refs,
                **({"agent_dispatch_plan": initial_dispatch_plan.to_dict()} if initial_dispatch_plan is not None else {}),
                **working_memory_diag,
                **dict(diagnostics or {}),
            },
        )
        checkpoint = self.checkpoints.write(
            state,
            event_offset=iteration.offset,
            execution_refs=(),
            execution_state_ref="",
            working_memory_refs=tuple(working_memory_refs),
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
                "graph_ref": resolved_graph_ref,
                "multi_agent_enabled": coordination_run is not None,
                "loop_limits": self.limits.to_dict(),
                "runtime_assembly_ref": assembly_ref,
                "contract_manifest_ref": manifest_ref,
                "working_memory_refs": working_memory_refs,
                **({"agent_dispatch_plan": initial_dispatch_plan.to_dict()} if initial_dispatch_plan is not None else {}),
                **working_memory_diag,
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
        if dispatch_plan_event is not None:
            ordered_events.append(dispatch_plan_event.to_dict())
        ordered_events.extend((iteration.to_dict(), checkpoint_event.to_dict()))
        return TaskRunLoopStartResult(
            task_run=task_run,
            agent_run=agent_run,
            coordination_run=coordination_run,
            loop_state=state,
            checkpoint=checkpoint,
            events=tuple(ordered_events),
        )

    def start_task_graph_run(
        self,
        *,
        session_id: str,
        graph: TaskGraphDefinition,
        runtime_spec: TaskGraphRuntimeSpec,
        task_id: str = "",
        initial_inputs: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> TaskRunLoopStartResult:
        """Create a durable runtime-loop run from a first-class TaskGraphDefinition."""
        source_initial_inputs = dict(initial_inputs or {})
        if not source_initial_inputs:
            restored_initial_inputs = self._restore_task_graph_initial_inputs(
                session_id=session_id,
                graph_id=graph.graph_id,
            )
            if restored_initial_inputs:
                source_initial_inputs = restored_initial_inputs
        effective_initial_inputs = ensure_project_runtime_inputs(
            initial_inputs=source_initial_inputs,
            graph_id=graph.graph_id,
            session_id=session_id,
        )
        runtime_policy = dict(graph.runtime_policy or {})
        coordinator_agent_id = str(runtime_spec.coordinator_agent_id or runtime_policy.get("coordinator_agent_id") or "agent:0").strip() or "agent:0"
        graph_definition_ref = self.runtime_objects.put_json_once(
            "task_graph_definitions",
            f"{session_id}:{task_id or graph.graph_id}:{graph.graph_id}",
            graph.to_dict(),
        )
        graph_runtime_spec_ref = self.runtime_objects.put_json_once(
            "task_graph_runtime_specs",
            f"{session_id}:{task_id or graph.graph_id}:{graph.graph_id}",
            runtime_spec.to_dict(),
        )
        graph_payload = _dispatch_graph_payload_from_task_graph_runtime_spec(
            graph=graph,
            runtime_spec=runtime_spec,
        )
        runtime_assembly = {
            "authority": "orchestration.task_graph_runtime_spec_assembly",
            "assembly_id": f"runtime-assembly:task-graph:{graph.graph_id}",
            "graph_ref": graph.graph_id,
            "runtime_spec_ref": f"runtime-spec:task-graph:{graph.graph_id}",
            "runtime_spec": runtime_spec.to_dict(),
            "initial_inputs": dict(effective_initial_inputs),
            "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
            "working_memory_policy": dict(graph.working_memory_policy or {}),
        }
        initial_inputs_ref = self.runtime_objects.put_object(
            "task_graph_initial_inputs",
            f"{session_id}:{task_id or graph.graph_id}:{graph.graph_id}",
            {
                "session_id": session_id,
                "task_id": task_id or graph.graph_id,
                "graph_id": graph.graph_id,
                "initial_inputs": dict(source_initial_inputs),
            },
        )
        start = self.start(
            session_id=session_id,
            task_id=task_id or graph.graph_id,
            task_contract_ref=graph.graph_contract_id or graph.graph_id,
            agent_id=coordinator_agent_id,
            agent_profile_id=str(runtime_policy.get("coordinator_agent_profile_id") or "task_graph_coordinator"),
            runtime_lane=str(runtime_policy.get("runtime_lane") or "task_graph_coordination"),
            adoption_mode="task_graph_runtime",
            graph_ref=graph.graph_id,
            graph_payload=graph_payload,
            coordinator_agent_id=coordinator_agent_id,
            topology_template_id=str(graph.metadata.get("topology_template_id") or ""),
            communication_protocol_id=graph.default_protocol_id,
            handoff_policy=str((runtime_spec.communication_modes or ("handoff",))[0]),
            failure_policy=str(runtime_policy.get("failure_policy") or ""),
            merge_policy=str(runtime_policy.get("merge_policy") or ""),
            runtime_assembly=runtime_assembly,
            diagnostics={
                "task_graph_run": True,
                "task_graph_id": graph.graph_id,
                "task_graph_title": graph.title,
                "task_family": str(getattr(graph, "task_family", "") or ""),
                "task_graph_publish_state": graph.publish_state,
                "task_graph_definition_ref": graph_definition_ref,
                "task_graph_runtime_spec_ref": graph_runtime_spec_ref,
                "task_graph_initial_inputs_ref": initial_inputs_ref,
                "task_graph_runtime_spec_valid": runtime_spec.valid,
                "task_graph_initial_input_keys": sorted(str(key) for key in source_initial_inputs.keys()),
                "project_id": str(effective_initial_inputs.get("project_id") or ""),
                "project_title": str(effective_initial_inputs.get("project_title") or ""),
                "metric_label": str(effective_initial_inputs.get("metric_label") or "units"),
                "target_metric_total": int(
                    effective_initial_inputs.get("target_metric_total")
                    or effective_initial_inputs.get("target_words")
                    or 0
                ),
                **dict(diagnostics or {}),
            },
        )
        if start.coordination_run is None:
            return start
        if not self.langgraph_coordination_runtime.supports(start.coordination_run):
            raise RuntimeError(
                "TaskGraph coordination run is missing LangGraph stage contracts; legacy initialization fallback was removed."
            )
        initialized = self.langgraph_coordination_runtime.initialize(
            coordination_run=start.coordination_run,
            event_task_run_id=start.task_run.task_run_id,
            inherited_inputs=dict(effective_initial_inputs),
        )
        events = [dict(item) for item in start.events]
        events.extend(
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in initialized.events
        )
        refreshed_task_run = self.state_index.get_task_run(start.task_run.task_run_id) or start.task_run
        refreshed_coordination_run = (
            self.state_index.get_coordination_run(start.coordination_run.coordination_run_id)
            or start.coordination_run
        )
        state = RuntimeLoopState(
            **{
                **start.loop_state.to_dict(),
                "diagnostics": {
                    **dict(start.loop_state.diagnostics),
                    "langgraph_coordination_initialized": True,
                    "langgraph_checkpoint_ref": initialized.checkpoint_ref,
                    "stage_execution_request": (
                        initialized.stage_execution_request.to_dict()
                        if initialized.stage_execution_request is not None
                        else {}
                    ),
                },
            }
        )
        project_id = str(effective_initial_inputs.get("project_id") or "").strip()
        if project_id:
            ledger = self.state_index.get_project_progress_ledger(project_id)
            if ledger is None:
                ledger = make_initial_project_ledger(
                    project_id=project_id,
                    session_id=session_id,
                    graph_id=graph.graph_id,
                    task_family=str(getattr(graph, "task_family", "") or ""),
                    project_title=str(effective_initial_inputs.get("project_title") or project_id),
                    metric_label=str(effective_initial_inputs.get("metric_label") or "units"),
                    target_metric_total=int(
                        effective_initial_inputs.get("target_metric_total")
                        or effective_initial_inputs.get("target_words")
                        or 0
                    ),
                    task_run_id=refreshed_task_run.task_run_id,
                )
            else:
                ledger = ProjectProgressLedger(
                    **{
                        **ledger.to_dict(),
                        "run_chain": [*list(ledger.run_chain), refreshed_task_run.task_run_id] if refreshed_task_run.task_run_id not in ledger.run_chain else list(ledger.run_chain),
                        "updated_at": time.time(),
                    }
                )
            self.state_index.upsert_project_progress_ledger(ledger)
            project_status = build_runtime_status(
                ledger=ledger,
                task_run_id=refreshed_task_run.task_run_id,
                coordination_run_id=refreshed_coordination_run.coordination_run_id,
                active_run_status=str(refreshed_coordination_run.status or refreshed_task_run.status or "running"),
                latest_artifact_root=str(dict(refreshed_task_run.diagnostics or {}).get("artifact_materialization", {}).get("artifact_root") or ""),
                latest_event_offset=int(refreshed_task_run.latest_event_offset or 0),
                latest_event_at=float(refreshed_task_run.updated_at or time.time()),
                last_effective_output_at=float(refreshed_task_run.updated_at or time.time()),
                blocker={},
                recovery_state={},
            )
            self.state_index.upsert_project_runtime_status(project_status)
            self.state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=session_id,
                    task_run_id=refreshed_task_run.task_run_id,
                    coordination_run_id=refreshed_coordination_run.coordination_run_id,
                    issue_type="formal_run_started",
                    issue_summary="Formal project run started.",
                    followup_status="watching",
                    diagnostics={
                        "graph_id": graph.graph_id,
                        "metric_label": str(effective_initial_inputs.get("metric_label") or "units"),
                        "target_metric_total": int(
                            effective_initial_inputs.get("target_metric_total")
                            or effective_initial_inputs.get("target_words")
                            or 0
                        ),
                    },
                )
            )
        return TaskRunLoopStartResult(
            task_run=refreshed_task_run,
            agent_run=start.agent_run,
            coordination_run=refreshed_coordination_run,
            loop_state=state,
            checkpoint=start.checkpoint,
            events=tuple(events),
        )

    def _restore_task_graph_initial_inputs(self, *, session_id: str, graph_id: str) -> dict[str, Any]:
        target_graph_id = str(graph_id or "").strip()
        if not session_id or not target_graph_id:
            return {}
        candidates = sorted(
            (
                task_run
                for task_run in self.state_index.list_session_task_runs(session_id)
                if str(task_run.task_id or "").strip() == target_graph_id
                and str(dict(task_run.diagnostics or {}).get("task_graph_id") or "").strip() == target_graph_id
            ),
            key=lambda item: float(item.updated_at or 0.0),
            reverse=True,
        )
        for task_run in candidates:
            diagnostics = dict(task_run.diagnostics or {})
            initial_inputs_ref = str(diagnostics.get("task_graph_initial_inputs_ref") or "").strip()
            if initial_inputs_ref:
                payload = self.runtime_objects.get_object(initial_inputs_ref)
                restored = dict(payload.get("initial_inputs") or {})
                if restored:
                    return restored
            runtime_assembly_ref = str(diagnostics.get("runtime_assembly_ref") or "").strip()
            if runtime_assembly_ref:
                assembly = self.runtime_objects.get_object(runtime_assembly_ref)
                restored = dict(assembly.get("initial_inputs") or {})
                if restored:
                    return restored
        return {}

    def submit_working_memory_candidates(
        self,
        *,
        task_run_id: str,
        node_id: str = "",
        node_run_id: str = "",
        run_attempt_id: str = "",
        stage_id: str = "",
        writer_agent_id: str = "",
        candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> tuple[Any, ...]:
        stored = []
        for index, candidate in enumerate(list(candidates or ())):
            if not isinstance(candidate, dict):
                continue
            payload = {
                "task_run_id": task_run_id,
                "owner_node_id": node_id or str(candidate.get("owner_node_id") or ""),
                "node_run_id": node_run_id or str(candidate.get("node_run_id") or ""),
                "run_attempt_id": run_attempt_id or str(candidate.get("run_attempt_id") or ""),
                "stage_id": stage_id or str(candidate.get("stage_id") or ""),
                "writer_agent_id": writer_agent_id or str(candidate.get("writer_agent_id") or ""),
                **dict(candidate),
            }
            if not str(payload.get("idempotency_key") or "").strip():
                payload["idempotency_key"] = f"{task_run_id}:{payload.get('owner_node_id')}:{payload.get('node_run_id')}:{payload.get('kind')}:{index}"
            stored.append(self.working_memory.create_item(**payload))
        event = self.event_log.append(
            task_run_id,
            "working_memory_candidates_submitted",
            payload={
                "candidate_count": len(stored),
                "work_memory_ids": [item.work_memory_id for item in stored],
                "node_id": node_id,
                "node_run_id": node_run_id,
                "run_attempt_id": run_attempt_id,
                "stage_id": stage_id,
                "writer_agent_id": writer_agent_id,
            },
            refs={"working_memory_ref": ",".join(item.work_memory_id for item in stored)},
        )
        _ = event
        return tuple(stored)

    def finalize_working_memory(
        self,
        *,
        task_run_id: str,
        actor_id: str = "runloop",
        terminal_reason: str = "completed",
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.working_memory_finalizer.finalize_task_run(
            task_run_id,
            actor_id=actor_id,
            terminal_reason=terminal_reason,
            policy=policy,
        )
        event = self.event_log.append(
            task_run_id,
            "working_memory_finalized",
            payload=result.to_dict(),
            refs={
                "working_memory_finalization_ref": result.archive_report_path,
                "working_memory_task_run_ref": task_run_id,
            },
        )
        return {
            "result": result.to_dict(),
            "event": event.to_dict(),
        }

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
        search_policy: list[str] | None = None,
    ):
        """Run the current single-agent lane inside the TaskRunLoop trace spine."""

        allowed_search_sources = _resolve_runtime_search_sources(
            search_policy=search_policy,
            task_selection=task_selection,
        )
        chain_runtime = agent_runtime_chain.build_runtime(
            session_id=session_id,
            task_id=task_id,
            turn_id=str(dict(task_selection or {}).get("turn_id") or ""),
            message=user_message,
            source=source,
            current_turn_context_override=dict(task_selection or {}),
            task_selection={
                **dict(task_selection or {}),
                "search_policy": sorted(allowed_search_sources),
            },
            agent_runtime_profile=agent_runtime_profile,
        )
        task_operation = dict(chain_runtime.get("task_operation") or {})
        task_contract = dict(task_operation.get("task_contract") or {})
        task_intent_contract = dict(task_operation.get("task_intent_contract") or {})
        selected_recipe_payload = dict(task_operation.get("selected_recipe") or {})
        bundle_spec_payload = dict(task_operation.get("bundle_spec") or {})
        task_spec_payload = dict(task_operation.get("task_spec") or {})
        task_execution_assembly_payload = dict(task_operation.get("task_execution_assembly") or {})
        task_projection_binding_payload = dict(task_operation.get("task_projection_binding") or {})
        task_flow_contract_binding_payload = dict(task_operation.get("task_flow_contract_binding") or {})
        task_execution_policy_payload = dict(task_operation.get("task_execution_policy") or {})
        task_agent_adoption_plan_payload = dict(task_operation.get("task_agent_adoption_plan") or {})
        task_memory_request_profile_payload = dict(task_operation.get("task_memory_request_profile") or {})
        task_communication_protocol_payload = dict(task_operation.get("task_communication_protocol") or {})
        raw_graph_payload = dict(task_operation.get("graph_record") or {})
        task_graph_payload = dict(task_operation.get("task_graph_record") or task_operation.get("graph_record") or {})
        runtime_spec_payload = dict(task_operation.get("task_graph_runtime_spec") or {})
        graph_payload = _normalize_runtime_graph_payload(
            raw_graph_payload=raw_graph_payload,
            task_graph_payload=task_graph_payload,
            runtime_spec_payload=runtime_spec_payload,
        )
        task_body_orchestration_payload = dict(chain_runtime.get("task_body_orchestration") or task_operation.get("task_body_orchestration") or {})
        agent_runtime_spec_payload = dict(chain_runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
        memory_view = dict(chain_runtime.get("memory_runtime_view") or {})
        context_policy = dict(chain_runtime.get("context_policy_result") or {})
        adoption_mode = str(task_agent_adoption_plan_payload.get("adoption_mode") or "adopt_existing")
        effective_limits = _runtime_limits_from_task_operation(task_operation, fallback=self.limits)
        result_refs: list[str] = []
        final_main_context: dict[str, Any] = {}
        final_task_summary_refs: list[dict[str, Any]] = []
        start = self.start(
            session_id=session_id,
            task_id=task_id,
            task_contract_ref=str(task_contract.get("task_id") or task_id),
            agent_id=str(agent_runtime_spec_payload.get("agent_id") or "agent:0"),
            agent_profile_id=str(
                getattr(agent_runtime_profile, "agent_profile_id", "") or "main_interactive_agent"
            ),
            runtime_lane=str(agent_runtime_spec_payload.get("runtime_lane") or "full_interactive"),
            task_agent_binding_ref=str(task_execution_assembly_payload.get("task_agent_binding_ref") or ""),
            adoption_mode=adoption_mode,
            graph_ref=str(
                task_graph_payload.get("graph_id")
                or graph_payload.get("graph_id")
                or graph_payload.get("task_graph_id")
                or ""
            ),
            coordinator_agent_id=str(graph_payload.get("coordinator_agent_id") or ""),
            topology_template_id=str(graph_payload.get("topology_template_id") or ""),
            communication_protocol_id=str(task_communication_protocol_payload.get("protocol_id") or ""),
            handoff_policy=str(graph_payload.get("handoff_policy") or ""),
            failure_policy=str(graph_payload.get("conflict_resolution_policy") or ""),
            merge_policy=str(graph_payload.get("output_merge_policy") or ""),
            diagnostics={
                "runtime_channel": "single_agent_runtime",
                "search_policy": list(search_policy) if search_policy is not None else None,
                "allowed_search_sources": sorted(allowed_search_sources),
            },
        )
        state = start.loop_state
        search_policy_event = self.event_log.append(
            state.task_run_id,
            "search_policy_resolved",
            payload={
                "search_policy": list(search_policy) if search_policy is not None else None,
                "allowed_sources": sorted(allowed_search_sources),
            },
        )
        yield {"type": "runtime_loop_event", "event": search_policy_event.to_dict()}
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

        task_contract_ref = str(task_contract.get("task_id") or task_id)
        runtime_task_ledger = _build_initial_task_run_ledger(
            task_run_id=state.task_run_id,
            task_contract_ref=task_contract_ref,
            task_spec_payload=task_spec_payload,
            selected_recipe_payload=selected_recipe_payload,
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
                "selected_recipe": selected_recipe_payload,
                "bundle_spec": bundle_spec_payload,
                "task_spec": task_spec_payload,
                "task_execution_assembly": task_execution_assembly_payload,
                "task_projection_binding": task_projection_binding_payload,
                "task_flow_contract_binding": task_flow_contract_binding_payload,
                "task_execution_policy": task_execution_policy_payload,
                "task_agent_adoption_plan": task_agent_adoption_plan_payload,
                "task_memory_request_profile": task_memory_request_profile_payload,
                "task_communication_protocol": task_communication_protocol_payload,
                "graph_record": graph_payload,
                "task_graph_record": task_graph_payload,
                "task_graph_runtime_spec": runtime_spec_payload,
                "task_body_orchestration": task_body_orchestration_payload,
                "agent_runtime_spec": agent_runtime_spec_payload,
                "task_run_ledger": runtime_task_ledger.to_dict() if runtime_task_ledger is not None else {},
                "source": source,
            },
            refs={
                "task_contract_ref": task_contract_ref,
                "task_intent_ref": str(task_intent_contract.get("task_intent_id") or ""),
                "task_template_id": str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
                "task_spec_ref": str(task_spec_payload.get("task_spec_ref") or ""),
                "task_execution_assembly_ref": str(task_execution_assembly_payload.get("assembly_id") or ""),
                "task_projection_binding_ref": str(task_projection_binding_payload.get("binding_id") or ""),
                "task_flow_contract_binding_ref": str(task_flow_contract_binding_payload.get("binding_id") or ""),
                "task_execution_policy_ref": str(task_execution_policy_payload.get("execution_policy_id") or task_execution_policy_payload.get("plan_id") or ""),
                "task_agent_adoption_plan_ref": str(task_agent_adoption_plan_payload.get("plan_id") or ""),
                "task_memory_request_profile_ref": str(task_memory_request_profile_payload.get("profile_id") or ""),
                "task_communication_protocol_ref": str(task_communication_protocol_payload.get("protocol_id") or ""),
                "graph_ref": str(
                    task_graph_payload.get("graph_id")
                    or graph_payload.get("graph_id")
                    or graph_payload.get("task_graph_id")
                    or ""
                ),
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
            graph_payload=graph_payload,
            task_graph_payload=task_graph_payload,
            communication_protocol_payload=task_communication_protocol_payload,
            task_agent_adoption_plan_payload=task_agent_adoption_plan_payload,
            effective_limits=effective_limits,
            task_spec_payload=task_spec_payload,
        )
        for runtime_event in runtime_object_events:
            yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
        latest_streamed_offset = max(
            [task_event.offset, *[int(getattr(event, "offset", -1)) for event in runtime_object_events]],
            default=task_event.offset,
        )
        for logged_event in self.event_log.list_events(state.task_run_id):
            if logged_event.offset > latest_streamed_offset:
                yield {"type": "runtime_loop_event", "event": logged_event.to_dict()}
                latest_streamed_offset = max(latest_streamed_offset, logged_event.offset)
        initial_coordination_run = (
            self.state_index.list_task_coordination_runs(state.task_run_id)[0]
            if self.state_index.list_task_coordination_runs(state.task_run_id)
            else None
        )
        if initial_coordination_run is not None:
            initial_coordination_state = self.langgraph_coordination_runtime.checkpoints.get_state(
                thread_id=initial_coordination_run.coordination_run_id
            )
            initial_request_payload = dict(dict(initial_coordination_state or {}).get("stage_execution_request") or {})
            if initial_request_payload:
                initial_request = NodeExecutionRequest.from_dict(initial_request_payload)
                continuation_payload = LangGraphCoordinationRuntimeResult(
                    state=dict(initial_coordination_state or {}),
                    stage_execution_request=initial_request,
                ).continuation_payload(
                    session_id=session_id,
                    current_turn_context=dict(task_operation.get("current_turn_context") or {}),
                )
                if continuation_payload:
                    async for event in self._continue_coordination_delivery_stream(
                        session_id=session_id,
                        history=history,
                        source=source,
                        agent_runtime_chain=agent_runtime_chain,
                        model_response_executor=model_response_executor,
                        runtime_context_manager=runtime_context_manager,
                        stage_projection_cycle=stage_projection_cycle,
                        memory_intent=memory_intent,
                        assistant_message_committer=assistant_message_committer,
                        tool_runtime_executor=tool_runtime_executor,
                        tool_instances=tool_instances,
                        agent_runtime_profile=agent_runtime_profile,
                        continuation_payload=continuation_payload,
                    ):
                        yield event
                    return
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
        model_stream_policy = _model_stream_policy_from_task_execution_assembly(
            task_execution_assembly_payload,
            current_turn_context=current_turn_context,
        )
        artifact_policy_for_validation = _artifact_policy_from_task_execution_assembly(
            selected_recipe_payload=selected_recipe_payload,
            task_execution_assembly=task_execution_assembly_payload,
            current_turn_context=current_turn_context,
        )
        if current_turn_context:
            current_turn_event = self.event_log.append(
                state.task_run_id,
                "current_turn_context_resolved",
                payload={
                    "current_turn_context": current_turn_context,
                    "execution_mode": str(current_turn_context.get("execution_mode") or ""),
                    "stream_policy": model_stream_policy,
                    "bundle_id": str(current_turn_context.get("bundle_id") or ""),
                    "bundle_item_count": len(list(current_turn_context.get("bundle_items") or [])),
                    "followup_target_count": len(list(current_turn_context.get("followup_target_refs") or [])),
                },
                refs={"task_contract_ref": task_contract_ref},
            )
            yield {"type": "runtime_loop_event", "event": current_turn_event.to_dict()}
        query_understanding = dict(task_operation.get("query_understanding") or {})
        retrieval_results: list[dict[str, Any]] | None = None
        if self._should_run_recipe_mcp_phase(
            query_understanding=query_understanding,
            selected_recipe_payload=selected_recipe_payload,
            task_operation=task_operation,
            allowed_search_sources=allowed_search_sources,
        ):
            mcp_outcome = await self._run_recipe_mcp_phase(
                task_run_id=state.task_run_id,
                session_id=session_id,
                task_id=task_id,
                user_message=user_message,
                current_turn_context=current_turn_context,
                query_understanding=query_understanding,
                selected_recipe_payload=selected_recipe_payload,
                task_spec_payload=task_spec_payload,
                task_contract_ref=task_contract_ref,
                runtime_task_ledger=runtime_task_ledger,
                state=state,
                allowed_search_sources=allowed_search_sources,
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
        runtime_tool_instances = self._tool_instances_for_resource_policy(
            tool_instances,
            resource_policy,
            allowed_search_sources=allowed_search_sources,
        )
        runtime_capability_state = build_runtime_capability_state(
            task_operation,
            resource_policy=resource_policy,
            agent_runtime_profile=agent_runtime_profile,
            visible_tool_names=[
                str(getattr(tool, "name", "") or "")
                for tool in list(runtime_tool_instances)
                if str(getattr(tool, "name", "") or "")
            ],
        )
        effective_runtime_execution_facts = {
            **dict(runtime_execution_facts or {}),
            "runtime_capability_state": runtime_capability_state,
        }
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
                allowed_search_sources=allowed_search_sources,
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
            runtime_execution_facts=effective_runtime_execution_facts,
            runtime_assembly=dict(
                dict(current_turn_context or {}).get("stage_execution_request", {}).get("runtime_assembly")
                or dict(current_turn_context or {}).get("runtime_assembly")
                or {}
            ),
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
            task_template_id=str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
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
                "task_template_id": str(selected_recipe_payload.get("template_id") or selected_recipe_payload.get("recipe_id") or ""),
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
            finished = self._upsert_finished_task_run(
                start_task_run=start.task_run,
                start_agent_run=start.agent_run,
                start_coordination_run=start.coordination_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                final_content="",
                diagnostics={"runtime_loop_control_reason": control_decision.reason},
            )
            for runtime_event in finished.events:
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            return

        directive_event = self.event_log.append(
            state.task_run_id,
            "runtime_directive_issued",
            payload={
                "directive": directive.to_dict(),
                "resource_policy": resource_policy.to_dict(),
                "search_policy": list(search_policy) if search_policy is not None else None,
                "allowed_search_sources": sorted(allowed_search_sources),
                "runtime_capability_state": runtime_capability_state,
                "effective_tool_names": [
                    str(getattr(tool, "name", "") or "")
                    for tool in list(runtime_tool_instances)
                    if str(getattr(tool, "name", "") or "")
                ],
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
            "search_policy": list(search_policy) if search_policy is not None else None,
            "allowed_search_sources": sorted(allowed_search_sources),
            "runtime_capability_state": runtime_capability_state,
            "effective_tool_names": [
                str(getattr(tool, "name", "") or "")
                for tool in list(runtime_tool_instances)
                if str(getattr(tool, "name", "") or "")
            ],
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
            finished = self._upsert_finished_task_run(
                start_task_run=start.task_run,
                start_agent_run=start.agent_run,
                start_coordination_run=start.coordination_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                final_content="",
                diagnostics={"operation_gate_reason": gate_result.reason},
            )
            for runtime_event in finished.events:
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            return

        final_content = ""
        final_answer_metadata: dict[str, Any] = {}
        terminal_reason = "completed"
        if final_main_context and self._final_main_context_can_finalize(
            selected_recipe_payload=selected_recipe_payload,
            retrieval_results=retrieval_results,
        ):
            final_content = self._select_final_answer_from_context(final_main_context)
            if not final_content:
                final_content = str(
                    final_main_context.get("resolved_answer")
                    or final_main_context.get("canonical_answer")
                    or ""
                )
            if not final_content and final_task_summary_refs:
                final_content = self._select_final_answer_from_task_summary_refs(final_task_summary_refs)
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
                model_stream_policy=model_stream_policy,
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
                    user_message=user_message,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
                    current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
                    runtime_context_manager=runtime_context_manager,
                    model_response_executor=model_response_executor,
                    tool_runtime_executor=tool_runtime_executor,
                    event=event,
                    allowed_search_sources=allowed_search_sources,
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
                            observation_aggregator.add_tool_observation(
                                observation_payload,
                                observation_ref=observation_ref,
                            )
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
                            if _recipe_allows_tool_observation_finalization(selected_recipe_payload):
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
        retrieval_followup_force_synthesis = False
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
            readiness_message = _build_answer_readiness_judge_message(
                user_message=user_message,
                aggregation=observation_aggregator.snapshot(),
                current_bundle_items=current_bundle_items,
                remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
            )
            if readiness_message:
                followup_messages.append(SystemMessage(content=readiness_message))
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
                    synthesized = _forced_tool_synthesis_from_available_evidence(
                        user_message=user_message,
                        aggregation=observation_aggregator.snapshot(),
                        final_task_summary_refs=final_task_summary_refs,
                        final_main_context=final_main_context,
                    )
                    if synthesized:
                        final_content = synthesized
                        final_answer_metadata = _forced_synthesis_answer_metadata(
                            source="runtime_loop.budget_exhausted_force_synthesis"
                        )
                    else:
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
                model_stream_policy=model_stream_policy,
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
                    user_message=user_message,
                    task_id=task_id,
                    task_operation=task_operation,
                    adopted_resource_policy=resource_policy,
                    current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
                    runtime_context_manager=runtime_context_manager,
                    model_response_executor=model_response_executor,
                    tool_runtime_executor=tool_runtime_executor,
                    event=event,
                    allowed_search_sources=allowed_search_sources,
                )
                for runtime_event in runtime_events:
                    if runtime_event.event_type == "executor_observation_received":
                        observation_ref = str(runtime_event.refs.get("observation_ref") or runtime_event.event_id)
                        result_refs.append(observation_ref)
                        observation = dict(runtime_event.payload.get("observation") or {})
                        if observation.get("observation_type") == "tool_result":
                            tool_observation_count += 1
                            observation_payload = dict(observation.get("payload") or {})
                            observation_aggregator.add_tool_observation(
                                observation_payload,
                                observation_ref=observation_ref,
                            )
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
                            observation_payload = dict(observation.get("payload") or {})
                            current_step = current_task_step_run(runtime_task_ledger)
                            if (
                                runtime_task_ledger is not None
                                and current_step is not None
                                and current_step.status == "running"
                                and current_step.executor_type in {"tool", "mcp", "agent"}
                            ):
                                error_text = str(observation_payload.get("error") or "executor_failed")
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
                                    diagnostics={
                                        "last_step_transition": "executor_error_observation",
                                        "last_error": {
                                            "message": error_text,
                                            "code": str(observation_payload.get("code") or ""),
                                            "provider": str(observation_payload.get("provider") or ""),
                                            "model": str(observation_payload.get("model") or ""),
                                            "detail": str(observation_payload.get("detail") or ""),
                                            "source": str(observation.get("source") or ""),
                                            "observation_ref": observation_ref,
                                            "step_id": current_step.step_id,
                                        },
                                    },
                                )
                                checkpoint_event = self._write_checkpoint_event(state, event_offset=ledger_event.offset)
                                yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                    elif runtime_event.event_type == "loop_error":
                        terminal_reason = "executor_failed"
                        runtime_error = str(runtime_event.payload.get("error") or "executor_failed")
                        runtime_observation = dict(runtime_event.payload.get("observation") or {})
                        runtime_observation_payload = dict(runtime_observation.get("payload") or {})
                        current_step = current_task_step_run(runtime_task_ledger)
                        if (
                            runtime_task_ledger is not None
                            and current_step is not None
                            and current_step.status == "running"
                        ):
                            runtime_task_ledger = fail_task_run_step(
                                runtime_task_ledger,
                                step_id=current_step.step_id,
                                completed_at=time.time(),
                                failure_reason=runtime_error,
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
                                diagnostics={
                                    "last_step_transition": "loop_error",
                                    "last_error": {
                                        "message": runtime_error,
                                        "code": str(runtime_observation_payload.get("code") or ""),
                                        "provider": str(runtime_observation_payload.get("provider") or ""),
                                        "model": str(runtime_observation_payload.get("model") or ""),
                                        "detail": str(runtime_observation_payload.get("detail") or ""),
                                        "source": str(runtime_event.payload.get("answer_source") or runtime_observation.get("source") or ""),
                                        "observation_ref": str(runtime_event.refs.get("observation_ref") or ""),
                                        "step_id": current_step.step_id,
                                    },
                                },
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
            if (
                next_pending_tool_calls
                and next_tool_messages
                and terminal_reason == "completed"
                and tool_observation_count > 0
                and _is_retrieval_task_mode(str(task_spec_payload.get("task_mode") or ""))
            ):
                retrieval_followup_force_synthesis = True
            if next_pending_tool_calls and next_tool_messages and terminal_reason == "completed":
                if _should_force_answer_after_tool_results(
                    aggregation=observation_aggregator.snapshot(),
                    final_task_summary_refs=final_task_summary_refs,
                    final_main_context=final_main_context,
                ):
                    synthesized = _forced_tool_synthesis_from_available_evidence(
                        user_message=user_message,
                        aggregation=observation_aggregator.snapshot(),
                        final_task_summary_refs=final_task_summary_refs,
                        final_main_context=final_main_context,
                    )
                    if synthesized:
                        final_content = synthesized
                        final_answer_metadata = _forced_synthesis_answer_metadata(source="runtime_loop.post_tool_judgement_force_synthesis")
                        followup_messages = []
                        break
                if retrieval_followup_force_synthesis:
                    synthesized = _forced_tool_synthesis_from_available_evidence(
                        user_message=user_message,
                        aggregation=observation_aggregator.snapshot(),
                        final_task_summary_refs=final_task_summary_refs,
                        final_main_context=final_main_context,
                    )
                    if synthesized:
                        final_content = synthesized
                        final_answer_metadata = _forced_synthesis_answer_metadata(source="runtime_loop.retrieval_followup_force_synthesis")
                        followup_messages = []
                        break
                if repeated_tool_halt and final_content:
                    followup_messages = []
                    break
                if repeated_tool_halt:
                    synthesized = _forced_tool_synthesis_from_available_evidence(
                        user_message=user_message,
                        aggregation=observation_aggregator.snapshot(),
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
                readiness_message = _build_answer_readiness_judge_message(
                    user_message=user_message,
                    aggregation=observation_aggregator.snapshot(),
                    current_bundle_items=current_bundle_items,
                    remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
                )
                if readiness_message:
                    followup_messages.append(SystemMessage(content=readiness_message))
                continue
            followup_messages = []

        artifact_validation = _validate_required_artifact_file(
            root_dir=self.root_dir,
            selected_recipe_payload=selected_recipe_payload,
            artifact_policy=artifact_policy_for_validation,
            final_content=final_content,
            result_refs=tuple(result_refs),
            event_log_events=[item.to_dict() for item in self.event_log.list_events(state.task_run_id)],
        )
        if (
            not artifact_validation["passed"]
            and terminal_reason == "completed"
            and _requires_write_file_artifact(selected_recipe_payload)
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
                    selected_recipe_payload=selected_recipe_payload,
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
                    model_stream_policy=model_stream_policy,
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
                        user_message=user_message,
                        task_id=task_id,
                        task_operation=task_operation,
                        adopted_resource_policy=resource_policy,
                        current_step_id=runtime_task_ledger.current_step_id if runtime_task_ledger is not None else state.current_step_id,
                        runtime_context_manager=runtime_context_manager,
                        model_response_executor=model_response_executor,
                        tool_runtime_executor=tool_runtime_executor,
                        event=event,
                        allowed_search_sources=allowed_search_sources,
                    )
                    for runtime_event in runtime_events:
                        if runtime_event.event_type == "executor_observation_received":
                            observation_ref = str(runtime_event.refs.get("observation_ref") or runtime_event.event_id)
                            result_refs.append(observation_ref)
                            observation = dict(runtime_event.payload.get("observation") or {})
                            if observation.get("observation_type") == "tool_result":
                                tool_observation_count += 1
                                observation_payload = dict(observation.get("payload") or {})
                                observation_aggregator.add_tool_observation(
                                    observation_payload,
                                    observation_ref=observation_ref,
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
                    selected_recipe_payload=selected_recipe_payload,
                    artifact_policy=artifact_policy_for_validation,
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
            and _requires_write_file_artifact(selected_recipe_payload)
        ):
            terminal_reason = "completed"
            final_content = _build_artifact_success_fallback_answer(
                selected_recipe_payload=selected_recipe_payload,
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
        context_answer_source = str(final_main_context.get("answer_source") or "").strip()
        if context_answer_source and str(final_answer_metadata.get("answer_source") or "").strip() in {
            "",
            "runtime_directive:model_response",
            "runtime_mcp",
        }:
            final_answer_metadata = {
                **dict(final_answer_metadata),
                "answer_source": context_answer_source,
            }
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
        working_memory_finalization = self.finalize_working_memory(
            task_run_id=terminal_state.task_run_id,
            actor_id=terminal_state.agent_id or "runloop",
            terminal_reason=terminal_state.terminal_reason or terminal_reason,
        )
        working_memory_finalization_result = dict(working_memory_finalization.get("result") or {})
        result_refs.append(f"working_memory_finalization:{working_memory_finalization_result.get('archive_report_path') or terminal_state.task_run_id}")
        yield {"type": "runtime_loop_event", "event": dict(working_memory_finalization.get("event") or {})}
        yield {"type": "working_memory_finalized", "result": working_memory_finalization_result}
        done_event = {
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
            "working_memory_finalization": working_memory_finalization_result,
            "task_run_ledger": final_task_run_ledger.to_dict() if final_task_run_ledger is not None else {},
            "task_result": task_result.to_dict() if task_result is not None else {},
            "output_commit": {
                "state": "committed" if assistant_commit_applied else "not_applied",
                "assistant_commit_applied": assistant_commit_applied,
                "assistant_commit": assistant_commit.to_dict(),
                "task_result_commit": final_commit.to_dict(),
                "working_memory_finalization": working_memory_finalization_result,
                "memory": dict(memory_commit_state),
                "file_work_context_writeback": bool(final_main_context or final_task_summary_refs),
            },
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
                "working_memory_finalization": working_memory_finalization_result,
                **memory_commit_state,
                "artifact_write_allowed": False,
            },
            diagnostics={
                **dict(terminal_state.diagnostics),
                "result_ref_count": len(result_refs),
                "working_memory_finalized": True,
                "working_memory_finalization": working_memory_finalization_result,
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
        continuation_payload: dict[str, Any] = {}
        try:
            finished = self._upsert_finished_task_run(
                start_task_run=start.task_run,
                start_agent_run=start.agent_run,
                start_coordination_run=start.coordination_run,
                task_contract_ref=task_contract_ref,
                terminal_state=terminal_state,
                checkpoint_event=checkpoint_event,
                final_content=final_content,
                task_result=task_result.to_dict() if task_result is not None else {},
                task_spec_payload=task_spec_payload,
                current_turn_context=current_turn_context,
                user_message=user_message,
                diagnostics={"final_content_chars": len(final_content)},
            )
            for runtime_event in finished.events:
                yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
            continuation_payload = dict(finished.continuation_payload or {})
        except Exception as exc:
            state_index_diagnostics = {
                "degraded": True,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "phase": "finished_task_run_state_write",
            }
            done_event["output_commit"] = {
                **dict(done_event.get("output_commit") or {}),
                "state_index_degraded": True,
                "state_index_error": state_index_diagnostics,
            }
            done_event["runtime_state_index"] = state_index_diagnostics
            try:
                degraded_event = self.event_log.append(
                    terminal_state.task_run_id,
                    "runtime_state_index_degraded",
                    payload=state_index_diagnostics,
                    refs={"checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or "")},
                )
                yield {"type": "runtime_loop_event", "event": degraded_event.to_dict()}
            except Exception:
                pass
        yield done_event
        if continuation_payload:
            async for event in self._continue_coordination_delivery_stream(
                session_id=session_id,
                history=history,
                source=source,
                agent_runtime_chain=agent_runtime_chain,
                model_response_executor=model_response_executor,
                runtime_context_manager=runtime_context_manager,
                stage_projection_cycle=stage_projection_cycle,
                memory_intent=memory_intent,
                assistant_message_committer=assistant_message_committer,
                tool_runtime_executor=tool_runtime_executor,
                tool_instances=tool_instances,
                agent_runtime_profile=agent_runtime_profile,
                continuation_payload=continuation_payload,
            ):
                yield event
            return

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
        task_result: dict[str, Any] | None = None,
        task_spec_payload: dict[str, Any] | None = None,
        current_turn_context: dict[str, Any] | None = None,
        user_message: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> FinishedTaskRunResult:
        events: list[Any] = []
        continuation_payload: dict[str, Any] = {}
        existing_task_run = self.state_index.get_task_run(start_task_run.task_run_id)
        base_task_run = existing_task_run or start_task_run
        explicit_inputs = dict(dict(current_turn_context or {}).get("explicit_inputs") or {})
        task_ref_for_artifacts = str(
            dict(current_turn_context or {}).get("selected_task_id")
            or dict(current_turn_context or {}).get("task_id")
            or task_contract_ref
            or base_task_run.task_id
            or ""
        ).strip()
        task_policy_for_artifacts: dict[str, Any] = {}
        task_record_for_artifacts = (
            self.task_flow_registry.get_specific_task_record(task_ref_for_artifacts)
            if task_ref_for_artifacts
            else None
        )
        if task_record_for_artifacts is None:
            task_record_for_artifacts = _specific_task_record_for_runtime_ref(
                self.task_flow_registry,
                task_ref_for_artifacts or task_contract_ref or base_task_run.task_id,
            )
        if task_record_for_artifacts is not None:
            task_ref_for_artifacts = str(getattr(task_record_for_artifacts, "task_id", "") or task_ref_for_artifacts)
            task_policy_for_artifacts = dict(task_record_for_artifacts.task_policy or {})
        stage_execution_request = dict(dict(current_turn_context or {}).get("stage_execution_request") or {})
        stage_artifact_policy = dict(stage_execution_request.get("artifact_policy") or {})
        if stage_artifact_policy:
            task_policy_for_artifacts = {
                **task_policy_for_artifacts,
                "artifact_policy": {
                    **dict(task_policy_for_artifacts.get("artifact_policy") or {}),
                    **stage_artifact_policy,
                },
            }
        stage_contract_for_acceptance: dict[str, Any] = {}
        stage_acceptance_preview: dict[str, Any] = {}
        requires_file_artifact_refs_preview = bool(
            dict(stage_execution_request.get("artifact_policy") or {}).get("enabled")
            or stage_execution_request.get("artifact_targets")
        )
        if stage_execution_request and start_coordination_run is not None:
            coordination_state_for_acceptance = self.langgraph_coordination_runtime.checkpoints.get_state(
                thread_id=start_coordination_run.coordination_run_id,
            ) or {}
            stage_contract_for_acceptance = dict(
                dict(coordination_state_for_acceptance.get("stage_contracts") or {}).get(
                    str(stage_execution_request.get("stage_id") or "")
                )
                or {}
            )
            stage_acceptance_preview = _stage_business_acceptance(
                stage_id=str(stage_execution_request.get("stage_id") or ""),
                contract=stage_contract_for_acceptance,
                explicit_inputs=explicit_inputs,
                final_content=final_content,
                output_refs=["artifact:pending"] if requires_file_artifact_refs_preview and str(terminal_state.status or "") == "completed" else [],
                terminal_status=terminal_state.status,
                requires_file_artifact_refs=requires_file_artifact_refs_preview,
            )
        acceptance_status = (
            "accepted"
            if bool(stage_acceptance_preview.get("accepted") is True)
            else "rejected"
            if stage_execution_request and requires_file_artifact_refs_preview
            else ""
        )
        try:
            artifact_materialization = materialize_task_artifacts(
                workspace_root=_workspace_root_from_runtime_root(self.root_dir),
                task_run_id=start_task_run.task_run_id,
                session_id=start_task_run.session_id,
                task_ref=task_ref_for_artifacts,
                coordination_run_id=start_coordination_run.coordination_run_id if start_coordination_run is not None else "",
                final_content=final_content,
                user_message=user_message,
                explicit_inputs=explicit_inputs,
                task_policy=task_policy_for_artifacts,
                task_status=terminal_state.status,
                terminal_reason=terminal_state.terminal_reason,
                task_diagnostics=dict(terminal_state.diagnostics or {}),
                acceptance_status=acceptance_status,
                stage_id=str(stage_execution_request.get("stage_id") or ""),
                request_id=str(stage_execution_request.get("request_id") or ""),
            )
        except Exception as exc:
            artifact_materialization = MaterializedTaskArtifacts(
                enabled=True,
                diagnostics={
                    "status": "failed",
                    "reason": str(exc),
                    "source": "task_policy.artifact_policy",
                },
            )
        artifact_materialization_payload = artifact_materialization.to_dict()
        artifact_repository_record: dict[str, Any] = {}
        if artifact_materialization.enabled and artifact_materialization.artifact_refs:
            artifact_policy = dict(dict(task_policy_for_artifacts.get("artifact_policy") or {}))
            artifact_repository_record = self.artifact_repository.record_materialization(
                task_run_id=start_task_run.task_run_id,
                graph_id=str(dict(start_task_run.diagnostics or {}).get("graph_ref") or ""),
                stage_id=str(stage_execution_request.get("stage_id") or ""),
                node_run_id=str(stage_execution_request.get("node_run_id") or stage_execution_request.get("request_id") or ""),
                task_ref=task_ref_for_artifacts,
                coordination_run_id=start_coordination_run.coordination_run_id if start_coordination_run is not None else "",
                artifact_refs=list(artifact_materialization.artifact_refs),
                artifact_root=artifact_materialization.artifact_root,
                created_files=list(artifact_materialization.created_files),
                status=acceptance_status or "accepted",
                repository_id=str(artifact_policy.get("repository_id") or artifact_policy.get("artifact_repository_id") or "artifact.repository.default"),
                collection_id=str(artifact_policy.get("collection_id") or artifact_policy.get("collection") or "default"),
                lifecycle_policy=dict(artifact_policy.get("lifecycle_policy") or {}),
                metadata={"source": "task_artifact_materializer"},
            )
            artifact_materialization_payload = {
                **artifact_materialization_payload,
                "artifact_repository": artifact_repository_record,
            }
        if artifact_materialization.enabled and artifact_materialization.artifact_refs:
            task_result_payload = dict(task_result or {})
            task_result_payload["output_refs"] = _dedupe_refs(
                [
                    *list(task_result_payload.get("output_refs") or []),
                    *list(artifact_materialization.artifact_refs),
                ]
            )
            task_result_payload["diagnostics"] = {
                **dict(task_result_payload.get("diagnostics") or {}),
                "artifact_materialization": artifact_materialization_payload,
            }
            final_outputs = dict(task_result_payload.get("final_outputs") or {})
            final_outputs["artifact_materialization"] = artifact_materialization_payload
            task_result_payload["final_outputs"] = final_outputs
            task_result = task_result_payload
        elif artifact_materialization.enabled:
            task_result = {
                **dict(task_result or {}),
                "diagnostics": {
                    **dict(dict(task_result or {}).get("diagnostics") or {}),
                    "artifact_materialization": artifact_materialization_payload,
                },
            }
        artifact_event = self.event_log.append(
            start_task_run.task_run_id,
            "task_artifacts_materialized" if artifact_materialization.enabled else "task_artifact_materialization_checked",
            payload={
                "artifact_materialization": artifact_materialization_payload,
                "artifact_repository": artifact_repository_record,
                "resolved_task_ref": task_ref_for_artifacts,
                "artifact_policy_enabled": bool(dict(task_policy_for_artifacts.get("artifact_policy") or {}).get("enabled")),
                "task_policy_keys": sorted(str(key) for key in task_policy_for_artifacts.keys()),
            },
            refs={
                "task_ref": task_ref_for_artifacts,
                "artifact_root": artifact_materialization.artifact_root,
            },
        )
        events.append(artifact_event)
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
                    **(
                        {"artifact_materialization": artifact_materialization_payload}
                        if artifact_materialization.enabled
                        else {}
                    ),
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
        continuation_coordination_run_id = str(
            dict(current_turn_context or {}).get("coordination_run_id")
            or dict(task_spec_payload or {}).get("inputs", {}).get("coordination_run_id")
            or ""
        ).strip()
        continuation_coordination_run = (
            self.state_index.get_coordination_run(continuation_coordination_run_id)
            if continuation_coordination_run_id
            else None
        )
        current_coordination_runs = self.state_index.list_task_coordination_runs(start_task_run.task_run_id)
        target_coordination_run = (
            continuation_coordination_run
            or (current_coordination_runs[0] if current_coordination_runs else start_coordination_run)
        )
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
            graph_record = self._resolve_task_graph_view(target_coordination_run.graph_ref)
            coordination_mode = str(
                (graph_record.coordination_mode if graph_record is not None else "")
                or dict(target_coordination_run.diagnostics.get("coordination_flow") or {}).get("coordination_mode")
                or ""
            ).strip()
            if self.langgraph_coordination_runtime.supports(target_coordination_run):
                raw_flow_state = dict(target_coordination_run.diagnostics.get("coordination_flow") or {})
                current_stage_request = dict(dict(current_turn_context or {}).get("stage_execution_request") or {})
                request_stage_id = str(current_stage_request.get("stage_id") or "").strip()
                flow_stage_id = str(raw_flow_state.get("current_stage_id") or "").strip()
                resolved_stage_id = self._stage_id_for_task_ref(
                    coordination_task=graph_record,
                    task_ref=task_contract_ref or start_task_run.task_id,
                )
                current_stage_id = request_stage_id or resolved_stage_id or flow_stage_id
                if (
                    request_stage_id
                    and flow_stage_id
                    and request_stage_id != flow_stage_id
                ):
                    terminal_state.diagnostics["coordination_flow_stage_repaired"] = {
                        "request_stage_id": request_stage_id,
                        "stale_flow_stage_id": flow_stage_id,
                        "resolved_stage_id": resolved_stage_id,
                        "authority": "orchestration.task_run_loop",
                    }
                all_output_refs = self._collect_task_result_output_refs(dict(task_result or {}))
                requires_file_artifact_refs = bool(
                    dict(current_stage_request.get("artifact_policy") or {}).get("enabled")
                    or current_stage_request.get("artifact_targets")
                )
                output_refs = [
                    ref
                    for ref in all_output_refs
                    if str(ref or "").startswith("artifact:")
                ] if requires_file_artifact_refs else all_output_refs
                materialization_payload = dict(dict(task_result or {}).get("diagnostics", {}).get("artifact_materialization") or {})
                if str(dict(materialization_payload.get("diagnostics") or {}).get("acceptance_status") or "") == "rejected":
                    output_refs = []
                task_result_ref = str(dict(task_result or {}).get("result_id") or agent_run_result.agent_run_result_id)
                coordination_state_before_resume = self.langgraph_coordination_runtime.checkpoints.get_state(
                    thread_id=target_coordination_run.coordination_run_id,
                ) or {}
                stage_contract = dict(
                    dict(coordination_state_before_resume.get("stage_contracts") or {}).get(current_stage_id) or {}
                )
                stage_acceptance = _stage_business_acceptance(
                    stage_id=current_stage_id,
                    contract=stage_contract,
                    explicit_inputs=dict(current_stage_request.get("explicit_inputs") or {}),
                    final_content=final_content,
                    output_refs=output_refs,
                    terminal_status=terminal_state.status,
                    requires_file_artifact_refs=requires_file_artifact_refs,
                )
                ready_event = NodeResultReadyEvent(
                    event_type="task_result_ready",
                    coordination_run_id=target_coordination_run.coordination_run_id,
                    task_run_id=start_task_run.task_run_id,
                    stage_id=current_stage_id,
                    task_ref=task_contract_ref or start_task_run.task_id,
                    task_result_ref=task_result_ref,
                    artifact_refs=tuple(output_refs),
                    accepted=bool(stage_acceptance.get("accepted") is True),
                    agent_run_result_ref=agent_run_result.agent_run_result_id,
                    request_id=str(current_stage_request.get("request_id") or ""),
                    dispatch_event_id=str(dict(current_stage_request.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
                    diagnostics={
                        "terminal_reason": terminal_state.terminal_reason,
                        "last_error": dict(terminal_state.diagnostics.get("last_error") or {}),
                        "content_metric_total": _count_text_units(final_content),
                        "stage_business_acceptance": stage_acceptance,
                    },
                )
                artifact_root = self._artifact_root_from_context_or_events(
                    current_task_run_id=start_task_run.task_run_id,
                    current_turn_context=dict(current_turn_context or {}),
                )
                runtime_result = self.langgraph_coordination_runtime.resume_from_task_result(
                    coordination_run=target_coordination_run,
                    event=ready_event,
                    current_task_result=dict(task_result or {}),
                    inherited_inputs=dict(dict(current_turn_context or {}).get("explicit_inputs") or {}),
                    artifact_root=artifact_root,
                )
                events.extend(runtime_result.events)
                if runtime_result.stage_execution_request is not None:
                    continuation_payload = runtime_result.continuation_payload(
                        session_id=start_task_run.session_id,
                        current_turn_context=dict(current_turn_context or {}),
                    )
                worker_spawn_summary = {
                    **worker_spawn_summary,
                    "coordination_runtime": "langgraph_runtime",
                    "stage_execution_request": bool(runtime_result.stage_execution_request is not None),
                }
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
                refreshed_task_run = self.state_index.get_task_run(start_task_run.task_run_id) or start_task_run
                refreshed_coordination_run = (
                    self.state_index.get_coordination_run(target_coordination_run.coordination_run_id)
                    or target_coordination_run
                )
                self._update_project_supervision_state(
                    task_run=refreshed_task_run,
                    coordination_run=refreshed_coordination_run,
                    current_turn_context=dict(current_turn_context or {}),
                    stage_id=current_stage_id,
                    task_result=dict(task_result or {}),
                    accepted=bool(ready_event.accepted),
                    terminal_status=str(terminal_state.status or ""),
                    terminal_reason=str(terminal_state.terminal_reason or ""),
                    metric_value=int(dict(ready_event.diagnostics or {}).get("content_metric_total") or 0),
                    coordination_state_before_resume=dict(runtime_result.state or coordination_state_before_resume or {}),
                    artifact_root=artifact_root,
                )
                return FinishedTaskRunResult(events=tuple(events), continuation_payload=continuation_payload)
            raise RuntimeError(
                f"Legacy coordination continuation path was removed for unsupported coordination run: {target_coordination_run.coordination_run_id}"
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
        return FinishedTaskRunResult(
            events=tuple(events),
            continuation_payload=continuation_payload,
        )

    def _sync_task_graph_root_terminal_objects(
        self,
        *,
        root_task_run_id: str,
        coordination_run_id: str,
        status: str,
        terminal_reason: str,
        merge_result_ref: str = "",
    ) -> None:
        root_task_run = self.state_index.get_task_run(root_task_run_id)
        if root_task_run is not None and root_task_run.status not in {"completed", "failed", "aborted"}:
            self.state_index.upsert_task_run(
                TaskRun(
                    task_run_id=root_task_run.task_run_id,
                    session_id=root_task_run.session_id,
                    task_id=root_task_run.task_id,
                    task_contract_ref=root_task_run.task_contract_ref,
                    owner_agent_seat_id=root_task_run.owner_agent_seat_id,
                    agent_id=root_task_run.agent_id,
                    agent_profile_id=root_task_run.agent_profile_id,
                    runtime_lane=root_task_run.runtime_lane,
                    status="completed" if status == "completed" else "failed",
                    created_at=root_task_run.created_at,
                    updated_at=time.time(),
                    latest_event_offset=root_task_run.latest_event_offset,
                    latest_checkpoint_ref=root_task_run.latest_checkpoint_ref,
                    terminal_reason=terminal_reason,
                    diagnostics={
                        **dict(root_task_run.diagnostics),
                        "task_graph_terminal_sync": {
                            "coordination_run_id": coordination_run_id,
                            "coordination_status": status,
                            "merge_result_ref": merge_result_ref,
                        },
                    },
                )
            )
        for agent_run in self.state_index.list_task_agent_runs(root_task_run_id):
            if agent_run.coordination_run_ref != coordination_run_id:
                continue
            if agent_run.status in {"completed", "failed", "killed"}:
                continue
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
                    status="completed" if status == "completed" else "failed",
                    latest_checkpoint_ref=agent_run.latest_checkpoint_ref,
                    result_ref=agent_run.result_ref or merge_result_ref,
                    created_at=agent_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(agent_run.diagnostics),
                        "terminal_reason": terminal_reason,
                        "task_graph_terminal_sync": {
                            "coordination_run_id": coordination_run_id,
                            "coordination_status": status,
                        },
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
            working_memory_refs=tuple(
                str(item).strip()
                for item in list(state.diagnostics.get("working_memory_refs") or [])
                if str(item).strip()
            ),
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
        graph_payload: dict[str, Any],
        communication_protocol_payload: dict[str, Any],
        task_graph_payload: dict[str, Any] | None = None,
        task_agent_adoption_plan_payload: dict[str, Any] | None = None,
        effective_limits: RuntimeLoopLimits | None = None,
        task_spec_payload: dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        events: list[Any] = []
        adoption_plan_payload = dict(task_agent_adoption_plan_payload or {})
        task_graph_payload = dict(task_graph_payload or graph_payload or {})
        graph_payload = _normalize_runtime_graph_payload(
            raw_graph_payload=graph_payload,
            task_graph_payload=task_graph_payload,
            runtime_spec_payload={},
        )
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
            role="coordinator" if graph_payload else start_result.agent_run.role,
            spawn_mode=adoption_mode,
            context_scope=start_result.agent_run.context_scope,
            runtime_lane=start_result.agent_run.runtime_lane,
            parent_agent_run_ref=start_result.agent_run.parent_agent_run_ref,
            coordination_run_ref=(
                start_result.agent_run.coordination_run_ref
                or (coordination_run_id if graph_payload else "")
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
        if graph_payload:
            topology_template_payload = self._resolve_topology_template(
                str(graph_payload.get("topology_template_id") or "")
            )
            coordination_flow = build_coordination_flow_state(
                coordination_task_payload=graph_payload,
                topology_template=topology_template_payload,
                communication_protocol_payload=communication_protocol_payload,
            )
            coordination_run = CoordinationRun(
                coordination_run_id=coordination_run_id,
                task_run_id=start_result.task_run.task_run_id,
                graph_ref=str(
                    task_graph_payload.get("graph_id")
                    or graph_payload.get("graph_id")
                    or graph_payload.get("task_graph_id")
                    or ""
                ),
                coordinator_agent_id=str(graph_payload.get("coordinator_agent_id") or updated_agent_run.agent_id),
                topology_template_id=str(graph_payload.get("topology_template_id") or ""),
                communication_protocol_id=str(communication_protocol_payload.get("protocol_id") or ""),
                handoff_policy=str(graph_payload.get("handoff_policy") or ""),
                failure_policy=str(graph_payload.get("conflict_resolution_policy") or ""),
                merge_policy=str(graph_payload.get("output_merge_policy") or ""),
                status="running",
                latest_checkpoint_ref="",
                created_at=time.time(),
                updated_at=time.time(),
                diagnostics={
                    "shared_context_policy": str(graph_payload.get("shared_context_policy") or ""),
                    "memory_sharing_policy": str(graph_payload.get("memory_sharing_policy") or ""),
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
            dispatch_plan = _compile_agent_dispatch_plan_from_graph_payload(
                task_run_id=start_result.task_run.task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                graph_payload=graph_payload,
                topology_template_payload=topology_template_payload,
            )
            coordination_run = CoordinationRun(
                coordination_run_id=coordination_run.coordination_run_id,
                task_run_id=coordination_run.task_run_id,
                graph_ref=coordination_run.graph_ref,
                coordinator_agent_id=coordination_run.coordinator_agent_id,
                topology_template_id=coordination_run.topology_template_id,
                communication_protocol_id=coordination_run.communication_protocol_id,
                handoff_policy=coordination_run.handoff_policy,
                failure_policy=coordination_run.failure_policy,
                merge_policy=coordination_run.merge_policy,
                status=coordination_run.status,
                latest_checkpoint_ref=coordination_run.latest_checkpoint_ref,
                created_at=coordination_run.created_at,
                updated_at=time.time(),
                diagnostics={
                    **dict(coordination_run.diagnostics),
                    "agent_dispatch_plan": dispatch_plan.to_dict(),
                },
            )
            self.state_index.upsert_coordination_run(coordination_run)
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
                        "agent_dispatch_plan": dispatch_plan.to_dict(),
                    },
                )
            )
            events.append(
                self.event_log.append(
                    start_result.task_run.task_run_id,
                    "agent_dispatch_plan_compiled",
                    payload={"agent_dispatch_plan": dispatch_plan.to_dict(), "source": "coordination_task_contract"},
                    refs={
                        "coordination_run_ref": coordination_run.coordination_run_id,
                        "dispatch_plan_ref": dispatch_plan.dispatch_plan_id,
                    },
                )
            )
            notification_events = [
                self.event_log.append(
                    start_result.task_run.task_run_id,
                    "agent_notification_queued",
                    payload={"queued_agent_notification": notification.to_dict(), "source": "dispatch_plan"},
                    refs={
                        "coordination_run_ref": coordination_run.coordination_run_id,
                        "notification_ref": notification.notification_id,
                    },
                )
                for notification in dispatch_plan.queued_notifications
            ]
            events.extend(notification_events)
            envelope_events = self._sync_graph_handoff_runtime_objects(
                task_run_id=start_result.task_run.task_run_id,
                coordination_run=coordination_run,
                parent_agent_run=updated_agent_run,
                graph_payload=graph_payload,
                topology_template_payload=topology_template_payload,
            )
            events.extend(envelope_events)
            current_coordination_run = coordination_run
            if self.langgraph_coordination_runtime.supports(coordination_run):
                runtime_result = self.langgraph_coordination_runtime.initialize(
                    coordination_run=coordination_run,
                    event_task_run_id=start_result.task_run.task_run_id,
                    inherited_inputs=dict(dict(task_spec_payload or {}).get("inputs") or {}),
                )
                events.extend(runtime_result.events)
                refreshed = self.state_index.get_coordination_run(coordination_run.coordination_run_id)
                if refreshed is not None:
                    current_coordination_run = refreshed
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

        if (
            current_coordination_run is not None
            and not self.langgraph_coordination_runtime.supports(current_coordination_run)
            and not bool(dict(current_coordination_run.diagnostics or {}).get("worker_spawn_runtime"))
        ):
            raise RuntimeError(
                f"Legacy coordination runtime sync path was removed: {current_coordination_run.coordination_run_id}"
            )
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
                graph_ref=f"graph.auto:{task_run_id}",
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
                    "worker_spawn_runtime": True,
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

    def _sync_graph_handoff_runtime_objects(
        self,
        *,
        task_run_id: str,
        coordination_run: CoordinationRun,
        parent_agent_run: AgentRun,
        graph_payload: dict[str, Any],
        topology_template_payload: dict[str, Any],
    ) -> list[Any]:
        events: list[Any] = []
        edges = _dispatch_edges_from_payload(graph_payload, topology_template_payload)
        if not edges:
            return events
        task_agent_runs = list(self.state_index.list_task_agent_runs(task_run_id))
        existing_handoffs = {
            str(item.handoff_id or "")
            for item in self.state_index.list_coordination_handoffs(coordination_run.coordination_run_id)
            if str(item.handoff_id or "")
        }
        for edge in edges:
            source_node_id = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
            target_node_id = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
            if not source_node_id or not target_node_id:
                continue
            edge_id = str(edge.get("edge_id") or f"{source_node_id}->{target_node_id}").strip()
            source_agent_run_ref = self._resolve_graph_node_agent_run_ref(
                task_agent_runs=task_agent_runs,
                node_id=source_node_id,
                fallback_agent_run=parent_agent_run,
            )
            target_agent_run_ref = self._resolve_graph_node_agent_run_ref(
                task_agent_runs=task_agent_runs,
                node_id=target_node_id,
                fallback_agent_run=parent_agent_run,
            )
            handoff_id = f"handoffenv:{_runtime_loop_short_hash({'coordination_run_id': coordination_run.coordination_run_id, 'edge_id': edge_id, 'source_agent_run_ref': source_agent_run_ref, 'target_agent_run_ref': target_agent_run_ref})}"
            if handoff_id in existing_handoffs:
                continue
            envelope = AgentHandoffEnvelope(
                handoff_id=handoff_id,
                task_run_id=task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                source_agent_run_ref=source_agent_run_ref,
                target_agent_run_ref=target_agent_run_ref,
                protocol_id=str(coordination_run.communication_protocol_id or ""),
                message_type=str(edge.get("message_type") or edge.get("policy") or edge.get("edge_type") or "structured_handoff"),
                payload_ref=edge_id,
                ack_state="pending" if bool(edge.get("ack_required", True) is not False) else "not_required",
                created_at=time.time(),
                diagnostics={
                    "coordination_engine": "langgraph",
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                    "edge_id": edge_id,
                    "handoff_policy": str(edge.get("policy") or edge.get("edge_type") or ""),
                    "payload_ref_kind": "graph_edge",
                    "formalized_from": "coordination_dispatch_graph",
                },
            )
            self.state_index.upsert_handoff_envelope(envelope)
            events.append(
                self.event_log.append(
                    task_run_id,
                    "handoff_envelope_created",
                    payload={"handoff_envelope": envelope.to_dict()},
                    refs={
                        "coordination_run_ref": coordination_run.coordination_run_id,
                        "handoff_ref": envelope.handoff_id,
                        "source_agent_run_ref": source_agent_run_ref,
                        "target_agent_run_ref": target_agent_run_ref,
                    },
                )
            )
            existing_handoffs.add(handoff_id)
        return events

    def _resolve_graph_node_agent_run_ref(
        self,
        *,
        task_agent_runs: list[AgentRun],
        node_id: str,
        fallback_agent_run: AgentRun,
    ) -> str:
        normalized = str(node_id or "").strip()
        if normalized in {"", "final_merge", "coordinator"}:
            return str(fallback_agent_run.agent_run_id or "")
        worker_runs = [
            item
            for item in task_agent_runs
            if str(item.agent_run_id or "") != str(fallback_agent_run.agent_run_id or "")
        ]
        if worker_runs:
            return str(worker_runs[0].agent_run_id or "")
        return str(fallback_agent_run.agent_run_id or "")

    def _resolve_topology_template(self, template_id: str) -> dict[str, Any]:
        target = str(template_id or "").strip()
        if not target:
            return {}
        match = next((item for item in self.task_flow_registry.list_topology_templates() if item.template_id == target), None)
        return match.to_dict() if match is not None else {}

    @staticmethod
    def _stage_id_for_task_ref(*, coordination_task: Any | None, task_ref: str) -> str:
        target = str(task_ref or "").strip()
        metadata = dict(getattr(coordination_task, "metadata", {}) or {}) if coordination_task is not None else {}
        for stage in list(metadata.get("stage_sequence") or []):
            if not isinstance(stage, dict):
                continue
            if str(stage.get("task_ref") or "").strip() == target:
                return str(stage.get("stage_id") or "").strip()
        contracts = list(metadata.get("stage_contracts") or [])
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            if str(contract.get("task_ref") or "").strip() == target:
                return str(contract.get("stage_id") or "").strip()
        return ""

    def _artifact_root_from_context_or_events(
        self,
        *,
        current_task_run_id: str,
        current_turn_context: dict[str, Any],
    ) -> str:
        artifact_root = str(
            current_turn_context.get("artifact_root")
            or current_turn_context.get("workspace_root")
            or dict(current_turn_context.get("explicit_inputs") or {}).get("artifact_root")
            or dict(current_turn_context.get("explicit_inputs") or {}).get("workspace_root")
            or ""
        ).strip()
        if not artifact_root:
            write_paths = _successful_write_file_paths(
                root_dir=self.root_dir,
                event_log_events=[item.to_dict() for item in self.event_log.list_events(current_task_run_id)],
            )
            if write_paths:
                artifact_root = str(Path(write_paths[0]["absolute_path"]).parent.as_posix())
        if artifact_root:
            workspace_root = _workspace_root_from_runtime_root(self.root_dir)
            artifact_root = artifact_root.replace("\\", "/").rstrip("/")
            workspace_posix = workspace_root.as_posix().rstrip("/")
            if artifact_root.startswith(workspace_posix + "/"):
                artifact_root = artifact_root[len(workspace_posix) + 1 :]
        return artifact_root

    def _project_id_for_task_run(
        self,
        *,
        task_run: TaskRun | None,
        current_turn_context: dict[str, Any] | None = None,
    ) -> str:
        turn_inputs = dict(dict(current_turn_context or {}).get("explicit_inputs") or {})
        if turn_inputs.get("project_id"):
            return str(turn_inputs.get("project_id") or "").strip()
        if task_run is not None:
            diagnostics = dict(task_run.diagnostics or {})
            if diagnostics.get("project_id"):
                return str(diagnostics.get("project_id") or "").strip()
            initial_inputs_ref = str(diagnostics.get("task_graph_initial_inputs_ref") or "").strip()
            if initial_inputs_ref:
                payload = dict(self.runtime_objects.get_object(initial_inputs_ref) or {})
                initial_inputs = dict(payload.get("initial_inputs") or {})
                if initial_inputs.get("project_id"):
                    return str(initial_inputs.get("project_id") or "").strip()
        return ""

    @staticmethod
    def _coordination_active_node_id(coordination_state: dict[str, Any] | None) -> str:
        state = dict(coordination_state or {})
        return str(state.get("active_stage_id") or state.get("active_node_id") or "").strip()

    def _update_project_supervision_state(
        self,
        *,
        task_run: TaskRun | None,
        coordination_run: CoordinationRun | None,
        current_turn_context: dict[str, Any] | None = None,
        stage_id: str = "",
        task_result: dict[str, Any] | None = None,
        accepted: bool = False,
        terminal_status: str = "",
        terminal_reason: str = "",
        metric_value: int = 0,
        coordination_state_before_resume: dict[str, Any] | None = None,
        artifact_root: str = "",
    ) -> None:
        if task_run is None:
            return
        project_id = self._project_id_for_task_run(task_run=task_run, current_turn_context=current_turn_context)
        if not project_id:
            return
        current_turn_context = dict(current_turn_context or {})
        explicit_inputs = dict(current_turn_context.get("explicit_inputs") or {})
        diagnostics = dict(task_run.diagnostics or {})
        ledger = self.state_index.get_project_progress_ledger(project_id)
        if ledger is None:
            initial_inputs_ref = str(diagnostics.get("task_graph_initial_inputs_ref") or "").strip()
            restored_inputs = {}
            if initial_inputs_ref:
                restored_inputs = dict(dict(self.runtime_objects.get_object(initial_inputs_ref) or {}).get("initial_inputs") or {})
            normalized_inputs = ensure_project_runtime_inputs(
                initial_inputs={**restored_inputs, **explicit_inputs},
                graph_id=str(diagnostics.get("task_graph_id") or diagnostics.get("graph_ref") or ""),
                session_id=task_run.session_id,
            )
            ledger = make_initial_project_ledger(
                project_id=project_id,
                session_id=task_run.session_id,
                graph_id=str(diagnostics.get("task_graph_id") or diagnostics.get("graph_ref") or ""),
                task_family=str(diagnostics.get("task_family") or ""),
                project_title=str(normalized_inputs.get("project_title") or project_id),
                metric_label=str(normalized_inputs.get("metric_label") or diagnostics.get("metric_label") or "units"),
                target_metric_total=int(
                    normalized_inputs.get("target_metric_total")
                    or normalized_inputs.get("target_words")
                    or diagnostics.get("target_metric_total")
                    or diagnostics.get("target_words")
                    or 0
                ),
                task_run_id=task_run.task_run_id,
            )
        coordination_state = dict(coordination_state_before_resume or {})
        pending_inputs = dict(coordination_state.get("pending_inputs") or {})
        stage_contract = dict(dict(coordination_state.get("stage_contracts") or {}).get(stage_id) or {})
        progress_policy = dict(stage_contract.get("progress_commit_policy") or {})
        if progress_policy.get("enabled") is True and accepted:
            unit_index_key = str(progress_policy.get("unit_index_key") or "unit_index")
            unit_start_key = str(progress_policy.get("unit_start_key") or unit_index_key)
            unit_end_key = str(progress_policy.get("unit_end_key") or unit_start_key)
            unit_count_key = str(progress_policy.get("unit_count_key") or "")
            metric_value_key = str(progress_policy.get("metric_value_key") or "content_metric_total")
            metric_target_key = str(progress_policy.get("metric_target_key") or "target_metric_total")
            unit_index = int(
                explicit_inputs.get(unit_index_key)
                or pending_inputs.get(unit_index_key)
                or 0
            )
            units_per_commit = max(
                _safe_int(
                    explicit_inputs.get(unit_count_key)
                    or pending_inputs.get(unit_count_key)
                    or 1
                ),
                1,
            )
            batch_start_index = _safe_int(
                explicit_inputs.get(unit_start_key)
                or pending_inputs.get(unit_start_key)
                or unit_index
                or 0
            )
            batch_end_index = _safe_int(
                explicit_inputs.get(unit_end_key)
                or pending_inputs.get(unit_end_key)
                or (batch_start_index + units_per_commit - 1 if batch_start_index else 0)
            )
            resolved_metric = int(
                metric_value
                or pending_inputs.get(metric_value_key)
                or dict(dict(coordination_state.get("diagnostics") or {}).get("runtime_loop") or {}).get(metric_value_key)
                or explicit_inputs.get(metric_target_key)
                or pending_inputs.get(metric_target_key)
                or 0
            )
            result_payload = dict(task_result or {})
            artifact_refs = self._collect_task_result_output_refs(result_payload)
            unit_ref = next((ref for ref in artifact_refs if str(ref).startswith("artifact:")), "")
            receipt_ref = str(result_payload.get("result_id") or f"{task_run.task_run_id}:{stage_id}:{unit_index}")
            total_units = max(batch_end_index - batch_start_index + 1, 1)
            per_unit_metric = max(int(resolved_metric / total_units), 0) if total_units > 1 else resolved_metric
            remainder_metric = max(resolved_metric - (per_unit_metric * total_units), 0)
            for offset, current_unit_index in enumerate(range(batch_start_index, batch_end_index + 1)):
                if current_unit_index <= 0:
                    continue
                current_metric = per_unit_metric + (remainder_metric if offset == total_units - 1 else 0)
                current_ref = f"{unit_ref}#unit_{current_unit_index:03d}" if unit_ref and total_units > 1 else unit_ref
                current_receipt_ref = f"{receipt_ref}:unit_{current_unit_index:03d}" if total_units > 1 else receipt_ref
                ledger = record_progress_unit_commit(
                    ledger,
                    task_run_id=task_run.task_run_id,
                    unit_index=current_unit_index,
                    unit_ref=current_ref,
                    metric_value=current_metric,
                    receipt_ref=current_receipt_ref,
                )
            self.state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=task_run.session_id,
                    task_run_id=task_run.task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
                    issue_type="progress_unit_committed",
                    issue_summary=(
                        f"Progress unit batch {batch_start_index}-{batch_end_index} committed."
                        if units_per_commit > 1
                        else f"Progress unit {unit_index} committed."
                    ),
                    repair_result="progress_updated",
                    followup_status="watching",
                    diagnostics={
                        "unit_index": unit_index,
                        "batch_start_index": batch_start_index,
                        "batch_end_index": batch_end_index,
                        "units_per_commit": units_per_commit,
                        "metric_value": resolved_metric,
                        "unit_ref": unit_ref,
                    },
                )
            )
        if stage_id == "memory_finalize" and accepted:
            ledger = record_delivery_state(
                ledger,
                task_run_id=task_run.task_run_id,
                delivery_state="completed",
            )
        elif stage_id == "final_review" and accepted:
            ledger = record_delivery_state(
                ledger,
                task_run_id=task_run.task_run_id,
                delivery_state="delivery_ready",
            )
        if terminal_status in {"failed", "aborted"}:
            failure = {
                "terminal_status": terminal_status,
                "terminal_reason": terminal_reason,
                "stage_id": stage_id,
                "task_run_id": task_run.task_run_id,
            }
            ledger = record_failure(
                ledger,
                task_run_id=task_run.task_run_id,
                failure=failure,
            )
            self.state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=task_run.session_id,
                    task_run_id=task_run.task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
                    issue_type="run_failed",
                    issue_summary=str(terminal_reason or terminal_status or "Task run failed"),
                    followup_status="needs_repair",
                    diagnostics=failure,
                )
            )
        elif accepted:
            ledger = clear_recovered_failure(
                ledger,
                task_run_id=task_run.task_run_id,
                stage_id=stage_id,
            )
        self.state_index.upsert_project_progress_ledger(ledger)
        latest_event_at = float(task_run.updated_at or time.time())
        coordination_active_status = str((coordination_run.status if coordination_run is not None else task_run.status) or "")
        coordination_terminal_reason = ""
        if coordination_run is not None:
            flow = dict(dict(coordination_run.diagnostics or {}).get("coordination_flow") or {})
            runtime_state = dict(dict(coordination_run.diagnostics or {}).get("langgraph_runtime_state") or {})
            coordination_terminal = str(flow.get("terminal_status") or runtime_state.get("terminal_status") or "").strip()
            if coordination_terminal == "completed":
                coordination_active_status = "completed"
                coordination_terminal_reason = "completed"
            elif coordination_terminal in {"failed", "blocked"}:
                coordination_active_status = "failed"
                coordination_terminal_reason = coordination_terminal
            elif coordination_terminal == "waiting_for_human":
                coordination_active_status = "waiting"
                coordination_terminal_reason = "waiting_for_human"
            elif coordination_active_status in {"failed", "aborted"} and not coordination_terminal:
                coordination_active_status = "running"
        blocker = classify_blocker(
            run_status=coordination_active_status,
            terminal_reason=str(coordination_terminal_reason or terminal_reason or task_run.terminal_reason or ""),
            active_node_id=self._coordination_active_node_id(coordination_state),
            stage_execution_request=dict(coordination_state.get("stage_execution_request") or {}),
            last_event_at=latest_event_at,
            failure=ledger.last_failure,
        )
        recovery_state = dict(ledger.last_repair_action or {})
        project_active_task_run_id = (
            str(coordination_run.task_run_id or "")
            if coordination_run is not None and str(coordination_run.task_run_id or "").strip()
            else task_run.task_run_id
        )
        project_status = build_runtime_status(
            ledger=ledger,
            task_run_id=project_active_task_run_id,
            coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
            active_run_status=coordination_active_status,
            latest_artifact_root=str(artifact_root or dict(diagnostics.get("artifact_materialization") or {}).get("artifact_root") or ""),
            latest_event_offset=int(task_run.latest_event_offset or 0),
            latest_event_at=latest_event_at,
            last_effective_output_at=float(task_run.updated_at or time.time()),
            blocker=blocker,
            recovery_state=recovery_state,
        )
        self.state_index.upsert_project_runtime_status(project_status)

    async def _continue_coordination_delivery_stream(
        self,
        *,
        session_id: str,
        history: list[dict[str, Any]],
        source: str,
        agent_runtime_chain: Any,
        model_response_executor: Any,
        runtime_context_manager: RuntimeContextManager,
        stage_projection_cycle: StageProjectionCycle | None,
        memory_intent: Any | None,
        assistant_message_committer: Callable[[dict[str, Any]], Any] | None,
        tool_runtime_executor: Any | None,
        tool_instances: list[Any] | None,
        agent_runtime_profile: Any | None,
        continuation_payload: dict[str, Any],
    ):
        next_task_ref = str(continuation_payload.get("next_task_ref") or "").strip()
        next_message = str(continuation_payload.get("message") or "").strip()
        next_turn_context = dict(continuation_payload.get("current_turn_context") or {})
        if not next_task_ref or not next_message:
            return
        stage_agent_id = str(next_turn_context.get("agent_id") or "").strip()
        stage_agent_runtime_profile = None
        if stage_agent_id:
            stage_agent_runtime_profile = self.agent_runtime_registry.get_profile(stage_agent_id)
            if stage_agent_runtime_profile is None:
                raise ValueError(f"TaskGraph node agent has no runtime profile: {stage_agent_id}")
        turn_marker = str(next_turn_context.get("turn_id") or "").strip() or f"turn:{session_id}:{uuid.uuid4().hex[:8]}"
        next_turn_context["turn_id"] = turn_marker
        next_task_id = f"taskinst:{turn_marker}:{next_task_ref.split('.')[-1]}"
        task_selection = {
            **dict(continuation_payload.get("task_selection") or {}),
            **{
                key: value
                for key, value in next_turn_context.items()
                if key in {
                    "turn_id",
                    "selected_task_id",
                    "task_id",
                    "agent_id",
                    "projection_id",
                    "selected_projection_id",
                    "runtime_limits",
                    "agent_group_id",
                    "artifact_root",
                    "workspace_root",
                    "explicit_inputs",
                    "a2a_payload",
                    "stage_execution_request",
                    "coordination_run_id",
                    "continuation_stage_id",
                }
            },
        }
        async for event in self.run_single_agent_stream(
            session_id=session_id,
            task_id=next_task_id,
            user_message=next_message,
            history=list(history or []),
            source=source,
            agent_runtime_chain=_ContinuationAgentRuntimeChain(
                base=_ContinuationAgentRuntimeChain.unwrap(agent_runtime_chain),
                forced_turn_context=next_turn_context,
            ),
            model_response_executor=model_response_executor,
            runtime_context_manager=runtime_context_manager,
            stage_projection_cycle=stage_projection_cycle,
            memory_intent=memory_intent,
            task_selection=task_selection,
            assistant_message_committer=assistant_message_committer,
            tool_runtime_executor=tool_runtime_executor,
            tool_instances=tool_instances,
            agent_runtime_profile=stage_agent_runtime_profile,
        ):
            if continuation_payload.get("suppress_done") and event.get("type") == "done":
                continue
            yield event

    def _latest_output_ref_for_task(self, *, task_ref: str) -> str:
        return self.artifact_ref_index.latest_output_ref(task_ref=task_ref)

    def _latest_output_refs_for_task(self, *, task_ref: str) -> list[str]:
        return self.artifact_ref_index.latest_output_refs(task_ref=task_ref)

    @staticmethod
    def _collect_task_result_output_refs(task_result: dict[str, Any]) -> list[str]:
        return collect_task_result_output_refs(task_result)

    @staticmethod
    def _dedupe_refs(refs: Any) -> list[str]:
        return dedupe_artifact_refs(refs)

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

    def _tool_instances_for_resource_policy(
        self,
        tool_instances: list[Any] | None,
        resource_policy: Any,
        *,
        allowed_search_sources: set[str] | None = None,
    ) -> list[Any]:
        from capability_system.tool_authorization import build_authorized_tool_set

        allowed_sources = allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
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
        filtered: list[Any] = []
        for tool in list(authorized.instances):
            tool_name = str(getattr(tool, "name", "") or "").strip()
            definition = self.tool_authorization_index.definitions_by_name.get(tool_name)
            if definition is not None and not tool_allowed_by_search_policy(definition, allowed_sources):
                continue
            filtered.append(tool)
        return filtered

    def _should_run_recipe_mcp_phase(
        self,
        *,
        query_understanding: dict[str, Any],
        selected_recipe_payload: dict[str, Any],
        task_operation: dict[str, Any],
        allowed_search_sources: set[str],
    ) -> bool:
        operation_requirement = dict(task_operation.get("operation_requirement") or {})
        resolution = dict(dict(operation_requirement.get("metadata") or {}).get("runtime_operation_resolution") or {})
        if str(resolution.get("execution_mode") or "").strip() == "delegate":
            return False
        source_kind = str(
            selected_recipe_payload.get("source_kind")
            or dict(selected_recipe_payload.get("metadata") or {}).get("source_kind")
            or query_understanding.get("source_kind")
            or ""
        ).strip()
        if get_local_mcp_unit_for_source_kind(source_kind) is not None:
            unit = get_local_mcp_unit_for_source_kind(source_kind)
            return operation_allowed_by_search_policy(
                str(getattr(unit, "operation_id", "") or ""),
                allowed_search_sources,
            )
        resolution = capability_resolution_view(query_understanding)
        return (
            resolution.preferred_skill == "rag-skill"
            and source_kind == "knowledge_base"
            and operation_allowed_by_search_policy("op.mcp_retrieval", allowed_search_sources)
        )

    def _rebuild_context_policy_with_retrieval(
        self,
        *,
        agent_runtime_chain: Any,
        session_id: str,
        user_message: str,
        memory_intent: Any | None,
        task_operation: dict[str, Any],
        retrieval_results: list[dict[str, Any]] | None,
        allowed_search_sources: set[str],
    ) -> dict[str, Any]:
        memory_request_profile = dict(task_operation.get("task_memory_request_profile") or {})
        retrieval_allowed = _task_operation_allows_context_retrieval(
            task_operation=task_operation,
            allowed_search_sources=allowed_search_sources,
        )
        context_policy_result = agent_runtime_chain.build_context_policy_result(
            session_id=session_id,
            message=user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            retrieval_results=retrieval_results if retrieval_allowed else None,
            retrieval_allowed=retrieval_allowed,
        )
        if context_policy_result is None:
            return {}
        if hasattr(context_policy_result, "to_dict"):
            return dict(context_policy_result.to_dict())
        return dict(context_policy_result)

    async def _run_recipe_mcp_phase(
        self,
        *,
        task_run_id: str,
        session_id: str,
        task_id: str,
        user_message: str,
        current_turn_context: dict[str, Any],
        query_understanding: dict[str, Any],
        selected_recipe_payload: dict[str, Any],
        task_spec_payload: dict[str, Any],
        task_contract_ref: str,
        runtime_task_ledger: TaskRunLedger | None,
        state: RuntimeLoopState,
        allowed_search_sources: set[str],
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

        mcp_route, operation_id, bindings, constraints, answer_source = self._recipe_mcp_request_parts(
            user_message=user_message,
            current_turn_context=current_turn_context,
            query_understanding=query_understanding,
            selected_recipe_payload=selected_recipe_payload,
            task_spec_payload=task_spec_payload,
        )
        if not operation_allowed_by_search_policy(operation_id, allowed_search_sources):
            blocked_event = self.event_log.append(
                task_run_id,
                "recipe_mcp_blocked_by_search_policy",
                payload={
                    "mcp_route": mcp_route,
                    "operation_id": operation_id,
                    "allowed_sources": sorted(allowed_search_sources),
                },
                refs={"task_contract_ref": task_contract_ref, "operation_id": operation_id},
            )
            events.append({"type": "runtime_loop_event", "event": blocked_event.to_dict()})
            return {
                "events": events,
                "ledger": runtime_task_ledger,
                "state": state,
                "result_refs": result_refs,
                "main_context": main_context,
                "task_summary_refs": task_summary_refs,
                "retrieval_results": retrieval_results,
            }
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

    def _recipe_mcp_request_parts(
        self,
        *,
        user_message: str,
        current_turn_context: dict[str, Any],
        query_understanding: dict[str, Any],
        selected_recipe_payload: dict[str, Any],
        task_spec_payload: dict[str, Any] | None = None,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
        source_kind = str(
            selected_recipe_payload.get("source_kind")
            or dict(selected_recipe_payload.get("metadata") or {}).get("source_kind")
            or query_understanding.get("source_kind")
            or ""
        ).strip()
        unit = get_local_mcp_unit_for_source_kind(source_kind)
        parameters = dict(query_understanding.get("tool_input") or query_understanding.get("parameters") or {})
        bindings: dict[str, Any] = {}
        constraints: dict[str, Any] = {}
        followup_contract = _followup_contract_from_task_spec(task_spec_payload)
        if unit is not None:
            path_key = str(unit.request_path_parameter or "").strip()
            binding_key = str(unit.followup_binding_key or "").strip()
            if path_key and binding_key and binding_key != "current_turn_context":
                path = str(
                    parameters.get(path_key)
                    or _followup_contract_source_path(followup_contract, binding_key=binding_key)
                    or ""
                ).strip()
                bindings = {binding_key: path} if path else {}
                constraints = {path_key: path} if path else {}
            if unit.request_mode_parameter:
                mode_key = str(unit.request_mode_parameter).strip()
                mode = str(parameters.get(mode_key) or unit.request_default_mode or "").strip()
                if mode:
                    constraints[mode_key] = mode
            if binding_key == "current_turn_context":
                bindings = {"current_turn_context": dict(current_turn_context or {})}
            constraints = _merge_followup_contract_into_payload(constraints, followup_contract=followup_contract)
            return unit.route, unit.operation_id, bindings, constraints, unit.answer_source
        bindings = {"current_turn_context": dict(current_turn_context or {})}
        retrieval_unit = get_local_mcp_unit("retrieval")
        if retrieval_unit is not None:
            return retrieval_unit.route, retrieval_unit.operation_id, bindings, {}, retrieval_unit.answer_source
        return "retrieval", "op.mcp_retrieval", bindings, {}, "runtime_rag_mcp"

    def _final_main_context_can_finalize(
        self,
        *,
        selected_recipe_payload: dict[str, Any],
        retrieval_results: list[dict[str, Any]] | None,
    ) -> bool:
        source_kind = str(
            selected_recipe_payload.get("source_kind")
            or dict(selected_recipe_payload.get("metadata") or {}).get("source_kind")
            or ""
        ).strip()
        unit = get_local_mcp_unit_for_source_kind(source_kind)
        if unit is not None and unit.route != "retrieval":
            return True
        return bool(retrieval_results)

    def _build_tool_authorization_index(self):
        from capability_system.tool_authorization import build_tool_authorization_index
        from capability_system.tool_definitions import get_tool_definitions

        return build_tool_authorization_index(get_tool_definitions())

    def _delegation_executor(self) -> AgentDelegationExecutor:
        executor = getattr(self, "_agent_delegation_executor", None)
        if executor is None:
            executor = AgentDelegationExecutor(
                self.backend_dir,
                state_index=self.state_index,
                event_log=self.event_log,
                evidence_orchestrator=self.evidence_orchestrator,
            )
            self._agent_delegation_executor = executor
        return executor

    def _build_delegation_request(
        self,
        *,
        task_run_id: str,
        action_request: Any,
        parent_agent_run_ref: str,
        source_agent_id: str,
        user_message: str,
        task_operation: dict[str, Any] | None = None,
        allowed_search_sources: set[str] | None = None,
    ) -> AgentDelegationRequest:
        tool_call = dict(action_request.payload.get("tool_call") or {})
        tool_args = dict(tool_call.get("args") or {})
        task_run = self.state_index.get_task_run(task_run_id)
        instruction = str(tool_args.get("instruction") or "").strip()
        input_payload = dict(tool_args.get("input_payload") or {})
        input_payload = _merge_followup_contract_into_payload(
            input_payload,
            followup_contract=_followup_contract_from_task_spec(dict(task_operation or {}).get("task_spec")),
        )
        recipe_metadata = dict(dict(dict(task_operation or {}).get("selected_recipe") or {}).get("metadata") or {})
        delegation_kind = str(tool_args.get("delegation_kind") or recipe_metadata.get("delegation_kind") or "").strip()
        target_agent_id = str(tool_args.get("target_agent_id") or recipe_metadata.get("delegate_target_agent_id") or "").strip()
        diagnostics = {
            "tool_call_id": str(tool_call.get("id") or ""),
            "operation_id": str(action_request.operation_id or ""),
            "allowed_search_sources": sorted(
                allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
            ),
            "goal_alignment": _classify_delegation_goal_alignment(
                user_message=user_message,
                instruction=instruction,
                input_payload=input_payload,
            ),
            "current_user_message": str(user_message or "").strip(),
        }
        return AgentDelegationRequest(
            request_id=f"delegation:req:{task_run_id}:{uuid.uuid4().hex[:8]}",
            task_run_id=task_run_id,
            session_id=str(task_run.session_id if task_run is not None else ""),
            parent_agent_run_ref=parent_agent_run_ref,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            delegation_kind=delegation_kind,
            instruction=instruction,
            input_payload=input_payload,
            context_policy=dict(tool_args.get("context_policy") or {}),
            expected_output_contract=dict(tool_args.get("expected_output_contract") or {}),
            timeout_policy=dict(tool_args.get("timeout_policy") or {}),
            created_at=time.time(),
            diagnostics=diagnostics,
        )

    async def _events_from_executor_event(
        self,
        task_run_id: str,
        *,
        user_message: str,
        task_id: str,
        task_operation: dict[str, Any],
        adopted_resource_policy: Any,
        current_step_id: str,
        runtime_context_manager: RuntimeContextManager,
        model_response_executor: Any,
        tool_runtime_executor: Any | None,
        event: dict[str, Any],
        allowed_search_sources: set[str] | None = None,
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
        if event_type == "content_delta":
            delta_text = str(event.get("content") or "")
            preview_limit = 400
            delta_preview = delta_text if len(delta_text) <= preview_limit else delta_text[:preview_limit]
            return [
                self.event_log.append(
                    task_run_id,
                    "model_item_received",
                    payload={
                        "stream_ref": str(event.get("stream_ref") or ""),
                        "delta_index": int(event.get("delta_index") or 0),
                        "delta_chars": int(event.get("delta_chars") or len(delta_text)),
                        "accumulated_chars": int(event.get("accumulated_chars") or len(delta_text)),
                        "delta_preview": delta_preview,
                        "is_final_chunk": bool(event.get("is_final_chunk") is True),
                    },
                    refs={
                        "directive_ref": str(event.get("stream_ref") or ""),
                    },
                )
            ]
        if event_type == "stream_recovery":
            return [
                self.event_log.append(
                    task_run_id,
                    "model_stream_recovery",
                    payload={
                        "status": str(event.get("status") or ""),
                        "reason": str(event.get("reason") or ""),
                        "code": str(event.get("code") or ""),
                        "provider": str(event.get("provider") or ""),
                        "model": str(event.get("model") or ""),
                        "detail": str(event.get("detail") or ""),
                        "partial_delta_count": int(event.get("partial_delta_count") or 0),
                    },
                    refs={
                        "directive_ref": str(event.get("directive_ref") or ""),
                    },
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
            allowed_sources = allowed_search_sources if allowed_search_sources is not None else normalize_search_policy(None)
            if not operation_allowed_by_search_policy(operation_id, allowed_sources):
                tool_call = dict(action_request.payload.get("tool_call") or {})
                tool_name = str(action_request.payload.get("tool_name") or "")
                blocked_observation = build_tool_result_observation(
                    task_run_id=task_run_id,
                    request_ref=action_request.request_id,
                    directive_ref=action_request.directive_ref,
                    tool_name=tool_name,
                    tool_call_id=str(tool_call.get("id") or action_request.request_id),
                    tool_args=dict(tool_call.get("args") or {}),
                    result="工具调用被本轮权限开关阻止：当前来源未授权。",
                )
                context_record = runtime_context_manager.record_observation(blocked_observation)
                return [
                    requested_event,
                    self.event_log.append(
                        task_run_id,
                        "tool_call_blocked_by_search_policy",
                        payload={
                            "operation_id": operation_id,
                            "tool_name": tool_name,
                            "allowed_sources": sorted(allowed_sources),
                            "observation": blocked_observation.to_dict(),
                            "context_record": context_record.to_dict(),
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "operation_id": operation_id,
                            "observation_ref": blocked_observation.observation_id,
                        },
                    ),
                    self.event_log.append(
                        task_run_id,
                        "executor_observation_received",
                        payload={
                            "observation": blocked_observation.to_dict(),
                            "context_record": context_record.to_dict(),
                            "source": blocked_observation.source,
                            "content_chars": blocked_observation.content_chars,
                        },
                        refs={
                            "action_request_ref": action_request.request_id,
                            "observation_ref": blocked_observation.observation_id,
                        },
                    ),
                ]
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
                if tool_name == "delegate_to_agent":
                    parent_agent_runs = self.state_index.list_task_agent_runs(task_run_id)
                    parent_agent_run = next((item for item in parent_agent_runs if item.agent_run_id.endswith(":main")), None)
                    if parent_agent_run is None and parent_agent_runs:
                        parent_agent_run = parent_agent_runs[0]
                    if parent_agent_run is None:
                        error_observation = build_tool_result_observation(
                            task_run_id=task_run_id,
                            request_ref=action_request.request_id,
                            directive_ref=tool_directive.directive_id,
                            tool_name="delegate_to_agent",
                            tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
                            tool_args=dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
                            result="委派失败：未找到父 AgentRun。",
                        )
                        context_record = runtime_context_manager.record_observation(error_observation)
                        events.append(
                            self.event_log.append(
                                task_run_id,
                                "executor_observation_received",
                                payload={
                                    "observation": error_observation.to_dict(),
                                    "context_record": context_record.to_dict(),
                                    "source": error_observation.source,
                                    "content_chars": error_observation.content_chars,
                                },
                                refs={
                                    "action_request_ref": action_request.request_id,
                                    "directive_ref": tool_directive.directive_id,
                                    "observation_ref": error_observation.observation_id,
                                },
                            )
                        )
                        return events
                    delegation_request = self._build_delegation_request(
                        task_run_id=task_run_id,
                        action_request=action_request,
                        parent_agent_run_ref=parent_agent_run.agent_run_id,
                        source_agent_id=parent_agent_run.agent_id,
                        user_message=user_message,
                        task_operation=task_operation,
                        allowed_search_sources=allowed_search_sources,
                    )
                    delegated = await self._delegation_executor().execute(
                        request=delegation_request,
                        parent_agent_run=parent_agent_run,
                        model_response_executor=model_response_executor,
                    )
                    events.extend(list(delegated.get("events") or []))
                    result_observation = build_tool_result_observation(
                        task_run_id=task_run_id,
                        request_ref=action_request.request_id,
                        directive_ref=tool_directive.directive_id,
                        tool_name="delegate_to_agent",
                        tool_call_id=str(dict(action_request.payload.get("tool_call") or {}).get("id") or action_request.request_id),
                        tool_args={
                            **dict(dict(action_request.payload.get("tool_call") or {}).get("args") or {}),
                            "current_user_message": str(user_message or "").strip(),
                        },
                        result=json.dumps(dict(delegated.get("observation") or {}), ensure_ascii=False),
                    )
                    context_record = runtime_context_manager.record_observation(result_observation)
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "tool_result_received",
                            payload={
                                "observation": result_observation.to_dict(),
                                "context_record": context_record.to_dict(),
                            },
                            refs={
                                "action_request_ref": action_request.request_id,
                                "directive_ref": tool_directive.directive_id,
                                "observation_ref": result_observation.observation_id,
                                "delegation_request_ref": delegation_request.request_id,
                            },
                        )
                    )
                    events.append(
                        self.event_log.append(
                            task_run_id,
                            "executor_observation_received",
                            payload={
                                "observation": result_observation.to_dict(),
                                "context_record": context_record.to_dict(),
                                "source": result_observation.source,
                                "content_chars": result_observation.content_chars,
                            },
                            refs={
                                "action_request_ref": action_request.request_id,
                                "directive_ref": tool_directive.directive_id,
                                "observation_ref": result_observation.observation_id,
                                "delegation_request_ref": delegation_request.request_id,
                            },
                        )
                    )
                    return events
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
    selected_recipe_payload: dict[str, Any],
) -> TaskRunLedger | None:
    task_spec = _task_spec_from_payload(task_spec_payload)
    selected_recipe = _recipe_from_payload(selected_recipe_payload)
    if task_spec is None or selected_recipe is None:
        return None
    return build_task_run_ledger(
        task_run_id=task_run_id,
        task_contract_ref=task_contract_ref,
        task_spec=task_spec,
        selected_recipe=selected_recipe,
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


def _recipe_allows_tool_observation_finalization(selected_recipe_payload: dict[str, Any]) -> bool:
    selected_recipe = _recipe_from_payload(selected_recipe_payload)
    if selected_recipe is None:
        return True
    return not _recipe_requires_model_finalize(selected_recipe)


def _recipe_requires_model_finalize(selected_recipe: ExecutionRecipe) -> bool:
    finalization_policy = dict(getattr(selected_recipe, "finalization_policy", {}) or {})
    if "requires_model_finalize" in finalization_policy:
        return bool(finalization_policy.get("requires_model_finalize"))
    return any(
        str(step.executor_type or "") == "model" and str(step.step_kind or "") == "finalize"
        for step in selected_recipe.step_blueprints
    )


def _is_retrieval_task_mode(task_mode: str) -> bool:
    normalized = str(task_mode or "").strip().lower()
    return "retrieval" in normalized or "knowledge" in normalized


def _task_spec_from_payload(payload: dict[str, Any]) -> TaskSpec | None:
    if not payload:
        return None
    try:
        return TaskSpec(
            task_id=str(payload.get("task_id") or ""),
            task_spec_ref=str(payload.get("task_spec_ref") or ""),
            recipe_id=str(payload.get("recipe_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_goal=str(payload.get("user_goal") or ""),
            inputs=dict(payload.get("inputs") or {}),
            bindings=dict(payload.get("bindings") or {}),
            constraints=dict(payload.get("constraints") or {}),
            current_turn_context_ref=str(payload.get("current_turn_context_ref") or ""),
            task_intent_ref=str(payload.get("task_intent_ref") or ""),
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


def _recipe_from_payload(payload: dict[str, Any]) -> ExecutionRecipe | None:
    if not payload:
        return None
    try:
        return ExecutionRecipe(
            recipe_id=str(payload.get("recipe_id") or ""),
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            execution_kind=str(payload.get("execution_kind") or ""),
            task_family=str(payload.get("task_family") or ""),
            task_mode=str(payload.get("task_mode") or ""),
            source_kind=str(payload.get("source_kind") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            output_schema=dict(payload.get("output_schema") or {}),
            default_agent_id=str(payload.get("default_agent_id") or "agent:0"),
            allowed_agent_ids=tuple(str(item) for item in list(payload.get("allowed_agent_ids") or ["agent:0"])),
            required_capability_tags=tuple(str(item) for item in list(payload.get("required_capability_tags") or [])),
            required_operations=tuple(str(item) for item in list(payload.get("required_operations") or [])),
            optional_operations=tuple(str(item) for item in list(payload.get("optional_operations") or [])),
            step_blueprints=tuple(_task_step_blueprint_from_payload(item) for item in list(payload.get("step_blueprints") or [])),
            validation_rules=tuple(_task_validation_rule_from_payload(item) for item in list(payload.get("validation_rules") or [])),
            safety_policy=dict(payload.get("safety_policy") or {}),
            artifact_policy=dict(payload.get("artifact_policy") or {}),
            finalization_policy=dict(payload.get("finalization_policy") or {}),
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
    selected_recipe_payload: dict[str, Any],
    artifact_policy: dict[str, Any] | None = None,
    final_content: str,
    result_refs: tuple[str, ...],
    event_log_events: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_policy_payload = dict(artifact_policy or {})
    rules = [
        dict(item)
        for item in list(selected_recipe_payload.get("validation_rules") or [])
        if str(dict(item).get("validation_kind") or "") == "artifact_file_required"
        and str(dict(item).get("severity") or "") == "error"
    ]
    if not rules:
        if _artifact_policy_requires_materialized_content(artifact_policy_payload):
            target_paths = _artifact_policy_target_paths(artifact_policy_payload)
            has_content = bool(str(final_content or "").strip())
            return {
                "passed": has_content,
                "required": True,
                "reason": (
                    "required artifact policy has final content for materialization"
                    if has_content
                    else "artifact_policy requires a final_content artifact but the model returned empty content"
                ),
                "source": "task_graph_artifact_policy",
                "artifact_targets": target_paths,
                "final_content_chars": len(str(final_content or "")),
                "result_ref_count": len(result_refs),
            }
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


def _requires_write_file_artifact(selected_recipe_payload: dict[str, Any]) -> bool:
    if "op.write_file" not in set(str(item) for item in list(selected_recipe_payload.get("required_operations") or [])):
        return False
    return any(
        str(dict(item).get("validation_kind") or "") == "artifact_file_required"
        and str(dict(item).get("severity") or "") == "error"
        for item in list(selected_recipe_payload.get("validation_rules") or [])
        if isinstance(item, dict)
    )


def _artifact_policy_requires_materialized_content(policy: dict[str, Any]) -> bool:
    artifact_policy = dict(policy or {})
    if not artifact_policy:
        return False
    if artifact_policy.get("enabled") is False:
        return False
    specs = [dict(item) for item in list(artifact_policy.get("artifacts") or []) if isinstance(item, dict)]
    if specs:
        return any(dict(item).get("required", True) is not False for item in specs)
    if artifact_policy.get("required") is False:
        return False
    return bool(str(artifact_policy.get("artifact_target") or artifact_policy.get("output_path") or "").strip())


def _artifact_policy_target_paths(policy: dict[str, Any]) -> list[str]:
    artifact_policy = dict(policy or {})
    targets: list[str] = []
    for item in list(artifact_policy.get("artifacts") or []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path and path not in targets:
            targets.append(path)
    for key in ("artifact_target", "output_path"):
        path = str(artifact_policy.get(key) or "").strip()
        if path and path not in targets:
            targets.append(path)
    return targets


def _build_required_artifact_write_messages(
    *,
    model_messages: list[Any],
    user_message: str,
    task_spec_payload: dict[str, Any],
    final_content: str,
    selected_recipe_payload: dict[str, Any],
) -> list[Any]:
    target_path = _required_artifact_target_path(task_spec_payload=task_spec_payload, user_message=user_message)
    task_title = str(selected_recipe_payload.get("title") or selected_recipe_payload.get("task_mode") or "artifact task")
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
    selected_recipe = dict(task_spec_payload.get("selected_recipe") or {})
    template_metadata = dict(selected_recipe.get("metadata") or {})
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
    default_artifact_name = str(template_metadata.get("default_artifact_name") or "").strip()
    if default_artifact_name:
        artifact_root = str(
            inputs.get("artifact_root")
            or inputs.get("workspace_root")
            or template_metadata.get("default_write_root")
            or template_metadata.get("default_write_roots", [""])[0]
            or "docs/系统规划/任务系统实测记录/artifacts"
        ).strip()
        if artifact_root:
            artifact_root = artifact_root.rstrip("/\\")
            task_mode = str(selected_recipe.get("task_mode") or "").strip()
            if task_mode:
                return f"{artifact_root}/{task_mode}/{default_artifact_name}"
            return f"{artifact_root}/{default_artifact_name}"
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


def _build_answer_readiness_judge_message(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
    current_bundle_items: list[dict[str, Any]],
    remaining_model_calls: int,
) -> str:
    evidence_items = list(aggregation.evidence_items or [])
    if not evidence_items:
        return ""
    lines = [
        "你已经收到工具返回的证据。现在先判断证据是否足够回答用户，而不是默认继续调用工具。",
        "",
        "你的任务：",
        "1. 如果证据已经足够覆盖用户当前问题，请直接收口回答。",
        "2. 如果证据只缺少少量关键信息，才继续调用工具；继续前必须明确缺口是什么。",
        "3. 如果用户问题本身不清楚，请向用户说明缺少的限定条件。",
        "4. 不要为了确认已经足够的信息而重复查询同类工具。",
        "",
        f"用户当前问题：{str(user_message or '').strip()}",
        f"剩余模型调用预算：{max(int(remaining_model_calls or 0), 0)}",
    ]
    if current_bundle_items:
        lines.append("")
        lines.append("当前是复合任务；只有未完成的子项才需要继续补证。")
    lines.append("")
    lines.append("已有证据：")
    for index, item in enumerate(evidence_items[-6:], start=1):
        tool_name = str(item.get("tool_name") or "tool").strip()
        result_preview = str(item.get("result_preview") or "").strip()
        result_chars = int(item.get("result_chars") or len(result_preview))
        truncated = "，已截断" if item.get("truncated") else ""
        args = dict(item.get("tool_args") or {})
        request_text = str(args.get("query") or args.get("path") or "").strip()
        request_part = f"；请求：{request_text}" if request_text else ""
        lines.append(f"{index}. 工具：{tool_name}{request_part}；结果长度：{result_chars}{truncated}")
        if result_preview:
            lines.append(f"   证据摘要：{result_preview}")
    lines.extend(
        [
            "",
            "请基于上述证据决定下一步。",
            "如果可以回答，请直接给用户可读结论，不要输出 JSON，不要解释内部判断过程。",
            "如果仍要调用工具，请只调用能补齐明确缺口的工具。",
        ]
    )
    return "\n".join(lines).strip()


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
    selected_recipe_payload: dict[str, Any],
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
        selected_recipe_payload.get("title")
        or selected_recipe_payload.get("task_mode")
        or selected_recipe_payload.get("template_id")
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


def _explicit_project_brief(explicit_inputs: dict[str, Any]) -> str:
    parts: list[str] = []
    title = str(explicit_inputs.get("project_title") or explicit_inputs.get("title") or "").strip()
    if title:
        parts.append(f"项目名称：{title}")
    constraints = str(
        explicit_inputs.get("user_hard_constraints")
        or explicit_inputs.get("hard_constraints")
        or explicit_inputs.get("user_seed")
        or explicit_inputs.get("project_brief")
        or ""
    ).strip()
    if constraints:
        parts.append(constraints)
    execution_policy = str(explicit_inputs.get("execution_policy") or "").strip()
    if execution_policy:
        parts.append(f"执行边界：{execution_policy}")
    return "\n".join(parts).strip()


def _forced_tool_synthesis_from_available_evidence(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> str:
    synthesized = _forced_tool_synthesis_answer(
        user_message=user_message,
        final_task_summary_refs=final_task_summary_refs,
        final_main_context=final_main_context,
    )
    if synthesized:
        return synthesized
    return _forced_tool_synthesis_from_observation_aggregation(
        user_message=user_message,
        aggregation=aggregation,
    )


def _forced_tool_synthesis_from_observation_aggregation(
    *,
    user_message: str,
    aggregation: ObservationAggregation,
) -> str:
    boundary = AssistantOutputBoundary()
    eligible = 0
    for item in list(aggregation.evidence_items or [])[-8:]:
        tool_name = str(item.get("tool_name") or "").strip()
        preview = str(item.get("result_preview") or "").strip()
        if not tool_name or not preview:
            continue
        if tool_name in {"search_text", "web_search", "fetch_url"} and len(preview) < 80:
            continue
        boundary.ingest_tool_result(tool_name, preview)
        eligible += 1
    if eligible <= 0:
        return ""
    boundary.finalize_segment()
    response = boundary.build_response(
        route="runtime_force_synthesis",
        execution_posture="tool_synthesis",
        user_message=user_message,
        tool_name="aggregated_tool_results",
        retrieval_results=None,
    )
    content = str(response.canonical_answer or "").strip()
    if not content or response.fallback_reason:
        return ""
    if response.selected_channel not in {"tool_visible_summary", "answer_candidate"}:
        return ""
    if _looks_like_runtime_internal_answer(content):
        return ""
    return content


def _should_force_answer_after_tool_results(
    *,
    aggregation: ObservationAggregation,
    final_task_summary_refs: list[dict[str, Any]],
    final_main_context: dict[str, Any],
) -> bool:
    tool_names = [str(item).strip() for item in list(aggregation.tool_names or []) if str(item).strip()]
    if final_task_summary_refs:
        return True
    active_constraints = dict(final_main_context.get("active_constraints") or {})
    if active_constraints.get("active_pdf") or active_constraints.get("active_dataset"):
        return True
    if "delegate_to_agent" in tool_names:
        return True
    return False


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
        summary = _clean_text(item.get("answer") or item.get("summary"))
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


def _select_final_answer_from_task_summary_refs(final_task_summary_refs: list[dict[str, Any]]) -> str:
    for item in final_task_summary_refs:
        answer = _clean_text(item.get("answer"))
        if answer:
            return answer
    for item in final_task_summary_refs:
        summary = _clean_text(item.get("summary"))
        if summary:
            return summary
    return ""


def _select_final_answer_from_context(final_main_context: dict[str, Any]) -> str:
    for key in ("answer", "resolved_answer", "canonical_answer"):
        value = _clean_text(final_main_context.get(key))
        if value:
            return value
    return ""


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
    if tool_name == "delegate_to_agent":
        return _project_delegated_file_work_context(tool_args=tool_args, result_text=result_text)
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
    context_writeback_hints = dict(tool_args.get("context_writeback_hints") or {})
    path = _clean_text(tool_args.get("path"))
    query = _clean_text(tool_args.get("query"))
    if not path:
        path = _clean_text(context_writeback_hints.get("source_path")) or _extract_tool_output_field(result_text, ("数据集", "文件", "path", "source"))
    if not path or _looks_like_failed_tool_result(result_text):
        return {}, []
    object_handle_id = _clean_text(context_writeback_hints.get("active_object_handle_id")) or _stable_file_work_id("source:dataset", path)
    result_handle_id = _clean_text(context_writeback_hints.get("active_result_handle_id")) or _stable_file_work_id("result:structured_answer", f"{path}:{query}:{result_text[:160]}")
    subset_labels = [
        str(item or "").strip()
        for item in list(context_writeback_hints.get("subset_labels") or [])
        if str(item or "").strip()
    ] or _extract_ranked_labels(result_text)
    subset_filter_column = _clean_text(context_writeback_hints.get("subset_filter_column"))
    subset_handle_id = (
        _clean_text(context_writeback_hints.get("active_subset_handle_id"))
        or _stable_file_work_id("subset:structured_selection", f"{path}:{'|'.join(subset_labels)}")
        if subset_labels
        else ""
    )
    active_constraints: dict[str, Any] = {
        "active_dataset": path,
        "source_kind": "dataset",
    }
    if subset_labels:
        active_constraints["subset_labels"] = subset_labels
    if subset_filter_column:
        active_constraints["subset_filter_column"] = subset_filter_column
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


def _project_delegated_file_work_context(
    *,
    tool_args: dict[str, Any],
    result_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    result_payload = _parse_json_object(result_text)
    if not result_payload or str(result_payload.get("status") or "") not in {"completed", "failed"}:
        return {}, []
    input_payload = dict(tool_args.get("input_payload") or {})
    context_writeback_hints = dict(result_payload.get("context_writeback_hints") or {})
    kind = _clean_text(tool_args.get("delegation_kind"))
    path = _clean_text(
        input_payload.get("file_path")
        or input_payload.get("path")
        or input_payload.get("active_dataset")
        or input_payload.get("active_pdf")
    )
    goal_alignment = _classify_delegation_goal_alignment(
        user_message=_clean_text(tool_args.get("current_user_message")),
        instruction=_clean_text(tool_args.get("instruction")),
        input_payload=input_payload,
    )
    if goal_alignment == "offtopic":
        return {}, []
    if not path:
        path = _clean_text(
            context_writeback_hints.get("source_path")
            or result_payload.get("source")
            or result_payload.get("path")
        )
    summary = _clean_text(result_payload.get("summary") or result_payload.get("answer_candidate") or result_text)
    if not path and kind in {"retrieval", "evidence_lookup", "knowledge_retrieval"}:
        task_id = _stable_file_work_id(
            "result:delegated_retrieval",
            f"{tool_args.get('instruction')}:{summary[:160]}",
        )
        main_context = {
            "active_goal": _clean_text(tool_args.get("instruction")),
            "active_work_item": "delegated_retrieval",
            "followup_mode": "summary_ref",
            "followup_resolution_source": "tool_observation_projection",
            "followup_target_task_id": task_id,
            "followup_target_task_ids": [task_id],
        }
        task_summary = {
            "task_id": task_id,
            "query": _clean_text(tool_args.get("instruction")),
            "summary": _compact_summary(summary),
            "task_kind": "delegated_retrieval",
            "key_points": [
                "source=delegated_retrieval",
                f"target_agent={_clean_text(result_payload.get('target_agent_id')) or 'delegated_agent'}",
            ],
        }
        return main_context, [task_summary]
    if not path:
        return {}, []
    delegated_tool_args = {
        "path": path,
        "query": _clean_text(input_payload.get("query") or tool_args.get("instruction")),
        **({"context_writeback_hints": context_writeback_hints} if context_writeback_hints else {}),
    }
    if kind in {"structured_data", "table_analysis", "structured_data_lookup"}:
        return _project_structured_data_tool_context(tool_args=delegated_tool_args, result_text=summary)
    if kind in {"pdf", "pdf_reading", "document_reading"}:
        mode = _clean_text(input_payload.get("mode") or input_payload.get("extract_mode"))
        if mode:
            delegated_tool_args["mode"] = mode
        return _project_pdf_tool_context(tool_args=delegated_tool_args, result_text=summary)
    return {}, []


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


def _parse_json_object(value: str) -> dict[str, Any]:
    import json

    text = str(value or "").strip()
    if not text.startswith("{"):
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _binding_identity(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def _compact_summary(value: str, max_chars: int = 280) -> str:
    return " ".join(str(value or "").split()).strip()[:max_chars]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _followup_contract_from_task_spec(task_spec_payload: dict[str, Any] | None) -> dict[str, Any]:
    inputs = dict(dict(task_spec_payload or {}).get("inputs") or {})
    contract = dict(inputs.get("followup_execution_contract") or {})
    if not contract:
        return {}
    return contract if str(contract.get("authority") or "") == "task_system.followup_execution_contract" else {}


def _followup_contract_source_path(followup_contract: dict[str, Any], *, binding_key: str) -> str:
    if not followup_contract:
        return ""
    binding = str(binding_key or "").strip()
    source_kind = str(followup_contract.get("source_kind") or "").strip()
    if binding == "active_dataset" and source_kind == "dataset":
        return _clean_text(followup_contract.get("source_path"))
    if binding == "active_pdf" and source_kind == "pdf":
        return _clean_text(followup_contract.get("source_path"))
    return ""


def _merge_followup_contract_into_payload(
    payload: dict[str, Any],
    *,
    followup_contract: dict[str, Any],
) -> dict[str, Any]:
    if not followup_contract:
        return dict(payload or {})
    merged = dict(payload or {})
    for key in (
        "followup_scope",
        "followup_target_kind",
        "followup_target_refs",
        "active_subset_handle_id",
        "active_result_handle_id",
        "active_object_handle_id",
        "subset_labels",
        "subset_filter_column",
    ):
        value = followup_contract.get(key)
        if value not in ("", [], {}, None):
            merged.setdefault(key, value)
    constraint_policy = str(followup_contract.get("constraint_policy") or "").strip()
    if constraint_policy:
        merged.setdefault("followup_constraint_policy", constraint_policy)
    source_path = _clean_text(followup_contract.get("source_path"))
    source_kind = _clean_text(followup_contract.get("source_kind"))
    current_tool_input = _compact_followup_tool_input(dict(followup_contract.get("tool_input") or {}))
    if source_path:
        if source_kind == "dataset":
            merged.setdefault("active_dataset", source_path)
            merged.setdefault("path", source_path)
        elif source_kind == "pdf":
            merged.setdefault("active_pdf", source_path)
            merged.setdefault("path", source_path)
    if current_tool_input:
        for key in ("query", "mode", "extract_mode", "section", "page", "pages", "max_chunks"):
            value = current_tool_input.get(key)
            if value not in ("", [], {}, None):
                merged[key] = value
        for key in ("path", "file_path", "active_pdf", "active_dataset"):
            value = current_tool_input.get(key)
            if value not in ("", [], {}, None):
                merged.setdefault(key, value)
    if followup_contract.get("subset_labels") or followup_contract.get("subset_filter_column"):
        semantic_hints = dict(merged.get("semantic_hints") or {})
        if followup_contract.get("subset_labels"):
            semantic_hints.setdefault("subset_allowed_values", list(followup_contract.get("subset_labels") or []))
        if followup_contract.get("subset_filter_column"):
            semantic_hints.setdefault("subset_filter_column", followup_contract.get("subset_filter_column"))
        merged["semantic_hints"] = semantic_hints
    return merged


def _compact_followup_tool_input(tool_input: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "query",
        "mode",
        "extract_mode",
        "path",
        "file_path",
        "active_pdf",
        "active_dataset",
        "section",
        "page",
        "pages",
        "max_chunks",
    ):
        value = tool_input.get(key)
        if value in ("", [], {}, None):
            continue
        compact[key] = value
    return compact


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


def _looks_like_runtime_internal_answer(value: str) -> bool:
    text = str(value or "").strip()
    internal_markers = (
        "本轮运行预算达到上限",
        "本轮运行时间达到上限",
        "本轮模型续写次数达到上限",
        "本轮委派全部被限流",
        "委派被限流",
        "请直接继续问",
        "下一轮我会优先调用",
    )
    return any(marker in text for marker in internal_markers)


def _classify_delegation_goal_alignment(
    *,
    user_message: str,
    instruction: str,
    input_payload: dict[str, Any],
) -> str:
    user_text = _clean_text(user_message)
    instruction_text = _clean_text(instruction)
    path = _clean_text(
        input_payload.get("file_path")
        or input_payload.get("path")
        or input_payload.get("active_pdf")
        or input_payload.get("active_dataset")
    )
    if not user_text or not instruction_text:
        return "unknown"
    user_lower = user_text.lower()
    instruction_lower = instruction_text.lower()
    if path:
        normalized_path = path.replace("\\", "/").lower()
        if normalized_path and normalized_path in user_lower:
            return "aligned"
        file_name = normalized_path.split("/")[-1]
        if file_name and file_name in user_lower:
            return "aligned"
    user_tokens = set(_alignment_tokens(user_text))
    instruction_tokens = set(_alignment_tokens(instruction_text))
    if not user_tokens or not instruction_tokens:
        return "unknown"
    overlap = user_tokens & instruction_tokens
    if len(overlap) >= 2:
        return "aligned"
    strong_user = any(token in user_lower for token in ("pdf", ".pdf", "第3页", "第三页", "第4页", "第四页", "第二部分", "章节"))
    strong_instruction = any(
        token in instruction_lower for token in ("pdf", ".pdf", "页", "第二部分", "章节", "全文", "目录页", "正文页")
    )
    if strong_user and strong_instruction:
        return "aligned"
    if strong_user != strong_instruction and not overlap:
        return "offtopic"
    if any(token in user_lower for token in ("表格", "excel", ".xlsx", ".csv")) and not any(
        token in instruction_lower for token in ("表格", "excel", ".xlsx", ".csv", "数据表", "数据集")
    ):
        return "offtopic"
    if any(token in user_lower for token in ("黄金", "金价", "xau", "天气")) and not any(
        token in instruction_lower for token in ("黄金", "金价", "xau", "天气")
    ):
        return "offtopic"
    return "unknown"


def _alignment_tokens(value: str) -> list[str]:
    import re

    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9_.:/\\-]{2,}|[\u4e00-\u9fff]{2,8}", str(value or "")):
        token = match.group(0).strip().lower()
        if not token or token in {"当前", "继续", "直接", "告诉我", "给我", "分析", "文件", "内容", "结果"}:
            continue
        tokens.append(token)
    return tokens


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


def _resolve_runtime_search_sources(
    *,
    search_policy: list[str] | tuple[str, ...] | set[str] | None,
    task_selection: dict[str, Any] | None,
) -> set[str]:
    if search_policy is not None:
        return normalize_search_policy(search_policy)
    selection = dict(task_selection or {})
    if _selection_is_coordination_task(selection):
        explicit_policy = _extract_task_search_policy(selection)
        if explicit_policy is not None:
            return normalize_search_policy(explicit_policy)
        return set()
    return normalize_search_policy(None)


def _selection_is_coordination_task(selection: dict[str, Any]) -> bool:
    if str(selection.get("continuation_stage_id") or "").strip():
        return True
    if dict(selection.get("stage_execution_request") or {}):
        return True
    if str(selection.get("coordination_run_id") or "").strip():
        return True
    runtime_assembly = dict(selection.get("runtime_assembly") or {})
    if str(runtime_assembly.get("runtime_lane") or "").strip() == "coordination_task":
        return True
    return str(selection.get("runtime_lane") or "").strip() == "coordination_task"


def _extract_task_search_policy(selection: dict[str, Any]) -> list[str] | tuple[str, ...] | set[str] | None:
    for key in ("search_policy", "allowed_search_sources"):
        value = selection.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    operation_policy = dict(selection.get("operation_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = operation_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    stage_request = dict(selection.get("stage_execution_request") or {})
    runtime_assembly = dict(stage_request.get("runtime_assembly") or selection.get("runtime_assembly") or {})
    permission_policy = dict(runtime_assembly.get("permission_policy") or runtime_assembly.get("resource_policy") or {})
    for key in ("search_policy", "allowed_search_sources"):
        value = permission_policy.get(key)
        if isinstance(value, (list, tuple, set)):
            return value
    return None


def _task_operation_allows_context_retrieval(
    *,
    task_operation: dict[str, Any],
    allowed_search_sources: set[str],
) -> bool:
    if not operation_allowed_by_search_policy("op.mcp_retrieval", allowed_search_sources):
        return False
    query_understanding = dict(task_operation.get("query_understanding") or {})
    if bool(query_understanding.get("should_skip_rag")):
        return False
    current_turn = dict(task_operation.get("current_turn_context") or {})
    if _selection_is_coordination_task(current_turn):
        return False
    operation_requirement = dict(task_operation.get("operation_requirement") or {})
    operations = {
        str(item or "").strip()
        for item in [
            *list(operation_requirement.get("required_operations") or []),
            *list(operation_requirement.get("skill_required_operations") or []),
        ]
        if str(item or "").strip()
    }
    if "op.mcp_retrieval" in operations:
        return True
    recipe = dict(task_operation.get("selected_recipe") or {})
    return str(recipe.get("source_kind") or "").strip() in {"knowledge", "retrieval", "knowledge_base"}


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
            "durable_memory_commit_attempted": False,
            "durable_memory_commit_failed": False,
            "durable_memory_commit_applied": False,
            "memory_maintenance_attempted": False,
            "memory_maintenance_status": "",
            "session_memory_succeeded": False,
            "durable_memory_succeeded": False,
            "durable_write_count": 0,
            "session_memory_chars": 0,
            "durable_saved_count": 0,
        }
    session_memory_chars = _safe_int(result.get("session_memory_chars"))
    durable_saved_count = _safe_int(result.get("durable_write_count", result.get("durable_saved_count")))
    maintenance_attempted = bool(result.get("memory_maintenance_attempted") is True)
    maintenance_status = str(result.get("memory_maintenance_status") or "")
    session_memory_succeeded = bool(result.get("session_memory_succeeded") is True)
    durable_memory_succeeded = bool(result.get("durable_memory_succeeded") is True)
    durable_commit_attempted = maintenance_attempted or bool(result.get("durable_memory_commit_attempted") is True)
    durable_commit_failed = maintenance_status == "failed" or bool(result.get("durable_memory_commit_failed") is True)
    return {
        "memory_write_allowed": True,
        "session_memory_refresh_applied": session_memory_succeeded or session_memory_chars > 0,
        "durable_memory_commit_attempted": durable_commit_attempted,
        "durable_memory_commit_failed": durable_commit_failed,
        "durable_memory_commit_applied": durable_commit_attempted and not durable_commit_failed and durable_saved_count > 0,
        "memory_maintenance_attempted": maintenance_attempted,
        "memory_maintenance_status": maintenance_status,
        "session_memory_succeeded": session_memory_succeeded,
        "durable_memory_succeeded": durable_memory_succeeded,
        "durable_write_count": durable_saved_count,
        "session_memory_chars": session_memory_chars,
        "durable_saved_count": durable_saved_count,
    }


def _working_memory_refs_from_assembly(assembly: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for section in list(dict(assembly or {}).get("context_sections") or []):
        if not isinstance(section, dict):
            continue
        metadata = dict(section.get("metadata") or {})
        for item in list(metadata.get("refs") or []):
            value = str(item or "").strip()
            if value and value not in refs:
                refs.append(value)
    return refs


def _working_memory_diagnostics_from_assembly(assembly: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(dict(assembly or {}).get("diagnostics") or {})
    keys = (
        "working_memory_enabled",
        "working_memory_task_run_id",
        "working_memory_graph_id",
        "working_memory_owner_node_id",
        "working_memory_node_run_id",
        "working_memory_run_attempt_id",
        "working_memory_required_count",
        "working_memory_preferred_count",
        "working_memory_conflict_count",
    )
    return {
        key: diagnostics.get(key)
        for key in keys
        if key in diagnostics
    }


def _specific_task_record_for_runtime_ref(flow_registry: TaskFlowRegistry, task_ref: str) -> Any | None:
    """Resolve a runtime task instance id back to its configured specific task."""
    raw = str(task_ref or "").strip()
    if not raw:
        return None
    suffix = raw.split(":")[-1].strip()
    if not suffix:
        return None
    for record in flow_registry.list_specific_task_records():
        task_id = str(getattr(record, "task_id", "") or "").strip()
        if task_id == raw or task_id.endswith(f".{suffix}") or task_id.split(".")[-1] == suffix:
            return record
    return None


def _compile_agent_dispatch_plan_from_graph_payload(
    *,
    task_run_id: str,
    coordination_run_id: str,
    graph_payload: dict[str, Any],
    topology_template_payload: dict[str, Any],
) -> AgentDispatchPlan:
    nodes = _dispatch_nodes_from_payload(graph_payload, topology_template_payload)
    edges = _dispatch_edges_from_payload(graph_payload, topology_template_payload)
    upstream: dict[str, list[str]] = {}
    downstream: dict[str, list[str]] = {}
    for edge in edges:
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if source and target:
            downstream.setdefault(source, []).append(target)
            upstream.setdefault(target, []).append(source)

    records: list[AgentDispatchRecord] = []
    barriers: list[CoordinationBarrierState] = []
    notifications: list[QueuedAgentNotification] = []
    dispatch_groups: dict[str, list[str]] = {}
    ready_node_ids: list[str] = []
    blocked_node_ids: list[str] = []
    background_node_ids: list[str] = []
    now = time.time()
    for index, node in enumerate(nodes):
        node_id = str(node.get("node_id") or node.get("id") or f"node_{index + 1}").strip()
        if not node_id:
            continue
        mode = str(node.get("execution_mode") or "sync").strip() or "sync"
        dispatch_group = str(node.get("dispatch_group") or "").strip()
        wait_policy = str(node.get("wait_policy") or "wait_all_upstream_completed").strip() or "wait_all_upstream_completed"
        join_policy = str(node.get("join_policy") or "all_success").strip() or "all_success"
        node_metadata = dict(node.get("metadata") or {}) if isinstance(node.get("metadata"), dict) else {}
        background_policy = dict(node.get("background_policy") or node_metadata.get("background_policy") or {})
        notification_policy = dict(node.get("notification_policy") or node_metadata.get("notification_policy") or {})
        lifecycle_policy = dict(node.get("resource_lifecycle_policy") or node_metadata.get("resource_lifecycle_policy") or {})
        node_upstream = tuple(upstream.get(node_id, ()))
        node_downstream = tuple(downstream.get(node_id, ()))
        status = "ready" if not node_upstream or wait_policy == "fire_and_continue" else "blocked"
        if mode == "manual_gate":
            status = "waiting"
        if status == "ready":
            ready_node_ids.append(node_id)
        else:
            blocked_node_ids.append(node_id)
        if mode == "background":
            background_node_ids.append(node_id)
        if dispatch_group:
            dispatch_groups.setdefault(dispatch_group, []).append(node_id)
        record = AgentDispatchRecord(
            dispatch_id=f"dispatch:{coordination_run_id}:{node_id}",
            task_run_id=task_run_id,
            coordination_run_id=coordination_run_id,
            node_id=node_id,
            node_run_id=f"noderun:{coordination_run_id}:{node_id}",
            agent_id=str(node.get("agent_id") or "").strip(),
            execution_mode=mode,
            dispatch_group=dispatch_group,
            wait_policy=wait_policy,
            join_policy=join_policy,
            status=status,
            blocks_downstream=not (mode == "background" and background_policy.get("blocks_downstream") is False),
            background_policy=background_policy,
            notification_policy=notification_policy,
            resource_lifecycle_policy=lifecycle_policy,
            upstream_node_ids=node_upstream,
            downstream_node_ids=node_downstream,
            created_at=now,
            diagnostics={
                "node_type": str(node.get("node_type") or ""),
                "input_contract_id": str(node.get("input_contract_id") or node_metadata.get("input_contract_id") or ""),
                "output_contract_id": str(node.get("output_contract_id") or node.get("node_contract_id") or node_metadata.get("output_contract_id") or node_metadata.get("node_contract_id") or ""),
                "projection_id": str(node.get("projection_id") or node_metadata.get("projection_id") or ""),
            },
        )
        records.append(record)
        if mode == "barrier":
            barriers.append(
                CoordinationBarrierState(
                    barrier_id=f"barrier:{coordination_run_id}:{node_id}",
                    task_run_id=task_run_id,
                    coordination_run_id=coordination_run_id,
                    node_id=node_id,
                    join_policy=join_policy,
                    waiting_for_node_ids=node_upstream,
                    status="waiting",
                )
            )
        if mode == "background":
            notifications.append(
                QueuedAgentNotification(
                    notification_id=f"notify:{coordination_run_id}:{node_id}:completion",
                    task_run_id=task_run_id,
                    coordination_run_id=coordination_run_id,
                    node_id=node_id,
                    event="background_completion_pending",
                    priority=str(notification_policy.get("priority") or "later"),
                    include_result=str(notification_policy.get("include_result") or "summary_and_refs"),
                    status="queued",
                    created_at=now,
                    diagnostics={"state_order": "status_before_notification"},
                )
            )

    return AgentDispatchPlan(
        dispatch_plan_id=f"dispatchplan:{coordination_run_id}",
        task_run_id=task_run_id,
        coordination_run_id=coordination_run_id,
        records=tuple(records),
        barrier_states=tuple(barriers),
        queued_notifications=tuple(notifications),
        ready_node_ids=tuple(ready_node_ids),
        blocked_node_ids=tuple(blocked_node_ids),
        background_node_ids=tuple(background_node_ids),
        dispatch_groups=dispatch_groups,
        diagnostics={
            "node_count": len(records),
            "edge_count": len(edges),
            "ready_count": len(ready_node_ids),
            "blocked_count": len(blocked_node_ids),
            "background_count": len(background_node_ids),
            "barrier_count": len(barriers),
            "notification_count": len(notifications),
            "scheduler_phase": "compiled_plan_only",
        },
    )


def _dispatch_graph_payload_from_task_graph_runtime_spec(
    *,
    graph: TaskGraphDefinition,
    runtime_spec: TaskGraphRuntimeSpec,
) -> dict[str, Any]:
    runtime_nodes = [node.to_dict() for node in runtime_spec.nodes]
    runtime_edges = [
        {
            **edge.to_dict(),
            "edge_type": edge.mode,
        }
        for edge in runtime_spec.edges
    ]
    return {
        "authority": "orchestration.task_graph_dispatch_payload",
        "graph_id": graph.graph_id,
        "task_graph_id": graph.graph_id,
        "title": graph.title,
        "domain_id": graph.domain_id,
        "task_family": graph.task_family,
        "graph_kind": graph.graph_kind,
        "coordinator_agent_id": runtime_spec.coordinator_agent_id,
        "agent_group_id": runtime_spec.agent_group_id,
        "topology_template_id": str(graph.metadata.get("topology_template_id") or ""),
        "handoff_policy": str((runtime_spec.communication_modes or ("handoff",))[0]),
        "conflict_resolution_policy": str(dict(graph.runtime_policy or {}).get("failure_policy") or ""),
        "output_merge_policy": str(dict(graph.runtime_policy or {}).get("merge_policy") or ""),
        "shared_context_policy": str(dict(graph.context_policy or {}).get("shared_context_policy") or ""),
        "memory_sharing_policy": str(dict(graph.working_memory_policy or {}).get("memory_sharing_policy") or ""),
        "graph_nodes": runtime_nodes,
        "graph_edges": runtime_edges,
        "metadata": {
            **dict(graph.metadata or {}),
            "runtime_spec_source": str(dict(runtime_spec.diagnostics or {}).get("source") or ""),
            "start_node_ids": list(runtime_spec.start_node_ids),
            "terminal_node_ids": list(runtime_spec.terminal_node_ids),
            "communication_modes": list(runtime_spec.communication_modes),
        },
    }


def _normalize_runtime_graph_payload(
    *,
    raw_graph_payload: dict[str, Any],
    task_graph_payload: dict[str, Any],
    runtime_spec_payload: dict[str, Any],
) -> dict[str, Any]:
    graph_payload = dict(raw_graph_payload or {})
    task_graph = dict(task_graph_payload or {})
    if not graph_payload and not task_graph:
        return {}
    if graph_payload.get("authority") == "orchestration.task_graph_dispatch_payload":
        return graph_payload
    metadata = dict(task_graph.get("metadata") or graph_payload.get("metadata") or {})
    runtime_policy = dict(task_graph.get("runtime_policy") or graph_payload.get("runtime_policy") or {})
    context_policy = dict(task_graph.get("context_policy") or graph_payload.get("context_policy") or {})
    working_memory_policy = dict(task_graph.get("working_memory_policy") or graph_payload.get("working_memory_policy") or {})
    runtime_spec = _runtime_spec_from_payload(runtime_spec_payload) if runtime_spec_payload else None
    if runtime_spec is not None:
        graph_definition = task_graph_from_dict(task_graph) if task_graph else task_graph_from_dict(graph_payload)
        return _dispatch_graph_payload_from_task_graph_runtime_spec(
            graph=graph_definition,
            runtime_spec=runtime_spec,
        )
    return {
        **graph_payload,
        "authority": "orchestration.task_graph_dispatch_payload",
        "graph_id": str(task_graph.get("graph_id") or graph_payload.get("graph_id") or graph_payload.get("task_graph_id") or ""),
        "task_graph_id": str(task_graph.get("graph_id") or graph_payload.get("task_graph_id") or graph_payload.get("graph_id") or ""),
        "title": str(task_graph.get("title") or graph_payload.get("title") or ""),
        "domain_id": str(task_graph.get("domain_id") or graph_payload.get("domain_id") or ""),
        "task_family": str(task_graph.get("task_family") or graph_payload.get("task_family") or ""),
        "graph_kind": str(task_graph.get("graph_kind") or graph_payload.get("graph_kind") or "coordination"),
        "coordinator_agent_id": str(runtime_policy.get("coordinator_agent_id") or graph_payload.get("coordinator_agent_id") or "agent:0"),
        "agent_group_id": str(runtime_policy.get("agent_group_id") or graph_payload.get("agent_group_id") or ""),
        "topology_template_id": str(metadata.get("topology_template_id") or graph_payload.get("topology_template_id") or ""),
        "handoff_policy": str(metadata.get("handoff_policy") or graph_payload.get("handoff_policy") or "handoff"),
        "conflict_resolution_policy": str(metadata.get("conflict_resolution_policy") or graph_payload.get("conflict_resolution_policy") or "coordinator_review"),
        "output_merge_policy": str(metadata.get("output_merge_policy") or graph_payload.get("output_merge_policy") or "coordinator_final_merge"),
        "shared_context_policy": str(context_policy.get("shared_context_policy") or graph_payload.get("shared_context_policy") or "explicit_refs_only"),
        "memory_sharing_policy": str(context_policy.get("memory_sharing_policy") or working_memory_policy.get("memory_sharing_policy") or graph_payload.get("memory_sharing_policy") or "isolated_by_default"),
        "graph_nodes": list(task_graph.get("graph_nodes") or task_graph.get("nodes") or graph_payload.get("graph_nodes") or graph_payload.get("nodes") or []),
        "graph_edges": list(task_graph.get("graph_edges") or task_graph.get("edges") or graph_payload.get("graph_edges") or graph_payload.get("edges") or []),
        "metadata": {
            **metadata,
            **dict(graph_payload.get("metadata") or {}),
        },
    }


def _runtime_spec_from_payload(payload: dict[str, Any]) -> TaskGraphRuntimeSpec | None:
    if not payload:
        return None
    try:
        return TaskGraphRuntimeSpec(
            graph_id=str(payload.get("graph_id") or ""),
            domain_id=str(payload.get("domain_id") or ""),
            task_family=str(payload.get("task_family") or ""),
            coordinator_agent_id=str(payload.get("coordinator_agent_id") or ""),
            graph_ref=str(payload.get("graph_ref") or payload.get("graph_id") or ""),
            agent_group_id=str(payload.get("agent_group_id") or ""),
            nodes=tuple(
                TaskGraphRuntimeNode(**{key: value for key, value in dict(item).items() if key in TaskGraphRuntimeNode.__dataclass_fields__})
                for item in list(payload.get("nodes") or [])
                if isinstance(item, dict)
            ),
            edges=tuple(
                TaskGraphRuntimeEdge(**{key: value for key, value in dict(item).items() if key in TaskGraphRuntimeEdge.__dataclass_fields__})
                for item in list(payload.get("edges") or [])
                if isinstance(item, dict)
            ),
            subtask_refs=tuple(str(item) for item in list(payload.get("subtask_refs") or []) if str(item)),
            communication_modes=tuple(str(item) for item in list(payload.get("communication_modes") or []) if str(item)),
            start_node_ids=tuple(str(item) for item in list(payload.get("start_node_ids") or []) if str(item)),
            terminal_node_ids=tuple(str(item) for item in list(payload.get("terminal_node_ids") or []) if str(item)),
            resource_nodes=_dict_tuple(payload.get("resource_nodes")),
            temporal_edges=_dict_tuple(payload.get("temporal_edges")),
            memory_edges=_dict_tuple(payload.get("memory_edges")),
            artifact_context_edges=_dict_tuple(payload.get("artifact_context_edges")),
            revision_edges=_dict_tuple(payload.get("revision_edges")),
            loop_frames=_dict_tuple(payload.get("loop_frames")),
            memory_matrix=dict(payload.get("memory_matrix") or {}),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    except (TypeError, ValueError):
        return None


def _dispatch_nodes_from_payload(graph_payload: dict[str, Any], topology_template_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        graph_payload.get("graph_nodes"),
        topology_template_payload.get("nodes"),
        dict(graph_payload.get("metadata") or {}).get("graph_nodes"),
    )
    for value in candidates:
        nodes = [dict(item) for item in list(value or []) if isinstance(item, dict)]
        if nodes:
            return nodes
    return []


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _dispatch_edges_from_payload(graph_payload: dict[str, Any], topology_template_payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = (
        graph_payload.get("graph_edges"),
        topology_template_payload.get("edges"),
        dict(graph_payload.get("metadata") or {}).get("graph_edges"),
    )
    for value in candidates:
        edges = [dict(item) for item in list(value or []) if isinstance(item, dict)]
        if edges:
            return edges
    return []


def _runtime_loop_short_hash(value: Any) -> str:
    import hashlib
    import json

    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _working_memory_root_for_loop(root_dir: Path) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "working_memory"
    return runtime_root / "working_memory"


def _artifact_repository_root_for_loop(root_dir: Path) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "artifact_repository"
    return runtime_root / "artifact_repository"


def _model_stream_policy_from_task_execution_assembly(
    task_execution_assembly: dict[str, Any],
    *,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    turn_context = dict(current_turn_context or {})
    stage_request = dict(turn_context.get("stage_execution_request") or {})
    policy: dict[str, Any] = {}
    for candidate in (
        assembly_metadata.get("stream_policy"),
        assembly_diagnostics.get("stream_policy"),
        stage_request.get("stream_policy"),
        turn_context.get("stream_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return {
        "enabled": bool(policy.get("enabled") is True),
        "mode": str(policy.get("mode") or "disabled"),
        "monitor_visibility": str(policy.get("monitor_visibility") or "none"),
        "chunk_event_type": str(policy.get("chunk_event_type") or ""),
        "emit_text_preview": bool(policy.get("emit_text_preview") is True),
        "preview_char_limit": _safe_int(policy.get("preview_char_limit")),
        "persist_full_stream_text": bool(policy.get("persist_full_stream_text") is True),
        "fallback_to_non_stream_on_error": bool(policy.get("fallback_to_non_stream_on_error", True) is not False),
        "authority": "orchestration.task_stream_policy",
    }


def _artifact_policy_from_task_execution_assembly(
    *,
    selected_recipe_payload: dict[str, Any],
    task_execution_assembly: dict[str, Any],
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assembly_payload = dict(task_execution_assembly or {})
    assembly_metadata = dict(assembly_payload.get("metadata") or {})
    assembly_diagnostics = dict(assembly_payload.get("diagnostics") or {})
    turn_context = dict(current_turn_context or {})
    stage_request = dict(turn_context.get("stage_execution_request") or {})
    policy: dict[str, Any] = {}
    for candidate in (
        selected_recipe_payload.get("artifact_policy"),
        assembly_metadata.get("artifact_policy"),
        assembly_diagnostics.get("artifact_policy"),
        stage_request.get("artifact_policy"),
        turn_context.get("artifact_policy"),
    ):
        candidate_dict = dict(candidate or {})
        if candidate_dict:
            policy = {**policy, **candidate_dict}
    return policy


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_text_units(content: str) -> int:
    text = str(content or "").strip()
    if not text:
        return 0
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))
    return cjk_chars + latin_words


def _stage_business_acceptance(
    *,
    stage_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any] | None = None,
    final_content: str,
    output_refs: list[str],
    terminal_status: str,
    requires_file_artifact_refs: bool,
) -> dict[str, Any]:
    artifact_ok = bool(output_refs) if requires_file_artifact_refs else True
    base_accepted = str(terminal_status or "") == "completed" and artifact_ok
    quality_policy = dict(contract.get("quality_retry_policy") or {})
    accepted_policies = {str(item) for item in list(quality_policy.get("acceptance_policies") or []) if str(item)}
    if "sectioned_text_batch_quality" in accepted_policies:
        content_quality = _sectioned_text_batch_quality_gate(
            final_content,
            explicit_inputs=dict(explicit_inputs or {}),
            policy=quality_policy,
        )
        return {
            "accepted": bool(base_accepted and content_quality["accepted"]),
            "base_accepted": base_accepted,
            "business_accepted": bool(content_quality["accepted"]),
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "sectioned_text_batch_quality",
            **content_quality,
            "authority": "orchestration.stage_business_acceptance",
        }
    node_type = str(contract.get("node_type") or "").strip()
    review_policy = dict(contract.get("review_gate_policy") or {})
    gate_policy = str(contract.get("gate_policy") or "").strip()
    is_review_gate = node_type == "review_gate" or gate_policy == "review_gate" or bool(review_policy)
    if not is_review_gate:
        return {
            "accepted": base_accepted,
            "base_accepted": base_accepted,
            "artifact_ok": artifact_ok,
            "stage_id": stage_id,
            "policy": "technical_completion",
            "authority": "orchestration.stage_business_acceptance",
        }
    verdict = _extract_review_verdict(final_content)
    allowed_to_commit = _extract_review_commit_permission(final_content)
    if verdict in {"pass", "pass_with_notes"}:
        business_accepted = True
    elif verdict in {"revise", "revise_volume", "revise_extension", "repair_canon", "fail_closed", "human_review_required", "reject", "blocker_found"}:
        business_accepted = False
    elif allowed_to_commit is not None:
        business_accepted = allowed_to_commit
    else:
        business_accepted = False
    return {
        "accepted": bool(base_accepted and business_accepted),
        "base_accepted": base_accepted,
        "business_accepted": business_accepted,
        "artifact_ok": artifact_ok,
        "stage_id": stage_id,
        "policy": "review_gate_verdict",
        "verdict": verdict,
        "allowed_to_commit": allowed_to_commit,
        "authority": "orchestration.stage_business_acceptance",
    }


def _extract_review_verdict(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    explicit_verdict = _extract_explicit_review_verdict(text)
    if explicit_verdict:
        return explicit_verdict
    if "不允许写入" in text or "不允许批次写入" in text or "必须等正文" in text:
        return "revise"
    if "允许批次写入记忆：否" in text or "是否允许批次写入记忆：否" in text:
        return "revise"
    if re.search(r"\bfail[_ -]?closed\b", lowered):
        return "fail_closed"
    for verdict in ("repair_canon", "revise_volume", "revise_extension", "blocker_found", "reject", "human_review_required", "pass_with_notes"):
        if verdict in lowered:
            return "pass_with_notes" if verdict == "pass_with_notes" else ("revise" if verdict in {"repair_canon", "revise_volume", "revise_extension", "blocker_found", "reject"} else verdict)
    return ""


def _extract_explicit_review_verdict(text: str) -> str:
    verdict_map = {
        "pass": "pass",
        "approved": "pass",
        "approve": "pass",
        "通过": "pass",
        "同意": "pass",
        "revise": "revise",
        "pass_with_notes": "pass",
        "revision required": "revise",
        "修订": "revise",
        "修改": "revise",
        "返工": "revise",
        "不通过": "revise",
        "repair_canon": "revise",
        "revise_volume": "revise",
        "revise_extension": "revise",
        "blocker_found": "revise",
        "reject": "revise",
        "human_review_required": "human_review_required",
        "fail_closed": "fail_closed",
    }
    patterns = (
        r"^\s*[【\[]?\s*(?:裁决|结论|verdict)\s*[】\]]?\s*[:：-]?\s*([^\n\r]+)",
        r"^\s*(?:裁决|结论|verdict)\s*[:：-]\s*([^\n\r]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            value = str(match.group(1) or "").strip().lower()
            for token, verdict in verdict_map.items():
                if token in value:
                    return verdict
    return ""


def _extract_review_commit_permission(content: str) -> bool | None:
    text = str(content or "")
    if not text.strip():
        return None
    if re.search(r"是否允许批次写入记忆\s*[:：]\s*(是|允许|yes|true|pass)", text, re.IGNORECASE):
        return True
    if re.search(r"是否允许批次写入记忆\s*[:：]\s*(否|不允许|no|false)", text, re.IGNORECASE):
        return False
    if "不允许写入" in text or "不允许批次写入" in text:
        return False
    if "允许批次写入记忆" in text and "否" not in text:
        return True
    return None


def _sectioned_text_batch_quality_gate(
    content: str,
    *,
    explicit_inputs: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    text = str(content or "").strip()
    content_metric_total = _count_text_units(text)
    unit_count_key = str(policy.get("unit_count_key") or "unit_count")
    unit_start_key = str(policy.get("unit_start_key") or "unit_start_index")
    unit_end_key = str(policy.get("unit_end_key") or "unit_end_index")
    unit_index_key = str(policy.get("unit_index_key") or unit_start_key)
    target_metric_key = str(policy.get("target_metric_key") or "target_metric_total")
    unit_target_metric_key = str(policy.get("unit_target_metric_key") or "")
    units_per_batch = max(
        _safe_int(explicit_inputs.get(unit_count_key)) or 1,
        1,
    )
    start_index = _safe_int(explicit_inputs.get(unit_start_key) or explicit_inputs.get(unit_index_key)) or 1
    end_index = _safe_int(explicit_inputs.get(unit_end_key)) or (start_index + units_per_batch - 1)
    expected_indexes = list(range(start_index, end_index + 1)) if end_index >= start_index else [start_index]
    heading_patterns = tuple(str(item).strip() for item in list(policy.get("required_heading_patterns") or []) if str(item).strip())
    found_indexes = _extract_indexed_markers(text, heading_patterns)
    missing_indexes = [index for index in expected_indexes if index not in found_indexes] if heading_patterns else []
    target_metric_total = _safe_int(explicit_inputs.get(target_metric_key)) or (
        (_safe_int(explicit_inputs.get(unit_target_metric_key)) or 0) * units_per_batch
    )
    min_ratio = float(policy.get("minimum_metric_ratio") or 0.0)
    min_per_unit = _safe_int(policy.get("minimum_metric_per_unit"))
    min_metric_total = max(min_per_unit * units_per_batch, int(target_metric_total * min_ratio))
    refusal_markers = tuple(str(item) for item in list(policy.get("refusal_markers") or [])) or (
        "抱歉，我无法",
        "无法执行这个请求",
        "请先提供",
        "缺少前置资产",
        "我没有读取到",
        "当前可推进步骤",
        "不能直接产出",
    )
    refusal_detected = any(marker in text for marker in refusal_markers)
    issues: list[str] = []
    if not text:
        issues.append("empty_content")
    if refusal_detected:
        issues.append("refusal_or_process_text_detected")
    if min_metric_total > 0 and content_metric_total < min_metric_total:
        issues.append(f"insufficient_metric:{content_metric_total}<{min_metric_total}")
    if missing_indexes:
        issues.append("missing_required_sections:" + ",".join(str(index) for index in missing_indexes))
    return {
        "accepted": not issues,
        "content_metric_total": content_metric_total,
        "min_required_metric_total": min_metric_total,
        "expected_unit_indexes": expected_indexes,
        "found_unit_indexes": sorted(found_indexes),
        "missing_unit_indexes": missing_indexes,
        "issues": issues,
    }


def _extract_indexed_markers(content: str, patterns: tuple[str, ...]) -> set[int]:
    indexes: set[int] = set()
    for pattern in patterns:
        try:
            matches = list(re.finditer(pattern, str(content or ""), flags=re.MULTILINE))
        except re.error:
            continue
        for match in matches:
            value = ""
            if "index" in match.groupdict():
                value = str(match.groupdict().get("index") or "")
            elif match.groups():
                value = str(match.group(1) or "")
            parsed = _parse_index_number(value)
            if parsed > 0:
                indexes.add(parsed)
    return indexes


def _parse_index_number(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    for char in raw:
        if char in digits:
            current = digits[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


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


class _ContinuationAgentRuntimeChain:
    def __init__(self, *, base: Any, forced_turn_context: dict[str, Any]) -> None:
        self._base = base
        self._forced_turn_context = dict(forced_turn_context or {})

    def build_runtime(self, **kwargs) -> dict[str, Any]:
        override = {
            **dict(kwargs.get("current_turn_context_override") or {}),
            **dict(self._forced_turn_context),
        }
        forced_agent_id = str(self._forced_turn_context.get("agent_id") or "").strip()
        if forced_agent_id:
            override["agent_id"] = forced_agent_id
        kwargs["current_turn_context_override"] = override
        task_selection = {
            **dict(kwargs.get("task_selection") or {}),
            **{
                key: value
                for key, value in override.items()
                if value not in ("", None, [], {})
            },
        }
        if forced_agent_id:
            task_selection["agent_id"] = forced_agent_id
        kwargs["task_selection"] = task_selection
        runtime = dict(self._base.build_runtime(**kwargs) or {})
        current_turn_context = {
            **dict(runtime.get("current_turn_context") or {}),
            **dict(self._forced_turn_context),
        }
        task_operation = dict(runtime.get("task_operation") or {})
        task_operation["current_turn_context"] = current_turn_context
        task_spec = dict(task_operation.get("task_spec") or {})
        task_spec["inputs"] = {
            **dict(task_spec.get("inputs") or {}),
            **dict(current_turn_context.get("explicit_inputs") or {}),
        }
        task_operation["task_spec"] = task_spec
        expected_agent_id = str(current_turn_context.get("agent_id") or "").strip()
        if expected_agent_id:
            agent_runtime_spec = dict(runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
            actual_agent_id = str(agent_runtime_spec.get("agent_id") or "").strip()
            if actual_agent_id != expected_agent_id:
                raise ValueError(
                    "TaskGraph node runtime assembled with wrong agent: "
                    f"expected {expected_agent_id}, got {actual_agent_id or '<empty>'}"
                )
        runtime["current_turn_context"] = current_turn_context
        runtime["task_operation"] = task_operation
        return runtime

    def build_context_policy_result(self, *args, **kwargs):
        return self._base.build_context_policy_result(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._base, name)

    @staticmethod
    def unwrap(chain: Any) -> Any:
        while isinstance(chain, _ContinuationAgentRuntimeChain):
            chain = chain._base
        return chain
