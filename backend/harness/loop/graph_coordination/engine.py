from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Annotated, Any, TypedDict

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from langgraph.graph import END, START, StateGraph

from memory_system.runtime_services import MemoryRuntimeServices
from artifact_system import ArtifactRepositoryService
from task_system import TaskContractRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.compiler.coordination_graph_models import TaskGraphRuntimeSpec
from task_system.graphs.task_graph_models import task_graph_from_dict

from harness.execution.node_protocol.node_execution_a2a_payload import build_node_execution_a2a_payload
from runtime.shared.artifact_refs import ArtifactRefIndex
from runtime.contracts.compiler import compile_coordination_contract_manifest
from runtime.contracts.continuation_inputs import ContinuationInputBinder
from runtime.contracts.continuation_policy import (
    CoordinationContinuationPolicy,
    CoordinationStageContract,
    contract_by_stage,
    parse_stage_contracts,
    derive_stage_contracts_from_graph,
    validate_stage_contracts,
)
from runtime.memory.project_supervision import make_supervision_record
from .memory_helpers import (
    _artifact_repository_root_for_runtime,
    _decision_refs,
    _filter_working_memory_refs_for_handoff,
    _formal_memory_acknowledgement,
    _formal_memory_commit_requests,
    _formal_memory_only_context,
    _formal_memory_write_records,
    _first_policy_value,
    _graph_edges,
    _graph_memory_edge_descriptors,
    _matching_commit_edge,
    _stage_working_memory_refs_for_commit,
    _timeline_working_memory_operation,
    _working_memory_read_operation_from_context,
    _working_memory_refs_from_context,
    _workspace_root_from_runtime_root,
)
from .result_helpers import (
    _collect_stage_outputs,
    _extract_source_output_value,
    _first_dict,
    _latest_timeline_result_record,
    _node_result_output_bundle,
    _stage_outputs_from_artifact_refs,
)
from .node_result_committer import (
    active_execution_request_payload as _active_execution_request_payload,
    artifact_refs_from_value as _artifact_refs_from_value,
    build_node_result_acceptance_draft,
    build_stage_result_request_payload as _stage_result_request_payload,
    committed_stage_identities as _committed_stage_identities,
    dependency_scope_key_from_inputs as _dependency_scope_key_from_inputs,
    node_execution_boundary as _node_execution_boundary,
    runtime_scope_coordinate_from_inputs as _runtime_scope_coordinate_from_inputs,
    scope_path_segments_from_coordinate as _scope_path_segments_from_coordinate,
    short_hash as _short_hash,
    stage_commit_identity as _stage_commit_identity,
    stale_result_reason as _stale_result_reason,
)
from .payloads import (
    _accept_contract_status,
    _edge_handoff_index_from_state,
    _graph_id_from_state,
    _initial_contract_status,
    _manifest_from_payload,
    _runtime_node_payload,
    _runtime_node_value,
    _runtime_spec_from_state,
    _runtime_spec_from_payload,
    _safe_id,
    _safe_int,
    _set_contract_node_status,
    _string_list,
)
from .trace_adapter import CoordinationTraceAdapter
from .context_packet_resolver import build_revision_packet_from_review, resolve_context_packets
from task_system.runtime_semantics.review_gate_verdict import (
    review_verdict_blocks_downstream_invalidation,
    review_verdict_is_accepted,
    review_verdict_is_rejected,
)
from .checkpoint_adapter import GraphCoordinationCheckpointStore
from .kernel import GraphCoordinationKernel
from .work_order_builder import build_node_work_order_from_request
from runtime.agent_assembly import (
    build_model_context_payload,
    build_runtime_control_payload,
    build_task_selection_payload,
    runtime_control_ref_summary,
)
from runtime.shared.runtime_object_store import RuntimeObjectStore
from runtime.shared.models import AgentHandoffEnvelope, CoordinationRun
from runtime.contracts.runtime_assembly_builder import build_node_runtime_assembly
from orchestration.artifact_policy_view import render_artifact_policy_instructions
from harness.execution.node_protocol.node_execution_request import NodeExecutionRequest, NodeResultReadyEvent
from harness.execution.graph_module_runtime import (
    build_graph_module_runtime_handle_from_contract,
    graph_module_stage_is_enabled,
)
from runtime.graph_runtime.batch_runtime import (
    apply_batch_to_pending_inputs,
    attach_batch_execution_request,
    batch_dispatcher_view,
    batch_execution_instance_for_result,
    batch_runtime_state_from_diagnostics,
    bootstrap_batch_lifecycle_runtime_state,
    is_technical_execution_failure,
    node_has_batch_plan,
    node_all_batches_committed,
    node_has_active_batch_work,
    node_has_dispatchable_batch_work,
    node_committed_batch_refs,
    node_has_failed_batch,
    node_has_more_batch_work,
    node_has_technical_blocked_batch,
    rewind_batch_lifecycle_for_stages,
    select_batch_for_stage,
    summarize_batch_lifecycle_runtime_state,
    transition_batch_after_stage_result,
)
from runtime.graph_runtime.scheduler import bootstrap_scheduler_state
from runtime.memory.timeline_ledger import TimelineEvent, TimelineLedgerStore
from runtime.memory.timeline_result_record import build_timeline_result_record
from task_system.runtime_semantics.protocol_boundary import is_internal_protocol_input_key
from harness.execution.node_protocol.node_handoff_protocol import (
    build_node_executor_binding,
    build_standard_node_input_package,
    build_standard_node_result_package,
    render_human_work_packet,
)


class CoordinationRuntimeState(TypedDict, total=False):
    coordination_run_id: str
    root_task_run_id: str
    coordination_mode: str
    active_node_id: str
    active_stage_id: str
    active_task_ref: str
    active_task_run_id: str
    stage_order: list[str]
    stage_contracts: dict[str, dict[str, Any]]
    contract_manifest: dict[str, Any]
    contract_status: dict[str, Any]
    node_contracts: dict[str, dict[str, Any]]
    edge_contracts: dict[str, dict[str, Any]]
    ready_nodes: list[str]
    blocked_nodes: list[str]
    running_nodes: list[str]
    waiting_nodes: list[str]
    completed_nodes: list[str]
    failed_nodes: list[str]
    handoff_packets: list[dict[str, Any]]
    acceptance_results: dict[str, Any]
    node_statuses: dict[str, str]
    stage_results: dict[str, dict[str, Any]]
    stage_results_by_instance: dict[str, dict[str, Any]]
    stale_stage_results: list[dict[str, Any]]
    duplicate_stage_commits: list[dict[str, Any]]
    committed_stage_identities: list[str]
    artifact_refs: Annotated[list[dict[str, Any]], operator.add]
    pending_inputs: dict[str, Any]
    missing_required_inputs: list[str]
    retry_counts: dict[str, int]
    retry_stage_id: str
    human_gate: dict[str, Any]
    terminal_status: str
    final_result_ref: str
    current_event: dict[str, Any]
    current_task_result: dict[str, Any]
    node_work_order: dict[str, Any]
    node_execution_request: dict[str, Any]
    stage_execution_request: dict[str, Any]
    a2a_payload: dict[str, Any]
    working_memory_contexts: dict[str, dict[str, Any]]
    working_memory_operations: list[dict[str, Any]]
    revision_packets: list[dict[str, Any]]
    timeline_result_records: list[dict[str, Any]]
    result_record_index: dict[str, dict[str, Any]]
    latest_stage_result_records: dict[str, str]
    accepted_result_records_by_scope: dict[str, dict[str, str]]
    batch_lifecycle_runtime_state: dict[str, Any]
    timeline: dict[str, Any]
    diagnostics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GraphCoordinationResult:
    state: dict[str, Any] = field(default_factory=dict)
    events: tuple[Any, ...] = ()
    stage_execution_request: NodeExecutionRequest | None = None
    node_work_order: dict[str, Any] = field(default_factory=dict)
    checkpoint_ref: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def continuation_payload(self, *, session_id: str, current_turn_context: dict[str, Any] | None = None) -> dict[str, Any]:
        work_order = dict(self.node_work_order or {})
        if self.stage_execution_request is None:
            return {}
        request = self.stage_execution_request
        work_order_task_ref = str(work_order.get("task_ref") or request.task_ref)
        work_order_executor_type = str(work_order.get("executor_type") or request.executor_type)
        work_order_stage_id = str(work_order.get("stage_id") or request.stage_id)
        stage_request_payload = request.to_dict()
        stage_request_ref = _stage_execution_request_ref(stage_request_payload)
        standard_input_package = dict(work_order.get("input_package") or request.standard_input_package)
        a2a_payload = dict(work_order.get("a2a_payload") or request.a2a_payload)
        runtime_control = build_runtime_control_payload(
            stage_execution_request=stage_request_payload,
            stage_execution_request_ref=stage_request_ref,
            node_work_order=work_order,
            standard_input_package=standard_input_package,
        )
        turn_context = build_model_context_payload(
            current_turn_context=current_turn_context,
            stage_execution_request=stage_request_payload,
            node_work_order=work_order,
            stage_execution_request_ref=stage_request_ref,
        )
        if work_order_executor_type == "human":
            return {
                "session_id": session_id,
                "coordination_run_id": request.coordination_run_id,
                "thread_id": request.thread_id,
                "current_task_run_id": request.root_task_run_id,
                "next_stage_id": work_order_stage_id,
                "current_turn_context": turn_context,
                "runtime_control": runtime_control,
                "stage_execution_request": stage_request_payload,
                "node_work_order": work_order,
                "a2a_payload": a2a_payload,
                "human_work_packet": dict(work_order.get("human_work_packet") or request.human_work_packet),
                "requires_human_executor": True,
                "suppress_done": True,
            }
        if work_order_executor_type == "graph_module" or str(work_order.get("work_kind") or "") == "graph_module":
            return {
                "session_id": session_id,
                "coordination_run_id": request.coordination_run_id,
                "thread_id": request.thread_id,
                "current_task_run_id": request.root_task_run_id,
                "next_stage_id": work_order_stage_id,
                "current_turn_context": turn_context,
                "runtime_control": runtime_control,
                "stage_execution_request": stage_request_payload,
                "node_work_order": work_order,
                "a2a_payload": a2a_payload,
                "graph_module_runtime_handle": dict(
                    dict(work_order.get("runtime_assembly") or request.runtime_assembly).get("graph_module_runtime_handle") or {}
                ),
                "requires_graph_module_executor": True,
                "suppress_done": True,
            }
        return {
            "session_id": session_id,
            "coordination_run_id": request.coordination_run_id,
            "thread_id": request.thread_id,
            "current_task_run_id": request.root_task_run_id,
            "next_task_ref": work_order_task_ref,
            "next_stage_id": work_order_stage_id,
            "current_turn_context": turn_context,
            "message": str(work_order.get("message") or request.message),
            "runtime_control": runtime_control,
            "task_selection": build_task_selection_payload(
                current_turn_context=turn_context,
                runtime_control=runtime_control,
            ),
            "suppress_done": True,
        }


def _stage_execution_request_ref(stage_request_payload: dict[str, Any]) -> str:
    request_id = str(stage_request_payload.get("request_id") or "").strip()
    if request_id:
        return request_id
    return str(stage_request_payload.get("idempotency_key") or "").strip()


