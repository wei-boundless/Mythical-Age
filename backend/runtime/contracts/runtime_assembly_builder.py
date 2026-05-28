from __future__ import annotations

import hashlib
from typing import Any

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile

from orchestration.artifact_policy_view import artifact_policy_summary

from .compiler_models import ContractManifest
from .runtime_assembly_models import (
    HandoffPacket,
    NodeRuntimeAssembly,
    RuntimeAcceptanceContract,
    RuntimeContextSection,
    RuntimeFailureContract,
    RuntimeLoopPolicy,
    RuntimeOutputContract,
)


def build_node_runtime_assembly(
    *,
    manifest: ContractManifest,
    node_id: str,
    agent_profile: AgentRuntimeProfile | None = None,
    explicit_inputs: dict[str, Any] | None = None,
    working_memory_context: dict[str, Any] | None = None,
    task_durable_memory_context: dict[str, Any] | None = None,
) -> NodeRuntimeAssembly:
    node = next((item for item in manifest.node_contracts if item.node_id == node_id), None)
    if node is None:
        raise ValueError(f"node not found in manifest: {node_id}")
    agent_id = node.agent_id or str(getattr(agent_profile, "agent_id", "") or "")
    agent_profile_id = str(getattr(agent_profile, "agent_profile_id", "") or "")
    agent_profile_agent_id = str(getattr(agent_profile, "agent_id", "") or "")
    context_assembly_policy = _context_assembly_policy_from_node(node)
    layered_context = _layered_node_context(manifest=manifest, node_id=node_id)
    node_artifact_policy = dict(node.artifact_bindings.get("artifact_policy") or getattr(node, "artifact_policy", {}) or node.metadata.get("artifact_policy") or {})
    sections = (
        RuntimeContextSection(
            section_id="coordination_task_state",
            title="协调任务状态",
            content_mode="status_only",
            source_ref=manifest.graph_ref or manifest.graph_id,
            model_visible=True,
            metadata={"profile_context_section": "task"},
        ),
        RuntimeContextSection(
            section_id="upstream_outputs",
            title="上游输出",
            content_mode="summary",
            source_ref=manifest.graph_id,
            model_visible=True,
            metadata={"profile_context_section": "upstream_outputs"},
        ),
        RuntimeContextSection(
            section_id="artifact_refs",
            title="产物引用",
            content_mode="refs_only",
            source_ref=manifest.manifest_id,
            model_visible=True,
            metadata={"profile_context_section": "artifact_refs"},
        ),
        RuntimeContextSection(
            section_id="artifact_policy",
            title="产物政策",
            content_mode="structured",
            source_ref=f"{manifest.graph_id}:{node_id}:artifact_policy",
            model_visible=True,
            metadata={
                "profile_context_section": "runtime_contracts",
                "artifact_policy": artifact_policy_summary(node_artifact_policy),
            },
        ),
        *_layered_context_sections(layered_context),
        *_working_memory_sections(working_memory_context),
        *_task_durable_memory_sections(task_durable_memory_context),
    )
    visible_sections, hidden_sections = _filter_context_sections_by_profile(sections, agent_profile)
    handoff_packets = tuple(
        _handoff_packet_from_edge(edge, manifest=manifest, target_node_id=node_id)
        for edge in manifest.edge_handoff_contracts
        if edge.target_node_id == node_id
    )
    working_diag = _working_memory_diagnostics(working_memory_context)
    task_durable_diag = _task_durable_memory_diagnostics(task_durable_memory_context)
    node_stream_policy = dict(node.artifact_bindings.get("stream_policy") or getattr(node, "stream_policy", {}) or node.metadata.get("stream_policy") or {})
    node_memory_read_policy = dict(node.memory_bindings.get("memory_read_policy") or getattr(node, "memory_read_policy", {}) or node.metadata.get("memory_read_policy") or {})
    node_memory_writeback_policy = dict(
        node.memory_bindings.get("memory_writeback_policy") or getattr(node, "memory_writeback_policy", {}) or node.metadata.get("memory_writeback_policy") or {}
    )
    node_dynamic_memory_read_policy = dict(
        node.memory_bindings.get("dynamic_memory_read_policy") or getattr(node, "dynamic_memory_read_policy", {}) or node.metadata.get("dynamic_memory_read_policy") or {}
    )
    node_length_budget = dict(node.runtime_bindings.get("length_budget") or {})
    node_role_prompt = str(node.metadata.get("role_prompt") or "").strip()
    return NodeRuntimeAssembly(
        assembly_id=_stable_assembly_id("node", manifest.manifest_id, node_id, explicit_inputs or {}),
        manifest_ref=manifest.manifest_id,
        graph_id=manifest.graph_id,
        graph_ref=str(manifest.graph_ref or manifest.graph_id or ""),
        node_id=node.node_id,
        task_ref=node.task_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        context_sections=visible_sections,
        input_contract_refs=tuple(ref for ref in (node.input_contract_id,) if ref),
        output_contracts=_runtime_output_contracts(manifest, only_contract_ids=set(node.contract_refs)),
        acceptance_contracts=_runtime_acceptance_contracts(manifest, only_contract_ids=set(node.contract_refs)),
        handoff_packets=handoff_packets,
        failure_contract=RuntimeFailureContract(),
        loop_policy=RuntimeLoopPolicy(
            loop_mode="coordination_node",
            max_turns=1,
            context_strategy="node_status_and_upstream_summary",
        ),
        metadata={
            "role_prompt": node_role_prompt,
            "stream_policy": node_stream_policy,
            "memory_read_policy": node_memory_read_policy,
            "memory_writeback_policy": node_memory_writeback_policy,
            "dynamic_memory_read_policy": node_dynamic_memory_read_policy,
            "artifact_policy": node_artifact_policy,
            "length_budget": node_length_budget,
            "contract_bindings": {
                "schema": dict(node.schema_bindings),
                "execution": dict(node.execution_bindings),
                "artifact": dict(node.artifact_bindings),
                "memory": dict(node.memory_bindings),
                "acceptance": dict(node.acceptance_bindings),
                "runtime": dict(node.runtime_bindings),
                "unit_batch": dict(node.unit_batch_bindings),
                "governance": dict(node.governance_bindings),
            },
            "layered_context": layered_context,
            "execution_timeline": {
                "timeline_kind": "node_execution_sequence",
                "steps": [
                    {
                        "step_id": "memory_read",
                        "title": "读取授权记忆包",
                        "kind": "memory_read",
                        "enabled": bool(node.metadata.get("memory_read_policy")),
                    },
                    {
                        "step_id": "execute_node",
                        "title": "执行节点职责",
                        "kind": "node_execution",
                        "enabled": True,
                    },
                    {
                        "step_id": "memory_write",
                        "title": "写入节点结果",
                        "kind": "memory_write",
                        "enabled": bool(node.metadata.get("memory_writeback_policy")),
                    },
                ],
                "authority": "orchestration.node_execution_timeline",
            },
        },
        diagnostics={
            "manifest_valid": manifest.valid,
            "manifest_issue_count": len(manifest.issues),
            "stream_policy": node_stream_policy,
            "length_budget": node_length_budget,
            "full_main_session_history_included": False,
            "handoff_packet_count": len(handoff_packets),
            "node_agent_id": node.agent_id,
            "agent_profile_agent_id": agent_profile_agent_id,
            "agent_resolution_source": "node" if node.agent_id else ("agent_profile" if agent_profile_agent_id else "none"),
            "agent_profile_ref": agent_profile_id,
            "agent_profile_source": "orchestration.agent_runtime_profile" if agent_profile else "none",
            "task_graph_node_ref": f"{manifest.graph_ref or manifest.graph_id}:{node.node_id}",
            "explicit_input_keys": sorted(str(key) for key in dict(explicit_inputs or {}).keys()),
            **working_diag,
            **task_durable_diag,
            "layered_context": {
                "memory_read_edge_count": len(layered_context["memory_reads"]),
                "memory_write_edge_count": len(layered_context["memory_writes"]),
                "artifact_context_edge_count": len(layered_context["artifact_context_edges"]),
                "revision_edge_count": len(layered_context["revision_edges"]),
                "temporal_incoming_edge_count": len(layered_context["temporal_incoming_edges"]),
                "memory_snapshot_id": layered_context["memory_snapshot"]["memory_snapshot_id"],
            },
            "context_assembly_policy": context_assembly_policy,
            "context_sections_requested": [item.section_id for item in sections],
            "context_sections_visible": [item.section_id for item in visible_sections],
            "context_sections_hidden_by_profile": hidden_sections,
        },
    )


