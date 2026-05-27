from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from capability_system import build_default_operation_registry
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from permissions import (
    ApprovalToken,
    OperationGate,
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
    complete_task_run_step,
    current_task_step_run,
    fail_task_run_step,
    find_task_step_run,
    next_pending_step_run,
    step_supports_operation,
)
from runtime.shared.checkpoint import RuntimeCheckpointStore
from runtime.shared.context_manager import RuntimeContextManager
from runtime.shared.execution_record import (
    OperationExecutionRecord,
    RuntimeExecutionStore,
)
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.loop_control import RuntimeLoopLimits
from harness.loop.graph_coordination.checkpoint_adapter import GraphCoordinationCheckpointStore
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.shared.artifact_paths import (
    artifact_repository_root_for_loop,
    workspace_root_from_runtime_root,
)
from runtime.shared.artifact_refs import ArtifactRefIndex
from harness.execution.agent_delegation_executor import AgentDelegationExecutor
from harness.loop.graph_coordination.engine import GraphCoordinationEngine
from harness.loop.agent_finalization import dedupe_refs as _dedupe_refs
from harness.loop.agent_lifecycle import (
    AgentRuntimeStartResult,
    build_coordination_state,
    start_agent_run,
    state_with_task_run_ledger,
    write_checkpoint_event,
)
from harness.runtime.execution_policy import (
    append_approval_rejection_observation,
    build_pending_approval_state,
    execute_approved_tool_from_state,
)
from harness.loop.agent_execution import (
    RuntimeExecutionEngine,
    build_delegation_request,
)
from runtime.memory.project_supervision import (
    build_runtime_status,
    ensure_project_runtime_inputs,
    latest_artifact_files_from_root,
    make_initial_project_ledger,
    make_supervision_record,
)
from runtime.graph_runtime.monitoring import (
    compact_monitor_snapshot,
    evaluate_task_graph_monitor_snapshot,
)
from runtime.memory.timeline_ledger import TimelineLedgerStore
from runtime.shared.dispatch_plan_compiler import (
    _compile_agent_dispatch_plan_from_graph_payload,
    _dispatch_edges_from_payload,
    _dispatch_graph_payload_from_task_graph_runtime_spec,
    _normalize_runtime_graph_payload,
)
from runtime.shared.models import (
    AgentHandoffEnvelope,
    AgentRun,
    CoordinationRun,
    ProjectProgressLedger,
    RuntimeLoopState,
    TaskRun,
)
from harness.loop.task_run_finalizer import (
    CompletedCheckpointRecoveryResult,
    TaskRunFinalizer,
)
from harness.observability import HarnessTraceReader
from harness.execution.delegation_models import AgentDelegationRequest
from agent_system.registry.worker_agent_blueprints import WorkerAgentSpawnRequest, WorkerAgentSpawnResult
from agent_system.registry.worker_agent_factory import WorkerAgentFactory

if TYPE_CHECKING:
    from runtime.memory.state_index import RuntimeStateIndex

