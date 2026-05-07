from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tasks.coordination_graph_compiler import compile_coordination_graph_spec

from .artifact_refs import ArtifactRefIndex, collect_task_result_output_refs
from .continuation_inputs import ContinuationInputBinder
from .continuation_policy import (
    CoordinationContinuationPolicy,
    CoordinationStageContract,
    contract_by_stage,
    parse_stage_contracts,
    validate_stage_contracts,
)
from .coordination_trace_adapter import CoordinationTraceAdapter
from .langgraph_checkpoint_adapter import LangGraphCheckpointStoreAdapter
from .models import CoordinationRun
from .stage_execution_request import StageExecutionRequest, TaskResultReadyEvent


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
        turn_context = {
            **dict(current_turn_context or {}),
            "selected_task_id": request.task_ref,
            "task_id": request.task_ref,
            "coordination_run_id": request.coordination_run_id,
            "continuation_stage_id": request.stage_id,
            "stage_execution_request": request.to_dict(),
            "explicit_inputs": dict(request.explicit_inputs),
        }
        return {
            "session_id": session_id,
            "coordination_run_id": request.coordination_run_id,
            "thread_id": request.thread_id,
            "current_task_run_id": request.root_task_run_id,
            "next_task_ref": request.task_ref,
            "next_stage_id": request.stage_id,
            "task_selection": {"selected_task_id": request.task_ref, "task_id": request.task_ref},
            "current_turn_context": turn_context,
            "message": request.message,
            "stage_execution_request": request.to_dict(),
            "suppress_done": True,
        }


