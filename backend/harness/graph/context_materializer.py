from __future__ import annotations

import time
from typing import Any

from .flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from .flow_packet import flow_packet_inbound_projection
from .loop_engine import LoopEngine
from .memory_context import MemoryContextAssembler
from .models import GraphHarnessConfig, GraphLoopState, GraphNodeExecutionSlot, GraphNodeWorkOrder, safe_id, stable_hash
from .runtime_objects import load_flow_packet
from .scheduler_view import upstream_dependency_node_ids


class GraphContextMaterializer:
    """Builds graph node work orders and internal materialization packages.

    GraphLoop owns state progression. This materializer owns the graph slot
    assembly data; RuntimeCompiler decides the model-visible projection.
    """

    authority = "harness.graph.context_materializer"

    def __init__(self, *, services: Any | None = None) -> None:
        self._services = services
        self._memory_context = MemoryContextAssembler(services=services)
        self._loop_engine = LoopEngine()

    def build_work_order(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
    ) -> GraphNodeWorkOrder:
        node_id = str(node.get("node_id") or "")
        executor = dict(node.get("executor") or {})
        executor_type = str(executor.get("executor_type") or "agent")
        inbound_context = self.inbound_context_for_node(graph_config=graph_config, state=state, node_id=node_id)
        input_package = self.build_input_package(
            graph_config=graph_config,
            state=state,
            node=node,
            inbound_context=inbound_context,
        )
        dispatch_seq = len(tuple(dict(state.result_history or {}).get(node_id) or ())) + 1
        work_order_id = f"gwork:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{dispatch_seq}:{state.event_cursor + 1}:{int(time.time() * 1000)}"
        graph_slot = self.build_graph_slot(
            graph_config=graph_config,
            state=state,
            node=node,
            work_order_id=work_order_id,
            input_package=input_package,
            inbound_context=inbound_context,
        )
        environment_refs = _environment_refs(graph_config)
        structure_hash = state.structure_hash or graph_config.expected_structural_hash()
        structure_version = state.structure_version or "graph_structure.v1"
        config_snapshot_id = graph_config.config_id
        config_snapshot_hash = graph_config.content_hash
        return GraphNodeWorkOrder(
            work_order_id=work_order_id,
            work_kind=_graph_work_kind(executor_type),
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            structure_hash=structure_hash,
            structure_version=structure_version,
            config_snapshot_id=config_snapshot_id,
            config_snapshot_hash=config_snapshot_hash,
            task_ref=str(node.get("task_ref") or f"task_graph.node.{graph_config.graph_id}.{node_id}"),
            executor_type=executor_type,
            node_id=node_id,
            agent_id=str(node.get("agent_id") or ""),
            agent_profile_id=str(node.get("agent_profile_id") or ""),
            message=str(input_package.get("agent_instruction") or ""),
            explicit_inputs=dict(input_package.get("initial_inputs") or {}),
            input_package=input_package,
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
                "graph_clock_seq": state.event_cursor + 1,
                "completed_node_ids": list(state.completed_node_ids),
                "failed_node_ids": list(state.failed_node_ids),
                "upstream_node_ids": list(upstream_dependency_node_ids(graph_config, node_id)),
                "available_result_node_ids": sorted(state.result_index.keys()),
                "authority": "harness.graph_loop.node_work_order_graph_state",
            },
            context_refs=dict(node.get("context") or {}),
            memory_view_request=dict(input_package.get("memory_view") or {}),
            artifact_view_request=dict(input_package.get("artifact_view") or {}),
            file_view_request=dict(input_package.get("file_view") or {}),
            artifact_space_ref=str(environment_refs.get("artifact_space_ref") or ""),
            memory_space_ref=str(environment_refs.get("memory_space_ref") or ""),
            file_access_table_refs=tuple(environment_refs.get("file_access_table_refs") or ()),
            artifact_repository_targets=tuple(dict(item) for item in list(environment_refs.get("artifact_repository_targets") or []) if isinstance(item, dict)),
            memory_repository_targets=tuple(dict(item) for item in list(environment_refs.get("memory_repository_targets") or []) if isinstance(item, dict)),
            permission_scope=dict(input_package.get("permission_summary") or graph_config.permissions or {}),
            tool_scope=dict(input_package.get("tool_capability_table") or graph_config.tools or {}),
            expected_result_contract=dict(input_package.get("expected_result_contract") or {}),
            async_policy=dict(node.get("async_policy") or {}),
            retry_policy=dict(node.get("retry") or {}),
            timeout_policy=dict(node.get("timeout") or {}),
            dispatch_context={
                "graph_run_id": state.graph_run_id,
                "config_id": graph_config.config_id,
                "graph_structure_hash": structure_hash,
                "graph_structure_version": structure_version,
                "config_snapshot_id": config_snapshot_id,
                "config_snapshot_hash": config_snapshot_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "graph_clock_seq": state.event_cursor + 1,
                "dispatch_event_id": f"dispatch:{state.graph_run_id}:{node_id}:{int(time.time() * 1000)}",
                "executor": executor,
                "inbound_context_count": len(inbound_context),
                "materializer": self.authority,
            },
        )

    def build_graph_slot(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        work_order_id: str,
        input_package: dict[str, Any],
        inbound_context: list[dict[str, Any]],
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
                "node_executor_task_run_id": "",
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "graph_id": graph_config.graph_id,
                "node_id": node_id,
                "work_order_id": str(work_order_id or ""),
            },
            node_contract=_node_contract_from_input_package(graph_config=graph_config, node=node, input_package=input_package),
            edge_contracts={
                "inbound_flow_packets": _inbound_flow_packets(slot_inbound_context),
                "inbound_edge_contexts": slot_inbound_context,
                "outbound_edge_policies": [
                    _outbound_edge_policy(dict(edge))
                    for edge in build_outbound_flow_edges(graph_config, node_id)
                ],
                "authority": "harness.graph.edge_contract_projection",
            },
            memory_contract={
                "namespace_id": _memory_namespace_id(graph_config=graph_config, state=state),
                "read_protocols": read_protocols,
                "resolved_snapshots": list(memory_resolution.get("resolved_snapshots") or []),
                "write_candidate_protocols": list(dict(memory_view.get("graph_memory_policy") or {}).get("write_rules") or []),
                "commit_protocols": list(dict(memory_view.get("graph_memory_policy") or {}).get("commit_rules") or []),
                "memory_receipt_refs": list(memory_resolution.get("memory_receipt_refs") or []),
                "diagnostics": dict(memory_resolution.get("diagnostics") or {}),
                "memory_space_ref": str(input_package.get("memory_space_ref") or ""),
                "authority": "harness.graph.memory_contract_projection",
            },
            loop_contract={
                "loop_context": loop_context,
                "scope_id": str(loop_context.get("scope_id") or ""),
                "variables": dict(dict(loop_context.get("active_frame") or {}).get("variables") or {}),
                "dynamic_bindings": dict(dict(loop_context.get("node_loop") or {}).get("bindings") or {}),
                "authority": "harness.graph.loop_contract_projection",
            },
            output_contract={
                "output_policy": dict(dict(output_contract.get("contract_bindings") or {}).get("output") or {}),
                "artifact_targets": _output_artifact_targets(input_package),
                "formal_memory_targets": [],
                "environment_projection": _output_environment_projection(graph_config),
                "expected_result_contract": dict(input_package.get("expected_result_contract") or {}),
                "authority": "harness.graph.output_contract_projection",
            },
            state_refs={
                "inbound_packet_refs": _inbound_packet_refs(inbound_context),
                "artifact_refs": [],
                "checkpoint_ref": "",
                "prior_result_refs": [dict(item) for item in dict(state.result_index or {}).values() if isinstance(item, dict)],
                "authority": "harness.graph.node_state_refs",
            },
            runtime_controls={
                "retry_policy": dict(node.get("retry") or {}),
                "timeout_policy": dict(node.get("timeout") or {}),
                "failure_policy": dict(node.get("failure_policy") or {}),
                "resume_policy": dict(node.get("resume_policy") or {}),
                "disconnect_policy": dict(node.get("disconnect_policy") or {}),
                "post_node_gate_policy": dict(dict(node.get("gates") or {}).get("post_node_gate_policy") or dict(node.get("metadata") or {}).get("post_node_gate_policy") or {}),
                "authority": "harness.graph.runtime_controls_projection",
            },
            visibility={
                "system_control_only": ["graph_identity", "state_refs", "runtime_controls"],
                "runtime_consumable": [
                    "node_contract.model_requirement",
                    "node_contract.tool_contract",
                    "node_contract.permission_contract",
                    "memory_contract.read_protocols",
                    "memory_contract.commit_protocols",
                    "output_contract.artifact_targets",
                ],
                "model_visible_projection": [
                    "node_contract.prompt_contract",
                    "edge_contracts.inbound_edge_contexts",
                    "memory_contract.resolved_snapshots",
                    "output_contract.output_policy",
                ],
                "authority": "harness.graph.node_execution_slot_visibility",
            },
        )
        return slot.to_dict()

    def build_input_package(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        inbound_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        prompt_contract = _prompt_contract(node)
        initial_inputs = dict(state.initial_inputs or {})
        loop_context = self._loop_engine.context_for_node(state=state, node=node)
        environment_refs = _environment_refs(graph_config)
        return {
            "package_id": f"gin:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(stable_hash([initial_inputs, loop_context, inbound_context])[:12])}",
            "authority": "harness.graph.node_materialization_package",
            "materializer_authority": self.authority,
            "node_identity": {
                "node_id": node_id,
                "title": str(node.get("title") or node_id),
                "node_type": str(node.get("node_type") or ""),
                "task_ref": str(node.get("task_ref") or ""),
                "agent_id": str(node.get("agent_id") or ""),
                "agent_profile_id": str(node.get("agent_profile_id") or ""),
            },
            "prompt_contract": prompt_contract,
            "task_environment_id": str(graph_config.task_environment_id or ""),
            "task_environment": dict(graph_config.environment or {}),
            "runtime_scope": _runtime_scope_from_state(state),
            "runtime_profile": _node_runtime_profile(graph_config=graph_config, node=node),
            "agent_instruction": _agent_instruction(prompt_contract=prompt_contract, node=node),
            "input_contract": dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("schema", {}),
            "output_contract": dict(node.get("contracts") or {}),
            "initial_inputs": initial_inputs,
            "loop_context": loop_context,
            "inbound_context": inbound_context,
            "memory_view": _memory_view_request(graph_config=graph_config, node=node),
            "artifact_view": _artifact_view_request(graph_config=graph_config, node=node),
            "file_view": _file_view_request(graph_config=graph_config, node=node),
            "environment_refs": environment_refs,
            "artifact_space_ref": str(environment_refs.get("artifact_space_ref") or ""),
            "memory_space_ref": str(environment_refs.get("memory_space_ref") or ""),
            "file_access_table_refs": list(environment_refs.get("file_access_table_refs") or []),
            "artifact_repository_targets": [dict(item) for item in list(environment_refs.get("artifact_repository_targets") or []) if isinstance(item, dict)],
            "memory_repository_targets": [dict(item) for item in list(environment_refs.get("memory_repository_targets") or []) if isinstance(item, dict)],
            "issue_view": _issue_view_request(graph_config=graph_config, node=node),
            "permission_summary": dict(node.get("permissions") or graph_config.permissions or {}),
            "tool_capability_table": dict(node.get("tools") or graph_config.tools or {}),
            "hidden_control_refs": {
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "work_order_source": "GraphLoop.dispatch_ready",
            },
            "expected_result_contract": dict(node.get("contracts") or {}),
        }

    def inbound_context_for_node(self, *, graph_config: GraphHarnessConfig, state: GraphLoopState, node_id: str) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        for edge in build_inbound_flow_edges(graph_config, node_id):
            edge_state = dict(state.edge_states.get(str(edge.get("edge_id") or "")) or {})
            for packet_entry in _edge_packet_entries(edge_state):
                packet = load_flow_packet(self._services, packet_entry) if self._services is not None else None
                if packet is None or packet.target_unit_id != node_id:
                    continue
                context.append(flow_packet_inbound_projection(packet, packet_ref=str(packet_entry.get("packet_ref") or "")))
        return context


def _slot_inbound_contexts(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    node_id: str,
    input_package: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    contexts = [dict(item) for item in inbound_context if isinstance(item, dict)]
    initial_inputs = dict(input_package.get("initial_inputs") or {})
    if not initial_inputs or not _is_graph_start_node(graph_config, node_id):
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
            "target_context_key": "graph_initial_inputs",
            "target_input_slot": "initial_inputs",
            "delivery_policy": "contract_payload",
            "payload": {
                "initial_inputs": initial_inputs,
                "graph_id": graph_config.graph_id,
                "project_id": str(initial_inputs.get("project_id") or ""),
                "authority": "harness.graph.initial_input_payload",
            },
            "artifact_refs": [],
            "memory_refs": [],
            "result_refs": [],
            "authority": "harness.graph.initial_input_context",
        },
    )
    return contexts


