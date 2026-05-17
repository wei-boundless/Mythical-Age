from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Annotated, Any, TypedDict

from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from langgraph.graph import END, START, StateGraph

from memory_system.formal_memory_service import FormalMemoryService
from memory_system.working_memory_finalizer import WorkingMemoryFinalizer
from memory_system.working_memory_service import WorkingMemoryService
from tasks import TaskContractRegistry
from tasks.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from tasks.coordination_graph_models import TaskGraphRuntimeEdge, TaskGraphRuntimeNode, TaskGraphRuntimeSpec
from tasks.task_graph_models import task_graph_from_dict

from .a2a_stage_payload import build_stage_execution_a2a_payload
from .artifact_refs import ArtifactRefIndex, collect_task_result_output_refs
from .contract_compiler import compile_coordination_contract_manifest
from .contract_compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledNodeContract,
    CompiledRuntimeContract,
    ContractCompileIssue,
    ContractManifest,
)
from .continuation_inputs import ContinuationInputBinder
from .continuation_policy import (
    CoordinationContinuationPolicy,
    CoordinationStageContract,
    contract_by_stage,
    parse_stage_contracts,
    derive_stage_contracts_from_graph,
    validate_stage_contracts,
)
from .coordination_trace_adapter import CoordinationTraceAdapter
from .context_packet_resolver import build_revision_packet_from_review, resolve_context_packets
from .langgraph_checkpoint_adapter import LangGraphCheckpointStoreAdapter
from .langgraph_runtime_kernel import LangGraphRuntimeKernel
from .runtime_object_store import RuntimeObjectStore
from .models import CoordinationRun
from .runtime_assembly_builder import build_node_runtime_assembly
from .stage_execution_request import StageExecutionRequest, TaskResultReadyEvent
from .task_graph_scheduler import bootstrap_scheduler_state
from .timeline_ledger import TimelineEvent, TimelineLedgerStore
from .timeline_result_record import build_timeline_result_record


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
    artifact_refs: Annotated[list[dict[str, Any]], operator.add]
    pending_inputs: dict[str, Any]
    missing_required_inputs: list[str]
    retry_counts: dict[str, int]
    human_gate: dict[str, Any]
    terminal_status: str
    final_result_ref: str
    current_event: dict[str, Any]
    current_task_result: dict[str, Any]
    stage_execution_request: dict[str, Any]
    a2a_payload: dict[str, Any]
    working_memory_contexts: dict[str, dict[str, Any]]
    working_memory_operations: list[dict[str, Any]]
    revision_packets: list[dict[str, Any]]
    timeline_result_records: list[dict[str, Any]]
    result_record_index: dict[str, dict[str, Any]]
    latest_stage_result_records: dict[str, str]
    accepted_result_records_by_scope: dict[str, dict[str, str]]
    timeline: dict[str, Any]
    diagnostics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LangGraphCoordinationRuntimeResult:
    state: dict[str, Any] = field(default_factory=dict)
    events: tuple[Any, ...] = ()
    stage_execution_request: StageExecutionRequest | None = None
    checkpoint_ref: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def continuation_payload(self, *, session_id: str, current_turn_context: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.stage_execution_request is None:
            return {}
        request = self.stage_execution_request
        runtime_assembly = dict(request.runtime_assembly or {})
        projection_id = str(runtime_assembly.get("projection_id") or "").strip()
        inherited_context = {
            key: value
            for key, value in dict(current_turn_context or {}).items()
            if key
            not in {
                "user_message",
                "current_user_message",
                "task_id",
                "selected_task_id",
                "agent_id",
                "projection_id",
                "selected_projection_id",
                "continuation_stage_id",
                "stage_execution_request",
                "a2a_payload",
            }
        }
        turn_context = {
            **inherited_context,
            "selected_task_id": request.task_ref,
            "task_id": request.task_ref,
            "agent_id": request.agent_id,
            "projection_id": projection_id,
            "selected_projection_id": projection_id,
            "coordination_run_id": request.coordination_run_id,
            "continuation_stage_id": request.stage_id,
            "stage_execution_request": request.to_dict(),
            "a2a_payload": dict(request.a2a_payload),
            "explicit_inputs": dict(request.explicit_inputs),
        }
        return {
            "session_id": session_id,
            "coordination_run_id": request.coordination_run_id,
            "thread_id": request.thread_id,
            "current_task_run_id": request.root_task_run_id,
            "next_task_ref": request.task_ref,
            "next_stage_id": request.stage_id,
            "current_turn_context": turn_context,
            "message": request.message,
            "stage_execution_request": request.to_dict(),
            "a2a_payload": dict(request.a2a_payload),
            "task_selection": {
                "selected_task_id": request.task_ref,
                "task_id": request.task_ref,
                "agent_id": request.agent_id,
                "projection_id": projection_id,
                "selected_projection_id": projection_id,
            },
            "suppress_done": True,
        }


class LangGraphCoordinationRuntime:
    """Topology-driven coordination runtime that owns stage progression state."""

    def __init__(
        self,
        *,
        root_dir: Any,
        registry_base_dir: Any | None = None,
        state_index: Any,
        event_log: Any,
        task_flow_registry: Any,
        trace_reader: Any,
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
        self.artifact_refs = ArtifactRefIndex(state_index=state_index, trace_reader=trace_reader)
        self.input_binder = ContinuationInputBinder(self.artifact_refs)
        self.checkpoints = LangGraphCheckpointStoreAdapter(root_dir)
        self.runtime_objects = RuntimeObjectStore(root_dir)
        self.trace_adapter = CoordinationTraceAdapter(state_index=state_index, event_log=event_log)
        self.working_memory = WorkingMemoryService(_working_memory_root_for_runtime(root_dir))
        self.working_memory_finalizer = WorkingMemoryFinalizer(self.working_memory)
        self.formal_memory = FormalMemoryService(_formal_memory_root_for_runtime(root_dir))
        self.timeline_ledger = TimelineLedgerStore(root_dir)
        self._app = self._build_app()
        self.kernel = LangGraphRuntimeKernel(app=self._app, checkpoints=self.checkpoints)

    def _resolve_task_graph_view(self, coordination_run: CoordinationRun):
        task_graph = self._resolve_task_graph_definition(coordination_run)
        if task_graph is None:
            return None
        derive = getattr(self.task_flow_registry, "derive_coordination_task_view_from_graph", None)
        if not callable(derive):
            return None
        return derive(task_graph)

    def _resolve_task_graph_definition(self, coordination_run: CoordinationRun):
        diagnostics = dict(coordination_run.diagnostics or {})
        definition_ref = str(diagnostics.get("task_graph_definition_ref") or "").strip()
        snapshot = self.runtime_objects.get_object(definition_ref) if definition_ref else {}
        if snapshot:
            return task_graph_from_dict(snapshot)
        target = str(coordination_run.graph_ref or "").strip()
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
    ) -> LangGraphCoordinationRuntimeResult:
        coordination_task = self._resolve_task_graph_view(coordination_run)
        if coordination_task is None:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
        state = self._load_or_bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)
        if inherited_inputs:
            state["pending_inputs"] = {**dict(state.get("pending_inputs") or {}), **dict(inherited_inputs)}
            state["diagnostics"] = {
                **dict(state.get("diagnostics") or {}),
                "inherited_input_keys": sorted(str(key) for key in dict(inherited_inputs).keys()),
            }
        self._append_timeline_event(
            state,
            event_type="run_started",
            status="running",
            payload={"coordination_run_id": coordination_run.coordination_run_id},
            idempotency_key=f"{coordination_run.coordination_run_id}:run_started",
        )
        if not dict(state.get("stage_execution_request") or {}):
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
        return LangGraphCoordinationRuntimeResult(
            state=state,
            events=tuple(events),
            stage_execution_request=(
                StageExecutionRequest.from_dict(dict(state.get("stage_execution_request") or {}))
                if dict(state.get("stage_execution_request") or {})
                else None
            ),
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics={"supported": True, "initialized": True},
        )

    def resume_from_task_result(
        self,
        *,
        coordination_run: CoordinationRun,
        event: TaskResultReadyEvent,
        current_task_result: dict[str, Any] | None = None,
        inherited_inputs: dict[str, Any] | None = None,
        artifact_root: str = "",
    ) -> LangGraphCoordinationRuntimeResult:
        coordination_task = self._resolve_task_graph_view(coordination_run)
        if coordination_task is None:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
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
        request_payload = dict(final_state.get("stage_execution_request") or {})
        request = StageExecutionRequest.from_dict(request_payload) if request_payload else None
        return LangGraphCoordinationRuntimeResult(
            state=final_state,
            events=tuple(events),
            stage_execution_request=request,
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics=dict(final_state.get("diagnostics") or {}),
        )

    def resume_human_gate(
        self,
        *,
        coordination_run_id: str,
        resume_payload: dict[str, Any],
    ) -> LangGraphCoordinationRuntimeResult:
        coordination_run = self.state_index.get_coordination_run(coordination_run_id)
        if coordination_run is None:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_coordination_run"})
        state = self.checkpoints.get_state(thread_id=coordination_run_id)
        if not state:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_checkpoint"})
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
        request_payload = dict(final_state.get("stage_execution_request") or {})
        request = StageExecutionRequest.from_dict(request_payload) if request_payload else None
        return LangGraphCoordinationRuntimeResult(
            state=final_state,
            events=tuple(events),
            stage_execution_request=request,
            checkpoint_ref=checkpoint.checkpoint_id,
            diagnostics=dict(final_state.get("diagnostics") or {}),
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
        volume_index = _safe_int(pending_inputs.get("volume_index"), 0)
        batch_start = _safe_int(pending_inputs.get("batch_start_index") or pending_inputs.get("chapter_index"), 0)
        batch_end = _safe_int(pending_inputs.get("batch_end_index"), batch_start)
        round_index = _safe_int(
            pending_inputs.get("round_index")
            or pending_inputs.get("revision_round")
            or pending_inputs.get("attempt_index"),
            0,
        )
        if volume_index > 0:
            scope_path.append(f"volume[{volume_index:03d}]")
        if batch_start > 0:
            batch_label = f"batch[{batch_start:03d}"
            if batch_end and batch_end != batch_start:
                batch_label += f"-{batch_end:03d}"
            batch_label += "]"
            scope_path.append(batch_label)
        if round_index > 0:
            scope_path.append(f"round[{round_index:03d}]")
        retry_index = int(dict(state.get("retry_counts") or {}).get(stage_id) or 0)
        if retry_index > 0:
            scope_path.append(f"retry[{retry_index}]")
        loop_index = _safe_int(pending_inputs.get("iteration_index"), 0)
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
        request_payload = dict(state.get("stage_execution_request") or {})
        stale_result = _stale_result_reason(event=event, request_payload=request_payload, stage_id=stage_id)
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
                "stage_execution_request": dict(state.get("stage_execution_request") or {}),
                "a2a_payload": dict(state.get("a2a_payload") or {}),
                "terminal_status": "stale_result_ignored",
                "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
                "diagnostics": {**dict(state.get("diagnostics") or {}), "last_stale_result_reason": stale_result},
            }
        raw_refs = [
            str(item)
            for item in list(event.get("artifact_refs") or [])
            if str(item)
        ]
        requires_file_artifact_refs = _contract_requires_file_artifact_refs(contract)
        artifact_refs = [item for item in raw_refs if item.startswith("artifact:")] if requires_file_artifact_refs else raw_refs
        trace_refs = [item for item in raw_refs if not item.startswith("artifact:")] if requires_file_artifact_refs else []
        output_mappings = [dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)]
        mapped_outputs: dict[str, Any] = {}
        for mapping in output_mappings:
            output_key = str(mapping.get("output_key") or "").strip()
            if not output_key:
                continue
            mapped_outputs[output_key] = artifact_refs if mapping.get("single") is False else (artifact_refs[0] if artifact_refs else "")
        output_bundle = _node_result_output_bundle(
            state=state,
            event=event,
            artifact_refs=artifact_refs,
            mapped_outputs=mapped_outputs,
        )
        stage_outputs = {
            **_structured_outputs_from_output_bundle(output_bundle),
            **mapped_outputs,
        }
        accepted = bool(event.get("accepted") is True) and _required_artifact_outputs_satisfied(
            output_mappings,
            artifact_refs,
            requires_file_artifact_refs=requires_file_artifact_refs,
        )
        node_id = str(contract.get("node_id") or stage_id)
        dispatch_context = dict(request_payload.get("dispatch_context") or {})
        stage_scope = self._stage_scope(state=state, stage_id=stage_id, contract=contract)
        commit_identity = _stage_commit_identity(
            stage_id=stage_id,
            explicit_inputs=dict(request_payload.get("explicit_inputs") or state.get("pending_inputs") or {}),
            artifact_refs=artifact_refs,
        )
        committed_identities = {
            str(item)
            for item in list(dict(state.get("diagnostics") or {}).get("committed_stage_identities") or [])
            if str(item)
        }
        if accepted and commit_identity and commit_identity in committed_identities:
            duplicate_event = self._append_timeline_event(
                state,
                event_type="duplicate_stage_commit_ignored",
                status="ignored",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                request_id=str(request_payload.get("request_id") or ""),
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
                "stage_execution_request": {},
                "a2a_payload": {},
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
            request_id=str(request_payload.get("request_id") or ""),
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
        result_record = build_timeline_result_record(
            request_payload=request_payload,
            result_event=result_event_payload,
            stage_id=stage_id,
            node_id=node_id,
            accepted=accepted,
            artifact_refs=artifact_refs,
            trace_refs=trace_refs,
            memory_write_candidate_refs=created_memory_refs,
            memory_commit_refs=committed_memory_refs,
            validation_result={
                "required_artifact_outputs_satisfied": accepted or not bool(event.get("accepted") is True),
                "requires_file_artifact_refs": requires_file_artifact_refs,
            },
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
        revision_packets = [dict(item) for item in list(state.get("revision_packets") or []) if isinstance(item, dict)]
        if accepted:
            node_statuses[stage_id] = "completed"
            node_statuses = _reset_failed_direct_downstream_after_success(
                state=state,
                node_statuses=node_statuses,
                stage_id=stage_id,
            )
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
                diagnostics={"retry_count": retry_counts.get(stage_id), "reason": "acceptance_failed_retry"},
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
        diagnostics = {**dict(state.get("diagnostics") or {}), "last_accepted_stage_id": stage_id}
        if accepted and commit_identity:
            diagnostics["committed_stage_identities"] = sorted({*committed_identities, commit_identity})
        if retry_stage_id:
            diagnostics["retry_stage_id"] = retry_stage_id
            diagnostics["retry_counts"] = retry_counts
        else:
            diagnostics.pop("retry_stage_id", None)
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
        artifact_payloads = [{"stage_id": stage_id, "ref": ref, "ref_kind": "artifact"} for ref in artifact_refs]
        return {
            "stage_results": stage_results,
            "stage_results_by_instance": stage_results_by_instance,
            "node_statuses": dict(loop_updates.get("node_statuses") or node_statuses),
            "retry_counts": retry_counts,
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
            "stage_execution_request": {},
            "a2a_payload": {},
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
        diagnostics = {
            **dict(scheduler_update.get("diagnostics") or {}),
            "latest_scheduler_event_id": str(event.event_id if event is not None else ""),
        }
        return {
            **scheduler_update,
            "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
            "diagnostics": diagnostics,
        }

    def _route_next(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        if not order:
            return {"terminal_status": "blocked", "missing_required_inputs": ["stage_order"]}
        if str(state.get("terminal_status") or "") == "stale_result_ignored":
            return {
                "terminal_status": "stale_result_ignored",
                "stage_execution_request": dict(state.get("stage_execution_request") or {}),
                "a2a_payload": dict(state.get("a2a_payload") or {}),
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
                "stage_execution_request": dict(state.get("stage_execution_request") or {}),
                "a2a_payload": dict(state.get("a2a_payload") or {}),
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
        if str(state.get("terminal_status") or "") == "failed":
            update = _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="failed",
            )
            return self._record_scheduler_evaluation(state=state, scheduler_update=update, node_statuses=dict(state.get("node_statuses") or {}))
        node_statuses = dict(state.get("node_statuses") or {})
        retry_stage_id = str(dict(state.get("diagnostics") or {}).get("retry_stage_id") or "").strip()
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
            diagnostics.pop("retry_stage_id", None)
            result = {
                **next_sets,
                "active_stage_id": retry_stage_id,
                "active_node_id": str(contract.get("node_id") or retry_stage_id),
                "active_task_ref": str(contract.get("task_ref") or ""),
                "node_statuses": node_statuses,
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
        binding = self.input_binder.bind(
            stage_contract=contract,
            current_task_result=current_task_result,
            current_task_ref=current_task_ref,
            stage_outputs=stage_outputs,
            inherited_inputs=dict(state.get("pending_inputs") or {}),
            artifact_root=str(dict(state.get("pending_inputs") or {}).get("artifact_root") or ""),
        )
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
                "pending_inputs": dict(binding.explicit_inputs),
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
        return {
            "pending_inputs": dict(binding.explicit_inputs),
            "missing_required_inputs": [],
            "diagnostics": {**dict(state.get("diagnostics") or {}), "binding": dict(binding.diagnostics)},
        }

    def _stage_execute(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        stage_id = str(state.get("active_stage_id") or "").strip()
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        explicit_inputs = dict(state.get("pending_inputs") or {})
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
            idempotency_key="",
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
        if runtime_assembly_payload:
            metadata = dict(runtime_assembly_payload.get("metadata") or {})
            metadata["dispatch_context"] = dict(dispatch_context)
            metadata["context_packet_summary"] = dict(context_packets.get("context_packet_summary") or {})
            runtime_assembly_payload["metadata"] = metadata
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
                event_type="stage_execution_request_created",
                status="creating",
                scope_type=str(stage_scope.get("scope_type") or "stage"),
                scope_path=list(stage_scope.get("scope_path") or ["run"]),
                node_id=node_id,
                phase_id=str(stage_scope.get("phase_id") or ""),
                payload={
                    "stage_id": stage_id,
                    "node_id": node_id,
                    "dispatch_event_id": dispatch_event.event_id,
                    "artifact_packet_id": str(artifact_context_packet.get("packet_id") or ""),
                    "memory_snapshot_id": str(memory_snapshot.get("snapshot_id") or ""),
                    "revision_packet_id": str(revision_packet.get("revision_packet_id") or ""),
                },
                causal_event_ids=[dispatch_event.event_id],
                idempotency_key="",
            )
        a2a_payload = build_stage_execution_a2a_payload(
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
            explicit_inputs=explicit_inputs,
            payload_contracts=payload_contracts,
            handoff_packets=handoff_packets,
            dispatch_context=dispatch_context,
            memory_snapshot=memory_snapshot,
            artifact_context_packet=artifact_context_packet,
            revision_packet=revision_packet,
            runtime_assembly_ref=str(runtime_assembly_payload.get("assembly_id") or ""),
            contract_manifest_ref=str((state.get("contract_manifest") or {}).get("manifest_id") or ""),
            ack_policy=str(a2a_runtime.get("ack_policy") or "explicit_ack"),
            handoff_policy=str(a2a_runtime.get("handoff_policy") or ""),
        )
        request = StageExecutionRequest(
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
            explicit_inputs=dict(explicit_inputs),
            runtime_assembly=runtime_assembly_payload,
            a2a_payload=a2a_payload,
            message=_stage_execution_message(
                stage_id=stage_id,
                task_ref=str(contract.get("task_ref") or state.get("active_task_ref") or ""),
                contract=contract,
                explicit_inputs=explicit_inputs,
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
        next_handoff_packets = list(state.get("handoff_packets") or [])
        next_handoff_packets.extend(handoff_packets)
        return {
            "stage_execution_request": request.to_dict(),
            "a2a_payload": a2a_payload,
            "handoff_packets": next_handoff_packets,
            "working_memory_contexts": working_memory_contexts,
            "working_memory_operations": working_memory_operations,
            "timeline": self.timeline_ledger.snapshot(str(state.get("coordination_run_id") or ""), limit=80),
            "terminal_status": "",
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
        dynamic_policy = dict(contract.get("dynamic_memory_read_policy") or {})
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
        legacy_working_memory_read_enabled = bool(read_policy) or bool(graph_policy.get("auto_read_enabled"))
        if not legacy_working_memory_read_enabled and not repository_read_edges:
            return {}
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or dict(state.get("diagnostics") or {}).get("graph_ref") or "")
        self.formal_memory.sync_graph_spec(graph_id=graph_id, graph_spec=graph_spec)
        coordination_run_id = str(state.get("coordination_run_id") or "").strip()
        predicted_clock_seq = int(self.timeline_ledger.load(coordination_run_id).current_clock_seq or 0) + 1 if coordination_run_id else 0
        formal_selection: dict[str, Any] = {}
        formal_selection_error = ""
        if repository_read_edges:
            try:
                formal_selection = self.formal_memory.select_for_node(
                    read_edges=repository_read_edges,
                    node_run_id=f"{root_task_run_id}:{stage_id}",
                    clock=f"clock:{predicted_clock_seq}" if predicted_clock_seq else "",
                    clock_seq=predicted_clock_seq,
                    limit=int(read_policy.get("max_items") or graph_policy.get("max_items") or 50),
                )
            except Exception as exc:  # pragma: no cover - defensive runtime diagnostics
                formal_selection_error = str(exc)
        request = {
            **dict(graph_policy.get("default_read_request") or {}),
            **dict(read_policy.get("read_request") or {}),
        }
        if read_policy.get("max_items") and "max_items" not in request:
            request["max_items"] = read_policy.get("max_items")
        node_run_id = f"{root_task_run_id}:{stage_id}"
        if legacy_working_memory_read_enabled:
            selection = self.working_memory.select_for_node(
                task_run_id=root_task_run_id,
                graph_id=graph_id,
                owner_node_id=node_id,
                node_run_id=node_run_id,
                run_attempt_id=str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
                reader_agent_id=str(contract.get("agent_id") or ""),
                node_role=str(contract.get("role") or ""),
                memory_read_policy=read_policy,
                dynamic_read_policy=dynamic_policy,
                request=request,
                token_budget=int(read_policy.get("token_budget") or graph_policy.get("token_budget") or 0),
            )
            context = _working_memory_context_from_selection(
                selection,
                task_run_id=root_task_run_id,
                graph_id=graph_id,
                owner_node_id=node_id,
                node_run_id=node_run_id,
                run_attempt_id=str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
                read_policy=read_policy,
            )
        else:
            context = _formal_memory_only_context(
                task_run_id=root_task_run_id,
                graph_id=graph_id,
                owner_node_id=node_id,
                node_run_id=node_run_id,
                run_attempt_id=str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
            )
        if repository_read_edges:
            diagnostics = dict(context.get("diagnostics") or {})
            diagnostics["formal_memory_primary"] = True
            diagnostics["working_memory_legacy_read_enabled"] = legacy_working_memory_read_enabled
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
        self.formal_memory.sync_graph_spec(graph_id=graph_id, graph_spec=graph_spec)
        memory_write_edge_by_id = {
            str(edge.get("edge_id") or ""): dict(edge)
            for edge in memory_write_edges
            if str(edge.get("edge_id") or "")
        }
        if not candidates and artifact_refs and bool(write_policy.get("capture_artifact_refs")):
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
            output_bundle=dict(output_bundle or {}),
        )
        created = []
        formal_memory_receipts: list[dict[str, Any]] = []
        node_run_id = f"{root_task_run_id}:{stage_id}"
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
                    "receipt_policy": dict(formal.get("receipt_policy") or {}),
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
                    )
                    formal_update = {
                        **formal,
                        "record_id": version.record_id,
                        "record_key": version.record_key,
                        "version_id": version.version_id,
                        "version": version.version,
                        "transaction_id": transaction.transaction_id,
                        "receipt": dict(transaction.receipt),
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
                            "commit_receipt": dict(commit_transaction.receipt),
                        }
                        formal_memory_receipts.append(dict(commit_transaction.receipt))
                    else:
                        formal_memory_receipts.append(dict(transaction.receipt))
                    item = self.working_memory.update_lifecycle(
                        item.work_memory_id,
                        metadata={"formal_memory": formal_update},
                        actor_id="langgraph_coordination_runtime",
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
            "formal_memory_receipts": formal_memory_receipts,
            "formal_memory_errors": formal_memory_errors,
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

    def _commit_stage_working_memory_decisions(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        contract: dict[str, Any],
        event: dict[str, Any],
        output_bundle: dict[str, Any] | None = None,
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
        accepted_refs = _decision_refs(decision_payload, "accepted_working_memory_refs", "accept_refs", "accepted_refs")
        discarded_refs = _decision_refs(decision_payload, "discarded_working_memory_refs", "discard_refs", "discarded_refs")
        conflict_refs = _decision_refs(decision_payload, "conflict_working_memory_refs", "conflict_refs")
        actor_id = str(contract.get("agent_id") or "langgraph_coordination_runtime")
        node_id = str(contract.get("node_id") or stage_id)
        graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
        graph_id = str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or dict(state.get("diagnostics") or {}).get("graph_ref") or "")
        self.formal_memory.sync_graph_spec(graph_id=graph_id, graph_spec=graph_spec)
        commit_edges = _graph_memory_edge_descriptors(
            state=state,
            stage_id=stage_id,
            node_id=node_id,
            operation="write",
        )
        commit_edges = [edge for edge in commit_edges if str(edge.get("edge_type") or "") == "memory_commit" or str(edge.get("memory_edge_type") or "") == "commit"]
        resolved_output_bundle = dict(output_bundle or _node_result_output_bundle(state=state, event=event, artifact_refs=[], mapped_outputs={}))
        edge_commit_requests, edge_commit_errors = _formal_memory_commit_requests(
            commit_edges=commit_edges,
            output_bundle=resolved_output_bundle,
        )
        refs_from_commit_edges = [request["candidate_ref"] for request in edge_commit_requests if request.get("candidate_ref")]
        for ref in refs_from_commit_edges:
            if ref not in accepted_refs:
                accepted_refs.append(ref)
        if not decision_payload and is_commit_stage and not accepted_refs:
            accepted_refs = _stage_working_memory_refs_for_commit(state)
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
        formal_memory_receipts: list[dict[str, Any]] = []
        formal_memory_errors: list[dict[str, Any]] = list(edge_commit_errors)
        for ref in accepted_refs:
            current = self.working_memory.get_item(ref)
            formal = dict(dict(getattr(current, "metadata", {}) or {}).get("formal_memory") or {}) if current is not None else {}
            metadata: dict[str, Any] = {"stage_id": stage_id, "operation": "memory_commit"}
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
                        "commit_receipt": dict(transaction.receipt),
                    }
                    formal_memory_receipts.append(dict(transaction.receipt))
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
            "formal_memory_receipts": formal_memory_receipts,
            "formal_memory_errors": formal_memory_errors,
            "status": "completed",
            "authority": "orchestration.working_memory_resource_node",
        }

    @staticmethod
    def _blocked(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {"terminal_status": str(state.get("terminal_status") or "blocked"), "stage_execution_request": {}, "a2a_payload": {}}

    @staticmethod
    def _noop(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {
            "terminal_status": str(state.get("terminal_status") or ""),
            "stage_execution_request": dict(state.get("stage_execution_request") or {}),
            "a2a_payload": dict(state.get("a2a_payload") or {}),
        }

    def _complete(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        task_run_id = str(state.get("root_task_run_id") or "").strip()
        operations = list(state.get("working_memory_operations") or [])
        if task_run_id and not any(str(item.get("operation") or "") == "memory_finalize" for item in operations if isinstance(item, dict)):
            result = self.working_memory_finalizer.finalize_task_run(
                task_run_id,
                actor_id="langgraph_coordination_runtime",
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
        return {"terminal_status": "completed", "stage_execution_request": {}, "a2a_payload": {}, "working_memory_operations": operations}

    @staticmethod
    def _route_after_next(state: CoordinationRuntimeState) -> str:
        terminal = str(state.get("terminal_status") or "")
        if terminal in {"stale_result_ignored", "duplicate_commit_ignored"}:
            return "noop"
        if terminal == "blocked":
            return "blocked"
        if terminal == "waiting_for_human":
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
        return "stage_execute"

    def _load_or_bootstrap_state(self, *, coordination_run: CoordinationRun, coordination_task: Any) -> dict[str, Any]:
        stored = self.checkpoints.get_state(thread_id=coordination_run.coordination_run_id)
        if stored:
            return stored
        return self._bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)

    def _bootstrap_state(self, *, coordination_run: CoordinationRun, coordination_task: Any) -> dict[str, Any]:
        topology_template = self.task_flow_registry.get_topology_template(coordination_run.topology_template_id)
        communication_protocol = self.task_flow_registry.get_task_communication_protocol(coordination_run.communication_protocol_id)
        specific_tasks = tuple(self.task_flow_registry.list_specific_task_records())
        task_graph = self._resolve_task_graph_definition(coordination_run)
        if task_graph is None:
            return {
                "coordination_run_id": coordination_run.coordination_run_id,
                "root_task_run_id": coordination_run.task_run_id,
                "terminal_status": "blocked",
                "stage_execution_request": {},
                "a2a_payload": {},
                "diagnostics": {
                    "coordination_engine": "langgraph_runtime",
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
        graph_spec_payload = self.runtime_objects.get_object(runtime_spec_ref) if runtime_spec_ref else {}
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
            "acceptance_results": {},
            "node_statuses": node_statuses,
            "stage_results": {},
            "stage_results_by_instance": {},
            "artifact_refs": [],
            "working_memory_contexts": {},
            "working_memory_operations": [],
            "revision_packets": [],
            "timeline_result_records": [],
            "result_record_index": {},
            "latest_stage_result_records": {},
            "accepted_result_records_by_scope": {},
            "timeline": self.timeline_ledger.snapshot(coordination_run.coordination_run_id, limit=80),
            "pending_inputs": dict(loop_state),
            "missing_required_inputs": [],
            "retry_counts": {},
            "human_gate": {},
            "terminal_status": "blocked" if issues else "",
            "final_result_ref": "",
            "current_event": {},
            "stage_execution_request": {},
            "a2a_payload": {},
            "diagnostics": {
                "coordination_engine": "langgraph_runtime",
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
    payload["projection_id"] = str(node.get("projection_id") or payload.get("projection_id") or "")
    for key in (
        "artifact_targets",
        "artifact_requirements",
        "artifact_policy",
        "artifact_target",
        "output_path",
        "instructions",
        "stage_instructions",
        "node_type",
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def _graph_id_from_state(state: dict[str, Any]) -> str:
    diagnostics = dict(state.get("diagnostics") or {})
    graph_spec = dict(diagnostics.get("coordination_graph_spec") or {})
    return str(graph_spec.get("graph_ref") or graph_spec.get("graph_id") or diagnostics.get("graph_ref") or "")


def _runtime_node_value(state: dict[str, Any], node_id: str, key: str) -> Any:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    for item in list(graph_spec.get("nodes") or []):
        node = dict(item or {})
        if str(node.get("node_id") or "") == str(node_id or ""):
            return node.get(key)
    return None


def _working_memory_root_for_runtime(root_dir: Any) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "working_memory"
    return runtime_root / "working_memory"


def _formal_memory_root_for_runtime(root_dir: Any) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "formal_memory"
    return runtime_root / "formal_memory"


def _first_policy_value(policy: dict[str, Any], key: str, default: str) -> str:
    values = [str(item).strip() for item in list(policy.get(key) or []) if str(item).strip()]
    return values[0] if values else str(default or "").strip()


def _formal_memory_only_context(
    *,
    task_run_id: str,
    graph_id: str,
    owner_node_id: str,
    node_run_id: str,
    run_attempt_id: str,
) -> dict[str, Any]:
    return {
        "task_run_id": task_run_id,
        "graph_id": graph_id,
        "owner_node_id": owner_node_id,
        "node_run_id": node_run_id,
        "run_attempt_id": run_attempt_id,
        "read_log_id": "",
        "denied_reason": "",
        "required_refs": [],
        "preferred_refs": [],
        "required_items": [],
        "preferred_items": [],
        "missing_required_records": [],
        "working_memory.required": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "working_memory.preferred": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "working_memory.artifact_refs": {"item_count": 0, "refs": [], "content_mode": "refs_only"},
        "working_memory.conflict_warnings": {"item_count": 0, "refs": [], "items": [], "content_mode": "summary"},
        "diagnostics": {
            "formal_memory_primary": True,
            "working_memory_legacy_read_enabled": False,
        },
    }


def _working_memory_context_from_selection(
    selection: dict[str, Any],
    *,
    task_run_id: str,
    graph_id: str,
    owner_node_id: str,
    node_run_id: str,
    run_attempt_id: str,
    read_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = dict(read_policy or {})
    required_items = [item for item in list(selection.get("required_items") or []) if hasattr(item, "to_dict")]
    preferred_items = [item for item in list(selection.get("preferred_items") or []) if hasattr(item, "to_dict")]
    excluded_items = [item for item in list(selection.get("excluded_items") or []) if hasattr(item, "to_dict")]
    selection_diagnostics = dict(selection.get("diagnostics") or {})
    required_refs = [str(getattr(item, "work_memory_id", "") or "") for item in required_items if str(getattr(item, "work_memory_id", "") or "")]
    preferred_refs = [str(getattr(item, "work_memory_id", "") or "") for item in preferred_items if str(getattr(item, "work_memory_id", "") or "")]
    conflict_items = [
        item
        for item in [*required_items, *preferred_items]
        if str(getattr(item, "status", "") or "") == "conflicted" or getattr(item, "conflict_refs", ())
    ]
    conflict_refs = [str(getattr(item, "work_memory_id", "") or "") for item in conflict_items if str(getattr(item, "work_memory_id", "") or "")]
    return {
        "task_run_id": task_run_id,
        "graph_id": graph_id,
        "owner_node_id": owner_node_id,
        "node_run_id": node_run_id,
        "run_attempt_id": run_attempt_id,
        "read_log_id": str(selection.get("read_log_id") or ""),
        "denied_reason": str(selection.get("denied_reason") or ""),
        "required_refs": required_refs,
        "preferred_refs": preferred_refs,
        "required_items": [item.to_dict() for item in required_items],
        "preferred_items": [item.to_dict() for item in preferred_items],
        "missing_required_records": list(selection_diagnostics.get("missing_repository_read_edges") or []),
        "working_memory.required": {
            "item_count": len(required_refs),
            "refs": required_refs,
            "items": [item.to_dict() for item in required_items],
            "content_mode": "summary",
        },
        "working_memory.preferred": {
            "item_count": len(preferred_refs),
            "refs": preferred_refs,
            "items": [item.to_dict() for item in preferred_items],
            "content_mode": "summary",
        },
        "working_memory.artifact_refs": {
            "item_count": sum(len(tuple(getattr(item, "artifact_refs", ()) or ())) for item in [*required_items, *preferred_items]),
            "refs": [
                ref
                for item in [*required_items, *preferred_items]
                for ref in list(getattr(item, "artifact_refs", ()) or ())
                if str(ref)
            ],
            "content_mode": "refs_only",
        },
        "working_memory.conflict_warnings": {
            "item_count": len(conflict_refs),
            "refs": conflict_refs,
            "items": [item.to_dict() for item in conflict_items],
            "content_mode": "summary",
        },
        "diagnostics": {
            **selection_diagnostics,
            "requested_topics": [
                str(item).strip()
                for item in list(policy.get("topics") or [])
                if str(item).strip()
            ],
            "required_topics": [
                str(item).strip()
                for item in list(policy.get("required_topics") or [])
                if str(item).strip()
            ],
            "forbidden_topics": [
                str(item).strip()
                for item in list(policy.get("forbidden_topics") or [])
                if str(item).strip()
            ],
            "excluded_refs": [
                str(getattr(item, "work_memory_id", "") or "")
                for item in excluded_items
                if str(getattr(item, "work_memory_id", "") or "")
            ],
        },
    }


def _working_memory_read_operation_from_context(
    *,
    context: dict[str, Any],
    stage_id: str,
    node_id: str,
    agent_id: str,
) -> dict[str, Any]:
    payload = dict(context or {})
    diagnostics = dict(payload.get("diagnostics") or {})
    required = dict(payload.get("working_memory.required") or {})
    preferred = dict(payload.get("working_memory.preferred") or {})
    formal_records = [dict(item) for item in list(payload.get("formal_memory.required_records") or []) if isinstance(item, dict)]
    formal_read_log_ids = [str(item).strip() for item in list(payload.get("formal_memory.read_log_ids") or []) if str(item).strip()]
    selected_refs = [
        *[str(item).strip() for item in list(required.get("refs") or []) if str(item).strip()],
        *[
            str(item).strip()
            for item in list(preferred.get("refs") or [])
            if str(item).strip() and str(item).strip() not in list(required.get("refs") or [])
        ],
    ]
    selected_formal_refs = [
        str(item.get("version_id") or item.get("record_id") or "").strip()
        for item in formal_records
        if str(item.get("version_id") or item.get("record_id") or "").strip()
    ]
    denied_reason = str(payload.get("denied_reason") or "")
    if not selected_refs and not selected_formal_refs and not denied_reason and not str(payload.get("read_log_id") or "") and not formal_read_log_ids:
        return {}
    return {
        "operation": "memory_read",
        "stage_id": stage_id,
        "node_id": node_id,
        "reader_agent_id": agent_id,
        "node_run_id": str(payload.get("node_run_id") or ""),
        "read_log_id": str(payload.get("read_log_id") or ""),
        "formal_memory_read_log_ids": formal_read_log_ids,
        "selected_working_memory_refs": selected_refs,
        "selected_formal_memory_refs": selected_formal_refs,
        "excluded_working_memory_refs": [
            str(item).strip()
            for item in list(diagnostics.get("excluded_refs") or [])
            if str(item).strip()
        ],
        "selected_formal_memory_records": formal_records[:12],
        "selected_item_previews": [
            dict(item)
            for item in list(diagnostics.get("selected_item_previews") or [])
            if isinstance(item, dict)
        ],
        "denied_reason": denied_reason,
        "status": "denied" if denied_reason else "completed",
        "authority": "orchestration.working_memory_resource_node",
    }


def _working_memory_refs_from_context(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for section_id in ("working_memory.required", "working_memory.preferred", "working_memory.conflict_warnings"):
        for ref in list(dict(context.get(section_id) or {}).get("refs") or []):
            if str(ref).strip() and str(ref).strip() not in refs:
                refs.append(str(ref).strip())
    return refs


def _timeline_working_memory_operation(
    operation: dict[str, Any],
    *,
    existing_operations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    payload = dict(operation or {})
    sequence_index = len([item for item in list(existing_operations or []) if isinstance(item, dict)]) + 1
    payload.setdefault("created_at", time.time())
    payload.setdefault("sequence_index", sequence_index)
    payload.setdefault("timeline_kind", "working_memory_operation")
    return payload


def _graph_memory_edge_descriptors(
    *,
    state: dict[str, Any],
    stage_id: str,
    node_id: str,
    operation: str,
) -> list[dict[str, Any]]:
    graph_spec = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    nodes_by_id = {
        str(item.get("node_id") or item.get("id") or "").strip(): dict(item)
        for item in list(graph_spec.get("nodes") or [])
        if isinstance(item, dict) and str(item.get("node_id") or item.get("id") or "").strip()
    }
    descriptors: list[dict[str, Any]] = []
    for raw in list(graph_spec.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        edge = dict(raw)
        edge_type = str(edge.get("edge_type") or edge.get("mode") or "").strip()
        metadata = dict(edge.get("metadata") or {})
        memory_edge_type = str(metadata.get("memory_edge_type") or "").strip()
        normalized_memory_edge_type = memory_edge_type or (edge_type.replace("memory_", "") if edge_type.startswith("memory_") else "")
        source = str(edge.get("source_node_id") or edge.get("from") or edge.get("source") or "").strip()
        target = str(edge.get("target_node_id") or edge.get("to") or edge.get("target") or "").strip()
        if operation == "read":
            if normalized_memory_edge_type != "read" or target not in {stage_id, node_id}:
                continue
        elif operation == "write":
            if normalized_memory_edge_type not in {"write", "write_candidate", "commit"} or source not in {stage_id, node_id}:
                continue
        else:
            continue
        selector = dict(metadata.get("selector") or {})
        record_key = str(metadata.get("record_key") or selector.get("record_key") or "").strip()
        record_kind = str(metadata.get("record_kind") or selector.get("record_kind") or "").strip()
        record_keys = [
            str(item).strip()
            for item in list(metadata.get("record_keys") or selector.get("record_keys") or [])
            if str(item).strip()
        ]
        record_kinds = [
            str(item).strip()
            for item in list(metadata.get("record_kinds") or selector.get("record_kinds") or [])
            if str(item).strip()
        ]
        if record_key and record_key not in record_keys:
            record_keys.insert(0, record_key)
        if record_kind and record_kind not in record_kinds:
            record_kinds.insert(0, record_kind)
        repository_node_id = str(metadata.get("repository_node_id") or "").strip()
        if not repository_node_id:
            if operation == "read" and _is_runtime_memory_repository_node(nodes_by_id.get(source, {})):
                repository_node_id = source
            elif operation == "write" and _is_runtime_memory_repository_node(nodes_by_id.get(target, {})):
                repository_node_id = target
        repository = str(
            metadata.get("repository")
            or metadata.get("repository_id")
            or _repository_id_from_runtime_node(nodes_by_id.get(repository_node_id, {}))
            or repository_node_id
            or ""
        ).strip()
        descriptors.append(
            {
                "edge_id": str(edge.get("edge_id") or "").strip(),
                "edge_type": edge_type,
                "memory_edge_type": normalized_memory_edge_type,
                "source_node_id": source,
                "target_node_id": target,
                "repository": repository,
                "repository_node_id": repository_node_id or repository,
                "collection": str(metadata.get("collection") or selector.get("collection") or "").strip(),
                "record_key": record_key,
                "record_kind": record_kind,
                "record_keys": record_keys,
                "record_kinds": record_kinds,
                "selector": selector,
                "version_selector": metadata.get("version_selector") or selector.get("version_selector") or "",
                "on_missing": str(metadata.get("on_missing") or "").strip(),
                "source_output_key": str(metadata.get("source_output_key") or selector.get("source_output_key") or "").strip(),
                "candidate_ref_key": str(metadata.get("candidate_ref_key") or "").strip(),
                "verdict_key": str(metadata.get("verdict_key") or "").strip(),
                "required_verdict": str(metadata.get("required_verdict") or "").strip(),
                "model_visible_label": str(metadata.get("model_visible_label") or metadata.get("visible_label") or "").strip(),
                "usage_instruction": str(metadata.get("usage_instruction") or metadata.get("instructions") or "").strip(),
                "receipt_policy": dict(metadata.get("receipt_policy") or edge.get("receipt_policy") or {}),
            }
        )
    return descriptors


def _matching_commit_edge(*, formal: dict[str, Any], commit_edges: list[dict[str, Any]]) -> dict[str, Any]:
    repository = str(formal.get("repository_id") or formal.get("repository") or "").strip()
    collection = str(formal.get("collection_id") or formal.get("collection") or "").strip()
    record_key = str(formal.get("record_key") or "").strip()
    record_kind = str(formal.get("record_kind") or "").strip()
    for edge in commit_edges:
        selector = dict(edge.get("selector") or {})
        if repository and repository != str(edge.get("repository") or "").strip():
            continue
        if collection and collection != str(edge.get("collection") or "").strip():
            continue
        edge_record_key = str(edge.get("record_key") or selector.get("record_key") or "").strip()
        if record_key and edge_record_key and record_key != edge_record_key:
            continue
        edge_record_kind = str(edge.get("record_kind") or selector.get("record_kind") or "").strip()
        edge_record_kinds = {str(item).strip() for item in list(edge.get("record_kinds") or []) if str(item).strip()}
        if record_kind and edge_record_kind and record_kind != edge_record_kind:
            continue
        if record_kind and edge_record_kinds and record_kind not in edge_record_kinds:
            continue
        return dict(edge)
    return dict(commit_edges[0]) if commit_edges else {}


def _formal_memory_commit_requests(
    *,
    commit_edges: list[dict[str, Any]],
    output_bundle: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for edge in commit_edges:
        candidate_ref_key = str(edge.get("candidate_ref_key") or "").strip()
        verdict_key = str(edge.get("verdict_key") or "").strip()
        required_verdict = str(edge.get("required_verdict") or "").strip()
        verdict = ""
        if verdict_key:
            verdict_extraction = _extract_source_output_value(verdict_key, candidates=[], output_bundle=output_bundle)
            if verdict_extraction.get("found"):
                verdict = _scalar_text(verdict_extraction.get("value"))
            elif required_verdict:
                errors.append(
                    {
                        "edge_id": str(edge.get("edge_id") or ""),
                        "verdict_key": verdict_key,
                        "required_verdict": required_verdict,
                        "error": "verdict_key_not_found",
                    }
                )
                continue
        if required_verdict and verdict and verdict != required_verdict:
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "verdict_key": verdict_key,
                    "verdict": verdict,
                    "required_verdict": required_verdict,
                    "error": "required_verdict_not_satisfied",
                }
            )
            continue
        if not candidate_ref_key:
            continue
        ref_extraction = _extract_source_output_value(candidate_ref_key, candidates=[], output_bundle=output_bundle)
        if not ref_extraction.get("found"):
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "candidate_ref_key": candidate_ref_key,
                    "error": "candidate_ref_key_not_found",
                }
            )
            continue
        refs = _refs_from_output_value(ref_extraction.get("value"))
        if not refs:
            errors.append(
                {
                    "edge_id": str(edge.get("edge_id") or ""),
                    "candidate_ref_key": candidate_ref_key,
                    "error": "candidate_ref_empty",
                }
            )
            continue
        for ref in refs:
            requests.append(
                {
                    "candidate_ref": ref,
                    "candidate_version_id": ref,
                    "edge": dict(edge),
                    "verdict": verdict,
                    "required_verdict": required_verdict,
                }
            )
    return requests, errors


def _formal_memory_write_records(
    *,
    candidates: list[dict[str, Any]],
    memory_write_edges: list[dict[str, Any]],
    fallback_write_policy: dict[str, Any],
    output_bundle: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not memory_write_edges:
        return [dict(item) for item in candidates], []
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    fallback_scope = _first_policy_value(fallback_write_policy, "writable_scopes", "node_scope")
    for edge in memory_write_edges:
        record_keys = [str(item).strip() for item in list(edge.get("record_keys") or []) if str(item).strip()]
        record_kinds = [str(item).strip() for item in list(edge.get("record_kinds") or []) if str(item).strip()]
        edge_operation = str(edge.get("memory_edge_type") or "").strip()
        commit_state = "committed" if edge_operation == "commit" else "candidate"
        default_status = "accepted" if commit_state == "committed" else "draft"
        source_output_key = str(edge.get("source_output_key") or "").strip()
        edge_candidates = candidates
        if source_output_key:
            extraction = _extract_source_output_value(
                source_output_key,
                candidates=candidates,
                output_bundle=output_bundle,
            )
            if not extraction.get("found"):
                errors.append(
                    {
                        "edge_id": str(edge.get("edge_id") or ""),
                        "repository_id": str(edge.get("repository") or ""),
                        "collection_id": str(edge.get("collection") or ""),
                        "source_output_key": source_output_key,
                        "error": "source_output_key_not_found",
                        "message": f"memory_write_candidate edge requires source_output_key '{source_output_key}', but the node result did not provide it.",
                    }
                )
                continue
            edge_candidates = [
                _candidate_from_source_output(
                    source_output_key=source_output_key,
                    value=extraction.get("value"),
                    source=str(extraction.get("source") or ""),
                    fallback_candidate=candidates[0] if candidates else {},
                )
            ]
        for index, raw_candidate in enumerate(edge_candidates):
            candidate = dict(raw_candidate)
            candidate_kind = str(candidate.get("kind") or "").strip()
            kind = candidate_kind if (candidate_kind and (not record_kinds or candidate_kind in record_kinds)) else (record_kinds[0] if record_kinds else candidate_kind)
            if not kind:
                kind = _first_policy_value(fallback_write_policy, "writable_kinds", "intermediate_result")
            record_key = str(candidate.get("record_key") or edge.get("record_key") or (record_keys[0] if record_keys else kind)).strip()
            metadata = dict(candidate.get("metadata") or {})
            formal_memory = {
                "repository_id": str(edge.get("repository") or ""),
                "repository_node_id": str(edge.get("repository_node_id") or edge.get("repository") or ""),
                "collection_id": str(edge.get("collection") or ""),
                "record_key": record_key,
                "record_kind": kind,
                "record_kinds": record_kinds,
                "record_keys": record_keys,
                "source_output_key": source_output_key,
                "source_edge_id": str(edge.get("edge_id") or ""),
                "source_edge_type": str(edge.get("edge_type") or ""),
                "memory_edge_type": edge_operation,
                "commit_state": commit_state,
                "selector": dict(edge.get("selector") or {}),
                "version_selector": str(edge.get("version_selector") or ""),
                "receipt_policy": dict(edge.get("receipt_policy") or {}),
            }
            records.append(
                {
                    **candidate,
                    "kind": kind,
                    "scope": str(candidate.get("scope") or fallback_scope),
                    "status": str(candidate.get("status") or default_status),
                    "visibility": str(candidate.get("visibility") or "shared_in_graph"),
                    "idempotency_key": str(candidate.get("idempotency_key") or f"{edge.get('edge_id')}:{index}:{kind}"),
                    "metadata": {
                        **metadata,
                        "formal_memory": formal_memory,
                    },
                }
            )
    return records, errors


def _node_result_output_bundle(
    *,
    state: dict[str, Any],
    event: dict[str, Any],
    artifact_refs: list[str],
    mapped_outputs: dict[str, Any],
) -> dict[str, Any]:
    current_task_result = dict(state.get("current_task_result") or {})
    diagnostics = dict(event.get("diagnostics") or {})
    final_outputs = _first_dict(
        current_task_result.get("final_outputs"),
        diagnostics.get("task_result_outputs"),
        diagnostics.get("final_outputs"),
    )
    outputs = _first_dict(
        current_task_result.get("outputs"),
        diagnostics.get("outputs"),
        diagnostics.get("structured_outputs"),
    )
    task_result_diagnostics = _first_dict(current_task_result.get("diagnostics"))
    artifact_materialization = _first_dict(
        final_outputs.get("artifact_materialization"),
        task_result_diagnostics.get("artifact_materialization"),
        diagnostics.get("artifact_materialization"),
    )
    output_refs = collect_task_result_output_refs(current_task_result) or [
        str(item).strip()
        for item in list(event.get("artifact_refs") or artifact_refs or [])
        if str(item).strip()
    ]
    return {
        "mapped_outputs": dict(mapped_outputs or {}),
        "final_outputs": final_outputs,
        "outputs": outputs,
        "diagnostics": diagnostics,
        "task_result_diagnostics": task_result_diagnostics,
        "task_result": current_task_result,
        "artifact_materialization": artifact_materialization,
        "artifact_refs": list(artifact_refs or []),
        "output_refs": output_refs,
        "result_refs": [str(event.get("task_result_ref") or "")] if str(event.get("task_result_ref") or "") else [],
    }


def _structured_outputs_from_output_bundle(output_bundle: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for section in (
        "outputs",
        "final_outputs",
        "mapped_outputs",
    ):
        for key, value in dict(output_bundle.get(section) or {}).items():
            if str(key).strip():
                outputs[str(key).strip()] = value
    artifact_refs = [str(item).strip() for item in list(output_bundle.get("artifact_refs") or []) if str(item).strip()]
    output_refs = [str(item).strip() for item in list(output_bundle.get("output_refs") or []) if str(item).strip()]
    if artifact_refs:
        outputs.setdefault("artifact_refs", artifact_refs)
    if output_refs:
        outputs.setdefault("output_refs", output_refs)
    return outputs


def _extract_source_output_value(
    key: str,
    *,
    candidates: list[dict[str, Any]],
    output_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_key = str(key or "").strip()
    if not source_key:
        return {"found": False}
    bundle = dict(output_bundle or {})
    direct_sources = [
        ("mapped_outputs", dict(bundle.get("mapped_outputs") or {})),
        ("final_outputs", dict(bundle.get("final_outputs") or {})),
        ("outputs", dict(bundle.get("outputs") or {})),
        ("diagnostics", dict(bundle.get("diagnostics") or {})),
        ("task_result_diagnostics", dict(bundle.get("task_result_diagnostics") or {})),
        ("artifact_materialization", dict(bundle.get("artifact_materialization") or {})),
    ]
    task_result = dict(bundle.get("task_result") or {})
    direct_sources.extend(
        [
            ("task_result.final_outputs", dict(task_result.get("final_outputs") or {})),
            ("task_result.outputs", dict(task_result.get("outputs") or {})),
            ("task_result", task_result),
        ]
    )
    for source_name, payload in direct_sources:
        if source_key in payload:
            return {"found": True, "value": payload.get(source_key), "source": source_name}
        nested = _lookup_path(payload, source_key)
        if nested.get("found"):
            return {"found": True, "value": nested.get("value"), "source": f"{source_name}.{source_key}"}
    if source_key in {"artifact_refs", "output_refs", "result_refs"}:
        values = [str(item).strip() for item in list(bundle.get(source_key) or []) if str(item).strip()]
        if values:
            return {"found": True, "value": values, "source": source_key}
    for index, candidate in enumerate(candidates):
        payload = dict(candidate.get("payload") or {}) if isinstance(candidate, dict) else {}
        if source_key in candidate:
            return {"found": True, "value": candidate.get(source_key), "source": f"working_memory_candidates[{index}]"}
        if str(candidate.get("output_key") or "").strip() == source_key:
            return {"found": True, "value": candidate, "source": f"working_memory_candidates[{index}]"}
        if source_key in payload:
            return {"found": True, "value": payload.get(source_key), "source": f"working_memory_candidates[{index}].payload"}
        nested = _lookup_path(payload, source_key)
        if nested.get("found"):
            return {"found": True, "value": nested.get("value"), "source": f"working_memory_candidates[{index}].payload.{source_key}"}
    return {"found": False}


def _candidate_from_source_output(
    *,
    source_output_key: str,
    value: Any,
    source: str,
    fallback_candidate: dict[str, Any],
) -> dict[str, Any]:
    fallback = dict(fallback_candidate or {})
    fallback_artifact_refs = _refs_from_output_value(fallback.get("artifact_refs"))
    if isinstance(value, dict):
        payload = dict(value)
        canonical_text = str(
            payload.get("canonical_text")
            or payload.get("text")
            or payload.get("content")
            or payload.get("markdown")
            or payload.get("body")
            or payload.get("final_answer")
            or ""
        ).strip()
        artifact_refs = _refs_from_output_value(payload.get("artifact_refs") or payload.get("output_refs")) or fallback_artifact_refs
        summary = str(payload.get("summary") or canonical_text or fallback.get("summary") or "").strip()
        title = str(payload.get("title") or fallback.get("title") or source_output_key).strip()
        kind = str(payload.get("kind") or fallback.get("kind") or "").strip()
        record_key = str(payload.get("record_key") or fallback.get("record_key") or "").strip()
    elif isinstance(value, str):
        canonical_text = value
        payload = {"source_output_key": source_output_key, source_output_key: value, "canonical_text": value}
        artifact_refs = fallback_artifact_refs
        summary = str(fallback.get("summary") or value[:280]).strip()
        title = str(fallback.get("title") or source_output_key).strip()
        kind = str(fallback.get("kind") or "").strip()
        record_key = str(fallback.get("record_key") or "").strip()
    else:
        payload = {"source_output_key": source_output_key, source_output_key: value}
        artifact_refs = _refs_from_output_value(value) if source_output_key in {"artifact_refs", "output_refs"} else fallback_artifact_refs
        canonical_text = "" if artifact_refs else _json_text(value)
        summary = str(fallback.get("summary") or canonical_text[:280] or source_output_key).strip()
        title = str(fallback.get("title") or source_output_key).strip()
        kind = str(fallback.get("kind") or "").strip()
        record_key = str(fallback.get("record_key") or "").strip()
    metadata = dict(fallback.get("metadata") or {})
    return {
        **fallback,
        "title": title,
        "summary": summary,
        "kind": kind or str(fallback.get("kind") or ""),
        "record_key": record_key,
        "canonical_text": canonical_text,
        "payload": payload,
        "artifact_refs": artifact_refs,
        "metadata": {
            **metadata,
            "source_output_key": source_output_key,
            "source_output_extraction": source,
        },
    }


def _lookup_path(payload: dict[str, Any], path: str) -> dict[str, Any]:
    if "." not in path:
        return {"found": False}
    current: Any = payload
    for part in [item for item in path.split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return {"found": False}
        current = current.get(part)
    return {"found": True, "value": current}


def _refs_from_output_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        refs: list[str] = []
        for key in ("work_memory_id", "working_memory_ref", "version_id", "candidate_version_id", "ref"):
            item = str(value.get(key) or "").strip()
            if item and item not in refs:
                refs.append(item)
        for key in ("refs", "artifact_refs", "output_refs", "working_memory_refs", "formal_memory_refs"):
            for item in _refs_from_output_value(value.get(key)):
                if item not in refs:
                    refs.append(item)
        return refs
    if isinstance(value, (list, tuple, set)):
        refs: list[str] = []
        for item in value:
            for ref in _refs_from_output_value(item):
                if ref not in refs:
                    refs.append(ref)
        return refs
    return []


def _scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("verdict", "status", "value", "result"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return str(value or "").strip()


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return dict(value)
    return {}


def _json_text(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value or "")


def _is_runtime_memory_repository_node(node: dict[str, Any]) -> bool:
    if not node:
        return False
    node_type = str(node.get("node_type") or "").strip()
    node_id = str(node.get("node_id") or node.get("id") or "").strip()
    work_posture = str(node.get("work_posture") or node.get("role") or "").strip()
    return (
        node_type in {"memory_repository", "working_memory_store", "runtime_state_store", "progress_ledger", "issue_ledger", "memory_resource", "memory"}
        or (node_type.endswith("repository") and "artifact" not in node_type)
        or (work_posture == "resource" and node_id.startswith("memory."))
        or node_id.startswith("memory.")
    )


def _repository_id_from_runtime_node(node: dict[str, Any]) -> str:
    metadata = dict(node.get("metadata") or {})
    repo_config = dict(metadata.get("memory_repository") or {})
    return str(repo_config.get("repository_id") or metadata.get("repository_id") or node.get("repository_id") or node.get("node_id") or "").strip()


def _contract_requires_file_artifact_refs(contract: dict[str, Any]) -> bool:
    artifact_policy = dict(contract.get("artifact_policy") or {})
    return bool(artifact_policy.get("enabled") or contract.get("artifact_targets") or contract.get("artifact_target") or contract.get("output_path"))


def _required_artifact_outputs_satisfied(
    output_mappings: list[dict[str, Any]],
    artifact_refs: list[str],
    *,
    requires_file_artifact_refs: bool,
) -> bool:
    if not requires_file_artifact_refs:
        return True
    requires_artifact = any(
        item.get("required") is True and str(item.get("output_key") or "").endswith(":artifact_refs")
        for item in output_mappings
        if isinstance(item, dict)
    )
    if not requires_artifact:
        return True
    return bool(artifact_refs)


def _filter_working_memory_refs_for_handoff(refs: list[str], policy: dict[str, Any], service: WorkingMemoryService) -> list[str]:
    explicit = [str(item).strip() for item in list(policy.get("working_memory_refs") or []) if str(item).strip()]
    if explicit:
        allowed = set(explicit)
        refs = [ref for ref in refs if ref in allowed]
    carry_kinds = {str(item).strip() for item in list(policy.get("carry_kinds") or []) if str(item).strip()}
    carry_scopes = {str(item).strip() for item in list(policy.get("carry_scopes") or []) if str(item).strip()}
    filtered: list[str] = []
    for ref in refs:
        item = service.get_item(ref)
        if item is None:
            continue
        if carry_kinds and item.kind not in carry_kinds:
            continue
        if carry_scopes and item.scope not in carry_scopes:
            continue
        filtered.append(ref)
    limit = _safe_int(policy.get("limit"), 0)
    selected = [ref for ref in filtered if ref]
    return selected[:limit] if limit > 0 else selected


def _decision_refs(payload: dict[str, Any], *keys: str) -> list[str]:
    refs: list[str] = []
    for key in keys:
        for ref in list(payload.get(key) or []):
            value = str(ref).strip()
            if value and value not in refs:
                refs.append(value)
    return refs


def _stage_working_memory_refs_for_commit(state: CoordinationRuntimeState) -> list[str]:
    refs: list[str] = []
    for result in dict(state.get("stage_results") or {}).values():
        if not isinstance(result, dict):
            continue
        for ref in list(result.get("working_memory_refs") or []):
            value = str(ref).strip()
            if value and value not in refs:
                refs.append(value)
    return refs


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
    pending_inputs = _apply_loop_derived_fields(pending_inputs, list(route_policy.get("derived_fields") or []))
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
        if exit_stage_id:
            node_statuses[exit_stage_id] = "pending"
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


def _stage_quality_retry_target(*, contract: dict[str, Any], stage_id: str, event: dict[str, Any]) -> str:
    policy = dict(contract.get("quality_retry_policy") or {})
    if policy.get("enabled") is not True:
        return ""
    diagnostics = dict(event.get("diagnostics") or {})
    acceptance = dict(diagnostics.get("stage_business_acceptance") or {})
    accepted_policies = {str(item) for item in list(policy.get("acceptance_policies") or []) if str(item)}
    if accepted_policies and str(acceptance.get("policy") or "") not in accepted_policies:
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
    requirements_key = str(policy.get("requirements_input_key") or "").strip()
    template = str(policy.get("requirements_template") or "").strip()
    if requirements_key and template:
        pending_inputs[requirements_key] = _render_runtime_template(
            template,
            {
                **pending_inputs,
                **dict(event.get("diagnostics") or {}),
                **dict(dict(event.get("diagnostics") or {}).get("stage_business_acceptance") or {}),
                "quality_issues": "; ".join(
                    str(item)
                    for item in list(dict(dict(event.get("diagnostics") or {}).get("stage_business_acceptance") or {}).get("issues") or [])
                    if str(item)
                ),
            },
        )
    for key in list(policy.get("clear_input_keys") or []):
        if str(key).strip():
            pending_inputs.pop(str(key).strip(), None)
    return pending_inputs


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
    return pending_inputs


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
            updated[key] = _safe_int(updated.get(key), _safe_int(item.get("start"), 0)) + _safe_int(item.get("step"), 1)
    return updated


def _apply_loop_derived_fields(pending_inputs: dict[str, Any], derived_fields: list[Any]) -> dict[str, Any]:
    updated = dict(pending_inputs)
    for raw in derived_fields:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        if not key:
            continue
        op = str(raw.get("op") or "format").strip()
        if op == "copy":
            updated[key] = updated.get(str(raw.get("from_key") or ""), raw.get("default"))
        elif op == "add":
            updated[key] = _safe_int(updated.get(str(raw.get("from_key") or "")), 0) + _safe_int(raw.get("value"), 0)
        elif op == "multiply":
            updated[key] = _safe_int(updated.get(str(raw.get("from_key") or "")), 0) * _safe_int(raw.get("value"), 1)
        elif op == "range":
            start = _safe_int(updated.get(str(raw.get("start_key") or "")), 0)
            end = _safe_int(updated.get(str(raw.get("end_key") or "")), start)
            updated[key] = list(range(start, end + 1)) if end >= start else []
        elif op == "ordinal_group":
            value = _safe_int(updated.get(str(raw.get("from_key") or "")), 1)
            size = max(_safe_int(raw.get("size"), 1), 1)
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
    user_seed = _explicit_project_brief(explicit_inputs)
    if user_seed:
        lines.append("用户硬设定：")
        lines.append(user_seed)
    original_request = str(explicit_inputs.get("original_user_request") or explicit_inputs.get("natural_request") or "").strip()
    if original_request and original_request != user_seed:
        lines.append("原始任务目标：")
        lines.append(original_request)
    if artifact_paths:
        lines.append("目标文本：" + "、".join(artifact_paths) + "。")
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
        lines.append("写作要求：")
        lines.extend(f"- {item}" for item in instructions)
    upstream = str(explicit_inputs.get("upstream_final_content") or "").strip()
    if upstream:
        lines.append("可参考的上轮内容：")
        lines.append(upstream[:800])
    return "\n".join(lines)


def _stale_result_reason(*, event: dict[str, Any], request_payload: dict[str, Any], stage_id: str) -> str:
    event_request_id = str(event.get("request_id") or "").strip()
    event_dispatch_id = str(event.get("dispatch_event_id") or "").strip()
    if not request_payload:
        return "missing_active_stage_execution_request" if event_request_id or event_dispatch_id else ""
    active_stage_id = str(request_payload.get("stage_id") or "").strip()
    if active_stage_id and active_stage_id != stage_id and (event_request_id or event_dispatch_id):
        return "stage_id_does_not_match_active_request"
    active_request_id = str(request_payload.get("request_id") or "").strip()
    if event_request_id and active_request_id and event_request_id != active_request_id:
        return "request_id_does_not_match_active_request"
    active_dispatch_id = str(dict(request_payload.get("dispatch_context") or {}).get("dispatch_event_id") or "").strip()
    if event_dispatch_id and active_dispatch_id and event_dispatch_id != active_dispatch_id:
        return "dispatch_event_id_does_not_match_active_request"
    return ""


def _stage_commit_identity(*, stage_id: str, explicit_inputs: dict[str, Any], artifact_refs: list[str]) -> str:
    if str(stage_id or "") != "memory_commit_chapter":
        return ""
    volume_index = _safe_int(explicit_inputs.get("volume_index"), 1)
    batch_start = _safe_int(explicit_inputs.get("batch_start_index") or explicit_inputs.get("chapter_index"), 0)
    batch_end = _safe_int(explicit_inputs.get("batch_end_index"), batch_start)
    source_refs = []
    for key in (
        "contract.writing.simple_novel.chapter_draft:artifact_refs",
        "contract.writing.simple_novel.chapter_review:artifact_refs",
        "chapter_draft_ref",
        "chapter_review_ref",
        "previous_candidate_ref",
        "previous_review_ref",
    ):
        source_refs.extend(_artifact_refs_from_value(explicit_inputs.get(key)))
    if not source_refs:
        source_refs.extend(str(item) for item in list(artifact_refs or []) if str(item))
    seed = {
        "stage_id": stage_id,
        "volume_index": volume_index,
        "batch_start_index": batch_start,
        "batch_end_index": batch_end,
        "source_refs": sorted(set(source_refs)),
    }
    return f"commitid:{_short_hash(seed)}"


def _short_hash(value: Any) -> str:
    import hashlib
    import json

    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


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
    if not records:
        return []
    lines = ["记忆快照："]
    for record in records[:20]:
        title = str(record.get("title") or record.get("record_key") or record.get("record_id") or record.get("version_id") or "记忆记录").strip()
        summary = str(record.get("summary") or record.get("canonical_text") or "").strip()
        if summary:
            lines.append(f"- {title}: {summary[:4000]}")
    return lines


def _readable_revision_packet_sections(revision_packet: dict[str, Any]) -> list[str]:
    if not revision_packet:
        return []
    lines = ["返修交接包："]
    for key in ("review_verdict", "required_changes", "review_result_refs", "previous_candidate_artifact_refs"):
        value = revision_packet.get(key)
        if value not in ("", None, [], {}):
            lines.append(f"- {key}: {value}")
    return lines


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


def _artifact_refs_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("artifact:") else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).startswith("artifact:")]
    return []


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
        human_gate_policy=dict(payload.get("human_gate_policy") or {}),
        artifact_context_policy=dict(payload.get("artifact_context_policy") or {}),
        revision_context_policy=dict(payload.get("revision_context_policy") or {}),
        quality_retry_policy=dict(payload.get("quality_retry_policy") or {}),
    )


def _collect_stage_outputs(stage_results: dict[str, Any]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for result in dict(stage_results or {}).values():
        if not isinstance(result, dict):
            continue
        for key, value in dict(result.get("outputs") or {}).items():
            if str(key):
                outputs[str(key)] = value
    return outputs


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
        node_statuses[stage_id] = "completed"
        contract_status = _set_contract_node_status(
            contract_status,
            stage_id=stage_id,
            node_status_value="satisfied",
            accepted=True,
            task_result_ref=str(event.get("task_result_ref") or original_event.get("task_result_ref") or original_event.get("agent_run_result_ref") or ""),
            artifact_refs=artifact_refs,
            missing_required_inputs=[],
            diagnostics={"reason": "human_gate_approved"},
        )
        diagnostics["human_gate"] = {"status": "approved", "stage_id": stage_id}
        return {
            "node_statuses": node_statuses,
            "contract_status": contract_status,
            "human_gate": {**human_gate, "status": "approved", "stage_id": stage_id, "resume": dict(event)},
            "terminal_status": "",
            "missing_required_inputs": [],
            "stage_execution_request": {},
            "a2a_payload": {},
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
        diagnostics["retry_stage_id"] = stage_id
        diagnostics["retry_counts"] = retry_counts
        diagnostics["human_gate"] = {"status": "retry", "stage_id": stage_id}
        return {
            "node_statuses": node_statuses,
            "retry_counts": retry_counts,
            "contract_status": contract_status,
            "human_gate": {**human_gate, "status": "retry", "stage_id": stage_id, "resume": dict(event)},
            "terminal_status": "",
            "missing_required_inputs": [],
            "stage_execution_request": {},
            "a2a_payload": {},
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
            "stage_execution_request": {},
            "a2a_payload": {},
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
        "stage_execution_request": {},
        "a2a_payload": {},
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
        active_scope_key=_active_scope_key_for_scheduler(state),
        terminal_status=terminal_status,
        mode="active",
    )
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
        "diagnostics": {
            **dict(state.get("diagnostics") or {}),
            "task_graph_scheduler_state": scheduler_state.to_dict(),
            "scheduler_authority": "task_graph_scheduler_state",
        },
    }


def _runtime_spec_from_state(state: dict[str, Any]) -> TaskGraphRuntimeSpec | None:
    payload = dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {})
    return _runtime_spec_from_payload(payload)


def _dependency_scope_key_from_inputs(inputs: dict[str, Any]) -> str:
    volume_index = _safe_int(inputs.get("volume_index"), 0)
    batch_start = _safe_int(inputs.get("batch_start_index") or inputs.get("chapter_index"), 0)
    batch_end = _safe_int(inputs.get("batch_end_index"), batch_start)
    round_index = _safe_int(inputs.get("round_index") or inputs.get("revision_round") or inputs.get("attempt_index"), 0)
    iteration_index = _safe_int(inputs.get("iteration_index"), 0)
    parts = ["run"]
    if volume_index > 0:
        parts.append(f"volume[{volume_index:03d}]")
    if batch_start > 0:
        batch_label = f"batch[{batch_start:03d}"
        if batch_end and batch_end != batch_start:
            batch_label += f"-{batch_end:03d}"
        batch_label += "]"
        parts.append(batch_label)
    if round_index > 0:
        parts.append(f"round[{round_index:03d}]")
    if iteration_index > 0:
        parts.append(f"iteration[{iteration_index}]")
    return "/".join(parts)


def _active_scope_key_for_scheduler(state: dict[str, Any]) -> str:
    request = dict(state.get("stage_execution_request") or {})
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
        volume_index = _safe_int(pending_inputs.get("volume_index"), 0)
        batch_start = _safe_int(pending_inputs.get("batch_start_index") or pending_inputs.get("chapter_index"), 0)
        batch_end = _safe_int(pending_inputs.get("batch_end_index"), batch_start)
        round_index = _safe_int(
            pending_inputs.get("round_index")
            or pending_inputs.get("revision_round")
            or pending_inputs.get("attempt_index"),
            0,
        )
        if volume_index > 0:
            scope_path.append(f"volume[{volume_index:03d}]")
        if batch_start > 0:
            batch_label = f"batch[{batch_start:03d}"
            if batch_end and batch_end != batch_start:
                batch_label += f"-{batch_end:03d}"
            batch_label += "]"
            scope_path.append(batch_label)
        if round_index > 0:
            scope_path.append(f"round[{round_index:03d}]")
        retry_index = _safe_int(dict(state.get("retry_counts") or {}).get(active_stage_id), 0)
        if retry_index > 0:
            scope_path.append(f"retry[{retry_index}]")
        loop_index = _safe_int(pending_inputs.get("iteration_index"), 0)
        if loop_index > 0:
            scope_path.append(f"iteration[{loop_index}]")
    return _dependency_scope_key_from_inputs(dict(state.get("pending_inputs") or {})) or "/".join(str(item).strip().replace("/", "_") for item in list(scope_path or ["run"]) if str(item).strip()) or "run"


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
                _dataclass_from_payload(TaskGraphRuntimeNode, item)
                for item in list(payload.get("nodes") or [])
                if isinstance(item, dict)
            ),
            edges=tuple(
                _dataclass_from_payload(TaskGraphRuntimeEdge, item)
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
            issues=(),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    except (TypeError, ValueError):
        return None


def _dataclass_from_payload(model_type: Any, payload: dict[str, Any]) -> Any:
    allowed = {item.name for item in dataclass_fields(model_type)}
    return model_type(**{key: value for key, value in dict(payload or {}).items() if key in allowed})


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _initial_contract_status(manifest: dict[str, Any]) -> dict[str, Any]:
    node_status = {
        str(item.get("node_id") or ""): {
            "status": "pending",
            "contract_refs": list(item.get("contract_refs") or []),
            "missing_required_inputs": [],
            "accepted": False,
        }
        for item in list(manifest.get("node_contracts") or [])
        if str(item.get("node_id") or "")
    }
    edge_status = {
        str(item.get("edge_id") or ""): {
            "status": "pending",
            "contract_refs": list(item.get("contract_refs") or []),
            "source_node_id": str(item.get("source_node_id") or ""),
            "target_node_id": str(item.get("target_node_id") or ""),
        }
        for item in list(manifest.get("edge_handoff_contracts") or [])
        if str(item.get("edge_id") or "")
    }
    return {
        "authority": "task_system.contract_status",
        "manifest_ref": str(manifest.get("manifest_id") or ""),
        "valid": bool(manifest.get("valid") is True),
        "issues": list(manifest.get("issues") or []),
        "node_status": node_status,
        "edge_status": edge_status,
        "acceptance_results": {},
    }


def _set_contract_node_status(
    contract_status: dict[str, Any],
    *,
    stage_id: str,
    node_status_value: str,
    accepted: bool,
    task_result_ref: str,
    artifact_refs: list[str],
    missing_required_inputs: list[str],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_status = dict(contract_status or {})
    node_status = {
        str(key): dict(value)
        for key, value in dict(next_status.get("node_status") or {}).items()
    }
    node_payload = dict(node_status.get(stage_id) or {})
    node_payload.update(
        {
            "status": node_status_value,
            "accepted": accepted,
            "task_result_ref": task_result_ref,
            "artifact_refs": list(artifact_refs),
            "missing_required_inputs": list(missing_required_inputs),
            "updated_at": time.time(),
            "diagnostics": dict(diagnostics or {}),
        }
    )
    node_status[stage_id] = node_payload
    acceptance_results = dict(next_status.get("acceptance_results") or {})
    acceptance_results[stage_id] = {
        "accepted": accepted,
        "status": node_status_value,
        "task_result_ref": task_result_ref,
        "artifact_refs": list(artifact_refs),
        "missing_required_inputs": list(missing_required_inputs),
        "diagnostics": dict(diagnostics or {}),
    }
    next_status["node_status"] = node_status
    next_status["acceptance_results"] = acceptance_results
    return next_status


def _accept_contract_status(
    status: dict[str, Any],
    *,
    stage_id: str,
    accepted: bool,
    task_result_ref: str,
    artifact_refs: list[str],
    missing_required_inputs: list[str],
) -> dict[str, Any]:
    next_status = dict(status or {})
    node_status = {
        str(key): dict(value)
        for key, value in dict(next_status.get("node_status") or {}).items()
    }
    node_payload = dict(node_status.get(stage_id) or {})
    node_payload.update(
        {
            "status": "satisfied" if accepted else "failed",
            "accepted": accepted,
            "task_result_ref": task_result_ref,
            "artifact_refs": list(artifact_refs),
            "missing_required_inputs": list(missing_required_inputs),
            "updated_at": time.time(),
        }
    )
    node_status[stage_id] = node_payload
    acceptance_results = dict(next_status.get("acceptance_results") or {})
    acceptance_results[stage_id] = {
        "accepted": accepted,
        "task_result_ref": task_result_ref,
        "artifact_refs": list(artifact_refs),
        "missing_required_inputs": list(missing_required_inputs),
    }
    next_status["node_status"] = node_status
    next_status["acceptance_results"] = acceptance_results
    return next_status


def _manifest_from_payload(payload: dict[str, Any]) -> ContractManifest | None:
    if not payload:
        return None
    return ContractManifest(
        manifest_id=str(payload.get("manifest_id") or ""),
        manifest_kind=str(payload.get("manifest_kind") or ""),
        task_ref=str(payload.get("task_ref") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        graph_id=str(payload.get("graph_id") or payload.get("graph_ref") or ""),
        graph_ref=str(payload.get("graph_ref") or payload.get("graph_id") or ""),
        global_contracts=tuple(_global_contract_from_payload(item) for item in list(payload.get("global_contracts") or []) if isinstance(item, dict)),
        node_contracts=tuple(_node_contract_from_payload(item) for item in list(payload.get("node_contracts") or []) if isinstance(item, dict)),
        edge_handoff_contracts=tuple(_edge_contract_from_payload(item) for item in list(payload.get("edge_handoff_contracts") or []) if isinstance(item, dict)),
        runtime_contracts=tuple(_runtime_contract_from_payload(item) for item in list(payload.get("runtime_contracts") or []) if isinstance(item, dict)),
        acceptance_contracts=tuple(_acceptance_contract_from_payload(item) for item in list(payload.get("acceptance_contracts") or []) if isinstance(item, dict)),
        issues=tuple(_compile_issue_from_payload(item) for item in list(payload.get("issues") or []) if isinstance(item, dict)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _global_contract_from_payload(payload: dict[str, Any]) -> CompiledGlobalContract:
    return CompiledGlobalContract(
        contract_id=str(payload.get("contract_id") or ""),
        title_zh=str(payload.get("title_zh") or ""),
        contract_kind=str(payload.get("contract_kind") or ""),
        source_ref=str(payload.get("source_ref") or ""),
        input_fields=tuple(dict(item) for item in list(payload.get("input_fields") or []) if isinstance(item, dict)),
        output_fields=tuple(dict(item) for item in list(payload.get("output_fields") or []) if isinstance(item, dict)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _node_contract_from_payload(payload: dict[str, Any]) -> CompiledNodeContract:
    return CompiledNodeContract(
        node_id=str(payload.get("node_id") or ""),
        title=str(payload.get("title") or ""),
        node_type=str(payload.get("node_type") or ""),
        task_id=str(payload.get("task_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        runtime_lane=str(payload.get("runtime_lane") or ""),
        projection_id=str(payload.get("projection_id") or ""),
        input_contract_id=str(payload.get("input_contract_id") or ""),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        contract_refs=tuple(str(item) for item in list(payload.get("contract_refs") or []) if str(item)),
        source_refs=tuple(str(item) for item in list(payload.get("source_refs") or []) if str(item)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _edge_contract_from_payload(payload: dict[str, Any]) -> CompiledEdgeHandoffContract:
    return CompiledEdgeHandoffContract(
        edge_id=str(payload.get("edge_id") or ""),
        source_node_id=str(payload.get("source_node_id") or ""),
        target_node_id=str(payload.get("target_node_id") or ""),
        message_type=str(payload.get("message_type") or ""),
        contract_refs=tuple(str(item) for item in list(payload.get("contract_refs") or []) if str(item)),
        handoff_policy=str(payload.get("handoff_policy") or "structured_packet"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _runtime_contract_from_payload(payload: dict[str, Any]) -> CompiledRuntimeContract:
    return CompiledRuntimeContract(
        agent_id=str(payload.get("agent_id") or ""),
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        allowed_runtime_lanes=tuple(str(item) for item in list(payload.get("allowed_runtime_lanes") or []) if str(item)),
        allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or []) if str(item)),
        allowed_memory_scopes=tuple(str(item) for item in list(payload.get("allowed_memory_scopes") or []) if str(item)),
        validation_state=str(payload.get("validation_state") or "unchecked"),
        metadata=dict(payload.get("metadata") or {}),
    )


def _acceptance_contract_from_payload(payload: dict[str, Any]) -> CompiledAcceptanceContract:
    return CompiledAcceptanceContract(
        contract_id=str(payload.get("contract_id") or ""),
        rule_count=int(payload.get("rule_count") or 0),
        rule_refs=tuple(str(item) for item in list(payload.get("rule_refs") or []) if str(item)),
        source_ref=str(payload.get("source_ref") or ""),
    )


def _compile_issue_from_payload(payload: dict[str, Any]) -> ContractCompileIssue:
    return ContractCompileIssue(
        code=str(payload.get("code") or ""),
        message=str(payload.get("message") or ""),
        severity=str(payload.get("severity") or "error"),
        source_ref=str(payload.get("source_ref") or ""),
        contract_id=str(payload.get("contract_id") or ""),
        node_id=str(payload.get("node_id") or ""),
        edge_id=str(payload.get("edge_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
    )