class GraphCoordinationEngine:
    """Topology-driven graph coordination engine behind GraphLoop."""

    def __init__(
        self,
        *,
        root_dir: Any,
        registry_base_dir: Any | None = None,
        state_index: Any,
        event_log: Any,
        task_flow_registry: Any,
        trace_reader: Any,
        artifact_repository: ArtifactRepositoryService | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.registry_base_dir = Path(
            registry_base_dir
            or getattr(task_flow_registry, "base_dir", "")
            or root_dir
        )
        self.state_index = state_index
        self.event_log = event_log
        self.task_flow_registry = task_flow_registry
        self.trace_reader = trace_reader
        self.artifact_repository = artifact_repository or ArtifactRepositoryService(
            _artifact_repository_root_for_runtime(root_dir),
            workspace_root=_workspace_root_from_runtime_root(root_dir),
        )
        self.artifact_refs = ArtifactRefIndex(
            state_index=state_index,
            trace_reader=trace_reader,
            artifact_repository=self.artifact_repository,
        )
        self.input_binder = ContinuationInputBinder(self.artifact_refs)
        self.checkpoints = GraphCoordinationCheckpointStore(root_dir)
        self.runtime_objects = RuntimeObjectStore(root_dir)
        self.trace_adapter = CoordinationTraceAdapter(state_index=state_index, event_log=event_log)
        self.memory_runtime_services = MemoryRuntimeServices.from_runtime_root(root_dir)
        self.working_memory = self.memory_runtime_services.working_memory
        self.working_memory_finalizer = self.memory_runtime_services.working_memory_finalizer
        self.formal_memory = self.memory_runtime_services.formal_memory
        self.timeline_ledger = TimelineLedgerStore(root_dir)
        self._app = self._build_app()
        self.kernel = GraphCoordinationKernel(app=self._app, checkpoints=self.checkpoints)

    def _resolve_task_graph_view(self, coordination_run: CoordinationRun, *, prefer_live_graph: bool = False):
        task_graph = self._resolve_task_graph_definition(coordination_run, prefer_live_graph=prefer_live_graph)
        if task_graph is None:
            return None
        derive = getattr(self.task_flow_registry, "derive_coordination_task_view_from_graph", None)
        if not callable(derive):
            return None
        return derive(task_graph)

    def _resolve_task_graph_definition(self, coordination_run: CoordinationRun, *, prefer_live_graph: bool = False):
        target = str(coordination_run.graph_ref or "").strip()
        if prefer_live_graph and target:
            get_task_graph = getattr(self.task_flow_registry, "get_task_graph", None)
            if callable(get_task_graph):
                live_graph = get_task_graph(target)
                if live_graph is not None:
                    return live_graph
        diagnostics = dict(coordination_run.diagnostics or {})
        definition_ref = str(diagnostics.get("task_graph_definition_ref") or "").strip()
        snapshot = self.runtime_objects.get_object(definition_ref) if definition_ref else {}
        if snapshot:
            return task_graph_from_dict(snapshot)
        if not target:
            return None
        get_task_graph = getattr(self.task_flow_registry, "get_task_graph", None)
        if not callable(get_task_graph):
            return None
        return get_task_graph(target)

    def supports(self, coordination_run: CoordinationRun) -> bool:
        coordination_task = self._resolve_task_graph_view(coordination_run)
        if coordination_task is None:
            return False
        contracts = self._contracts_for_run(coordination_run=coordination_run, coordination_task=coordination_task)
        return bool(contracts)

    def initialize(
        self,
        *,
        coordination_run: CoordinationRun,
        event_task_run_id: str = "",
        inherited_inputs: dict[str, Any] | None = None,
    ) -> GraphCoordinationResult:
        coordination_task = self._resolve_task_graph_view(coordination_run)
        if coordination_task is None:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
        state = self._load_or_bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)
        if inherited_inputs:
            business_inherited_inputs = {
                str(key): value
                for key, value in dict(inherited_inputs).items()
                if not is_internal_protocol_input_key(str(key))
            }
            state["pending_inputs"] = {**dict(state.get("pending_inputs") or {}), **business_inherited_inputs}
            project_id = _project_id_from_state(
                state,
                state_index=self.state_index,
                fallback_task_run_id=coordination_run.task_run_id,
            )
            state["diagnostics"] = {
                **dict(state.get("diagnostics") or {}),
                "inherited_input_keys": sorted(str(key) for key in business_inherited_inputs.keys()),
                **({"project_id": project_id} if project_id else {}),
                "filtered_internal_protocol_input_keys": sorted(
                    str(key)
                    for key in dict(inherited_inputs).keys()
                    if is_internal_protocol_input_key(str(key))
                ),
            }
        self._append_timeline_event(
            state,
            event_type="run_started",
            status="running",
            payload={"coordination_run_id": coordination_run.coordination_run_id},
            idempotency_key=f"{coordination_run.coordination_run_id}:run_started",
        )
        if not _active_execution_request_payload(state):
            prepared_inputs = self._stage_prepare(state)
            state.update(prepared_inputs)
            if str(state.get("terminal_status") or "") not in {"blocked", "waiting_for_batch_result"}:
                prepared = self._stage_execute(state)
                state.update(prepared)
        state = self._attach_timeline_snapshot(state)
        kernel_result = self.kernel.checkpoint(
            thread_id=coordination_run.coordination_run_id,
            state=state,
            reason="initialize",
            checkpoint_metadata={"event": "initialize"},
        )
        checkpoint = kernel_result.checkpoint
        self._append_timeline_event(
            state,
            event_type="checkpoint_linked",
            status="completed",
            checkpoint_ref=checkpoint.checkpoint_id,
            payload={"reason": "initialize"},
            idempotency_key=f"{coordination_run.coordination_run_id}:checkpoint:{checkpoint.checkpoint_id}",
        )
        state = self._attach_timeline_snapshot(state)
        events = self.trace_adapter.write_state(
            coordination_run=coordination_run,
            state=state,
            checkpoint_ref=checkpoint.checkpoint_id,
            event_task_run_id=event_task_run_id or coordination_run.task_run_id,
        )
        return _runtime_result_from_state(
            state=state,
            events=tuple(events),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={"supported": True, "initialized": True},
        )

    def resume_from_task_result(
        self,
        *,
        coordination_run: CoordinationRun,
        event: NodeResultReadyEvent,
        current_task_result: dict[str, Any] | None = None,
        inherited_inputs: dict[str, Any] | None = None,
        artifact_root: str = "",
    ) -> GraphCoordinationResult:
        coordination_task = self._resolve_task_graph_view(coordination_run)
        if coordination_task is None:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
        state = self._load_or_bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)
        state["current_event"] = event.to_dict()
        state["current_task_result"] = dict(current_task_result or {})
        state["pending_inputs"] = {
            **dict(state.get("pending_inputs") or {}),
            **dict(inherited_inputs or {}),
        }
        if artifact_root:
            state["pending_inputs"]["artifact_root"] = artifact_root
        kernel_result = self.kernel.invoke(
            state=state,
            thread_id=coordination_run.coordination_run_id,
            reason="task_result_ready",
            checkpoint_metadata={"event": "task_result_ready", "task_run_id": event.task_run_id},
        )
        final_state = dict(kernel_result.state or {})
        checkpoint = kernel_result.checkpoint
        self._append_timeline_event(
            final_state,
            event_type="checkpoint_linked",
            status="completed",
            checkpoint_ref=checkpoint.checkpoint_id,
            payload={"reason": "task_result_ready", "task_run_id": event.task_run_id},
            idempotency_key=f"{coordination_run.coordination_run_id}:checkpoint:{checkpoint.checkpoint_id}",
        )
        final_state = self._attach_timeline_snapshot(final_state)
        events = self.trace_adapter.write_state(
            coordination_run=coordination_run,
            state=final_state,
            checkpoint_ref=checkpoint.checkpoint_id,
            event_task_run_id=event.task_run_id,
        )
        self._record_coordination_supervision(
            coordination_run=coordination_run,
            issue_type="task_result_resume",
            issue_summary=f"Task result resumed for stage {str(event.stage_id or '')}",
            root_cause=str(event.event_type or "task_result_ready"),
            repair_action="resume_from_task_result",
            repair_result=str(final_state.get("terminal_status") or ""),
            followup_status="recorded",
            diagnostics={
                "stage_id": str(event.stage_id or ""),
                "task_result_ref": str(event.task_result_ref or ""),
                "checkpoint_ref": checkpoint.checkpoint_id,
            },
        )
        return _runtime_result_from_state(
            state=final_state,
            events=tuple(events),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics=dict(final_state.get("diagnostics") or {}),
        )

    def resume_human_gate(
        self,
        *,
        coordination_run_id: str,
        resume_payload: dict[str, Any],
    ) -> GraphCoordinationResult:
        coordination_run = self.state_index.get_coordination_run(coordination_run_id)
        if coordination_run is None:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_coordination_run"})
        state = self.checkpoints.get_state(thread_id=coordination_run_id)
        if not state:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_checkpoint"})
        state = _normalize_coordination_authoritative_state(state)
        human_gate = dict(state.get("human_gate") or {})
        pending_stage_id = str(resume_payload.get("stage_id") or human_gate.get("stage_id") or human_gate.get("pending_stage_id") or state.get("active_stage_id") or "").strip()
        state["human_gate"] = {
            **human_gate,
            "resume": dict(resume_payload or {}),
            "status": "resuming",
        }
        state["terminal_status"] = ""
        state["current_event"] = {
            "event_type": "human_gate_resumed",
            "stage_id": pending_stage_id,
            **dict(resume_payload or {}),
        }
        self._append_timeline_event(
            state,
            event_type="human_gate_resumed",
            status="resuming",
            scope_type="stage",
            scope_path=list(self._stage_scope(state=state, stage_id=pending_stage_id).get("scope_path") or ["run"]),
            node_id=pending_stage_id,
            payload={"stage_id": pending_stage_id, "resume_payload": dict(resume_payload or {})},
        )
        kernel_result = self.kernel.invoke(
            state=state,
            thread_id=coordination_run_id,
            reason="human_gate_resumed",
            checkpoint_metadata={"event": "human_gate_resumed"},
        )
        final_state = dict(kernel_result.state or state)
        checkpoint = kernel_result.checkpoint
        self._append_timeline_event(
            final_state,
            event_type="checkpoint_linked",
            status="completed",
            checkpoint_ref=checkpoint.checkpoint_id,
            payload={"reason": "human_gate_resumed"},
            idempotency_key=f"{coordination_run_id}:checkpoint:{checkpoint.checkpoint_id}",
        )
        final_state = self._attach_timeline_snapshot(final_state)
        events = self.trace_adapter.write_state(
            coordination_run=coordination_run,
            state=final_state,
            checkpoint_ref=checkpoint.checkpoint_id,
            event_task_run_id=coordination_run.task_run_id,
        )
        self._record_coordination_supervision(
            coordination_run=coordination_run,
            issue_type="human_gate_resume",
            issue_summary=f"Human gate resumed with decision {str(resume_payload.get('decision') or resume_payload.get('action') or 'continue')}",
            root_cause=str(resume_payload.get("reason") or "human_gate"),
            repair_action=str(resume_payload.get("decision") or resume_payload.get("action") or "continue"),
            repair_result=str(final_state.get("terminal_status") or ""),
            followup_status="recorded",
            diagnostics={
                "stage_id": pending_stage_id,
                "resume_payload": dict(resume_payload or {}),
                "checkpoint_ref": checkpoint.checkpoint_id,
                "final_state": {
                    "status": str(final_state.get("terminal_status") or ""),
                    "active_stage_id": str(final_state.get("active_stage_id") or ""),
                },
            },
        )
        return _runtime_result_from_state(
            state=final_state,
            events=tuple(events),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics=dict(final_state.get("diagnostics") or {}),
        )

    def rewind_from_stage(
        self,
        *,
        coordination_run_id: str,
        stage_id: str,
        reason: str = "stage_output_invalid",
        inherited_inputs: dict[str, Any] | None = None,
        refresh_graph_spec: bool = True,
    ) -> GraphCoordinationResult:
        coordination_run = self.state_index.get_coordination_run(coordination_run_id)
        if coordination_run is None:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_coordination_run"})
        state = self.checkpoints.get_state(thread_id=coordination_run_id)
        if not state:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_checkpoint"})
        state = _normalize_coordination_authoritative_state(state)

        target_stage_id = str(stage_id or "").strip()
        if not target_stage_id:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_stage_id"})

        if refresh_graph_spec:
            coordination_task = self._resolve_task_graph_view(coordination_run, prefer_live_graph=True)
            if coordination_task is not None:
                refreshed = self._bootstrap_state(
                    coordination_run=coordination_run,
                    coordination_task=coordination_task,
                    prefer_live_graph=True,
                )
                for key in (
                    "stage_order",
                    "stage_contracts",
                    "contract_manifest",
                    "node_contracts",
                    "edge_contracts",
                ):
                    if refreshed.get(key):
                        state[key] = refreshed[key]
                refreshed_diagnostics = dict(refreshed.get("diagnostics") or {})
                diagnostics = dict(state.get("diagnostics") or {})
                for key in (
                    "coordination_graph_spec",
                    "task_graph_scheduler_state",
                    "contract_manifest_ref",
                    "contract_manifest_valid",
                    "contract_manifest_issue_count",
                    "stage_contract_issues",
                    "continuation_policy",
                    "runtime_loop_policy",
                ):
                    if key in refreshed_diagnostics:
                        diagnostics[key] = refreshed_diagnostics[key]
                diagnostics["rewind_refreshed_graph_spec"] = True
                state["diagnostics"] = diagnostics

        invalidated_stage_ids = _downstream_stage_ids(state=state, stage_id=target_stage_id, include_self=True)
        if target_stage_id not in invalidated_stage_ids:
            invalidated_stage_ids.insert(0, target_stage_id)
        invalidated_set = set(invalidated_stage_ids)
        order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        if target_stage_id not in order:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "stage_not_in_order", "stage_id": target_stage_id})
        invalidated_node_ids = [
            str(dict(dict(state.get("stage_contracts") or {}).get(stage) or {}).get("node_id") or stage)
            for stage in invalidated_stage_ids
            if str(stage)
        ]
        target_node_id = str(dict(dict(state.get("stage_contracts") or {}).get(target_stage_id) or {}).get("node_id") or target_stage_id)

        stage_results = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results") or {}).items()
            if str(key) and isinstance(value, dict) and str(key) not in invalidated_set
        }
        removed_stage_results = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results") or {}).items()
            if str(key) in invalidated_set and isinstance(value, dict)
        }
        invalidated_result_record_ids = {
            str(dict(result).get("timeline_result_record", {}).get("result_record_id") or "")
            for result in removed_stage_results.values()
            if isinstance(result, dict)
        }
        invalidated_result_record_ids.update(
            str(record_id)
            for stage, record_id in dict(state.get("latest_stage_result_records") or {}).items()
            if str(stage) in invalidated_set and str(record_id)
        )
        invalidated_result_record_ids = {item for item in invalidated_result_record_ids if item}

        node_statuses = {
            str(key): str(value)
            for key, value in dict(state.get("node_statuses") or {}).items()
            if str(key)
        }
        for item in order:
            if item in invalidated_set:
                node_statuses[item] = "running" if item == target_stage_id else "pending"
            elif node_statuses.get(item) not in {"completed", "failed", "waiting_for_human", "human_gate", "waiting"}:
                node_statuses[item] = "pending"

        timeline_result_records = [
            dict(item)
            for item in list(state.get("timeline_result_records") or [])
            if isinstance(item, dict)
            and str(item.get("stage_id") or "") not in invalidated_set
            and str(item.get("result_record_id") or "") not in invalidated_result_record_ids
        ]
        result_record_index = {
            str(key): dict(value)
            for key, value in dict(state.get("result_record_index") or {}).items()
            if str(key) not in invalidated_result_record_ids
        }
        stage_results_by_instance = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results_by_instance") or {}).items()
            if str(key) not in invalidated_result_record_ids
            and str(dict(value).get("stage_id") or "") not in invalidated_set
        }
        latest_stage_result_records = {
            str(stage): str(record_id)
            for stage, record_id in dict(state.get("latest_stage_result_records") or {}).items()
            if str(stage) not in invalidated_set and str(record_id)
        }
        accepted_result_records_by_scope = {}
        for scope_key, records in dict(state.get("accepted_result_records_by_scope") or {}).items():
            if not isinstance(records, dict):
                continue
            kept = {
                str(stage): str(record_id)
                for stage, record_id in dict(records).items()
                if str(stage) not in invalidated_set and str(record_id) not in invalidated_result_record_ids
            }
            if kept:
                accepted_result_records_by_scope[str(scope_key)] = kept

        contract_status = _rewound_contract_status(
            dict(state.get("contract_status") or {}),
            invalidated_stage_ids=invalidated_stage_ids,
            target_stage_id=target_stage_id,
            reason=reason,
        )

        artifact_refs = [
            dict(item)
            for item in list(state.get("artifact_refs") or [])
            if isinstance(item, dict) and str(item.get("stage_id") or "") not in invalidated_set
        ]
        handoff_packets = [
            dict(item)
            for item in list(state.get("handoff_packets") or [])
            if isinstance(item, dict)
            and str(item.get("source_node_id") or "") not in invalidated_set
            and str(item.get("target_node_id") or "") not in invalidated_set
            and str(item.get("source_stage_id") or "") not in invalidated_set
            and str(item.get("target_stage_id") or "") not in invalidated_set
        ]
        working_memory_operations = [
            dict(item)
            for item in list(state.get("working_memory_operations") or [])
            if isinstance(item, dict)
            and str(item.get("stage_id") or "") not in invalidated_set
            and str(item.get("node_id") or "") not in invalidated_set
            and str(item.get("source_node_id") or "") not in invalidated_set
            and str(item.get("target_node_id") or "") not in invalidated_set
        ]

        preserved_pending_inputs = _rewind_preserved_pending_inputs(
            dict(state.get("pending_inputs") or {}),
            invalidated_stage_ids=invalidated_stage_ids,
            stage_results=stage_results,
        )
        inherited_payload = dict(inherited_inputs or {})
        preserved_inherited_inputs = _rewind_preserved_pending_inputs(
            inherited_payload,
            invalidated_stage_ids=invalidated_stage_ids,
            stage_results=stage_results,
        )
        rewind_metadata_inputs = {
            key: inherited_payload[key]
            for key in ("artifact_root", "workspace_root", "rewind_invalidated_artifacts")
            if key in inherited_payload
        }
        pending_inputs = {**preserved_pending_inputs, **preserved_inherited_inputs, **rewind_metadata_inputs}
        pending_inputs["force_replay"] = True
        pending_inputs["force_replay_after"] = time.time()
        pending_inputs["rewind_from_stage"] = target_stage_id
        pending_inputs["rewind_reason"] = reason
        pending_inputs = _normalize_pending_inputs_with_runtime_loop_policy(
            state=state,
            pending_inputs=pending_inputs,
            preserve_existing_batch_scope=True,
        )

        diagnostics = {
            **dict(state.get("diagnostics") or {}),
            "last_rewind": {
                "stage_id": target_stage_id,
                "reason": reason,
                "invalidated_stage_ids": invalidated_stage_ids,
                "invalidated_result_record_ids": sorted(invalidated_result_record_ids),
                "created_at": time.time(),
            },
        }
        batch_runtime_state = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        ) or batch_runtime_state_from_diagnostics(diagnostics)
        if batch_runtime_state:
            batch_runtime_state = rewind_batch_lifecycle_for_stages(
                runtime_state=batch_runtime_state,
                invalidated_stage_ids=invalidated_stage_ids,
                invalidated_node_ids=invalidated_node_ids,
                target_stage_id=target_stage_id,
                target_node_id=target_node_id,
                reason=reason,
            )
            diagnostics["batch_lifecycle_runtime_state"] = batch_runtime_state
            diagnostics["last_rewind"]["batch_lifecycle_rewound"] = bool(batch_runtime_state)
        committed_identities = [
            item
            for item in _committed_stage_identities(state)
            if not any(str(item).startswith(f"{stage}:") for stage in invalidated_set)
        ]
        for key in (
            "last_accepted_stage_id",
            "last_duplicate_commit_identity",
            "last_stale_result_reason",
            "human_gate",
        ):
            value = str(diagnostics.get(key) or "")
            if value in invalidated_set or key == "last_accepted_stage_id":
                diagnostics.pop(key, None)

        state.update(
            {
                "active_stage_id": target_stage_id,
                "active_node_id": target_node_id,
                "active_task_ref": str(dict(dict(state.get("stage_contracts") or {}).get(target_stage_id) or {}).get("task_ref") or ""),
                "node_statuses": node_statuses,
                "stage_results": stage_results,
                "stage_results_by_instance": stage_results_by_instance,
                "committed_stage_identities": committed_identities,
                "timeline_result_records": timeline_result_records,
                "result_record_index": result_record_index,
                "latest_stage_result_records": latest_stage_result_records,
                "accepted_result_records_by_scope": accepted_result_records_by_scope,
                "contract_status": contract_status,
                "artifact_refs": artifact_refs,
                "handoff_packets": handoff_packets,
                "working_memory_operations": working_memory_operations,
                **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
                "pending_inputs": pending_inputs,
                "missing_required_inputs": [],
                "retry_stage_id": "",
                "current_event": {},
                "current_task_result": {},
                **_execution_boundary_cleared(),
                "human_gate": {},
                "terminal_status": "",
                "diagnostics": diagnostics,
            }
        )
        prepared_inputs = self._stage_prepare(state)
        state.update(prepared_inputs)
        if str(state.get("terminal_status") or "") in {"blocked", "waiting_for_batch_result"}:
            prepared = {}
        else:
            scheduler = _scheduler_node_sets(order=order, node_statuses=node_statuses, state=state, terminal_status="")
            state.update(scheduler)
            prepared = self._stage_execute(state)
        state.update(prepared)
        state = self._attach_timeline_snapshot(state)
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run_id,
            state=state,
            metadata={
                "event": "rewind_from_stage",
                "stage_id": target_stage_id,
                "reason": reason,
                "invalidated_stage_ids": invalidated_stage_ids,
            },
        )
        self._append_timeline_event(
            state,
            event_type="stage_rewound",
            status="completed",
            scope_type="stage",
            node_id=target_stage_id,
            payload={
                "stage_id": target_stage_id,
                "reason": reason,
                "invalidated_stage_ids": invalidated_stage_ids,
                "checkpoint_ref": checkpoint.checkpoint_id,
            },
        )
        state = self._attach_timeline_snapshot(state)
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run_id,
            state=state,
            metadata={
                "event": "rewind_from_stage_timeline_attached",
                "stage_id": target_stage_id,
                "reason": reason,
            },
        )
        events = self.trace_adapter.write_state(
            coordination_run=coordination_run,
            state=state,
            checkpoint_ref=checkpoint.checkpoint_id,
            event_task_run_id=coordination_run.task_run_id,
        )
        self._record_coordination_supervision(
            coordination_run=coordination_run,
            issue_type="stage_rewind",
            issue_summary=f"Coordination stage rewound from {target_stage_id}",
            root_cause=str(reason or "stage_output_invalid"),
            repair_action="rewind_stage",
            repair_result="rewound",
            followup_status="pending_control",
            diagnostics={
                "stage_id": target_stage_id,
                "reason": reason,
                "invalidated_stage_ids": invalidated_stage_ids,
                "invalidated_result_record_ids": sorted(invalidated_result_record_ids),
                "checkpoint_ref": checkpoint.checkpoint_id,
            },
        )
        request_payload = _active_execution_request_payload(state)
        request = NodeExecutionRequest.from_dict(request_payload) if request_payload else None
        return GraphCoordinationResult(
            state=state,
            events=tuple(events),
            stage_execution_request=request,
            node_work_order=dict(state.get("node_work_order") or {}),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={
                "supported": True,
                "rewound": True,
                "stage_id": target_stage_id,
                "invalidated_stage_ids": invalidated_stage_ids,
                "invalidated_result_record_ids": sorted(invalidated_result_record_ids),
            },
        )

    def _record_coordination_supervision(
        self,
        *,
        coordination_run: CoordinationRun,
        issue_type: str,
        issue_summary: str,
        root_cause: str,
        repair_action: str,
        repair_result: str,
        followup_status: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        task_run = self.state_index.get_task_run(coordination_run.task_run_id)
        if task_run is None:
            return
        project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "").strip()
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        if not project_id or not session_id:
            return
        self.state_index.upsert_supervision_record(
            make_supervision_record(
                project_id=project_id,
                session_id=session_id,
                task_run_id=coordination_run.task_run_id,
                coordination_run_id=coordination_run.coordination_run_id,
                issue_type=issue_type,
                issue_summary=issue_summary,
                root_cause=root_cause,
                repair_action=repair_action,
                repair_result=repair_result,
                followup_status=followup_status,
                diagnostics=dict(diagnostics or {}),
            )
        )

    def dispatch_ready_batch_requests(
        self,
        *,
        coordination_run: CoordinationRun,
        max_requests: int = 4,
        include_current_request: bool = True,
        checkpoint_reason: str = "dispatch_ready_batch_requests",
    ) -> GraphCoordinationResult:
        state = self.checkpoints.get_state(thread_id=coordination_run.coordination_run_id)
        if not state:
            return GraphCoordinationResult(diagnostics={"supported": False, "reason": "missing_checkpoint"})
        state = _normalize_coordination_authoritative_state(state)
        limit = max(int(max_requests or 0), 0)
        if limit <= 0:
            return GraphCoordinationResult(state=state, diagnostics={"supported": True, "request_count": 0})
        requests: list[NodeExecutionRequest] = []
        current_request_payload = _active_execution_request_payload(state)
        if include_current_request and current_request_payload:
            try:
                current_request = NodeExecutionRequest.from_dict(current_request_payload)
                if _request_dispatch_identity(current_request.to_dict()) not in {
                    _request_dispatch_identity(item.to_dict()) for item in requests
                }:
                    requests.append(current_request)
            except ValueError:
                pass
        state = dict(state)
        while len(requests) < limit:
            active_stage_id = str(state.get("active_stage_id") or "").strip()
            if not active_stage_id:
                break
            contract = dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {})
            node_id = str(contract.get("node_id") or active_stage_id)
            batch_runtime_state = summarize_batch_lifecycle_runtime_state(
                dict(state.get("batch_lifecycle_runtime_state") or {})
            ) or batch_runtime_state_from_diagnostics(dict(state.get("diagnostics") or {}))
            if not (
                batch_runtime_state
                and node_has_batch_plan(runtime_state=batch_runtime_state, stage_id=active_stage_id, node_id=node_id)
                and node_has_dispatchable_batch_work(runtime_state=batch_runtime_state, stage_id=active_stage_id, node_id=node_id)
            ):
                break
            state["stage_execution_request"] = {}
            state["node_execution_request"] = {}
            state["node_work_order"] = {}
            state["terminal_status"] = ""
            prepared_inputs = self._stage_prepare(state)
            state.update(prepared_inputs)
            if str(state.get("terminal_status") or "") in {"blocked", "waiting_for_batch_result"}:
                break
            prepared = self._stage_execute(state)
            state.update(prepared)
            request_payload = _active_execution_request_payload(state)
            if not request_payload:
                break
            try:
                request = NodeExecutionRequest.from_dict(request_payload)
            except ValueError:
                break
            identities = {_request_dispatch_identity(item.to_dict()) for item in requests}
            if _request_dispatch_identity(request_payload) in identities:
                break
            requests.append(request)
        state["diagnostics"] = {
            **dict(state.get("diagnostics") or {}),
            "batch_dispatcher": batch_dispatcher_view(dict(state.get("batch_lifecycle_runtime_state") or {})),
        }
        state = self._attach_timeline_snapshot(state)
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run.coordination_run_id,
            state=state,
            metadata={"event": checkpoint_reason, "request_count": len(requests)},
        )
        events = self.trace_adapter.write_state(
            coordination_run=coordination_run,
            state=state,
            checkpoint_ref=checkpoint.checkpoint_id,
            event_task_run_id=coordination_run.task_run_id,
        )
        return GraphCoordinationResult(
            state=state,
            events=tuple(events),
            stage_execution_request=requests[-1] if requests else None,
            node_work_order=dict(state.get("node_work_order") or {}),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={
                "supported": True,
                "request_count": len(requests),
                "stage_execution_requests": [request.to_dict() for request in requests],
                "batch_dispatcher": dict(state.get("diagnostics", {}).get("batch_dispatcher") or {}),
            },
        )

    def _build_app(self):
        graph = StateGraph(CoordinationRuntimeState)
        graph.add_node("stage_accept", self._stage_accept)
        graph.add_node("route_next", self._route_next)
        graph.add_node("stage_prepare", self._stage_prepare)
        graph.add_node("stage_execute", self._stage_execute)
        graph.add_node("blocked", self._blocked)
        graph.add_node("noop", self._noop)
        graph.add_node("complete", self._complete)
        graph.add_edge(START, "stage_accept")
        graph.add_edge("stage_accept", "route_next")
        graph.add_conditional_edges(
            "route_next",
            self._route_after_next,
            {
                "stage_prepare": "stage_prepare",
                "blocked": "blocked",
                "noop": "noop",
                "complete": "complete",
            },
        )
        graph.add_conditional_edges(
            "stage_prepare",
            self._route_after_prepare,
            {
                "stage_execute": "stage_execute",
                "blocked": "blocked",
            },
        )
        graph.add_edge("stage_execute", END)
        graph.add_edge("blocked", END)
        graph.add_edge("noop", END)
        graph.add_edge("complete", END)
        return graph.compile()

    def _append_timeline_event(
        self,
        state: dict[str, Any],
        *,
        event_type: str,
        status: str = "recorded",
        scope_type: str = "run",
        scope_path: list[str] | tuple[str, ...] | None = None,
        node_id: str = "",
        edge_id: str = "",
        phase_id: str = "",
        loop_frame_id: str = "",
        iteration_index: int = 0,
        revision_cycle_id: str = "",
        parallel_group_id: str = "",
        dispatch_id: str = "",
        request_id: str = "",
        result_record_id: str = "",
        payload_ref: str = "",
        payload: dict[str, Any] | None = None,
        checkpoint_ref: str = "",
        causal_event_ids: list[str] | tuple[str, ...] = (),
        idempotency_key: str = "",
    ) -> TimelineEvent | None:
        coordination_run_id = str(state.get("coordination_run_id") or "").strip()
        if not coordination_run_id:
            return None
        graph_id = _graph_id_from_state(state)
        event = self.timeline_ledger.append_event(
            coordination_run_id=coordination_run_id,
            root_task_run_id=str(state.get("root_task_run_id") or ""),
            graph_id=graph_id,
            event_type=event_type,
            status=status,
            scope_type=scope_type,
            scope_path=scope_path or ("run",),
            causal_event_ids=causal_event_ids,
            node_id=node_id,
            edge_id=edge_id,
            phase_id=phase_id,
            loop_frame_id=loop_frame_id,
            iteration_index=iteration_index,
            revision_cycle_id=revision_cycle_id,
            parallel_group_id=parallel_group_id,
            dispatch_id=dispatch_id,
            request_id=request_id,
            result_record_id=result_record_id,
            payload_ref=payload_ref,
            payload=payload or {},
            checkpoint_ref=checkpoint_ref,
            idempotency_key=idempotency_key,
        )
        state["timeline"] = self.timeline_ledger.snapshot(coordination_run_id, limit=80)
        return event

    def _attach_timeline_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        coordination_run_id = str(state.get("coordination_run_id") or "").strip()
        if not coordination_run_id:
            return state
        updated = dict(state or {})
        updated["timeline"] = self.timeline_ledger.snapshot(coordination_run_id, limit=80)
        return updated

    def _stage_scope(
        self,
        *,
        state: dict[str, Any],
        stage_id: str,
        contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(contract or dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {}))
        phase_id = str(payload.get("phase_id") or _runtime_node_value(state, stage_id, "phase_id") or "phase.unassigned")
        scope_path = ["run", phase_id]
        pending_inputs = dict(state.get("pending_inputs") or {})
        coordinate = _runtime_scope_coordinate_from_inputs(pending_inputs)
        volume_index = int(coordinate.get("volume_index") or 0)
        batch_start = int(coordinate.get("batch_start_index") or 0)
        batch_end = int(coordinate.get("batch_end_index") or 0)
        round_index = int(coordinate.get("round_index") or 0)
        scope_path.extend(_scope_path_segments_from_coordinate(coordinate))
        retry_index = int(dict(state.get("retry_counts") or {}).get(stage_id) or 0)
        if retry_index > 0:
            scope_path.append(f"retry[{retry_index}]")
        loop_index = int(coordinate.get("iteration_index") or 0)
        if loop_index > 0:
            scope_path.append(f"iteration[{loop_index}]")
        dependency_scope_key = _dependency_scope_key_from_inputs(pending_inputs)
        return {
            "scope_type": "stage",
            "scope_path": scope_path,
            "phase_id": phase_id,
            "iteration_index": loop_index,
            "volume_index": volume_index,
            "batch_start_index": batch_start,
            "batch_end_index": batch_end,
            "round_index": round_index,
            "dependency_scope_key": dependency_scope_key,
        }

    def _stage_accept(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        event = dict(state.get("current_event") or {})
        if str(event.get("event_type") or "") == "human_gate_resumed":
            return _resume_human_gate_state(state=state, event=event)
        stage_id = str(event.get("stage_id") or state.get("active_stage_id") or "").strip()
        if not stage_id:
            return {"diagnostics": {**dict(state.get("diagnostics") or {}), "accept_warning": "missing_stage_id"}}
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        request_payload = _active_execution_request_payload(state)
        node_id = str(contract.get("node_id") or stage_id)
        batch_runtime_state_for_result = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        ) or batch_runtime_state_from_diagnostics(dict(state.get("diagnostics") or {}))
        batch_result_execution = batch_execution_instance_for_result(
            runtime_state=batch_runtime_state_for_result,
            stage_id=stage_id,
            node_id=node_id,
            request_id=str(event.get("request_id") or ""),
            dispatch_event_id=str(event.get("dispatch_event_id") or ""),
            batch_execution_id=str(dict(event.get("diagnostics") or {}).get("unit_batch_execution_id") or ""),
            event_diagnostics=dict(event.get("diagnostics") or {}),
        ) if batch_runtime_state_for_result else {}
        if batch_result_execution and (
            not request_payload
            or str(request_payload.get("request_id") or "") != str(event.get("request_id") or "")
            or str(dict(request_payload.get("dispatch_context") or {}).get("dispatch_event_id") or "") != str(event.get("dispatch_event_id") or "")
        ):
            request_payload = _batch_execution_request_payload_from_state(
                state=state,
                stage_id=stage_id,
                node_id=node_id,
                batch_execution=batch_result_execution,
            ) or request_payload
        stale_result = _stale_result_reason(
            event=event,
            request_payload=request_payload,
            stage_id=stage_id,
            known_batch_execution=bool(batch_result_execution),
        )
        if stale_result:
            stale_event = self._append_timeline_event(
                state,
                event_type="stale_node_result_ignored",
                status="ignored",
                scope_type="stage",
                scope_path=list(dict(request_payload.get("dispatch_context") or {}).get("scope_path") or ["run"]),
                node_id=str(contract.get("node_id") or stage_id),
                phase_id=str(contract.get("phase_id") or ""),
                request_id=str(request_payload.get("request_id") or ""),
                payload={
                    "stage_id": stage_id,
                    "task_run_id": str(event.get("task_run_id") or ""),
                    "task_result_ref": str(event.get("task_result_ref") or ""),
                    "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
                    "reason": stale_result,
                    "event_request_id": str(event.get("request_id") or ""),
                    "active_request_id": str(request_payload.get("request_id") or ""),
                    "event_dispatch_event_id": str(event.get("dispatch_event_id") or ""),
                    "active_dispatch_event_id": str(dict(request_payload.get("dispatch_context") or {}).get("dispatch_event_id") or ""),
                },
                idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:stale:{event.get('task_result_ref') or event.get('agent_run_result_ref') or event.get('task_run_id')}",
            )
            stale_results = [dict(item) for item in list(state.get("stale_stage_results") or []) if isinstance(item, dict)]
            stale_results.append(dict(stale_event.to_dict() if stale_event is not None else {}))
            return {
                "stale_stage_results": stale_results,
                "node_work_order": dict(state.get("node_work_order") or {}),
                "node_execution_request": _active_execution_request_payload(state),
                "stage_execution_request": dict(state.get("stage_execution_request") or {}),
                "a2a_payload": dict(state.get("a2a_payload") or {}),
                "terminal_status": "stale_result_ignored",
                "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
                "diagnostics": {**dict(state.get("diagnostics") or {}), "last_stale_result_reason": stale_result},
            }
        stage_scope = self._stage_scope(state=state, stage_id=stage_id, contract=contract)
        review_gate_accepted = _review_gate_event_is_accepted(event=event, contract=contract)
        committed_identities = set(_committed_stage_identities(state))
        result_draft = build_node_result_acceptance_draft(
            state=state,
            event=event,
            stage_id=stage_id,
            contract=contract,
            request_payload=request_payload,
            stage_scope=stage_scope,
            event_accepted_by_policy=review_gate_accepted,
            committed_identities=committed_identities,
        )
        result_request_payload = result_draft.result_request_payload
        stage_scope = self._stage_scope(
            state={
                **dict(state),
                "pending_inputs": dict(result_request_payload.get("explicit_inputs") or state.get("pending_inputs") or {}),
            },
            stage_id=stage_id,
            contract=contract,
        )
        artifact_refs = result_draft.artifact_refs
        trace_refs = result_draft.trace_refs
        output_bundle = result_draft.output_bundle
        stage_outputs = result_draft.stage_outputs
        required_artifact_outputs_satisfied = result_draft.required_artifact_outputs_satisfied
        requires_file_artifact_refs = result_draft.requires_file_artifact_refs
        output_mappings = result_draft.output_mappings
        accepted = result_draft.accepted
        dispatch_context = result_draft.dispatch_context
        commit_identity = result_draft.commit_identity
        if accepted and commit_identity and commit_identity in committed_identities:
            duplicate_event = self._append_timeline_event(
                state,
                event_type="duplicate_stage_commit_ignored",
                status="ignored",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                request_id=str(result_request_payload.get("request_id") or ""),
                payload={
                    "stage_id": stage_id,
                    "commit_identity": commit_identity,
                    "task_run_id": str(event.get("task_run_id") or ""),
                    "task_result_ref": str(event.get("task_result_ref") or ""),
                    "artifact_refs": artifact_refs,
                },
                idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:duplicate_commit:{commit_identity}",
            )
            duplicate_commits = [dict(item) for item in list(state.get("duplicate_stage_commits") or []) if isinstance(item, dict)]
            duplicate_commits.append(dict(duplicate_event.to_dict() if duplicate_event is not None else {}))
            return {
                "duplicate_stage_commits": duplicate_commits,
                "committed_stage_identities": sorted(committed_identities),
                **_execution_boundary_cleared(),
                "terminal_status": "duplicate_commit_ignored",
                "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
                "diagnostics": {**dict(state.get("diagnostics") or {}), "last_duplicate_commit_identity": commit_identity},
            }
        result_event = self._append_timeline_event(
            state,
            event_type="node_result_received",
            status="accepted" if accepted else "rejected",
            scope_type=str(stage_scope.get("scope_type") or "stage"),
            scope_path=list(stage_scope.get("scope_path") or ["run"]),
            node_id=node_id,
            phase_id=str(stage_scope.get("phase_id") or ""),
            iteration_index=int(stage_scope.get("iteration_index") or 0),
            request_id=str(result_request_payload.get("request_id") or ""),
            payload={
                "stage_id": stage_id,
                "task_run_id": str(event.get("task_run_id") or ""),
                "task_result_ref": str(event.get("task_result_ref") or ""),
                "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
                "artifact_refs": artifact_refs,
                "trace_refs": trace_refs,
                "accepted": accepted,
                "dispatch_event_id": str(dispatch_context.get("dispatch_event_id") or ""),
            },
            causal_event_ids=[str(dispatch_context.get("dispatch_event_id") or "")] if dispatch_context.get("dispatch_event_id") else (),
            idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:result:{event.get('task_result_ref') or event.get('agent_run_result_ref') or event.get('task_run_id')}",
        )
        result_event_payload = result_event.to_dict() if result_event is not None else {}
        stage_results = dict(state.get("stage_results") or {})
        stage_result_payload = {
            "task_run_id": str(event.get("task_run_id") or ""),
            "task_ref": str(contract.get("task_ref") or event.get("task_ref") or ""),
            "task_result_ref": str(event.get("task_result_ref") or ""),
            "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
            "artifact_refs": artifact_refs,
            "trace_refs": trace_refs,
            "outputs": stage_outputs,
            "diagnostics": dict(event.get("diagnostics") or {}),
            "accepted": accepted,
        }
        working_memory_operations = list(state.get("working_memory_operations") or [])
        if bool(event.get("accepted") is True):
            write_operation = self._submit_stage_working_memory_candidates(
                state=state,
                stage_id=stage_id,
                contract=contract,
                event=event,
                artifact_refs=artifact_refs,
                output_bundle=output_bundle,
                execution_context=result_request_payload,
                source_clock=str(result_event_payload.get("event_id") or ""),
                source_clock_seq=int(result_event_payload.get("clock_seq") or 0),
            )
            if write_operation:
                stage_result_payload["working_memory_refs"] = list(write_operation.get("created_working_memory_refs") or [])
                working_memory_operations.append(
                    _timeline_working_memory_operation(
                        write_operation,
                        existing_operations=working_memory_operations,
                    )
                )
                for operation in self._resolve_stage_working_memory_handoffs(
                    state=state,
                    stage_id=stage_id,
                    created_working_memory_refs=list(write_operation.get("created_working_memory_refs") or []),
                    event=event,
                ):
                    if not isinstance(operation, dict):
                        continue
                    working_memory_operations.append(
                        _timeline_working_memory_operation(
                            operation,
                            existing_operations=working_memory_operations,
                        )
                    )
            commit_operation = self._commit_stage_working_memory_decisions(
                state=state,
                stage_id=stage_id,
                contract=contract,
                event=event,
                output_bundle=output_bundle,
                execution_context=result_request_payload,
                current_stage_candidate_refs=list(stage_result_payload.get("working_memory_refs") or []),
                source_clock=str(result_event_payload.get("event_id") or ""),
                source_clock_seq=int(result_event_payload.get("clock_seq") or 0),
            )
            if commit_operation:
                working_memory_operations.append(
                    _timeline_working_memory_operation(
                        commit_operation,
                        existing_operations=working_memory_operations,
                    )
                )
        node_statuses = dict(state.get("node_statuses") or {})
        created_memory_refs = _string_list(stage_result_payload.get("working_memory_refs"))
        committed_memory_refs = [
            ref
            for operation in working_memory_operations
            if isinstance(operation, dict) and str(operation.get("operation") or "") == "memory_commit"
            for ref in _string_list(operation.get("accepted_working_memory_refs"))
        ]
        memory_candidates = [
            {"memory_ref": ref, "source": "working_memory_candidate"}
            for ref in created_memory_refs
        ]
        standard_result_package = build_standard_node_result_package(
            request_payload=result_request_payload,
            event=event,
            outputs=stage_outputs,
            artifact_refs=artifact_refs,
            memory_candidates=memory_candidates,
        )
        stage_result_payload["standard_result_package"] = standard_result_package.to_dict()
        result_record = build_timeline_result_record(
            request_payload=result_request_payload,
            result_event=result_event_payload,
            stage_id=stage_id,
            node_id=node_id,
            accepted=accepted,
            artifact_refs=artifact_refs,
            trace_refs=trace_refs,
            memory_write_candidate_refs=created_memory_refs,
            memory_commit_refs=committed_memory_refs,
            validation_result=result_draft.validation_result(
                event_accepts_artifacts=bool(event.get("accepted") is True) or review_gate_accepted,
            ),
        )
        result_record_payload = result_record.to_dict()
        stage_result_payload["timeline_result_record"] = result_record_payload
        stage_results_by_instance = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results_by_instance") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        stage_results_by_instance[result_record.result_record_id] = dict(stage_result_payload)
        timeline_result_records = [dict(item) for item in list(state.get("timeline_result_records") or []) if isinstance(item, dict)]
        timeline_result_records.append(result_record_payload)
        result_record_index = {
            str(key): dict(value)
            for key, value in dict(state.get("result_record_index") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        result_record_index[result_record.result_record_id] = result_record_payload
        latest_stage_result_records = {
            str(key): str(value)
            for key, value in dict(state.get("latest_stage_result_records") or {}).items()
            if str(key) and str(value)
        }
        accepted_result_records_by_scope = {
            str(scope): {str(stage): str(record_id) for stage, record_id in dict(records or {}).items() if str(stage) and str(record_id)}
            for scope, records in dict(state.get("accepted_result_records_by_scope") or {}).items()
            if str(scope) and isinstance(records, dict)
        }
        if accepted:
            stage_results[stage_id] = dict(stage_result_payload)
            latest_stage_result_records[stage_id] = result_record.result_record_id
            scope_records = dict(accepted_result_records_by_scope.get(result_record.scope_key) or {})
            scope_records[stage_id] = result_record.result_record_id
            accepted_result_records_by_scope[result_record.scope_key] = scope_records
            dependency_scope_key = str(result_record.dependency_scope_key or result_record.scope_key or "")
            if dependency_scope_key:
                dependency_scope_records = dict(accepted_result_records_by_scope.get(dependency_scope_key) or {})
                dependency_scope_records[stage_id] = result_record.result_record_id
                accepted_result_records_by_scope[dependency_scope_key] = dependency_scope_records
            self._formalize_stage_handoffs(
                state=state,
                stage_id=stage_id,
                node_id=node_id,
                contract=contract,
                event=event,
                result_record_payload=result_record_payload,
                stage_result_payload=stage_result_payload,
            )
        self._append_timeline_event(
            state,
            event_type="node_timeline_result_recorded",
            status=result_record.status,
            scope_type=str(stage_scope.get("scope_type") or "stage"),
            scope_path=list(stage_scope.get("scope_path") or ["run"]),
            node_id=node_id,
            phase_id=str(stage_scope.get("phase_id") or ""),
            iteration_index=int(stage_scope.get("iteration_index") or 0),
            request_id=str(request_payload.get("request_id") or ""),
            result_record_id=result_record.result_record_id,
            payload=result_record_payload,
            causal_event_ids=[str(result_event_payload.get("event_id") or "")] if result_event_payload.get("event_id") else (),
            idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:timeline_result:{result_record.result_record_id}",
        )
        retry_counts = dict(state.get("retry_counts") or {})
        retry_stage_id = ""
        terminal_status = ""
        technical_retry = is_technical_execution_failure(dict(event.get("diagnostics") or {}))
        revision_packets = [dict(item) for item in list(state.get("revision_packets") or []) if isinstance(item, dict)]
        if accepted:
            node_statuses[stage_id] = "completed"
            node_statuses = _reset_failed_direct_downstream_after_success(
                state=state,
                node_statuses=node_statuses,
                stage_id=stage_id,
            )
        elif technical_retry:
            node_statuses[stage_id] = "pending"
            retry_stage_id = stage_id
        elif _stage_quality_retry_target(contract=contract, stage_id=stage_id, event=event):
            target_stage_id = _stage_quality_retry_target(contract=contract, stage_id=stage_id, event=event)
            node_statuses[stage_id] = "pending"
            retry_stage_id = target_stage_id
            retry_counts[stage_id] = int(retry_counts.get(stage_id) or 0) + 1
            state["pending_inputs"] = _pending_inputs_for_stage_quality_retry(
                state=state,
                stage_id=stage_id,
                contract=contract,
                event=event,
            )
        elif _review_revision_target(contract=contract, stage_id=stage_id):
            target_stage_id = _review_revision_target(contract=contract, stage_id=stage_id)
            node_statuses[stage_id] = "failed"
            node_statuses[target_stage_id] = "pending"
            retry_stage_id = target_stage_id
            revision_packet = build_revision_packet_from_review(
                state=state,
                review_stage_id=stage_id,
                target_stage_id=target_stage_id,
                event=event,
                accepted=accepted,
            )
            revision_packets.append(revision_packet)
            self._append_timeline_event(
                state,
                event_type="revision_packet_created",
                status="open",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                revision_cycle_id=str(revision_packet.get("revision_cycle_id") or ""),
                payload=revision_packet,
                causal_event_ids=[result_record.result_record_id],
                idempotency_key=f"{state.get('coordination_run_id')}:{revision_packet.get('revision_packet_id')}",
            )
            state["pending_inputs"] = _pending_inputs_for_revision_retry(
                state=state,
                review_stage_id=stage_id,
                target_stage_id=target_stage_id,
                event=event,
            )
        elif _retry_allowed(contract=contract, retry_counts=retry_counts, stage_id=stage_id):
            retry_counts[stage_id] = int(retry_counts.get(stage_id) or 0) + 1
            node_statuses[stage_id] = "pending"
            retry_stage_id = stage_id
        elif _human_gate_required(contract, state=state):
            node_statuses[stage_id] = "waiting_for_human"
            terminal_status = "waiting_for_human"
        else:
            node_statuses[stage_id] = "failed"
            terminal_status = "failed"
        if terminal_status == "waiting_for_human":
            contract_status = _set_contract_node_status(
                dict(state.get("contract_status") or {}),
                stage_id=stage_id,
                node_status_value="human_gate",
                accepted=False,
                task_result_ref=str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
                artifact_refs=artifact_refs,
                missing_required_inputs=[],
                diagnostics={"reason": "acceptance_failed_waiting_for_human"},
            )
        elif retry_stage_id:
            contract_status = _set_contract_node_status(
                dict(state.get("contract_status") or {}),
                stage_id=stage_id,
                node_status_value="pending_retry",
                accepted=False,
                task_result_ref=str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
                artifact_refs=artifact_refs,
                missing_required_inputs=[],
                diagnostics={
                    "retry_count": retry_counts.get(stage_id),
                    "reason": "technical_retry" if technical_retry else "acceptance_failed_retry",
                },
            )
        else:
            contract_status = _accept_contract_status(
                dict(state.get("contract_status") or {}),
                stage_id=stage_id,
                accepted=accepted,
                task_result_ref=str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
                artifact_refs=artifact_refs,
                missing_required_inputs=[],
            )
        committed_stage_identities = sorted({*committed_identities, commit_identity}) if accepted and commit_identity else sorted(committed_identities)
        diagnostics = {**dict(state.get("diagnostics") or {}), "last_accepted_stage_id": stage_id}
        if accepted and commit_identity:
            diagnostics["last_committed_stage_identity"] = commit_identity
        if retry_stage_id:
            diagnostics["retry_counts"] = retry_counts
        else:
            diagnostics.pop("retry_counts", None)
        if technical_retry:
            diagnostics["last_technical_retry_stage_id"] = stage_id
            diagnostics["last_technical_retry_reason"] = str(dict(event.get("diagnostics") or {}).get("terminal_reason") or "executor_failed")
        human_gate = dict(state.get("human_gate") or {})
        if terminal_status == "waiting_for_human":
            human_gate = {
                **human_gate,
                "status": "waiting",
                "stage_id": stage_id,
                "pending_stage_id": stage_id,
                "task_ref": str(contract.get("task_ref") or event.get("task_ref") or ""),
                "reason": "acceptance_failed",
                "original_event": dict(event),
                "created_at": time.time(),
            }
            diagnostics["human_gate"] = {key: value for key, value in human_gate.items() if key != "original_event"}
            self._append_timeline_event(
                state,
                event_type="human_gate_opened",
                status="waiting",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                payload={key: value for key, value in human_gate.items() if key != "original_event"},
                causal_event_ids=[result_record.result_record_id],
            )
        elif accepted or retry_stage_id or terminal_status == "failed":
            human_gate = {**human_gate, "status": "cleared"} if human_gate else {}
        loop_updates = _loop_after_stage_accept(
            state=state,
            stage_id=stage_id,
            accepted=accepted,
            contract=contract,
            event=event,
        )
        batch_runtime_state = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        ) or batch_runtime_state_from_diagnostics(dict(state.get("diagnostics") or {}))
        batch_updates: dict[str, Any] = {}
        if batch_runtime_state and node_has_batch_plan(
            runtime_state=batch_runtime_state,
            stage_id=stage_id,
            node_id=node_id,
        ):
            batch_runtime_state = transition_batch_after_stage_result(
                runtime_state=batch_runtime_state,
                stage_id=stage_id,
                node_id=node_id,
                accepted=accepted,
                task_result_ref=str(event.get("task_result_ref") or ""),
                agent_run_result_ref=str(event.get("agent_run_result_ref") or ""),
                request_id=str(event.get("request_id") or result_request_payload.get("request_id") or ""),
                dispatch_event_id=str(
                    event.get("dispatch_event_id")
                    or dict(result_request_payload.get("dispatch_context") or {}).get("dispatch_event_id")
                    or ""
                ),
                batch_execution_id=str(
                    dict(event.get("diagnostics") or {}).get("unit_batch_execution_id")
                    or dict(result_request_payload.get("explicit_inputs") or {}).get("unit_batch_execution_id")
                    or dict(result_request_payload.get("dispatch_context") or {}).get("batch_execution_id")
                    or ""
                ),
                event_diagnostics=dict(event.get("diagnostics") or {}),
            )
            batch_updates["batch_lifecycle_runtime_state"] = batch_runtime_state
            diagnostics["batch_lifecycle_runtime_state"] = batch_runtime_state
            diagnostics["last_batch_transition"] = dict(dict(batch_runtime_state.get("diagnostics") or {}).get("last_transition") or {})
            if node_has_failed_batch(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id):
                node_statuses[stage_id] = "failed"
                terminal_status = "failed"
                loop_updates = {
                    **dict(loop_updates or {}),
                    "node_statuses": node_statuses,
                    "terminal_status": "failed",
                }
            elif node_has_technical_blocked_batch(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id):
                node_statuses[stage_id] = "blocked"
                terminal_status = "blocked"
                retry_stage_id = ""
                diagnostics["batch_node_continue"] = False
                diagnostics["batch_node_blocked"] = True
                diagnostics["batch_node_blocked_reason"] = "technical_retry_exhausted"
                loop_updates = {
                    **dict(loop_updates or {}),
                    "node_statuses": node_statuses,
                    "terminal_status": "blocked",
                    "pending_inputs": dict(state.get("pending_inputs") or {}),
                    "diagnostics": {
                        **dict(loop_updates.get("diagnostics") or {}),
                        "batch_node_blocked": True,
                        "batch_node_blocked_reason": "technical_retry_exhausted",
                    },
                }
            elif node_has_more_batch_work(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id):
                node_statuses[stage_id] = "pending"
                terminal_status = ""
                retry_stage_id = stage_id
                diagnostics["batch_node_continue"] = True
                if (
                    node_has_active_batch_work(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id)
                    and not node_has_dispatchable_batch_work(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id)
                ):
                    diagnostics["batch_node_continue_reason"] = "waiting_for_active_batch_result"
                loop_updates = {
                    **dict(loop_updates or {}),
                    "node_statuses": node_statuses,
                    "terminal_status": "",
                    "pending_inputs": dict(state.get("pending_inputs") or {}),
                    "diagnostics": {
                        **dict(loop_updates.get("diagnostics") or {}),
                        "batch_node_continue": True,
                    },
                }
            elif node_all_batches_committed(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id):
                stage_result_payload["batch_committed_results"] = node_committed_batch_refs(
                    runtime_state=batch_runtime_state,
                    stage_id=stage_id,
                    node_id=node_id,
                )
                stage_results[stage_id] = dict(stage_result_payload)
                node_statuses[stage_id] = "completed"
                loop_updates = {
                    **dict(loop_updates or {}),
                    "node_statuses": node_statuses,
                    "terminal_status": "",
                }
        artifact_payloads = [{"stage_id": stage_id, "ref": ref, "ref_kind": "artifact"} for ref in artifact_refs]
        return {
            "stage_results": stage_results,
            "stage_results_by_instance": stage_results_by_instance,
            "committed_stage_identities": committed_stage_identities,
            "node_statuses": dict(loop_updates.get("node_statuses") or node_statuses),
            **batch_updates,
            "retry_counts": retry_counts,
            "retry_stage_id": retry_stage_id,
            "contract_status": contract_status,
            "human_gate": human_gate,
            "artifact_refs": artifact_payloads,
            "working_memory_operations": working_memory_operations,
            "revision_packets": revision_packets,
            "timeline_result_records": timeline_result_records,
            "result_record_index": result_record_index,
            "latest_stage_result_records": latest_stage_result_records,
            "accepted_result_records_by_scope": accepted_result_records_by_scope,
            "final_result_ref": str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
            **_execution_boundary_cleared(),
            "terminal_status": str(loop_updates.get("terminal_status") if "terminal_status" in loop_updates else terminal_status),
            "pending_inputs": dict(loop_updates.get("pending_inputs") or state.get("pending_inputs") or {}),
            "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
            "diagnostics": {**diagnostics, **dict(loop_updates.get("diagnostics") or {})},
        }

    def _record_scheduler_evaluation(
        self,
        *,
        state: dict[str, Any],
        scheduler_update: dict[str, Any],
        node_statuses: dict[str, str],
    ) -> dict[str, Any]:
        payload = {
            "ready_node_ids": list(scheduler_update.get("ready_nodes") or []),
            "blocked_node_ids": list(scheduler_update.get("blocked_nodes") or []),
            "running_node_ids": list(scheduler_update.get("running_nodes") or []),
            "completed_node_ids": list(scheduler_update.get("completed_nodes") or []),
            "failed_node_ids": list(scheduler_update.get("failed_nodes") or []),
            "terminal_status": str(scheduler_update.get("terminal_status") or ""),
            "node_statuses": dict(node_statuses or {}),
        }
        event = self._append_timeline_event(
            state,
            event_type="scheduler_evaluated",
            status="completed",
            payload=payload,
            idempotency_key="",
        )
        batch_runtime_state = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        ) or batch_runtime_state_from_diagnostics(dict(state.get("diagnostics") or {}))
        diagnostics = {
            **dict(scheduler_update.get("diagnostics") or {}),
            "latest_scheduler_event_id": str(event.event_id if event is not None else ""),
            **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
        }
        return {
            **scheduler_update,
            **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
            "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
            "diagnostics": diagnostics,
        }

    def _formalize_stage_handoffs(
        self,
        *,
        state: dict[str, Any],
        stage_id: str,
        node_id: str,
        contract: dict[str, Any],
        event: dict[str, Any],
        result_record_payload: dict[str, Any],
        stage_result_payload: dict[str, Any],
    ) -> None:
        coordination_run_id = str(state.get("coordination_run_id") or "").strip()
        task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not coordination_run_id or not task_run_id:
            return
        source_agent_run_ref = self._resolve_source_agent_run_ref(task_run_id=task_run_id, event=event)
        if not source_agent_run_ref:
            source_agent_run_ref = self._resolve_stage_agent_run_ref(
                task_run_id=task_run_id,
                coordination_run_id=coordination_run_id,
                stage_id=stage_id,
                agent_id=str(contract.get("agent_id") or ""),
            )
        if not source_agent_run_ref:
            source_agent_run_ref = f"stage:{stage_id}"
        outgoing_edges = [
            dict(item)
            for item in _graph_edges(state)
            if str(item.get("source_node_id") or item.get("from") or item.get("source") or "") in {node_id, stage_id}
        ]
        if not outgoing_edges:
            return
        existing_handoff_ids = {
            str(item.handoff_id or "")
            for item in self.state_index.list_coordination_handoffs(coordination_run_id)
            if str(item.handoff_id or "")
        }
        stage_contracts = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_contracts") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        manifest_edge_contracts = {
            str(item.get("edge_id") or f"{item.get('source_node_id', '')}->{item.get('target_node_id', '')}"): dict(item)
            for item in list(dict(state.get("contract_manifest") or {}).get("edge_handoff_contracts") or [])
            if isinstance(item, dict)
        }
        payload_ref = str(result_record_payload.get("result_record_id") or stage_result_payload.get("task_result_ref") or "")
        for edge in outgoing_edges:
            target_stage_id = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
            if not target_stage_id:
                continue
            edge_id = str(edge.get("edge_id") or f"{node_id}->{target_stage_id}").strip()
            target_contract = dict(stage_contracts.get(target_stage_id) or {})
            target_agent_run_ref = self._resolve_stage_agent_run_ref(
                task_run_id=task_run_id,
                coordination_run_id=coordination_run_id,
                stage_id=target_stage_id,
                agent_id=str(target_contract.get("agent_id") or ""),
            ) or f"stage:{target_stage_id}"
            edge_contract = dict(manifest_edge_contracts.get(edge_id) or {})
            handoff_id = f"handoffenv:{_short_hash({'coordination_run_id': coordination_run_id, 'edge_id': edge_id, 'payload_ref': payload_ref, 'source_agent_run_ref': source_agent_run_ref, 'target_agent_run_ref': target_agent_run_ref})}"
            if handoff_id in existing_handoff_ids:
                continue
            envelope = AgentHandoffEnvelope(
                handoff_id=handoff_id,
                task_run_id=task_run_id,
                coordination_run_id=coordination_run_id,
                source_agent_run_ref=source_agent_run_ref,
                target_agent_run_ref=target_agent_run_ref,
                protocol_id=str(dict(dict(state.get("diagnostics") or {}).get("a2a_runtime") or {}).get("protocol_id") or ""),
                message_type=str(edge_contract.get("message_type") or edge.get("message_type") or edge.get("policy") or "structured_handoff"),
                payload_ref=payload_ref,
                ack_state="pending" if bool(edge.get("ack_required", True) is not False) else "not_required",
                created_at=time.time(),
                diagnostics={
                    "coordination_engine": "harness.graph_coordination_engine",
                    "source_stage_id": stage_id,
                    "source_node_id": node_id,
                    "target_stage_id": target_stage_id,
                    "target_node_id": str(target_contract.get("node_id") or target_stage_id),
                    "edge_id": edge_id,
                    "task_ref": str(contract.get("task_ref") or event.get("task_ref") or ""),
                    "task_result_ref": str(event.get("task_result_ref") or ""),
                    "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
                    "artifact_refs": list(stage_result_payload.get("artifact_refs") or []),
                    "contract_refs": list(edge_contract.get("contract_refs") or []),
                    "handoff_policy": str(edge_contract.get("handoff_policy") or edge.get("policy") or ""),
                },
            )
            self.state_index.upsert_handoff_envelope(envelope)
            handoff_envelopes = [dict(item) for item in list(state.get("handoff_envelopes") or []) if isinstance(item, dict)]
            handoff_envelopes.append(envelope.to_dict())
            state["handoff_envelopes"] = handoff_envelopes
            self.event_log.append(
                task_run_id,
                "handoff_envelope_created",
                payload={"handoff_envelope": envelope.to_dict()},
                refs={
                    "coordination_run_ref": coordination_run_id,
                    "handoff_ref": envelope.handoff_id,
                    "source_agent_run_ref": source_agent_run_ref,
                    "target_agent_run_ref": target_agent_run_ref,
                },
            )
            existing_handoff_ids.add(handoff_id)

    def _resolve_source_agent_run_ref(self, *, task_run_id: str, event: dict[str, Any]) -> str:
        agent_run_result_ref = str(event.get("agent_run_result_ref") or "").strip()
        if agent_run_result_ref.startswith("agresult:"):
            return agent_run_result_ref[len("agresult:") :].strip()
        if not agent_run_result_ref:
            return ""
        for result in self.state_index.list_task_agent_run_results(task_run_id):
            if str(result.agent_run_result_id or "") == agent_run_result_ref:
                return str(result.agent_run_id or "").strip()
        return ""

    def _resolve_stage_agent_run_ref(
        self,
        *,
        task_run_id: str,
        coordination_run_id: str,
        stage_id: str,
        agent_id: str,
    ) -> str:
        stage_agent_id = str(agent_id or "").strip()
        task_agent_runs = list(self.state_index.list_task_agent_runs(task_run_id))
        prioritized = [
            item
            for item in task_agent_runs
            if str(item.coordination_run_ref or "").strip() == coordination_run_id
        ] or task_agent_runs
        if stage_agent_id:
            for agent_run in prioritized:
                if str(agent_run.agent_id or "").strip() == stage_agent_id:
                    return str(agent_run.agent_run_id or "").strip()
        for agent_run in prioritized:
            diagnostics = dict(agent_run.diagnostics or {})
            if str(diagnostics.get("stage_id") or diagnostics.get("node_id") or "").strip() == stage_id:
                return str(agent_run.agent_run_id or "").strip()
        return str(prioritized[0].agent_run_id or "").strip() if prioritized else ""

    def _route_next(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        if not order:
            return {"terminal_status": "blocked", "missing_required_inputs": ["stage_order"]}
        if str(state.get("terminal_status") or "") == "stale_result_ignored":
            return {
                "terminal_status": "stale_result_ignored",
                **_execution_boundary_preserved(state),
                "ready_nodes": list(state.get("ready_nodes") or []),
                "blocked_nodes": list(state.get("blocked_nodes") or []),
                "running_nodes": list(state.get("running_nodes") or []),
                "waiting_nodes": list(state.get("waiting_nodes") or []),
                "completed_nodes": list(state.get("completed_nodes") or []),
                "failed_nodes": list(state.get("failed_nodes") or []),
                "diagnostics": dict(state.get("diagnostics") or {}),
            }
        if str(state.get("terminal_status") or "") == "duplicate_commit_ignored":
            return {
                "terminal_status": "duplicate_commit_ignored",
                **_execution_boundary_preserved(state),
                "ready_nodes": list(state.get("ready_nodes") or []),
                "blocked_nodes": list(state.get("blocked_nodes") or []),
                "running_nodes": list(state.get("running_nodes") or []),
                "waiting_nodes": list(state.get("waiting_nodes") or []),
                "completed_nodes": list(state.get("completed_nodes") or []),
                "failed_nodes": list(state.get("failed_nodes") or []),
                "diagnostics": dict(state.get("diagnostics") or {}),
            }
        if str(state.get("terminal_status") or "") == "waiting_for_human":
            update = _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="waiting_for_human",
            )
            return self._record_scheduler_evaluation(state=state, scheduler_update=update, node_statuses=dict(state.get("node_statuses") or {}))
        if str(state.get("terminal_status") or "") == "waiting_for_batch_result":
            update = _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="waiting_for_batch_result",
            )
            return self._record_scheduler_evaluation(state=state, scheduler_update=update, node_statuses=dict(state.get("node_statuses") or {}))
        if str(state.get("terminal_status") or "") == "failed":
            update = _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="failed",
            )
            return self._record_scheduler_evaluation(state=state, scheduler_update=update, node_statuses=dict(state.get("node_statuses") or {}))
        node_statuses = dict(state.get("node_statuses") or {})
        retry_stage_id = str(state.get("retry_stage_id") or "").strip()
        if retry_stage_id and retry_stage_id in order and node_statuses.get(retry_stage_id) not in {"completed", "failed"}:
            contracts = dict(state.get("stage_contracts") or {})
            contract = dict(contracts.get(retry_stage_id) or {})
            node_statuses[retry_stage_id] = "running"
            next_sets = _scheduler_node_sets(
                order=order,
                node_statuses=node_statuses,
                state=state,
            )
            diagnostics = dict(state.get("diagnostics") or {})
            result = {
                **next_sets,
                "active_stage_id": retry_stage_id,
                "active_node_id": str(contract.get("node_id") or retry_stage_id),
                "active_task_ref": str(contract.get("task_ref") or ""),
                "node_statuses": node_statuses,
                "retry_stage_id": "",
                "terminal_status": "",
                "missing_required_inputs": [],
                "diagnostics": {**dict(next_sets.get("diagnostics") or {}), **diagnostics},
            }
            return self._record_scheduler_evaluation(state=state, scheduler_update=result, node_statuses=node_statuses)
        sets = _scheduler_node_sets(
            order=order,
            node_statuses=node_statuses,
            state=state,
        )
        ready = list(sets.get("ready_nodes") or [])
        if not ready and sets.get("terminal_status"):
            return self._record_scheduler_evaluation(state=state, scheduler_update=sets, node_statuses=node_statuses)
        if not ready:
            blocked_nodes = [node for node in order if node_statuses.get(node) not in {"completed", "failed"}]
            result = {
                **sets,
                "terminal_status": "blocked",
                "blocked_nodes": blocked_nodes,
                "missing_required_inputs": [f"upstream:{node}" for node in blocked_nodes],
            }
            return self._record_scheduler_evaluation(state=state, scheduler_update=result, node_statuses=node_statuses)
        preferred_stage = str(dict(dict(state.get("diagnostics") or {}).get("runtime_loop") or {}).get("preferred_next_stage_id") or "").strip()
        if preferred_stage and preferred_stage in ready:
            ready = [preferred_stage, *[item for item in ready if item != preferred_stage]]
        next_stage = ready[0]
        contracts = dict(state.get("stage_contracts") or {})
        contract = dict(contracts.get(next_stage) or {})
        node_statuses[next_stage] = "running"
        next_sets = _scheduler_node_sets(
            order=order,
            node_statuses=node_statuses,
            state=state,
        )
        result = {
            **next_sets,
            "active_stage_id": next_stage,
            "active_node_id": str(contract.get("node_id") or next_stage),
            "active_task_ref": str(contract.get("task_ref") or ""),
            "node_statuses": node_statuses,
            "terminal_status": "",
            "missing_required_inputs": [],
        }
        return self._record_scheduler_evaluation(state=state, scheduler_update=result, node_statuses=node_statuses)

    def _stage_prepare(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        stage_id = str(state.get("active_stage_id") or "").strip()
        contract_payload = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        if not contract_payload:
            return {"terminal_status": "blocked", "missing_required_inputs": [f"stage_contract:{stage_id}"]}
        contract = _contract_from_payload(contract_payload)
        current_event = dict(state.get("current_event") or {})
        source_stage_id = str(current_event.get("stage_id") or "").strip()
        source_contract = dict(dict(state.get("stage_contracts") or {}).get(source_stage_id) or {})
        current_task_ref = str(source_contract.get("task_ref") or current_event.get("task_ref") or "")
        current_task_result = {
            **dict(state.get("current_task_result") or {}),
            "output_refs": list(current_event.get("artifact_refs") or []),
            "result_refs": [str(current_event.get("task_result_ref") or "")],
        }
        stage_outputs = _collect_stage_outputs(dict(state.get("stage_results") or {}))
        inherited_inputs = _normalize_pending_inputs_with_runtime_loop_policy(
            state=state,
            pending_inputs=dict(state.get("pending_inputs") or {}),
            preserve_existing_batch_scope=True,
        )
        binding = self.input_binder.bind(
            stage_contract=contract,
            current_task_result=current_task_result,
            current_task_ref=current_task_ref,
            stage_outputs=stage_outputs,
            inherited_inputs=inherited_inputs,
            artifact_root=str(inherited_inputs.get("artifact_root") or ""),
        )
        explicit_inputs = _normalize_pending_inputs_with_runtime_loop_policy(
            state=state,
            pending_inputs=dict(binding.explicit_inputs),
            preserve_existing_batch_scope=True,
        )
        batch_runtime_state = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        ) or batch_runtime_state_from_diagnostics(dict(state.get("diagnostics") or {}))
        selected_batch: dict[str, Any] = {}
        if binding.blocked:
            node_statuses = dict(state.get("node_statuses") or {})
            node_statuses[stage_id] = "blocked"
            contract_status = _accept_contract_status(
                dict(state.get("contract_status") or {}),
                stage_id=stage_id,
                accepted=False,
                task_result_ref="",
                artifact_refs=[],
                missing_required_inputs=list(binding.missing_required_inputs),
            )
            return {
                "pending_inputs": explicit_inputs,
                "missing_required_inputs": list(binding.missing_required_inputs),
                "terminal_status": "blocked",
                "node_statuses": node_statuses,
                "contract_status": contract_status,
                **_scheduler_node_sets(
                    order=[str(item) for item in list(state.get("stage_order") or []) if str(item)],
                    node_statuses=node_statuses,
                    state=state,
                    terminal_status="blocked",
                ),
                "diagnostics": {**dict(state.get("diagnostics") or {}), "binding": dict(binding.diagnostics)},
            }
        if batch_runtime_state and node_has_batch_plan(
            runtime_state=batch_runtime_state,
            stage_id=stage_id,
            node_id=str(contract_payload.get("node_id") or stage_id),
        ):
            node_id = str(contract_payload.get("node_id") or stage_id)
            batch_runtime_state, selected_batch = select_batch_for_stage(
                runtime_state=batch_runtime_state,
                stage_id=stage_id,
                node_id=node_id,
            )
            if not selected_batch:
                node_statuses = dict(state.get("node_statuses") or {})
                node_statuses[stage_id] = "waiting"
                wait_reason = (
                    "batch_parallel_capacity_reached"
                    if node_has_active_batch_work(runtime_state=batch_runtime_state, stage_id=stage_id, node_id=node_id)
                    else "batch_no_dispatchable_work"
                )
                return {
                    "pending_inputs": explicit_inputs,
                    "missing_required_inputs": [],
                    "terminal_status": "waiting_for_batch_result",
                    "node_statuses": node_statuses,
                    "batch_lifecycle_runtime_state": batch_runtime_state,
                    **_scheduler_node_sets(
                        order=[str(item) for item in list(state.get("stage_order") or []) if str(item)],
                        node_statuses=node_statuses,
                        state={**dict(state), "batch_lifecycle_runtime_state": batch_runtime_state},
                        terminal_status="waiting_for_batch_result",
                    ),
                    "diagnostics": {
                        **dict(state.get("diagnostics") or {}),
                        "binding": dict(binding.diagnostics),
                        "batch_lifecycle_runtime_state": batch_runtime_state,
                        "batch_dispatch_wait_reason": wait_reason,
                    },
                }
            explicit_inputs = apply_batch_to_pending_inputs(
                pending_inputs=explicit_inputs,
                batch_state=selected_batch,
            )
        return {
            "pending_inputs": explicit_inputs,
            "missing_required_inputs": [],
            "batch_lifecycle_runtime_state": batch_runtime_state or dict(state.get("batch_lifecycle_runtime_state") or {}),
            "diagnostics": {
                **dict(state.get("diagnostics") or {}),
                "binding": dict(binding.diagnostics),
                **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
                **({"active_batch": selected_batch} if selected_batch else {}),
            },
        }

    def _stage_execute(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        stage_id = str(state.get("active_stage_id") or "").strip()
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        explicit_inputs = _normalize_pending_inputs_with_runtime_loop_policy(
            state=state,
            pending_inputs=dict(state.get("pending_inputs") or {}),
            preserve_existing_batch_scope=True,
        )
        current_event = dict(state.get("current_event") or {})
        source_stage_id = str(current_event.get("stage_id") or "").strip()
        diagnostics = dict(state.get("diagnostics") or {})
        a2a_runtime = dict(diagnostics.get("a2a_runtime") or {})
        protocol_id = str(a2a_runtime.get("protocol_id") or diagnostics.get("communication_protocol_id") or "")
        message_type = str(contract.get("a2a_message_type") or a2a_runtime.get("default_message_type") or "message/send")
        payload_contracts = [
            str(item)
            for item in list(contract.get("payload_contracts") or a2a_runtime.get("payload_contracts") or [])
            if str(item)
        ]
        manifest = _manifest_from_payload(dict(state.get("contract_manifest") or {}))
        node_id = str(contract.get("node_id") or stage_id)
        agent_profile = self._agent_profile_for(str(contract.get("agent_id") or ""))
        working_memory_context = self._select_stage_working_memory_context(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            contract=contract,
        )
        working_memory_operations = list(state.get("working_memory_operations") or [])
        read_operation = _working_memory_read_operation_from_context(
            context=working_memory_context,
            stage_id=stage_id,
            node_id=node_id,
            agent_id=str(contract.get("agent_id") or ""),
        )
        if read_operation:
            working_memory_operations.append(
                _timeline_working_memory_operation(
                    read_operation,
                    existing_operations=working_memory_operations,
                )
            )
        working_memory_contexts = {
            **dict(state.get("working_memory_contexts") or {}),
            **({stage_id: working_memory_context} if working_memory_context else {}),
        }
        stage_scope = self._stage_scope(state=state, stage_id=stage_id, contract=contract)
        missing_required_memory = [
            dict(item)
            for item in list(dict(working_memory_context or {}).get("missing_required_records") or [])
            if isinstance(item, dict)
        ]
        invalid_required_memory = _required_canonical_memory_content_violations(working_memory_context)
        if invalid_required_memory:
            missing_required_memory.extend(invalid_required_memory)
        if missing_required_memory:
            self._append_timeline_event(
                state,
                event_type="memory_required_records_missing",
                status="blocked",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                iteration_index=int(stage_scope.get("iteration_index") or 0),
                payload={
                    "stage_id": stage_id,
                    "node_id": node_id,
                    "missing_required_records": missing_required_memory,
                    "invalid_required_records": invalid_required_memory,
                    "repository_read_edges": list(dict(working_memory_context or {}).get("repository_read_edges") or []),
                },
                idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:missing_required_memory",
            )
            node_statuses = dict(state.get("node_statuses") or {})
            node_statuses[stage_id] = "blocked"
            return {
                "terminal_status": "blocked",
                "node_statuses": node_statuses,
                "working_memory_contexts": working_memory_contexts,
                "working_memory_operations": working_memory_operations,
                "missing_required_memory_records": missing_required_memory,
                "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
                **_scheduler_node_sets(
                    order=[str(item) for item in list(state.get("stage_order") or []) if str(item)],
                    node_statuses=node_statuses,
                    state=state,
                    terminal_status="blocked",
                ),
                "diagnostics": {
                    **dict(state.get("diagnostics") or {}),
                    "missing_required_memory_records": missing_required_memory,
                    "invalid_required_memory_records": invalid_required_memory,
                    "stage_blocked_by_memory": True,
                },
            }
        dispatch_idempotency_key = _node_dispatch_idempotency_key(
            coordination_run_id=str(state.get("coordination_run_id") or ""),
            stage_id=stage_id,
            stage_scope=stage_scope,
            explicit_inputs=explicit_inputs,
            retry_counts=dict(state.get("retry_counts") or {}),
        )
        dispatch_event = self._append_timeline_event(
            state,
            event_type="node_dispatch_requested",
            status="requested",
            scope_type=str(stage_scope.get("scope_type") or "stage"),
            scope_path=list(stage_scope.get("scope_path") or ["run"]),
            node_id=node_id,
            phase_id=str(stage_scope.get("phase_id") or ""),
            iteration_index=int(stage_scope.get("iteration_index") or 0),
            payload={
                "stage_id": stage_id,
                "node_id": node_id,
                "task_ref": str(contract.get("task_ref") or state.get("active_task_ref") or ""),
                "explicit_input_keys": sorted(str(key) for key in explicit_inputs.keys()),
            },
            idempotency_key=dispatch_idempotency_key,
        )
        dispatch_context = {
            "dispatch_event_id": str(dispatch_event.event_id if dispatch_event is not None else ""),
            "clock_seq": int(dispatch_event.clock_seq if dispatch_event is not None else 0),
            "scope_path": list(stage_scope.get("scope_path") or ["run"]),
            "scope_type": str(stage_scope.get("scope_type") or "stage"),
            "phase_id": str(stage_scope.get("phase_id") or ""),
            "dependency_scope_key": str(stage_scope.get("dependency_scope_key") or ""),
            "volume_index": int(stage_scope.get("volume_index") or 0),
            "batch_start_index": int(stage_scope.get("batch_start_index") or 0),
            "batch_end_index": int(stage_scope.get("batch_end_index") or 0),
            "round_index": int(stage_scope.get("round_index") or 0),
            "node_id": node_id,
            "stage_id": stage_id,
            "thread_id": str(state.get("coordination_run_id") or ""),
            "coordination_run_id": str(state.get("coordination_run_id") or ""),
            "root_task_run_id": str(state.get("root_task_run_id") or ""),
        }
        batch_execution_id = str(explicit_inputs.get("unit_batch_execution_id") or "").strip()
        if batch_execution_id:
            dispatch_context["batch_execution_id"] = batch_execution_id
            dispatch_context["unit_batch_id"] = str(explicit_inputs.get("unit_batch_id") or "")
            dispatch_context["unit_batch_plan_id"] = str(explicit_inputs.get("unit_batch_plan_id") or "")
            dispatch_context["unit_batch_sequence_index"] = int(explicit_inputs.get("unit_batch_sequence_index") or 0)
        dispatch_identity_seed = f"{dispatch_context['coordination_run_id']}:{stage_id}:{dispatch_context['dispatch_event_id'] or dispatch_context['clock_seq']}"
        dispatch_context["activation_id"] = f"activation:{_safe_id(dispatch_identity_seed)}"
        dispatch_context["execution_permit_id"] = f"permit:{_safe_id(dispatch_identity_seed)}"
        runtime_assembly_payload: dict[str, Any] = {}
        handoff_packets: list[dict[str, Any]] = []
        if manifest is not None:
            try:
                assembly = build_node_runtime_assembly(
                    manifest=manifest,
                    node_id=node_id,
                    agent_profile=agent_profile,
                    explicit_inputs=explicit_inputs,
                    working_memory_context=working_memory_context,
                )
                runtime_assembly_payload = assembly.to_dict()
                handoff_packets = [dict(item) for item in runtime_assembly_payload.get("handoff_packets") or []]
            except ValueError:
                runtime_assembly_payload = {}
        context_packets = resolve_context_packets(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            explicit_inputs=explicit_inputs,
            working_memory_context=working_memory_context,
            dispatch_context=dispatch_context,
        )
        memory_snapshot = dict(context_packets.get("memory_snapshot") or {})
        artifact_context_packet = dict(context_packets.get("artifact_context_packet") or {})
        revision_packet = dict(context_packets.get("revision_packet") or {})
        resolved_handoff_packets = [dict(item) for item in list(context_packets.get("handoff_packets") or []) if isinstance(item, dict)]
        agent_visible_explicit_inputs = _agent_visible_checkout_explicit_inputs(explicit_inputs)
        executor_binding = build_node_executor_binding(
            node_id=node_id,
            contract=contract,
            explicit_inputs=agent_visible_explicit_inputs,
            agent_profile_id=str(runtime_assembly_payload.get("agent_profile_id") or getattr(agent_profile, "agent_profile_id", "") or ""),
        )
        standard_input_package = build_standard_node_input_package(
            coordination_run_id=str(state.get("coordination_run_id") or ""),
            stage_id=stage_id,
            node_id=node_id,
            contract=contract,
            explicit_inputs=agent_visible_explicit_inputs,
            dispatch_context=dispatch_context,
            memory_snapshot=memory_snapshot,
            artifact_context_packet=artifact_context_packet,
            revision_packet=revision_packet,
            handoff_packets=[*handoff_packets, *resolved_handoff_packets],
        )
        human_work_packet = (
            render_human_work_packet(
                input_package=standard_input_package,
                executor_binding=executor_binding,
                contract=contract,
            )
            if executor_binding.selected_executor == "human"
            else None
        )
        if runtime_assembly_payload:
            metadata = dict(runtime_assembly_payload.get("metadata") or {})
            metadata["dispatch_context"] = dict(dispatch_context)
            metadata["context_packet_summary"] = dict(context_packets.get("context_packet_summary") or {})
            metadata["standard_input_package_id"] = standard_input_package.package_id
            metadata["executor_binding"] = executor_binding.to_dict()
            runtime_assembly_payload["metadata"] = metadata
        graph_module_handle = (
            _graph_module_runtime_handle_from_contract(
                state=state,
                stage_id=stage_id,
                node_id=node_id,
                contract=contract,
                explicit_inputs=agent_visible_explicit_inputs,
                dispatch_context=dispatch_context,
                standard_input_package=standard_input_package.to_dict(),
            )
            if _is_graph_module_stage(contract)
            else {}
        )
        if graph_module_handle:
            graph_module_executor_binding_payload = executor_binding.to_dict()
            graph_module_executor_binding_payload.update(
                {
                    "selected_executor": "graph_module",
                    "default_executor": "graph_module",
                    "allowed_executors": ["graph_module"],
                    "linked_graph_id": str(graph_module_handle.get("linked_graph_id") or ""),
                    "imported_graph_id": str(graph_module_handle.get("linked_graph_id") or ""),
                    "graph_module_runtime_handle": graph_module_handle,
                }
            )
            executor_binding = type(executor_binding)(
                node_id=executor_binding.node_id,
                default_executor="graph_module",
                allowed_executors=("graph_module",),
                selected_executor="graph_module",
                override_policy=executor_binding.override_policy,
                agent_profile_id=executor_binding.agent_profile_id,
                human_profile_id=executor_binding.human_profile_id,
                tool_binding_id=executor_binding.tool_binding_id,
                linked_graph_id=str(graph_module_handle.get("linked_graph_id") or ""),
                imported_graph_id=str(graph_module_handle.get("linked_graph_id") or ""),
                interaction_schema_id=executor_binding.interaction_schema_id,
                diagnostics={
                    **dict(executor_binding.diagnostics),
                    "graph_module_runtime_handle": graph_module_handle,
                },
            )
            runtime_assembly_payload = {
                **dict(runtime_assembly_payload or {}),
                "authority": "harness.execution.graph_module_runtime_assembly",
                "assembly_id": str(
                    runtime_assembly_payload.get("assembly_id")
                    or f"runtime-assembly:graph-module:{_safe_id(graph_module_handle.get('handle_id'))}"
                ),
                "graph_id": _graph_id_from_state(state),
                "graph_ref": _graph_id_from_state(state),
                "node_id": node_id,
                "task_ref": str(contract.get("task_ref") or state.get("active_task_ref") or ""),
                "agent_id": "",
                "agent_profile_id": "",
                "runtime_lane": str(contract.get("runtime_lane") or "task_graph_coordination"),
                "metadata": {
                    **dict(runtime_assembly_payload.get("metadata") or {}),
                    "dispatch_context": dict(dispatch_context),
                    "standard_input_package_id": standard_input_package.package_id,
                    "executor_binding": graph_module_executor_binding_payload,
                },
                "graph_module_runtime_handle": graph_module_handle,
            }
        else:
            graph_module_executor_binding_payload = {}
        if dispatch_event is not None:
            self._append_timeline_event(
                state,
                event_type="memory_snapshot_resolved",
                status="completed",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                payload=memory_snapshot,
                causal_event_ids=[dispatch_event.event_id],
                idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:memory_snapshot:{dispatch_event.event_id}",
            )
            self._append_timeline_event(
                state,
                event_type="node_execution_request_created",
                status="creating",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                payload={
                    "stage_id": stage_id,
                    "node_id": node_id,
                    "dispatch_event_id": dispatch_event.event_id,
                    "activation_id": dispatch_context["activation_id"],
                    "execution_permit_id": dispatch_context["execution_permit_id"],
                    "artifact_packet_id": str(artifact_context_packet.get("packet_id") or ""),
                    "memory_snapshot_id": str(memory_snapshot.get("snapshot_id") or ""),
                    "revision_packet_id": str(revision_packet.get("revision_packet_id") or ""),
                    "standard_input_package_id": standard_input_package.package_id,
                    "executor_type": executor_binding.selected_executor,
                    "graph_module_runtime_handle_id": str(graph_module_handle.get("handle_id") or ""),
                },
                causal_event_ids=[dispatch_event.event_id],
                idempotency_key="",
            )
        a2a_payload = build_node_execution_a2a_payload(
            coordination_run_id=str(state.get("coordination_run_id") or ""),
            root_task_run_id=str(state.get("root_task_run_id") or ""),
            stage_id=stage_id,
            node_id=node_id,
            task_ref=str(contract.get("task_ref") or state.get("active_task_ref") or ""),
            agent_id=str(contract.get("agent_id") or ""),
            source_stage_id=source_stage_id,
            source_agent_id=str(dict(dict(state.get("stage_contracts") or {}).get(source_stage_id) or {}).get("agent_id") or ""),
            protocol_id=protocol_id,
            message_type=message_type,
            explicit_inputs=agent_visible_explicit_inputs,
            payload_contracts=payload_contracts,
            handoff_packets=handoff_packets,
            dispatch_context=dispatch_context,
            memory_snapshot=memory_snapshot,
            artifact_context_packet=artifact_context_packet,
            revision_packet=revision_packet,
            standard_input_package=standard_input_package.to_dict(),
            runtime_assembly_ref=str(runtime_assembly_payload.get("assembly_id") or ""),
            contract_manifest_ref=str((state.get("contract_manifest") or {}).get("manifest_id") or ""),
            ack_policy=str(a2a_runtime.get("ack_policy") or "explicit_ack"),
            handoff_policy=str(a2a_runtime.get("handoff_policy") or ""),
        )
        request = NodeExecutionRequest(
            request_id="",
            coordination_run_id=str(state.get("coordination_run_id") or ""),
            thread_id=str(state.get("coordination_run_id") or ""),
            root_task_run_id=str(state.get("root_task_run_id") or ""),
            stage_id=stage_id,
            node_id=str(contract.get("node_id") or stage_id),
            task_ref=str(contract.get("task_ref") or state.get("active_task_ref") or ""),
            agent_id=str(contract.get("agent_id") or ""),
            agent_profile_id=str(runtime_assembly_payload.get("agent_profile_id") or getattr(agent_profile, "agent_profile_id", "") or ""),
            runtime_lane=str(contract.get("runtime_lane") or ""),
            executor_type=executor_binding.selected_executor,
            executor_binding=graph_module_executor_binding_payload or executor_binding.to_dict(),
            explicit_inputs=_explicit_inputs_with_runtime_boundary_policy(
                explicit_inputs=_explicit_inputs_with_replay_policy(
                    explicit_inputs=agent_visible_explicit_inputs,
                    contract=contract,
                    node_id=node_id,
                ),
                contract=contract,
            ),
            standard_input_package=standard_input_package.to_dict(),
            human_work_packet=human_work_packet.to_dict() if human_work_packet is not None else {},
            runtime_assembly=runtime_assembly_payload,
            a2a_payload=a2a_payload,
            message=_stage_execution_message(
                stage_id=stage_id,
                task_ref=str(contract.get("task_ref") or state.get("active_task_ref") or ""),
                contract=contract,
                explicit_inputs=_explicit_inputs_with_runtime_boundary_policy(
                    explicit_inputs=_explicit_inputs_with_replay_policy(
                        explicit_inputs=agent_visible_explicit_inputs,
                        contract=contract,
                        node_id=node_id,
                    ),
                    contract=contract,
                ),
                artifact_context_packet=artifact_context_packet,
                memory_snapshot=memory_snapshot,
                revision_packet=revision_packet,
            ),
            artifact_root=str(explicit_inputs.get("artifact_root") or ""),
            artifact_policy=dict(contract.get("artifact_policy") or {}),
            stream_policy=dict(contract.get("stream_policy") or {}),
            artifact_targets=tuple(dict(item) for item in list(contract.get("artifact_targets") or []) if isinstance(item, dict)),
            output_contract_id=str(contract.get("output_contract_id") or ""),
            expected_outputs=tuple(dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)),
            working_memory_refs=tuple(_working_memory_refs_from_context(working_memory_context)),
            dispatch_context=dispatch_context,
            memory_snapshot=memory_snapshot,
            artifact_context_packet=artifact_context_packet,
            revision_packet=revision_packet,
            handoff_packet_refs=tuple(str(item) for item in list(context_packets.get("handoff_packet_refs") or []) if str(item)),
            timeline_result_policy={
                "required": True,
                "commit_visibility": "accepted_outputs_only",
                "authority": "task_graph.timeline_result_policy",
            },
        )
        node_work_order = build_node_work_order_from_request(request, state=state)
        runtime_control = build_runtime_control_payload(
            stage_execution_request=request.to_dict(),
            stage_execution_request_ref=_stage_execution_request_ref(request.to_dict()),
            node_work_order=node_work_order.to_dict(),
            standard_input_package=standard_input_package.to_dict(),
        )
        if dispatch_event is not None:
            self._append_timeline_event(
                state,
                event_type="node_work_order_created",
                status="created",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                request_id=request.request_id,
                payload={
                    "work_order_id": node_work_order.work_order_id,
                    "work_kind": node_work_order.work_kind,
                    "stage_id": stage_id,
                    "node_id": node_id,
                    "task_ref": node_work_order.task_ref,
                    "executor_type": node_work_order.executor_type,
                    "request_id": request.request_id,
                },
                causal_event_ids=[dispatch_event.event_id],
                idempotency_key=f"{state.get('coordination_run_id')}:{stage_id}:work_order:{request.request_id}",
            )
        batch_runtime_state = summarize_batch_lifecycle_runtime_state(
            dict(state.get("batch_lifecycle_runtime_state") or {})
        )
        if batch_execution_id and batch_runtime_state:
            batch_runtime_state = attach_batch_execution_request(
                runtime_state=batch_runtime_state,
                batch_execution_id=batch_execution_id,
                request_id=request.request_id,
                dispatch_event_id=str(dispatch_context.get("dispatch_event_id") or ""),
                request_payload=request.to_dict(),
            )
        next_handoff_packets = list(state.get("handoff_packets") or [])
        next_handoff_packets.extend(handoff_packets)
        return {
            "node_execution_request": request.to_dict(),
            "stage_execution_request": request.to_dict(),
            "node_work_order": node_work_order.to_dict(),
            "a2a_payload": a2a_payload,
            "pending_inputs": explicit_inputs,
            **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
            "handoff_packets": next_handoff_packets,
            "working_memory_contexts": working_memory_contexts,
            "working_memory_operations": working_memory_operations,
            "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
            "terminal_status": "",
            "diagnostics": {
                **dict(state.get("diagnostics") or {}),
                "runtime_control_summary": runtime_control_ref_summary(runtime_control),
                **({"batch_lifecycle_runtime_state": batch_runtime_state} if batch_runtime_state else {}),
            },
        }

    def _select_stage_working_memory_context(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        node_id: str,
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        read_policy = dict(contract.get("memory_read_policy") or {})
        graph_policy = dict(dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {}).get("diagnostics") or {}).get("working_memory_policy") or {}
        graph_policy = dict(graph_policy or {})
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return {}
        repository_read_edges = _graph_memory_edge_descriptors(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            operation="read",
        )
        if not repository_read_edges and not read_policy:
            return {}
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or dict(state.get("diagnostics") or {}).get("graph_ref") or "")
        runtime_scope = _formal_memory_runtime_scope(state, state_index=self.state_index)
        self.formal_memory.sync_graph_spec_for_scope(
            graph_id=graph_id,
            graph_spec=graph_spec,
            task_run_id=root_task_run_id,
            runtime_scope=runtime_scope,
        )
        coordination_run_id = str(state.get("coordination_run_id") or "").strip()
        predicted_clock_seq = int(self.timeline_ledger.load(coordination_run_id).current_clock_seq or 0) + 1 if coordination_run_id else 0
        formal_selection: dict[str, Any] = {}
        formal_selection_error = ""
        if repository_read_edges:
            try:
                formal_selection = self.formal_memory.select_for_node(
                    read_edges=repository_read_edges,
                    task_run_id=root_task_run_id,
                    node_run_id=f"{root_task_run_id}:{stage_id}",
                    clock=f"clock:{predicted_clock_seq}" if predicted_clock_seq else "",
                    clock_seq=predicted_clock_seq,
                    limit=int(read_policy.get("max_items") or graph_policy.get("max_items") or 50),
                    runtime_scope=runtime_scope,
                )
            except Exception as exc:  # pragma: no cover - defensive runtime diagnostics
                formal_selection_error = str(exc)
        node_run_id = f"{root_task_run_id}:{stage_id}"
        working_selection: dict[str, Any] = {}
        if read_policy:
            working_selection = self.working_memory.select_for_node(
                task_run_id=root_task_run_id,
                graph_id=graph_id,
                owner_node_id=node_id,
                node_run_id=node_run_id,
                reader_agent_id=str(contract.get("agent_id") or ""),
                node_role=str(contract.get("role") or contract.get("work_posture") or ""),
                memory_read_policy=read_policy,
                dynamic_read_policy=graph_policy,
                request={
                    "requested_kinds": list(read_policy.get("readable_kinds") or []),
                    "acceptable_scopes": list(read_policy.get("readable_scopes") or []),
                    "max_items": int(read_policy.get("max_items") or graph_policy.get("max_items") or 50),
                    "allow_handoff_visibility": True,
                    "readable_owner_node_ids": _working_memory_source_node_ids_for_stage(
                        state=state,
                        target_stage_id=stage_id,
                        target_node_id=node_id,
                    ),
                },
            )
        context = _formal_memory_only_context(
            task_run_id=root_task_run_id,
            graph_id=graph_id,
            owner_node_id=node_id,
            node_run_id=node_run_id,
            run_attempt_id=str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
        )
        if working_selection:
            required_items = [item.to_dict() for item in list(working_selection.get("required_items") or [])]
            preferred_items = [item.to_dict() for item in list(working_selection.get("preferred_items") or [])]
            required_refs = [str(item.get("work_memory_id") or "") for item in required_items if str(item.get("work_memory_id") or "")]
            preferred_refs = [str(item.get("work_memory_id") or "") for item in preferred_items if str(item.get("work_memory_id") or "")]
            context.update(
                {
                    "required_refs": required_refs,
                    "preferred_refs": preferred_refs,
                    "required_items": required_items,
                    "preferred_items": preferred_items,
                    "read_log_id": str(working_selection.get("read_log_id") or ""),
                    "working_memory.required": {
                        "item_count": len(required_items),
                        "refs": required_refs,
                        "items": required_items,
                        "content_mode": "summary",
                    },
                    "working_memory.preferred": {
                        "item_count": len(preferred_items),
                        "refs": preferred_refs,
                        "items": preferred_items,
                        "content_mode": "summary",
                    },
                }
            )
            diagnostics = dict(context.get("diagnostics") or {})
            diagnostics["working_memory_primary"] = True
            diagnostics["working_memory"] = dict(working_selection.get("diagnostics") or {})
            context["diagnostics"] = diagnostics
        if repository_read_edges:
            diagnostics = dict(context.get("diagnostics") or {})
            diagnostics["formal_memory_primary"] = True
            diagnostics["repository_read_edge_count"] = len(repository_read_edges)
            diagnostics["repository_read_edges"] = repository_read_edges
            if formal_selection_error:
                diagnostics["formal_memory_error"] = formal_selection_error
            formal_diagnostics = dict(formal_selection.get("diagnostics") or {})
            if formal_diagnostics:
                diagnostics["formal_memory"] = formal_diagnostics
            context["diagnostics"] = diagnostics
            context["repository_read_edges"] = repository_read_edges
            if formal_selection:
                context["formal_memory.required_records"] = list(formal_selection.get("required_records") or [])
                context["formal_memory.read_logs"] = list(formal_selection.get("read_logs") or [])
                context["formal_memory.read_log_ids"] = list(formal_selection.get("read_log_ids") or [])
                context["formal_memory.missing_required_records"] = list(formal_selection.get("missing_required_records") or [])
                context["missing_required_records"] = list(formal_selection.get("missing_required_records") or [])
                context["formal_memory"] = {
                    "required_records": list(formal_selection.get("required_records") or []),
                    "read_logs": list(formal_selection.get("read_logs") or []),
                    "missing_required_records": list(formal_selection.get("missing_required_records") or []),
                    "authority": "formal_memory.service",
                }
        return context

    def _submit_stage_working_memory_candidates(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        contract: dict[str, Any],
        event: dict[str, Any],
        artifact_refs: list[str],
        output_bundle: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
        source_clock: str = "",
        source_clock_seq: int = 0,
    ) -> dict[str, Any]:
        write_policy = dict(contract.get("memory_writeback_policy") or {})
        if not write_policy:
            return {}
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return {}
        raw_candidates = list(dict(event.get("diagnostics") or {}).get("working_memory_candidates") or [])
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)]
        node_id = str(contract.get("node_id") or stage_id)
        memory_write_edges = _graph_memory_edge_descriptors(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            operation="write",
        )
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or dict(state.get("diagnostics") or {}).get("graph_ref") or "")
        runtime_scope = _formal_memory_runtime_scope(state, state_index=self.state_index)
        self.formal_memory.sync_graph_spec_for_scope(
            graph_id=graph_id,
            graph_spec=graph_spec,
            task_run_id=root_task_run_id,
            runtime_scope=runtime_scope,
        )
        memory_write_edge_by_id = {
            str(edge.get("edge_id") or ""): dict(edge)
            for edge in memory_write_edges
            if str(edge.get("edge_id") or "")
        }
        refs_only_auto_capture_allowed = (
            bool(write_policy.get("capture_artifact_refs"))
            and (
                not memory_write_edges
                or any(_memory_edge_allows_refs_only_auto_candidate(edge) for edge in memory_write_edges)
            )
        )
        if not candidates and artifact_refs and refs_only_auto_capture_allowed:
            candidates = [
                {
                    "title": f"{stage_id} 输出产物",
                    "summary": f"{stage_id} 已产出 {len(artifact_refs)} 个产物引用，等待后续审核或提交。",
                    "artifact_refs": artifact_refs,
                    "kind": _first_policy_value(write_policy, "writable_kinds", "intermediate_result"),
                    "scope": _first_policy_value(write_policy, "writable_scopes", "node_scope"),
                }
            ]
        if not candidates and not any(str(edge.get("source_output_key") or "").strip() for edge in memory_write_edges):
            return {}
        write_records, formal_memory_errors = _formal_memory_write_records(
            candidates=candidates,
            memory_write_edges=memory_write_edges,
            fallback_write_policy=write_policy,
            output_bundle={
                **dict(output_bundle or {}),
                "workspace_root": str(_workspace_root_from_runtime_root(self.root_dir)),
            },
        )
        created = []
        formal_memory_acknowledgements: list[dict[str, Any]] = []
        node_run_id = f"{root_task_run_id}:{stage_id}"
        execution_boundary = _node_execution_boundary(execution_context)
        for index, candidate in enumerate(write_records):
            payload = {
                "task_run_id": root_task_run_id,
                "task_id": str(contract.get("task_ref") or event.get("task_ref") or ""),
                "graph_id": graph_id,
                "owner_node_id": node_id,
                "owner_node_role": str(contract.get("role") or ""),
                "node_run_id": node_run_id,
                "run_attempt_id": str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
                "stage_id": stage_id,
                "writer_agent_id": str(contract.get("agent_id") or ""),
                "kind": str(candidate.get("kind") or _first_policy_value(write_policy, "writable_kinds", "intermediate_result")),
                "scope": str(candidate.get("scope") or _first_policy_value(write_policy, "writable_scopes", "node_scope")),
                "status": str(candidate.get("status") or write_policy.get("default_status") or "draft"),
                "visibility": str(candidate.get("visibility") or write_policy.get("default_visibility") or ("shared_in_graph" if memory_write_edges else "private_to_node")),
                "summary": str(candidate.get("summary") or ""),
                "title": str(candidate.get("title") or ""),
                "payload": dict(candidate.get("payload") or {"source_stage_id": stage_id}),
                "artifact_refs": list(candidate.get("artifact_refs") or artifact_refs),
                "write_policy": write_policy,
                "idempotency_key": str(candidate.get("idempotency_key") or f"{root_task_run_id}:{stage_id}:wmwrite:{index}"),
                "metadata": {
                    **dict(candidate.get("metadata") or {}),
                    "operation": "memory_write",
                    "source_event_task_run_id": str(event.get("task_run_id") or ""),
                    "source_task_result_ref": str(event.get("task_result_ref") or ""),
                    "memory_write_edges": memory_write_edges,
                    "node_execution_boundary": execution_boundary,
                },
            }
            item = self.working_memory.create_item(**payload)
            formal = dict(dict(payload.get("metadata") or {}).get("formal_memory") or {})
            if formal.get("repository_id") and formal.get("collection_id"):
                source_edge_id = str(formal.get("source_edge_id") or "")
                edge_descriptor = memory_write_edge_by_id.get(source_edge_id) or {
                    "edge_id": source_edge_id,
                    "repository": str(formal.get("repository_id") or ""),
                    "collection": str(formal.get("collection_id") or ""),
                    "record_kind": str(formal.get("record_kind") or item.kind or ""),
                    "record_key": str(formal.get("record_key") or formal.get("record_kind") or item.kind or ""),
                    "selector": dict(formal.get("selector") or {}),
                    "commit_visibility_policy": dict(formal.get("commit_visibility_policy") or {}),
                }
                try:
                    version, transaction = self.formal_memory.write_candidate_from_edge(
                        edge=edge_descriptor,
                        candidate={
                            **candidate,
                            "payload": dict(item.payload or {}),
                            "summary": item.summary,
                            "title": item.title,
                            "kind": item.kind,
                            "artifact_refs": list(item.artifact_refs),
                            "idempotency_key": f"{item.idempotency_key}:formal",
                        },
                        task_run_id=root_task_run_id,
                        graph_id=graph_id,
                        node_run_id=node_run_id,
                        source_node_id=node_id,
                        source_clock=source_clock,
                        source_clock_seq=source_clock_seq,
                        artifact_refs=list(item.artifact_refs),
                        runtime_scope=runtime_scope,
                    )
                    formal_update = {
                        **formal,
                        "record_id": version.record_id,
                        "record_key": version.record_key,
                        "version_id": version.version_id,
                        "version": version.version,
                        "transaction_id": transaction.transaction_id,
                        "write_acknowledgement": _formal_memory_acknowledgement(transaction.receipt),
                    }
                    if str(formal.get("commit_state") or "") == "committed":
                        committed_version, commit_transaction = self.formal_memory.commit_from_edge(
                            edge=edge_descriptor,
                            candidate_version_id=version.version_id,
                            node_run_id=node_run_id,
                            source_clock=source_clock,
                            source_clock_seq=source_clock_seq,
                        )
                        formal_update = {
                            **formal_update,
                            "commit_state": committed_version.status,
                            "committed_version_id": committed_version.version_id,
                            "commit_transaction_id": commit_transaction.transaction_id,
                            "commit_acknowledgement": _formal_memory_acknowledgement(commit_transaction.receipt),
                        }
                        formal_memory_acknowledgements.append(_formal_memory_acknowledgement(commit_transaction.receipt))
                    else:
                        formal_memory_acknowledgements.append(_formal_memory_acknowledgement(transaction.receipt))
                    item = self.working_memory.update_lifecycle(
                        item.work_memory_id,
                        metadata={"formal_memory": formal_update},
                        actor_id="graph_coordination_engine",
                        event_type="formal_memory_write_recorded",
                    )
                except Exception as exc:  # pragma: no cover - surfaced in runtime diagnostics
                    formal_memory_errors.append(
                        {
                            "work_memory_id": item.work_memory_id,
                            "edge_id": source_edge_id,
                            "repository_id": str(formal.get("repository_id") or ""),
                            "collection_id": str(formal.get("collection_id") or ""),
                            "error": str(exc),
                        }
                    )
            created.append(item)
        return {
            "operation": "memory_write",
            "stage_id": stage_id,
            "node_id": node_id,
            "node_run_id": node_run_id,
            "created_working_memory_refs": [item.work_memory_id for item in created],
            "formal_memory_acknowledgements": formal_memory_acknowledgements,
            "formal_memory_errors": formal_memory_errors,
            "node_execution_boundary": execution_boundary,
            "candidate_count": len(created),
            "status": "completed",
            "authority": "orchestration.working_memory_resource_node",
        }

    def _resolve_stage_working_memory_handoffs(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        created_working_memory_refs: list[str],
        event: dict[str, Any],
    ) -> list[dict[str, Any]]:
        refs = [str(item).strip() for item in list(created_working_memory_refs or []) if str(item).strip()]
        if not refs:
            return []
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return []
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or "")
        operations: list[dict[str, Any]] = []
        for edge in [dict(item) for item in list(graph_spec.get("edges") or []) if isinstance(item, dict)]:
            if str(edge.get("source_node_id") or "") != stage_id:
                continue
            policy = dict(edge.get("working_memory_handoff_policy") or {})
            if not policy:
                continue
            target_node_id = str(edge.get("target_node_id") or "").strip()
            selected_refs = _filter_working_memory_refs_for_handoff(refs, policy, self.working_memory)
            if not selected_refs:
                continue
            transaction = self.working_memory.resolve_handoff_into_working_memory(
                task_run_id=root_task_run_id,
                graph_id=graph_id,
                edge_id=str(edge.get("edge_id") or ""),
                source_node_run_id=f"{root_task_run_id}:{stage_id}",
                target_node_run_id=f"{root_task_run_id}:{target_node_id}",
                handoff_id=f"wmhandoff:{root_task_run_id}:{edge.get('edge_id') or stage_id + ':' + target_node_id}",
                source_message_hash=str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
                working_memory_refs=selected_refs,
                summary=str(policy.get("summary") or f"{stage_id} 工作记忆交接到 {target_node_id}"),
                metadata={"policy": policy, "operation": "memory_handoff"},
            )
            operations.append(
                {
                    "operation": "memory_handoff",
                    "edge_id": str(edge.get("edge_id") or ""),
                    "source_node_id": stage_id,
                    "target_node_id": target_node_id,
                    "handoff_transaction_ref": transaction.transaction_id,
                    "adopted_working_memory_refs": list(transaction.adopted_work_memory_ids),
                    "status": transaction.transaction_status,
                    "authority": "orchestration.working_memory_resource_node",
                }
            )
        return operations

    @staticmethod
    def _candidate_refs_from_commit_approval_sources(
        *,
        state: CoordinationRuntimeState,
        commit_edges: list[dict[str, Any]],
        current_stage_id: str,
        current_stage_candidate_refs: list[str] | None = None,
    ) -> list[str]:
        approval_sources = {
            str(edge.get("approval_source_node_id") or "").strip()
            for edge in commit_edges
            if str(edge.get("approval_source_node_id") or "").strip()
        }
        if not approval_sources:
            return []
        refs: list[str] = []
        if current_stage_id in approval_sources:
            for ref in _string_list(current_stage_candidate_refs or []):
                if ref and ref not in refs:
                    refs.append(ref)
        for stage_id in sorted(approval_sources):
            result = dict(dict(state.get("stage_results") or {}).get(stage_id) or {})
            for ref in _string_list(result.get("working_memory_refs")):
                if ref and ref not in refs:
                    refs.append(ref)
        return refs

    def _commit_stage_working_memory_decisions(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        contract: dict[str, Any],
        event: dict[str, Any],
        output_bundle: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
        current_stage_candidate_refs: list[str] | None = None,
        source_clock: str = "",
        source_clock_seq: int = 0,
    ) -> dict[str, Any]:
        diagnostics = dict(event.get("diagnostics") or {})
        decision_payload = dict(diagnostics.get("working_memory_commit") or diagnostics.get("memory_commit_decision") or {})
        node_type = str(contract.get("node_type") or "").strip()
        review_policy = dict(contract.get("review_gate_policy") or {})
        is_commit_stage = node_type in {"memory", "memory_resource", "memory_commit"} or bool(review_policy.get("commit_working_memory"))
        if not decision_payload and not is_commit_stage:
            return {}
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return {}
        execution_boundary = _node_execution_boundary(execution_context)
        if execution_boundary.get("valid") is not True:
            return {
                "operation": "memory_commit",
                "stage_id": stage_id,
                "node_id": str(contract.get("node_id") or stage_id),
                "accepted_working_memory_refs": [],
                "discarded_working_memory_refs": [],
                "conflict_working_memory_refs": [],
                "formal_memory_acknowledgements": [],
                "formal_memory_errors": [
                    {
                        "error": "memory_commit_without_active_node_execution_permit",
                        "node_execution_boundary": execution_boundary,
                    }
                ],
                "node_execution_boundary": execution_boundary,
                "status": "blocked",
                "authority": "orchestration.working_memory_resource_node",
            }
        accepted_refs = _decision_refs(decision_payload, "accepted_working_memory_refs", "accept_refs", "accepted_refs")
        discarded_refs = _decision_refs(decision_payload, "discarded_working_memory_refs", "discard_refs", "discarded_refs")
        conflict_refs = _decision_refs(decision_payload, "conflict_working_memory_refs", "conflict_refs")
        actor_id = str(contract.get("agent_id") or "graph_coordination_engine")
        node_id = str(contract.get("node_id") or stage_id)
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or dict(state.get("diagnostics") or {}).get("graph_ref") or "")
        self.formal_memory.sync_graph_spec_for_scope(
            graph_id=graph_id,
            graph_spec=graph_spec,
            task_run_id=root_task_run_id,
            runtime_scope=_formal_memory_runtime_scope(state, state_index=self.state_index),
        )
        commit_edges = _graph_memory_edge_descriptors(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            operation="write",
        )
        commit_edges = [edge for edge in commit_edges if str(edge.get("edge_type") or "") == "memory_commit" or str(edge.get("memory_edge_type") or "") == "commit"]
        resolved_output_bundle = dict(output_bundle or _node_result_output_bundle(state=state, event=event, artifact_refs=[], mapped_outputs={}))
        fallback_commit_refs = list(accepted_refs)
        if commit_edges and not fallback_commit_refs:
            fallback_commit_refs = self._candidate_refs_from_commit_approval_sources(
                state=state,
                commit_edges=commit_edges,
                current_stage_id=stage_id,
                current_stage_candidate_refs=current_stage_candidate_refs,
            )
        edge_commit_requests: list[dict[str, Any]] = []
        edge_commit_errors: list[dict[str, Any]] = []
        if commit_edges:
            edge_commit_requests, edge_commit_errors = _formal_memory_commit_requests(
                commit_edges=commit_edges,
                output_bundle=resolved_output_bundle,
                accepted_candidate_refs=fallback_commit_refs,
            )
        refs_from_commit_edges = [request["candidate_ref"] for request in edge_commit_requests if request.get("candidate_ref")]
        for ref in refs_from_commit_edges:
            if ref not in accepted_refs:
                accepted_refs.append(ref)
        if not decision_payload and is_commit_stage and not accepted_refs:
            accepted_refs = _stage_working_memory_refs_for_commit(state)
            for ref in _string_list(current_stage_candidate_refs or []):
                if ref not in accepted_refs:
                    accepted_refs.append(ref)
        if not accepted_refs and not discarded_refs and not conflict_refs and not edge_commit_errors:
            return {}
        commit_request_by_ref = {
            str(request.get("candidate_ref") or ""): dict(request)
            for request in edge_commit_requests
            if str(request.get("candidate_ref") or "")
        }
        accepted: list[str] = []
        discarded: list[str] = []
        conflicted: list[str] = []
        formal_memory_acknowledgements: list[dict[str, Any]] = []
        formal_memory_errors: list[dict[str, Any]] = list(edge_commit_errors)
        for ref in accepted_refs:
            current = self.working_memory.get_item(ref)
            formal = dict(dict(getattr(current, "metadata", {}) or {}).get("formal_memory") or {}) if current is not None else {}
            metadata: dict[str, Any] = {"stage_id": stage_id, "operation": "memory_commit", "node_execution_boundary": execution_boundary}
            commit_request = dict(commit_request_by_ref.get(str(ref) or "") or {})
            commit_edge = dict(commit_request.get("edge") or {})
            version_id = str(formal.get("version_id") or formal.get("candidate_version_id") or commit_request.get("candidate_version_id") or "")
            if formal and not commit_edge:
                commit_edge = _matching_commit_edge(formal=formal, commit_edges=commit_edges)
            if not version_id and current is None:
                version_id = str(ref or "").strip()
            if version_id:
                try:
                    committed_version, transaction = self.formal_memory.commit_from_edge(
                        edge=commit_edge or {
                            "edge_id": str(formal.get("source_edge_id") or ""),
                            "repository": str(formal.get("repository_id") or ""),
                            "collection": str(formal.get("collection_id") or ""),
                            "record_key": str(formal.get("record_key") or ""),
                            "record_kind": str(formal.get("record_kind") or ""),
                        },
                        candidate_version_id=version_id,
                        node_run_id=f"{root_task_run_id}:{stage_id}",
                        source_clock=source_clock,
                        source_clock_seq=source_clock_seq,
                        verdict=str(commit_request.get("verdict") or ""),
                        required_verdict=str(commit_request.get("required_verdict") or ""),
                    )
                    formal = {
                        **formal,
                        "commit_state": committed_version.status,
                        "committed_version_id": committed_version.version_id if committed_version.status == "committed" else "",
                        "commit_transaction_id": transaction.transaction_id,
                        "commit_acknowledgement": _formal_memory_acknowledgement(transaction.receipt),
                    }
                    formal_memory_acknowledgements.append(_formal_memory_acknowledgement(transaction.receipt))
                except Exception as exc:  # pragma: no cover - surfaced in runtime diagnostics
                    formal_memory_errors.append(
                        {
                            "work_memory_id": ref if current is not None else "",
                            "version_id": version_id,
                            "repository_id": str(formal.get("repository_id") or commit_edge.get("repository") or ""),
                            "collection_id": str(formal.get("collection_id") or commit_edge.get("collection") or ""),
                            "error": str(exc),
                        }
                    )
            if formal and current is not None:
                metadata["formal_memory"] = {
                    **formal,
                    "commit_state": "committed",
                    "source_commit_stage_id": stage_id,
                }
            if current is not None:
                item = self.working_memory.accept_item(ref, actor_id=actor_id, metadata=metadata)
                accepted.append(item.work_memory_id)
            elif version_id:
                accepted.append(version_id)
        for ref in discarded_refs:
            item = self.working_memory.discard_item(ref, actor_id=actor_id, metadata={"stage_id": stage_id, "operation": "memory_commit"})
            discarded.append(item.work_memory_id)
        for ref in conflict_refs:
            item = self.working_memory.mark_conflict(ref, actor_id=actor_id, metadata={"stage_id": stage_id, "operation": "memory_commit"})
            conflicted.append(item.work_memory_id)
        return {
            "operation": "memory_commit",
            "stage_id": stage_id,
            "node_id": node_id,
            "accepted_working_memory_refs": accepted,
            "discarded_working_memory_refs": discarded,
            "conflict_working_memory_refs": conflicted,
            "formal_memory_acknowledgements": formal_memory_acknowledgements,
            "formal_memory_errors": formal_memory_errors,
            "node_execution_boundary": execution_boundary,
            "status": "completed",
            "authority": "orchestration.working_memory_resource_node",
        }

    @staticmethod
    def _blocked(state: CoordinationRuntimeState) -> dict[str, Any]:
        return _clear_execution_boundary(state, terminal_status=str(state.get("terminal_status") or "blocked"))

    @staticmethod
    def _noop(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {
            "terminal_status": str(state.get("terminal_status") or ""),
            "node_work_order": dict(state.get("node_work_order") or {}),
            "node_execution_request": _active_execution_request_payload(state),
            "stage_execution_request": dict(state.get("stage_execution_request") or {}),
            "a2a_payload": dict(state.get("a2a_payload") or {}),
        }

    def _complete(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        task_run_id = str(state.get("root_task_run_id") or "").strip()
        operations = list(state.get("working_memory_operations") or [])
        if task_run_id and not any(str(item.get("operation") or "") == "memory_finalize" for item in operations if isinstance(item, dict)):
            result = self.working_memory_finalizer.finalize_task_run(
                task_run_id,
                actor_id="graph_coordination_engine",
                terminal_reason="completed",
                policy={"promotion_strategy": "archive_only"},
            )
            operations.append(
                _timeline_working_memory_operation(
                    {
                    "operation": "memory_finalize",
                    "task_run_id": task_run_id,
                    "finalization_ref": result.archive_report_path,
                    "status": "completed",
                    "authority": "orchestration.working_memory_resource_node",
                    },
                    existing_operations=operations,
                )
            )
        return {**_clear_execution_boundary(state, terminal_status="completed"), "working_memory_operations": operations}

    @staticmethod
    def _route_after_next(state: CoordinationRuntimeState) -> str:
        terminal = str(state.get("terminal_status") or "")
        if terminal in {"stale_result_ignored", "duplicate_commit_ignored"}:
            return "noop"
        if terminal == "blocked":
            return "blocked"
        if terminal in {"waiting_for_human", "waiting_for_batch_result"}:
            return "blocked"
        if terminal == "failed":
            return "blocked"
        if terminal == "completed":
            return "complete"
        return "stage_prepare"

    @staticmethod
    def _route_after_prepare(state: CoordinationRuntimeState) -> str:
        if str(state.get("terminal_status") or "") == "blocked":
            return "blocked"
        if str(state.get("terminal_status") or "") == "waiting_for_batch_result":
            return "blocked"
        return "stage_execute"

    def _load_or_bootstrap_state(self, *, coordination_run: CoordinationRun, coordination_task: Any) -> dict[str, Any]:
        stored = self.checkpoints.get_state(thread_id=coordination_run.coordination_run_id)
        if stored:
            return _normalize_coordination_authoritative_state(stored)
        return self._bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)

    def _bootstrap_state(
        self,
        *,
        coordination_run: CoordinationRun,
        coordination_task: Any,
        prefer_live_graph: bool = False,
    ) -> dict[str, Any]:
        topology_template = self.task_flow_registry.get_topology_template(coordination_run.topology_template_id)
        communication_protocol = self.task_flow_registry.get_task_communication_protocol(coordination_run.communication_protocol_id)
        specific_tasks = tuple(self.task_flow_registry.list_specific_task_records())
        task_graph = self._resolve_task_graph_definition(coordination_run, prefer_live_graph=prefer_live_graph)
        if task_graph is None:
            return {
                "coordination_run_id": coordination_run.coordination_run_id,
                "root_task_run_id": coordination_run.task_run_id,
                "terminal_status": "blocked",
                **_execution_boundary_cleared(),
                "diagnostics": {
                    "coordination_engine": "harness.graph_coordination_engine",
                    "task_graph_runtime_source": "missing_task_graph_definition",
                    "stage_contract_issues": [
                        {
                            "code": "missing_task_graph_definition",
                            "message": "TaskGraph runtime requires a first-class TaskGraphDefinition snapshot or registry record.",
                            "severity": "error",
                        }
                    ],
                },
            }
        runtime_spec_ref = str(dict(coordination_run.diagnostics or {}).get("task_graph_runtime_spec_ref") or "").strip()
        graph_spec_payload = self.runtime_objects.get_object(runtime_spec_ref) if runtime_spec_ref and not prefer_live_graph else {}
        graph_spec = (
            _runtime_spec_from_payload(graph_spec_payload)
            if graph_spec_payload
            else None
        ) or compile_task_graph_definition_runtime_spec(
            graph=task_graph,
            specific_tasks=specific_tasks,
            communication_protocol=communication_protocol,
        )
        topology_nodes = _merge_runtime_nodes(
            compiled_nodes=[node.to_dict() for node in graph_spec.nodes],
            configured_nodes=[dict(item) for item in list(getattr(topology_template, "nodes", ()) or [])],
        )
        contracts = self._contracts_for_run(coordination_run=coordination_run, coordination_task=coordination_task)
        stage_sequence = [dict(item) for item in list(dict(getattr(coordination_task, "metadata", {}) or {}).get("stage_sequence") or []) if isinstance(item, dict)]
        issues = validate_stage_contracts(coordination_task=coordination_task, contracts=contracts, stage_sequence=stage_sequence)
        order = [contract.stage_id for contract in contracts]
        if not order:
            order = [str(item.get("stage_id") or "") for item in stage_sequence if str(item.get("stage_id") or "")]
        current_stage = str(dict(coordination_run.diagnostics.get("coordination_flow") or {}).get("current_stage_id") or (order[0] if order else ""))
        if current_stage and current_stage not in order:
            current_stage = order[0] if order else ""
        coordination_metadata = dict(getattr(coordination_task, "metadata", {}) or {})
        loop_state = _initial_loop_state(metadata=coordination_metadata)
        contract_map = {contract.stage_id: _contract_payload(contract, topology_nodes=topology_nodes) for contract in contracts}
        for node in topology_nodes:
            node_id = str(node.get("node_id") or "").strip()
            if node_id and node_id not in contract_map:
                contract_map[node_id] = _contract_payload(
                    CoordinationStageContract(
                        stage_id=node_id,
                        task_ref=str(node.get("task_id") or ""),
                        node_id=node_id,
                    ),
                    topology_nodes=topology_nodes,
                )
        if not order:
            order = _topological_stage_order(topology_nodes, [edge.to_dict() for edge in graph_spec.edges])
        if not current_stage and order:
            current_stage = order[0]
        manifest = compile_coordination_contract_manifest(
            contract_registry=TaskContractRegistry(self.registry_base_dir),
            coordination_task=coordination_task,
            graph_spec=graph_spec,
            specific_tasks=specific_tasks,
            communication_protocol=communication_protocol,
            agent_profiles=tuple(AgentRuntimeRegistry(self.registry_base_dir).list_profiles()),
        )
        manifest_payload = manifest.to_dict()
        node_contracts = {
            str(item.get("node_id") or ""): dict(item)
            for item in list(manifest_payload.get("node_contracts") or [])
            if str(item.get("node_id") or "")
        }
        edge_contracts = {
            str(item.get("edge_id") or f"{item.get('source_node_id', '')}->{item.get('target_node_id', '')}"): dict(item)
            for item in list(manifest_payload.get("edge_handoff_contracts") or [])
            if str(item.get("source_node_id") or "") and str(item.get("target_node_id") or "")
        }
        node_statuses: dict[str, str] = {}
        for stage_id in order:
            if stage_id == current_stage:
                node_statuses[stage_id] = "running"
            else:
                node_statuses[stage_id] = "pending"
        scheduler_state = bootstrap_scheduler_state(
            runtime_spec=graph_spec,
            node_statuses=node_statuses,
            terminal_status="blocked" if issues else "",
            edge_handoff_index={},
            mode="active",
        )
        batch_lifecycle_runtime_state = bootstrap_batch_lifecycle_runtime_state(
            runtime_spec_payload=graph_spec.to_dict(),
            mode="active",
        )
        return {
            "coordination_run_id": coordination_run.coordination_run_id,
            "root_task_run_id": coordination_run.task_run_id,
            "coordination_mode": str(getattr(coordination_task, "coordination_mode", "") or ""),
            "active_stage_id": current_stage,
            "active_node_id": str(contract_map.get(current_stage, {}).get("node_id") or current_stage),
            "active_task_ref": str(contract_map.get(current_stage, {}).get("task_ref") or ""),
            "stage_order": order,
            "stage_contracts": contract_map,
            "contract_manifest": manifest_payload,
            "contract_status": _initial_contract_status(manifest_payload),
            "node_contracts": node_contracts,
            "edge_contracts": edge_contracts,
            "ready_nodes": list(scheduler_state.ready_node_ids),
            "blocked_nodes": list(scheduler_state.blocked_node_ids),
            "running_nodes": list(scheduler_state.running_node_ids),
            "completed_nodes": list(scheduler_state.completed_node_ids),
            "failed_nodes": list(scheduler_state.failed_node_ids),
            "handoff_packets": [],
            "handoff_envelopes": [],
            "acceptance_results": {},
            "node_statuses": node_statuses,
            "stage_results": {},
            "stage_results_by_instance": {},
            "committed_stage_identities": [],
            "artifact_refs": [],
            "working_memory_contexts": {},
            "working_memory_operations": [],
            "revision_packets": [],
            "timeline_result_records": [],
            "result_record_index": {},
            "latest_stage_result_records": {},
            "accepted_result_records_by_scope": {},
            "batch_lifecycle_runtime_state": batch_lifecycle_runtime_state,
            "timeline": self.timeline_ledger.snapshot(coordination_run.coordination_run_id, limit=80),
            "pending_inputs": dict(loop_state),
            "missing_required_inputs": [],
            "retry_counts": {},
            "retry_stage_id": "",
            "human_gate": {},
            "terminal_status": "blocked" if issues else "",
            "final_result_ref": "",
            "current_event": {},
            **_execution_boundary_cleared(),
            "diagnostics": {
                "coordination_engine": "harness.graph_coordination_engine",
                "communication_protocol_id": coordination_run.communication_protocol_id,
                "a2a_runtime": {
                    "protocol": "official",
                    "protocol_version": "0.3.0",
                    "transport": "JSONRPC",
                    "protocol_id": coordination_run.communication_protocol_id,
                    "default_message_type": "message/send",
                    "payload_contracts": list(getattr(communication_protocol, "payload_contracts", ()) or []),
                    "ack_policy": str(getattr(communication_protocol, "ack_policy", "") or "explicit_ack"),
                    "handoff_policy": str(coordination_run.handoff_policy or ""),
                },
                "coordination_graph_spec": graph_spec.to_dict(),
                "graph_ref": graph_spec.graph_ref or graph_spec.graph_id,
                "task_graph_scheduler_state": scheduler_state.to_dict(),
                "batch_lifecycle_runtime_state": batch_lifecycle_runtime_state,
                "task_graph_runtime_source": "task_graph_definition",
                "contract_manifest_ref": manifest.manifest_id,
                "contract_manifest_valid": manifest.valid,
                "contract_manifest_issue_count": len(manifest.issues),
                "stage_contract_issues": issues,
                "continuation_policy": CoordinationContinuationPolicy.from_metadata(
                    coordination_metadata
                ).to_dict(),
                "runtime_loop_policy": dict(coordination_metadata.get("runtime_loop_policy") or {}),
                "runtime_loop": dict(loop_state),
            },
        }

    def _contracts_for_run(self, *, coordination_run: CoordinationRun, coordination_task: Any) -> tuple[CoordinationStageContract, ...]:
        topology_template = self.task_flow_registry.get_topology_template(coordination_run.topology_template_id)
        topology_nodes = [dict(item) for item in list(getattr(topology_template, "nodes", ()) or [])]
        topology_edges = [dict(item) for item in list(getattr(topology_template, "edges", ()) or [])]
        contracts = parse_stage_contracts(
            coordination_task=coordination_task,
            topology_nodes=topology_nodes,
            topology_edges=topology_edges,
        )
        if contracts:
            return contracts
        return derive_stage_contracts_from_graph(
            coordination_task=coordination_task,
            topology_nodes=topology_nodes,
            topology_edges=topology_edges,
        )

    def _agent_profile_for(self, agent_id: str) -> Any:
        return AgentRuntimeRegistry(self.registry_base_dir).get_profile(agent_id)


def _contract_payload(contract: CoordinationStageContract, *, topology_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    node = next(
        (
            dict(item)
            for item in topology_nodes
            if str(item.get("node_id") or "") == (contract.node_id or contract.stage_id)
        ),
        {},
    )
    payload = contract.to_dict()
    payload["agent_id"] = str(node.get("agent_id") or payload.get("agent_id") or "")
    payload["runtime_lane"] = str(node.get("lane") or node.get("runtime_lane") or payload.get("runtime_lane") or "")
    payload["role"] = str(node.get("role") or node.get("work_posture") or payload.get("role") or "")
    payload["title"] = str(node.get("title") or payload.get("title") or contract.stage_id)
    payload["input_contract_id"] = str(node.get("input_contract_id") or payload.get("input_contract_id") or "")
    payload["output_contract_id"] = str(node.get("output_contract_id") or node.get("node_contract_id") or payload.get("output_contract_id") or "")
    for key in (
        "artifact_targets",
        "artifact_requirements",
        "artifact_policy",
        "artifact_target",
        "output_path",
        "instructions",
        "stage_instructions",
        "node_type",
        "executor_policy",
        "memory_read_policy",
        "memory_writeback_policy",
        "dynamic_memory_read_policy",
        "review_gate_policy",
        "human_gate_policy",
        "artifact_context_policy",
        "revision_context_policy",
        "quality_retry_policy",
        "progress_commit_policy",
        "loop_kind",
        "loop_scope_id",
        "title_template",
        "loop_route_policy",
    ):
        if key in node and (key not in payload or payload.get(key) in ("", None, [], {})):
            payload[key] = node[key]
    metadata = dict(node.get("metadata") or {}) if isinstance(node.get("metadata"), dict) else {}
    for key in (
        "artifact_context_policy",
        "revision_context_policy",
        "quality_retry_policy",
        "progress_commit_policy",
        "loop_kind",
        "loop_scope_id",
        "title_template",
        "loop_route_policy",
    ):
        if key in metadata and (key not in payload or payload.get(key) in ("", None, [], {})):
            payload[key] = metadata[key]
    if metadata and (not isinstance(payload.get("metadata"), dict) or not payload.get("metadata")):
        payload["metadata"] = metadata
    if (
        str(payload.get("node_type") or "").strip() == "graph_module"
        or bool(metadata.get("graph_module"))
        or str(metadata.get("execution_mode") or "").strip() == "graph_module_run"
    ):
        for key in (
            "graph_module_runtime_plan_id",
            "graph_module_runtime_plan",
            "linked_graph_id",
            "version_ref",
            "handoff_contract_id",
            "input_port_id",
            "output_port_id",
            "isolation_policy",
            "visibility_policy",
            "detach_policy",
        ):
            if key in metadata and (key not in payload or payload.get(key) in ("", None, [], {})):
                payload[key] = metadata[key]
        executor_policy = {
            **dict(payload.get("executor_policy") or {}),
            **dict(metadata.get("executor_policy") or {}),
        }
        executor_policy.setdefault("default_executor", "graph_module")
        executor_policy.setdefault("allowed_executors", ["graph_module"])
        executor_policy.setdefault("linked_graph_id", str(payload.get("linked_graph_id") or ""))
        executor_policy.setdefault("imported_graph_id", str(payload.get("linked_graph_id") or ""))
        executor_policy.setdefault("auto_start_imported_initial_stage", True)
        payload["executor_policy"] = executor_policy
        if not str(payload.get("task_ref") or "").strip():
            graph_id = str(payload.get("importing_graph_id") or dict(payload.get("graph_module_runtime_plan") or {}).get("importing_graph_id") or "")
            payload["task_ref"] = f"task_graph.node.{graph_id or 'graph'}.{payload.get('node_id') or contract.stage_id}"
    artifact_policy = dict(payload.get("artifact_policy") or {})
    artifact_target = str(payload.get("artifact_target") or payload.get("output_path") or artifact_policy.get("artifact_target") or "").strip()
    if artifact_target:
        artifact_policy.setdefault("enabled", True)
        artifact_policy.setdefault("required", True)
        artifact_policy.setdefault("source", "task_graph_node")
        artifact_policy["artifact_target"] = artifact_target
        artifact_policy.setdefault(
            "artifacts",
            [
                {
                    "path": artifact_target,
                    "required": True,
                    "content_source": "final_content",
                    "fallback_to_full_content": True,
                }
            ],
        )
        payload["artifact_policy"] = artifact_policy
        targets = [dict(item) for item in list(payload.get("artifact_targets") or []) if isinstance(item, dict)]
        if not any(str(item.get("path") or "") == artifact_target for item in targets):
            targets.append({"path": artifact_target, "required": True, "source": "task_graph_node"})
        payload["artifact_targets"] = targets
    return payload














def _is_graph_module_stage(contract: dict[str, Any]) -> bool:
    return graph_module_stage_is_enabled(contract)


def _graph_module_runtime_handle_from_contract(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    dispatch_context: dict[str, Any],
    standard_input_package: dict[str, Any],
) -> dict[str, Any]:
    return build_graph_module_runtime_handle_from_contract(
        importing_graph_id=_graph_id_from_state(state),
        importing_coordination_run_id=str(state.get("coordination_run_id") or ""),
        importing_root_task_run_id=str(state.get("root_task_run_id") or ""),
        stage_id=stage_id,
        node_id=node_id,
        contract=contract,
        runtime_node=_runtime_node_payload(state, node_id),
        explicit_inputs=explicit_inputs,
        dispatch_context=dispatch_context,
        standard_input_package=standard_input_package,
    )


































































def _merge_runtime_nodes(*, compiled_nodes: list[dict[str, Any]], configured_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configured_by_id = {
        str(item.get("node_id") or item.get("id") or "").strip(): dict(item)
        for item in list(configured_nodes or [])
        if isinstance(item, dict) and str(item.get("node_id") or item.get("id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for compiled in list(compiled_nodes or []):
        node = dict(compiled or {})
        node_id = str(node.get("node_id") or "").strip()
        configured = dict(configured_by_id.get(node_id) or {})
        metadata = dict(node.get("metadata") or {})
        configured_metadata = dict(configured.get("metadata") or {}) if isinstance(configured.get("metadata"), dict) else {}
        node.update(
            {
                key: value
                for key, value in configured.items()
                if key not in {"metadata"} and value not in ("", None, [], {})
            }
        )
        node["metadata"] = {**metadata, **configured_metadata}
        merged.append(node)
    known = {str(item.get("node_id") or "") for item in merged}
    for node_id, configured in configured_by_id.items():
        if node_id not in known:
            merged.append(dict(configured))
    return merged


def _runtime_loop_policy_from_state(state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(state.get("diagnostics") or {})
    return dict(diagnostics.get("runtime_loop_policy") or {})


def _formal_memory_runtime_scope(
    state: dict[str, Any],
    *,
    state_index: Any | None = None,
) -> dict[str, Any]:
    project_id = _project_id_from_state(
        state,
        state_index=state_index,
        fallback_task_run_id=str(state.get("root_task_run_id") or ""),
    )
    return {"project_id": project_id} if project_id else {}


def _project_id_from_state(
    state: dict[str, Any],
    *,
    state_index: Any | None = None,
    fallback_task_run_id: str = "",
) -> str:
    pending_inputs = dict(state.get("pending_inputs") or {})
    diagnostics = dict(state.get("diagnostics") or {})
    for value in (
        pending_inputs.get("project_id"),
        diagnostics.get("project_id"),
        dict(diagnostics.get("runtime_loop") or {}).get("project_id"),
        dict(diagnostics.get("runtime_loop_policy") or {}).get("project_id"),
        dict(dict(diagnostics.get("runtime_loop_policy") or {}).get("initial_inputs") or {}).get("project_id"),
    ):
        project_id = str(value or "").strip()
        if project_id:
            return project_id
    task_run_id = str(fallback_task_run_id or state.get("root_task_run_id") or "").strip()
    if state_index is not None and task_run_id:
        try:
            task_run = state_index.get_task_run(task_run_id)
        except Exception:
            task_run = None
        if task_run is not None:
            project_id = str(dict(getattr(task_run, "diagnostics", {}) or {}).get("project_id") or "").strip()
            if project_id:
                return project_id
    return ""


def _normalize_pending_inputs_with_runtime_loop_policy(
    *,
    state: dict[str, Any],
    pending_inputs: dict[str, Any],
    preserve_existing_batch_scope: bool = True,
) -> dict[str, Any]:
    policy = _runtime_loop_policy_from_state(state)
    derived_fields = list(policy.get("derived_fields") or [])
    if not derived_fields:
        return dict(pending_inputs or {})
    return _apply_loop_derived_fields(
        dict(pending_inputs or {}),
        derived_fields,
        preserve_existing_batch_scope=preserve_existing_batch_scope,
    )


def _initial_loop_state(*, metadata: dict[str, Any]) -> dict[str, Any]:
    policy = dict(metadata.get("runtime_loop_policy") or {})
    if not policy.get("enabled"):
        return {}
    pending_inputs = dict(policy.get("initial_inputs") or {})
    pending_inputs = _apply_loop_derived_fields(pending_inputs, list(policy.get("derived_fields") or []))
    summary = str(policy.get("summary") or "").strip()
    if summary:
        pending_inputs.setdefault("runtime_loop_summary", _render_runtime_template(summary, pending_inputs))
    return pending_inputs


def _loop_after_stage_accept(
    *,
    state: CoordinationRuntimeState,
    stage_id: str,
    accepted: bool,
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    route_policy = dict(contract.get("loop_route_policy") or {})
    if not accepted or not route_policy:
        return {}
    mode = str(route_policy.get("mode") or "").strip()
    if mode not in {"metric_target", "next_scope_or_final"}:
        return {}
    pending_inputs = dict(state.get("pending_inputs") or {})
    node_statuses = dict(state.get("node_statuses") or {})
    diagnostics = dict(event.get("diagnostics") or {})
    metric_key = str(route_policy.get("metric_key") or "runtime_metric").strip()
    current_key = str(route_policy.get("current_key") or "runtime_current").strip()
    target_key = str(route_policy.get("target_key") or "runtime_target").strip()
    increment = _safe_int(
        diagnostics.get(metric_key)
        or diagnostics.get(str(route_policy.get("diagnostic_metric_key") or ""))
        or pending_inputs.get(str(route_policy.get("fallback_increment_key") or ""))
        or route_policy.get("default_increment"),
        0,
    )
    if increment:
        pending_inputs[str(route_policy.get("last_metric_key") or f"last_{metric_key}")] = increment
    current_value = _safe_int(pending_inputs.get(current_key), 0) + max(increment, 0)
    pending_inputs[current_key] = current_value
    for secondary in [dict(item) for item in list(route_policy.get("secondary_counters") or []) if isinstance(item, dict)]:
        key = str(secondary.get("current_key") or "").strip()
        if key:
            pending_inputs[key] = _safe_int(pending_inputs.get(key), 0) + max(increment, 0)
    pending_inputs = _advance_loop_counters(pending_inputs, route_policy)
    pending_inputs = _apply_loop_derived_fields(
        pending_inputs,
        list(route_policy.get("derived_fields") or []),
        preserve_existing_batch_scope=False,
    )
    continue_stage_id = str(route_policy.get("continue_stage_id") or "").strip()
    exit_stage_id = str(route_policy.get("exit_stage_id") or "").strip()
    target_value = _safe_int(pending_inputs.get(target_key), 0)
    continue_allowed = bool(continue_stage_id) and (target_value <= 0 or current_value < target_value)
    for secondary in [dict(item) for item in list(route_policy.get("secondary_counters") or []) if isinstance(item, dict)]:
        current = _safe_int(pending_inputs.get(str(secondary.get("current_key") or "")), 0)
        target = _safe_int(pending_inputs.get(str(secondary.get("target_key") or "")), 0)
        if target > 0:
            continue_allowed = continue_allowed and current < target
    loop_stage_ids = _loop_chain_stage_ids(
        state=state,
        current_stage_id=stage_id,
        continue_stage_id=continue_stage_id,
        exit_stage_id=exit_stage_id,
        loop_scope_id=str(route_policy.get("loop_scope_id") or contract.get("loop_scope_id") or ""),
    )
    if continue_allowed:
        for loop_stage_id in loop_stage_ids:
            node_statuses[loop_stage_id] = "pending"
        node_statuses[stage_id] = "completed"
        return {
            "node_statuses": node_statuses,
            "pending_inputs": pending_inputs,
            "terminal_status": "",
            "diagnostics": {
                "runtime_loop": {
                    "status": "continue",
                    "preferred_next_stage_id": continue_stage_id,
                    "loop_scope_id": str(route_policy.get("loop_scope_id") or contract.get("loop_scope_id") or ""),
                    "metric_key": metric_key,
                    "metric_increment": increment,
                    "current_key": current_key,
                    "current_value": current_value,
                    "target_key": target_key,
                    "target_value": target_value,
                    "exit_stage_id": exit_stage_id,
                }
            },
        }
    if exit_stage_id:
        node_statuses[exit_stage_id] = "pending"
    return {
        "node_statuses": node_statuses,
        "pending_inputs": pending_inputs,
        "terminal_status": "",
        "diagnostics": {
            "runtime_loop": {
                "status": "exit",
                "preferred_next_stage_id": exit_stage_id,
                "loop_scope_id": str(route_policy.get("loop_scope_id") or contract.get("loop_scope_id") or ""),
                "metric_key": metric_key,
                "metric_increment": increment,
                "current_key": current_key,
                "current_value": current_value,
                "target_key": target_key,
                "target_value": target_value,
            }
        },
    }


def _review_revision_target(*, contract: dict[str, Any], stage_id: str) -> str:
    node_type = str(contract.get("node_type") or "").strip()
    gate_policy = str(contract.get("gate_policy") or "").strip()
    review_policy = dict(contract.get("review_gate_policy") or {})
    if node_type != "review_gate" and gate_policy != "review_gate" and not review_policy:
        return ""
    explicit = str(review_policy.get("revision_stage_id") or review_policy.get("on_revise") or "").strip()
    return explicit


def _review_gate_event_is_accepted(*, event: dict[str, Any], contract: dict[str, Any]) -> bool:
    node_type = str(contract.get("node_type") or "").strip()
    gate_policy = str(contract.get("gate_policy") or "").strip()
    review_policy = dict(contract.get("review_gate_policy") or {})
    if node_type != "review_gate" and gate_policy != "review_gate" and not review_policy:
        return False
    diagnostics = dict(event.get("diagnostics") or {})
    acceptance = dict(diagnostics.get("stage_business_acceptance") or {})
    verdict = str(
        acceptance.get("verdict")
        or acceptance.get("review_verdict")
        or diagnostics.get("verdict")
        or diagnostics.get("review_verdict")
        or ""
    ).strip()
    if review_verdict_is_rejected(verdict):
        return False
    return review_verdict_is_accepted(verdict)


def _stage_quality_retry_target(*, contract: dict[str, Any], stage_id: str, event: dict[str, Any]) -> str:
    policy = dict(contract.get("quality_retry_policy") or {})
    if policy.get("enabled") is not True:
        return ""
    diagnostics = dict(event.get("diagnostics") or {})
    acceptance = dict(diagnostics.get("stage_business_acceptance") or {})
    accepted_policies = {str(item) for item in list(policy.get("acceptance_policies") or []) if str(item)}
    acceptance_policies = {
        str(item)
        for item in [
            acceptance.get("policy"),
            *list(acceptance.get("quality_gate_policies") or []),
        ]
        if str(item)
    }
    if accepted_policies and not accepted_policies.intersection(acceptance_policies):
        return ""
    issues = [str(item) for item in list(acceptance.get("issues") or []) if str(item)]
    recoverable_prefixes = tuple(str(item) for item in list(policy.get("recoverable_issue_prefixes") or []) if str(item))
    if not recoverable_prefixes or any(issue == prefix or issue.startswith(prefix) for issue in issues for prefix in recoverable_prefixes):
        return str(policy.get("retry_stage_id") or stage_id or "").strip()
    return ""


def _pending_inputs_for_stage_quality_retry(
    *,
    state: CoordinationRuntimeState,
    stage_id: str,
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    pending_inputs = dict(state.get("pending_inputs") or {})
    policy = dict(contract.get("quality_retry_policy") or {})
    next_round = _safe_int(pending_inputs.get("round_index"), 1) + 1
    pending_inputs.update(
        {
            "round_index": next_round,
            "revision_required": True,
            "force_replay": True,
            "force_replay_after": time.time(),
            "previous_quality_failure_stage_id": stage_id,
        }
    )
    current_output_key = str(policy.get("carry_current_output_as") or "").strip()
    if current_output_key:
        pending_inputs[current_output_key] = _first_artifact_ref(event)
    pending_inputs = _normalize_pending_inputs_with_runtime_loop_policy(
        state=state,
        pending_inputs=pending_inputs,
        preserve_existing_batch_scope=True,
    )
    requirements_key = str(policy.get("requirements_input_key") or "").strip()
    template = str(policy.get("requirements_template") or "").strip()
    if requirements_key and template:
        acceptance = dict(dict(event.get("diagnostics") or {}).get("stage_business_acceptance") or {})
        quality_issues = "; ".join(
            str(item)
            for item in list(acceptance.get("issues") or [])
            if str(item)
        )
        quality_issue_summary = _quality_issue_summary_from_acceptance(acceptance)
        pending_inputs[requirements_key] = _render_runtime_template(
            template,
            {
                **pending_inputs,
                **dict(event.get("diagnostics") or {}),
                **acceptance,
                "quality_issues": quality_issues,
                "quality_issue_summary": quality_issue_summary,
            },
        )
    for key in list(policy.get("clear_input_keys") or []):
        if str(key).strip():
            pending_inputs.pop(str(key).strip(), None)
    return _normalize_pending_inputs_with_runtime_loop_policy(
        state=state,
        pending_inputs=pending_inputs,
        preserve_existing_batch_scope=True,
    )


def _quality_issue_summary_from_acceptance(acceptance: dict[str, Any]) -> str:
    explicit = str(acceptance.get("quality_issue_summary") or "").strip()
    if explicit:
        return explicit
    parts: list[str] = []
    unit_summary = str(acceptance.get("unit_metric_summary") or "").strip()
    if unit_summary:
        parts.append(f"逐单元统计：{unit_summary}")
    content_total = _safe_int(acceptance.get("content_metric_total"), 0)
    min_total = _safe_int(acceptance.get("min_required_metric_total"), 0)
    target_total = _safe_int(acceptance.get("target_units"), 0)
    metric_label = str(acceptance.get("metric_summary_label") or "")
    if min_total > 0 and content_total < min_total:
        parts.append(f"总量约{content_total}{metric_label}，低于最低要求{min_total}{metric_label}，需至少补约{min_total - content_total}{metric_label}")
    elif target_total > 0 and content_total < target_total:
        parts.append(f"总量约{content_total}{metric_label}，低于目标{target_total}{metric_label}，建议补约{target_total - content_total}{metric_label}")
    if parts:
        return "；".join(parts)
    return "; ".join(str(item) for item in list(acceptance.get("issues") or []) if str(item))


def _pending_inputs_for_revision_retry(
    *,
    state: CoordinationRuntimeState,
    review_stage_id: str,
    target_stage_id: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    pending_inputs = dict(state.get("pending_inputs") or {})
    contract = dict(dict(state.get("stage_contracts") or {}).get(review_stage_id) or {})
    policy = dict(contract.get("revision_context_policy") or {})
    next_round = _safe_int(pending_inputs.get("round_index"), 1) + 1
    pending_inputs.update(
        {
            "round_index": next_round,
            "revision_required": True,
            "force_replay": True,
            "force_replay_after": time.time(),
            "previous_review_stage_id": review_stage_id,
            "previous_review_ref": _first_artifact_ref(event),
        }
    )
    context_refs: list[dict[str, str]] = []
    for item in list(policy.get("carry") or []):
        if not isinstance(item, dict):
            continue
        input_key = str(item.get("input_key") or "").strip()
        if not input_key:
            continue
        value = _resolve_revision_context_value(item, pending_inputs=pending_inputs, event=event)
        if value in ("", None, [], {}):
            continue
        pending_inputs[input_key] = value
        context_refs.append({"input_key": input_key, "ref": str(value)})
    if context_refs:
        pending_inputs["previous_revision_context_refs"] = context_refs
    requirements_key = str(policy.get("requirements_input_key") or "revision_requirements").strip()
    if requirements_key and requirements_key not in pending_inputs:
        pending_inputs[requirements_key] = str(policy.get("default_requirements") or "上一轮审核未通过；请按审核意见重做本节点产物。")
    for key in list(policy.get("clear_input_keys") or []):
        if str(key).strip():
            pending_inputs.pop(str(key).strip(), None)
    return _normalize_pending_inputs_with_runtime_loop_policy(
        state=state,
        pending_inputs=pending_inputs,
        preserve_existing_batch_scope=True,
    )


def _resolve_revision_context_value(item: dict[str, Any], *, pending_inputs: dict[str, Any], event: dict[str, Any]) -> Any:
    source = str(item.get("source") or "").strip()
    if source == "current_review":
        return _first_artifact_ref(event)
    if source == "current_output":
        return _first_artifact_ref(event)
    if source == "inherited_input":
        return pending_inputs.get(str(item.get("from_key") or item.get("input_key") or "").strip())
    if source == "literal":
        return item.get("value")
    if source == "collect":
        values: list[Any] = []
        for child in list(item.get("items") or []):
            if not isinstance(child, dict):
                continue
            value = _resolve_revision_context_value(child, pending_inputs=pending_inputs, event=event)
            if isinstance(value, list):
                values.extend(value)
            elif value not in ("", None, [], {}):
                values.append(value)
        return values
    return None


def _first_artifact_ref(event: dict[str, Any]) -> str:
    for item in list(event.get("artifact_refs") or []):
        ref = str(item or "").strip()
        if ref.startswith("artifact:"):
            return ref
    return ""


def _reset_failed_direct_downstream_after_success(
    *,
    state: CoordinationRuntimeState,
    node_statuses: dict[str, str],
    stage_id: str,
) -> dict[str, str]:
    runtime_spec = _runtime_spec_from_state(state)
    if runtime_spec is None:
        return node_statuses
    conditional_modes = {
        "repair_route",
        "revision_request",
        "fail_closed",
        "human_handoff",
        "manual_gate",
    }
    reset_statuses = dict(node_statuses)
    stage_contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
    stage_loop_scope_id = str(stage_contract.get("loop_scope_id") or "").strip()
    for edge in runtime_spec.edges:
        if str(edge.source_node_id or "") != stage_id:
            continue
        if str(edge.mode or "") in conditional_modes:
            continue
        target = str(edge.target_node_id or "")
        if not target:
            continue
        target_contract = dict(dict(state.get("stage_contracts") or {}).get(target) or {})
        if reset_statuses.get(target) == "failed":
            reset_statuses[target] = "pending"
        elif stage_loop_scope_id and str(target_contract.get("loop_scope_id") or "").strip() == stage_loop_scope_id and reset_statuses.get(target) in {"completed", "blocked"}:
            reset_statuses[target] = "pending"
    return reset_statuses


def _loop_chain_stage_ids(
    *,
    state: CoordinationRuntimeState,
    current_stage_id: str,
    continue_stage_id: str,
    exit_stage_id: str,
    loop_scope_id: str = "",
) -> set[str]:
    order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
    if not order or current_stage_id not in order or continue_stage_id not in order:
        return {continue_stage_id} if continue_stage_id else set()
    start = order.index(continue_stage_id)
    end = order.index(current_stage_id)
    if start <= end:
        return set(order[start : end + 1])
    clean_scope = str(loop_scope_id or "").strip()
    if clean_scope:
        return {
            stage_id
            for stage_id in order
            if stage_id not in {exit_stage_id}
            and str(dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {}).get("loop_scope_id") or "").strip() == clean_scope
        }
    return {
        stage_id
        for stage_id in order
        if stage_id not in {exit_stage_id}
        and dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {}).get("loop_policy")
    }


def _advance_loop_counters(pending_inputs: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    updated = dict(pending_inputs)
    for item in [dict(value) for value in list(policy.get("counter_updates") or []) if isinstance(value, dict)]:
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        mode = str(item.get("mode") or "increment").strip()
        if mode == "reset":
            updated[key] = _safe_int(item.get("value"), 0)
        elif mode == "copy":
            updated[key] = updated.get(str(item.get("from_key") or ""), item.get("default"))
        else:
            step = _safe_int(
                updated.get(str(item.get("step_key") or "")),
                _safe_int(item.get("step"), 1),
            )
            updated[key] = _safe_int(updated.get(key), _safe_int(item.get("start"), 0)) + step
    return updated


def _apply_loop_derived_fields(
    pending_inputs: dict[str, Any],
    derived_fields: list[Any],
    *,
    preserve_existing_batch_scope: bool = False,
) -> dict[str, Any]:
    updated = dict(pending_inputs)
    for raw in derived_fields:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        if not key:
            continue
        op = str(raw.get("op") or "format").strip()
        if op == "copy":
            if preserve_existing_batch_scope and key == "batch_start_index" and updated.get(key) not in ("", None, [], {}):
                continue
            updated[key] = updated.get(str(raw.get("from_key") or ""), raw.get("default"))
        elif op == "add":
            if preserve_existing_batch_scope and key == "batch_end_index" and updated.get(key) not in ("", None, [], {}):
                continue
            value = _safe_int(
                updated.get(str(raw.get("value_key") or "")),
                _safe_int(raw.get("value"), 0),
            )
            offset = _safe_int(raw.get("offset"), 0)
            updated[key] = _safe_int(updated.get(str(raw.get("from_key") or "")), 0) + value + offset
        elif op == "multiply":
            value = _safe_int(
                updated.get(str(raw.get("value_key") or "")),
                _safe_int(raw.get("value"), 1),
            )
            updated[key] = _safe_int(updated.get(str(raw.get("from_key") or "")), 0) * value
        elif op == "range":
            start = _safe_int(updated.get(str(raw.get("start_key") or "")), 0)
            end = _safe_int(updated.get(str(raw.get("end_key") or "")), start)
            updated[key] = list(range(start, end + 1)) if end >= start else []
        elif op == "ordinal_group":
            value = _safe_int(updated.get(str(raw.get("from_key") or "")), 1)
            size = max(
                _safe_int(updated.get(str(raw.get("size_key") or "")), _safe_int(raw.get("size"), 1)),
                1,
            )
            updated[key] = ((max(value, 1) - 1) // size) + 1
        elif op == "join":
            values = updated.get(str(raw.get("from_key") or ""))
            prefix = str(raw.get("prefix") or "")
            suffix = str(raw.get("suffix") or "")
            sep = str(raw.get("separator") or ", ")
            updated[key] = sep.join(f"{prefix}{item}{suffix}" for item in list(values or []))
        elif op == "format":
            updated[key] = _render_runtime_template(str(raw.get("template") or ""), updated)
    return updated


def _stage_execution_message(
    *,
    stage_id: str,
    task_ref: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    artifact_context_packet: dict[str, Any] | None = None,
    memory_snapshot: dict[str, Any] | None = None,
    revision_packet: dict[str, Any] | None = None,
) -> str:
    title_template = str(contract.get("title_template") or "").strip()
    title = _render_runtime_template(title_template, explicit_inputs) if title_template else ""
    if not title:
        title = str(contract.get("title") or stage_id or task_ref).strip()
    artifact_paths = [
        _render_runtime_template(str(item.get("path") or item.get("naming_rule") or "").strip(), explicit_inputs)
        for item in list(contract.get("artifact_requirements") or contract.get("artifact_targets") or [])
        if isinstance(item, dict) and str(item.get("path") or item.get("naming_rule") or "").strip()
    ]
    instructions = [
        _render_runtime_template(str(item).strip(), explicit_inputs)
        for item in list(contract.get("instructions") or contract.get("stage_instructions") or [])
        if str(item).strip()
    ]
    lines = [
        f"本轮工作：{title}。",
        "请直接完成本节点职责要求的产物，不要写寒暄、等待补充、工作过程说明或系统说明。",
        "请严格依据本节点收到的任务说明、交接包、记忆快照、产物上下文和输出契约工作；不要自行猜测未提供的上游结果。",
    ]
    loop_summary = str(explicit_inputs.get("runtime_loop_summary") or "").strip()
    if loop_summary:
        lines.append("当前循环上下文：")
        lines.append(loop_summary)
    batch_boundary = _runtime_batch_boundary_instruction(contract=contract, explicit_inputs=explicit_inputs)
    if batch_boundary:
        lines.append("本轮处理边界：")
        lines.append(batch_boundary)
    user_seed = _explicit_project_brief(explicit_inputs)
    if user_seed:
        lines.append("用户约束：")
        lines.append(user_seed)
    original_request = str(explicit_inputs.get("original_user_request") or explicit_inputs.get("natural_request") or "").strip()
    if original_request and original_request != user_seed:
        lines.append("原始任务目标：")
        lines.append(original_request)
    if artifact_paths:
        lines.append("目标产物：" + "、".join(artifact_paths) + "。")
    artifact_policy_instruction = render_artifact_policy_instructions(contract.get("artifact_policy"))
    if artifact_policy_instruction:
        lines.append(artifact_policy_instruction)
    readable_artifacts = _readable_artifact_context_for_stage(
        contract=contract,
        explicit_inputs=explicit_inputs,
        artifact_context_packet=dict(artifact_context_packet or {}),
    )
    if readable_artifacts:
        lines.extend(readable_artifacts)
    memory_sections = _readable_memory_snapshot_sections(dict(memory_snapshot or {}))
    if memory_sections:
        lines.extend(memory_sections)
    revision_sections = _readable_revision_packet_sections(dict(revision_packet or {}))
    if revision_sections:
        lines.extend(revision_sections)
    if instructions:
        lines.append("任务要求：")
        lines.extend(f"- {item}" for item in instructions)
    upstream = str(explicit_inputs.get("upstream_final_content") or "").strip()
    if upstream:
        lines.append("可参考的上轮内容：")
        lines.append(upstream[:800])
    return "\n".join(lines)


def _normalize_coordination_authoritative_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(state or {})
    diagnostics = dict(normalized.get("diagnostics") or {})
    if "committed_stage_identities" not in normalized:
        committed = [
            str(item)
            for item in list(diagnostics.get("committed_stage_identities") or [])
            if str(item)
        ]
        normalized["committed_stage_identities"] = sorted(set(committed))
    if "retry_stage_id" not in normalized:
        normalized["retry_stage_id"] = str(diagnostics.get("retry_stage_id") or "").strip()
    for key in ("committed_stage_identities", "retry_stage_id"):
        diagnostics.pop(key, None)
    if diagnostics != dict(normalized.get("diagnostics") or {}):
        normalized["diagnostics"] = diagnostics
    return normalized


def _runtime_result_from_state(
    *,
    state: dict[str, Any],
    events: tuple[Any, ...],
    checkpoint_ref: str,
    diagnostics: dict[str, Any],
) -> GraphCoordinationResult:
    request_payload = _active_execution_request_payload(state)
    request = NodeExecutionRequest.from_dict(request_payload) if request_payload else None
    return GraphCoordinationResult(
        state=state,
        events=events,
        stage_execution_request=request,
        node_work_order=dict(state.get("node_work_order") or {}),
        checkpoint_ref=checkpoint_ref,
        diagnostics=diagnostics,
    )


def _batch_execution_request_payload_from_state(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    batch_execution: dict[str, Any],
) -> dict[str, Any]:
    stored_request = dict(batch_execution.get("request_payload") or {})
    if stored_request:
        return stored_request
    coordination_run_id = str(state.get("coordination_run_id") or "")
    request_id = str(batch_execution.get("request_id") or "")
    dispatch_event_id = str(batch_execution.get("dispatch_event_id") or "")
    batch_range = dict(batch_execution.get("range") or {})
    explicit_inputs = {
        **dict(state.get("pending_inputs") or {}),
        "unit_kind": str(batch_execution.get("unit_kind") or "unit"),
        "unit_batch_id": str(batch_execution.get("batch_id") or ""),
        "unit_batch_execution_id": str(batch_execution.get("execution_id") or ""),
        "unit_batch_plan_id": str(batch_execution.get("plan_id") or ""),
        "unit_batch_sequence_index": _safe_int(batch_execution.get("sequence_index"), 0),
        "unit_batch_label": str(batch_range.get("label") or ""),
        "batch_start_index": _safe_int(batch_range.get("start"), 0),
        "batch_end_index": _safe_int(batch_range.get("end"), _safe_int(batch_range.get("start"), 0)),
        "batch_range": {
            "start": _safe_int(batch_range.get("start"), 0),
            "end": _safe_int(batch_range.get("end"), _safe_int(batch_range.get("start"), 0)),
            "label": str(batch_range.get("label") or ""),
        },
    }
    dispatch_context = {
        "dispatch_event_id": dispatch_event_id,
        "batch_execution_id": str(batch_execution.get("execution_id") or ""),
        "unit_batch_id": str(batch_execution.get("batch_id") or ""),
        "unit_batch_plan_id": str(batch_execution.get("plan_id") or ""),
        "unit_batch_sequence_index": _safe_int(batch_execution.get("sequence_index"), 0),
        "batch_start_index": _safe_int(batch_range.get("start"), 0),
        "batch_end_index": _safe_int(batch_range.get("end"), _safe_int(batch_range.get("start"), 0)),
        "node_id": node_id,
        "stage_id": stage_id,
        "thread_id": coordination_run_id,
        "coordination_run_id": coordination_run_id,
        "root_task_run_id": str(state.get("root_task_run_id") or ""),
    }
    contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
    return {
        "request_id": request_id,
        "coordination_run_id": coordination_run_id,
        "thread_id": coordination_run_id,
        "root_task_run_id": str(state.get("root_task_run_id") or ""),
        "stage_id": stage_id,
        "node_id": node_id,
        "task_ref": str(contract.get("task_ref") or ""),
        "agent_id": str(contract.get("agent_id") or ""),
        "runtime_lane": str(contract.get("runtime_lane") or ""),
        "explicit_inputs": explicit_inputs,
        "dispatch_context": dispatch_context,
    }


def _request_dispatch_identity(request_payload: dict[str, Any]) -> str:
    payload = dict(request_payload or {})
    dispatch_context = dict(payload.get("dispatch_context") or {})
    return "|".join(
        [
            str(payload.get("coordination_run_id") or dispatch_context.get("coordination_run_id") or ""),
            str(payload.get("stage_id") or dispatch_context.get("stage_id") or ""),
            str(payload.get("request_id") or ""),
            str(dispatch_context.get("dispatch_event_id") or ""),
            str(dispatch_context.get("batch_execution_id") or dict(payload.get("explicit_inputs") or {}).get("unit_batch_execution_id") or ""),
        ]
    )


def _readable_artifact_context_for_stage(
    *,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
    artifact_context_packet: dict[str, Any] | None = None,
) -> list[str]:
    policy = dict(contract.get("artifact_context_policy") or {})
    items = [dict(item) for item in list(policy.get("items") or []) if isinstance(item, dict)]
    if not items:
        return []
    sections: list[str] = []
    expanded = dict(dict(artifact_context_packet or {}).get("expanded_text_by_input_key") or {})
    if expanded:
        label_by_key = {
            str(item.get("input_key") or item.get("label") or "").strip(): str(item.get("label") or "").strip()
            for item in items
            if isinstance(item, dict)
        }
        sections.append("产物交接包：")
        for input_key, content in expanded.items():
            text = str(content or "").strip()
            if not text:
                continue
            label = label_by_key.get(str(input_key), "") or str(input_key)
            sections.append(f"{label}（{input_key}）：")
            sections.append(text)
    max_items = max(_safe_int(policy.get("max_items"), len(items)), 1)
    for item in items[:max_items]:
        refs = _artifact_refs_from_value(_resolve_artifact_context_value(item, explicit_inputs=explicit_inputs))
        max_refs = max(_safe_int(item.get("max_refs"), 1), 1)
        for ref in refs[:max_refs]:
            content = _read_artifact_ref_text(ref)
            if not content:
                continue
            label = str(item.get("label") or "可读上下文").strip()
            max_chars = max(_safe_int(item.get("max_chars"), _safe_int(policy.get("default_max_chars"), 12000)), 1)
            sections.append(f"{label}（{ref}）：")
            sections.append(content[:max_chars])
    return sections


def _readable_memory_snapshot_sections(memory_snapshot: dict[str, Any]) -> list[str]:
    records = [dict(item) for item in list(memory_snapshot.get("resolved_records") or []) if isinstance(item, dict)]
    missing = [dict(item) for item in list(memory_snapshot.get("missing_required_records") or []) if isinstance(item, dict)]
    if not records and not missing:
        return []
    lines = ["记忆快照："]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (str(record.get("repository_id") or "").strip(), str(record.get("collection_id") or "").strip())
        grouped.setdefault(key, []).append(record)
    for (repository_id, collection_id), group in grouped.items():
        label = " / ".join(item for item in (repository_id, collection_id) if item) or "formal_memory"
        lines.append(f"[{label}]")
        for record in group[:12]:
            title = str(record.get("model_visible_label") or record.get("title") or record.get("record_key") or record.get("record_id") or record.get("version_id") or "记忆记录").strip()
            address = "/".join(
                item
                for item in (
                    str(record.get("repository_id") or ""),
                    str(record.get("collection_id") or ""),
                    str(record.get("record_key") or ""),
                )
                if item
            )
            content_state = str(record.get("content_state") or "").strip()
            usage = str(record.get("usage_instruction") or "").strip()
            canonical_text = str(record.get("canonical_text") or "").strip()
            summary = str(record.get("summary") or "").strip()
            lines.append(f"- {title} ({address}; content_state={content_state or 'unknown'})")
            if usage:
                lines.append(f"  用途：{usage[:1000]}")
            text = canonical_text or summary
            if text:
                lines.append(f"  内容：{text[:4000]}")
            elif record.get("artifact_refs"):
                lines.append("  警告：此记录只有产物引用，没有正式记忆内容，不能满足 required canonical memory。")
            for warning in list(record.get("content_warnings") or []):
                if isinstance(warning, dict) and warning.get("message"):
                    lines.append(f"  警告：{str(warning.get('message'))[:1000]}")
    if missing:
        lines.append("缺失的必需记忆：")
        for item in missing[:20]:
            address = "/".join(
                part
                for part in (
                    str(item.get("logical_repository_id") or item.get("repository") or ""),
                    str(item.get("collection") or ""),
                    str(dict(item.get("selector") or {}).get("record_key") or ""),
                )
                if part
            )
            reason = str(item.get("reason") or "missing_required_record")
            lines.append(f"- {str(item.get('edge_id') or '')}: {address or 'unknown'} ({reason})")
    return lines


def _required_canonical_memory_content_violations(working_memory_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    context = dict(working_memory_context or {})
    records: list[dict[str, Any]] = []
    for item in list(context.get("formal_memory.required_records") or []):
        if isinstance(item, dict):
            records.append(dict(item))
    for item in list(dict(context.get("formal_memory") or {}).get("required_records") or []):
        if isinstance(item, dict):
            records.append(dict(item))

    violations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        ref = str(record.get("version_id") or record.get("record_id") or record.get("record_key") or "")
        if ref and ref in seen:
            continue
        if ref:
            seen.add(ref)
        requirement = dict(record.get("content_requirement") or {})
        canonical_required = bool(requirement.get("canonical_text_required"))
        refs_only_allowed = bool(requirement.get("artifact_ref_only_allowed"))
        if not canonical_required or refs_only_allowed:
            continue
        canonical_text = str(record.get("canonical_text") or "").strip()
        content_state = str(record.get("content_state") or "").strip()
        status = str(record.get("status") or "").strip()
        if canonical_text and content_state != "refs_only" and status != "candidate":
            continue
        violations.append(
            {
                "edge_id": str(record.get("read_edge_id") or ""),
                "repository": str(record.get("repository_id") or ""),
                "collection": str(record.get("collection_id") or ""),
                "selector": {"record_key": str(record.get("record_key") or "")},
                "version_id": str(record.get("version_id") or ""),
                "record_id": str(record.get("record_id") or ""),
                "record_key": str(record.get("record_key") or ""),
                "status": status,
                "content_state": content_state or "unknown",
                "content_requirement": requirement,
                "reason": "required_canonical_memory_content_invalid",
            }
        )
    return violations


def _working_memory_source_node_ids_for_stage(
    *,
    state: CoordinationRuntimeState,
    target_stage_id: str,
    target_node_id: str,
) -> list[str]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    stage_contracts = {
        str(item.get("stage_id") or item.get("node_id") or "").strip(): dict(item)
        for item in list(graph_spec.get("stage_contracts") or [])
        if isinstance(item, dict) and str(item.get("stage_id") or item.get("node_id") or "").strip()
    }
    source_node_ids: list[str] = []
    for raw_edge in list(graph_spec.get("edges") or []):
        edge = dict(raw_edge or {}) if isinstance(raw_edge, dict) else {}
        edge_target_stage = str(edge.get("target_stage_id") or edge.get("target") or "").strip()
        edge_target_node = str(edge.get("target_node_id") or edge.get("target") or "").strip()
        if edge_target_stage not in {target_stage_id, ""} and edge_target_node not in {target_node_id, ""}:
            continue
        policy = dict(edge.get("working_memory_handoff_policy") or {})
        if not policy:
            continue
        source_stage_id = str(edge.get("source_stage_id") or edge.get("source") or "").strip()
        source_node_id = str(edge.get("source_node_id") or edge.get("source") or "").strip()
        if source_stage_id and source_stage_id in stage_contracts:
            source_node_id = str(stage_contracts[source_stage_id].get("node_id") or source_node_id or source_stage_id)
        value = source_node_id or source_stage_id
        if value and value not in source_node_ids:
            source_node_ids.append(value)
    return source_node_ids


def _memory_edge_allows_refs_only_auto_candidate(edge: dict[str, Any]) -> bool:
    requirement = dict(edge.get("content_requirement") or {})
    materialization_policy = dict(edge.get("materialization_policy") or edge.get("candidate_materialization_policy") or {})
    if bool(requirement.get("artifact_ref_only_allowed")):
        return True
    if bool(requirement.get("canonical_text_required")):
        return False
    if str(materialization_policy.get("canonical_text_mode") or "").strip() in {"none", "refs_only"}:
        return True
    if str(materialization_policy.get("mode") or "").strip() in {"none", "refs_only"}:
        return True
    return False


def _readable_revision_packet_sections(revision_packet: dict[str, Any]) -> list[str]:
    if not revision_packet:
        return []
    lines = ["返修交接包："]
    lines.append("请只使用本交接包中已经展开的文本与当前上下文完成返修；不要输出 read_file、search_text、工具调用标签或任何内部协议片段。")
    for key in ("review_verdict", "required_changes"):
        value = revision_packet.get(key)
        if value not in ("", None, [], {}):
            lines.append(f"- {key}: {value}")
    _append_revision_ref_texts(
        lines,
        title="审核报告内容",
        refs=_artifact_refs_from_value(revision_packet.get("review_result_refs")),
        max_chars=12000,
    )
    _append_revision_ref_texts(
        lines,
        title="上一版候选产物内容",
        refs=_artifact_refs_from_value(revision_packet.get("previous_candidate_artifact_refs")),
        max_chars=30000,
    )
    for key in ("review_result_refs", "previous_candidate_artifact_refs"):
        value = revision_packet.get(key)
        if value not in ("", None, [], {}):
            lines.append(f"- {key}: {value}")
    return lines


def _append_revision_ref_texts(lines: list[str], *, title: str, refs: list[str], max_chars: int) -> None:
    if not refs:
        return
    appended = False
    for ref in refs[:3]:
        if "/debug/" in str(ref).replace("\\", "/"):
            continue
        content = _read_artifact_ref_text(ref)
        text = str(content or "").strip()
        if not text:
            continue
        if not appended:
            lines.append(f"{title}：")
            appended = True
        lines.append(f"--- {ref} ---")
        lines.append(text[:max_chars])


def _resolve_artifact_context_value(item: dict[str, Any], *, explicit_inputs: dict[str, Any]) -> Any:
    source = str(item.get("source") or "input_key").strip()
    if source == "input_key":
        return explicit_inputs.get(str(item.get("input_key") or "").strip())
    if source == "literal":
        return item.get("value")
    if source == "collect":
        values: list[Any] = []
        for child in list(item.get("items") or []):
            if not isinstance(child, dict):
                continue
            value = _resolve_artifact_context_value(child, explicit_inputs=explicit_inputs)
            if isinstance(value, list):
                values.extend(value)
            elif value not in ("", None, [], {}):
                values.append(value)
        return values
    return None


def _read_artifact_ref_text(ref: str) -> str:
    raw = str(ref or "").strip()
    if not raw.startswith("artifact:"):
        return ""
    rel = raw[len("artifact:") :]
    candidates = [Path(rel)]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / rel)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _render_runtime_template(template: str, values: dict[str, Any]) -> str:
    text = str(template or "")
    if not text:
        return ""
    try:
        return text.format_map(_SafeFormatValues(values))
    except (KeyError, ValueError, IndexError):
        rendered = text
        for key, value in dict(values or {}).items():
            rendered = rendered.replace("{" + str(key) + "}", str(value))
        return rendered


def _runtime_batch_boundary_instruction(*, contract: dict[str, Any], explicit_inputs: dict[str, Any]) -> str:
    policy = _runtime_batch_boundary_policy(contract=contract, explicit_inputs=explicit_inputs)
    if policy.get("enabled") is False:
        return ""
    start_key = str(policy.get("start_key") or "batch_start_index").strip()
    end_key = str(policy.get("end_key") or "batch_end_index").strip()
    count_key = str(policy.get("count_key") or "unit_batch_size").strip()
    list_key = str(policy.get("list_key") or "unit_batch_list").strip()
    metric_key = str(policy.get("target_metric_key") or "batch_target_units").strip()
    start = _safe_int(explicit_inputs.get(start_key), 0)
    end = _safe_int(explicit_inputs.get(end_key), 0)
    unit_count = _safe_int(explicit_inputs.get(count_key), 0)
    if start <= 0 or end < start:
        return ""
    unit_label = str(policy.get("unit_label") or explicit_inputs.get("unit_label") or "单元").strip()
    unit_label_prefix = str(policy.get("unit_label_prefix") or explicit_inputs.get("unit_label_prefix") or "").strip()
    unit_label_suffix = str(policy.get("unit_label_suffix") or explicit_inputs.get("unit_label_suffix") or unit_label).strip()
    range_template = str(policy.get("range_template") or "本节点只允许处理{unit_label_prefix}{start}{unit_label_suffix}至{unit_label_prefix}{end}{unit_label_suffix}。").strip()
    list_template = str(policy.get("list_template") or "允许单元清单：{unit_list}。").strip()
    size_template = str(policy.get("size_template") or "当前运行时每轮批次大小为 {unit_count} {unit_label}。").strip()
    metric_template = str(policy.get("metric_template") or "当前批次目标工作量约 {target_metric}。").strip()
    conflict_template = str(
        policy.get("conflict_template")
        or "如果项目启动包、上游旧产物或历史摘要出现其他批次大小或其他范围，以本轮处理边界为准。"
    ).strip()
    unit_list = str(explicit_inputs.get(list_key) or "").strip()
    if not unit_list:
        separator = str(policy.get("unit_list_separator") or "、")
        unit_list = separator.join(f"{unit_label_prefix}{index}{unit_label_suffix}" for index in range(start, end + 1))
    target_metric = _safe_int(explicit_inputs.get(metric_key), 0)
    values = {
        **dict(explicit_inputs or {}),
        "start": start,
        "end": end,
        "unit_count": unit_count,
        "unit_label": unit_label,
        "unit_label_prefix": unit_label_prefix,
        "unit_label_suffix": unit_label_suffix,
        "unit_list": unit_list,
        "target_metric": target_metric,
    }
    parts = [
        _render_runtime_template(range_template, values),
        _render_runtime_template(list_template, values),
    ]
    if unit_count:
        parts.append(_render_runtime_template(size_template, values))
    if target_metric:
        parts.append(_render_runtime_template(metric_template, values))
    if conflict_template:
        parts.append(_render_runtime_template(conflict_template, values))
    return "".join(parts)


def _runtime_batch_boundary_policy(*, contract: dict[str, Any], explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    for source in (
        dict(contract.get("runtime_batch_boundary_policy") or {}),
        dict(contract.get("memory_writeback_policy") or {}).get("runtime_batch_boundary_policy"),
        dict(contract.get("executor_policy") or {}).get("runtime_batch_boundary_policy"),
        explicit_inputs.get("runtime_batch_boundary_policy"),
    ):
        if isinstance(source, dict):
            policy = {**policy, **source}
    if policy:
        return policy
    unit_label = str(explicit_inputs.get("unit_label") or "").strip()
    if unit_label:
        return {"unit_label": unit_label}
    return {}


def _explicit_inputs_with_runtime_boundary_policy(
    *,
    explicit_inputs: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    policy = _runtime_batch_boundary_policy(contract=contract, explicit_inputs=explicit_inputs)
    if not policy:
        return dict(explicit_inputs or {})
    return {
        **dict(explicit_inputs or {}),
        "runtime_batch_boundary_policy": policy,
    }


def _agent_visible_checkout_explicit_inputs(explicit_inputs: dict[str, Any]) -> dict[str, Any]:
    """Strip runtime checkout controls before constructing model-facing input packets."""

    visible: dict[str, Any] = {}
    for key, value in dict(explicit_inputs or {}).items():
        key_text = str(key or "").strip()
        if _rewind_input_key_is_runtime_residue(key_text):
            continue
        if key_text in {"rewind_invalidated_artifacts"}:
            continue
        visible[key_text] = value
    return visible


def _explicit_inputs_with_replay_policy(
    *,
    explicit_inputs: dict[str, Any],
    contract: dict[str, Any],
    node_id: str,
) -> dict[str, Any]:
    policy = _replay_sanitization_policy(contract=contract, node_id=node_id)
    if not policy:
        return dict(explicit_inputs or {})
    return {
        **dict(explicit_inputs or {}),
        "replay_sanitization_policy": policy,
    }


def _replay_sanitization_policy(*, contract: dict[str, Any], node_id: str) -> dict[str, Any]:
    _ = node_id
    for source in (
        dict(contract.get("revision_context_policy") or {}),
        dict(contract.get("quality_retry_policy") or {}),
        dict(contract.get("executor_policy") or {}),
        dict(contract.get("metadata") or {}),
    ):
        policy = source.get("replay_sanitization_policy")
        if isinstance(policy, dict) and policy:
            return dict(policy)
    return {}


class _SafeFormatValues(dict):
    def __init__(self, values: dict[str, Any]) -> None:
        super().__init__({str(key): value for key, value in dict(values or {}).items()})

    def __missing__(self, key: str) -> str:
        return "{" + str(key) + "}"


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


def _contract_from_payload(payload: dict[str, Any]) -> CoordinationStageContract:
    return CoordinationStageContract(
        stage_id=str(payload.get("stage_id") or ""),
        task_ref=str(payload.get("task_ref") or ""),
        node_id=str(payload.get("node_id") or ""),
        required_inputs=tuple(str(item) for item in list(payload.get("required_inputs") or []) if str(item)),
        optional_inputs=tuple(str(item) for item in list(payload.get("optional_inputs") or []) if str(item)),
        input_bindings=tuple(dict(item) for item in list(payload.get("input_bindings") or []) if isinstance(item, dict)),
        output_mappings=tuple(dict(item) for item in list(payload.get("output_mappings") or []) if isinstance(item, dict)),
        gate_policy=str(payload.get("gate_policy") or ""),
        on_success=str(payload.get("on_success") or "advance"),
        on_failure=str(payload.get("on_failure") or "fail_closed"),
        retry_policy=dict(payload.get("retry_policy") or {}),
        agent_id=str(payload.get("agent_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        role=str(payload.get("role") or ""),
        title=str(payload.get("title") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        node_type=str(payload.get("node_type") or ""),
        executor_policy=dict(payload.get("executor_policy") or {}),
        memory_read_policy=dict(payload.get("memory_read_policy") or {}),
        memory_writeback_policy=dict(payload.get("memory_writeback_policy") or {}),
        dynamic_memory_read_policy=dict(payload.get("dynamic_memory_read_policy") or {}),
        review_gate_policy=dict(payload.get("review_gate_policy") or {}),
        human_gate_policy=dict(payload.get("human_gate_policy") or {}),
        artifact_policy=dict(payload.get("artifact_policy") or {}),
        stream_policy=dict(payload.get("stream_policy") or {}),
        artifact_context_policy=dict(payload.get("artifact_context_policy") or {}),
        revision_context_policy=dict(payload.get("revision_context_policy") or {}),
        quality_retry_policy=dict(payload.get("quality_retry_policy") or {}),
        artifact_targets=tuple(dict(item) for item in list(payload.get("artifact_targets") or []) if isinstance(item, dict)),
    )


def _stage_scope_for_resume(*, state: dict[str, Any], stage_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    latest_record = _latest_timeline_result_record(state=state, stage_id=stage_id)
    pending_inputs = dict(state.get("pending_inputs") or {})
    phase_id = str(contract.get("phase_id") or latest_record.get("timeline_coordinate", {}).get("phase_id") or _runtime_node_value(state, stage_id, "phase_id") or "phase.unassigned")
    scope_path = [str(item) for item in list(latest_record.get("scope_path") or []) if str(item)]
    if not scope_path:
        scope_path = ["run", phase_id]
    dependency_scope_key = (
        str(latest_record.get("dependency_scope_key") or "")
        or _dependency_scope_key_from_inputs(pending_inputs)
        or "/".join(str(item).strip().replace("/", "_") for item in scope_path if str(item).strip())
    )
    return {
        "scope_type": "stage",
        "scope_path": scope_path,
        "phase_id": phase_id,
        "iteration_index": _safe_int(dict(latest_record.get("timeline_coordinate") or {}).get("iteration_index") or pending_inputs.get("iteration_index"), 0),
        "volume_index": _safe_int(dict(latest_record.get("timeline_coordinate") or {}).get("volume_index") or pending_inputs.get("volume_index"), 0),
        "batch_start_index": _safe_int(dict(latest_record.get("timeline_coordinate") or {}).get("batch_start_index") or pending_inputs.get("batch_start_index"), 0),
        "batch_end_index": _safe_int(dict(latest_record.get("timeline_coordinate") or {}).get("batch_end_index") or pending_inputs.get("batch_end_index"), 0),
        "round_index": _safe_int(
            dict(latest_record.get("timeline_coordinate") or {}).get("round_index")
            or pending_inputs.get("round_index")
            or pending_inputs.get("revision_round")
            or pending_inputs.get("attempt_index"),
            0,
        ),
        "dependency_scope_key": dependency_scope_key,
    }








def _retry_allowed(*, contract: dict[str, Any], retry_counts: dict[str, Any], stage_id: str) -> bool:
    on_failure = str(contract.get("on_failure") or "").strip()
    retry_policy = dict(contract.get("retry_policy") or {})
    limit = int(retry_policy.get("retry_limit") or retry_policy.get("max_attempts") or 0)
    if on_failure == "retry_once" and limit <= 0:
        limit = 1
    if str(retry_policy.get("mode") or "").strip() in {"retry", "retry_once"} and limit <= 0:
        limit = 1
    if limit <= 0:
        return False
    return int(retry_counts.get(stage_id) or 0) < limit


def _human_gate_required(contract: dict[str, Any], *, state: dict[str, Any] | None = None) -> bool:
    gate_policy = str(contract.get("gate_policy") or "").strip()
    on_failure = str(contract.get("on_failure") or "").strip()
    human_gate_policy = dict(contract.get("human_gate_policy") or {})
    mode = str(human_gate_policy.get("mode") or "").strip()
    if state is not None:
        continuation_policy = dict(dict(state.get("diagnostics") or {}).get("continuation_policy") or {})
        mode = mode or str(continuation_policy.get("human_gate_mode") or "").strip()
    if mode in {"disabled", "off", "auto_continue", "non_blocking"}:
        return False
    return (
        gate_policy in {"human_gate", "manual_review", "human_review", "wait_for_human"}
        or on_failure in {"human_gate", "manual_review", "human_review", "wait_for_human"}
        or human_gate_policy.get("enabled") is True
    )


def _resume_human_gate_state(*, state: CoordinationRuntimeState, event: dict[str, Any]) -> dict[str, Any]:
    human_gate = dict(state.get("human_gate") or {})
    stage_id = str(event.get("stage_id") or human_gate.get("stage_id") or human_gate.get("pending_stage_id") or state.get("active_stage_id") or "").strip()
    if not stage_id:
        return {"diagnostics": {**dict(state.get("diagnostics") or {}), "human_gate_warning": "missing_stage_id"}}
    decision = str(
        event.get("decision")
        or event.get("action")
        or event.get("status")
        or ("approve" if event.get("accepted") is True else "")
    ).strip().lower()
    node_statuses = dict(state.get("node_statuses") or {})
    retry_counts = dict(state.get("retry_counts") or {})
    diagnostics = dict(state.get("diagnostics") or {})
    contract_status = dict(state.get("contract_status") or {})
    if decision in {"approve", "approved", "accept", "accepted", "continue"}:
        original_event = dict(human_gate.get("original_event") or {})
        artifact_refs = [
            str(item)
            for item in list(event.get("artifact_refs") or original_event.get("artifact_refs") or [])
            if str(item)
        ]
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        node_id = str(contract.get("node_id") or stage_id)
        stage_scope = _stage_scope_for_resume(state=state, stage_id=stage_id, contract=contract)
        approval_event = {
            **original_event,
            **event,
            "accepted": True,
            "artifact_refs": artifact_refs,
            "task_result_ref": str(event.get("task_result_ref") or original_event.get("task_result_ref") or original_event.get("agent_run_result_ref") or ""),
        }
        request_payload = _stage_result_request_payload(
            state=state,
            request_payload=_active_execution_request_payload(state),
            event=approval_event,
            stage_id=stage_id,
            node_id=node_id,
            contract=contract,
            stage_scope=stage_scope,
        )
        stage_outputs = _stage_outputs_from_artifact_refs(contract=contract, artifact_refs=artifact_refs)
        standard_result_package = build_standard_node_result_package(
            request_payload=request_payload,
            event=approval_event,
            outputs=stage_outputs,
            artifact_refs=artifact_refs,
        )
        current_clock_seq = _safe_int(dict(state.get("timeline") or {}).get("current_clock_seq"), 0)
        latest_record = _latest_timeline_result_record(state=state, stage_id=stage_id)
        result_event = {
            "event_id": str(event.get("event_id") or f"human_resume:{stage_id}:{current_clock_seq or _safe_int(latest_record.get('clock_seq'), 0) or 1}"),
            "clock_seq": current_clock_seq or _safe_int(latest_record.get("clock_seq"), 0) or 1,
            "scope_path": list(stage_scope.get("scope_path") or latest_record.get("scope_path") or ["run"]),
        }
        timeline_result_record = build_timeline_result_record(
            request_payload=request_payload,
            result_event=result_event,
            stage_id=stage_id,
            node_id=node_id,
            accepted=True,
            artifact_refs=artifact_refs,
            validation_result={"manual_resume_decision": decision, "accepted_by_human_gate": True},
        )
        result_record_payload = timeline_result_record.to_dict()
        stage_result_payload = {
            "task_run_id": str(original_event.get("task_run_id") or event.get("task_run_id") or ""),
            "task_ref": str(contract.get("task_ref") or original_event.get("task_ref") or event.get("task_ref") or ""),
            "task_result_ref": str(approval_event.get("task_result_ref") or ""),
            "agent_run_result_ref": str(original_event.get("agent_run_result_ref") or ""),
            "artifact_refs": artifact_refs,
            "trace_refs": [],
            "outputs": stage_outputs,
            "diagnostics": {"manual_resume_decision": decision},
            "accepted": True,
            "standard_result_package": standard_result_package.to_dict(),
            "timeline_result_record": result_record_payload,
        }
        stage_results = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        stage_results[stage_id] = stage_result_payload
        stage_results_by_instance = {
            str(key): dict(value)
            for key, value in dict(state.get("stage_results_by_instance") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        stage_results_by_instance[timeline_result_record.result_record_id] = dict(stage_result_payload)
        timeline_result_records = [dict(item) for item in list(state.get("timeline_result_records") or []) if isinstance(item, dict)]
        if not any(str(item.get("result_record_id") or "") == timeline_result_record.result_record_id for item in timeline_result_records):
            timeline_result_records.append(result_record_payload)
        result_record_index = {
            str(key): dict(value)
            for key, value in dict(state.get("result_record_index") or {}).items()
            if str(key) and isinstance(value, dict)
        }
        result_record_index[timeline_result_record.result_record_id] = result_record_payload
        latest_stage_result_records = {
            str(key): str(value)
            for key, value in dict(state.get("latest_stage_result_records") or {}).items()
            if str(key) and str(value)
        }
        latest_stage_result_records[stage_id] = timeline_result_record.result_record_id
        accepted_result_records_by_scope = {
            str(scope): {str(stage): str(record_id) for stage, record_id in dict(records or {}).items() if str(stage) and str(record_id)}
            for scope, records in dict(state.get("accepted_result_records_by_scope") or {}).items()
            if str(scope) and isinstance(records, dict)
        }
        for scope_key in (timeline_result_record.scope_key, timeline_result_record.dependency_scope_key):
            if not scope_key:
                continue
            scope_records = dict(accepted_result_records_by_scope.get(scope_key) or {})
            scope_records[stage_id] = timeline_result_record.result_record_id
            accepted_result_records_by_scope[scope_key] = scope_records
        node_statuses[stage_id] = "completed"
        contract_status = _set_contract_node_status(
            contract_status,
            stage_id=stage_id,
            node_status_value="satisfied",
            accepted=True,
            task_result_ref=str(event.get("task_result_ref") or original_event.get("task_result_ref") or original_event.get("agent_run_result_ref") or ""),
            artifact_refs=artifact_refs,
            missing_required_inputs=[],
            diagnostics={"reason": "human_gate_approved", "work_order_id": str(request_payload.get("work_order_id") or request_payload.get("request_id") or "")},
        )
        diagnostics["human_gate"] = {"status": "approved", "stage_id": stage_id}
        return {
            "node_statuses": node_statuses,
            "stage_results": stage_results,
            "stage_results_by_instance": stage_results_by_instance,
            "timeline_result_records": timeline_result_records,
            "result_record_index": result_record_index,
            "latest_stage_result_records": latest_stage_result_records,
            "accepted_result_records_by_scope": accepted_result_records_by_scope,
            "contract_status": contract_status,
            "human_gate": {**human_gate, "status": "approved", "stage_id": stage_id, "resume": dict(event)},
            "terminal_status": "",
            "missing_required_inputs": [],
            **_execution_boundary_cleared(),
            "diagnostics": diagnostics,
        }
    if decision in {"retry", "rework", "revise", "rerun"}:
        retry_counts[stage_id] = int(retry_counts.get(stage_id) or 0) + 1
        node_statuses[stage_id] = "pending"
        contract_status = _set_contract_node_status(
            contract_status,
            stage_id=stage_id,
            node_status_value="pending_retry",
            accepted=False,
            task_result_ref="",
            artifact_refs=[],
            missing_required_inputs=[],
            diagnostics={"reason": "human_gate_retry", "retry_count": retry_counts.get(stage_id)},
        )
        diagnostics["retry_counts"] = retry_counts
        diagnostics["human_gate"] = {"status": "retry", "stage_id": stage_id}
        return {
            "node_statuses": node_statuses,
            "retry_counts": retry_counts,
            "retry_stage_id": stage_id,
            "contract_status": contract_status,
            "human_gate": {**human_gate, "status": "retry", "stage_id": stage_id, "resume": dict(event)},
            "terminal_status": "",
            "missing_required_inputs": [],
            **_execution_boundary_cleared(),
            "diagnostics": diagnostics,
        }
    if decision in {"reject", "rejected", "fail", "failed"}:
        node_statuses[stage_id] = "failed"
        contract_status = _set_contract_node_status(
            contract_status,
            stage_id=stage_id,
            node_status_value="failed",
            accepted=False,
            task_result_ref="",
            artifact_refs=[],
            missing_required_inputs=[],
            diagnostics={"reason": "human_gate_rejected"},
        )
        diagnostics["human_gate"] = {"status": "rejected", "stage_id": stage_id}
        return {
            "node_statuses": node_statuses,
            "contract_status": contract_status,
            "human_gate": {**human_gate, "status": "rejected", "stage_id": stage_id, "resume": dict(event)},
            "terminal_status": "failed",
            "missing_required_inputs": [],
            **_execution_boundary_cleared(),
            "diagnostics": diagnostics,
        }
    node_statuses[stage_id] = "waiting_for_human"
    contract_status = _set_contract_node_status(
        contract_status,
        stage_id=stage_id,
        node_status_value="human_gate",
        accepted=False,
        task_result_ref="",
        artifact_refs=[],
        missing_required_inputs=[],
        diagnostics={"reason": "human_gate_waiting_for_decision"},
    )
    diagnostics["human_gate"] = {"status": "waiting", "stage_id": stage_id}
    return {
        "node_statuses": node_statuses,
        "contract_status": contract_status,
        "human_gate": {**human_gate, "status": "waiting", "stage_id": stage_id, "resume": dict(event)},
        "terminal_status": "waiting_for_human",
        **_execution_boundary_cleared(),
        "diagnostics": diagnostics,
    }


def _topological_stage_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    node_ids = [str(item.get("node_id") or item.get("id") or "").strip() for item in nodes]
    node_ids = [item for item in node_ids if item]
    incoming_count = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if source in incoming_count and target in incoming_count:
            incoming_count[target] += 1
            outgoing[source].append(target)
    queue = [node_id for node_id in node_ids if incoming_count[node_id] == 0]
    resolved: list[str] = []
    while queue:
        node_id = queue.pop(0)
        if node_id in resolved:
            continue
        resolved.append(node_id)
        for target in outgoing.get(node_id, []):
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                queue.append(target)
    return resolved if len(resolved) == len(node_ids) else node_ids


def _clear_execution_boundary(state: dict[str, Any], *, terminal_status: str) -> dict[str, Any]:
    return {
        "terminal_status": terminal_status,
        **_execution_boundary_cleared(),
    }


def _execution_boundary_cleared() -> dict[str, Any]:
    return {
        "node_work_order": {},
        "node_execution_request": {},
        "stage_execution_request": {},
        "a2a_payload": {},
    }


def _execution_boundary_preserved(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_work_order": dict(state.get("node_work_order") or {}),
        "node_execution_request": _active_execution_request_payload(state),
        "stage_execution_request": dict(state.get("stage_execution_request") or {}),
        "a2a_payload": dict(state.get("a2a_payload") or {}),
    }


def _downstream_stage_ids(*, state: dict[str, Any], stage_id: str, include_self: bool = True) -> list[str]:
    target = str(stage_id or "").strip()
    if not target:
        return []
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    edges = [dict(item) for item in list(graph_spec.get("edges") or []) if isinstance(item, dict)]
    order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
    known = set(order)
    order_index = {item: index for index, item in enumerate(order)}
    outgoing: dict[str, list[str]] = {item: [] for item in known}
    for edge in edges:
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        next_stage = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if (
            source in known
            and next_stage in known
            and _edge_allows_downstream_invalidation(edge=edge, source=source, target=next_stage, order_index=order_index)
            and next_stage not in outgoing.setdefault(source, [])
        ):
            outgoing[source].append(next_stage)
    visited: set[str] = set()
    queue = [target]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for next_stage in outgoing.get(current, []):
            if next_stage not in visited:
                queue.append(next_stage)
    ordered = [item for item in order if item in visited]
    if len(ordered) <= 1 and target in order:
        ordered = order[order.index(target) :]
    if include_self and target not in ordered:
        ordered.insert(0, target)
    if not include_self:
        ordered = [item for item in ordered if item != target]
    return ordered


def _edge_allows_downstream_invalidation(
    *,
    edge: dict[str, Any],
    source: str,
    target: str,
    order_index: dict[str, int],
) -> bool:
    metadata = dict(edge.get("metadata") or {})
    mode = str(edge.get("mode") or edge.get("edge_type") or metadata.get("edge_type") or "").strip()
    dependency_role = str(metadata.get("dependency_role") or edge.get("dependency_role") or "").strip()
    loop_role = str(metadata.get("loop_role") or edge.get("loop_role") or "").strip()
    verdict = str(metadata.get("verdict") or edge.get("verdict") or "").strip()
    if mode in {"review_feedback", "repair_feedback", "conditional_feedback"}:
        return False
    if mode in {"revision_request", "repair_route", "human_handoff", "fail_closed", "conditional_route"}:
        return False
    if dependency_role in {
        "feedback",
        "conditional_feedback",
        "repair_feedback",
        "non_blocking_feedback",
        "conditional_route",
        "repair_route",
        "failure_route",
        "human_handoff",
    }:
        return False
    if loop_role in {"repair", "feedback"}:
        return False
    if review_verdict_blocks_downstream_invalidation(verdict):
        return False
    return order_index.get(target, -1) >= order_index.get(source, -1)


def _rewound_contract_status(
    status: dict[str, Any],
    *,
    invalidated_stage_ids: list[str],
    target_stage_id: str,
    reason: str,
) -> dict[str, Any]:
    invalidated = {str(item) for item in list(invalidated_stage_ids or []) if str(item)}
    next_status = dict(status or {})
    node_status = {
        str(stage): dict(payload)
        for stage, payload in dict(next_status.get("node_status") or {}).items()
        if str(stage) and isinstance(payload, dict)
    }
    acceptance_results = {
        str(stage): dict(payload)
        for stage, payload in dict(next_status.get("acceptance_results") or {}).items()
        if str(stage) and isinstance(payload, dict) and str(stage) not in invalidated
    }
    for stage in invalidated:
        if stage not in node_status:
            continue
        node_status[stage] = {
            **dict(node_status.get(stage) or {}),
            "status": "pending_rewind" if stage == target_stage_id else "invalidated_downstream",
            "accepted": False,
            "task_result_ref": "",
            "artifact_refs": [],
            "missing_required_inputs": [],
            "updated_at": time.time(),
            "diagnostics": {"rewound_from_stage": target_stage_id, "reason": reason},
        }
    next_status["node_status"] = node_status
    next_status["acceptance_results"] = acceptance_results
    return next_status


def _rewind_preserved_pending_inputs(
    pending_inputs: dict[str, Any],
    *,
    invalidated_stage_ids: list[str],
    stage_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    invalidated = {str(item) for item in list(invalidated_stage_ids or []) if str(item)}
    valid_artifact_refs = {
        str(ref)
        for result in dict(stage_results or {}).values()
        if isinstance(result, dict)
        for ref in list(result.get("artifact_refs") or [])
        if str(ref)
    }
    preserved: dict[str, Any] = {}
    for key, value in dict(pending_inputs or {}).items():
        key_text = str(key)
        if _rewind_input_key_is_runtime_residue(key_text):
            continue
        if _input_key_scoped_to_invalidated_stage(key_text, invalidated):
            continue
        filtered = _filter_rewind_input_value(value, valid_artifact_refs=valid_artifact_refs)
        if filtered in ("", None, [], {}):
            continue
        preserved[key_text] = filtered
    return preserved


def _rewind_input_key_is_runtime_residue(key: str) -> bool:
    key_text = str(key or "").strip()
    if not key_text:
        return True
    if re.fullmatch(r"contract\.[A-Za-z0-9_.:-]+:artifact_refs", key_text):
        return True
    if key_text in {
        "upstream_output_refs",
        "revision_required",
        "required_changes",
        "review_verdict",
        "previous_candidate_artifact_refs",
        "previous_revision_context_refs",
        "rewind_invalidated_artifacts",
        "rewind_from_stage",
        "rewind_reason",
        "force_replay",
        "force_replay_after",
    }:
        return True
    return key_text.startswith(("previous_review_", "revision_"))


def _input_key_scoped_to_invalidated_stage(key: str, invalidated_stage_ids: set[str]) -> bool:
    key_text = str(key or "")
    for stage in invalidated_stage_ids:
        stage_text = str(stage or "")
        if not stage_text:
            continue
        if key_text == stage_text:
            return True
        if key_text.startswith((f"{stage_text}_", f"{stage_text}:", f"{stage_text}.")):
            return True
        if key_text.endswith((f"_{stage_text}", f":{stage_text}", f".{stage_text}")):
            return True
        if key_text.endswith(f"{stage_text}_ref") or key_text.endswith(f"{stage_text}_refs"):
            return True
        if f".{stage_text}." in key_text or f":{stage_text}:" in key_text:
            return True
    return False


def _filter_rewind_input_value(value: Any, *, valid_artifact_refs: set[str]) -> Any:
    if isinstance(value, list):
        filtered = [_filter_rewind_input_value(item, valid_artifact_refs=valid_artifact_refs) for item in value]
        return [item for item in filtered if item not in ("", None, [], {})]
    if isinstance(value, tuple):
        filtered = [_filter_rewind_input_value(item, valid_artifact_refs=valid_artifact_refs) for item in value]
        return [item for item in filtered if item not in ("", None, [], {})]
    if isinstance(value, dict):
        return {
            str(key): filtered
            for key, item in value.items()
            if (filtered := _filter_rewind_input_value(item, valid_artifact_refs=valid_artifact_refs)) not in ("", None, [], {})
        }
    if isinstance(value, str) and value.startswith("artifact:") and valid_artifact_refs and value not in valid_artifact_refs:
        return ""
    return value


def _scheduler_node_sets(
    *,
    order: list[str],
    node_statuses: dict[str, str],
    state: dict[str, Any],
    terminal_status: str = "",
) -> dict[str, Any]:
    runtime_spec = _runtime_spec_from_state(state)
    if runtime_spec is None:
        blocked_nodes = [node for node in order if node_statuses.get(node) not in {"completed", "failed"}]
        return {
            "ready_nodes": [],
            "blocked_nodes": blocked_nodes,
            "running_nodes": [node for node in order if node_statuses.get(node) == "running"],
            "waiting_nodes": [
                node
                for node in order
                if node_statuses.get(node) in {"waiting_for_human", "human_gate", "waiting"}
            ],
            "completed_nodes": [node for node in order if node_statuses.get(node) == "completed"],
            "failed_nodes": [node for node in order if node_statuses.get(node) == "failed"],
            "terminal_status": terminal_status or "blocked",
            "missing_required_inputs": ["coordination_graph_spec"],
            "diagnostics": {
                **dict(state.get("diagnostics") or {}),
                "scheduler_authority": "task_graph_scheduler_state",
                "scheduler_error": "missing_coordination_graph_spec",
            },
        }
    scheduler_state = bootstrap_scheduler_state(
        runtime_spec=runtime_spec,
        node_statuses=node_statuses,
        result_record_index=dict(state.get("result_record_index") or {}),
        accepted_result_records_by_scope=dict(state.get("accepted_result_records_by_scope") or {}),
        edge_handoff_index=_edge_handoff_index_from_state(state),
        active_scope_key=_active_scope_key_for_scheduler(state),
        terminal_status=terminal_status,
        mode="active",
    )
    effective_node_statuses = {
        str(key): str(value)
        for key, value in dict(scheduler_state.diagnostics.get("effective_node_statuses") or {}).items()
        if str(key)
    }
    resolved_node_statuses = effective_node_statuses or dict(node_statuses)
    return {
        "ready_nodes": list(scheduler_state.ready_node_ids),
        "blocked_nodes": list(scheduler_state.blocked_node_ids),
        "running_nodes": list(scheduler_state.running_node_ids),
        "waiting_nodes": [
            node_id
            for node_id, status in node_statuses.items()
            if str(status) in {"waiting_for_human", "human_gate", "waiting"}
        ],
        "completed_nodes": list(scheduler_state.completed_node_ids),
        "failed_nodes": list(scheduler_state.failed_node_ids),
        "terminal_status": scheduler_state.terminal_status,
        "node_statuses": resolved_node_statuses,
        "diagnostics": {
            **dict(state.get("diagnostics") or {}),
            "task_graph_scheduler_state": scheduler_state.to_dict(),
            "scheduler_authority": "task_graph_scheduler_state",
        },
    }






def _node_dispatch_idempotency_key(
    *,
    coordination_run_id: str,
    stage_id: str,
    stage_scope: dict[str, Any],
    explicit_inputs: dict[str, Any],
    retry_counts: dict[str, Any],
) -> str:
    retry_index = _safe_int(dict(retry_counts or {}).get(stage_id), 0)
    force_replay_after = str(explicit_inputs.get("force_replay_after") or "").strip()
    seed = {
        "coordination_run_id": coordination_run_id,
        "stage_id": stage_id,
        "scope_path": list(stage_scope.get("scope_path") or []),
        "dependency_scope_key": str(stage_scope.get("dependency_scope_key") or ""),
        "volume_index": _safe_int(stage_scope.get("volume_index"), 0),
        "batch_start_index": _safe_int(stage_scope.get("batch_start_index"), 0),
        "batch_end_index": _safe_int(stage_scope.get("batch_end_index"), 0),
        "round_index": _safe_int(stage_scope.get("round_index"), 0),
        "iteration_index": _safe_int(stage_scope.get("iteration_index"), 0),
        "retry_index": retry_index,
        "force_replay_after": force_replay_after,
    }
    return f"{coordination_run_id}:{stage_id}:dispatch:{_short_hash(seed)}"


def _active_scope_key_for_scheduler(state: dict[str, Any]) -> str:
    request = dict(state.get("node_execution_request") or state.get("stage_execution_request") or {})
    dispatch_context = dict(request.get("dispatch_context") or {})
    dependency_scope_key = str(dispatch_context.get("dependency_scope_key") or "").strip()
    if dependency_scope_key:
        return dependency_scope_key
    scope_path = list(dispatch_context.get("scope_path") or [])
    if not scope_path:
        active_stage_id = str(state.get("active_stage_id") or "")
        contract = dict(dict(state.get("stage_contracts") or {}).get(active_stage_id) or {})
        phase_id = str(contract.get("phase_id") or _runtime_node_value(state, active_stage_id, "phase_id") or "phase.unassigned")
        scope_path = ["run", phase_id]
        pending_inputs = dict(state.get("pending_inputs") or {})
        coordinate = _runtime_scope_coordinate_from_inputs(pending_inputs)
        scope_path.extend(_scope_path_segments_from_coordinate(coordinate))
        retry_index = _safe_int(dict(state.get("retry_counts") or {}).get(active_stage_id), 0)
        if retry_index > 0:
            scope_path.append(f"retry[{retry_index}]")
        loop_index = int(coordinate.get("iteration_index") or 0)
        if loop_index > 0:
            scope_path.append(f"iteration[{loop_index}]")
    return _dependency_scope_key_from_inputs(dict(state.get("pending_inputs") or {})) or "/".join(str(item).strip().replace("/", "_") for item in list(scope_path or ["run"]) if str(item).strip()) or "run"