class HarnessServiceHost:
    """Durable service host consumed by AgentLoop and GraphLoop.

    This object owns stores, event logs, registries, execution engines, and
    recovery services. It does not own the agent or graph control loop.
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
        from runtime.memory.state_index import RuntimeStateIndex

        self.state_index = RuntimeStateIndex(self.root_dir)
        self.runtime_objects = RuntimeObjectStore(self.root_dir)
        self.coordination_checkpoints = GraphCoordinationCheckpointStore(self.root_dir)
        self.timeline_ledger = TimelineLedgerStore(self.root_dir)
        self.trace_reader = HarnessTraceReader(
            self.state_index,
            self.event_log,
            self.checkpoints,
            self.coordination_checkpoints,
            self.timeline_ledger,
        )
        self.evidence_orchestrator = evidence_orchestrator
        self.operation_gate = operation_gate or OperationGate(build_default_operation_registry())
        self.permission_mode_provider = permission_mode_provider
        self.limits = limits or RuntimeLoopLimits()
        self.tool_authorization_index = self._build_tool_authorization_index()
        self.execution_engine = RuntimeExecutionEngine(
            event_log=self.event_log,
            definitions_by_name=self.tool_authorization_index.definitions_by_name,
            operation_gate=self.operation_gate,
            permission_mode_provider=self._current_permission_mode,
            root_dir=self.root_dir,
            execution_store=self.execution_store,
            record_execution_event=self._record_execution_event,
            build_pending_approval_state=build_pending_approval_state,
            list_parent_agent_runs=self.state_index.list_task_agent_runs,
            build_delegation_request=self._build_delegation_request,
            execute_delegation=self._delegation_executor().execute,
        )
        self.task_flow_registry = TaskFlowRegistry(self.backend_dir)
        self.agent_registry = AgentRegistry(self.backend_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.backend_dir)
        self.worker_agent_factory = WorkerAgentFactory(self.backend_dir)
        artifact_repository = ArtifactRepositoryService(
            artifact_repository_root_for_loop(self.root_dir),
            workspace_root=workspace_root_from_runtime_root(self.root_dir),
        )
        self.graph_coordination_engine = GraphCoordinationEngine(
            root_dir=self.root_dir,
            registry_base_dir=self.backend_dir,
            state_index=self.state_index,
            event_log=self.event_log,
            task_flow_registry=self.task_flow_registry,
            trace_reader=self,
            artifact_repository=artifact_repository,
        )
        self.artifact_ref_index = ArtifactRefIndex(self.state_index, self, artifact_repository=artifact_repository)
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
            graph_coordination_engine=self.graph_coordination_engine,
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
        approval_risk_fingerprint = str(
            approval_state.get("approval_risk_fingerprint")
            or dict(approval_state.get("resume_contract") or {}).get("risk_fingerprint")
            or ""
        ).strip()
        token = ApprovalToken(
            token_id=f"approval:{task_run_id}:{uuid.uuid4().hex[:8]}",
            operation_id=operation_id,
            directive_ref=directive_ref,
            granted=approved,
            source="runtime_approval_api",
            risk_fingerprint=approval_risk_fingerprint,
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
                "risk_fingerprint": token.risk_fingerprint,
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
        runtime_lane: str = "standard_task",
        task_agent_binding_ref: str = "",
        skill_workflow_ref: str = "",
        health_issue_ref: str = "",
        execution_mode: str = "single_agent",
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
    ) -> AgentRuntimeStartResult:
        return start_agent_run(
            self,
            session_id=session_id,
            task_id=task_id,
            task_contract_ref=task_contract_ref,
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            runtime_lane=runtime_lane,
            task_agent_binding_ref=task_agent_binding_ref,
            skill_workflow_ref=skill_workflow_ref,
            health_issue_ref=health_issue_ref,
            execution_mode=execution_mode,
            graph_ref=graph_ref,
            graph_payload=graph_payload,
            topology_template_payload=topology_template_payload,
            coordinator_agent_id=coordinator_agent_id,
            topology_template_id=topology_template_id,
            communication_protocol_id=communication_protocol_id,
            handoff_policy=handoff_policy,
            failure_policy=failure_policy,
            merge_policy=merge_policy,
            runtime_assembly=runtime_assembly,
            diagnostics=diagnostics,
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
    ) -> AgentRuntimeStartResult:
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
            execution_mode="task_graph_runtime",
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
        if not self.graph_coordination_engine.supports(start.coordination_run):
            raise RuntimeError(
                "TaskGraph coordination run is missing LangGraph stage contracts; legacy initialization fallback was removed."
            )
        initialized = self.graph_coordination_engine.initialize(
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
                    "graph_coordination_initialized": True,
                    "graph_coordination_checkpoint_ref": initialized.checkpoint_ref,
                    "stage_execution_request": (
                        initialized.stage_execution_request.to_dict()
                        if initialized.stage_execution_request is not None
                        else {}
                    ),
                    "node_work_order": dict(initialized.node_work_order or {}),
                },
            }
        )
        latest_initialization_event_offset = start.checkpoint.event_offset
        for item in events:
            try:
                latest_initialization_event_offset = max(
                    latest_initialization_event_offset,
                    int(dict(item).get("offset") or latest_initialization_event_offset),
                )
            except (TypeError, ValueError):
                continue
        initialization_checkpoint_event = self._write_checkpoint_event(
            state,
            event_offset=latest_initialization_event_offset,
        )
        events.append(initialization_checkpoint_event.to_dict())
        refreshed_checkpoint = self.checkpoints.load_latest(start.task_run.task_run_id) or start.checkpoint
        checkpoint_ref = str(initialization_checkpoint_event.refs.get("checkpoint_ref") or refreshed_checkpoint.checkpoint_id)
        refreshed_task_run = self.state_index.get_task_run(start.task_run.task_run_id) or refreshed_task_run
        refreshed_task_run = TaskRun(
            task_run_id=refreshed_task_run.task_run_id,
            session_id=refreshed_task_run.session_id,
            task_id=refreshed_task_run.task_id,
            task_contract_ref=refreshed_task_run.task_contract_ref,
            owner_agent_seat_id=refreshed_task_run.owner_agent_seat_id,
            agent_id=refreshed_task_run.agent_id,
            agent_profile_id=refreshed_task_run.agent_profile_id,
            runtime_lane=refreshed_task_run.runtime_lane,
            status=refreshed_task_run.status,
            created_at=refreshed_task_run.created_at,
            updated_at=time.time(),
            latest_event_offset=initialization_checkpoint_event.offset,
            latest_checkpoint_ref=checkpoint_ref,
            terminal_reason=refreshed_task_run.terminal_reason,
            diagnostics=dict(refreshed_task_run.diagnostics),
        )
        self.state_index.upsert_task_run(refreshed_task_run)
        project_id = str(effective_initial_inputs.get("project_id") or "").strip()
        if project_id:
            ledger = self.state_index.get_project_progress_ledger(project_id)
            if ledger is None:
                ledger = make_initial_project_ledger(
                    project_id=project_id,
                    session_id=session_id,
                    graph_id=graph.graph_id,
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
        return AgentRuntimeStartResult(
            task_run=refreshed_task_run,
            agent_run=start.agent_run,
            coordination_run=refreshed_coordination_run,
            loop_state=state,
            checkpoint=refreshed_checkpoint,
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
        return write_checkpoint_event(self, state, event_offset=event_offset)

    def _apply_tool_result_step_transition(
        self,
        *,
        state: RuntimeLoopState,
        runtime_task_ledger: TaskRunLedger | None,
        result_refs: list[str],
        operation_id: str,
        observation_ref: str,
        observation_payload: dict[str, Any],
        reason: str,
        diagnostics: dict[str, Any] | None = None,
        emit_entered_step: bool = True,
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None, list[Any]]:
        if runtime_task_ledger is None:
            return state, runtime_task_ledger, []
        current_step = current_task_step_run(runtime_task_ledger)
        if (
            current_step is None
            or current_step.status != "running"
            or current_step.executor_type not in {"tool", "mcp", "agent"}
            or not step_supports_operation(current_step, operation_id)
        ):
            return state, runtime_task_ledger, []

        transition_diagnostics = {
            "transition_reason": reason,
            "operation_id": operation_id,
            **dict(diagnostics or {}),
        }
        runtime_task_ledger = complete_task_run_step(
            runtime_task_ledger,
            step_id=current_step.step_id,
            completed_at=time.time(),
            observation_refs=(observation_ref,),
            output_refs=(observation_ref,),
            step_result_ref=observation_ref,
            executor_ref=str(observation_payload.get("tool_name") or operation_id),
            diagnostics=transition_diagnostics,
        )
        events: list[Any] = []
        completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
        if completed_step is not None:
            events.append(
                self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_completed",
                    step_run=completed_step,
                    ledger=runtime_task_ledger,
                    reason=reason,
                    refs={"operation_id": operation_id, "observation_ref": observation_ref},
                )
            )
        runtime_task_ledger = advance_task_run_ledger(
            runtime_task_ledger,
            started_at=time.time(),
            diagnostics=transition_diagnostics,
        )
        ledger_event = self._record_task_run_ledger_updated(
            state.task_run_id,
            ledger=runtime_task_ledger,
            reason=reason,
            refs={"operation_id": operation_id, "observation_ref": observation_ref},
        )
        events.append(ledger_event)
        entered_step = current_task_step_run(runtime_task_ledger)
        if emit_entered_step and entered_step is not None and entered_step.step_id != current_step.step_id:
            events.append(
                self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered_step,
                    ledger=runtime_task_ledger,
                    reason=reason,
                    refs={"operation_id": operation_id, "observation_ref": observation_ref},
                )
            )
        state = self._state_with_task_run_ledger(
            state,
            runtime_task_ledger,
            result_refs=result_refs,
            diagnostics={"last_step_transition": reason},
        )
        events.append(self._write_checkpoint_event(state, event_offset=ledger_event.offset))
        return state, runtime_task_ledger, events

    def _apply_tool_call_step_transition(
        self,
        *,
        state: RuntimeLoopState,
        runtime_task_ledger: TaskRunLedger | None,
        result_refs: list[str],
        operation_id: str,
        action_request_ref: str,
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None, list[Any]]:
        if runtime_task_ledger is None:
            return state, runtime_task_ledger, []
        current_step = current_task_step_run(runtime_task_ledger)
        next_step = next_pending_step_run(
            runtime_task_ledger,
            start_after_step_id=current_step.step_id if current_step is not None else "",
        )
        if (
            current_step is None
            or current_step.status != "running"
            or current_step.executor_type != "model"
            or current_step.step_kind != "understand"
            or next_step is None
        ):
            return state, runtime_task_ledger, []

        diagnostics = {
            "transition_reason": "tool_call_requested",
            "operation_id": operation_id,
        }
        runtime_task_ledger = complete_task_run_step(
            runtime_task_ledger,
            step_id=current_step.step_id,
            completed_at=time.time(),
            output_refs=(action_request_ref,),
            executor_ref=operation_id or current_step.executor_ref,
            diagnostics=diagnostics,
        )
        events: list[Any] = []
        completed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
        if completed_step is not None:
            events.append(
                self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_completed",
                    step_run=completed_step,
                    ledger=runtime_task_ledger,
                    reason="tool_call_requested",
                    refs={"operation_id": operation_id},
                )
            )
        runtime_task_ledger = advance_task_run_ledger(
            runtime_task_ledger,
            started_at=time.time(),
            diagnostics=diagnostics,
        )
        entered_step = current_task_step_run(runtime_task_ledger)
        ledger_event = self._record_task_run_ledger_updated(
            state.task_run_id,
            ledger=runtime_task_ledger,
            reason="tool_call_requested",
            refs={"operation_id": operation_id},
        )
        events.append(ledger_event)
        if entered_step is not None and entered_step.step_id != current_step.step_id:
            events.append(
                self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_entered",
                    step_run=entered_step,
                    ledger=runtime_task_ledger,
                    reason="tool_call_requested",
                    refs={"operation_id": operation_id},
                )
            )
        state = self._state_with_task_run_ledger(
            state,
            runtime_task_ledger,
            result_refs=result_refs,
            diagnostics={"last_step_transition": "tool_call_requested"},
        )
        events.append(self._write_checkpoint_event(state, event_offset=ledger_event.offset))
        return state, runtime_task_ledger, events

    def _apply_failed_step_transition(
        self,
        *,
        state: RuntimeLoopState,
        runtime_task_ledger: TaskRunLedger | None,
        reason: str,
        failure_reason: str,
        refs: dict[str, str] | None = None,
        diagnostics: dict[str, Any] | None = None,
        ledger_diagnostics: dict[str, Any] | None = None,
        result_refs: list[str] | tuple[str, ...] | None = None,
        observation_refs: tuple[str, ...] = (),
        output_refs: tuple[str, ...] = (),
        step_result_ref: str = "",
        executor_ref: str = "",
        allowed_executor_types: set[str] | None = None,
    ) -> tuple[RuntimeLoopState, TaskRunLedger | None, list[Any]]:
        if runtime_task_ledger is None:
            return state, runtime_task_ledger, []
        current_step = current_task_step_run(runtime_task_ledger)
        if current_step is None or current_step.status != "running":
            return state, runtime_task_ledger, []
        if allowed_executor_types is not None and current_step.executor_type not in allowed_executor_types:
            return state, runtime_task_ledger, []

        transition_diagnostics = {
            "transition_reason": reason,
            **dict(diagnostics or {}),
        }
        runtime_task_ledger = fail_task_run_step(
            runtime_task_ledger,
            step_id=current_step.step_id,
            completed_at=time.time(),
            failure_reason=failure_reason,
            observation_refs=observation_refs,
            output_refs=output_refs,
            step_result_ref=step_result_ref,
            executor_ref=executor_ref or current_step.executor_ref,
            diagnostics=transition_diagnostics,
        )
        events: list[Any] = []
        failed_step = find_task_step_run(runtime_task_ledger, current_step.step_id)
        if failed_step is not None:
            events.append(
                self._record_task_run_step_event(
                    state.task_run_id,
                    event_type="step_failed",
                    step_run=failed_step,
                    ledger=runtime_task_ledger,
                    reason=reason,
                    refs=refs,
                )
            )
        ledger_event = self._record_task_run_ledger_updated(
            state.task_run_id,
            ledger=runtime_task_ledger,
            reason=reason,
            refs=refs,
            diagnostics=ledger_diagnostics,
        )
        events.append(ledger_event)
        state_diagnostics = {
            "last_step_transition": reason,
            **dict(diagnostics or {}),
        }
        state = self._state_with_task_run_ledger(
            state,
            runtime_task_ledger,
            result_refs=result_refs,
            diagnostics=state_diagnostics,
        )
        events.append(self._write_checkpoint_event(state, event_offset=ledger_event.offset))
        return state, runtime_task_ledger, events

    def _sync_runtime_objects_after_task_contract(
        self,
        *,
        start_result: AgentRuntimeStartResult,
        event_offset: int,
        execution_mode: str,
        task_agent_binding_ref: str,
        graph_payload: dict[str, Any],
        communication_protocol_payload: dict[str, Any],
        task_graph_payload: dict[str, Any] | None = None,
        task_execution_policy_payload: dict[str, Any] | None = None,
        effective_limits: RuntimeLoopLimits | None = None,
        task_spec_payload: dict[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        events: list[Any] = []
        execution_policy_payload = dict(task_execution_policy_payload or {})
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
            spawn_mode=execution_mode,
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
                "execution_mode": execution_mode,
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
            coordination_flow = build_coordination_state(
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
            if self.graph_coordination_engine.supports(coordination_run):
                runtime_result = self.graph_coordination_engine.initialize(
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
            execution_mode=execution_mode,
            task_agent_binding_ref=task_agent_binding_ref,
            execution_policy_payload=execution_policy_payload,
            event_offset=event_offset,
        )
        events.extend(spawn_events)

        if (
            current_coordination_run is not None
            and not self.graph_coordination_engine.supports(current_coordination_run)
            and not bool(dict(current_coordination_run.diagnostics or {}).get("worker_spawn_runtime"))
        ):
            raise RuntimeError(
                f"Legacy coordination sync path was removed: {current_coordination_run.coordination_run_id}"
            )
        return tuple(events)

    def _sync_worker_spawn_runtime_objects(
        self,
        *,
        task_run_id: str,
        parent_agent_run: AgentRun,
        coordination_run: CoordinationRun | None,
        execution_mode: str,
        task_agent_binding_ref: str,
        execution_policy_payload: dict[str, Any],
        event_offset: int,
    ) -> tuple[list[Any], CoordinationRun | None]:
        events: list[Any] = []
        allow_spawn = bool(execution_policy_payload.get("allow_worker_agent_spawn") is True)
        blueprint_id = str(execution_policy_payload.get("worker_agent_blueprint_id") or "").strip()
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
            naming_rule=str(execution_policy_payload.get("worker_agent_naming_rule") or "").strip(),
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
            spawn_reason="task_execution_policy_authorized",
            requested_at=time.time(),
            diagnostics={
                "execution_mode": execution_mode,
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
        if coordination_run is None and self._execution_mode_allows_projection(execution_mode):
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
                    "coordination_engine": "graph_coordination_engine",
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
    def _execution_mode_allows_projection(execution_mode: str) -> bool:
        return str(execution_mode or "").strip() == "coordinated_agents"

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
        return state_with_task_run_ledger(
            state,
            ledger,
            transition=transition,
            task_result_ref=task_result_ref,
            result_refs=result_refs,
            status=status,
            terminal_reason=terminal_reason,
            diagnostics=diagnostics,
            commit_state=commit_state,
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
                operation_gate=self.operation_gate,
                permission_mode_provider=self._current_permission_mode,
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
        task_run = self.state_index.get_task_run(task_run_id)
        return build_delegation_request(
            task_run_id=task_run_id,
            action_request=action_request,
            parent_agent_run_ref=parent_agent_run_ref,
            source_agent_id=source_agent_id,
            user_message=user_message,
            task_operation=task_operation,
            allowed_search_sources=allowed_search_sources,
            session_id=str(task_run.session_id if task_run is not None else ""),
        )





_STANDARD_INPUT_MODEL_TEXT_LIMIT = 120_000
_STANDARD_INPUT_ITEM_TEXT_LIMIT = 24_000



















































def _runtime_loop_short_hash(value: Any) -> str:
    import hashlib
    import json

    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]






























