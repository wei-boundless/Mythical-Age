from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Annotated, Any, TypedDict

from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from langgraph.graph import END, START, StateGraph

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
from .langgraph_checkpoint_adapter import LangGraphCheckpointStoreAdapter
from .runtime_object_store import RuntimeObjectStore
from .models import CoordinationRun
from .runtime_assembly_builder import build_node_runtime_assembly
from .stage_execution_request import StageExecutionRequest, TaskResultReadyEvent
from .task_graph_scheduler import bootstrap_scheduler_state


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
    artifact_refs: Annotated[list[dict[str, Any]], operator.add]
    pending_inputs: dict[str, Any]
    missing_required_inputs: list[str]
    retry_counts: dict[str, int]
    human_gate: dict[str, Any]
    terminal_status: str
    final_result_ref: str
    current_event: dict[str, Any]
    stage_execution_request: dict[str, Any]
    a2a_payload: dict[str, Any]
    working_memory_contexts: dict[str, dict[str, Any]]
    working_memory_operations: list[dict[str, Any]]
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
        self._app = self._build_app()

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
        if not dict(state.get("stage_execution_request") or {}):
            prepared = self._stage_execute(state)
            state.update(prepared)
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run.coordination_run_id,
            state=state,
            metadata={"event": "initialize"},
        )
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
        state["pending_inputs"] = {
            **dict(state.get("pending_inputs") or {}),
            **dict(inherited_inputs or {}),
        }
        if artifact_root:
            state["pending_inputs"]["artifact_root"] = artifact_root
        graph_result = self._app.invoke(state, config={"configurable": {"thread_id": coordination_run.coordination_run_id}})
        final_state = dict(graph_result or {})
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run.coordination_run_id,
            state=final_state,
            metadata={"event": "task_result_ready", "task_run_id": event.task_run_id},
        )
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
        graph_result = self._app.invoke(state, config={"configurable": {"thread_id": coordination_run_id}})
        final_state = dict(graph_result or state)
        checkpoint = self.checkpoints.put_state(
            thread_id=coordination_run_id,
            state=final_state,
            metadata={"event": "human_gate_resumed"},
        )
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
        graph.add_node("complete", self._complete)
        graph.add_edge(START, "stage_accept")
        graph.add_edge("stage_accept", "route_next")
        graph.add_conditional_edges(
            "route_next",
            self._route_after_next,
            {
                "stage_prepare": "stage_prepare",
                "blocked": "blocked",
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
        graph.add_edge("complete", END)
        return graph.compile()

    def _stage_accept(self, state: CoordinationRuntimeState) -> dict[str, Any]:
        event = dict(state.get("current_event") or {})
        if str(event.get("event_type") or "") == "human_gate_resumed":
            return _resume_human_gate_state(state=state, event=event)
        stage_id = str(event.get("stage_id") or state.get("active_stage_id") or "").strip()
        if not stage_id:
            return {"diagnostics": {**dict(state.get("diagnostics") or {}), "accept_warning": "missing_stage_id"}}
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
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
        stage_results = dict(state.get("stage_results") or {})
        stage_results[stage_id] = {
            "task_run_id": str(event.get("task_run_id") or ""),
            "task_ref": str(contract.get("task_ref") or event.get("task_ref") or ""),
            "task_result_ref": str(event.get("task_result_ref") or ""),
            "agent_run_result_ref": str(event.get("agent_run_result_ref") or ""),
            "artifact_refs": artifact_refs,
            "trace_refs": trace_refs,
            "outputs": mapped_outputs,
            "accepted": bool(event.get("accepted") is True) and _required_artifact_outputs_satisfied(
                output_mappings,
                artifact_refs,
                requires_file_artifact_refs=requires_file_artifact_refs,
            ),
        }
        working_memory_operations = list(state.get("working_memory_operations") or [])
        if bool(event.get("accepted") is True):
            write_operation = self._submit_stage_working_memory_candidates(
                state=state,
                stage_id=stage_id,
                contract=contract,
                event=event,
                artifact_refs=artifact_refs,
            )
            if write_operation:
                stage_results[stage_id]["working_memory_refs"] = list(write_operation.get("created_working_memory_refs") or [])
                working_memory_operations.append(write_operation)
                working_memory_operations.extend(
                    self._resolve_stage_working_memory_handoffs(
                        state=state,
                        stage_id=stage_id,
                        created_working_memory_refs=list(write_operation.get("created_working_memory_refs") or []),
                        event=event,
                    )
                )
            commit_operation = self._commit_stage_working_memory_decisions(
                state=state,
                stage_id=stage_id,
                contract=contract,
                event=event,
            )
            if commit_operation:
                working_memory_operations.append(commit_operation)
        node_statuses = dict(state.get("node_statuses") or {})
        accepted = bool(event.get("accepted") is True) and _required_artifact_outputs_satisfied(
            output_mappings,
            artifact_refs,
            requires_file_artifact_refs=requires_file_artifact_refs,
        )
        retry_counts = dict(state.get("retry_counts") or {})
        retry_stage_id = ""
        terminal_status = ""
        if accepted:
            node_statuses[stage_id] = "completed"
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
        elif accepted or retry_stage_id or terminal_status == "failed":
            human_gate = {**human_gate, "status": "cleared"} if human_gate else {}
        loop_updates = _chapter_loop_after_stage_accept(
            state=state,
            stage_id=stage_id,
            accepted=accepted,
            contract=contract,
            event=event,
        )
        artifact_payloads = [{"stage_id": stage_id, "ref": ref, "ref_kind": "artifact"} for ref in artifact_refs]
        return {
            "stage_results": stage_results,
            "node_statuses": dict(loop_updates.get("node_statuses") or node_statuses),
            "retry_counts": retry_counts,
            "contract_status": contract_status,
            "human_gate": human_gate,
            "artifact_refs": artifact_payloads,
            "working_memory_operations": working_memory_operations,
            "final_result_ref": str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
            "stage_execution_request": {},
            "a2a_payload": {},
            "terminal_status": str(loop_updates.get("terminal_status") if "terminal_status" in loop_updates else terminal_status),
            "pending_inputs": dict(loop_updates.get("pending_inputs") or state.get("pending_inputs") or {}),
            "diagnostics": {**diagnostics, **dict(loop_updates.get("diagnostics") or {})},
        }

    @staticmethod
    def _route_next(state: CoordinationRuntimeState) -> dict[str, Any]:
        order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        if not order:
            return {"terminal_status": "blocked", "missing_required_inputs": ["stage_order"]}
        if str(state.get("terminal_status") or "") == "waiting_for_human":
            return _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="waiting_for_human",
            )
        if str(state.get("terminal_status") or "") == "failed":
            return _scheduler_node_sets(
                order=order,
                node_statuses=dict(state.get("node_statuses") or {}),
                state=state,
                terminal_status="failed",
            )
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
            return {
                **next_sets,
                "active_stage_id": retry_stage_id,
                "active_node_id": str(contract.get("node_id") or retry_stage_id),
                "active_task_ref": str(contract.get("task_ref") or ""),
                "node_statuses": node_statuses,
                "terminal_status": "",
                "missing_required_inputs": [],
                "diagnostics": {**dict(next_sets.get("diagnostics") or {}), **diagnostics},
            }
        sets = _scheduler_node_sets(
            order=order,
            node_statuses=node_statuses,
            state=state,
        )
        ready = list(sets.get("ready_nodes") or [])
        if not ready and sets.get("terminal_status"):
            return sets
        if not ready:
            blocked_nodes = [node for node in order if node_statuses.get(node) not in {"completed", "failed"}]
            return {
                **sets,
                "terminal_status": "blocked",
                "blocked_nodes": blocked_nodes,
                "missing_required_inputs": [f"upstream:{node}" for node in blocked_nodes],
            }
        preferred_stage = str(dict(dict(state.get("diagnostics") or {}).get("chapter_loop") or {}).get("preferred_next_stage_id") or "").strip()
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
        return {
            **next_sets,
            "active_stage_id": next_stage,
            "active_node_id": str(contract.get("node_id") or next_stage),
            "active_task_ref": str(contract.get("task_ref") or ""),
            "node_statuses": node_statuses,
            "terminal_status": "",
            "missing_required_inputs": [],
        }

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
        working_memory_contexts = {
            **dict(state.get("working_memory_contexts") or {}),
            **({stage_id: working_memory_context} if working_memory_context else {}),
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
            ),
            artifact_root=str(explicit_inputs.get("artifact_root") or ""),
            artifact_policy=dict(contract.get("artifact_policy") or {}),
            artifact_targets=tuple(dict(item) for item in list(contract.get("artifact_targets") or []) if isinstance(item, dict)),
            output_contract_id=str(contract.get("output_contract_id") or ""),
            expected_outputs=tuple(dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)),
            working_memory_refs=tuple(_working_memory_refs_from_context(working_memory_context)),
        )
        next_handoff_packets = list(state.get("handoff_packets") or [])
        next_handoff_packets.extend(handoff_packets)
        return {
            "stage_execution_request": request.to_dict(),
            "a2a_payload": a2a_payload,
            "handoff_packets": next_handoff_packets,
            "working_memory_contexts": working_memory_contexts,
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
        if not read_policy and not bool(graph_policy.get("auto_read_enabled")):
            return {}
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return {}
        request = {
            **dict(graph_policy.get("default_read_request") or {}),
            **dict(read_policy.get("read_request") or {}),
        }
        if read_policy.get("max_items") and "max_items" not in request:
            request["max_items"] = read_policy.get("max_items")
        node_run_id = f"{root_task_run_id}:{stage_id}"
        selection = self.working_memory.select_for_node(
            task_run_id=root_task_run_id,
            graph_id=str(dict(state.get("diagnostics") or {}).get("graph_ref") or dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {}).get("graph_ref") or ""),
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
        return _working_memory_context_from_selection(
            selection,
            task_run_id=root_task_run_id,
            graph_id=str(dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {}).get("graph_ref") or ""),
            owner_node_id=node_id,
            node_run_id=node_run_id,
            run_attempt_id=str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
        )

    def _submit_stage_working_memory_candidates(
        self,
        *,
        state: CoordinationRuntimeState,
        stage_id: str,
        contract: dict[str, Any],
        event: dict[str, Any],
        artifact_refs: list[str],
    ) -> dict[str, Any]:
        write_policy = dict(contract.get("memory_writeback_policy") or {})
        if not write_policy:
            return {}
        root_task_run_id = str(state.get("root_task_run_id") or "").strip()
        if not root_task_run_id:
            return {}
        raw_candidates = list(dict(event.get("diagnostics") or {}).get("working_memory_candidates") or [])
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)]
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
        if not candidates:
            return {}
        created = []
        node_id = str(contract.get("node_id") or stage_id)
        node_run_id = f"{root_task_run_id}:{stage_id}"
        for index, candidate in enumerate(candidates):
            payload = {
                "task_run_id": root_task_run_id,
                "task_id": str(contract.get("task_ref") or event.get("task_ref") or ""),
                "graph_id": str(dict(dict(state.get("diagnostics") or {}).get("coordination_graph_spec") or {}).get("graph_ref") or ""),
                "owner_node_id": node_id,
                "owner_node_role": str(contract.get("role") or ""),
                "node_run_id": node_run_id,
                "run_attempt_id": str(dict(state.get("retry_counts") or {}).get(stage_id) or 0),
                "stage_id": stage_id,
                "writer_agent_id": str(contract.get("agent_id") or ""),
                "kind": _first_policy_value(write_policy, "writable_kinds", str(candidate.get("kind") or "intermediate_result")),
                "scope": _first_policy_value(write_policy, "writable_scopes", str(candidate.get("scope") or "node_scope")),
                "status": str(candidate.get("status") or write_policy.get("default_status") or "draft"),
                "visibility": str(candidate.get("visibility") or write_policy.get("default_visibility") or "private_to_node"),
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
                },
            }
            created.append(self.working_memory.create_item(**payload))
        return {
            "operation": "memory_write",
            "stage_id": stage_id,
            "node_id": node_id,
            "node_run_id": node_run_id,
            "created_working_memory_refs": [item.work_memory_id for item in created],
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
        if not decision_payload and is_commit_stage:
            accepted_refs = _stage_working_memory_refs_for_commit(state)
        if not accepted_refs and not discarded_refs and not conflict_refs:
            return {}
        actor_id = str(contract.get("agent_id") or "langgraph_coordination_runtime")
        accepted: list[str] = []
        discarded: list[str] = []
        conflicted: list[str] = []
        for ref in accepted_refs:
            item = self.working_memory.accept_item(ref, actor_id=actor_id, metadata={"stage_id": stage_id, "operation": "memory_commit"})
            accepted.append(item.work_memory_id)
        for ref in discarded_refs:
            item = self.working_memory.discard_item(ref, actor_id=actor_id, metadata={"stage_id": stage_id, "operation": "memory_commit"})
            discarded.append(item.work_memory_id)
        for ref in conflict_refs:
            item = self.working_memory.mark_conflict(ref, actor_id=actor_id, metadata={"stage_id": stage_id, "operation": "memory_commit"})
            conflicted.append(item.work_memory_id)
        return {
            "operation": "memory_commit",
            "stage_id": stage_id,
            "node_id": str(contract.get("node_id") or stage_id),
            "accepted_working_memory_refs": accepted,
            "discarded_working_memory_refs": discarded,
            "conflict_working_memory_refs": conflicted,
            "status": "completed",
            "authority": "orchestration.working_memory_resource_node",
        }

    @staticmethod
    def _blocked(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {"terminal_status": str(state.get("terminal_status") or "blocked"), "stage_execution_request": {}, "a2a_payload": {}}

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
                {
                    "operation": "memory_finalize",
                    "task_run_id": task_run_id,
                    "finalization_ref": result.archive_report_path,
                    "status": "completed",
                    "authority": "orchestration.working_memory_resource_node",
                }
            )
        return {"terminal_status": "completed", "stage_execution_request": {}, "a2a_payload": {}, "working_memory_operations": operations}

    @staticmethod
    def _route_after_next(state: CoordinationRuntimeState) -> str:
        terminal = str(state.get("terminal_status") or "")
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
        chapter_loop_state = _initial_chapter_loop_state(metadata=coordination_metadata)
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
            "artifact_refs": [],
            "working_memory_contexts": {},
            "working_memory_operations": [],
            "pending_inputs": dict(chapter_loop_state),
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
                "chapter_loop_policy": dict(coordination_metadata.get("chapter_loop_policy") or {}),
                "chapter_loop": dict(chapter_loop_state),
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
    payload["agent_id"] = str(node.get("agent_id") or "")
    payload["runtime_lane"] = str(node.get("lane") or node.get("runtime_lane") or "")
    payload["role"] = str(node.get("role") or "")
    payload["title"] = str(node.get("title") or contract.stage_id)
    payload["input_contract_id"] = str(node.get("input_contract_id") or payload.get("input_contract_id") or "")
    payload["output_contract_id"] = str(node.get("output_contract_id") or node.get("node_contract_id") or "")
    payload["projection_id"] = str(node.get("projection_id") or "")
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
        "loop_kind",
        "chapter_scoped",
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


def _working_memory_root_for_runtime(root_dir: Any) -> Path:
    runtime_root = Path(root_dir).resolve()
    if runtime_root.name == "runtime_state":
        return runtime_root.parent / "working_memory"
    return runtime_root / "working_memory"


def _first_policy_value(policy: dict[str, Any], key: str, default: str) -> str:
    values = [str(item).strip() for item in list(policy.get(key) or []) if str(item).strip()]
    return values[0] if values else str(default or "").strip()


def _working_memory_context_from_selection(
    selection: dict[str, Any],
    *,
    task_run_id: str,
    graph_id: str,
    owner_node_id: str,
    node_run_id: str,
    run_attempt_id: str,
) -> dict[str, Any]:
    required_items = [item for item in list(selection.get("required_items") or []) if hasattr(item, "to_dict")]
    preferred_items = [item for item in list(selection.get("preferred_items") or []) if hasattr(item, "to_dict")]
    excluded_items = [item for item in list(selection.get("excluded_items") or []) if hasattr(item, "to_dict")]
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
            **dict(selection.get("diagnostics") or {}),
            "excluded_refs": [
                str(getattr(item, "work_memory_id", "") or "")
                for item in excluded_items
                if str(getattr(item, "work_memory_id", "") or "")
            ],
        },
    }


