from __future__ import annotations

import inspect
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import ToolMessage

from capability_system import build_default_operation_registry
from capability_system.local_mcp_registry import get_local_mcp_unit, get_local_mcp_unit_for_source_kind
from capability_system.search_policy import (
    normalize_search_policy,
    operation_allowed_by_search_policy,
)
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from agent_system.models.model_profile_resolver import ModelProfileResolver
from permissions import (
    ApprovalToken,
    OperationGate,
    OperationGatePipelineContext,
)
from project_layout import ProjectLayout
from memory_system.runtime_services import MemoryRuntimeServices
from artifact_system import ArtifactRepositoryService
from task_system.registry.flow_registry import TaskFlowRegistry
from task_system.compiler.coordination_graph_models import TaskGraphRuntimeSpec
from task_system.graphs.task_graph_models import TaskGraphDefinition
from task_system.tasks.run_models import (
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
from task_system.tasks.spec_models import TaskSpec
from task_system.tasks.step_models import StepInputBinding, TaskStepBlueprint
from task_system.planning.execution_recipe_models import ExecutionRecipe, TaskValidationRule
from understanding.capability_resolution_view import capability_resolution_view

from context_system.projection.projection import (
    projection_from_bundle_answer,
)
from orchestration.commit_gate import build_assistant_session_message_commit_decision, build_task_run_final_commit_decision
from ..professional_runtime.driver import ProfessionalTaskRunDriver, ProfessionalTaskRunOutcome
from ..shared.checkpoint import RuntimeCheckpoint, RuntimeCheckpointStore
from ..coordination_runtime.flow import (
    build_coordination_flow_state,
)
from ..shared.context_manager import RuntimeContextManager
from ..shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
)
from ..shared.event_log import RuntimeEventLog
from ..shared.loop_control import RuntimeLoopLimits, check_runtime_loop_control
from ..coordination_runtime.checkpoint_adapter import LangGraphCheckpointStoreAdapter
from ..shared.runtime_object_store import RuntimeObjectStore
from .artifact_paths import (
    _artifact_repository_root_for_loop,
    _build_required_artifact_write_messages,
    _required_artifact_target_path,
    _requires_write_file_artifact,
    _validate_required_artifact_file,
    _workspace_root_from_runtime_root,
)
from ..shared.artifact_refs import ArtifactRefIndex
from ..execution.agent_delegation_executor import AgentDelegationExecutor
from ..coordination_runtime.runtime import LangGraphCoordinationRuntime, LangGraphCoordinationRuntimeResult
from ..agent_assembly import WorkOrder, build_agent_assembly_contract
from ..execution_permit import (
    append_approval_rejection_observation,
    build_execution_permit_from_payload,
    build_pending_approval_state,
    execute_approved_tool_from_state,
    tool_instances_for_policy_and_permit,
)
from ..execution_engine import (
    ModelToolCallAccumulator,
    apply_observation_aggregation,
    append_executor_error_observation,
    append_model_answer_observation,
    append_simple_executor_event,
    artifact_success_fallback_answer_metadata,
    build_artifact_success_fallback_answer,
    build_initial_followup_messages,
    build_next_followup_messages,
    builtin_tool_lane_answer_from_observation,
    classify_delegation_goal_alignment,
    finalize_after_followup_tool_results,
    finalize_budget_exhausted_followup,
    forced_synthesis_answer_metadata,
    forced_tool_synthesis_from_available_evidence,
    handle_tool_call_requested_event,
    merge_task_spec_binding_into_delegation_payload,
    record_tool_observation_projection,
    select_final_answer_from_context,
    select_final_answer_from_task_summary_refs,
)
from ..memory.project_supervision import (
    build_runtime_status,
    ensure_project_runtime_inputs,
    latest_artifact_files_from_root,
    make_initial_project_ledger,
    make_supervision_record,
)
from ..execution.node_execution_request import NodeExecutionRequest, build_node_execution_idempotency_key
from ..graph_runtime.monitoring import (
    compact_monitor_snapshot,
    evaluate_task_graph_monitor_snapshot,
)
from ..memory.timeline_ledger import TimelineLedgerStore
from ..contracts.deliverable_validator import _protocol_leak_detected
from ..shared.protocol_boundary import is_internal_protocol_input_key
from .dispatch_plan_compiler import (
    _compile_agent_dispatch_plan_from_graph_payload,
    _dispatch_edges_from_payload,
    _dispatch_graph_payload_from_task_graph_runtime_spec,
    _normalize_runtime_graph_payload,
)
from .quality_gates import (
    _artifact_policy_from_task_execution_assembly,
    _model_stream_policy_from_task_execution_assembly,
    _safe_int,
)
from permissions import build_model_response_runtime_adoption, build_runtime_capability_state
from ..shared.models import (
    AgentHandoffEnvelope,
    AgentRun,
    CoordinationRun,
    ProjectProgressLedger,
    RuntimeLoopState,
    TaskRun,
)
from ..memory.observation_aggregator import ObservationAggregator
from ..shared.safety import build_task_safety_validators
from .sandbox_policy import prepare_runtime_sandbox_policy_for_turn
from ..shared.stage_projection import StageProjectionCycle
from ..memory.state_index import RuntimeStateIndex
from .finalizer import (
    CompletedCheckpointRecoveryResult,
    TaskRunFinalizer,
)
from ..memory.trace_reader import RuntimeLoopTraceReader
from ..execution.delegation_models import AgentDelegationRequest
from ..shared.tool_repetition_guard import ToolRepetitionGuard
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from agent_system.registry.worker_agent_factory import WorkerAgentFactory
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
        permission_mode_provider: Callable[[], str] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        if backend_dir is None:
            self.backend_dir = ProjectLayout.from_runtime_root(self.root_dir).backend_dir
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
        self.permission_mode_provider = permission_mode_provider
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()
        self.task_flow_registry = TaskFlowRegistry(self.backend_dir)
        self.agent_registry = AgentRegistry(self.backend_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.backend_dir)
        self.worker_agent_factory = WorkerAgentFactory(self.backend_dir)
        artifact_repository = ArtifactRepositoryService(
            _artifact_repository_root_for_loop(self.root_dir),
            workspace_root=_workspace_root_from_runtime_root(self.root_dir),
        )
        self.langgraph_coordination_runtime = LangGraphCoordinationRuntime(
            root_dir=self.root_dir,
            registry_base_dir=self.backend_dir,
            state_index=self.state_index,
            event_log=self.event_log,
            task_flow_registry=self.task_flow_registry,
            trace_reader=self,
            artifact_repository=artifact_repository,
        )
        self.artifact_ref_index = ArtifactRefIndex(self.state_index, self, artifact_repository=artifact_repository)
        self.evidence_orchestrator = evidence_orchestrator
        self.memory_runtime_services = MemoryRuntimeServices.from_runtime_root(self.root_dir)
        self.working_memory = self.memory_runtime_services.working_memory
        self.working_memory_finalizer = self.memory_runtime_services.working_memory_finalizer
        self.task_run_finalizer = TaskRunFinalizer(
            root_dir=self.root_dir,
            state_index=self.state_index,
            event_log=self.event_log,
            checkpoints=self.checkpoints,
            execution_store=self.execution_store,
            runtime_objects=self.runtime_objects,
            task_flow_registry=self.task_flow_registry,
            langgraph_coordination_runtime=self.langgraph_coordination_runtime,
            artifact_repository=artifact_repository,
        )

    def _current_permission_mode(self) -> str:
        provider = self.permission_mode_provider
        if callable(provider):
            try:
                mode = str(provider() or "").strip()
                if mode:
                    return mode
            except Exception:
                return "default"
        return "default"

    def list_session_traces(self, session_id: str) -> dict[str, Any]:
        return self.trace_reader.list_session_task_runs(session_id)

    def list_global_live_monitor(self, limit: int = 20) -> dict[str, Any]:
        return self.trace_reader.list_global_live_monitor(limit=limit)

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

    async def resolve_pending_approval(
        self,
        task_run_id: str,
        *,
        decision: str,
        message: str = "",
        tool_runtime_executor: Any | None = None,
    ) -> dict[str, Any]:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            raise KeyError(task_run_id)
        checkpoint = self.checkpoints.load_latest(task_run_id)
        if checkpoint is None:
            raise ValueError("TaskRun has no checkpoint to resolve approval from")
        approval_state = dict(checkpoint.loop_state.pending_approval_state or {})
        if str(approval_state.get("status") or "") != "pending":
            raise ValueError("TaskRun has no pending approval")
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"approve", "approved", "reject", "rejected"}:
            raise ValueError("approval decision must be approve or reject")
        approved = normalized_decision in {"approve", "approved"}
        operation_id = str(approval_state.get("operation_id") or "").strip()
        directive_ref = str(approval_state.get("directive_ref") or "").strip()
        if not operation_id or not directive_ref:
            raise ValueError("pending approval is missing operation_id or directive_ref")
        resolved_at = time.time()
        resolution = {
            "decision": "approved" if approved else "rejected",
            "message": str(message or "").strip(),
            "resolved_at": resolved_at,
        }
        token = ApprovalToken(
            token_id=f"approval:{task_run_id}:{uuid.uuid4().hex[:8]}",
            operation_id=operation_id,
            directive_ref=directive_ref,
            granted=approved,
            source="runtime_approval_api",
        )
        next_approval_state = {
            **approval_state,
            "status": "approved" if approved else "rejected",
            "resolution": resolution,
            "approval_token": {
                "token_id": token.token_id,
                "operation_id": token.operation_id,
                "directive_ref": token.directive_ref,
                "granted": token.granted,
                "source": token.source,
            },
        }
        resumed_event = self.event_log.append(
            task_run_id,
            "approval_resumed",
            payload={
                "approval": next_approval_state,
                "decision": resolution["decision"],
                "operation_id": operation_id,
                "directive_ref": directive_ref,
            },
            refs={
                "operation_id": operation_id,
                "directive_ref": directive_ref,
                "approval_token_ref": token.token_id,
            },
        )
        if approved:
            resume_result = await execute_approved_tool_from_state(
                event_log=self.event_log,
                runtime_context_manager=RuntimeContextManager(lambda **_kwargs: ""),
                task_run_id=task_run_id,
                approval_state=approval_state,
                approval_token=token,
                tool_runtime_executor=tool_runtime_executor,
                operation_gate=self.operation_gate,
                permission_mode=self._current_permission_mode(),
                root_dir=self.root_dir,
                execution_store=self.execution_store,
                record_execution_event=self._record_execution_event,
            )
            next_approval_state = {
                **next_approval_state,
                "resume_result": resume_result,
            }
            final_status = "completed" if resume_result.get("executed") else "blocked"
            terminal_reason = "completed" if resume_result.get("executed") else "blocked_by_gate"
        else:
            resume_result = {
                "executed": False,
                "rejected": True,
                "reason": str(message or "").strip() or "approval rejected",
            }
            append_approval_rejection_observation(
                event_log=self.event_log,
                runtime_context_manager=RuntimeContextManager(lambda **_kwargs: ""),
                task_run_id=task_run_id,
                approval_state=approval_state,
                directive_ref=directive_ref,
                reason=resume_result["reason"],
                resolution=resolution,
            )
            final_status = "blocked"
            terminal_reason = "blocked_by_gate"
        resolved_state = RuntimeLoopState(
            task_run_id=checkpoint.loop_state.task_run_id,
            status=final_status,  # type: ignore[arg-type]
            turn_count=checkpoint.loop_state.turn_count,
            step_count=checkpoint.loop_state.step_count,
            current_step_id=checkpoint.loop_state.current_step_id,
            agent_id=checkpoint.loop_state.agent_id,
            agent_profile_id=checkpoint.loop_state.agent_profile_id,
            runtime_lane=checkpoint.loop_state.runtime_lane,
            task_agent_binding_ref=checkpoint.loop_state.task_agent_binding_ref,
            task_template_id=checkpoint.loop_state.task_template_id,
            task_spec_ref=checkpoint.loop_state.task_spec_ref,
            task_result_ref=checkpoint.loop_state.task_result_ref,
            skill_workflow_ref=checkpoint.loop_state.skill_workflow_ref,
            health_issue_ref=checkpoint.loop_state.health_issue_ref,
            transition="continue_after_approval",
            terminal_reason=terminal_reason,  # type: ignore[arg-type]
            messages_ref=checkpoint.loop_state.messages_ref,
            context_snapshot_ref=checkpoint.loop_state.context_snapshot_ref,
            memory_state_ref=checkpoint.loop_state.memory_state_ref,
            projection_ref=checkpoint.loop_state.projection_ref,
            prompt_manifest_ref=checkpoint.loop_state.prompt_manifest_ref,
            pending_action_requests=(),
            pending_approval_state=next_approval_state,
            denial_tracking_state=checkpoint.loop_state.denial_tracking_state,
            token_pressure=checkpoint.loop_state.token_pressure,
            compaction_state=checkpoint.loop_state.compaction_state,
            result_refs=tuple(
                _dedupe_refs(
                    [
                        *list(checkpoint.loop_state.result_refs),
                        *list(resume_result.get("result_refs") or []),
                    ]
                )
            ),
            commit_state=checkpoint.loop_state.commit_state,
            diagnostics={
                **dict(checkpoint.loop_state.diagnostics),
                "approval_resolution": resolution,
                "approval_resume_result": resume_result,
            },
        )
        checkpoint_event = self._write_checkpoint_event(resolved_state, event_offset=resumed_event.offset)
        self._upsert_task_run_runtime_state(
            task_run=task_run,
            status=final_status,
            terminal_reason=terminal_reason,
            latest_event_offset=checkpoint_event.offset,
            latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
            diagnostics={
                "pending_approval_state": next_approval_state,
                "approval_resolution": resolution,
                "approval_resume_result": resume_result,
            },
        )
        return {
            "authority": "orchestration.runtime_approval_resolution",
            "task_run_id": task_run_id,
            "decision": resolution["decision"],
            "approval": next_approval_state,
            "resume_result": resume_result,
            "events": [resumed_event.to_dict(), checkpoint_event.to_dict()],
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
        model_selection: dict[str, Any] | None = None,
    ):
        """Run the current single-agent lane inside the TaskRunLoop trace spine."""

        assembly_contract = _assembly_contract_from_task_selection(task_selection)
        runtime_chain_task_selection = dict(task_selection or {})
        if assembly_contract:
            runtime_chain_task_selection["agent_assembly_contract"] = dict(assembly_contract)
            runtime_chain_task_selection["assembly_id"] = str(assembly_contract.get("assembly_id") or "")
            runtime_chain_task_selection["work_order_id"] = str(assembly_contract.get("work_order_id") or "")
            runtime_chain_task_selection["executor_type"] = str(assembly_contract.get("executor_type") or "")
        allowed_search_sources = _resolve_runtime_search_sources(
            search_policy=search_policy,
            task_selection=runtime_chain_task_selection,
        )
        chain_runtime = agent_runtime_chain.build_runtime(
            session_id=session_id,
            task_id=task_id,
            turn_id=str(dict(runtime_chain_task_selection or {}).get("turn_id") or ""),
            message=user_message,
            source=source,
            current_turn_context_override=dict(runtime_chain_task_selection or {}),
            task_selection={
                **dict(runtime_chain_task_selection or {}),
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
        if assembly_contract:
            agent_runtime_spec_payload = _agent_runtime_spec_with_assembly_contract(
                agent_runtime_spec_payload,
                assembly_contract,
            )
            task_operation["agent_runtime_spec"] = agent_runtime_spec_payload
            task_operation["agent_assembly_contract"] = assembly_contract
        execution_permit = _execution_permit_from_assembly_contract(assembly_contract)
        if execution_permit:
            task_operation["execution_permit"] = execution_permit
        effective_agent_runtime_profile = agent_runtime_profile or self.agent_runtime_registry.get_profile(
            str(agent_runtime_spec_payload.get("agent_id") or "").strip()
        )
        effective_agent_profile_id = str(agent_runtime_spec_payload.get("agent_profile_id") or "").strip()
        if not effective_agent_profile_id:
            effective_agent_profile_id = str(
                getattr(effective_agent_runtime_profile, "agent_profile_id", "")
                or _agent_profile_id_for_runtime_spec(
                    self.agent_runtime_registry,
                    agent_runtime_spec_payload,
                )
                or "main_interactive_agent"
            )
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
            agent_profile_id=effective_agent_profile_id,
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
                "agent_assembly_contract": _assembly_contract_diagnostics(assembly_contract),
                "execution_permit": _execution_permit_diagnostics(execution_permit),
                **_stage_execution_request_diagnostics(dict(task_selection or {})),
            },
        )
        state = start.loop_state
        sandbox_policy = prepare_runtime_sandbox_policy_for_turn(
            root_dir=self.root_dir,
            session_id=session_id,
            task_run_id=state.task_run_id,
            task_contract=task_contract,
            user_message=user_message,
            selected_recipe_payload=selected_recipe_payload,
            task_selection=dict(task_selection or {}),
            state_index=self.state_index,
            event_log=self.event_log,
        )
        if sandbox_policy.get("enabled") is True:
            sandbox_event = self.event_log.append(
                state.task_run_id,
                "runtime_sandbox_prepared",
                payload={
                    "sandbox_policy": sandbox_policy,
                    "scope": "tool_layer_side_effect_isolation",
                    "real_workspace_access": str(sandbox_policy.get("real_workspace_access") or "read_only"),
                },
                refs={
                    "sandbox_root_ref": str(sandbox_policy.get("sandbox_root") or ""),
                    "task_contract_ref": str(task_contract.get("task_id") or task_id),
                },
            )
            yield {"type": "runtime_loop_event", "event": sandbox_event.to_dict()}
        search_policy_event = self.event_log.append(
            state.task_run_id,
            "search_policy_resolved",
            payload={
                "search_policy": list(search_policy) if search_policy is not None else None,
                "allowed_sources": sorted(allowed_search_sources),
                "sandbox_policy": sandbox_policy,
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
                "agent_assembly_contract": assembly_contract,
                "execution_permit": execution_permit,
                "task_run_ledger": runtime_task_ledger.to_dict() if runtime_task_ledger is not None else {},
                "sandbox_policy": sandbox_policy,
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
                "agent_assembly_contract_ref": str(assembly_contract.get("assembly_id") or ""),
                "work_order_ref": str(assembly_contract.get("work_order_id") or ""),
                "execution_permit_ref": str(execution_permit.get("permit_id") or ""),
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
                    node_work_order=dict(dict(initial_coordination_state or {}).get("node_work_order") or {}),
                    agent_assembly_contract=dict(dict(initial_coordination_state or {}).get("agent_assembly_contract") or {}),
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
        if _is_professional_task_run_recipe(selected_recipe_payload):
            model_stream_policy = {
                **model_stream_policy,
                "model_response_timeout_seconds": max(
                    float(model_stream_policy.get("model_response_timeout_seconds") or 0),
                    240.0,
                ),
                "non_stream_fallback_timeout_seconds": max(
                    float(model_stream_policy.get("non_stream_fallback_timeout_seconds") or 0),
                    240.0,
                ),
            }
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
            for trace_event in _intent_continuation_trace_events(current_turn_context):
                trace_record = self.event_log.append(
                    state.task_run_id,
                    trace_event["event_type"],
                    payload=dict(trace_event.get("payload") or {}),
                    refs={"task_contract_ref": task_contract_ref},
                )
                yield {"type": "runtime_loop_event", "event": trace_record.to_dict()}
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
            agent_runtime_profile=effective_agent_runtime_profile,
            sandbox_policy=sandbox_policy,
        )
        resolved_model_spec = None
        model_resolution: dict[str, Any] = {}
        settings_service = getattr(getattr(model_response_executor, "model_runtime", None), "settings_service", None)
        if settings_service is not None:
            model_requirement = dict(
                dict(task_execution_assembly_payload.get("contract_bindings") or {}).get("runtime") or {}
            ).get("model_requirement")
            graph_runtime_defaults = _chat_model_selection_runtime_defaults(model_selection)
            resolved_model_spec = ModelProfileResolver(settings_service).resolve_model_spec(
                agent_runtime_profile=effective_agent_runtime_profile,
                model_requirement=dict(model_requirement) if isinstance(model_requirement, dict) else {},
                runtime_lane=str(agent_runtime_spec_payload.get("runtime_lane") or ""),
                graph_runtime_defaults=graph_runtime_defaults,
            )
            model_resolution = resolved_model_spec.to_public_dict()
            model_resolution_event = self.event_log.append(
                state.task_run_id,
                "model_profile_resolved",
                payload={"model_resolution": model_resolution},
                refs={
                    "task_contract_ref": task_contract_ref,
                    "agent_profile_ref": str(getattr(effective_agent_runtime_profile, "agent_profile_id", "") or ""),
                },
            )
            yield {"type": "runtime_loop_event", "event": model_resolution_event.to_dict()}
        task_safety_envelope = dict(dict(task_operation.get("operation_requirement") or {}).get("metadata") or {}).get(
            "safety_envelope",
            {},
        )
        task_safety_validators = build_task_safety_validators(
            root_dir=self.root_dir,
            safety_envelope=task_safety_envelope,
            sandbox_policy=sandbox_policy,
        )
        runtime_tool_instances = tool_instances_for_policy_and_permit(
            tool_instances=tool_instances,
            resource_policy=resource_policy,
            definitions_by_name=self.tool_authorization_index.definitions_by_name,
            normalize_operation_id=self.operation_gate.registry.normalize_id,
            allowed_search_sources=allowed_search_sources,
            sandbox_policy=sandbox_policy,
            execution_permit=execution_permit,
        )
        runtime_capability_state = build_runtime_capability_state(
            task_operation,
            resource_policy=resource_policy,
            agent_runtime_profile=effective_agent_runtime_profile,
            visible_tool_names=[
                str(getattr(tool, "name", "") or "")
                for tool in list(runtime_tool_instances)
                if str(getattr(tool, "name", "") or "")
            ],
            sandbox_policy=sandbox_policy,
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
            finished = self.task_run_finalizer.upsert_finished_task_run(
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
                "sandbox_policy": sandbox_policy,
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
            "sandbox_policy": sandbox_policy,
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
                permission_mode=self._current_permission_mode(),
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
            finished = self.task_run_finalizer.upsert_finished_task_run(
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
            final_content = select_final_answer_from_context(final_main_context)
            if not final_content:
                final_content = str(
                    final_main_context.get("resolved_answer")
                    or final_main_context.get("canonical_answer")
                    or ""
                )
            if not final_content and final_task_summary_refs:
                final_content = select_final_answer_from_task_summary_refs(final_task_summary_refs)
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
        tool_call_accumulator = ModelToolCallAccumulator()
        tool_messages: list[ToolMessage] = []
        tool_observation_count = 0
        executed_bundle_ordinals: list[int] = []
        tool_repetition_guard = ToolRepetitionGuard()
        repeated_tool_halt = False
        builtin_tool_lane_finalized = False
        professional_task_driver_ran = False
        if _is_professional_task_run_recipe(selected_recipe_payload):
            professional_task_driver_ran = True
            driver = ProfessionalTaskRunDriver(
                event_log=self.event_log,
                events_from_executor_event=self._events_from_executor_event,
                record_task_run_step_event=self._record_task_run_step_event,
                record_task_run_ledger_updated=self._record_task_run_ledger_updated,
                state_with_task_run_ledger=self._state_with_task_run_ledger,
                write_checkpoint_event=self._write_checkpoint_event,
            )
            outcome = ProfessionalTaskRunOutcome(
                ledger=runtime_task_ledger,
                state=state,
                result_refs=list(result_refs),
                final_content=final_content,
                final_answer_metadata=dict(final_answer_metadata),
                terminal_reason=terminal_reason,
                turn_count=0,
                model_call_count=0,
                main_context=dict(final_main_context),
                task_summary_refs=[dict(item) for item in final_task_summary_refs],
                bundle_summary_refs=[dict(item) for item in final_bundle_summary_refs],
            )
            async for event in driver.run_stream(
                outcome=outcome,
                user_message=user_message,
                task_id=task_id,
                task_operation=task_operation,
                task_contract_ref=task_contract_ref,
                selected_recipe_payload=selected_recipe_payload,
                context_snapshot=context_snapshot,
                directive=directive,
                resource_policy=resource_policy,
                model_response_executor=model_response_executor,
                runtime_context_manager=runtime_context_manager,
                model_stream_policy=model_stream_policy,
                resolved_model_spec=resolved_model_spec,
                tool_runtime_executor=tool_runtime_executor,
                runtime_tool_instances=runtime_tool_instances,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
            ):
                yield event
            runtime_task_ledger = outcome.ledger
            state = outcome.state
            result_refs = list(_dedupe_refs([*result_refs, *outcome.result_refs]))
            final_content = outcome.final_content
            final_answer_metadata = dict(outcome.final_answer_metadata)
            terminal_reason = outcome.terminal_reason
            final_main_context = dict(outcome.main_context)
            final_task_summary_refs = [dict(item) for item in outcome.task_summary_refs]
            final_bundle_summary_refs = [dict(item) for item in outcome.bundle_summary_refs]

        if not final_content and not professional_task_driver_ran:
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
                model_spec=resolved_model_spec,
            ):
                if event.get("type") == "tool_call_requested":
                    tool_call_accumulator.ingest_event(event)
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
                            aggregation, matched_ordinal = record_tool_observation_projection(
                                observation_aggregator=observation_aggregator,
                                observation_payload=observation_payload,
                                observation_ref=observation_ref,
                                current_bundle_items=current_bundle_items,
                                executed_bundle_ordinals=executed_bundle_ordinals,
                            )
                            if matched_ordinal > 0 and matched_ordinal not in executed_bundle_ordinals:
                                executed_bundle_ordinals.append(matched_ordinal)
                            if aggregation.projection.main_context or aggregation.projection.task_summary_refs:
                                (
                                    final_main_context,
                                    final_task_summary_refs,
                                    final_bundle_summary_refs,
                                ) = apply_observation_aggregation(aggregation)
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
                                builtin_tool_lane_answer_metadata = builtin_tool_lane_answer_from_observation(
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
                                builtin_tool_lane_finalized = len(tool_call_accumulator.pending_tool_calls) <= 1 and not current_bundle_items
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
                    elif runtime_event.event_type == "approval_waiting":
                        approval_state = dict(runtime_event.payload.get("approval") or {})
                        state, approval_event, checkpoint_event, _task_run = self._enter_waiting_approval(
                            task_run_id=state.task_run_id,
                            approval_state=approval_state,
                            current_state=state,
                            current_task_run=start.task_run,
                            existing_approval_event=runtime_event,
                        )
                        yield {"type": "runtime_loop_event", "event": approval_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                        yield {
                            "type": "approval_waiting",
                            "approval": approval_state,
                            "task_run_id": state.task_run_id,
                        }
                        return
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

        turn_count = 1
        model_call_count = 1
        if professional_task_driver_ran:
            turn_count = max(1, int(outcome.turn_count or 1))
            model_call_count = max(0, int(outcome.model_call_count or 0))
        followup_messages: list[Any] = []
        retrieval_followup_force_synthesis = False
        if len(tool_call_accumulator.pending_tool_calls) > 1 and terminal_reason == "completed":
            builtin_tool_lane_finalized = False
            final_content = ""
            final_answer_metadata = {}
            preserve_final_answer_metadata = False
        if tool_call_accumulator.pending_tool_calls and tool_messages and terminal_reason == "completed" and not builtin_tool_lane_finalized:
            followup_messages = build_initial_followup_messages(
                context_model_messages=list(context_snapshot.model_messages),
                tool_call_accumulator=tool_call_accumulator,
                tool_messages=tool_messages,
                user_message=user_message,
                aggregation=observation_aggregator.snapshot(),
                current_bundle_items=current_bundle_items,
                remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
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
                    finalization = finalize_budget_exhausted_followup(
                        user_message=user_message,
                        aggregation=observation_aggregator.snapshot(),
                        final_task_summary_refs=final_task_summary_refs,
                        final_main_context=final_main_context,
                        control_message=followup_control.message,
                        tool_observation_count=tool_observation_count,
                    )
                    final_content = finalization.content
                    final_answer_metadata = dict(finalization.answer_metadata or {})
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
            next_tool_call_accumulator = ModelToolCallAccumulator()
            next_tool_messages: list[ToolMessage] = []
            async for event in model_response_executor.stream(
                user_message=user_message,
                model_messages=followup_messages,
                directive=directive,
                tool_instances=runtime_tool_instances,
                model_stream_policy=model_stream_policy,
                model_spec=resolved_model_spec,
            ):
                if event.get("type") == "tool_call_requested":
                    next_tool_call_accumulator.ingest_event(event)
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
                            aggregation, matched_ordinal = record_tool_observation_projection(
                                observation_aggregator=observation_aggregator,
                                observation_payload=observation_payload,
                                observation_ref=observation_ref,
                                current_bundle_items=current_bundle_items,
                                executed_bundle_ordinals=executed_bundle_ordinals,
                            )
                            if matched_ordinal > 0 and matched_ordinal not in executed_bundle_ordinals:
                                executed_bundle_ordinals.append(matched_ordinal)
                            (
                                final_main_context,
                                final_task_summary_refs,
                                final_bundle_summary_refs,
                            ) = apply_observation_aggregation(observation_aggregator.snapshot())
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
                    elif runtime_event.event_type == "approval_waiting":
                        approval_state = dict(runtime_event.payload.get("approval") or {})
                        state, approval_event, checkpoint_event, _task_run = self._enter_waiting_approval(
                            task_run_id=state.task_run_id,
                            approval_state=approval_state,
                            current_state=state,
                            current_task_run=start.task_run,
                            existing_approval_event=runtime_event,
                        )
                        yield {"type": "runtime_loop_event", "event": approval_event.to_dict()}
                        yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                        yield {
                            "type": "approval_waiting",
                            "approval": approval_state,
                            "task_run_id": state.task_run_id,
                        }
                        return
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
                next_tool_call_accumulator.pending_tool_calls
                and next_tool_messages
                and terminal_reason == "completed"
                and tool_observation_count > 0
                and _is_retrieval_task_mode(str(task_spec_payload.get("task_mode") or ""))
            ):
                retrieval_followup_force_synthesis = True
            if next_tool_call_accumulator.pending_tool_calls and next_tool_messages and terminal_reason == "completed":
                finalization = finalize_after_followup_tool_results(
                    user_message=user_message,
                    aggregation=observation_aggregator.snapshot(),
                    final_task_summary_refs=final_task_summary_refs,
                    final_main_context=final_main_context,
                    repeated_tool_halt=repeated_tool_halt,
                    final_content=final_content,
                    tool_observation_count=tool_observation_count,
                    retrieval_followup_force_synthesis=retrieval_followup_force_synthesis,
                )
                if finalization.finalized:
                    final_content = finalization.content
                    if finalization.answer_metadata is not None:
                        final_answer_metadata = dict(finalization.answer_metadata)
                    followup_messages = []
                    break
                followup_messages = build_next_followup_messages(
                    previous_messages=followup_messages,
                    tool_call_accumulator=next_tool_call_accumulator,
                    tool_messages=next_tool_messages,
                    user_message=user_message,
                    aggregation=observation_aggregator.snapshot(),
                    current_bundle_items=current_bundle_items,
                    remaining_model_calls=max(effective_limits.max_model_calls - model_call_count, 0),
                )
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
                repair_tool_call_accumulator = ModelToolCallAccumulator()
                async for event in model_response_executor.stream(
                    user_message=user_message,
                    model_messages=repair_messages,
                    directive=directive,
                    tool_instances=repair_tool_instances,
                    model_stream_policy=model_stream_policy,
                    model_spec=resolved_model_spec,
                ):
                    if event.get("type") == "tool_call_requested":
                        repair_tool_call_accumulator.ingest_event(event)
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
                        elif runtime_event.event_type == "approval_waiting":
                            approval_state = dict(runtime_event.payload.get("approval") or {})
                            state, approval_event, checkpoint_event, _task_run = self._enter_waiting_approval(
                                task_run_id=state.task_run_id,
                                approval_state=approval_state,
                                current_state=state,
                                current_task_run=start.task_run,
                                existing_approval_event=runtime_event,
                            )
                            yield {"type": "runtime_loop_event", "event": approval_event.to_dict()}
                            yield {"type": "runtime_loop_event", "event": checkpoint_event.to_dict()}
                            yield {
                                "type": "approval_waiting",
                                "approval": approval_state,
                                "task_run_id": state.task_run_id,
                            }
                            return
                        yield {"type": "runtime_loop_event", "event": runtime_event.to_dict()}
                    if event.get("type") == "done" and not repair_tool_call_accumulator.pending_tool_calls:
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
                        "tool_call_count": len(repair_tool_call_accumulator.pending_tool_calls),
                        "assistant_content_chars": len(repair_tool_call_accumulator.assistant_content),
                        "assistant_additional_kwargs": repair_tool_call_accumulator.assistant_additional_kwargs,
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
            final_content = build_artifact_success_fallback_answer(
                selected_recipe_payload=selected_recipe_payload,
                artifact_validation=artifact_validation,
                final_task_summary_refs=final_task_summary_refs,
                final_main_context=final_main_context,
            )
            final_answer_metadata = {
                **artifact_success_fallback_answer_metadata(),
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
        if current_bundle_items and final_content and not _suppress_bundle_projection_for_task_graph_node(
            current_turn_context=dict(current_turn_context or {}),
            selected_recipe_payload=selected_recipe_payload,
        ):
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
                ) = apply_observation_aggregation(aggregation)
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
            finished = self.task_run_finalizer.upsert_finished_task_run(
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

    def recover_completed_checkpoint_task_run(
        self,
        *,
        task_run_id: str,
        current_turn_context: dict[str, Any] | None = None,
        user_message: str = "",
    ) -> CompletedCheckpointRecoveryResult:
        task_run = self.state_index.get_task_run(task_run_id)
        if task_run is None:
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="missing_task_run",
                task_run_id=task_run_id,
            )
        checkpoint = self.checkpoints.load_latest(task_run_id)
        if checkpoint is None:
            return CompletedCheckpointRecoveryResult(
                recovered=False,
                reason="missing_checkpoint",
                task_run_id=task_run_id,
            )
        return self.task_run_finalizer.recover_completed_checkpoint_task_run(
            task_run=task_run,
            checkpoint=checkpoint,
            current_turn_context=current_turn_context,
            user_message=user_message,
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
        assembly_contract = _assembly_contract_from_continuation_payload(
            continuation_payload,
            base_dir=self.backend_dir,
        )
        if assembly_contract:
            next_turn_context["agent_assembly_contract"] = assembly_contract
        if not next_task_ref or not next_message:
            return
        stage_agent_id = str(assembly_contract.get("agent_id") or next_turn_context.get("agent_id") or "").strip()
        stage_agent_profile_id = str(assembly_contract.get("agent_profile_id") or next_turn_context.get("agent_profile_id") or "").strip()
        stage_runtime_lane = str(assembly_contract.get("runtime_lane") or next_turn_context.get("runtime_lane") or "").strip()
        if stage_agent_id:
            next_turn_context["agent_id"] = stage_agent_id
        if stage_agent_profile_id:
            next_turn_context["agent_profile_id"] = stage_agent_profile_id
        if stage_runtime_lane:
            next_turn_context["runtime_lane"] = stage_runtime_lane
        stage_agent_runtime_profile = None
        if stage_agent_id:
            stage_agent_runtime_profile = self.agent_runtime_registry.get_profile(stage_agent_id)
            if stage_agent_runtime_profile is None:
                raise ValueError(f"TaskGraph node agent has no runtime profile: {stage_agent_id}")
        stage_request = dict(next_turn_context.get("stage_execution_request") or continuation_payload.get("stage_execution_request") or {})
        standard_input_materials = _render_standard_input_package_for_model(stage_request)
        if standard_input_materials and standard_input_materials not in next_message:
            next_message = f"{next_message}\n\n{standard_input_materials}"
        turn_marker = str(next_turn_context.get("turn_id") or "").strip() or _stable_stage_turn_id(
            session_id=session_id,
            task_ref=next_task_ref,
            stage_request=stage_request,
        )
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
                    "agent_profile_id",
                    "projection_id",
                    "selected_projection_id",
                    "runtime_lane",
                    "runtime_limits",
                    "agent_group_id",
                    "artifact_root",
                    "workspace_root",
                    "explicit_inputs",
                    "a2a_payload",
                    "stage_execution_request",
                    "node_work_order",
                    "agent_assembly_contract",
                    "coordination_run_id",
                    "continuation_stage_id",
                }
            },
        }
        if assembly_contract:
            task_selection.update(
                {
                    "agent_assembly_contract": assembly_contract,
                    "agent_id": stage_agent_id,
                    "agent_profile_id": stage_agent_profile_id,
                    "runtime_lane": stage_runtime_lane,
                    "work_order_id": str(assembly_contract.get("work_order_id") or ""),
                    "assembly_id": str(assembly_contract.get("assembly_id") or ""),
                    "executor_type": str(assembly_contract.get("executor_type") or ""),
                }
            )
        async for event in self.run_single_agent_stream(
            session_id=session_id,
            task_id=next_task_id,
            user_message=next_message,
            history=list(history or []),
            source=source,
            agent_runtime_chain=_ContinuationAgentRuntimeChain(
                base=_ContinuationAgentRuntimeChain.unwrap(agent_runtime_chain),
                forced_turn_context=next_turn_context,
                assembly_contract=assembly_contract,
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

    def _upsert_task_run_runtime_state(
        self,
        *,
        task_run: TaskRun,
        status: str,
        terminal_reason: str = "",
        latest_event_offset: int | None = None,
        latest_checkpoint_ref: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status=status,  # type: ignore[arg-type]
                created_at=task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=(
                    int(latest_event_offset)
                    if latest_event_offset is not None
                    else task_run.latest_event_offset
                ),
                latest_checkpoint_ref=latest_checkpoint_ref or task_run.latest_checkpoint_ref,
                terminal_reason=terminal_reason,  # type: ignore[arg-type]
                diagnostics={
                    **dict(task_run.diagnostics),
                    **dict(diagnostics or {}),
                },
            )
        )

    def _enter_waiting_approval(
        self,
        *,
        task_run_id: str,
        approval_state: dict[str, Any],
        current_state: RuntimeLoopState | None = None,
        current_task_run: TaskRun | None = None,
        event_offset: int | None = None,
        existing_approval_event: Any | None = None,
    ) -> tuple[RuntimeLoopState, Any, Any, TaskRun | None]:
        base_state = current_state
        if base_state is None:
            checkpoint = self.checkpoints.load_latest(task_run_id)
            base_state = checkpoint.loop_state if checkpoint is not None else None
        if base_state is None:
            base_state = RuntimeLoopState(task_run_id=task_run_id, status="running")
        waiting_state = RuntimeLoopState(
            task_run_id=base_state.task_run_id,
            status="waiting_approval",
            turn_count=base_state.turn_count,
            step_count=base_state.step_count,
            current_step_id=base_state.current_step_id,
            agent_id=base_state.agent_id,
            agent_profile_id=base_state.agent_profile_id,
            runtime_lane=base_state.runtime_lane,
            task_agent_binding_ref=base_state.task_agent_binding_ref,
            task_template_id=base_state.task_template_id,
            task_spec_ref=base_state.task_spec_ref,
            task_result_ref=base_state.task_result_ref,
            skill_workflow_ref=base_state.skill_workflow_ref,
            health_issue_ref=base_state.health_issue_ref,
            transition=base_state.transition,
            terminal_reason="waiting_approval",
            messages_ref=base_state.messages_ref,
            context_snapshot_ref=base_state.context_snapshot_ref,
            memory_state_ref=base_state.memory_state_ref,
            projection_ref=base_state.projection_ref,
            prompt_manifest_ref=base_state.prompt_manifest_ref,
            pending_action_requests=(dict(approval_state),),
            pending_approval_state=dict(approval_state),
            denial_tracking_state=base_state.denial_tracking_state,
            token_pressure=base_state.token_pressure,
            compaction_state=base_state.compaction_state,
            result_refs=base_state.result_refs,
            commit_state=base_state.commit_state,
            diagnostics={
                **dict(base_state.diagnostics),
                "pending_approval_state": dict(approval_state),
            },
        )
        approval_event = existing_approval_event or self.event_log.append(
            task_run_id,
            "approval_waiting",
            payload={"approval": dict(approval_state)},
            refs={
                "operation_id": str(approval_state.get("operation_id") or ""),
                "directive_ref": str(approval_state.get("directive_ref") or ""),
                "action_request_ref": str(approval_state.get("action_request_ref") or ""),
            },
        )
        approval_event_offset = int(getattr(approval_event, "offset", event_offset if event_offset is not None else -1))
        checkpoint_event = self._write_checkpoint_event(
            waiting_state,
            event_offset=approval_event_offset if event_offset is None else max(event_offset, approval_event_offset),
        )
        task_run = current_task_run or self.state_index.get_task_run(task_run_id)
        if task_run is not None:
            self._upsert_task_run_runtime_state(
                task_run=task_run,
                status="waiting_approval",
                terminal_reason="waiting_approval",
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or ""),
                diagnostics={"pending_approval_state": dict(approval_state)},
            )
        return waiting_state, approval_event, checkpoint_event, task_run

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
        if _is_professional_task_run_recipe(selected_recipe_payload):
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
        if unit is not None:
            path_key = str(unit.request_path_parameter or "").strip()
            binding_key = str(unit.followup_binding_key or "").strip()
            if path_key and binding_key and binding_key != "current_turn_context":
                path = str(
                    parameters.get(path_key)
                    or _path_from_context_recall(
                        current_turn_context,
                        source_kind=str(unit.source_kind or source_kind or ""),
                        binding_key=binding_key,
                    )
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
        task_spec_payload = dict(dict(task_operation or {}).get("task_spec") or {})
        task_spec_inputs = dict(task_spec_payload.get("inputs") or {})
        agent_communication_protocol = dict(task_spec_inputs.get("agent_communication_protocol") or {})
        if agent_communication_protocol:
            input_payload.setdefault("agent_communication_protocol", agent_communication_protocol)
        input_payload = merge_task_spec_binding_into_delegation_payload(
            input_payload,
            task_spec_payload=task_spec_payload,
            current_turn_context=dict(dict(task_operation or {}).get("current_turn_context") or {}),
            user_message=user_message,
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
            "goal_alignment": classify_delegation_goal_alignment(
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
            expected_output_contract=dict(
                tool_args.get("expected_output_contract")
                or agent_communication_protocol.get("expected_output_contract")
                or {}
            ),
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
        sandbox_policy: dict[str, Any] | None = None,
    ):
        event_type = str(event.get("type") or "")
        simple_events = append_simple_executor_event(self.event_log, task_run_id, event)
        if simple_events is not None:
            return simple_events
        if event_type == "answer_candidate":
            return append_model_answer_observation(
                event_log=self.event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                event=event,
            )
        if event_type == "tool_call_requested":
            return await handle_tool_call_requested_event(
                event_log=self.event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                event=event,
                current_step_id=current_step_id,
                task_id=task_id,
                task_operation=task_operation,
                adopted_resource_policy=adopted_resource_policy,
                user_message=user_message,
                model_response_executor=model_response_executor,
                tool_runtime_executor=tool_runtime_executor,
                definitions_by_name=self.tool_authorization_index.definitions_by_name,
                operation_gate=self.operation_gate,
                permission_mode=self._current_permission_mode(),
                root_dir=self.root_dir,
                allowed_search_sources=allowed_search_sources,
                sandbox_policy=sandbox_policy,
                execution_store=self.execution_store,
                record_execution_event=self._record_execution_event,
                build_pending_approval_state=build_pending_approval_state,
                list_parent_agent_runs=self.state_index.list_task_agent_runs,
                build_delegation_request=self._build_delegation_request,
                execute_delegation=self._delegation_executor().execute,
            )
        if event_type == "error":
            return append_executor_error_observation(
                event_log=self.event_log,
                runtime_context_manager=runtime_context_manager,
                task_run_id=task_run_id,
                event=event,
            )
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


def _suppress_bundle_projection_for_task_graph_node(
    *,
    current_turn_context: dict[str, Any],
    selected_recipe_payload: dict[str, Any],
) -> bool:
    context = dict(current_turn_context or {})
    if context.get("suppress_bundle_projection") is True:
        return True
    if dict(context.get("stage_execution_request") or {}):
        return True
    if str(context.get("source") or "").startswith("codex_rewind_"):
        return True
    metadata = dict(dict(selected_recipe_payload or {}).get("metadata") or {})
    return bool(metadata.get("task_graph_node_runtime") is True or metadata.get("suppress_bundle_projection") is True)


_STANDARD_INPUT_MODEL_TEXT_LIMIT = 120_000
_STANDARD_INPUT_ITEM_TEXT_LIMIT = 24_000


def _render_standard_input_package_for_model(stage_request: dict[str, Any]) -> str:
    package = dict(dict(stage_request or {}).get("standard_input_package") or {})
    items = [dict(item) for item in list(package.get("input_items") or []) if isinstance(item, dict)]
    if not items:
        return ""

    rendered_items: list[str] = []
    total_chars = 0
    for item in items:
        input_key = str(item.get("input_key") or "").strip() or "unnamed_input"
        if is_internal_protocol_input_key(input_key):
            continue
        content_type = str(item.get("content_type") or "").strip()
        usage_instruction = str(item.get("usage_instruction") or "").strip()
        source_node_id = str(item.get("source_node_id") or "").strip()
        metadata = dict(item.get("metadata") or {})
        text = str(metadata.get("text") or "").strip()
        if not text:
            text = str(item.get("content_preview") or "").strip()
        if not text:
            continue
        if _protocol_leak_detected(text):
            text = re.sub(
                r"<\s*/?\s*(?:tool_call|invoke|read_file|search_text|search_files|delegate_to_agent)[^>]*>",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
        if len(text) > _STANDARD_INPUT_ITEM_TEXT_LIMIT:
            text = text[:_STANDARD_INPUT_ITEM_TEXT_LIMIT].rstrip() + "\n\n[上游材料因长度限制已截断，请只依据已展示内容继续。]"
        header_bits = [f"输入键：{input_key}"]
        if content_type:
            header_bits.append(f"类型：{content_type}")
        if source_node_id:
            header_bits.append(f"来源节点：{source_node_id}")
        if usage_instruction:
            header_bits.append(f"用途：{usage_instruction}")
        block = "\n".join(
            [
                "## " + "；".join(header_bits),
                text,
            ]
        )
        if total_chars + len(block) > _STANDARD_INPUT_MODEL_TEXT_LIMIT:
            remaining = max(_STANDARD_INPUT_MODEL_TEXT_LIMIT - total_chars, 0)
            if remaining <= 200:
                break
            block = block[:remaining].rstrip() + "\n\n[标准输入材料因总长度限制已截断。]"
        rendered_items.append(block)
        total_chars += len(block)

    if not rendered_items:
        return ""
    return "\n".join(
        [
            "# 标准节点输入材料",
            "以下内容由编排运行层预读取并展开，模型只能依据这些已展开材料工作；不得要求读取文件、调用工具或输出伪工具标签。",
            *rendered_items,
        ]
    )

def _recipe_requires_model_finalize(selected_recipe: ExecutionRecipe) -> bool:
    finalization_policy = dict(getattr(selected_recipe, "finalization_policy", {}) or {})
    if "requires_model_finalize" in finalization_policy:
        return bool(finalization_policy.get("requires_model_finalize"))
    return any(
        str(step.executor_type or "") == "model" and str(step.step_kind or "") == "finalize"
        for step in selected_recipe.step_blueprints
    )


def _is_professional_task_run_recipe(selected_recipe_payload: dict[str, Any]) -> bool:
    payload = dict(selected_recipe_payload or {})
    metadata = dict(payload.get("metadata") or {})
    return (
        str(payload.get("recipe_id") or "").strip()
        in {"runtime.recipe.role_interaction", "runtime.recipe.standard_task", "runtime.recipe.professional_task"}
        or str(metadata.get("runtime_driver") or "").strip() == "professional_task_run"
        or str(metadata.get("interaction_mode") or "").strip()
        in {"role_mode", "standard_mode", "professional_mode"}
        or str(payload.get("task_mode") or "").strip()
        in {"role_mode", "standard_mode", "professional_mode"}
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


def _intent_continuation_trace_events(current_turn_context: dict[str, Any]) -> list[dict[str, Any]]:
    context = dict(current_turn_context or {})
    intent_frame = dict(context.get("intent_frame") or {})
    intent_decision = dict(context.get("intent_decision") or {})
    runtime_assembly_hint = dict(context.get("runtime_assembly_hint") or {})
    continuation_candidates = [
        dict(item)
        for item in list(context.get("continuation_candidates") or [])
        if isinstance(item, dict)
    ]
    continuation_decision = dict(context.get("continuation_decision") or {})
    events: list[dict[str, Any]] = []
    if intent_frame:
        events.append(
            {
                "event_type": "intent_frame_built",
                "payload": {
                    "intent_frame": intent_frame,
                    "action_hypotheses": list(intent_frame.get("action_hypotheses") or []),
                    "target_domain_hints": list(intent_frame.get("target_domain_hints") or []),
                },
            }
        )
    if intent_decision:
        events.append(
            {
                "event_type": "intent_decision_made",
                "payload": {
                    "intent_decision": intent_decision,
                    "runtime_assembly_hint": runtime_assembly_hint,
                },
            }
        )
    if continuation_candidates:
        events.append(
            {
                "event_type": "continuation_candidates_built",
                "payload": {
                    "continuation_candidates": continuation_candidates,
                    "candidate_count": len(continuation_candidates),
                    "compatible_candidate_count": sum(1 for item in continuation_candidates if item.get("compatible") is True),
                },
            }
        )
    if continuation_decision:
        events.append(
            {
                "event_type": "continuation_decision_made",
                "payload": {
                    "continuation_decision": continuation_decision,
                    "selected_candidate_id": str(continuation_decision.get("selected_candidate_id") or ""),
                    "decision_kind": str(continuation_decision.get("decision_kind") or ""),
                },
            }
        )
    return events


def _stable_stage_turn_id(*, session_id: str, task_ref: str, stage_request: dict[str, Any] | None) -> str:
    request = dict(stage_request or {})
    stage_id = str(request.get("stage_id") or request.get("node_id") or task_ref.rsplit(".", 1)[-1] or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not idempotency_key and request:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=str(request.get("coordination_run_id") or ""),
            node_id=str(request.get("node_id") or stage_id),
            explicit_inputs=dict(request.get("explicit_inputs") or {}),
            dispatch_context=dict(request.get("dispatch_context") or {}),
        )
    identity = idempotency_key or str(request.get("request_id") or "").strip()
    if not identity:
        identity = f"{session_id}:{task_ref}:{uuid.uuid4().hex[:8]}"
    return f"turn:{session_id}:{_stable_stage_turn_suffix(identity)}:{_safe_task_id_component(stage_id or 'stage')}"


def _stable_stage_turn_suffix(value: str) -> str:
    import hashlib

    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]


def _safe_task_id_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip())[:80] or "stage"


def _stage_execution_request_diagnostics(selection: dict[str, Any]) -> dict[str, Any]:
    request = dict(selection.get("stage_execution_request") or {})
    if not request:
        return {}
    stage_id = str(request.get("stage_id") or request.get("node_id") or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=str(request.get("coordination_run_id") or ""),
            node_id=str(request.get("node_id") or stage_id),
            explicit_inputs=dict(request.get("explicit_inputs") or {}),
            dispatch_context=dict(request.get("dispatch_context") or {}),
        )
    return {
        "coordination_run_id": str(request.get("coordination_run_id") or ""),
        "coordination_stage_id": stage_id,
        "stage_id": stage_id,
        "node_id": str(request.get("node_id") or stage_id),
        "stage_request_id": str(request.get("request_id") or ""),
        "stage_idempotency_key": idempotency_key,
        "stage_dispatch_event_id": str(dict(request.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
        "continuation_stage_id": str(selection.get("continuation_stage_id") or stage_id),
    }


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


def _agent_profile_id_for_runtime_spec(registry: Any, runtime_spec_payload: dict[str, Any]) -> str:
    agent_id = str(runtime_spec_payload.get("agent_id") or "").strip()
    if not agent_id:
        return ""
    getter = getattr(registry, "get_profile", None)
    if not callable(getter):
        return ""
    profile = getter(agent_id)
    return str(getattr(profile, "agent_profile_id", "") or "").strip()


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


def _runtime_loop_short_hash(value: Any) -> str:
    import hashlib
    import json

    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _assembly_contract_from_continuation_payload(
    continuation_payload: dict[str, Any] | None,
    *,
    base_dir: Path,
) -> dict[str, Any]:
    payload = dict(continuation_payload or {})
    assembly = dict(payload.get("agent_assembly_contract") or {})
    if assembly:
        return assembly
    context = dict(payload.get("current_turn_context") or {})
    assembly = dict(context.get("agent_assembly_contract") or {})
    if assembly:
        return assembly
    work_order = dict(payload.get("node_work_order") or context.get("node_work_order") or {})
    if not work_order:
        return {}
    return build_agent_assembly_contract(WorkOrder.from_dict(work_order), base_dir=base_dir).to_dict()


def _assembly_contract_from_task_selection(task_selection: dict[str, Any] | None) -> dict[str, Any]:
    selection = dict(task_selection or {})
    assembly = dict(selection.get("agent_assembly_contract") or {})
    if assembly:
        return assembly
    context = dict(selection.get("current_turn_context") or {})
    assembly = dict(context.get("agent_assembly_contract") or {})
    if assembly:
        return assembly
    return {}


def _agent_runtime_spec_with_assembly_contract(
    agent_runtime_spec: dict[str, Any],
    assembly_contract: dict[str, Any],
) -> dict[str, Any]:
    spec = dict(agent_runtime_spec or {})
    for key in ("agent_id", "agent_profile_id", "runtime_lane"):
        value = str(assembly_contract.get(key) or "").strip()
        if value:
            spec[key] = value
    spec["agent_assembly_contract_id"] = str(assembly_contract.get("assembly_id") or "")
    spec["work_order_id"] = str(assembly_contract.get("work_order_id") or "")
    spec["executor_type"] = str(assembly_contract.get("executor_type") or spec.get("executor_type") or "")
    return spec


def _assembly_contract_diagnostics(assembly_contract: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(assembly_contract or {})
    if not assembly:
        return {}
    return {
        "assembly_id": str(assembly.get("assembly_id") or ""),
        "work_order_id": str(assembly.get("work_order_id") or ""),
        "work_kind": str(assembly.get("work_kind") or ""),
        "agent_id": str(assembly.get("agent_id") or ""),
        "agent_profile_id": str(assembly.get("agent_profile_id") or ""),
        "runtime_lane": str(assembly.get("runtime_lane") or ""),
        "executor_type": str(assembly.get("executor_type") or ""),
    }


def _execution_permit_from_assembly_contract(assembly_contract: dict[str, Any] | None) -> dict[str, Any]:
    return build_execution_permit_from_payload(dict(assembly_contract or {}))


def _execution_permit_diagnostics(execution_permit: dict[str, Any] | None) -> dict[str, Any]:
    permit = dict(execution_permit or {})
    if not permit:
        return {}
    return {
        "permit_id": str(permit.get("permit_id") or ""),
        "assembly_id": str(permit.get("assembly_id") or ""),
        "work_order_id": str(permit.get("work_order_id") or ""),
        "agent_id": str(permit.get("agent_id") or ""),
        "agent_profile_id": str(permit.get("agent_profile_id") or ""),
        "executor_type": str(permit.get("executor_type") or ""),
        "allowed_operations": list(permit.get("allowed_operations") or []),
        "visible_tools": list(permit.get("visible_tools") or []),
        "dispatchable_tools": list(permit.get("dispatchable_tools") or []),
    }


def _chat_model_selection_runtime_defaults(model_selection: dict[str, Any] | None) -> dict[str, Any]:
    selection = dict(model_selection or {})
    provider = str(selection.get("provider") or "").strip().lower()
    model = str(selection.get("model") or "").strip()
    base_url = str(selection.get("base_url") or "").strip()
    if not provider or not model:
        return {}
    defaults: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "credential_ref": str(selection.get("credential_ref") or f"provider:{provider}:primary").strip(),
    }
    if base_url:
        defaults["base_url"] = base_url
    return defaults


class _ContinuationAgentRuntimeChain:
    def __init__(self, *, base: Any, forced_turn_context: dict[str, Any], assembly_contract: dict[str, Any] | None = None) -> None:
        self._base = base
        self._forced_turn_context = dict(forced_turn_context or {})
        self._assembly_contract = dict(assembly_contract or self._forced_turn_context.get("agent_assembly_contract") or {})

    def build_runtime(self, **kwargs) -> dict[str, Any]:
        override = {
            **dict(kwargs.get("current_turn_context_override") or {}),
            **dict(self._forced_turn_context),
        }
        if self._assembly_contract:
            override["agent_assembly_contract"] = self._assembly_contract
        forced_agent_id = str(self._assembly_contract.get("agent_id") or self._forced_turn_context.get("agent_id") or "").strip()
        forced_agent_profile_id = str(self._assembly_contract.get("agent_profile_id") or self._forced_turn_context.get("agent_profile_id") or "").strip()
        forced_runtime_lane = str(self._assembly_contract.get("runtime_lane") or self._forced_turn_context.get("runtime_lane") or "").strip()
        if forced_agent_id:
            override["agent_id"] = forced_agent_id
        if forced_agent_profile_id:
            override["agent_profile_id"] = forced_agent_profile_id
        if forced_runtime_lane:
            override["runtime_lane"] = forced_runtime_lane
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
        if forced_agent_profile_id:
            task_selection["agent_profile_id"] = forced_agent_profile_id
        if forced_runtime_lane:
            task_selection["runtime_lane"] = forced_runtime_lane
        if self._assembly_contract:
            task_selection["agent_assembly_contract"] = self._assembly_contract
            task_selection["assembly_id"] = str(self._assembly_contract.get("assembly_id") or "")
            task_selection["work_order_id"] = str(self._assembly_contract.get("work_order_id") or "")
            task_selection["executor_type"] = str(self._assembly_contract.get("executor_type") or "")
        kwargs["task_selection"] = task_selection
        runtime = dict(self._base.build_runtime(**kwargs) or {})
        current_turn_context = {
            **dict(runtime.get("current_turn_context") or {}),
            **dict(self._forced_turn_context),
        }
        if self._assembly_contract:
            current_turn_context["agent_assembly_contract"] = self._assembly_contract
            current_turn_context["agent_id"] = forced_agent_id
            current_turn_context["agent_profile_id"] = forced_agent_profile_id
            current_turn_context["runtime_lane"] = forced_runtime_lane
        task_operation = dict(runtime.get("task_operation") or {})
        task_operation["current_turn_context"] = current_turn_context
        if self._assembly_contract:
            task_operation["agent_assembly_contract"] = self._assembly_contract
        task_spec = dict(task_operation.get("task_spec") or {})
        task_spec["inputs"] = {
            **dict(task_spec.get("inputs") or {}),
            **dict(current_turn_context.get("explicit_inputs") or {}),
        }
        task_operation["task_spec"] = task_spec
        expected_agent_id = str(self._assembly_contract.get("agent_id") or current_turn_context.get("agent_id") or "").strip()
        if expected_agent_id:
            agent_runtime_spec = dict(runtime.get("agent_runtime_spec") or task_operation.get("agent_runtime_spec") or {})
            actual_agent_id = str(agent_runtime_spec.get("agent_id") or "").strip()
            if actual_agent_id != expected_agent_id:
                raise ValueError(
                    "TaskGraph node runtime assembled with wrong agent: "
                    f"expected {expected_agent_id}, got {actual_agent_id or '<empty>'}"
                )
            if self._assembly_contract:
                agent_runtime_spec = _agent_runtime_spec_with_assembly_contract(
                    agent_runtime_spec,
                    self._assembly_contract,
                )
                runtime["agent_runtime_spec"] = agent_runtime_spec
                task_operation["agent_runtime_spec"] = agent_runtime_spec
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
