from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from artifact_system.artifact_authority import artifact_ref_value, dedupe_artifact_refs, normalize_artifact_ref

from .edge_contracts import edge_contract_or_projection
from .flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from .flow_packet import flow_packet_inbound_projection
from .loop_engine import LoopEngine
from .memory_context import MemoryContextAssembler
from .models import GraphHarnessConfig, GraphLoopState, GraphNodeExecutionSlot, GraphNodeWorkOrder, safe_id, stable_hash
from .runtime_objects import load_flow_packet, load_node_result
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
        work_order_id = f"gwork:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{dispatch_seq}:{graph_clock_seq}:{int(time.time() * 1000)}"
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
        compiled_node_contract = dict(input_package.get("compiled_node_contract") or {})
        node_session_policy = dict(compiled_node_contract.get("session_policy") or {})
        node_session_id = _node_session_id(
            state=state,
            node_id=node_id,
            dispatch_seq=dispatch_seq,
            session_policy=node_session_policy,
        )
        execution_input_package = _execution_input_package(input_package)
        execution_artifact_view = _execution_artifact_view_request(input_package.get("artifact_view"))
        execution_expected_result_contract = _execution_expected_result_contract(input_package.get("expected_result_contract"))
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
            node_session_id=node_session_id,
            node_session_policy=node_session_policy,
            node_id=node_id,
            agent_id=str(node.get("agent_id") or ""),
            agent_profile_id=str(node.get("agent_profile_id") or ""),
            message=str(input_package.get("agent_instruction") or ""),
            explicit_inputs=dict(input_package.get("initial_inputs") or {}),
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
                "authority": "harness.graph_loop.node_work_order_graph_state",
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
            permission_scope=_explicit_permission_scope(input_package),
            tool_scope=_explicit_tool_scope(input_package),
            expected_result_contract=execution_expected_result_contract,
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
                "node_session_id": node_session_id,
                "node_session_policy": node_session_policy,
                "graph_clock_seq": graph_clock_seq,
                "node_dispatch_seq": dispatch_seq,
                "node_dispatch_count": dispatch_seq,
                "round_index": _dispatch_round_index(input_package=input_package, dispatch_seq=dispatch_seq),
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
            node_contract=_execution_node_contract_from_input_package(graph_config=graph_config, node=node, input_package=input_package),
            edge_contracts={
                "inbound_flow_packets": _inbound_flow_packets(slot_inbound_context),
                "inbound_edge_contexts": _execution_inbound_contexts(slot_inbound_context),
                "outbound_edge_policies": [
                    _outbound_edge_policy(graph_config=graph_config, edge=dict(edge))
                    for edge in build_outbound_flow_edges(graph_config, node_id)
                ],
                "authority": "harness.graph.edge_contract_projection",
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
                "authority": "harness.graph.memory_contract_projection",
            },
            loop_contract={
                "loop_context": _execution_loop_context(loop_context),
                "scope_id": str(loop_context.get("scope_id") or ""),
                "variables": _loop_variables(loop_context),
                "dynamic_bindings": _loop_dynamic_bindings(loop_context),
                "authority": "harness.graph.loop_contract_projection",
            },
            output_contract={
                "output_policy": dict(dict(output_contract.get("contract_bindings") or {}).get("output") or {}),
                "artifact_targets": _output_artifact_targets(input_package),
                "formal_memory_targets": [],
                "environment_projection": _output_environment_projection(graph_config, input_package=input_package),
                "expected_result_contract": _execution_expected_result_contract(input_package.get("expected_result_contract")),
                "authority": "harness.graph.output_contract_projection",
            },
            state_refs={
                "inbound_packet_refs": _inbound_packet_refs(inbound_context),
                "artifact_refs": [],
                "checkpoint_ref": "",
                "prior_result_ref_count": len(dict(state.result_index or {})),
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
        dispatch_seq: int = 1,
        graph_clock_seq: int = 1,
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        prompt_contract = _prompt_contract(node)
        compiled_node_contract = _compiled_node_contract(graph_config=graph_config, node_id=node_id)
        task_environment_id = _node_effective_environment_id(graph_config=graph_config, node=node, compiled_node_contract=compiled_node_contract)
        loop_context = self._loop_engine.context_for_node(state=state, node=node)
        initial_inputs = dict(state.initial_inputs or {})
        initial_inputs.update(_current_chapter_execution_inputs(initial_inputs))
        initial_inputs.update(_revision_request_inputs(node=node, inbound_context=inbound_context, initial_inputs=initial_inputs))
        initial_inputs.update(_quality_revision_inputs(node=node, inbound_context=inbound_context, initial_inputs=initial_inputs))
        initial_inputs.update(_current_chapter_outline_inputs(initial_inputs=initial_inputs, inbound_context=inbound_context))
        inbound_context = _sanitize_revision_context_for_current_chapter(
            node_id=node_id,
            initial_inputs=initial_inputs,
            inbound_context=inbound_context,
        )
        initial_inputs.update(_batch_chapter_ledger_inputs_for_node(node_id=node_id, inbound_context=inbound_context))
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
            "compiled_node_contract": compiled_node_contract,
            "task_environment_id": task_environment_id,
            "runtime_scope": _runtime_scope_from_state(state),
            "runtime_profile": _node_runtime_profile(graph_config=graph_config, node=node, compiled_node_contract=compiled_node_contract),
            "execution_boundary": {
                "node_worker_only": True,
                "graph_state_owner": "harness.graph_loop",
                "allowed_result_authority": "harness.graph_node_result_envelope",
                "forbidden_actions": [
                    "advance_graph_state",
                    "dispatch_downstream_node",
                    "write_graph_checkpoint",
                    "bypass_edge_contract",
                ],
                "authority": "harness.graph.node_worker_execution_boundary",
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
            "permission_summary": dict(compiled_node_contract.get("permission_ceiling") or node.get("permissions") or {}),
            "tool_capability_table": dict(compiled_node_contract.get("tool_contract") or node.get("tools") or {}),
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
                **({"compiled_node_contract": compiled_node_contract} if compiled_node_contract else {}),
            },
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
        context.extend(_loop_iteration_contexts_for_node(graph_config=graph_config, state=state, node_id=node_id))
        context.extend(_self_quality_failure_contexts_for_node(services=self._services, state=state, node_id=node_id))
        return context


def _current_chapter_execution_inputs(initial_inputs: dict[str, Any]) -> dict[str, Any]:
    chapter = _int_value(initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return {}
    patch: dict[str, Any] = {
        "current_chapter_index": chapter,
        "current_chapter_index_padded": f"{chapter:03d}",
        "current_chapter_label": f"第{chapter}章",
        "current_chapter_file_prefix": f"chapter_{chapter:03d}",
    }
    revision_range = str(initial_inputs.get("revision_execution_range") or "").strip()
    active_range = str(initial_inputs.get("active_chapter_range") or "").strip()
    if revision_range:
        patch["revision_execution_range"] = revision_range
    elif active_range:
        patch["revision_execution_range"] = active_range
    return patch


def _int_value(value: Any, default: int | None = 0) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _current_chapter_outline_inputs(*, initial_inputs: dict[str, Any], inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return {}
    for text in _inbound_artifact_texts(inbound_context, current_chapter=chapter):
        section = _extract_chapter_outline_section(text, chapter)
        if not section:
            continue
        title = _chapter_outline_title(section, chapter)
        return _drop_empty(
            {
                "current_chapter_outline": section,
                "current_chapter_outline_title": title,
                "current_chapter_outline_source": "inbound_artifact_projection",
            }
        )
    return {}


def _inbound_artifact_texts(inbound_context: list[dict[str, Any]], *, current_chapter: int | None = None) -> list[str]:
    texts: list[str] = []
    for raw in inbound_context:
        item = dict(raw or {})
        payload = dict(item.get("payload") or {})
        for container in (item, payload):
            for artifact_payload in list(dict(container).get("artifact_payloads") or []):
                if not isinstance(artifact_payload, dict):
                    continue
                text = str(artifact_payload.get("content") or artifact_payload.get("text") or "").strip()
                if text:
                    texts.append(text)
        if current_chapter is not None:
            revision_text = str(payload.get("handoff_summary") or "").strip()
            current_requirements = _extract_current_chapter_revision_requirements(revision_text, current_chapter)
            if current_requirements:
                texts.append(current_requirements)
    return texts


def _batch_chapter_ledger_inputs_for_node(*, node_id: str, inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    if _node_tail(node_id) != "chapter_batch_assemble":
        return {}
    for raw in inbound_context:
        if not isinstance(raw, dict):
            continue
        payload = dict(raw.get("payload") or {})
        ledger = payload.get("batch_chapter_ledger")
        if isinstance(ledger, dict) and ledger:
            return {
                "batch_chapter_ledger": _compact_batch_chapter_ledger(dict(ledger)),
                "batch_chapter_ledger_authority": "harness.graph.batch_chapter_ledger",
            }
    return {}


def _compact_batch_chapter_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for raw in list(ledger.get("chapters") or []):
        if not isinstance(raw, dict):
            continue
        draft = dict(raw.get("draft") or {})
        route = dict(raw.get("route") or {})
        chapters.append(
            _drop_empty(
                {
                    "chapter_index": raw.get("chapter_index"),
                    "status": str(raw.get("status") or ""),
                    "draft_artifact_refs": _artifact_ref_values(draft.get("artifact_refs")),
                    "route_artifact_refs": _artifact_ref_values(route.get("artifact_refs")),
                    "draft_source": str(draft.get("source") or ""),
                    "route_source": str(route.get("source") or ""),
                    "warnings": [str(item) for item in list(raw.get("warnings") or []) if str(item)],
                }
            )
        )
    return _drop_empty(
        {
            "authority": "harness.graph.batch_chapter_ledger",
            "source": str(ledger.get("source") or ""),
            "batch_start_index": ledger.get("batch_start_index"),
            "batch_end_index": ledger.get("batch_end_index"),
            "expected_chapter_indexes": [int(item) for item in list(ledger.get("expected_chapter_indexes") or []) if _int_value(item, None) is not None],
            "complete_chapter_indexes": [int(item) for item in list(ledger.get("complete_chapter_indexes") or []) if _int_value(item, None) is not None],
            "missing_chapter_indexes": [int(item) for item in list(ledger.get("missing_chapter_indexes") or []) if _int_value(item, None) is not None],
            "chapters": chapters,
        }
    )


def _extract_chapter_outline_section(text: str, chapter: int) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""
    pattern = re.compile(rf"(?m)^###\s*第0*{chapter}\s*章[：:].*$")
    match = pattern.search(normalized)
    if not match:
        return ""
    tail = normalized[match.start() :]
    next_match = re.search(r"(?m)^###\s*第0*\d{1,4}\s*章[：:].*$", tail[1:])
    section = tail[: next_match.start() + 1] if next_match else tail
    return section.strip()[:6000]


def _chapter_outline_title(section: str, chapter: int) -> str:
    first = str(section or "").strip().splitlines()[0] if str(section or "").strip() else ""
    return first.lstrip("#").strip() or f"第{chapter}章"


def _sanitize_revision_context_for_current_chapter(
    *,
    node_id: str,
    initial_inputs: dict[str, Any],
    inbound_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _node_tail(node_id) != "chapter_draft" or not initial_inputs.get("revision_queue_chapter_indexes"):
        return inbound_context
    chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    if chapter is None:
        return inbound_context
    sanitized: list[dict[str, Any]] = []
    for raw in inbound_context:
        item = dict(raw or {})
        packet_type = str(item.get("packet_type") or "").lower()
        edge_id = str(item.get("edge_id") or "").lower()
        target_key = str(item.get("target_context_key") or item.get("target_input_slot") or "")
        is_revision = "revision" in packet_type or ".revision." in edge_id or target_key == "返修交接包"
        if not is_revision:
            sanitized.append(item)
            continue
        payload = dict(item.get("payload") or {})
        refs = _artifact_ref_values(item.get("artifact_refs") or payload.get("artifact_refs"))
        payload.pop("artifact_payloads", None)
        payload["handoff_summary"] = str(initial_inputs.get("chapter_revision_requirements") or payload.get("handoff_summary") or "")[:8000]
        payload["current_chapter_index"] = chapter
        payload["revision_execution_range"] = str(initial_inputs.get("revision_execution_range") or "")
        item["payload"] = _drop_empty(payload)
        item["artifact_refs"] = [{"path": ref} for ref in refs]
        item["delivery_policy"] = "current_chapter_revision_summary_and_refs"
        visibility = dict(item.get("visibility") or {})
        visibility["artifact_text_projection"] = "suppressed_for_current_chapter_revision_packet"
        visibility["authority"] = "harness.graph.context_materializer.current_chapter_revision_visibility"
        item["visibility"] = visibility
        sanitized.append(item)
    return sanitized


def _node_tail(node_id: str) -> str:
    return str(node_id or "").strip().rsplit("::", 1)[-1]


def _extract_current_chapter_revision_requirements(text: str, chapter: int) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    selected: list[str] = []
    chapter_pattern = re.compile(rf"第\s*0*{chapter}\s*章")
    next_chapter_pattern = re.compile(r"第\s*0*\d{1,4}\s*章")
    capture = False
    for line in lines:
        if chapter_pattern.search(line):
            capture = True
            selected.append(line)
            continue
        if capture and next_chapter_pattern.search(line) and not chapter_pattern.search(line):
            break
        if capture:
            selected.append(line)
    if not selected:
        return ""
    return "\n".join(selected).strip()[:6000]


def _self_quality_failure_contexts_for_node(
    *,
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
    include_artifact_text = not _quality_issues_include_chapter_mismatch(issue_values)
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
            "artifact_payloads": _artifact_payloads_for_refs(artifact_refs, max_refs=8, max_chars=30000) if include_artifact_text else [],
            "authority": "harness.graph.self_quality_failure_payload",
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
                    "artifact_text_projection": "bounded" if include_artifact_text else "suppressed_after_chapter_mismatch",
                    "authority": "harness.graph.self_quality_failure_context.visibility",
                },
                "authority": "harness.graph.self_quality_failure_context",
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
            if not _quality_failure_matches_current_artifact(state=state, result=result, summary=summary):
                break
            return {"summary": summary, "result": result}
        break
    return {}


def _quality_failure_matches_current_artifact(*, state: GraphLoopState, result: Any, summary: dict[str, Any]) -> bool:
    prefix = str(dict(state.initial_inputs or {}).get("chapter_file_prefix") or "").strip()
    if not prefix:
        return True
    refs = _artifact_ref_values(list(getattr(result, "artifact_refs", ()) or []) or summary.get("artifact_refs"))
    return any(prefix in str(ref or "") for ref in refs)


def _quality_issues_include_chapter_mismatch(issues: list[Any]) -> bool:
    return any(str(item or "").strip().startswith("chapter_mismatch:") for item in issues)


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
        executor_type=str(summary.get("executor_type") or "agent"),
        status=str(summary.get("status") or "blocked"),
        artifact_refs=tuple(_artifact_ref_values(summary.get("artifact_refs"))),
        handoff_summary=str(summary.get("handoff_summary") or ""),
        error=dict(summary.get("error") or {}),
        created_at=float(summary.get("created_at") or 0.0),
    )


def _loop_iteration_contexts_for_node(
    *,
    graph_config: GraphHarnessConfig,
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
        batch_chapter_ledger = _batch_chapter_ledger(
            graph_config=graph_config,
            state=state,
            frame=frame,
            iteration_entries=iteration_entries,
        )
        aggregate_refs.extend(_artifact_ref_values(dict(batch_chapter_ledger).get("artifact_refs")))
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
                        "batch_chapter_ledger": batch_chapter_ledger,
                        "artifact_refs": artifact_refs,
                        "artifact_payloads": _artifact_payloads_for_refs(artifact_refs, max_refs=24, max_chars=12000),
                        "authority": "harness.graph.loop_iteration_results_payload",
                    },
                    "artifact_refs": [{"path": ref} for ref in artifact_refs],
                    "memory_refs": [],
                    "result_refs": [],
                    "receipt_refs": [],
                    "visibility": {
                        "source": "loop_state.iteration_results",
                        "artifact_text_projection": "bounded",
                        "authority": "harness.graph.loop_iteration_context.visibility",
                    },
                    "authority": "harness.graph.loop_iteration_context",
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


def _batch_chapter_ledger(
    *,
    graph_config: GraphHarnessConfig,
    state: GraphLoopState,
    frame: dict[str, Any],
    iteration_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    if _node_tail(str(frame.get("exit_node_id") or "")) != "chapter_batch_assemble":
        return {}
    initial_inputs = dict(state.initial_inputs or {})
    start = _int_value(initial_inputs.get("batch_start_index"), None)
    end = _int_value(initial_inputs.get("batch_end_index"), start)
    if start is None or end is None:
        return {}
    if end < start:
        start, end = end, start
    if end - start > 100:
        return {}
    existing_by_chapter: dict[int, dict[str, Any]] = {}
    for entry in iteration_entries:
        chapter = _chapter_index_from_iteration_entry(entry)
        if chapter is not None and start <= chapter <= end and chapter not in existing_by_chapter:
            existing_by_chapter[chapter] = dict(entry)
    scope_nodes = [str(item) for item in list(frame.get("scope_node_ids") or []) if str(item)]
    draft_node_id = _node_id_for_tail(graph_config=graph_config, scope_node_ids=scope_nodes, tail="chapter_draft")
    router_node_id = _node_id_for_tail(graph_config=graph_config, scope_node_ids=scope_nodes, tail="chapter_unit_router")
    history_index = _batch_chapter_artifact_index(
        state=state,
        start=start,
        end=end,
        draft_node_id=draft_node_id,
        router_node_id=router_node_id,
    )
    chapter_entries: list[dict[str, Any]] = []
    all_refs: list[Any] = []
    for chapter in range(start, end + 1):
        loop_entry = dict(existing_by_chapter.get(chapter) or {})
        loop_results = _chapter_node_results_by_tail(loop_entry)
        history_results = {
            tail: dict(summary)
            for tail, summary in dict(history_index.get(chapter) or {}).items()
            if isinstance(summary, dict)
        }
        draft_entry = dict(loop_results.get("chapter_draft") or history_results.get("chapter_draft") or {})
        router_entry = dict(loop_results.get("chapter_unit_router") or history_results.get("chapter_unit_router") or {})
        draft_refs = _artifact_ref_values(draft_entry.get("artifact_refs"))
        router_refs = _artifact_ref_values(router_entry.get("artifact_refs"))
        all_refs.extend(draft_refs)
        all_refs.extend(router_refs)
        warnings: list[str] = []
        if not loop_entry and (draft_refs or router_refs):
            warnings.append("artifact_found_without_loop_iteration_result")
        if not draft_refs:
            warnings.append("draft_artifact_missing")
        if not router_refs:
            warnings.append("route_artifact_missing")
        chapter_entries.append(
            _drop_empty(
                {
                    "chapter_index": chapter,
                    "chapter_index_padded": f"{chapter:03d}",
                    "iteration_id": str(loop_entry.get("iteration_id") or f"chapter-{chapter}"),
                    "loop_iteration_present": bool(loop_entry),
                    "status": "complete" if draft_refs and router_refs else "incomplete",
                    "draft": _ledger_node_result_projection(draft_entry, source="loop_iteration_results" if loop_results.get("chapter_draft") else "result_history"),
                    "route": _ledger_node_result_projection(router_entry, source="loop_iteration_results" if loop_results.get("chapter_unit_router") else "result_history"),
                    "warnings": warnings,
                }
            )
        )
    complete = [entry["chapter_index"] for entry in chapter_entries if entry.get("status") == "complete"]
    missing = [entry["chapter_index"] for entry in chapter_entries if entry.get("status") != "complete"]
    return _drop_empty(
        {
            "authority": "harness.graph.batch_chapter_ledger",
            "source": "loop_iteration_results_plus_completed_result_history",
            "batch_start_index": start,
            "batch_end_index": end,
            "expected_chapter_indexes": list(range(start, end + 1)),
            "complete_chapter_indexes": complete,
            "missing_chapter_indexes": missing,
            "chapters": chapter_entries,
            "artifact_refs": _artifact_ref_values(all_refs),
        }
    )


def _chapter_node_results_by_tail(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for raw in list(dict(entry or {}).get("node_results") or []):
        if not isinstance(raw, dict):
            continue
        node_result = dict(raw)
        tail = _node_tail(str(node_result.get("node_id") or ""))
        if tail in {"chapter_draft", "chapter_unit_router"} and tail not in results:
            results[tail] = node_result
    return results


def _ledger_node_result_projection(entry: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not entry:
        return {}
    return _drop_empty(
        {
            "source": source,
            "node_id": str(entry.get("node_id") or ""),
            "status": str(entry.get("status") or ""),
            "result_ref": str(entry.get("result_ref") or ""),
            "artifact_refs": _artifact_ref_values(entry.get("artifact_refs")),
            "handoff_summary": str(entry.get("handoff_summary") or "")[:800],
        }
    )


def _batch_chapter_artifact_index(
    *,
    state: GraphLoopState,
    start: int,
    end: int,
    draft_node_id: str,
    router_node_id: str,
) -> dict[int, dict[str, dict[str, Any]]]:
    index: dict[int, dict[str, dict[str, Any]]] = {chapter: {} for chapter in range(start, end + 1)}
    for node_id, summaries in dict(state.result_history or {}).items():
        tail = _node_tail(str(node_id or ""))
        if tail not in {"chapter_draft", "chapter_unit_router"}:
            continue
        marker = "draft_round_" if tail == "chapter_draft" else "unit_route_round_"
        fallback_node_id = draft_node_id if tail == "chapter_draft" else router_node_id
        for raw_summary in list(summaries or []):
            if not isinstance(raw_summary, dict):
                continue
            if str(raw_summary.get("status") or "") != "completed":
                continue
            for chapter, refs in _chapter_artifact_refs_from_summary(raw_summary, marker=marker, start=start, end=end).items():
                summary = {
                    **dict(raw_summary),
                    "node_id": str(raw_summary.get("node_id") or fallback_node_id),
                    "artifact_refs": refs,
                    "source": "result_history",
                    "context_authority": "harness.graph.batch_chapter_artifact_index",
                }
                current = dict(index.get(chapter, {}).get(tail) or {})
                if not current or _chapter_summary_is_newer(summary, current):
                    index.setdefault(chapter, {})[tail] = summary
    return index


def _chapter_artifact_refs_from_summary(
    summary: dict[str, Any],
    *,
    marker: str,
    start: int,
    end: int,
) -> dict[int, list[str]]:
    refs_by_chapter: dict[int, list[str]] = {}
    for ref in _artifact_ref_values(summary.get("artifact_refs")):
        if marker not in str(ref):
            continue
        chapter = _chapter_index_from_artifact_ref(ref)
        if chapter is None or chapter < start or chapter > end:
            continue
        refs_by_chapter.setdefault(chapter, []).append(ref)
    return refs_by_chapter


def _chapter_index_from_iteration_entry(entry: dict[str, Any]) -> int | None:
    chapter = _chapter_index_from_iteration_id(str(dict(entry or {}).get("iteration_id") or ""))
    if chapter is not None:
        return chapter
    for node_result in list(dict(entry or {}).get("node_results") or []):
        if not isinstance(node_result, dict):
            continue
        for ref in _artifact_ref_values(node_result.get("artifact_refs")):
            chapter = _chapter_index_from_artifact_ref(ref)
            if chapter is not None:
                return chapter
    return None


def _chapter_index_from_iteration_id(iteration_id: str) -> int | None:
    match = re.search(r"(?:^|[^A-Za-z])chapter[-_:](\d{1,4})(?:$|[^0-9])", str(iteration_id or ""))
    if not match:
        return None
    return int(match.group(1))


def _chapter_index_from_artifact_ref(ref: str) -> int | None:
    match = re.search(r"(?:^|[\\/])chapter_(\d{3,4})(?:[\\/]|$)", str(ref or ""))
    if not match:
        return None
    return int(match.group(1))


def _chapter_summary_is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    return _chapter_summary_sort_key(candidate) > _chapter_summary_sort_key(current)


def _chapter_summary_sort_key(summary: dict[str, Any]) -> tuple[float, int, str]:
    refs = _artifact_ref_values(summary.get("artifact_refs"))
    identity = str(summary.get("result_id") or (refs[-1] if refs else ""))
    return (
        float(summary.get("created_at") or 0.0),
        max([_round_index_from_ref(ref) for ref in refs] or [0]),
        identity,
    )


def _round_index_from_ref(ref: str) -> int:
    numbers = [int(match) for match in re.findall(r"round_(\d+)", str(ref or ""))]
    return max(numbers) if numbers else 0


def _node_id_for_tail(*, graph_config: GraphHarnessConfig, scope_node_ids: list[str], tail: str) -> str:
    for node_id in scope_node_ids:
        if _node_tail(node_id) == tail:
            return node_id
    for node in graph_config.nodes:
        node_id = str(dict(node or {}).get("node_id") or "")
        if _node_tail(node_id) == tail:
            return node_id
    return tail


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
                "authority": "harness.graph.loop_iteration_artifact_text_projection",
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
            "authority": str(payload.get("authority") or "harness.graph.node_materialization_package"),
            "materializer_authority": str(payload.get("materializer_authority") or ""),
            "node_identity": _execution_node_identity(payload.get("node_identity")),
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
            "agent_id": str(identity.get("agent_id") or ""),
            "agent_profile_id": str(identity.get("agent_profile_id") or ""),
        }
    )


def _execution_runtime_scope(value: Any) -> dict[str, Any]:
    scope = dict(value or {})
    allowed = {
        "project_id",
        "graph_task_instance_id",
        "workspace_view",
        "artifact_root",
        "scope_id",
        "graph_binding_mode",
        "memory_namespace_id",
    }
    return _drop_empty({key: scope.get(key) for key in allowed})


def _explicit_permission_scope(input_package: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(input_package or {}).get("permission_summary") or {})


def _explicit_tool_scope(input_package: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(input_package or {}).get("tool_capability_table") or {})


def _execution_runtime_policy(value: Any) -> dict[str, Any]:
    policy = dict(value or {})
    return _drop_empty(
        {
            "source": str(policy.get("source") or ""),
            "node_id": str(policy.get("node_id") or ""),
            "context_policy": dict(policy.get("context_policy") or {}),
            "prompt_pack_refs_by_invocation": dict(policy.get("prompt_pack_refs_by_invocation") or {}),
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
            "authority": str(contract.get("authority") or "harness.graph.execution_expected_result_contract"),
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
                    "authority": str(item.get("authority") or "harness.graph.inbound_context"),
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
            include_project_brief=str(payload.get("authority") or "") == "harness.graph.initial_input_payload",
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
    if isinstance(payload.get("batch_chapter_ledger"), dict):
        result["batch_chapter_ledger"] = _compact_batch_chapter_ledger(dict(payload.get("batch_chapter_ledger") or {}))
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
            "authority": str(item.get("authority") or "harness.graph.flow_packet.artifact_text_projection"),
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
                    "authority": str(snapshot.get("authority") or "harness.graph.resolved_memory_snapshot"),
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
            "authority": str(loop_context.get("authority") or "harness.graph.loop_engine"),
            "scope_id": str(loop_context.get("scope_id") or ""),
            "current_scope_id": str(loop_context.get("current_scope_id") or ""),
            "current_frame_id": str(loop_context.get("current_frame_id") or ""),
            "iteration_index": loop_context.get("iteration_index"),
            "iteration_id": str(loop_context.get("iteration_id") or ""),
            "cursor_key": str(loop_context.get("cursor_key") or ""),
            "cursor_value": loop_context.get("cursor_value"),
            "active_frame": _execution_loop_frame(loop_context.get("active_frame")),
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
            "status": str(frame.get("status") or ""),
            "kind": str(frame.get("kind") or ""),
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
            "authority": str(frame.get("authority") or ""),
        }
    )


def _execution_initial_inputs(value: Any, *, include_project_brief: bool = False) -> dict[str, Any]:
    payload = dict(value or {})
    allowed_keys = {
        *set(_loop_contract_inputs(payload).keys()),
        "active_chapter_count",
        "active_chapter_end_index",
        "active_chapter_start_index",
        "batch_chapter_list",
        "batch_chapter_numbers",
        "batch_end_index_padded",
        "batch_index_padded",
        "batch_label",
        "batch_start_index_padded",
        "batch_target_measure",
        "chapter_batch_iteration",
        "chapter_file_prefix",
        "chapter_index_padded",
        "chapter_label",
        "chapter_unit_completed_count",
        "current_chapter_outline",
        "current_chapter_outline_source",
        "current_chapter_outline_title",
        "graph_task_instance_id",
        "group_current_measure",
        "group_target_measure",
        "last_batch_words",
        "metric_label",
        "project_title",
        "quality_gate_feedback",
        "revision_queue_chapter_indexes",
        "source",
        "target_group_count",
        "target_unit_count",
        "title",
        "total_current_measure",
        "unit_index",
        "units_per_group",
        "volume_index",
        "volume_index_padded",
        "volume_label",
        "workspace_view",
    }
    result: dict[str, Any] = {}
    for key in allowed_keys:
        value = payload.get(key)
        if value in ("", None, [], {}):
            continue
        if key == "current_chapter_outline":
            result[key] = str(value)[:6000]
        elif key == "quality_gate_feedback" and isinstance(value, dict):
            result[key] = _truncate_value(value, max_chars=6000)
        else:
            result[key] = value
    if include_project_brief and payload.get("project_brief"):
        result["project_brief"] = str(payload.get("project_brief") or "")[:12000]
    return _drop_empty(result)


def _loop_contract_inputs(value: Any) -> dict[str, Any]:
    payload = dict(value or {})
    allowed_keys = {
        "project_id",
        "artifact_root",
        "chapter_index",
        "current_chapter_index",
        "current_chapter_index_padded",
        "current_chapter_label",
        "current_chapter_file_prefix",
        "batch_index",
        "batch_start_index",
        "batch_end_index",
        "batch_chapter_range",
        "unit_start_index",
        "unit_end_index",
        "unit_count",
        "units_per_batch",
        "target_measure_units",
        "unit_target_measure",
        "target_unit_measure",
        "revision_execution_range",
        "active_chapter_range",
        "round_index",
    }
    return {key: payload.get(key) for key in allowed_keys if payload.get(key) not in ("", None, [], {})}


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


def _revision_request_inputs(
    *,
    node: dict[str, Any],
    inbound_context: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    requirements_key = _node_revision_requirements_key(node)
    if not requirements_key:
        return {}
    revision = _first_inbound_revision_request(inbound_context)
    if not revision:
        return {}
    current_chapter = _int_value(initial_inputs.get("current_chapter_index") or initial_inputs.get("chapter_index"), None)
    revision_text = _revision_request_text(revision, current_chapter=current_chapter)
    if not revision_text:
        return {}
    payload = {
        requirements_key: revision_text,
        "revision_required": True,
    }
    artifact_refs = _artifact_ref_values(revision.get("artifact_refs"))
    if artifact_refs:
        payload["previous_chapter_review_ref"] = {"artifact_refs": artifact_refs}
    return payload


def _node_revision_requirements_key(node: dict[str, Any]) -> str:
    retry_policy = dict(node.get("retry") or {})
    key = str(retry_policy.get("requirements_input_key") or "").strip()
    if key:
        return key
    executor_policy = dict(node.get("executor_policy") or {})
    replay_policy = dict(executor_policy.get("replay_sanitization_policy") or {})
    return str(replay_policy.get("requirements_key") or "").strip()


def _quality_revision_inputs(
    *,
    node: dict[str, Any],
    inbound_context: list[dict[str, Any]],
    initial_inputs: dict[str, Any],
) -> dict[str, Any]:
    retry_policy = dict(node.get("retry") or {})
    requirements_key = str(retry_policy.get("requirements_input_key") or "").strip()
    template = str(retry_policy.get("requirements_template") or "").strip()
    if not requirements_key or not template or requirements_key in initial_inputs:
        return {}
    quality = _first_inbound_quality_failure(inbound_context)
    if not quality:
        return {}
    unit_start = initial_inputs.get("chapter_index") or initial_inputs.get("unit_start_index") or initial_inputs.get("batch_start_index") or ""
    unit_end = initial_inputs.get("chapter_index") or initial_inputs.get("unit_end_index") or initial_inputs.get("batch_end_index") or ""
    values = {
        **dict(initial_inputs or {}),
        "quality_issues": "; ".join(str(item) for item in list(quality.get("issues") or []) if str(item)),
        "quality_issue_summary": str(quality.get("quality_issue_summary") or ""),
        "start": unit_start,
        "end": unit_end,
        "count": initial_inputs.get("units_per_batch") or initial_inputs.get("unit_count") or "",
        "unit_target": initial_inputs.get("unit_target_measure") or initial_inputs.get("target_unit_measure") or "",
    }
    revision_inputs = {
        requirements_key: _format_revision_template(template, values),
        "quality_gate_feedback": quality,
    }
    carry_key = str(retry_policy.get("carry_current_output_as") or "").strip()
    if carry_key and carry_key not in initial_inputs:
        previous_output = _quality_failure_previous_output(quality)
        if previous_output:
            revision_inputs[carry_key] = previous_output
    return revision_inputs


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
        "authority": "harness.graph.context_materializer.dispatch_metadata",
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


def _first_inbound_revision_request(inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    for item in inbound_context:
        context = dict(item or {})
        packet_type = str(context.get("packet_type") or "").strip().lower()
        target_key = str(context.get("target_context_key") or context.get("target_input_slot") or "").strip()
        edge_id = str(context.get("edge_id") or "").strip().lower()
        if "revision" not in packet_type and target_key != "返修交接包" and ".revision." not in edge_id:
            continue
        payload = dict(context.get("payload") or {})
        if not payload:
            continue
        return {
            **payload,
            "artifact_refs": _artifact_ref_values(context.get("artifact_refs") or payload.get("artifact_refs")),
            "authority": "harness.graph.context_materializer.revision_request_inputs",
        }
    return {}


def _revision_request_text(revision: dict[str, Any], *, current_chapter: int | None = None) -> str:
    parts: list[str] = []
    summary = str(revision.get("handoff_summary") or "").strip()
    if summary:
        parts.append(summary)
    current_parts: list[str] = []
    for item in list(revision.get("artifact_payloads") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("content") or "").strip()
        if not text:
            continue
        if current_chapter is not None:
            current_text = _extract_current_chapter_revision_requirements(text, current_chapter)
            if current_text:
                current_parts.append(current_text)
                continue
            scoped = _revision_requirement_or_blocking_sections(text)
            if scoped:
                parts.append(scoped)
                continue
        else:
            parts.append(text)
    if current_parts:
        prefix = f"当前返修章：第{current_chapter}章。以下要求只用于当前章重写；返修队列中的其他章节由图循环逐章调度。"
        return "\n\n".join(dict.fromkeys([prefix, *current_parts])).strip()
    return "\n\n".join(dict.fromkeys(parts)).strip()


def _revision_requirement_or_blocking_sections(text: str) -> str:
    normalized = str(text or "")
    sections: list[str] = []
    for heading in ("返修要求", "必须修改项", "阻塞性问题", "问题清单"):
        pattern = re.compile(rf"(?m)^#{{1,4}}\s*{heading}\b.*$")
        match = pattern.search(normalized)
        if not match:
            continue
        tail = normalized[match.start() :]
        first_newline = tail.find("\n")
        search_tail = tail[first_newline + 1 :] if first_newline >= 0 else ""
        next_heading = re.search(r"(?m)^#{1,4}\s+", search_tail)
        section = tail[: first_newline + 1 + next_heading.start()] if next_heading and first_newline >= 0 else tail
        if section.strip():
            sections.append(section.strip())
    return "\n\n".join(dict.fromkeys(sections)).strip()[:8000]


def _first_inbound_quality_failure(inbound_context: list[dict[str, Any]]) -> dict[str, Any]:
    for item in inbound_context:
        payload = dict(dict(item or {}).get("payload") or {})
        source_error = dict(payload.get("source_error") or {})
        quality = dict(payload.get("quality_acceptance") or {})
        if str(source_error.get("reason") or "") != "quality_gate_failed" and bool(quality.get("accepted") is not False):
            continue
        return {
            **quality,
            "quality_issue_summary": str(source_error.get("quality_issue_summary") or quality.get("quality_issue_summary") or ""),
            "issues": list(source_error.get("issues") or quality.get("issues") or []),
            "source_error": source_error,
            "artifact_refs": _artifact_ref_values(payload.get("artifact_refs")),
            "artifact_payloads": [
                dict(item)
                for item in list(payload.get("artifact_payloads") or [])
                if isinstance(item, dict)
            ],
            "handoff_summary": str(payload.get("handoff_summary") or ""),
            "authority": "harness.graph.context_materializer.quality_revision_inputs",
        }
    return {}


def _quality_failure_previous_output(quality: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "artifact_refs": _artifact_ref_values(quality.get("artifact_refs")),
            "artifact_payloads": [
                _drop_empty(
                    {
                        "artifact_ref": str(dict(item).get("artifact_ref") or ""),
                        "content": str(dict(item).get("content") or dict(item).get("text") or "")[:30000],
                        "truncated": bool(dict(item).get("truncated") is True),
                        "max_chars": int(dict(item).get("max_chars") or 30000),
                    }
                )
                for item in list(quality.get("artifact_payloads") or [])[:8]
                if isinstance(item, dict)
            ],
            "handoff_summary": str(quality.get("handoff_summary") or "")[:1200],
            "authority": "harness.graph.context_materializer.previous_quality_failure_output",
        }
    )


def _format_revision_template(template: str, values: dict[str, Any]) -> str:
    class _Missing(dict):
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_Missing(values))
    except (KeyError, IndexError, ValueError):
        return template


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


def _execution_node_contract_from_input_package(
    *,
    graph_config: GraphHarnessConfig,
    node: dict[str, Any],
    input_package: dict[str, Any],
) -> dict[str, Any]:
    runtime_profile = dict(input_package.get("runtime_profile") or {})
    node_contract = dict(input_package.get("output_contract") or {})
    compiled_node_contract = dict(input_package.get("compiled_node_contract") or {})
    bindings = dict(node_contract.get("contract_bindings") or {})
    runtime_binding = dict(bindings.get("runtime") or {})
    executor = dict(node.get("executor") or {})
    agent = dict(compiled_node_contract.get("agent") or {})
    model_requirement = dict(
        runtime_binding.get("model_requirement")
        or runtime_profile.get("model_requirement")
        or compiled_node_contract.get("model_requirement")
        or {}
    )
    return _drop_empty(
        {
            "contract_id": str(compiled_node_contract.get("contract_id") or node_contract.get("node_contract_id") or ""),
            "compiled_contract_id": str(compiled_node_contract.get("contract_id") or ""),
            "node_id": str(compiled_node_contract.get("node_id") or node.get("node_id") or ""),
            "node_kind": str(compiled_node_contract.get("node_kind") or ""),
            "node_class": str(compiled_node_contract.get("node_class") or ""),
            "node_identity": dict(input_package.get("node_identity") or {}),
            "agent_assembly": _drop_empty(
                {
                    "agent_id": str(node.get("agent_id") or agent.get("agent_id") or ""),
                    "agent_profile_id": str(node.get("agent_profile_id") or agent.get("agent_profile_id") or ""),
                    "executor_type": str(executor.get("executor_type") or "agent"),
                    "authority": "harness.graph.node_agent_assembly_projection",
                }
            ),
            "prompt_contract": dict(input_package.get("prompt_contract") or {}),
            "model_requirement": model_requirement,
            "reasoning_policy": dict(runtime_profile.get("reasoning_policy") or {}),
            "completion_profile": dict(runtime_profile.get("completion_profile") or {}),
            "runtime_policy": _execution_runtime_policy(runtime_profile.get("runtime_policy") or compiled_node_contract.get("runtime_policy")),
            "tool_contract": dict(compiled_node_contract.get("tool_contract") or node.get("tools") or {}),
            "skill_contract": dict(bindings.get("skills") or {}),
            "permission_contract": dict(compiled_node_contract.get("permission_ceiling") or node.get("permissions") or {}),
            "input_contract": dict(input_package.get("input_contract") or {}),
            "acceptance_policy": dict(bindings.get("acceptance") or {}),
            "contract_bindings": _drop_empty(
                {
                    "execution": dict(bindings.get("execution") or {}),
                }
            ),
            "environment_lock": _environment_lock_ref(compiled_node_contract.get("environment_lock") or runtime_profile.get("node_environment_lock")),
            "project_binding": dict(compiled_node_contract.get("project_binding") or runtime_profile.get("graph_project_binding") or {}),
            "session_policy": dict(compiled_node_contract.get("session_policy") or runtime_profile.get("node_session_policy") or {}),
            "authority": "harness.graph.node_contract_execution_projection",
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


def _outbound_edge_policy(*, graph_config: GraphHarnessConfig, edge: dict[str, Any]) -> dict[str, Any]:
    edge_contract = edge_contract_or_projection(graph_config, edge)
    packet = dict(edge_contract.get("packet") or {})
    reliability = dict(edge_contract.get("reliability") or {})
    protocol = dict(edge_contract.get("protocol") or {})
    trace = dict(edge_contract.get("trace") or {})
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_type": str(edge.get("edge_type") or ""),
        "edge_contract_id": str(edge_contract.get("contract_id") or ""),
        "protocol_kind": str(protocol.get("kind") or ""),
        "interaction_pattern": str(protocol.get("interaction_pattern") or ""),
        "produces_flow_packet": bool(protocol.get("produces_flow_packet", trace.get("persist_packet", False))),
        "scheduler_role": str(edge.get("scheduler_role") or ""),
        "semantic_role": str(edge.get("semantic_role") or ""),
        "payload_contract_id": str(packet.get("payload_contract_id") or edge.get("payload_contract_id") or ""),
        "packet_contract_id": str(packet.get("packet_contract_id") or _edge_packet_contract_id(edge)),
        "source_output_selector": str(packet.get("source_output_selector") or _edge_source_output_selector(edge)),
        "target_context_key": str(packet.get("target_context_key") or _edge_target_context_key(edge)),
        "target_input_slot": str(packet.get("target_input_slot") or _edge_target_input_slot(edge)),
        "projection_policy": dict(edge.get("context_filter_policy") or {}),
        "visibility_policy": dict(edge.get("visibility_policy") or {}),
        "receipt_policy": {
            "ack_required": bool(reliability.get("ack_required", edge.get("ack_required", True))),
            "ack_policy": str(reliability.get("ack_policy") or edge.get("ack_policy") or ""),
        },
        "trace_policy": {
            "persist_packet": bool(trace.get("persist_packet", False)),
            "checkpoint_policy": str(trace.get("checkpoint_policy") or ""),
        },
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


def _memory_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(task_environment_id or graph_config.task_environment_id or ""),
        "environment_memory_space": dict(environment.get("memory_space") or {}),
        "memory_space_ref": _memory_space_ref(graph_config),
        "node_memory_policy": dict(node.get("memory") or {}),
        "graph_memory_policy": _node_memory_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _artifact_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
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


def _file_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any], task_environment_id: str = "") -> dict[str, Any]:
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


def _output_environment_projection(graph_config: GraphHarnessConfig, *, input_package: dict[str, Any] | None = None) -> dict[str, Any]:
    compiled_node_contract = dict(dict(input_package or {}).get("compiled_node_contract") or {})
    environment_lock = dict(compiled_node_contract.get("environment_lock") or {})
    return _drop_empty(
        {
            "task_environment_id": str(
                environment_lock.get("task_environment_id")
                or dict(input_package or {}).get("task_environment_id")
                or ""
            ),
            "node_environment_lock": environment_lock,
            "authority": "harness.graph.output_environment_projection",
        }
    )


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


def _compiled_node_contract(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    index = dict(dict(graph_config.contracts or {}).get("node_contract_index") or {})
    return dict(index.get(str(node_id or "")) or {})


def _node_effective_environment_id(
    *,
    graph_config: GraphHarnessConfig,
    node: dict[str, Any],
    compiled_node_contract: dict[str, Any],
) -> str:
    environment_lock = dict(compiled_node_contract.get("environment_lock") or {})
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
    if normalized in {"human", "human_gate", "review_gate"}:
        return "human_gate"
    if normalized == "tool":
        return "tool"
    return "agent"


def _node_runtime_profile(*, graph_config: GraphHarnessConfig, node: dict[str, Any], compiled_node_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(metadata.get("runtime") or {})
    compiled = dict(compiled_node_contract or {})
    environment_lock = dict(compiled.get("environment_lock") or {})
    task_environment_id = str(environment_lock.get("task_environment_id") or "")
    return {
        **runtime_profile,
        "task_environment_id": task_environment_id,
        "node_environment_lock": environment_lock,
        "node_session_policy": dict(compiled.get("session_policy") or {}),
        "graph_project_binding": dict(compiled.get("project_binding") or {}),
        "tool_policy": dict(compiled.get("tool_contract") or node.get("tools") or {}),
        "permission_policy": dict(compiled.get("permission_ceiling") or node.get("permissions") or {}),
        "runtime_policy": {
            "source": "graph_node_config",
            "node_id": str(node.get("node_id") or ""),
            "context_policy": {"task_run_context": "disabled"},
            "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution"]},
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