class LangGraphCoordinationRuntime:
    """Topology-driven coordination runtime that owns stage progression state."""

    def __init__(
        self,
        *,
        root_dir: Any,
        state_index: Any,
        event_log: Any,
        task_flow_registry: Any,
        trace_reader: Any,
    ) -> None:
        self.root_dir = root_dir
        self.state_index = state_index
        self.event_log = event_log
        self.task_flow_registry = task_flow_registry
        self.trace_reader = trace_reader
        self.artifact_refs = ArtifactRefIndex(state_index=state_index, trace_reader=trace_reader)
        self.input_binder = ContinuationInputBinder(self.artifact_refs)
        self.checkpoints = LangGraphCheckpointStoreAdapter(root_dir)
        self.trace_adapter = CoordinationTraceAdapter(state_index=state_index, event_log=event_log)
        self._app = self._build_app()

    def supports(self, coordination_run: CoordinationRun) -> bool:
        coordination_task = self.task_flow_registry.get_coordination_task(coordination_run.coordination_task_ref)
        if coordination_task is None:
            return False
        contracts = self._contracts_for_run(coordination_run=coordination_run, coordination_task=coordination_task)
        return bool(contracts)

    def initialize(
        self,
        *,
        coordination_run: CoordinationRun,
        event_task_run_id: str = "",
    ) -> LangGraphCoordinationRuntimeResult:
        coordination_task = self.task_flow_registry.get_coordination_task(coordination_run.coordination_task_ref)
        if coordination_task is None:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
        state = self._load_or_bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)
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
        coordination_task = self.task_flow_registry.get_coordination_task(coordination_run.coordination_task_ref)
        if coordination_task is None:
            return LangGraphCoordinationRuntimeResult(diagnostics={"supported": False, "reason": "missing_coordination_task"})
        state = self._load_or_bootstrap_state(coordination_run=coordination_run, coordination_task=coordination_task)
        state["current_event"] = event.to_dict()
        state["pending_inputs"] = dict(inherited_inputs or {})
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
        state["human_gate"] = {
            **dict(state.get("human_gate") or {}),
            "resume": dict(resume_payload or {}),
        }
        state["terminal_status"] = ""
        state["current_event"] = {
            "event_type": "human_gate_resumed",
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

    @staticmethod
    def _stage_accept(state: CoordinationRuntimeState) -> dict[str, Any]:
        event = dict(state.get("current_event") or {})
        stage_id = str(event.get("stage_id") or state.get("active_stage_id") or "").strip()
        if not stage_id:
            return {"diagnostics": {**dict(state.get("diagnostics") or {}), "accept_warning": "missing_stage_id"}}
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        artifact_refs = [
            str(item)
            for item in list(event.get("artifact_refs") or [])
            if str(item)
        ]
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
            "outputs": mapped_outputs,
            "accepted": bool(event.get("accepted") is True),
        }
        node_statuses = dict(state.get("node_statuses") or {})
        node_statuses[stage_id] = "completed" if event.get("accepted") is True else "failed"
        artifact_payloads = [{"stage_id": stage_id, "ref": ref, "ref_kind": "artifact"} for ref in artifact_refs]
        return {
            "stage_results": stage_results,
            "node_statuses": node_statuses,
            "artifact_refs": artifact_payloads,
            "final_result_ref": str(event.get("task_result_ref") or event.get("agent_run_result_ref") or ""),
            "stage_execution_request": {},
            "diagnostics": {**dict(state.get("diagnostics") or {}), "last_accepted_stage_id": stage_id},
        }

    @staticmethod
    def _route_next(state: CoordinationRuntimeState) -> dict[str, Any]:
        order = [str(item) for item in list(state.get("stage_order") or []) if str(item)]
        active = str(state.get("active_stage_id") or "").strip()
        if not order:
            return {"terminal_status": "blocked", "missing_required_inputs": ["stage_order"]}
        next_stage = ""
        if active in order:
            index = order.index(active)
            if index + 1 < len(order):
                next_stage = order[index + 1]
        elif not active:
            next_stage = order[0]
        if not next_stage:
            return {
                "active_stage_id": "",
                "active_task_ref": "",
                "terminal_status": "completed",
            }
        contracts = dict(state.get("stage_contracts") or {})
        contract = dict(contracts.get(next_stage) or {})
        node_statuses = dict(state.get("node_statuses") or {})
        node_statuses[next_stage] = "running"
        return {
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
            return {
                "pending_inputs": dict(binding.explicit_inputs),
                "missing_required_inputs": list(binding.missing_required_inputs),
                "terminal_status": "blocked",
                "node_statuses": node_statuses,
                "diagnostics": {**dict(state.get("diagnostics") or {}), "binding": dict(binding.diagnostics)},
            }
        return {
            "pending_inputs": dict(binding.explicit_inputs),
            "missing_required_inputs": [],
            "diagnostics": {**dict(state.get("diagnostics") or {}), "binding": dict(binding.diagnostics)},
        }

    @staticmethod
    def _stage_execute(state: CoordinationRuntimeState) -> dict[str, Any]:
        stage_id = str(state.get("active_stage_id") or "").strip()
        contract = dict(dict(state.get("stage_contracts") or {}).get(stage_id) or {})
        request = StageExecutionRequest(
            request_id="",
            coordination_run_id=str(state.get("coordination_run_id") or ""),
            thread_id=str(state.get("coordination_run_id") or ""),
            root_task_run_id=str(state.get("root_task_run_id") or ""),
            stage_id=stage_id,
            node_id=str(contract.get("node_id") or stage_id),
            task_ref=str(contract.get("task_ref") or state.get("active_task_ref") or ""),
            agent_id=str(contract.get("agent_id") or ""),
            runtime_lane=str(contract.get("runtime_lane") or ""),
            explicit_inputs=dict(state.get("pending_inputs") or {}),
            artifact_root=str(dict(state.get("pending_inputs") or {}).get("artifact_root") or ""),
            expected_outputs=tuple(dict(item) for item in list(contract.get("output_mappings") or []) if isinstance(item, dict)),
        )
        return {
            "stage_execution_request": request.to_dict(),
            "terminal_status": "",
        }

    @staticmethod
    def _blocked(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {"terminal_status": "blocked", "stage_execution_request": {}}

    @staticmethod
    def _complete(state: CoordinationRuntimeState) -> dict[str, Any]:
        return {"terminal_status": "completed", "stage_execution_request": {}}

    @staticmethod
    def _route_after_next(state: CoordinationRuntimeState) -> str:
        terminal = str(state.get("terminal_status") or "")
        if terminal == "blocked":
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
        graph_spec = compile_coordination_graph_spec(
            coordination_task=coordination_task,
            specific_tasks=tuple(self.task_flow_registry.list_specific_task_records()),
            topology_template=topology_template,
            communication_protocol=communication_protocol,
        )
        topology_nodes = [node.to_dict() for node in graph_spec.nodes]
        contracts = self._contracts_for_run(coordination_run=coordination_run, coordination_task=coordination_task)
        stage_sequence = [dict(item) for item in list(dict(getattr(coordination_task, "metadata", {}) or {}).get("stage_sequence") or []) if isinstance(item, dict)]
        issues = validate_stage_contracts(coordination_task=coordination_task, contracts=contracts, stage_sequence=stage_sequence)
        order = [contract.stage_id for contract in contracts]
        if not order:
            order = [str(item.get("stage_id") or "") for item in stage_sequence if str(item.get("stage_id") or "")]
        current_stage = str(dict(coordination_run.diagnostics.get("coordination_flow") or {}).get("current_stage_id") or (order[0] if order else ""))
        if current_stage and current_stage not in order:
            current_stage = order[0] if order else ""
        contract_map = {contract.stage_id: _contract_payload(contract, topology_nodes=topology_nodes) for contract in contracts}
        node_statuses: dict[str, str] = {}
        for stage_id in order:
            if stage_id == current_stage:
                node_statuses[stage_id] = "running"
            else:
                node_statuses[stage_id] = "pending"
        return {
            "coordination_run_id": coordination_run.coordination_run_id,
            "root_task_run_id": coordination_run.task_run_id,
            "coordination_mode": str(getattr(coordination_task, "coordination_mode", "") or ""),
            "active_stage_id": current_stage,
            "active_node_id": str(contract_map.get(current_stage, {}).get("node_id") or current_stage),
            "active_task_ref": str(contract_map.get(current_stage, {}).get("task_ref") or ""),
            "stage_order": order,
            "stage_contracts": contract_map,
            "node_statuses": node_statuses,
            "stage_results": {},
            "artifact_refs": [],
            "pending_inputs": {},
            "missing_required_inputs": [],
            "retry_counts": {},
            "human_gate": {},
            "terminal_status": "blocked" if issues else "",
            "final_result_ref": "",
            "current_event": {},
            "stage_execution_request": {},
            "diagnostics": {
                "coordination_engine": "langgraph_runtime",
                "coordination_graph_spec": graph_spec.to_dict(),
                "stage_contract_issues": issues,
                "continuation_policy": CoordinationContinuationPolicy.from_metadata(
                    dict(getattr(coordination_task, "metadata", {}) or {})
                ).to_dict(),
            },
        }

    def _contracts_for_run(self, *, coordination_run: CoordinationRun, coordination_task: Any) -> tuple[CoordinationStageContract, ...]:
        topology_template = self.task_flow_registry.get_topology_template(coordination_run.topology_template_id)
        topology_nodes = [dict(item) for item in list(getattr(topology_template, "nodes", ()) or [])]
        return parse_stage_contracts(coordination_task=coordination_task, topology_nodes=topology_nodes)


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
    return payload


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