def _layered_node_context(*, manifest: ContractManifest, node_id: str) -> dict[str, Any]:
    layered = dict(dict(manifest.metadata or {}).get("layered_graph") or {})
    memory_edges = [dict(item) for item in list(layered.get("memory_edges") or []) if isinstance(item, dict)]
    artifact_edges = [dict(item) for item in list(layered.get("artifact_context_edges") or []) if isinstance(item, dict)]
    revision_edges = [dict(item) for item in list(layered.get("revision_edges") or []) if isinstance(item, dict)]
    temporal_edges = [dict(item) for item in list(layered.get("temporal_edges") or []) if isinstance(item, dict)]
    resource_nodes = [dict(item) for item in list(layered.get("resource_nodes") or []) if isinstance(item, dict)]
    resource_by_id = {str(item.get("node_id") or ""): item for item in resource_nodes if str(item.get("node_id") or "")}
    memory_reads = [
        _memory_edge_descriptor(edge, resource_by_id=resource_by_id, direction="read")
        for edge in memory_edges
        if _memory_edge_targets_node(edge, node_id=node_id, operation="read")
    ]
    memory_writes = [
        _memory_edge_descriptor(edge, resource_by_id=resource_by_id, direction="write")
        for edge in memory_edges
        if _memory_edge_targets_node(edge, node_id=node_id, operation="write")
    ]
    incoming_artifact_edges = [
        dict(edge)
        for edge in artifact_edges
        if str(edge.get("target_node_id") or "").strip() == node_id
    ]
    incoming_revision_edges = [
        dict(edge)
        for edge in revision_edges
        if str(edge.get("target_node_id") or "").strip() == node_id
    ]
    incoming_temporal_edges = [
        dict(edge)
        for edge in temporal_edges
        if str(edge.get("target_node_id") or "").strip() == node_id
    ]
    memory_snapshot = {
        "authority": "task_system.deterministic_memory_snapshot_descriptor",
        "memory_snapshot_id": _stable_assembly_id(
            "memory-snapshot",
            manifest.manifest_id,
            node_id,
            {"read_edge_ids": [item["edge_id"] for item in memory_reads]},
        ),
        "node_id": node_id,
        "stage_id": node_id,
        "configured_scope_ref": f"{manifest.graph_ref or manifest.graph_id}:{node_id}",
        "runtime_clock_authority": "task_graph.timeline_ledger",
        "read_edge_ids": [item["edge_id"] for item in memory_reads],
        "resolved_record_refs": [],
        "retrieval_mode": "directed_repository_edges",
    }
    return {
        "authority": "task_system.layered_node_context",
        "node_id": node_id,
        "memory_reads": memory_reads,
        "memory_writes": memory_writes,
        "memory_snapshot": memory_snapshot,
        "artifact_context_edges": incoming_artifact_edges,
        "revision_edges": incoming_revision_edges,
        "temporal_incoming_edges": incoming_temporal_edges,
    }