def _is_graph_start_node(graph_config: GraphHarnessConfig, node_id: str) -> bool:
    start_node_ids = {
        str(item)
        for item in list(dict(graph_config.control or {}).get("start_node_ids") or [])
        if str(item)
    }
    return node_id in start_node_ids


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


def _node_contract_from_input_package(
    *,
    graph_config: GraphHarnessConfig,
    node: dict[str, Any],
    input_package: dict[str, Any],
) -> dict[str, Any]:
    runtime_profile = dict(input_package.get("runtime_profile") or {})
    node_contract = dict(input_package.get("output_contract") or {})
    return {
        "node_identity": dict(input_package.get("node_identity") or {}),
        "agent_assembly": {
            "agent_id": str(node.get("agent_id") or ""),
            "agent_profile_id": str(node.get("agent_profile_id") or ""),
            "executor": dict(node.get("executor") or {}),
            "authority": "harness.graph.node_agent_assembly_projection",
        },
        "prompt_contract": dict(input_package.get("prompt_contract") or {}),
        "model_requirement": dict(dict(node_contract.get("contract_bindings") or {}).get("runtime") or {}).get("model_requirement", {}),
        "reasoning_policy": dict(runtime_profile.get("reasoning_policy") or {}),
        "tool_contract": dict(node.get("tools") or graph_config.tools or {}),
        "skill_contract": dict(dict(node_contract.get("contract_bindings") or {}).get("skills") or {}),
        "permission_contract": dict(node.get("permissions") or graph_config.permissions or {}),
        "input_contract": dict(input_package.get("input_contract") or {}),
        "output_contract": node_contract,
        "memory_permission": dict(node.get("memory") or {}),
        "acceptance_policy": dict(dict(node_contract.get("contract_bindings") or {}).get("acceptance") or {}),
        "authority": "harness.graph.node_contract_projection",
    }


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
            "authority": "harness.graph.inbound_flow_packet_ref",
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