def _working_memory_refs_from_context(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for section_id in ("working_memory.required", "working_memory.preferred", "working_memory.conflict_warnings"):
        for ref in list(dict(context.get(section_id) or {}).get("refs") or []):
            if str(ref).strip() and str(ref).strip() not in refs:
                refs.append(str(ref).strip())
    return refs


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


def _initial_chapter_loop_state(*, metadata: dict[str, Any]) -> dict[str, Any]:
    policy = dict(metadata.get("chapter_loop_policy") or {})
    if not policy.get("enabled"):
        return {}
    first_index = _safe_int(policy.get("first_chapter_index"), 1)
    target_words = _safe_int(policy.get("default_target_words"), 1000000)
    chapter_target_words = _safe_int(policy.get("default_chapter_target_words"), 5000)
    return _chapter_loop_inputs(
        chapter_index=first_index,
        target_words=target_words,
        current_words=0,
        chapter_target_words=chapter_target_words,
    )


def _chapter_loop_after_stage_accept(
    *,
    state: CoordinationRuntimeState,
    stage_id: str,
    accepted: bool,
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    route_policy = dict(contract.get("loop_route_policy") or {})
    if not accepted:
        return {}
    pending_inputs = dict(state.get("pending_inputs") or {})
    stage_chapter_words = _safe_int(dict(event.get("diagnostics") or {}).get("chapter_words"), 0)
    if contract.get("chapter_scoped") is True and stage_chapter_words > 0:
        pending_inputs["last_chapter_words"] = stage_chapter_words
    if str(route_policy.get("mode") or "") != "chapter_word_target":
        if pending_inputs != dict(state.get("pending_inputs") or {}):
            return {
                "pending_inputs": pending_inputs,
                "diagnostics": {
                    "chapter_loop": {
                        **dict(dict(state.get("diagnostics") or {}).get("chapter_loop") or {}),
                        "last_chapter_words": stage_chapter_words,
                    }
                },
            }
        return {}
    chapter_index = _safe_int(pending_inputs.get("chapter_index"), 1)
    current_words = _safe_int(pending_inputs.get("current_words"), 0)
    target_words = _safe_int(pending_inputs.get("target_words"), 1000000)
    chapter_words = _safe_int(
        dict(event.get("diagnostics") or {}).get("chapter_words")
        or pending_inputs.get("last_chapter_words"),
        0,
    )
    if chapter_words <= 0:
        chapter_words = _safe_int(pending_inputs.get("chapter_target_words"), 5000)
    current_words += chapter_words
    continue_stage_id = str(route_policy.get("continue_stage_id") or "chapter_plan")
    exit_stage_id = str(route_policy.get("exit_stage_id") or "final_assembly")
    node_statuses = dict(state.get("node_statuses") or {})
    if current_words < target_words:
        next_chapter_index = chapter_index + 1 if route_policy.get("increment_chapter_on_continue") is not False else chapter_index
        pending_inputs.update(
            _chapter_loop_inputs(
                chapter_index=next_chapter_index,
                target_words=target_words,
                current_words=current_words,
                chapter_target_words=_safe_int(pending_inputs.get("chapter_target_words"), 5000),
            )
        )
        for loop_stage_id, status in list(node_statuses.items()):
            loop_contract = dict(dict(state.get("stage_contracts") or {}).get(loop_stage_id) or {})
            if loop_contract.get("chapter_scoped") is True:
                node_statuses[loop_stage_id] = "pending"
        node_statuses[stage_id] = "completed"
        node_statuses[continue_stage_id] = "pending"
        node_statuses[exit_stage_id] = "pending"
        return {
            "node_statuses": node_statuses,
            "pending_inputs": pending_inputs,
            "terminal_status": "",
            "diagnostics": {
                "chapter_loop": {
                    "status": "continue",
                    "preferred_next_stage_id": continue_stage_id,
                    "completed_chapter_index": chapter_index,
                    "next_chapter_index": next_chapter_index,
                    "current_words": current_words,
                    "target_words": target_words,
                    "chapter_words": chapter_words,
                }
            },
        }
    pending_inputs.update(
        _chapter_loop_inputs(
            chapter_index=chapter_index,
            target_words=target_words,
            current_words=current_words,
            chapter_target_words=_safe_int(pending_inputs.get("chapter_target_words"), 5000),
        )
    )
    node_statuses[exit_stage_id] = "pending"
    return {
        "node_statuses": node_statuses,
        "pending_inputs": pending_inputs,
        "terminal_status": "",
        "diagnostics": {
                "chapter_loop": {
                    "status": "exit",
                    "preferred_next_stage_id": exit_stage_id,
                    "completed_chapter_index": chapter_index,
                "current_words": current_words,
                "target_words": target_words,
                "chapter_words": chapter_words,
            }
        },
    }


def _chapter_loop_inputs(
    *,
    chapter_index: int,
    target_words: int,
    current_words: int,
    chapter_target_words: int,
) -> dict[str, Any]:
    return {
        "chapter_index": chapter_index,
        "chapter_index_padded": f"{chapter_index:03d}",
        "chapter_label": f"第{chapter_index}章",
        "chapter_file_prefix": f"chapter_{chapter_index:03d}",
        "target_words": target_words,
        "current_words": current_words,
        "chapter_target_words": chapter_target_words,
    }


def _stage_execution_message(
    *,
    stage_id: str,
    task_ref: str,
    contract: dict[str, Any],
    explicit_inputs: dict[str, Any],
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
    chapter_index = _safe_int(explicit_inputs.get("chapter_index"), 0)
    chapter_target_words = _safe_int(explicit_inputs.get("chapter_target_words"), 0)
    current_words = _safe_int(explicit_inputs.get("current_words"), 0)
    target_words = _safe_int(explicit_inputs.get("target_words"), 0)
    lines = [
        f"本轮工作：{title}。",
        "请直接完成本轮创作或编辑产物，不要写寒暄、等待补充、工作过程说明或系统说明。",
        "只使用用户给定的硬设定作为不可违背边界；边界之外由你按本轮职责自由发挥。",
    ]
    if chapter_index > 0:
        lines.append(
            f"当前章节：第{chapter_index}章。"
            f"本章目标约{chapter_target_words or 5000}字；"
            f"全书目标约{target_words or 1000000}字；"
            f"当前已完成约{current_words}字。"
        )
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
    if instructions:
        lines.append("写作要求：")
        lines.extend(f"- {item}" for item in instructions)
    upstream = str(explicit_inputs.get("upstream_final_content") or "").strip()
    if upstream:
        lines.append("可参考的上轮内容：")
        lines.append(upstream[:800])
    return "\n".join(lines)


def _render_runtime_template(template: str, values: dict[str, Any]) -> str:
    text = str(template or "")
    if not text:
        return ""
    chapter_index = _safe_int(values.get("chapter_index"), 1)
    replacements = {
        "chapter_index": chapter_index,
        "chapter_index_padded": str(values.get("chapter_index_padded") or f"{chapter_index:03d}"),
        "chapter_label": str(values.get("chapter_label") or f"第{chapter_index}章"),
        "chapter_file_prefix": str(values.get("chapter_file_prefix") or f"chapter_{chapter_index:03d}"),
        "target_words": _safe_int(values.get("target_words"), 1000000),
        "current_words": _safe_int(values.get("current_words"), 0),
        "chapter_target_words": _safe_int(values.get("chapter_target_words"), 5000),
    }
    rendered = text.replace("{chapter_index:03d}", f"{chapter_index:03d}")
    for key, value in replacements.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


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
    requested_batch = str(explicit_inputs.get("requested_batch") or "").strip()
    if requested_batch:
        parts.append(f"批次目标：{requested_batch}")
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
            issues=(),
            diagnostics=dict(payload.get("diagnostics") or {}),
        )
    except (TypeError, ValueError):
        return None


def _dataclass_from_payload(model_type: Any, payload: dict[str, Any]) -> Any:
    allowed = {item.name for item in dataclass_fields(model_type)}
    return model_type(**{key: value for key, value in dict(payload or {}).items() if key in allowed})


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