def _layered_context_sections(layered_context: dict[str, Any]) -> tuple[RuntimeContextSection, ...]:
    sections: list[RuntimeContextSection] = []
    if layered_context.get("memory_reads") or layered_context.get("memory_writes"):
        sections.append(
            RuntimeContextSection(
                section_id="memory_snapshot",
                title="定向记忆快照",
                content_mode="structured",
                source_ref=str(dict(layered_context.get("memory_snapshot") or {}).get("memory_snapshot_id") or ""),
                model_visible=True,
                metadata={
                    "profile_context_section": "working_memory",
                    "memory_reads": list(layered_context.get("memory_reads") or []),
                    "memory_writes": list(layered_context.get("memory_writes") or []),
                    "memory_snapshot": dict(layered_context.get("memory_snapshot") or {}),
                },
            )
        )
    if layered_context.get("artifact_context_edges"):
        sections.append(
            RuntimeContextSection(
                section_id="artifact_context",
                title="定向产物上下文",
                content_mode="structured",
                source_ref=str(layered_context.get("node_id") or ""),
                model_visible=True,
                metadata={
                    "profile_context_section": "artifact_refs",
                    "artifact_context_edges": list(layered_context.get("artifact_context_edges") or []),
                },
            )
        )
    if layered_context.get("revision_edges"):
        sections.append(
            RuntimeContextSection(
                section_id="revision_context",
                title="返修交接上下文",
                content_mode="structured",
                source_ref=str(layered_context.get("node_id") or ""),
                model_visible=True,
                metadata={
                    "profile_context_section": "upstream_outputs",
                    "revision_edges": list(layered_context.get("revision_edges") or []),
                },
            )
        )
    return tuple(sections)


