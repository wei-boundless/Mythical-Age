from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, normalize_artifact_ref

from .edge_contracts import edge_contract_for_edge
from .flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from .context_provider_registry import (
    apply_context_providers,
    context_provider_initial_input_keys,
    context_provider_loop_contract_input_keys,
    context_provider_runtime_scope_keys,
)
from .flow_packet import flow_packet_inbound_projection
from .loop_engine import LoopEngine
from .memory_context import MemoryContextAssembler
from .models import ExecutableGraphConfig, GraphLoopState, GraphNodeExecutionSlot, GraphNodeWorkOrder, safe_id, stable_hash
from .node_adapter_models import node_execution_adapter_from_node, node_physical_spec_from_node, work_kind_for_adapter
from .runtime_objects import load_flow_packet, load_node_result
from .scheduler_view import upstream_dependency_node_ids
from .spacetime_models import graph_time_ref_for_dispatch, node_attempt_ref_for_dispatch


class GraphContextMaterializer:
    """Builds graph node work orders and internal materialization packages.

    GraphLoop owns state progression. This materializer owns the graph slot
    assembly data; RuntimeCompiler decides the model-visible projection.
    """

    authority = "graph_system.context_materializer"

    def __init__(self, *, services: Any | None = None) -> None:
        self._services = services
        self._memory_context = MemoryContextAssembler(services=services)
        self._loop_engine = LoopEngine()

    def build_work_order(
        self,
        *,
        graph_config: ExecutableGraphConfig,
        state: GraphLoopState,
        node: dict[str, Any],
    ) -> GraphNodeWorkOrder:
        node_id = str(node.get("node_id") or "")
        executor = dict(node.get("executor") or {})
        executor_type = str(executor.get("executor_type") or "agent")
        dispatch_seq = len(tuple(dict(state.result_history or {}).get(node_id) or ())) + 1
        graph_clock_seq = state.event_cursor + 1
        inbound_context = self.inbound_context_for_node(graph_config=graph_config, state=state, node_id=node_id)
        input_package = self.build_input_package(
            graph_config=graph_config,
            state=state,
            node=node,
            inbound_context=inbound_context,
            dispatch_seq=dispatch_seq,
            graph_clock_seq=graph_clock_seq,
        )
        visible_inbound_context = [
            dict(item)
            for item in list(input_package.get("inbound_context") or inbound_context or [])
            if isinstance(item, dict)
        ]
        work_order_id = f"gwork:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{dispatch_seq}:{graph_clock_seq}:{int(time.time() * 1000)}"
        node_physical = node_physical_spec_from_node(node)
        execution_adapter = node_execution_adapter_from_node(node)
        superstep_seq = _superstep_seq_from_state(state=state, graph_clock_seq=graph_clock_seq)
        graph_time = graph_time_ref_for_dispatch(
            graph_run_id=state.graph_run_id,
            structure_hash=state.structure_hash or graph_config.expected_structural_hash(),
            graph_clock_seq=graph_clock_seq,
            event_cursor=state.event_cursor,
            superstep_seq=superstep_seq,
            checkpoint_id=str(state.diagnostics.get("latest_checkpoint_id") or ""),
        ).to_dict()
        node_attempt = node_attempt_ref_for_dispatch(
            graph_run_id=state.graph_run_id,
            node_id=node_id,
            work_order_id=work_order_id,
            node_dispatch_seq=dispatch_seq,
            graph_clock_seq=graph_clock_seq,
            superstep_seq=superstep_seq,
        ).to_dict()
        graph_slot = self.build_graph_slot(
            graph_config=graph_config,
            state=state,
            node=node,
            work_order_id=work_order_id,
            input_package=input_package,
            inbound_context=visible_inbound_context,
            node_physical=node_physical.to_dict(),
            execution_adapter=execution_adapter.to_dict(),
            graph_time=graph_time,
            node_attempt=node_attempt,
        )
        environment_refs = _environment_refs(graph_config)
        structure_hash = state.structure_hash or graph_config.expected_structural_hash()
        structure_version = state.structure_version or "graph_structure.v1"
        config_snapshot_id = graph_config.config_id
        config_snapshot_hash = graph_config.content_hash
        agent_binding = dict(input_package.get("agent_binding") or {})
        agent_config = _node_agent_config(node=node, agent_binding=agent_binding)
        node_session_policy = dict(agent_binding.get("session_policy") or {})
        node_session_id = _node_session_id(
            state=state,
            node_id=node_id,
            dispatch_seq=dispatch_seq,
            session_policy=node_session_policy,
        )
        execution_input_package = _execution_input_package(input_package)
        execution_artifact_view = _execution_artifact_view_request(input_package.get("artifact_view"))
        execution_expected_result_contract = _execution_expected_result_contract(input_package.get("expected_result_contract"))
        explicit_inputs = dict(input_package.get("initial_inputs") or {})
        idempotency_key = _work_order_idempotency_key(
            graph_config=graph_config,
            state=state,
            node_id=node_id,
            explicit_inputs=explicit_inputs,
            graph_clock_seq=graph_clock_seq,
        )
        task_ref = str(node.get("task_ref") or f"task_graph.node.{graph_config.graph_id}.{node_id}")
        graph_node_task_binding_hint = _graph_node_task_binding_hint(
            graph_config=graph_config,
            state=state,
            node=node,
            node_id=node_id,
            task_ref=task_ref,
            work_order_id=work_order_id,
            input_package=input_package,
            idempotency_key=idempotency_key,
            structure_hash=structure_hash,
            expected_result_contract=execution_expected_result_contract,
        )
        return GraphNodeWorkOrder(
            work_order_id=work_order_id,
            work_kind=work_kind_for_adapter(execution_adapter.adapter_kind, legacy_executor_type=executor_type),
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            node_kind=node_physical.node_kind,
            execution_adapter=execution_adapter.to_dict(),
            graph_time=graph_time,
            node_attempt=node_attempt,
            structure_hash=structure_hash,
            structure_version=structure_version,
            config_snapshot_id=config_snapshot_id,
            config_snapshot_hash=config_snapshot_hash,
            task_ref=task_ref,
            executor_type=executor_type,
            node_session_id=node_session_id,
            node_session_policy=node_session_policy,
            node_id=node_id,
            agent_id=str(agent_config.get("agent_id") or ""),
            agent_profile_id=str(agent_config.get("agent_profile_id") or ""),
            message=str(input_package.get("agent_instruction") or ""),
            explicit_inputs=explicit_inputs,
            idempotency_key=idempotency_key,
            input_package=execution_input_package,
            graph_slot=graph_slot,
            graph_state={
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": structure_version,
                "config_snapshot_id": config_snapshot_id,
                "config_snapshot_hash": config_snapshot_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "node_session_id": node_session_id,
                "node_session_policy": node_session_policy,
                "graph_clock_seq": graph_clock_seq,
                "node_dispatch_seq": dispatch_seq,
                "node_dispatch_count": dispatch_seq,
                "round_index": _dispatch_round_index(input_package=input_package, dispatch_seq=dispatch_seq),
                "completed_node_ids": list(state.completed_node_ids),
                "failed_node_ids": list(state.failed_node_ids),
                "upstream_node_ids": list(upstream_dependency_node_ids(graph_config, node_id)),
                "available_result_node_ids": sorted(state.result_index.keys()),
                "authority": "graph_system_loop.node_work_order_graph_state",
            },
            context_refs=dict(node.get("context") or {}),
            memory_view_request={},
            artifact_view_request=execution_artifact_view,
            file_view_request={},
            artifact_space_ref=str(environment_refs.get("artifact_space_ref") or ""),
            memory_space_ref=str(environment_refs.get("memory_space_ref") or ""),
            file_access_table_refs=(),
            artifact_repository_targets=(),
            memory_repository_targets=(),
            expected_result_contract=execution_expected_result_contract,
            async_policy=dict(node.get("async_policy") or {}),
            retry_policy=dict(node.get("retry") or {}),
            timeout_policy=dict(node.get("timeout") or {}),
            dispatch_context={
                "graph_run_id": state.graph_run_id,
                "config_id": graph_config.config_id,
                "node_kind": node_physical.node_kind,
                "node_physical": node_physical.to_dict(),
                "execution_adapter": execution_adapter.to_dict(),
                "graph_time": graph_time,
                "node_attempt": node_attempt,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": structure_version,
                "config_snapshot_id": config_snapshot_id,
                "config_snapshot_hash": config_snapshot_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "node_session_id": node_session_id,
                "node_session_policy": node_session_policy,
                "graph_clock_seq": graph_clock_seq,
                "node_dispatch_seq": dispatch_seq,
                "node_dispatch_count": dispatch_seq,
                "round_index": _dispatch_round_index(input_package=input_package, dispatch_seq=dispatch_seq),
                "dispatch_event_id": f"dispatch:{state.graph_run_id}:{node_id}:{int(time.time() * 1000)}",
                "executor": executor,
                "graph_node_task_binding_hint": graph_node_task_binding_hint,
                "inbound_context_count": len(visible_inbound_context),
                "materializer": self.authority,
            },
        )

    def build_graph_slot(
        self,
        *,
        graph_config: ExecutableGraphConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        work_order_id: str,
        input_package: dict[str, Any],
        inbound_context: list[dict[str, Any]],
        node_physical: dict[str, Any] | None = None,
        execution_adapter: dict[str, Any] | None = None,
        graph_time: dict[str, Any] | None = None,
        node_attempt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        loop_context = dict(input_package.get("loop_context") or {})
        memory_view = dict(input_package.get("memory_view") or {})
        output_contract = dict(input_package.get("output_contract") or {})
        slot_inbound_context = _slot_inbound_contexts(
            graph_config=graph_config,
            state=state,
            node_id=node_id,
            input_package=input_package,
            inbound_context=inbound_context,
        )
        read_protocols = list(dict(memory_view.get("graph_memory_policy") or {}).get("read_rules") or [])
        memory_resolution = self._memory_context.resolve_for_node(
            graph_config=graph_config,
            state=state,
            node=node,
            work_order_id=work_order_id,
            read_protocols=read_protocols,
        )
        slot = GraphNodeExecutionSlot(
            slot_id=f"gslot:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(stable_hash([input_package.get('package_id'), slot_inbound_context, loop_context])[:12])}",
            graph_identity={
                "graph_run_id": state.graph_run_id,
                "root_task_run_id": state.task_run_id,
                "graph_root_task_run_id": state.task_run_id,
                "node_executor_execution_id": "",
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "graph_id": graph_config.graph_id,
                "node_id": node_id,
                "work_order_id": str(work_order_id or ""),
            },
            node_physical=dict(node_physical or input_package.get("node_physical") or {}),
            execution_adapter=dict(execution_adapter or input_package.get("execution_adapter") or {}),
            graph_time=dict(graph_time or input_package.get("graph_time") or {}),
            node_attempt=dict(node_attempt or input_package.get("node_attempt") or {}),
            task_contract=_execution_task_contract_from_input_package(input_package),
            agent_binding=_execution_agent_binding_from_input_package(input_package),
            edge_contracts={
                "inbound_flow_packets": _inbound_flow_packets(slot_inbound_context),
                "inbound_edge_contexts": _execution_inbound_contexts(slot_inbound_context),
                "outbound_edge_policies": [
                    _outbound_edge_policy(graph_config=graph_config, edge=dict(edge))
                    for edge in build_outbound_flow_edges(graph_config, node_id)
                ],
                "authority": "graph_system.compiled_edge_contract_context",
            },
            memory_contract={
                "namespace_id": _memory_namespace_id(graph_config=graph_config, state=state),
                "read_protocol_count": len(read_protocols),
                "resolved_snapshots": _execution_memory_snapshots(memory_resolution.get("resolved_snapshots")),
                "write_candidate_protocol_count": len(list(dict(memory_view.get("graph_memory_policy") or {}).get("write_rules") or [])),
                "commit_protocol_count": len(list(dict(memory_view.get("graph_memory_policy") or {}).get("commit_rules") or [])),
                "memory_receipt_refs": list(memory_resolution.get("memory_receipt_refs") or []),
                "diagnostics": dict(memory_resolution.get("diagnostics") or {}),
                "memory_space_ref": str(input_package.get("memory_space_ref") or ""),
                "authority": "graph_system.memory_contract_projection",
            },
            loop_contract={
                "loop_context": _execution_loop_context(loop_context),
                "scope_id": str(loop_context.get("scope_id") or ""),
                "variables": _loop_variables(loop_context),
                "dynamic_bindings": _loop_dynamic_bindings(loop_context),
                "authority": "graph_system.loop_contract_projection",
            },
            output_contract={
                "output_policy": dict(dict(output_contract.get("contract_bindings") or {}).get("output") or {}),
                "artifact_targets": _output_artifact_targets(input_package),
                "formal_memory_targets": [],
                "environment_projection": _output_environment_projection(graph_config, input_package=input_package),
                "expected_result_contract": _execution_expected_result_contract(input_package.get("expected_result_contract")),
                "authority": "graph_system.output_contract_projection",
            },
            state_refs={
                "inbound_packet_refs": _inbound_packet_refs(inbound_context),
                "artifact_refs": [],
                "checkpoint_ref": "",
                "prior_result_ref_count": len(dict(state.result_index or {})),
                "authority": "graph_system.node_state_refs",
            },
            runtime_controls={
                "retry_policy": dict(node.get("retry") or {}),
                "timeout_policy": dict(node.get("timeout") or {}),
                "failure_policy": dict(node.get("failure_policy") or {}),
                "resume_policy": dict(node.get("resume_policy") or {}),
                "disconnect_policy": dict(node.get("disconnect_policy") or {}),
                "post_node_gate_policy": dict(dict(node.get("gates") or {}).get("post_node_gate_policy") or dict(node.get("metadata") or {}).get("post_node_gate_policy") or {}),
                "authority": "graph_system.runtime_controls_projection",
            },
            visibility={
                "system_control_only": ["graph_identity", "state_refs", "runtime_controls"],
                "runtime_consumable": [
                    "agent_binding",
                    "output_contract.artifact_targets",
                ],
                "model_visible_projection": [
                    "task_contract.prompt_contract",
                    "edge_contracts.inbound_edge_contexts",
                    "memory_contract.resolved_snapshots",
                    "output_contract.output_policy",
                ],
                "authority": "graph_system.node_execution_slot_visibility",
            },
        )
        return slot.to_dict()

    def build_input_package(
        self,
        *,
        graph_config: ExecutableGraphConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        inbound_context: list[dict[str, Any]],
        dispatch_seq: int = 1,
        graph_clock_seq: int = 1,
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        prompt_contract = _prompt_contract(node)
        task_contract = _node_task_contract(graph_config=graph_config, node_id=node_id)
        agent_binding = _node_agent_binding(graph_config=graph_config, node_id=node_id)
        task_environment_id = _node_effective_environment_id(graph_config=graph_config, node=node, agent_binding=agent_binding)
        loop_context = self._loop_engine.context_for_node(state=state, node=node)
        node_physical = node_physical_spec_from_node(node)
        execution_adapter = node_execution_adapter_from_node(node)
        graph_time = graph_time_ref_for_dispatch(
            graph_run_id=state.graph_run_id,
            structure_hash=state.structure_hash or graph_config.expected_structural_hash(),
            graph_clock_seq=graph_clock_seq,
            event_cursor=state.event_cursor,
            superstep_seq=_superstep_seq_from_state(state=state, graph_clock_seq=graph_clock_seq),
            checkpoint_id=str(state.diagnostics.get("latest_checkpoint_id") or ""),
        ).to_dict()
        initial_inputs = _initial_inputs_with_loop_cursor(
            initial_inputs=dict(state.initial_inputs or {}),
            loop_context=loop_context,
        )
        initial_inputs, inbound_context = apply_context_providers(
            graph_config=graph_config,
            state=state,
            node=node,
            services=self._services,
            initial_inputs=initial_inputs,
            inbound_context=inbound_context,
        )
        loop_context = _loop_context_with_materialized_inputs(
            loop_context=loop_context,
            initial_inputs=initial_inputs,
        )
        inbound_context = _slot_inbound_contexts(
            graph_config=graph_config,
            state=state,
            node_id=node_id,
            input_package={"initial_inputs": initial_inputs},
            inbound_context=inbound_context,
        )
        environment_refs = _environment_refs(graph_config)
        return {
            "package_id": f"gin:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(stable_hash([initial_inputs, loop_context, inbound_context])[:12])}",
            "authority": "graph_system.node_materialization_package",
            "materializer_authority": self.authority,
            "node_identity": {
                "node_id": node_id,
                "title": str(node.get("title") or node_id),
                "node_type": str(node.get("node_type") or ""),
                "node_kind": node_physical.node_kind,
                "task_ref": str(node.get("task_ref") or ""),
            },
            "node_physical": node_physical.to_dict(),
            "execution_adapter": execution_adapter.to_dict(),
            "graph_time": graph_time,
            "prompt_contract": prompt_contract,
            "task_contract": task_contract,
            "agent_binding": agent_binding,
            "task_environment_id": task_environment_id,
            "runtime_scope": _runtime_scope_from_state(state),
            "runtime_profile": _node_runtime_profile(graph_config=graph_config, node=node, agent_binding=agent_binding),
            "execution_boundary": {
                "node_worker_only": True,
                "graph_state_owner": "graph_system_loop",
                "allowed_result_authority": "graph_system_node_result_envelope",
                "forbidden_actions": [
                    "advance_graph_state",
                    "dispatch_downstream_node",
                    "write_graph_checkpoint",
                    "bypass_edge_contract",
                ],
                "authority": "graph_system.node_worker_execution_boundary",
            },
            "agent_instruction": _agent_instruction(prompt_contract=prompt_contract, node=node),
            "input_contract": dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("schema", {}),
            "output_contract": dict(node.get("contracts") or {}),
            "initial_inputs": initial_inputs,
            "loop_context": loop_context,
            "dispatch_metadata": _dispatch_metadata(
                initial_inputs=initial_inputs,
                loop_context=loop_context,
                dispatch_seq=dispatch_seq,
                graph_clock_seq=graph_clock_seq,
            ),
            "inbound_context": inbound_context,
            "memory_view": _memory_view_request(graph_config=graph_config, node=node, task_environment_id=task_environment_id),
            "artifact_view": _artifact_view_request(graph_config=graph_config, node=node, task_environment_id=task_environment_id),
            "file_view": _file_view_request(graph_config=graph_config, node=node, task_environment_id=task_environment_id),
            "environment_refs": environment_refs,
            "artifact_space_ref": str(environment_refs.get("artifact_space_ref") or ""),
            "memory_space_ref": str(environment_refs.get("memory_space_ref") or ""),
            "file_access_table_refs": list(environment_refs.get("file_access_table_refs") or []),
            "artifact_repository_targets": [dict(item) for item in list(environment_refs.get("artifact_repository_targets") or []) if isinstance(item, dict)],
            "memory_repository_targets": [dict(item) for item in list(environment_refs.get("memory_repository_targets") or []) if isinstance(item, dict)],
            "issue_view": _issue_view_request(graph_config=graph_config, node=node),
            "hidden_control_refs": {
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "work_order_source": "GraphLoop.dispatch_ready",
            },
            "expected_result_contract": {
                **dict(node.get("contracts") or {}),
                **({"task_contract": task_contract} if task_contract else {}),
            },
        }

    def inbound_context_for_node(self, *, graph_config: ExecutableGraphConfig, state: GraphLoopState, node_id: str) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        for edge in build_inbound_flow_edges(graph_config, node_id):
            edge_state = dict(state.edge_states.get(str(edge.get("edge_id") or "")) or {})
            for packet_entry in _edge_packet_entries(edge_state):
                packet = load_flow_packet(self._services, packet_entry) if self._services is not None else None
                if packet is None or packet.target_unit_id != node_id:
                    continue
                context.append(flow_packet_inbound_projection(packet, packet_ref=str(packet_entry.get("packet_ref") or "")))
        context.extend(_loop_iteration_contexts_for_node(graph_config=graph_config, state=state, node_id=node_id))
        context.extend(
            _self_quality_failure_contexts_for_node(
                graph_config=graph_config,
                services=self._services,
                state=state,
                node_id=node_id,
            )
        )
        return context


def _work_order_idempotency_key(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node_id: str,
    explicit_inputs: dict[str, Any],
    graph_clock_seq: int,
) -> str:
    transition_refs: list[dict[str, Any]] = []
    for edge in graph_config.edges:
        if str(edge.get("target_node_id") or "") != node_id:
            continue
        edge_state = dict(state.edge_states.get(str(edge.get("edge_id") or "")) or {})
        if str(edge_state.get("status") or "") != "ready":
            continue
        transition_refs.append(
            {
                "edge_id": str(edge.get("edge_id") or ""),
                "decision_ref": str(edge_state.get("decision_ref") or ""),
                "source_result_ref": str(edge_state.get("source_result_ref") or ""),
                "graph_clock_seq": int(edge_state.get("graph_clock_seq") or 0),
            }
        )
    return f"{state.graph_run_id}:{node_id}:{stable_hash([explicit_inputs, transition_refs, graph_clock_seq])}"


def _graph_node_task_binding_hint(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node: dict[str, Any],
    node_id: str,
    task_ref: str,
    work_order_id: str,
    input_package: dict[str, Any],
    idempotency_key: str,
    structure_hash: str,
    expected_result_contract: dict[str, Any],
) -> dict[str, Any]:
    node_metadata = dict(node.get("metadata") or {})
    agent_config = _node_agent_config(node=node, agent_binding=dict(input_package.get("agent_binding") or {}))
    binding_key = stable_hash(
        [
            state.graph_run_id,
            node_id,
            idempotency_key,
        ]
    )
    task_key = stable_hash(
        [
            state.graph_run_id,
            node_id,
            task_ref,
            idempotency_key,
        ]
    )
    parent_task_environment_id = str(
        state.diagnostics.get("task_environment_id")
        or dict(state.diagnostics.get("runtime_scope") or {}).get("task_environment_id")
        or graph_config.task_environment_id
        or ""
    ).strip()
    return _drop_empty(
        {
            "authority": "graph_system.graph_node_task_binding_hint",
            "binding_id": f"gntb:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{binding_key[:16]}",
            "graph_run_id": state.graph_run_id,
            "graph_id": graph_config.graph_id,
            "config_id": graph_config.config_id,
            "structure_hash": structure_hash,
            "node_id": node_id,
            "work_order_id": work_order_id,
            "parent_task_environment_id": parent_task_environment_id,
            "node_task_environment_id": f"taskenv:graphnode:{task_key[:20]}",
            "task_instance_id": f"taskinst:graphnode:{task_key[:20]}",
            "task_ref": task_ref,
            "agent_profile_id": str(agent_config.get("agent_profile_id") or ""),
            "input_package_ref": str(input_package.get("package_id") or ""),
            "expected_result_contract_ref": str(
                expected_result_contract.get("contract_ref")
                or expected_result_contract.get("contract_id")
                or ""
            ),
            "lease_policy": dict(node.get("async_policy") or {}),
            "result_projection_policy": dict(node_metadata.get("result_projection_policy") or {}),
            "idempotency_key": idempotency_key,
            "status": "created",
        }
    )


def _int_value(value: Any, default: int | None = 0) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _node_tail(node_id: str) -> str:
    return str(node_id or "").strip().rsplit("::", 1)[-1]


def _node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any] | None:
    target = str(node_id or "").strip()
    if not target:
        return None
    for raw in graph_config.nodes:
        node = dict(raw or {}) if isinstance(raw, dict) else {}
        if str(node.get("node_id") or "").strip() == target:
            return node
    return None


def _self_quality_failure_contexts_for_node(
    *,
    graph_config: ExecutableGraphConfig,
    services: Any | None,
    state: GraphLoopState,
    node_id: str,
) -> list[dict[str, Any]]:
    latest_failure = _latest_self_quality_failure(services=services, state=state, node_id=node_id)
    if not latest_failure:
        return []
    result = latest_failure["result"]
    summary = dict(latest_failure.get("summary") or {})
    artifact_refs = _artifact_ref_values(list(result.artifact_refs or []) or summary.get("artifact_refs"))
    source_error = dict(result.error or summary.get("error") or {})
    quality_acceptance = dict(dict(result.diagnostics or {}).get("quality_acceptance") or {})
    issue_values = list(source_error.get("issues") or quality_acceptance.get("issues") or [])
    retry_policy = dict((_node_by_id(graph_config, node_id) or {}).get("retry") or {})
    include_artifact_text = bool(retry_policy.get("include_quality_failure_artifact_text") is True)
    payload = _drop_empty(
        {
            "source_error": source_error,
            "quality_acceptance": quality_acceptance,
            "quality_issue_summary": str(
                source_error.get("quality_issue_summary")
                or quality_acceptance.get("quality_issue_summary")
                or ""
            ),
            "issues": issue_values,
            "handoff_summary": str(result.handoff_summary or summary.get("handoff_summary") or "")[:1200],
            "artifact_refs": artifact_refs,
            "artifact_payloads": (
                _artifact_payloads_for_refs(artifact_refs, max_refs=8, max_chars=30000)
                if include_artifact_text
                else []
            ),
            "authority": "graph_system.self_quality_failure_payload",
        }
    )
    return [
        _drop_empty(
            {
                "context_id": f"qualityretry:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(str(summary.get('result_id') or result.result_id))}",
                "packet_type": "quality_retry_feedback",
                "source_node_id": node_id,
                "target_node_id": node_id,
                "edge_id": f"quality_retry_feedback::{node_id}->{node_id}",
                "payload_contract_id": "contract.graph.quality_retry_feedback",
                "packet_contract_id": "contract.graph.quality_retry_feedback",
                "target_context_key": "quality_retry_feedback",
                "target_input_slot": "quality_retry_feedback",
                "delivery_policy": "quality_failure_payload_and_artifact_text",
                "payload": payload,
                "artifact_refs": [{"path": ref} for ref in artifact_refs],
                "memory_refs": [],
                "result_refs": [
                    _drop_empty(
                        {
                            "ref_kind": "node_result",
                            "result_ref": str(summary.get("result_ref") or ""),
                            "result_id": str(summary.get("result_id") or result.result_id),
                            "node_id": node_id,
                            "status": str(summary.get("status") or result.status),
                        }
                    )
                ],
                "receipt_refs": [],
                "visibility": {
                    "source": "graph_loop.result_history.latest_self_quality_failure",
                    "artifact_text_projection": "bounded" if include_artifact_text else "suppressed_by_retry_policy",
                    "authority": "graph_system.self_quality_failure_context.visibility",
                },
                "authority": "graph_system.self_quality_failure_context",
            }
        )
    ]


def _latest_self_quality_failure(
    *,
    services: Any | None,
    state: GraphLoopState,
    node_id: str,
) -> dict[str, Any]:
    for raw_summary in reversed(tuple(dict(state.result_history or {}).get(node_id) or ())):
        if not isinstance(raw_summary, dict):
            continue
        summary = dict(raw_summary)
        result = load_node_result(services, summary) if services is not None else None
        if result is None:
            result = _node_result_from_history_summary(summary)
        if result is None:
            continue
        source_error = dict(result.error or summary.get("error") or {})
        quality_acceptance = dict(dict(result.diagnostics or {}).get("quality_acceptance") or {})
        status = str(summary.get("status") or result.status)
        if status == "blocked" and (
            str(source_error.get("reason") or "") == "quality_gate_failed"
            or quality_acceptance.get("accepted") is False
        ):
            return {"summary": summary, "result": result}
        break
    return {}


def _node_result_from_history_summary(summary: dict[str, Any]) -> Any | None:
    result_id = str(summary.get("result_id") or "")
    graph_run_id = str(summary.get("graph_run_id") or "")
    task_run_id = str(summary.get("task_run_id") or "")
    node_id = str(summary.get("node_id") or "")
    work_order_id = str(summary.get("work_order_id") or "")
    if not result_id or not graph_run_id or not task_run_id or not node_id or not work_order_id:
        return None
    from .models import NodeResultEnvelope

    return NodeResultEnvelope(
        result_id=result_id,
        graph_run_id=graph_run_id,
        task_run_id=task_run_id,
        node_id=node_id,
        work_order_id=work_order_id,
        node_kind=str(summary.get("node_kind") or "agent_execution_node"),
        execution_adapter_kind=str(summary.get("execution_adapter_kind") or "agent_harness"),
        graph_time=dict(summary.get("graph_time") or {}),
        node_attempt=dict(summary.get("node_attempt") or {}),
        execution_trace_binding=dict(summary.get("execution_trace_binding") or {}),
        executor_type=str(summary.get("executor_type") or "agent"),
        status=str(summary.get("status") or "blocked"),
        artifact_refs=tuple(_artifact_ref_values(summary.get("artifact_refs"))),
        handoff_summary=str(summary.get("handoff_summary") or ""),
        error=dict(summary.get("error") or {}),
        created_at=float(summary.get("created_at") or 0.0),
    )


def _loop_iteration_contexts_for_node(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node_id: str,
) -> list[dict[str, Any]]:
    loop_state = dict(state.loop_state or {})
    frames = {
        str(frame_id): dict(frame)
        for frame_id, frame in dict(loop_state.get("frames") or {}).items()
        if isinstance(frame, dict)
    }
    iteration_results = {
        str(frame_id): dict(frame_results)
        for frame_id, frame_results in dict(loop_state.get("iteration_results") or {}).items()
        if isinstance(frame_results, dict)
    }
    contexts: list[dict[str, Any]] = []
    for frame in frames.values():
        frame_id = str(frame.get("frame_id") or frame.get("scope_id") or "").strip()
        scope_id = str(frame.get("scope_id") or frame_id).strip()
        if not frame_id or str(frame.get("exit_node_id") or "").strip() != node_id:
            continue
        frame_results = dict(iteration_results.get(frame_id) or iteration_results.get(scope_id) or {})
        if not frame_results:
            continue
        iteration_entries: list[dict[str, Any]] = []
        aggregate_refs: list[Any] = []
        for iteration_id, raw_node_results in _ordered_iteration_items(frame_results):
            node_entries: list[dict[str, Any]] = []
            for result_node_id, raw_summary in dict(raw_node_results or {}).items():
                if not isinstance(raw_summary, dict):
                    continue
                summary = dict(raw_summary)
                node_entry = _node_result_context_entry(result_node_id=result_node_id, summary=summary)
                artifact_refs = list(node_entry.get("artifact_refs") or [])
                aggregate_refs.extend(artifact_refs)
                node_entries.append(node_entry)
            if node_entries:
                iteration_entries.append(
                    {
                        "iteration_id": str(iteration_id or ""),
                        "node_results": node_entries,
                    }
                )
        artifact_refs = _artifact_ref_values(aggregate_refs)
        contexts.append(
            _drop_empty(
                {
                    "context_id": f"loopctx:{safe_id(state.graph_run_id)}:{safe_id(frame_id)}:{safe_id(node_id)}",
                    "packet_type": "loop_iteration_results",
                    "source_node_id": "__loop__",
                    "target_node_id": node_id,
                    "edge_id": f"loop_iteration_results::{frame_id}->{node_id}",
                    "payload_contract_id": "contract.graph.loop_iteration_results",
                    "packet_contract_id": "contract.graph.loop_iteration_results",
                    "target_context_key": "loop_iteration_results",
                    "target_input_slot": "loop_iteration_results",
                    "delivery_policy": "loop_iteration_artifact_payloads",
                    "payload": {
                        "frame_id": frame_id,
                        "scope_id": scope_id,
                        "frame_status": str(frame.get("status") or ""),
                        "loop_iteration_results": iteration_entries,
                        "artifact_refs": artifact_refs,
                        "artifact_payloads": _artifact_payloads_for_refs(artifact_refs, max_refs=24, max_chars=12000),
                        "authority": "graph_system.loop_iteration_results_payload",
                    },
                    "artifact_refs": [{"path": ref} for ref in artifact_refs],
                    "memory_refs": [],
                    "result_refs": [],
                    "receipt_refs": [],
                    "visibility": {
                        "source": "loop_state.iteration_results",
                        "artifact_text_projection": "bounded",
                        "authority": "graph_system.loop_iteration_context.visibility",
                    },
                    "authority": "graph_system.loop_iteration_context",
                }
            )
        )
    return contexts


def _node_result_context_entry(*, result_node_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    artifact_refs = _artifact_ref_values(summary.get("artifact_refs"))
    return _drop_empty(
        {
            "node_id": str(result_node_id or summary.get("node_id") or ""),
            "status": str(summary.get("status") or ""),
            "result_ref": str(summary.get("result_ref") or ""),
            "artifact_refs": artifact_refs,
            "handoff_summary": str(summary.get("handoff_summary") or "")[:1200],
        }
    )


def _ordered_iteration_items(frame_results: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    items = [
        (str(iteration_id), dict(node_results))
        for iteration_id, node_results in frame_results.items()
        if isinstance(node_results, dict)
    ]
    return sorted(items, key=lambda item: _iteration_sort_key(item[0]))


def _iteration_sort_key(iteration_id: str) -> tuple[int, str]:
    numbers = [int(match) for match in re.findall(r"\d+", str(iteration_id or ""))]
    return (numbers[-1] if numbers else 0, str(iteration_id or ""))


def _artifact_ref_values(refs: Any) -> list[str]:
    normalized = dedupe_artifact_refs([normalize_artifact_ref(ref) for ref in list(refs or [])])
    return [value for value in (artifact_ref_value(ref) for ref in normalized) if value]


def _artifact_payloads_for_refs(refs: list[str], *, max_refs: int, max_chars: int) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for ref in refs[:max_refs]:
        text, truncated = _read_artifact_text(ref, max_chars=max_chars)
        if not text:
            continue
        payloads.append(
            {
                "artifact_ref": ref,
                "content": text,
                "truncated": truncated,
                "max_chars": max_chars,
                "authority": "graph_system.loop_iteration_artifact_text_projection",
            }
        )
    return payloads


def _read_artifact_text(ref: str, *, max_chars: int) -> tuple[str, bool]:
    raw = Path(str(ref or "")).expanduser()
    candidates = [raw] if raw.is_absolute() else [
        Path.cwd() / raw,
        Path.cwd().parent / raw,
        Path(__file__).resolve().parents[3] / raw,
    ]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        try:
            if not resolved.exists() or not resolved.is_file():
                continue
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return text[:max_chars], len(text) > max_chars
    return "", False


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _execution_input_package(input_package: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_package or {})
    return _drop_empty(
        {
            "package_id": str(payload.get("package_id") or ""),
            "authority": str(payload.get("authority") or "graph_system.node_materialization_package"),
            "materializer_authority": str(payload.get("materializer_authority") or ""),
            "node_identity": _execution_node_identity(payload.get("node_identity")),
            "task_contract": _execution_task_contract_from_input_package(payload),
            "agent_binding": _execution_agent_binding_from_input_package(payload),
            "task_environment_id": str(payload.get("task_environment_id") or ""),
            "runtime_scope": _execution_runtime_scope(payload.get("runtime_scope")),
            "execution_boundary": dict(payload.get("execution_boundary") or {}),
            "agent_instruction": str(payload.get("agent_instruction") or ""),
            "initial_inputs": _execution_initial_inputs(payload.get("initial_inputs")),
            "loop_context": _execution_loop_context(payload.get("loop_context")),
            "inbound_context": _execution_inbound_contexts(payload.get("inbound_context")),
        }
    )


def _execution_node_identity(value: Any) -> dict[str, Any]:
    identity = dict(value or {})
    return _drop_empty(
        {
            "node_id": str(identity.get("node_id") or ""),
            "title": str(identity.get("title") or ""),
            "node_type": str(identity.get("node_type") or ""),
            "task_ref": str(identity.get("task_ref") or ""),
        }
    )


def _execution_runtime_scope(value: Any) -> dict[str, Any]:
    scope = dict(value or {})
    allowed = {
        "project_id",
        "graph_task_instance_id",
        "workspace_view",
        "artifact_root",
        "project_path",
        "source_project_id",
        "scope_id",
        "graph_binding_mode",
        "memory_namespace_id",
        *context_provider_runtime_scope_keys(),
    }
    return _drop_empty({key: scope.get(key) for key in allowed})


def _execution_runtime_policy(value: Any) -> dict[str, Any]:
    policy = dict(value or {})
    return _drop_empty(
        {
            "source": str(policy.get("source") or ""),
            "node_id": str(policy.get("node_id") or ""),
            "context_policy": dict(policy.get("context_policy") or {}),
            "prompt_wiring_overrides": dict(policy.get("prompt_wiring_overrides") or {}),
            "operation_authorization_projection": dict(policy.get("operation_authorization_projection") or {}),
            "prompt_policy": dict(policy.get("prompt_policy") or {}),
            "subagent_policy": dict(policy.get("subagent_policy") or {}),
            "control_capabilities": dict(policy.get("control_capabilities") or {}),
        }
    )


def _execution_artifact_view_request(value: Any) -> dict[str, Any]:
    view = dict(value or {})
    graph_policy = dict(view.get("graph_artifact_policy") or {})
    return _drop_empty(
        {
            "artifact_space_ref": str(view.get("artifact_space_ref") or ""),
            "node_artifact_policy": dict(view.get("node_artifact_policy") or {}),
            "graph_artifact_policy": _drop_empty(
                {
                    "context_edges": _memory_protocol_refs(graph_policy.get("context_edges")),
                    "context_edge_count": graph_policy.get("context_edge_count"),
                    "total_context_edge_count": graph_policy.get("total_context_edge_count"),
                    "authority": str(graph_policy.get("authority") or ""),
                }
            ),
        }
    )


def _execution_expected_result_contract(value: Any) -> dict[str, Any]:
    contract = dict(value or {})
    bindings = dict(contract.get("contract_bindings") or {})
    slim_bindings = {
        key: dict(bindings.get(key) or {})
        for key in ("output", "artifact", "acceptance")
        if isinstance(bindings.get(key), dict) and dict(bindings.get(key) or {})
    }
    return _drop_empty(
        {
            "node_contract_id": str(contract.get("node_contract_id") or ""),
            "input_contract_id": str(contract.get("input_contract_id") or ""),
            "output_contract_id": str(contract.get("output_contract_id") or ""),
            "contract_bindings": slim_bindings,
            "required_sections": [str(item) for item in list(contract.get("required_sections") or []) if str(item)],
            "constraints": [str(item) for item in list(contract.get("constraints") or []) if str(item)],
            "authority": str(contract.get("authority") or "graph_system.execution_expected_result_contract"),
        }
    )


def _execution_inbound_contexts(value: Any) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for item in list(value or [])[:16]:
        if not isinstance(item, dict):
            continue
        payload = dict(item.get("payload") or {})
        contexts.append(
            _drop_empty(
                {
                    "authority": str(item.get("authority") or "graph_system.inbound_context"),
                    "context_id": str(item.get("context_id") or ""),
                    "packet_id": str(item.get("packet_id") or ""),
                    "packet_ref": str(item.get("packet_ref") or ""),
                    "packet_type": str(item.get("packet_type") or ""),
                    "source_node_id": str(item.get("source_node_id") or ""),
                    "target_node_id": str(item.get("target_node_id") or ""),
                    "source_edge_id": str(item.get("source_edge_id") or ""),
                    "edge_id": str(item.get("edge_id") or item.get("source_edge_id") or ""),
                    "payload_contract_id": str(item.get("payload_contract_id") or ""),
                    "packet_contract_id": str(item.get("packet_contract_id") or item.get("payload_contract_id") or ""),
                    "target_context_key": str(item.get("target_context_key") or ""),
                    "target_input_slot": str(item.get("target_input_slot") or ""),
                    "delivery_policy": str(item.get("delivery_policy") or ""),
                    "payload": _execution_context_payload(payload),
                    "artifact_refs": _artifact_ref_summaries(item.get("artifact_refs")),
                    "memory_refs": _bounded_dicts(item.get("memory_refs"), limit=12),
                    "result_refs": _bounded_dicts(item.get("result_refs"), limit=8),
                    "receipt_refs": _bounded_dicts(item.get("receipt_refs"), limit=12),
                    "visibility": dict(item.get("visibility") or {}),
                    "lineage": _execution_lineage(item.get("lineage")),
                }
            )
        )
    return contexts


def _execution_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(payload.get("initial_inputs"), dict):
        result["initial_inputs"] = _execution_initial_inputs(
            payload.get("initial_inputs"),
            include_user_creative_seed=str(payload.get("authority") or "") == "graph_system.initial_input_payload",
        )
    for key in ("graph_id", "project_id", "title"):
        if payload.get(key):
            result[key] = str(payload.get(key) or "")
    if payload.get("handoff_summary"):
        result["handoff_summary"] = str(payload.get("handoff_summary") or "")[:1200]
    if isinstance(payload.get("source_error"), dict):
        result["source_error"] = _truncate_value(dict(payload.get("source_error") or {}), max_chars=4000)
    if isinstance(payload.get("quality_acceptance"), dict):
        result["quality_acceptance"] = _truncate_value(dict(payload.get("quality_acceptance") or {}), max_chars=4000)
    if payload.get("quality_issue_summary"):
        result["quality_issue_summary"] = str(payload.get("quality_issue_summary") or "")[:4000]
    if isinstance(payload.get("issues"), list):
        result["issues"] = [str(item) for item in list(payload.get("issues") or [])[:32] if str(item)]
    if isinstance(payload.get("artifact_refs"), list):
        result["artifact_refs"] = _artifact_ref_values(payload.get("artifact_refs"))[:16]
    if isinstance(payload.get("receipt_refs"), list):
        result["receipt_refs"] = _bounded_dicts(payload.get("receipt_refs"), limit=12)
    if isinstance(payload.get("bounded_outputs"), dict):
        result["bounded_outputs"] = _truncate_value(dict(payload.get("bounded_outputs") or {}), max_chars=8000)
    if isinstance(payload.get("loop_iteration_results"), list):
        result["loop_iteration_results"] = _truncate_value(list(payload.get("loop_iteration_results") or [])[:10], max_chars=6000)
    if isinstance(payload.get("artifact_payloads"), list):
        payload_limit = 6 if isinstance(payload.get("loop_iteration_results"), list) else 2
        result["artifact_payloads"] = [
            _execution_artifact_payload(dict(item))
            for item in list(payload.get("artifact_payloads") or [])[:payload_limit]
            if isinstance(item, dict)
        ]
    if payload.get("authority"):
        result["authority"] = str(payload.get("authority") or "")
    return _drop_empty(result)


def _execution_artifact_payload(item: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "artifact_ref": str(item.get("artifact_ref") or item.get("path") or item.get("absolute_path") or ""),
            "content": str(item.get("content") or item.get("text") or "")[:16000],
            "truncated": bool(item.get("truncated") is True),
            "max_chars": min(_safe_int(item.get("max_chars"), 16000), 16000),
            "authority": str(item.get("authority") or "graph_system.flow_packet.artifact_text_projection"),
        }
    )


def _execution_memory_snapshots(value: Any) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for item in _selected_execution_memory_snapshots(value):
        if not isinstance(item, dict):
            continue
        snapshot = dict(item)
        records = snapshot.get("records") or snapshot.get("items") or snapshot.get("memories") or []
        snapshots.append(
            _drop_empty(
                {
                    "snapshot_id": str(snapshot.get("snapshot_id") or ""),
                    "graph_id": str(snapshot.get("graph_id") or ""),
                    "node_id": str(snapshot.get("node_id") or ""),
                    "edge_id": str(snapshot.get("edge_id") or ""),
                    "logical_repository_id": str(snapshot.get("logical_repository_id") or snapshot.get("repository_id") or ""),
                    "collection_id": str(snapshot.get("collection_id") or snapshot.get("collection") or ""),
                    "record_count": snapshot.get("record_count"),
                    "records": [_execution_memory_record(dict(record)) for record in list(records)[:4] if isinstance(record, dict)],
                    "read_log_id": str(snapshot.get("read_log_id") or ""),
                    "model_visible_label": str(snapshot.get("model_visible_label") or ""),
                    "usage_instruction": str(snapshot.get("usage_instruction") or "")[:1200],
                    "summary": str(snapshot.get("summary") or "")[:2000],
                    "authority": str(snapshot.get("authority") or "graph_system.resolved_memory_snapshot"),
                }
            )
        )
    return snapshots


def _selected_execution_memory_snapshots(value: Any) -> list[dict[str, Any]]:
    items = [dict(item) for item in list(value or []) if isinstance(item, dict)]
    if len(items) <= 10:
        return items
    selected = [*items[:6], *items[-4:]]
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in selected:
        key = str(item.get("snapshot_id") or item.get("collection_id") or item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _execution_memory_record(record: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "record_key": str(record.get("record_key") or ""),
            "record_kind": str(record.get("record_kind") or ""),
            "canonical_text": str(record.get("canonical_text") or record.get("content") or record.get("text") or "")[:1800],
            "summary": str(record.get("summary") or "")[:1000],
            "model_visible_label": str(record.get("model_visible_label") or ""),
            "usage_instruction": str(record.get("usage_instruction") or "")[:1000],
            "authority": str(record.get("authority") or "formal_memory.resolved_record.model_visible"),
        }
    )


def _execution_loop_context(value: Any) -> dict[str, Any]:
    loop_context = dict(value or {})
    return _drop_empty(
        {
            "authority": str(loop_context.get("authority") or "graph_system.loop_engine"),
            "scope_id": str(loop_context.get("scope_id") or ""),
            "current_scope_id": str(loop_context.get("current_scope_id") or ""),
            "current_frame_id": str(loop_context.get("current_frame_id") or ""),
            "iteration_index": loop_context.get("iteration_index"),
            "iteration_id": str(loop_context.get("iteration_id") or ""),
            "cursor_key": str(loop_context.get("cursor_key") or ""),
            "cursor_value": loop_context.get("cursor_value"),
            "active_frame": _execution_loop_frame(loop_context.get("active_frame")),
            "current_frame": _execution_loop_frame(loop_context.get("current_frame")),
            "result_history_counts": dict(loop_context.get("result_history_counts") or {}),
            "contract_inputs": _loop_contract_inputs(loop_context.get("contract_inputs")),
        }
    )


def _execution_loop_frame(value: Any) -> dict[str, Any]:
    frame = dict(value or {})
    return _drop_empty(
        {
            "frame_id": str(frame.get("frame_id") or ""),
            "scope_id": str(frame.get("scope_id") or ""),
            "parent_scope_id": str(frame.get("parent_scope_id") or ""),
            "status": str(frame.get("status") or ""),
            "kind": str(frame.get("kind") or ""),
            "algorithm_kind": str(frame.get("algorithm_kind") or frame.get("kind") or ""),
            "unit_kind": str(frame.get("unit_kind") or ""),
            "entry_node_id": str(frame.get("entry_node_id") or ""),
            "router_node_id": str(frame.get("router_node_id") or ""),
            "exit_node_id": str(frame.get("exit_node_id") or ""),
            "cursor_key": str(frame.get("cursor_key") or ""),
            "start_key": str(frame.get("start_key") or ""),
            "end_key": str(frame.get("end_key") or ""),
            "step": frame.get("step"),
            "iteration_index_key": str(frame.get("iteration_index_key") or ""),
            "iteration_identity_template": str(frame.get("iteration_identity_template") or ""),
            "unit_kind": str(frame.get("unit_kind") or ""),
            "iteration_size_key": str(frame.get("iteration_size_key") or ""),
            "iteration_index": frame.get("iteration_index"),
            "cursor": frame.get("cursor"),
            "start": frame.get("start"),
            "end": frame.get("end"),
            "active_iteration_id": str(frame.get("active_iteration_id") or ""),
            "initial_inputs": _loop_contract_inputs(frame.get("initial_inputs")),
            "tree_reduce": _execution_tree_reduce(frame.get("tree_reduce")),
            "aggregate_policy": dict(frame.get("aggregate_policy") or {}),
            "authority": str(frame.get("authority") or ""),
        }
    )


def _execution_tree_reduce(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    if not payload:
        return {}
    return _drop_empty(
        {
            "physical_authority": str(payload.get("physical_authority") or ""),
            "semantic_authority": str(payload.get("semantic_authority") or ""),
            "frame_status": str(payload.get("frame_status") or ""),
            "depth": payload.get("depth"),
            "folder_node_id": str(payload.get("folder_node_id") or ""),
            "folder_stable_ref": str(payload.get("folder_stable_ref") or ""),
            "manifest_ref": str(payload.get("manifest_ref") or ""),
            "direct_file_count": payload.get("direct_file_count"),
            "child_folder_count": payload.get("child_folder_count"),
            "child_return_count": payload.get("child_return_count"),
            "aggregate_policy": str(payload.get("aggregate_policy") or ""),
            "authority": "graph_system.execution_tree_reduce_projection",
        }
    )


def _execution_initial_inputs(value: Any, *, include_user_creative_seed: bool = False) -> dict[str, Any]:
    payload = dict(value or {})
    allowed_keys = {
        *set(_loop_contract_inputs(payload).keys()),
        "graph_task_instance_id",
        *context_provider_initial_input_keys(),
        "project_path",
        "project_title",
        "quality_gate_feedback",
        "source_project_id",
        "source",
        "title",
        "workspace_view",
    }
    result: dict[str, Any] = {}
    for key in allowed_keys:
        value = payload.get(key)
        if value in ("", None, [], {}):
            continue
        if key.endswith("_outline"):
            result[key] = str(value)[:6000]
        elif key == "quality_gate_feedback" and isinstance(value, dict):
            result[key] = _truncate_value(value, max_chars=6000)
        else:
            result[key] = value
    if include_user_creative_seed and payload.get("user_creative_seed"):
        result["user_creative_seed"] = str(payload.get("user_creative_seed") or "")[:12000]
        result["user_input_kind"] = str(payload.get("user_input_kind") or "raw_creative_paragraph")
    return _drop_empty(result)


def _loop_contract_inputs(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    allowed_keys = {
        "project_id",
        "artifact_root",
        "project_path",
        "source_project_id",
        "revision_execution_range",
        "round_index",
        *context_provider_loop_contract_input_keys(),
    }
    return {key: payload.get(key) for key in allowed_keys if payload.get(key) not in ("", None, [], {})}


def _initial_inputs_with_loop_cursor(
    *,
    initial_inputs: dict[str, Any],
    loop_context: dict[str, Any],
) -> dict[str, Any]:
    inputs = dict(initial_inputs or {})
    active_frame = dict(dict(loop_context or {}).get("active_frame") or {})
    cursor_key = str(active_frame.get("cursor_key") or dict(loop_context or {}).get("cursor_key") or "").strip()
    cursor_value = active_frame.get("cursor")
    if cursor_value in ("", None):
        cursor_value = dict(loop_context or {}).get("cursor_value")
    if cursor_key and cursor_value not in ("", None):
        inputs[cursor_key] = cursor_value
    for frame_value_key, input_key_name in (("start", "start_key"), ("end", "end_key")):
        input_key = str(active_frame.get(input_key_name) or "").strip()
        frame_value = active_frame.get(frame_value_key)
        if input_key and frame_value not in ("", None):
            inputs[input_key] = frame_value
    return inputs


def _loop_context_with_materialized_inputs(
    *,
    loop_context: dict[str, Any],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    context = dict(loop_context or {})
    inputs = dict(initial_inputs or {})
    active_frame = dict(context.get("active_frame") or {})
    if active_frame:
        values = {
            **dict(active_frame.get("values") or {}),
            **inputs,
        }
        cursor_key = str(active_frame.get("cursor_key") or context.get("cursor_key") or "").strip()
        if cursor_key and active_frame.get("cursor") not in ("", None):
            values[cursor_key] = active_frame.get("cursor")
        active_frame["values"] = values
        context["active_frame"] = active_frame
        frame_id = str(active_frame.get("frame_id") or active_frame.get("scope_id") or "").strip()
        active_frames = []
        replaced = False
        for raw in list(context.get("active_frames") or []):
            frame = dict(raw) if isinstance(raw, dict) else {}
            if frame_id and str(frame.get("frame_id") or frame.get("scope_id") or "") == frame_id:
                frame["cursor_value"] = active_frame.get("cursor")
                frame["iteration_id"] = str(active_frame.get("active_iteration_id") or frame.get("iteration_id") or "")
                replaced = True
            active_frames.append(frame)
        if active_frames:
            context["active_frames"] = active_frames
        elif not replaced:
            context["active_frames"] = []
    context["contract_inputs"] = inputs
    return context


def _loop_variables(loop_context: dict[str, Any]) -> dict[str, Any]:
    active_frame = dict(dict(loop_context or {}).get("active_frame") or {})
    variables = dict(active_frame.get("variables") or {})
    payload = {
        **_loop_contract_inputs(dict(loop_context or {}).get("contract_inputs")),
        **_loop_contract_inputs(active_frame.get("initial_inputs")),
        **_loop_contract_inputs(active_frame.get("values")),
        **_loop_contract_inputs(active_frame.get("state")),
        **_loop_contract_inputs(variables),
    }
    cursor_key = str(active_frame.get("cursor_key") or dict(loop_context or {}).get("cursor_key") or "")
    if cursor_key and active_frame.get("cursor") not in ("", None):
        payload[cursor_key] = active_frame.get("cursor")
    for key in ("iteration_index", "active_iteration_id", "start", "end", "cursor"):
        if active_frame.get(key) not in ("", None):
            payload[key] = active_frame.get(key)
    return _truncate_value(_drop_empty(payload), max_chars=4000)


def _loop_dynamic_bindings(loop_context: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(dict(loop_context or {}).get("node_loop") or {}).get("bindings") or {})


def _memory_protocol_refs(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(value or [])[:24]:
        if not isinstance(item, dict):
            continue
        protocol = dict(item)
        selector = dict(protocol.get("selector") or {})
        refs.append(
            _drop_empty(
                {
                    "edge_id": str(protocol.get("edge_id") or ""),
                    "edge_type": str(protocol.get("edge_type") or ""),
                    "source_node_id": str(protocol.get("source_node_id") or ""),
                    "target_node_id": str(protocol.get("target_node_id") or ""),
                    "semantic_role": str(protocol.get("semantic_role") or ""),
                    "scheduler_role": str(protocol.get("scheduler_role") or ""),
                    "repository": str(protocol.get("repository") or protocol.get("repository_id") or ""),
                    "repository_id": str(protocol.get("repository_id") or protocol.get("repository") or ""),
                    "collection": str(protocol.get("collection") or protocol.get("collection_id") or selector.get("collection") or ""),
                    "collection_id": str(protocol.get("collection_id") or protocol.get("collection") or selector.get("collection") or ""),
                    "record_key": str(protocol.get("record_key") or selector.get("record_key") or ""),
                    "record_kind": str(protocol.get("record_kind") or selector.get("record_kind") or ""),
                    "record_keys": [str(value) for value in list(protocol.get("record_keys") or selector.get("record_keys") or []) if str(value)],
                    "record_kinds": [str(value) for value in list(protocol.get("record_kinds") or selector.get("record_kinds") or []) if str(value)],
                    "version_selector": str(protocol.get("version_selector") or selector.get("version_selector") or ""),
                    "on_missing": str(protocol.get("on_missing") or selector.get("on_missing") or ""),
                    "model_visible_label": str(protocol.get("model_visible_label") or ""),
                    "usage_instruction": str(protocol.get("usage_instruction") or "")[:1200],
                    "authority": str(protocol.get("authority") or ""),
                }
            )
        )
    return refs


def _artifact_ref_summaries(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for ref in _artifact_ref_values(value)[:16]:
        result.append({"ref_kind": "artifact", "artifact_ref": ref})
    return result


def _execution_lineage(value: Any) -> dict[str, Any]:
    lineage = dict(value or {})
    return _drop_empty(
        {
            "source_authority": str(lineage.get("source_authority") or ""),
            "graph_config_id": str(lineage.get("graph_config_id") or ""),
            "result_id": str(lineage.get("result_id") or ""),
            "result_ref": str(lineage.get("result_ref") or ""),
            "work_order_id": str(lineage.get("work_order_id") or ""),
            "edge_id": str(lineage.get("edge_id") or ""),
            "source_node_id": str(lineage.get("source_node_id") or ""),
            "target_node_id": str(lineage.get("target_node_id") or ""),
        }
    )


def _environment_lock_ref(value: Any) -> dict[str, Any]:
    lock = dict(value or {})
    return _drop_empty(
        {
            "task_environment_id": str(lock.get("task_environment_id") or ""),
            "environment_id": str(lock.get("environment_id") or ""),
            "source": str(lock.get("source") or ""),
            "locked": bool(lock.get("locked") is True),
            "authority": str(lock.get("authority") or ""),
        }
    )


def _bounded_dicts(value: Any, *, limit: int) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or [])[:limit] if isinstance(item, dict)]


def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slot_inbound_contexts(
    *,
    graph_config: ExecutableGraphConfig,
    state: GraphLoopState,
    node_id: str,
    input_package: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contexts = [dict(item) for item in inbound_context if isinstance(item, dict)]
    initial_inputs = dict(input_package.get("initial_inputs") or {})
    if not initial_inputs or not _is_graph_start_node(graph_config, node_id):
        return contexts
    if any(str(item.get("context_id") or "") == "graph_initial_input" for item in contexts):
        return contexts
    contexts.insert(
        0,
        {
            "context_id": "graph_initial_input",
            "packet_type": "graph_initial_input",
            "source_node_id": "__graph_input__",
            "target_node_id": node_id,
            "edge_id": f"graph_input::{node_id}",
            "payload_contract_id": "contract.graph.initial_inputs",
            "packet_contract_id": "contract.graph.initial_inputs",
            "target_context_key": "用户原始创意段落",
            "target_input_slot": "user_creative_seed",
            "delivery_policy": "contract_payload",
            "payload": {
                "initial_inputs": initial_inputs,
                "graph_id": graph_config.graph_id,
                "project_id": str(initial_inputs.get("project_id") or ""),
                "authority": "graph_system.initial_input_payload",
            },
            "artifact_refs": [],
            "memory_refs": [],
            "result_refs": [],
            "authority": "graph_system.initial_input_context",
        },
    )
    return contexts


def _is_graph_start_node(graph_config: ExecutableGraphConfig, node_id: str) -> bool:
    start_node_ids = {
        str(item)
        for item in list(dict(graph_config.control or {}).get("start_node_ids") or [])
        if str(item)
    }
    return node_id in start_node_ids


def _dispatch_metadata(
    *,
    initial_inputs: dict[str, Any],
    loop_context: dict[str, Any],
    dispatch_seq: int,
    graph_clock_seq: int,
) -> dict[str, Any]:
    node_dispatch_seq = max(1, int(dispatch_seq or 1))
    round_index = _explicit_round_index(initial_inputs)
    if round_index <= 0 and _loop_frame_has_value(loop_context, "round_index"):
        active_frame = dict(dict(loop_context or {}).get("active_frame") or {})
        frame_values = dict(active_frame.get("values") or active_frame.get("state") or active_frame)
        round_index = _explicit_round_index(frame_values)
    if round_index <= 0:
        round_index = node_dispatch_seq
    return {
        "node_dispatch_seq": node_dispatch_seq,
        "node_dispatch_count": node_dispatch_seq,
        "dispatch_seq": node_dispatch_seq,
        "graph_clock_seq": max(1, int(graph_clock_seq or 1)),
        "round_index": round_index,
        "authority": "graph_system.context_materializer.dispatch_metadata",
    }


def _loop_frame_has_value(loop_context: dict[str, Any], key: str) -> bool:
    active_frame = dict(dict(loop_context or {}).get("active_frame") or {})
    frame_values = dict(active_frame.get("values") or active_frame.get("state") or active_frame)
    return key in frame_values and str(frame_values.get(key) or "").strip() != ""


def _dispatch_round_index(*, input_package: dict[str, Any], dispatch_seq: int) -> int:
    initial_inputs = dict(dict(input_package or {}).get("initial_inputs") or {})
    dispatch_metadata = dict(dict(input_package or {}).get("dispatch_metadata") or {})
    metadata_round_index = _explicit_round_index(dispatch_metadata)
    if metadata_round_index > 0:
        return metadata_round_index
    return_index = _explicit_round_index(initial_inputs)
    return return_index if return_index > 0 else max(1, int(dispatch_seq or 1))


def _explicit_round_index(payload: dict[str, Any]) -> int:
    try:
        value = int(dict(payload or {}).get("round_index"))
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else 0


def _edge_packet_entries(edge_state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in list(edge_state.get("packet_refs") or []):
        if isinstance(item, dict):
            entry = dict(item)
        else:
            entry = {"packet_ref": str(item or "")}
        if str(entry.get("packet_ref") or ""):
            entries.append(entry)
    latest_ref = str(edge_state.get("latest_packet_ref") or "")
    if latest_ref and all(str(item.get("packet_ref") or "") != latest_ref for item in entries):
        entries.append({"packet_ref": latest_ref, "packet_id": str(edge_state.get("latest_packet_id") or "")})
    return entries


def _execution_task_contract_from_input_package(input_package: dict[str, Any]) -> dict[str, Any]:
    task_contract = dict(input_package.get("task_contract") or {})
    output_contract = dict(input_package.get("output_contract") or {})
    bindings = dict(output_contract.get("contract_bindings") or {})
    return _drop_empty(
        {
            "contract_id": str(task_contract.get("contract_id") or output_contract.get("node_contract_id") or ""),
            "node_id": str(task_contract.get("node_id") or ""),
            "node_kind": str(task_contract.get("node_kind") or ""),
            "node_class": str(task_contract.get("node_class") or ""),
            "node_identity": dict(input_package.get("node_identity") or {}),
            "prompt_contract": dict(task_contract.get("prompt_contract") or input_package.get("prompt_contract") or {}),
            "input_contract": dict(task_contract.get("input_contract") or input_package.get("input_contract") or {}),
            "output_contract": dict(task_contract.get("output_contract") or {}),
            "acceptance_policy": dict(bindings.get("acceptance") or {}),
            "contract_bindings": _drop_empty(
                {
                    "output": dict(bindings.get("output") or {}),
                    "artifact": dict(bindings.get("artifact") or {}),
                    "acceptance": dict(bindings.get("acceptance") or {}),
                    "execution": dict(bindings.get("execution") or {}),
                }
            ),
            "artifact_contract": dict(task_contract.get("artifact_contract") or {}),
            "state_policy": dict(task_contract.get("state_policy") or {}),
            "trace_policy": dict(task_contract.get("trace_policy") or {}),
            "authority": "graph_system.task_contract_execution_projection",
        }
    )


def _execution_agent_binding_from_input_package(input_package: dict[str, Any]) -> dict[str, Any]:
    binding = dict(input_package.get("agent_binding") or {})
    runtime_profile = dict(input_package.get("runtime_profile") or {})
    runtime_policy = dict(binding.get("runtime_policy") or runtime_profile.get("runtime_policy") or {})
    return _drop_empty(
        {
            "binding_id": str(binding.get("binding_id") or ""),
            "binding_mode": str(binding.get("binding_mode") or ""),
            "node_id": str(binding.get("node_id") or ""),
            "node_kind": str(binding.get("node_kind") or ""),
            "node_class": str(binding.get("node_class") or ""),
            "executor_type": str(binding.get("executor_type") or ""),
            "executor_policy": dict(binding.get("executor_policy") or {}),
            "agent_id": str(binding.get("agent_id") or ""),
            "agent_profile_id": str(binding.get("agent_profile_id") or ""),
            "agent_group_id": str(binding.get("agent_group_id") or ""),
            "agent_selection_policy": str(binding.get("agent_selection_policy") or ""),
            "model_requirement": dict(binding.get("model_requirement") or {}),
            "reasoning_policy": dict(runtime_profile.get("reasoning_policy") or {}),
            "completion_profile": dict(runtime_profile.get("completion_profile") or {}),
            "runtime_policy": _execution_runtime_policy(runtime_policy),
            "permission_ceiling": dict(binding.get("permission_ceiling") or {}),
            "tool_contract": dict(binding.get("tool_contract") or {}),
            "tool_policy": dict(binding.get("tool_policy") or {}),
            "environment_lock": _environment_lock_ref(binding.get("environment_lock") or runtime_profile.get("node_environment_lock")),
            "project_binding": dict(binding.get("project_binding") or runtime_profile.get("graph_project_binding") or {}),
            "session_policy": dict(binding.get("session_policy") or runtime_profile.get("node_session_policy") or {}),
            "context_config": dict(binding.get("context_config") or {}),
            "authority": "graph_system.agent_binding_execution_projection",
        }
    )


def _inbound_flow_packets(inbound_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "packet_id": str(item.get("packet_id") or ""),
            "packet_ref": str(item.get("packet_ref") or ""),
            "packet_type": str(item.get("packet_type") or ""),
            "source_node_id": str(item.get("source_node_id") or ""),
            "target_node_id": str(item.get("target_node_id") or ""),
            "edge_id": str(item.get("edge_id") or item.get("source_edge_id") or ""),
            "payload_contract_id": str(item.get("payload_contract_id") or item.get("packet_contract_id") or ""),
            "packet_contract_id": str(item.get("packet_contract_id") or item.get("payload_contract_id") or ""),
            "target_context_key": str(item.get("target_context_key") or ""),
            "target_input_slot": str(item.get("target_input_slot") or ""),
            "delivery_policy": str(item.get("delivery_policy") or ""),
            "visibility": dict(item.get("visibility") or {}),
            "lineage": dict(item.get("lineage") or {}),
            "authority": "graph_system.inbound_flow_packet_ref",
        }
        for item in inbound_context
        if isinstance(item, dict)
    ]


def _inbound_packet_refs(inbound_context: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in inbound_context:
        if not isinstance(item, dict):
            continue
        packet_ref = str(item.get("packet_ref") or "")
        packet_id = str(item.get("packet_id") or "")
        if not packet_ref and not packet_id:
            continue
        refs.append(
            {
                "packet_id": packet_id,
                "packet_ref": packet_ref,
                "edge_id": str(item.get("edge_id") or item.get("source_edge_id") or ""),
            }
        )
    return refs


def _outbound_edge_policy(*, graph_config: ExecutableGraphConfig, edge: dict[str, Any]) -> dict[str, Any]:
    edge_contract = edge_contract_for_edge(graph_config, edge)
    packet = dict(edge_contract.get("packet") or {})
    reliability = dict(edge_contract.get("reliability") or {})
    protocol = dict(edge_contract.get("protocol") or {})
    scheduler = dict(edge_contract.get("scheduler") or {})
    trace = dict(edge_contract.get("trace") or {})
    packet_visibility = dict(packet.get("visibility") or {})
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "edge_contract_id": str(edge_contract.get("contract_id") or ""),
        "protocol_kind": str(protocol.get("kind") or ""),
        "interaction_pattern": str(protocol.get("interaction_pattern") or ""),
        "produces_flow_packet": bool(protocol.get("produces_flow_packet", trace.get("persist_packet", False))),
        "scheduler_role": str(scheduler.get("scheduler_role") or ""),
        "semantic_role": str(scheduler.get("semantic_role") or ""),
        "payload_contract_id": str(packet.get("payload_contract_id") or ""),
        "packet_contract_id": str(packet.get("packet_contract_id") or packet.get("payload_contract_id") or ""),
        "source_output_selector": str(packet.get("source_output_selector") or ""),
        "target_context_key": str(packet.get("target_context_key") or ""),
        "target_input_slot": str(packet.get("target_input_slot") or ""),
        "projection_policy": dict(packet_visibility.get("context_filter_policy") or {}),
        "visibility_policy": packet_visibility,
        "receipt_policy": {
            "ack_required": bool(reliability.get("ack_required", True)),
            "ack_policy": str(reliability.get("ack_policy") or ""),
        },
        "trace_policy": {
            "persist_packet": bool(trace.get("persist_packet", False)),
            "checkpoint_policy": str(trace.get("checkpoint_policy") or ""),
        },
        "authority": "graph_system.outbound_edge_policy_projection",
    }


def _memory_namespace_id(*, graph_config: ExecutableGraphConfig, state: GraphLoopState) -> str:
    runtime_scope = dict(dict(state.diagnostics or {}).get("runtime_scope") or {})
    runtime_namespace = dict(runtime_scope.get("graph_task_memory_namespace") or {})
    runtime_namespace_id = str(runtime_namespace.get("namespace_id") or runtime_scope.get("memory_namespace_id") or "").strip()
    if runtime_namespace_id:
        return runtime_namespace_id
    memory_scope = dict(graph_config.memory or {}).get("graph_task_memory_namespace")
    if isinstance(memory_scope, dict):
        explicit = str(memory_scope.get("namespace_id") or "").strip()
        if explicit and bool(memory_scope.get("shared") is True):
            return explicit
    return f"graphmem:{safe_id(state.graph_run_id)}"


def _prompt_contract(node: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(node.get("prompt") or {})
    return {
        "role_prompt": str(prompt.get("role_prompt") or "").strip(),
        "task_instruction": str(prompt.get("task_instruction") or "").strip(),
        "output_instruction": str(prompt.get("output_instruction") or "").strip(),
        "language_policy": dict(prompt.get("language_policy") or {}),
        "forbidden_behavior": list(prompt.get("forbidden_behavior") or []),
        "definition_of_done": list(prompt.get("definition_of_done") or []),
    }


def _agent_instruction(*, prompt_contract: dict[str, Any], node: dict[str, Any]) -> str:
    parts = [
        str(prompt_contract.get("role_prompt") or "").strip(),
        str(prompt_contract.get("task_instruction") or "").strip(),
        str(prompt_contract.get("output_instruction") or "").strip(),
    ]
    forbidden = [str(item).strip() for item in list(prompt_contract.get("forbidden_behavior") or []) if str(item).strip()]
    done = [str(item).strip() for item in list(prompt_contract.get("definition_of_done") or []) if str(item).strip()]
    if forbidden:
        parts.append("禁止事项：\n" + "\n".join(f"- {item}" for item in forbidden))
    language_policy = dict(prompt_contract.get("language_policy") or {})
    if language_policy:
        parts.append("语言要求：\n" + "\n".join(f"- {key}: {_prompt_policy_text(value)}" for key, value in language_policy.items() if value not in ("", None, [], {})))
    if done:
        parts.append("完成标准：\n" + "\n".join(f"- {item}" for item in done))
    message = "\n".join(item for item in parts if item).strip()
    if message:
        return message
    return f"请根据你的角色职责完成当前节点任务：{str(node.get('title') or node.get('node_id') or '未命名节点')}。"


def _prompt_policy_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return "；".join(f"{key}={_prompt_policy_text(item)}" for key, item in value.items() if item not in ("", None, [], {}))
    return str(value)


def _memory_view_request(*, graph_config: ExecutableGraphConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(task_environment_id or graph_config.task_environment_id or ""),
        "environment_memory_space": dict(environment.get("memory_space") or {}),
        "memory_space_ref": _memory_space_ref(graph_config),
        "node_memory_policy": dict(node.get("memory") or {}),
        "graph_memory_policy": _node_memory_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _artifact_view_request(*, graph_config: ExecutableGraphConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(task_environment_id or graph_config.task_environment_id or ""),
        "environment_artifact_policy": dict(environment.get("artifact_policy") or {}),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "node_artifact_policy": dict(node.get("artifacts") or {}),
        "graph_artifact_policy": _node_artifact_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _file_view_request(*, graph_config: ExecutableGraphConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(task_environment_id or graph_config.task_environment_id or ""),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "file_management": dict(environment.get("file_management") or {}),
        "file_access_tables": list(environment.get("file_access_tables") or []),
        "file_access_table_refs": _file_access_table_refs(graph_config),
        "node_file_policy": dict(node.get("files") or {}),
        "graph_resource_policy": _resource_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _issue_view_request(*, graph_config: ExecutableGraphConfig, node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or "")
    return {
        "issue_ledgers": [
            _resource_node_summary(dict(item), node_id=node_id)
            for item in list(dict(graph_config.resources or {}).get("resource_nodes") or [])
            if str(dict(item).get("resource_type") or dict(item).get("node_type") or "") == "issue_ledger"
            and _resource_visible_to_node(dict(item), node_id=node_id)
        ]
    }


def _output_artifact_targets(input_package: dict[str, Any]) -> list[dict[str, Any]]:
    output_contract = dict(input_package.get("output_contract") or {})
    bindings = dict(output_contract.get("contract_bindings") or {})
    output_binding = dict(bindings.get("output") or {})
    artifact_binding = dict(bindings.get("artifact") or {})
    artifact_policy = dict(artifact_binding.get("artifact_policy") or artifact_binding)
    artifact_view = dict(input_package.get("artifact_view") or {})
    node_artifact_policy = dict(artifact_view.get("node_artifact_policy") or {})
    candidates = [
        dict(output_binding.get("artifact_materialization_policy") or {}).get("artifact_targets"),
        output_binding.get("artifact_targets"),
        artifact_binding.get("artifact_targets"),
        artifact_policy.get("artifact_targets"),
        artifact_policy.get("artifacts"),
        node_artifact_policy.get("artifact_targets"),
        node_artifact_policy.get("artifacts"),
    ]
    for value in candidates:
        targets = [dict(item) for item in list(value or []) if isinstance(item, dict)]
        if targets:
            return targets
    return []


def _output_environment_projection(graph_config: ExecutableGraphConfig, *, input_package: dict[str, Any] | None = None) -> dict[str, Any]:
    agent_binding = dict(dict(input_package or {}).get("agent_binding") or {})
    environment_lock = dict(agent_binding.get("environment_lock") or {})
    return _drop_empty(
        {
            "task_environment_id": str(
                environment_lock.get("task_environment_id")
                or dict(input_package or {}).get("task_environment_id")
                or ""
            ),
            "node_environment_lock": environment_lock,
            "authority": "graph_system.output_environment_projection",
        }
    )


def _node_memory_policy_view(*, graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    policy = dict(graph_config.memory or {})
    read_rules = _dedupe_edge_items(
        [
            *_target_node_items(list(policy.get("read_rules") or []), node_id=node_id),
            *_resource_flow_edges(graph_config=graph_config, node_id=node_id, semantic_role="memory"),
        ]
    )
    return {
        "working_memory_policy_profile_id": str(policy.get("working_memory_policy_profile_id") or ""),
        "working_memory_policy": dict(policy.get("working_memory_policy") or {}),
        "read_rules": read_rules,
        "read_rule_count": len(read_rules),
        "total_read_rule_count": len(list(policy.get("read_rules") or [])),
        "memory_protocol": _memory_protocol_summary(dict(policy.get("memory_protocol") or {})),
        "authority": "graph_system.context_materializer.node_memory_policy_view",
    }


def _node_artifact_policy_view(*, graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    policy = dict(graph_config.artifacts or {})
    context_edges = _dedupe_edge_items(
        [
            *_target_node_items(list(policy.get("context_edges") or []), node_id=node_id),
            *_resource_flow_edges(graph_config=graph_config, node_id=node_id, semantic_role="artifact"),
        ]
    )
    return {
        "context_edges": context_edges,
        "context_edge_count": len(context_edges),
        "total_context_edge_count": len(list(policy.get("context_edges") or [])),
        "authority": "graph_system.context_materializer.node_artifact_policy_view",
    }


def _resource_policy_view(*, graph_config: ExecutableGraphConfig, node_id: str = "") -> dict[str, Any]:
    file_context_edges = _resource_flow_edges(graph_config=graph_config, node_id=node_id, semantic_role="file") if node_id else []
    visible_resource_ids = {
        str(edge.get("source_node_id") or "")
        for edge in file_context_edges
        if str(edge.get("source_node_id") or "")
    }
    protocol_entry = _node_protocol_entry(graph_config=graph_config, node_id=node_id)
    visible_resource_ids.update(str(item) for item in list(protocol_entry.get("readable_resource_node_ids") or []) if str(item))
    visible_resource_ids.update(str(item) for item in list(protocol_entry.get("writable_resource_node_ids") or []) if str(item))
    resources = [
        _resource_node_summary(dict(item), node_id=node_id)
        for item in list(dict(graph_config.resources or {}).get("resource_nodes") or [])
        if isinstance(item, dict)
        and (
            _resource_visible_to_node(dict(item), node_id=node_id)
            or str(dict(item).get("node_id") or dict(item).get("resource_id") or "") in visible_resource_ids
        )
    ]
    return {
        "resource_nodes": resources,
        "resource_node_count": len(resources),
        "file_context_edges": file_context_edges,
        "file_context_edge_count": len(file_context_edges),
        "protocol_resource_node_ids": sorted(visible_resource_ids),
        "authority": "graph_system.context_materializer.resource_policy_view",
    }


def _resource_node_summary(item: dict[str, Any], *, node_id: str = "") -> dict[str, Any]:
    current_node_id = str(node_id or "")
    return {
        "node_id": str(item.get("node_id") or ""),
        "title": str(item.get("title") or ""),
        "resource_type": str(item.get("resource_type") or item.get("node_type") or ""),
        "repository_id": str(item.get("repository_id") or ""),
        "collections": [str(value) for value in list(item.get("collections") or []) if str(value)],
        "current_node_can_read": _resource_can_read(item, node_id=current_node_id),
        "current_node_can_write": _resource_can_write(item, node_id=current_node_id),
        "authority": str(item.get("authority") or "task_system.resource_node"),
    }


def _target_node_items(items: list[Any], *, node_id: str) -> list[dict[str, Any]]:
    target = str(node_id or "")
    if not target:
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        if str(payload.get("target_node_id") or "") == target or str(payload.get("node_id") or "") == target:
            result.append(payload)
    return result


def _resource_visible_to_node(item: dict[str, Any], *, node_id: str) -> bool:
    current_node_id = str(node_id or "")
    if not current_node_id:
        return False
    resource_id = str(item.get("node_id") or item.get("resource_id") or "")
    return (
        current_node_id == resource_id
        or _resource_can_read(item, node_id=current_node_id)
        or _resource_can_write(item, node_id=current_node_id)
    )


def _resource_can_read(item: dict[str, Any], *, node_id: str) -> bool:
    current_node_id = str(node_id or "")
    readable_by = {str(value) for value in list(item.get("readable_by") or []) if str(value)}
    return bool(current_node_id and ("*" in readable_by or current_node_id in readable_by))


def _resource_can_write(item: dict[str, Any], *, node_id: str) -> bool:
    current_node_id = str(node_id or "")
    write_owners = {str(value) for value in list(item.get("write_owner_node_ids") or []) if str(value)}
    return bool(current_node_id and ("*" in write_owners or current_node_id in write_owners))


def _resource_flow_edges(*, graph_config: ExecutableGraphConfig, node_id: str, semantic_role: str) -> list[dict[str, Any]]:
    role = str(semantic_role or "").strip()
    result: list[dict[str, Any]] = []
    for edge in build_inbound_flow_edges(graph_config, node_id):
        payload = dict(edge)
        if str(payload.get("semantic_role") or "") != role:
            continue
        result.append(payload)
    return result


def _node_protocol_entry(*, graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    index = dict(dict(graph_config.contracts or {}).get("node_protocol_index") or {})
    return dict(index.get(str(node_id or "")) or {})


def _node_task_contract(*, graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    index = dict(dict(graph_config.contracts or {}).get("node_task_contract_index") or {})
    return dict(index.get(str(node_id or "")) or {})


def _node_agent_binding(*, graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    index = dict(dict(graph_config.contracts or {}).get("node_agent_binding_index") or {})
    return dict(index.get(str(node_id or "")) or {})


def _node_effective_environment_id(
    *,
    graph_config: ExecutableGraphConfig,
    node: dict[str, Any],
    agent_binding: dict[str, Any],
) -> str:
    environment_lock = dict(agent_binding.get("environment_lock") or {})
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or metadata.get("runtime") or {})
    return str(
        environment_lock.get("task_environment_id")
        or environment_lock.get("environment_id")
        or metadata.get("task_environment_id")
        or metadata.get("environment_id")
        or runtime_profile.get("task_environment_id")
        or runtime_profile.get("environment_id")
        or ""
    ).strip()


def _node_agent_config(*, node: dict[str, Any], agent_binding: dict[str, Any]) -> dict[str, str]:
    return {
        "agent_id": str(node.get("agent_id") or agent_binding.get("agent_id") or "").strip(),
        "agent_profile_id": str(node.get("agent_profile_id") or agent_binding.get("agent_profile_id") or "").strip(),
        "agent_group_id": str(node.get("agent_group_id") or agent_binding.get("agent_group_id") or "").strip(),
        "agent_selection_policy": str(agent_binding.get("agent_selection_policy") or "").strip(),
    }


def _node_session_id(
    *,
    state: GraphLoopState,
    node_id: str,
    dispatch_seq: int,
    session_policy: dict[str, Any],
) -> str:
    mode = str(session_policy.get("mode") or "per_node_run_session").strip()
    if mode in {"root_graph_session", "reuse_graph_session"}:
        return str(state.session_id or "")
    template = str(session_policy.get("session_id_template") or "gsess-{graph_run_id}-{node_id}-{dispatch_seq}")
    values = {
        "graph_run_id": safe_id(state.graph_run_id),
        "raw_graph_run_id": state.graph_run_id,
        "node_id": safe_id(node_id),
        "raw_node_id": node_id,
        "dispatch_seq": int(dispatch_seq or 1),
        "root_session_id": safe_id(state.session_id),
        "raw_root_session_id": state.session_id,
    }
    try:
        rendered = template.format(**values)
    except Exception:
        rendered = f"gsess-{safe_id(state.graph_run_id)}-{safe_id(node_id)}-{int(dispatch_seq or 1)}"
    return safe_id(str(rendered or "").strip(), limit=180) or f"gsess-{safe_id(state.graph_run_id)}-{safe_id(node_id)}-{int(dispatch_seq or 1)}"


def _dedupe_edge_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        payload = dict(item)
        key = str(payload.get("edge_id") or payload)
        if key in seen:
            continue
        seen.add(key)
        result.append(payload)
    return result


def _memory_protocol_summary(protocol: dict[str, Any]) -> dict[str, Any]:
    if not protocol:
        return {}
    return {
        "authority": str(protocol.get("authority") or ""),
        "repository_count": len(list(protocol.get("repositories") or [])),
        "read_rule_count": len(list(protocol.get("read_rules") or [])),
        "write_rule_count": len(list(protocol.get("write_rules") or [])),
    }


def _graph_work_kind(executor_type: str) -> str:
    normalized = str(executor_type or "agent").strip()
    if normalized in {"human", "human_gate", "manual_gate"}:
        raise ValueError("human gate is a node/edge gate attachment, not a graph work kind")
    if normalized == "review_gate":
        return "control_router"
    if normalized == "tool":
        return "tool"
    return "agent"


def _superstep_seq_from_state(*, state: GraphLoopState, graph_clock_seq: int) -> int:
    loop_state = dict(state.loop_state or {})
    for key in ("superstep_seq", "dispatch_wave_seq", "wave_seq"):
        try:
            value = int(loop_state.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return max(1, int(graph_clock_seq or 1))


def _node_runtime_profile(*, graph_config: ExecutableGraphConfig, node: dict[str, Any], agent_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(metadata.get("runtime") or {})
    binding = dict(agent_binding or {})
    environment_lock = dict(binding.get("environment_lock") or {})
    task_environment_id = str(environment_lock.get("task_environment_id") or "")
    return {
        **runtime_profile,
        "task_environment_id": task_environment_id,
        "node_environment_lock": environment_lock,
        "node_session_policy": dict(binding.get("session_policy") or {}),
        "graph_project_binding": dict(binding.get("project_binding") or {}),
        "runtime_policy": {
            "source": "graph_node_config",
            "node_id": str(node.get("node_id") or ""),
            "context_policy": {"task_run_context": "disabled"},
            "prompt_wiring_overrides": {
                "task_execution": {
                    "runtime_prompt_pack": {
                        "pack_refs": ["runtime.pack.graph_node_execution"],
                        "replace": True,
                        "owner_layer": "graph_system",
                        "cache_scope": "static",
                    }
                }
            },
            "prompt_policy": {
                "environment_prompt_visibility": "hidden",
                "environment_payload_visibility": "hidden",
                "project_instruction_visibility": "hidden",
                "personality_prompt_visibility": "hidden",
                "runtime_environment_boundary_visibility": "hidden",
            },
            "operation_authorization_projection": {
                "model_visible": "summary_without_denials",
                "reason": "图节点只需要知道本轮可用操作；被拒绝操作不参与节点交付判断。",
            },
            **dict(binding.get("runtime_policy") or runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {}),
        },
    }


def _environment_refs(graph_config: ExecutableGraphConfig) -> dict[str, Any]:
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "memory_space_ref": _memory_space_ref(graph_config),
        "file_access_table_refs": list(_file_access_table_refs(graph_config)),
        "artifact_repository_targets": _artifact_repository_targets(graph_config),
        "memory_repository_targets": _memory_repository_targets(graph_config),
        "authority": "graph_system.context_materializer.environment_refs",
    }


def _artifact_space_ref(graph_config: ExecutableGraphConfig) -> str:
    storage = dict(dict(graph_config.environment or {}).get("storage_space") or {})
    return str(storage.get("artifact_root") or "").strip()


def _memory_space_ref(graph_config: ExecutableGraphConfig) -> str:
    memory_space = dict(dict(graph_config.environment or {}).get("memory_space") or {})
    for key in ("environment_memory_refs", "project_knowledge_refs", "shared_context_refs", "retrieval_index_refs"):
        refs = [str(item) for item in list(memory_space.get(key) or []) if str(item)]
        if refs:
            return refs[0]
    return str(graph_config.task_environment_id or "").strip()


def _file_access_table_refs(graph_config: ExecutableGraphConfig) -> tuple[str, ...]:
    tables = list(dict(graph_config.environment or {}).get("file_access_tables") or [])
    refs: list[str] = []
    for item in tables:
        if not isinstance(item, dict):
            continue
        table_id = str(item.get("table_id") or "").strip()
        if table_id:
            refs.append(table_id)
    return tuple(dict.fromkeys(refs))


def _artifact_repository_targets(graph_config: ExecutableGraphConfig) -> list[dict[str, Any]]:
    artifact_root = _artifact_space_ref(graph_config)
    if not artifact_root:
        return []
    return [
        {
            "target_ref": artifact_root,
            "target_kind": "task_environment_artifact_root",
            "task_environment_id": str(graph_config.task_environment_id or ""),
            "authority": "task_environment.artifact_policy",
        }
    ]


def _memory_repository_targets(graph_config: ExecutableGraphConfig) -> list[dict[str, Any]]:
    memory_space = dict(dict(graph_config.environment or {}).get("memory_space") or {})
    targets: list[dict[str, Any]] = []
    for key in ("environment_memory_refs", "project_knowledge_refs", "shared_context_refs", "retrieval_index_refs"):
        for ref in [str(item).strip() for item in list(memory_space.get(key) or []) if str(item).strip()]:
            targets.append(
                {
                    "target_ref": ref,
                    "target_kind": key,
                    "task_environment_id": str(graph_config.task_environment_id or ""),
                    "authority": "task_environment.memory_space",
                }
            )
    return targets


def _runtime_scope_from_state(state: GraphLoopState) -> dict[str, Any]:
    return dict(dict(state.diagnostics or {}).get("runtime_scope") or {})