def _outbound_edge_policy(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "scheduler_role": str(edge.get("scheduler_role") or ""),
        "semantic_role": str(edge.get("semantic_role") or ""),
        "payload_contract_id": str(edge.get("payload_contract_id") or ""),
        "packet_contract_id": _edge_packet_contract_id(edge),
        "source_output_selector": _edge_source_output_selector(edge),
        "target_context_key": _edge_target_context_key(edge),
        "target_input_slot": _edge_target_input_slot(edge),
        "projection_policy": dict(edge.get("context_filter_policy") or {}),
        "visibility_policy": dict(edge.get("visibility_policy") or {}),
        "receipt_policy": {"ack_required": bool(edge.get("ack_required", True)), "ack_policy": str(edge.get("ack_policy") or "")},
        "authority": "harness.graph.outbound_edge_policy_projection",
    }


def _memory_namespace_id(*, graph_config: GraphHarnessConfig, state: GraphLoopState) -> str:
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


def _edge_packet_contract_id(edge: dict[str, Any]) -> str:
    bindings = dict(edge.get("contract_bindings") or {})
    schema = dict(bindings.get("schema") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(edge.get("packet_contract_id") or handoff.get("packet_contract_id") or edge.get("payload_contract_id") or schema.get("payload_contract_id") or "").strip()


def _edge_source_output_selector(edge: dict[str, Any]) -> str:
    policy = dict(edge.get("context_filter_policy") or {})
    artifact_policy = dict(edge.get("artifact_ref_policy") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    candidates = [
        handoff.get("source_output_selector"),
        policy.get("source_output_selector"),
        artifact_policy.get("source_output_key"),
        _first_string(policy.get("include_output_keys")),
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key, enabled in value.items():
            text = str(key or "").strip()
            if text and enabled:
                return text
        return ""
    for item in list(value or []):
        text = str(item or "").strip()
        if text:
            return text
    return ""


def _edge_target_context_key(edge: dict[str, Any]) -> str:
    metadata = dict(edge.get("metadata") or {})
    artifact_policy = dict(edge.get("artifact_ref_policy") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(
        edge.get("target_context_key")
        or handoff.get("target_context_key")
        or metadata.get("target_context_key")
        or metadata.get("target_input_key")
        or artifact_policy.get("target_input_key")
        or ""
    ).strip()


def _edge_target_input_slot(edge: dict[str, Any]) -> str:
    metadata = dict(edge.get("metadata") or {})
    bindings = dict(edge.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(edge.get("target_input_slot") or handoff.get("target_input_slot") or metadata.get("target_input_slot") or metadata.get("input_alias") or "").strip()


def _prompt_contract(node: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(node.get("prompt") or {})
    return {
        "role_prompt": str(prompt.get("role_prompt") or "").strip(),
        "task_instruction": str(prompt.get("task_instruction") or "").strip(),
        "output_instruction": str(prompt.get("output_instruction") or "").strip(),
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
    if done:
        parts.append("完成标准：\n" + "\n".join(f"- {item}" for item in done))
    message = "\n".join(item for item in parts if item).strip()
    if message:
        return message
    return f"请根据你的角色职责完成当前节点任务：{str(node.get('title') or node.get('node_id') or '未命名节点')}。"


def _memory_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_memory_space": dict(environment.get("memory_space") or {}),
        "memory_space_ref": _memory_space_ref(graph_config),
        "node_memory_policy": dict(node.get("memory") or {}),
        "graph_memory_policy": _node_memory_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _artifact_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_artifact_policy": dict(environment.get("artifact_policy") or {}),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "node_artifact_policy": dict(node.get("artifacts") or {}),
        "graph_artifact_policy": _node_artifact_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _file_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "file_management": dict(environment.get("file_management") or {}),
        "file_access_tables": list(environment.get("file_access_tables") or []),
        "file_access_table_refs": _file_access_table_refs(graph_config),
        "node_file_policy": dict(node.get("files") or {}),
        "graph_resource_policy": _resource_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _issue_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
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


def _output_environment_projection(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    storage = dict(environment.get("storage_space") or {})
    artifact_policy = dict(environment.get("artifact_policy") or {})
    return {
        "task_environment_id": str(graph_config.task_environment_id or environment.get("environment_id") or ""),
        "environment_artifact_root": str(storage.get("artifact_root") or ""),
        "environment_storage_root": str(storage.get("environment_storage_root") or ""),
        "environment_artifact_repository": str(artifact_policy.get("artifact_root") or artifact_policy.get("artifact_repository_id") or ""),
        "authority": "harness.graph.output_environment_projection",
    }


def _node_memory_policy_view(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
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
        "authority": "harness.graph.context_materializer.node_memory_policy_view",
    }


def _node_artifact_policy_view(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
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
        "authority": "harness.graph.context_materializer.node_artifact_policy_view",
    }


def _resource_policy_view(*, graph_config: GraphHarnessConfig, node_id: str = "") -> dict[str, Any]:
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
        "authority": "harness.graph.context_materializer.resource_policy_view",
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


def _resource_flow_edges(*, graph_config: GraphHarnessConfig, node_id: str, semantic_role: str) -> list[dict[str, Any]]:
    role = str(semantic_role or "").strip()
    result: list[dict[str, Any]] = []
    for edge in build_inbound_flow_edges(graph_config, node_id):
        payload = dict(edge)
        if str(payload.get("semantic_role") or "") != role:
            continue
        result.append(payload)
    return result


def _node_protocol_entry(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    index = dict(dict(graph_config.contracts or {}).get("node_protocol_index") or {})
    return dict(index.get(str(node_id or "")) or {})


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
    if normalized in {"human", "human_gate", "review_gate"}:
        return "human_gate"
    if normalized == "tool":
        return "tool"
    return "agent"


def _node_runtime_profile(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(metadata.get("runtime") or {})
    return {
        **runtime_profile,
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "tool_policy": dict(node.get("tools") or graph_config.tools or {}),
        "permission_policy": dict(node.get("permissions") or graph_config.permissions or {}),
        "runtime_policy": {
            "source": "graph_node_config",
            "node_id": str(node.get("node_id") or ""),
            "context_policy": {"task_run_context": "disabled"},
            "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            "operation_authorization_projection": {
                "model_visible": "summary_without_denials",
                "reason": "图节点只需要知道本轮可用操作；被拒绝操作不参与节点交付判断。",
            },
            **dict(runtime_profile.get("runtime_policy") or runtime_profile.get("execution_policy") or {}),
        },
    }


def _environment_refs(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "memory_space_ref": _memory_space_ref(graph_config),
        "file_access_table_refs": list(_file_access_table_refs(graph_config)),
        "artifact_repository_targets": _artifact_repository_targets(graph_config),
        "memory_repository_targets": _memory_repository_targets(graph_config),
        "authority": "harness.graph.context_materializer.environment_refs",
    }


def _artifact_space_ref(graph_config: GraphHarnessConfig) -> str:
    storage = dict(dict(graph_config.environment or {}).get("storage_space") or {})
    return str(storage.get("artifact_root") or "").strip()


def _memory_space_ref(graph_config: GraphHarnessConfig) -> str:
    memory_space = dict(dict(graph_config.environment or {}).get("memory_space") or {})
    for key in ("environment_memory_refs", "project_knowledge_refs", "shared_context_refs", "retrieval_index_refs"):
        refs = [str(item) for item in list(memory_space.get(key) or []) if str(item)]
        if refs:
            return refs[0]
    return str(graph_config.task_environment_id or "").strip()


def _file_access_table_refs(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    tables = list(dict(graph_config.environment or {}).get("file_access_tables") or [])
    refs: list[str] = []
    for item in tables:
        if not isinstance(item, dict):
            continue
        table_id = str(item.get("table_id") or "").strip()
        if table_id:
            refs.append(table_id)
    return tuple(dict.fromkeys(refs))


def _artifact_repository_targets(graph_config: GraphHarnessConfig) -> list[dict[str, Any]]:
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


def _memory_repository_targets(graph_config: GraphHarnessConfig) -> list[dict[str, Any]]:
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