def _memory_edge_targets_node(edge: dict[str, Any], *, node_id: str, operation: str) -> bool:
    edge_type = str(edge.get("memory_edge_type") or "").strip()
    source = str(edge.get("source_node_id") or "").strip()
    target = str(edge.get("target_node_id") or "").strip()
    if operation == "read":
        return target == node_id and edge_type in {"read", "handoff"}
    if operation == "write":
        return source == node_id and edge_type in {"write", "write_candidate", "commit"}
    return False


def _memory_edge_descriptor(
    edge: dict[str, Any],
    *,
    resource_by_id: dict[str, dict[str, Any]],
    direction: str,
) -> dict[str, Any]:
    source = str(edge.get("source_node_id") or "").strip()
    target = str(edge.get("target_node_id") or "").strip()
    resource = resource_by_id.get(source if direction == "read" else target, {})
    return {
        "edge_id": str(edge.get("edge_id") or ""),
        "operation": direction,
        "memory_edge_type": str(edge.get("memory_edge_type") or ""),
        "repository": str(edge.get("repository") or resource.get("repository_id") or ""),
        "collection": str(edge.get("collection") or ""),
        "resource_node_id": str(resource.get("node_id") or ""),
        "record_keys": list(edge.get("record_keys") or []),
        "selector": dict(edge.get("selector") or {}),
        "version_selector": str(edge.get("version_selector") or ""),
        "on_missing": str(edge.get("on_missing") or ""),
        "read_contract": dict(edge.get("read_contract") or {}),
        "write_contract": dict(edge.get("write_contract") or {}),
    }


def _runtime_output_contracts(
    manifest: ContractManifest,
    *,
    only_contract_ids: set[str] | None = None,
) -> tuple[RuntimeOutputContract, ...]:
    selected = []
    for contract in manifest.global_contracts:
        if only_contract_ids is not None and contract.contract_id not in only_contract_ids:
            continue
        required = tuple(
            str(field.get("field_id") or "")
            for field in contract.output_fields
            if field.get("required") and str(field.get("field_id") or "")
        )
        selected.append(
            RuntimeOutputContract(
                contract_id=contract.contract_id,
                title_zh=contract.title_zh,
                required_fields=required,
                metadata={"contract_kind": contract.contract_kind},
            )
        )
    return tuple(selected)


