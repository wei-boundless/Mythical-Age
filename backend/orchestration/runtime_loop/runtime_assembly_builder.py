from __future__ import annotations

import hashlib
from typing import Any

from orchestration.agent_runtime_models import AgentRuntimeProfile

from .contract_compiler_models import ContractManifest
from .runtime_assembly_models import (
    HandoffPacket,
    NodeRuntimeAssembly,
    RuntimeAcceptanceContract,
    RuntimeContextSection,
    RuntimeFailureContract,
    RuntimeLoopPolicy,
    RuntimeOutputContract,
    SingleAgentRuntimeAssembly,
)


def build_single_agent_runtime_assembly(
    *,
    manifest: ContractManifest,
    agent_profile: AgentRuntimeProfile | None,
    explicit_inputs: dict[str, Any] | None = None,
    runtime_lane: str = "",
    working_memory_context: dict[str, Any] | None = None,
    task_durable_memory_context: dict[str, Any] | None = None,
) -> SingleAgentRuntimeAssembly:
    agent_id = str(getattr(agent_profile, "agent_id", "") or "agent:0")
    agent_profile_id = str(getattr(agent_profile, "agent_profile_id", "") or "main_interactive_agent")
    sections = (
        RuntimeContextSection(
            section_id="main_session_history",
            title="主会话历史",
            content_mode="summary",
            source_ref="conversation",
            model_visible=True,
            metadata={"history_policy": "summary_by_default", "profile_context_section": "conversation"},
        ),
        RuntimeContextSection(
            section_id="task_inputs",
            title="任务输入",
            content_mode="structured",
            source_ref=manifest.task_ref,
            model_visible=True,
            metadata={
                "input_keys": sorted(str(key) for key in dict(explicit_inputs or {}).keys()),
                "profile_context_section": "task",
            },
        ),
        RuntimeContextSection(
            section_id="runtime_contracts",
            title="运行契约",
            content_mode="refs_only",
            source_ref=manifest.manifest_id,
            model_visible=True,
            metadata={"profile_context_section": "runtime_contracts"},
        ),
        *_working_memory_sections(working_memory_context),
        *_task_durable_memory_sections(task_durable_memory_context),
    )
    visible_sections, hidden_sections = _filter_context_sections_by_profile(sections, agent_profile)
    working_diag = _working_memory_diagnostics(working_memory_context)
    task_durable_diag = _task_durable_memory_diagnostics(task_durable_memory_context)
    return SingleAgentRuntimeAssembly(
        assembly_id=_stable_assembly_id("single", manifest.manifest_id, agent_id, explicit_inputs or {}),
        manifest_ref=manifest.manifest_id,
        task_ref=manifest.task_ref,
        workflow_id=manifest.workflow_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        runtime_lane=runtime_lane,
        context_sections=visible_sections,
        output_contracts=_runtime_output_contracts(manifest),
        acceptance_contracts=_runtime_acceptance_contracts(manifest),
        failure_contract=RuntimeFailureContract(),
        loop_policy=RuntimeLoopPolicy(loop_mode="single_agent", max_turns=1),
        diagnostics={
            "manifest_valid": manifest.valid,
            "manifest_issue_count": len(manifest.issues),
            "full_history_included": False,
            "explicit_input_keys": sorted(str(key) for key in dict(explicit_inputs or {}).keys()),
            **working_diag,
            **task_durable_diag,
            "context_sections_requested": [item.section_id for item in sections],
            "context_sections_visible": [item.section_id for item in visible_sections],
            "context_sections_hidden_by_profile": hidden_sections,
        },
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
    node_projection_id = str(getattr(node, "projection_id", "") or "").strip()
    agent_default_projection_id = str(getattr(agent_profile, "default_projection_id", "") or "").strip()
    resolved_projection_id = node_projection_id or agent_default_projection_id
    sections = (
        RuntimeContextSection(
            section_id="coordination_task_state",
            title="协调任务状态",
            content_mode="status_only",
            source_ref=manifest.coordination_task_id,
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
    return NodeRuntimeAssembly(
        assembly_id=_stable_assembly_id("node", manifest.manifest_id, node_id, explicit_inputs or {}),
        manifest_ref=manifest.manifest_id,
        coordination_task_ref=manifest.coordination_task_id,
        graph_id=manifest.graph_id,
        node_id=node.node_id,
        task_ref=node.task_id,
        agent_id=agent_id,
        agent_profile_id=agent_profile_id,
        projection_id=resolved_projection_id,
        runtime_lane=node.runtime_lane,
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
        diagnostics={
            "manifest_valid": manifest.valid,
            "manifest_issue_count": len(manifest.issues),
            "full_main_session_history_included": False,
            "handoff_packet_count": len(handoff_packets),
            "node_projection_id": node_projection_id,
            "agent_default_projection_id": agent_default_projection_id,
            "projection_resolution_source": "node" if node_projection_id else ("agent_default" if agent_default_projection_id else "none"),
            "projection_override": bool(node_projection_id and agent_default_projection_id and node_projection_id != agent_default_projection_id),
            "explicit_input_keys": sorted(str(key) for key in dict(explicit_inputs or {}).keys()),
            **working_diag,
            **task_durable_diag,
            "context_sections_requested": [item.section_id for item in sections],
            "context_sections_visible": [item.section_id for item in visible_sections],
            "context_sections_hidden_by_profile": hidden_sections,
        },
    )


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
    return HandoffPacket(
        packet_id=_stable_assembly_id("handoff", manifest.manifest_id, edge.edge_id, {"target": target_node_id}),
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        contract_refs=edge.contract_refs,
        payload={
            "manifest_ref": manifest.manifest_id,
            "edge_id": edge.edge_id,
            "contract_refs": list(edge.contract_refs),
        },
        a2a_trace={
            "message_type": edge.message_type,
            "handoff_policy": edge.handoff_policy,
            "business_mode": dict(edge.metadata or {}).get("business_mode", ""),
        },
        metadata={"graph_id": manifest.graph_id},
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
        "upstream_outputs": {"upstream_outputs", "handoff", "task"},
        "artifact_refs": {"artifact_refs", "tool"},
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


def _stable_assembly_id(kind: str, manifest_ref: str, subject: str, payload: dict[str, Any]) -> str:
    raw = repr((kind, manifest_ref, subject, sorted((str(k), str(v)) for k, v in dict(payload or {}).items())))
    return f"runtime-assembly:{kind}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def _working_memory_sections(working_memory_context: dict[str, Any] | None) -> tuple[RuntimeContextSection, ...]:
    payload = dict(working_memory_context or {})
    task_run_id = str(payload.get("task_run_id") or "").strip()
    if not task_run_id:
        return ()
    sections: list[RuntimeContextSection] = []
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
                    "task_family": str(payload.get("task_family") or ""),
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