def _runtime_acceptance_contracts(
    manifest: ContractManifest,
    *,
    only_contract_ids: set[str] | None = None,
) -> tuple[RuntimeAcceptanceContract, ...]:
    selected = []
    for contract in manifest.acceptance_contracts:
        if only_contract_ids is not None and contract.contract_id not in only_contract_ids:
            continue
        selected.append(
            RuntimeAcceptanceContract(
                contract_id=contract.contract_id,
                rule_refs=contract.rule_refs,
                hard_rule_count=contract.rule_count,
            )
        )
    return tuple(selected)


def _handoff_packet_from_edge(edge: Any, *, manifest: ContractManifest, target_node_id: str) -> HandoffPacket:
    edge_metadata = dict(edge.metadata or {})
    return HandoffPacket(
        packet_id=_stable_assembly_id("handoff", manifest.manifest_id, edge.edge_id, {"target": target_node_id}),
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        contract_refs=edge.contract_refs,
        payload={
            "manifest_ref": manifest.manifest_id,
            "edge_id": edge.edge_id,
            "contract_refs": list(edge.contract_refs),
            "handoff_summary": str(edge_metadata.get("handoff_summary") or ""),
            "required_refs": [
                str(item).strip()
                for item in list(edge_metadata.get("required_refs") or [])
                if str(item).strip()
            ],
            "memory_expectation": str(edge_metadata.get("memory_expectation") or ""),
            "contract_bindings": {
                "schema": dict(getattr(edge, "schema_bindings", {}) or {}),
                "handoff": dict(getattr(edge, "handoff_bindings", {}) or {}),
                "temporal": dict(getattr(edge, "temporal_bindings", {}) or {}),
                "memory": dict(getattr(edge, "memory_bindings", {}) or {}),
                "artifact": dict(getattr(edge, "artifact_bindings", {}) or {}),
                "governance": dict(getattr(edge, "governance_bindings", {}) or {}),
            },
        },
        a2a_trace={
            "message_type": edge.message_type,
            "handoff_policy": edge.handoff_policy,
            "business_mode": edge_metadata.get("business_mode", ""),
        },
        metadata={
            "graph_id": manifest.graph_id,
            "protocol_id": str(edge_metadata.get("protocol_id") or ""),
        },
    )


def _filter_context_sections_by_profile(
    sections: tuple[RuntimeContextSection, ...],
    agent_profile: AgentRuntimeProfile | None,
) -> tuple[tuple[RuntimeContextSection, ...], list[str]]:
    allowed = {
        str(item or "").strip()
        for item in tuple(getattr(agent_profile, "allowed_context_sections", ()) or ())
        if str(item or "").strip()
    }
    if not allowed:
        return sections, []
    visible: list[RuntimeContextSection] = []
    hidden: list[str] = []
    for section in sections:
        profile_key = str(section.metadata.get("profile_context_section") or section.section_id).strip()
        aliases = _context_section_aliases(section.section_id, profile_key)
        if allowed.intersection(aliases):
            visible.append(section)
        else:
            hidden.append(section.section_id)
    return tuple(visible), hidden


def _context_section_aliases(section_id: str, profile_key: str) -> set[str]:
    aliases = {str(section_id or "").strip(), str(profile_key or "").strip()}
    alias_map = {
        "main_session_history": {"conversation"},
        "task_inputs": {"task"},
        "coordination_task_state": {"task", "coordination_task_state"},
        "runtime_contracts": {"runtime_contracts"},
        "artifact_policy": {"runtime_contracts", "artifact_refs"},
        "upstream_outputs": {"upstream_outputs", "handoff", "task"},
        "memory_snapshot": {"working_memory", "memory_runtime_view", "task"},
        "revision_context": {"upstream_outputs", "handoff", "task"},
        "artifact_refs": {"artifact_refs", "tool"},
        "artifact_context": {"artifact_refs", "tool"},
        "working_memory.required": {"working_memory", "memory_runtime_view", "task"},
        "working_memory.preferred": {"working_memory", "memory_runtime_view", "task"},
        "working_memory.artifact_refs": {"working_memory", "artifact_refs", "tool"},
        "working_memory.conflict_warnings": {"working_memory", "memory_runtime_view", "runtime_trace"},
        "task_durable_memory.required": {"task_durable", "task_durable_memory", "memory_runtime_view", "task"},
        "task_durable_memory.preferred": {"task_durable", "task_durable_memory", "memory_runtime_view", "task"},
        "task_durable_memory.refs": {"task_durable", "task_durable_memory", "artifact_refs"},
    }
    aliases.update(alias_map.get(str(section_id or "").strip(), set()))
    aliases.discard("")
    return aliases


def _context_assembly_policy_from_node(node: Any) -> dict[str, Any]:
    metadata = dict(getattr(node, "metadata", {}) or {})
    visibility = dict(metadata.get("context_visibility_policy") or {})
    memory_read = dict(metadata.get("memory_read_policy") or {})
    conversation_memory = str(
        visibility.get("conversation_memory")
        or visibility.get("conversation_memory_policy")
        or memory_read.get("conversation_memory")
        or memory_read.get("conversation_memory_policy")
        or ""
    ).strip()
    suppress_conversation = conversation_memory in {
        "hidden",
        "disabled",
        "off",
        "none",
        "no_conversation",
        "suppress",
        "suppress_conversation",
    } or bool(visibility.get("suppress_conversation_memory") or memory_read.get("suppress_conversation_memory"))
    return {
        "main_session_history": "hidden",
        "suppress_conversation_memory": suppress_conversation,
        "conversation_memory": "hidden" if suppress_conversation else "profile_default",
    }


def _stable_assembly_id(kind: str, manifest_ref: str, subject: str, payload: dict[str, Any]) -> str:
    raw = repr((kind, manifest_ref, subject, sorted((str(k), str(v)) for k, v in dict(payload or {}).items())))
    return f"runtime-assembly:{kind}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _working_memory_sections(working_memory_context: dict[str, Any] | None) -> tuple[RuntimeContextSection, ...]:
    payload = dict(working_memory_context or {})
    task_run_id = str(payload.get("task_run_id") or "").strip()
    if not task_run_id:
        return ()
    sections: list[RuntimeContextSection] = []
    formal_records = [dict(item) for item in list(payload.get("formal_memory.required_records") or []) if isinstance(item, dict)]
    if formal_records:
        sections.append(
            RuntimeContextSection(
                section_id="formal_memory.required_records",
                title="正式记忆快照",
                content_mode="structured",
                source_ref=f"formal_memory:{task_run_id}",
                model_visible=True,
                metadata={
                    "profile_context_section": "working_memory",
                    "task_run_id": task_run_id,
                    "graph_id": str(payload.get("graph_id") or ""),
                    "owner_node_id": str(payload.get("owner_node_id") or ""),
                    "node_run_id": str(payload.get("node_run_id") or ""),
                    "record_count": len(formal_records),
                    "record_refs": [
                        str(item.get("version_id") or item.get("record_id") or "")
                        for item in formal_records
                        if str(item.get("version_id") or item.get("record_id") or "")
                    ],
                    "records": formal_records,
                    "read_log_ids": list(payload.get("formal_memory.read_log_ids") or []),
                },
            )
        )
    for section_id, title in (
        ("working_memory.required", "工作记忆必需切片"),
        ("working_memory.preferred", "工作记忆优先切片"),
        ("working_memory.artifact_refs", "工作记忆产物引用"),
        ("working_memory.conflict_warnings", "工作记忆冲突提示"),
    ):
        section_payload = dict(payload.get(section_id) or {})
        item_count = int(section_payload.get("item_count") or 0)
        if item_count <= 0 and not section_payload.get("refs"):
            continue
        sections.append(
            RuntimeContextSection(
                section_id=section_id,
                title=title,
                content_mode=str(section_payload.get("content_mode") or "summary").strip() or "summary",
                source_ref=f"working_memory:{task_run_id}",
                model_visible=section_id != "working_memory.conflict_warnings" or bool(section_payload.get("model_visible", True)),
                metadata={
                    "profile_context_section": "working_memory",
                    "task_run_id": task_run_id,
                    "graph_id": str(payload.get("graph_id") or ""),
                    "owner_node_id": str(payload.get("owner_node_id") or ""),
                    "node_run_id": str(payload.get("node_run_id") or ""),
                    "run_attempt_id": str(payload.get("run_attempt_id") or ""),
                    "item_count": item_count,
                    "refs": list(section_payload.get("refs") or []),
                },
            )
        )
    return tuple(sections)


def _working_memory_diagnostics(working_memory_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(working_memory_context or {})
    task_run_id = str(payload.get("task_run_id") or "").strip()
    return {
        "working_memory_enabled": bool(task_run_id),
        "working_memory_task_run_id": task_run_id,
        "working_memory_graph_id": str(payload.get("graph_id") or ""),
        "working_memory_owner_node_id": str(payload.get("owner_node_id") or ""),
        "working_memory_node_run_id": str(payload.get("node_run_id") or ""),
        "working_memory_run_attempt_id": str(payload.get("run_attempt_id") or ""),
        "working_memory_required_count": int(dict(payload.get("working_memory.required") or {}).get("item_count") or 0),
        "working_memory_preferred_count": int(dict(payload.get("working_memory.preferred") or {}).get("item_count") or 0),
        "working_memory_conflict_count": int(dict(payload.get("working_memory.conflict_warnings") or {}).get("item_count") or 0),
        "formal_memory_required_count": len([item for item in list(payload.get("formal_memory.required_records") or []) if isinstance(item, dict)]),
        "formal_memory_primary": bool(dict(payload.get("diagnostics") or {}).get("formal_memory_primary")),
    }


def _task_durable_memory_sections(task_durable_context: dict[str, Any] | None) -> tuple[RuntimeContextSection, ...]:
    payload = dict(task_durable_context or {})
    namespace_id = str(payload.get("namespace_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    graph_id = str(payload.get("graph_id") or "").strip()
    if not namespace_id and not task_id and not graph_id:
        return ()
    source_ref = f"task_durable_memory:{namespace_id or task_id or graph_id}"
    sections: list[RuntimeContextSection] = []
    for section_id, title in (
        ("task_durable_memory.required", "任务长期记忆必需切片"),
        ("task_durable_memory.preferred", "任务长期记忆优先切片"),
        ("task_durable_memory.refs", "任务长期记忆引用"),
    ):
        section_payload = dict(payload.get(section_id) or {})
        item_count = int(section_payload.get("item_count") or 0)
        refs = list(section_payload.get("refs") or [])
        if item_count <= 0 and not refs:
            continue
        sections.append(
            RuntimeContextSection(
                section_id=section_id,
                title=title,
                content_mode=str(section_payload.get("content_mode") or "summary").strip() or "summary",
                source_ref=source_ref,
                model_visible=bool(section_payload.get("model_visible", True)),
                metadata={
                    "profile_context_section": "task_durable_memory",
                    "namespace_id": namespace_id,
                    "domain_id": str(payload.get("domain_id") or ""),
                    "task_id": task_id,
                    "graph_id": graph_id,
                    "project_id": str(payload.get("project_id") or ""),
                    "artifact_namespace": str(payload.get("artifact_namespace") or ""),
                    "item_count": item_count,
                    "refs": refs,
                },
            )
        )
    return tuple(sections)


def _task_durable_memory_diagnostics(task_durable_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(task_durable_context or {})
    namespace_id = str(payload.get("namespace_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    graph_id = str(payload.get("graph_id") or "").strip()
    return {
        "task_durable_memory_enabled": bool(namespace_id or task_id or graph_id),
        "task_durable_memory_namespace_id": namespace_id,
        "task_durable_memory_task_id": task_id,
        "task_durable_memory_graph_id": graph_id,
        "task_durable_memory_required_count": int(dict(payload.get("task_durable_memory.required") or {}).get("item_count") or 0),
        "task_durable_memory_preferred_count": int(dict(payload.get("task_durable_memory.preferred") or {}).get("item_count") or 0),
    }


