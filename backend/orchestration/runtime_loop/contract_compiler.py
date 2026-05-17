from __future__ import annotations

from typing import Any

from orchestration.agent_runtime_models import AgentRuntimeProfile
from tasks.contract_definition_models import ContractSpec
from tasks.contract_registry import TaskContractRegistry
from tasks.coordination_graph_models import TaskGraphRuntimeSpec
from tasks.flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol
from tasks.workflow_models import TaskWorkflowBinding

from .a2a_stage_payload import DEFAULT_A2A_MESSAGE_TYPE
from .contract_compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledNodeContract,
    CompiledRuntimeContract,
    CompiledWorkflowContract,
    ContractCompileIssue,
    ContractManifest,
)


def compile_workflow_contract_manifest(
    *,
    contract_registry: TaskContractRegistry,
    task: SpecificTaskRecord,
    workflow: TaskWorkflowBinding,
    agent_profile: AgentRuntimeProfile | None = None,
    agent_id: str = "",
    runtime_lane: str = "",
) -> ContractManifest:
    issues: list[ContractCompileIssue] = []
    global_contracts: dict[str, CompiledGlobalContract] = {}
    acceptance_contracts: dict[str, CompiledAcceptanceContract] = {}

    input_contract_id = str(task.input_contract_id or "").strip()
    output_contract_id = str(task.output_contract_id or workflow.output_contract_id or "").strip()
    workflow_output_contract_id = str(workflow.output_contract_id or output_contract_id).strip()

    for contract_id, source_ref, purpose in (
        (input_contract_id, task.task_id, "input_contract"),
        (output_contract_id, task.task_id, "output_contract"),
        (workflow_output_contract_id, workflow.workflow_id, "workflow_output_contract"),
    ):
        _collect_contract(
            registry=contract_registry,
            contract_id=contract_id,
            source_ref=source_ref,
            purpose=purpose,
            global_contracts=global_contracts,
            acceptance_contracts=acceptance_contracts,
            issues=issues,
        )

    step_contracts: list[dict[str, Any]] = []
    node_contracts: list[CompiledNodeContract] = []
    steps = list(workflow.steps or ())
    for index, raw_step in enumerate(steps or ({"step_id": "workflow_execution", "title": workflow.title},), start=1):
        step = dict(raw_step)
        step_id = str(step.get("step_id") or step.get("id") or f"step_{index}").strip()
        step_contract_id = str(step.get("contract_id") or step.get("output_contract_id") or "").strip()
        if not step_contract_id and index == len(steps):
            step_contract_id = workflow_output_contract_id
        if step_contract_id:
            _collect_contract(
                registry=contract_registry,
                contract_id=step_contract_id,
                source_ref=f"{workflow.workflow_id}:{step_id}",
                purpose="workflow_step_contract",
                global_contracts=global_contracts,
                acceptance_contracts=acceptance_contracts,
                issues=issues,
            )
        step_contracts.append(
            {
                "step_id": step_id,
                "title": str(step.get("title") or step_id),
                "contract_id": step_contract_id,
            }
        )
        node_contracts.append(
            CompiledNodeContract(
                node_id=step_id,
                title=str(step.get("title") or step_id),
                node_type="workflow_step",
                task_id=task.task_id,
                agent_id=agent_id or str(task.metadata.get("agent_id") or ""),
                runtime_lane=runtime_lane,
                input_contract_id=input_contract_id if index == 1 else "",
                output_contract_id=step_contract_id,
                contract_refs=tuple(ref for ref in (input_contract_id if index == 1 else "", step_contract_id) if ref),
                source_refs=(workflow.workflow_id, task.task_id),
            )
        )

    runtime_contracts = _compile_runtime_contracts(
        agent_profiles=tuple(item for item in (agent_profile,) if item is not None),
        runtime_lane=runtime_lane,
        output_contract_id=output_contract_id,
        issues=issues,
    )

    manifest = ContractManifest(
        manifest_id=f"contract-manifest:workflow:{workflow.workflow_id}:{task.task_id}",
        manifest_kind="workflow",
        task_ref=task.task_id,
        workflow_id=workflow.workflow_id,
        global_contracts=tuple(global_contracts.values()),
        workflow_contracts=(
            CompiledWorkflowContract(
                workflow_id=workflow.workflow_id,
                title=workflow.title,
                output_contract_id=workflow_output_contract_id,
                step_contracts=tuple(step_contracts),
                source_ref=task.task_id,
            ),
        ),
        node_contracts=tuple(node_contracts),
        runtime_contracts=tuple(runtime_contracts),
        acceptance_contracts=tuple(acceptance_contracts.values()),
        issues=tuple(issues),
        metadata={"compiler": "contract_compiler.v1"},
    )
    return manifest


def compile_coordination_contract_manifest(
    *,
    contract_registry: TaskContractRegistry,
    coordination_task: CoordinationTaskDefinition,
    graph_spec: TaskGraphRuntimeSpec,
    specific_tasks: tuple[SpecificTaskRecord, ...] = (),
    communication_protocol: TaskCommunicationProtocol | None = None,
    agent_profiles: tuple[AgentRuntimeProfile, ...] = (),
) -> ContractManifest:
    graph_ref = str(graph_spec.graph_id or dict(coordination_task.metadata or {}).get("graph_id") or coordination_task.graph_id).strip()
    issues: list[ContractCompileIssue] = [
        ContractCompileIssue(
            code=f"graph_{item.code}",
            message=item.message,
            severity=item.severity,
            node_id=item.node_id,
            edge_id=item.edge_id,
            source_ref=graph_ref,
        )
        for item in graph_spec.issues
    ]
    global_contracts: dict[str, CompiledGlobalContract] = {}
    acceptance_contracts: dict[str, CompiledAcceptanceContract] = {}
    task_by_id = {item.task_id: item for item in specific_tasks}
    profiles_by_agent = {item.agent_id: item for item in agent_profiles}

    node_contracts: list[CompiledNodeContract] = []
    for node in graph_spec.nodes:
        task = task_by_id.get(node.task_id)
        node_metadata = dict(node.metadata or {})
        node_projection_id = str(
            getattr(node, "projection_id", "")
            or node_metadata.get("projection_id")
            or node_metadata.get("projection_overlay_id")
            or ""
        ).strip()
        explicit_input_contract_id = str(
            getattr(node, "input_contract_id", "")
            or node_metadata.get("input_contract_id")
            or ""
        ).strip()
        explicit_output_contract_id = str(
            getattr(node, "output_contract_id", "")
            or node_metadata.get("output_contract_id")
            or ""
        ).strip()
        input_contract_id = str(
            explicit_input_contract_id
            or getattr(task, "input_contract_id", "")
            or ""
        ).strip()
        output_contract_id = str(
            explicit_output_contract_id
            or getattr(task, "output_contract_id", "")
            or ""
        ).strip()
        explicit_node_contract_refs = tuple(
            ref
            for ref in dict.fromkeys(
                [
                    str(node_metadata.get("node_contract_id") or node_metadata.get("contract_id") or "").strip(),
                    *[
                        str(item).strip()
                        for item in list(node_metadata.get("contract_refs") or [])
                        if str(item).strip()
                    ],
                ]
            )
            if ref
        )
        if task is not None or input_contract_id or output_contract_id:
            for contract_id, purpose in (
                (input_contract_id, "node_input_contract"),
                (output_contract_id, "node_output_contract"),
            ):
                _collect_contract(
                    registry=contract_registry,
                    contract_id=contract_id,
                    source_ref=f"{graph_ref}:{node.node_id}",
                    purpose=purpose,
                    global_contracts=global_contracts,
                    acceptance_contracts=acceptance_contracts,
                    issues=issues,
                    node_id=node.node_id,
                )
        elif node.task_id:
            issues.append(
                ContractCompileIssue(
                    code="node_task_missing",
                    message=f"节点引用的任务不存在，无法编译节点契约：{node.task_id}",
                    severity="error",
                    source_ref=graph_ref,
                    node_id=node.node_id,
                    contract_id=node.task_id,
                )
            )
        for contract_id in explicit_node_contract_refs:
            _collect_contract(
                registry=contract_registry,
                contract_id=contract_id,
                source_ref=f"{graph_ref}:{node.node_id}",
                purpose="node_execution_contract",
                global_contracts=global_contracts,
                acceptance_contracts=acceptance_contracts,
                issues=issues,
                node_id=node.node_id,
            )
        node_contracts.append(
            CompiledNodeContract(
                node_id=node.node_id,
                title=node.title,
                node_type=node.node_type,
                task_id=node.task_id,
                agent_id=node.agent_id,
                runtime_lane=node.runtime_lane,
                projection_id=node_projection_id,
                input_contract_id=input_contract_id,
                output_contract_id=output_contract_id,
                contract_refs=tuple(ref for ref in (input_contract_id, output_contract_id, *explicit_node_contract_refs) if ref),
                source_refs=(graph_ref, node.task_id),
                metadata={
                    "role": node.role,
                    "explicit_node_contract_refs": explicit_node_contract_refs,
                    "context_visibility_policy": dict(getattr(node, "context_visibility_policy", {}) or {}),
                    "memory_read_policy": dict(getattr(node, "memory_read_policy", {}) or {}),
                    "memory_writeback_policy": dict(getattr(node, "memory_writeback_policy", {}) or {}),
                    "dynamic_memory_read_policy": dict(getattr(node, "dynamic_memory_read_policy", {}) or {}),
                    "review_gate_policy": dict(getattr(node, "review_gate_policy", {}) or {}),
                    "human_gate_policy": dict(getattr(node, "human_gate_policy", {}) or {}),
                    "artifact_policy": dict(getattr(node, "artifact_policy", {}) or {}),
                    "stream_policy": dict(getattr(node, "stream_policy", {}) or {}),
                },
            )
        )
        profile = profiles_by_agent.get(node.agent_id)
        if profile is None and node.agent_id:
            issues.append(
                ContractCompileIssue(
                    code="runtime_profile_missing",
                    message=f"节点 Agent 缺少 runtime profile：{node.agent_id}",
                    severity="error",
                    source_ref=graph_ref,
                    node_id=node.node_id,
                    agent_id=node.agent_id,
                )
            )
        elif profile is not None and task is not None:
            _validate_agent_profile(
                profile=profile,
                runtime_lane=node.runtime_lane,
                output_contract_id=output_contract_id,
                issues=issues,
                node_id=node.node_id,
            )

    edge_contracts: list[CompiledEdgeHandoffContract] = []
    protocol_payload_contracts = tuple(str(item).strip() for item in getattr(communication_protocol, "payload_contracts", ()) if str(item).strip())
    for edge in graph_spec.edges:
        metadata = dict(edge.metadata or {})
        contract_refs = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in [
                    getattr(edge, "payload_contract_id", ""),
                    metadata.get("contract_id"),
                    *list(metadata.get("contract_refs") or []),
                    *protocol_payload_contracts,
                ]
                if str(item or "").strip()
            )
        )
        for contract_id in contract_refs:
            _collect_contract(
                registry=contract_registry,
                contract_id=contract_id,
                source_ref=f"{graph_ref}:{edge.edge_id}",
                purpose="edge_handoff_contract",
                global_contracts=global_contracts,
                acceptance_contracts=acceptance_contracts,
                issues=issues,
                edge_id=edge.edge_id,
            )
        if not contract_refs:
            issues.append(
                ContractCompileIssue(
                    code="edge_handoff_contract_missing",
                    message=f"通信边缺少 handoff payload 契约：{edge.edge_id}",
                    severity="error",
                    source_ref=graph_ref,
                    edge_id=edge.edge_id,
                )
            )
        edge_contracts.append(
            CompiledEdgeHandoffContract(
                edge_id=edge.edge_id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                message_type=edge.mode if edge.mode.startswith("message/") else DEFAULT_A2A_MESSAGE_TYPE,
                contract_refs=contract_refs,
                handoff_policy=coordination_task.handoff_policy,
                metadata={
                    "business_mode": edge.mode,
                    "protocol_id": getattr(communication_protocol, "protocol_id", "") or "",
                    "handoff_summary": str(metadata.get("handoff_summary") or ""),
                    "required_refs": [
                        str(item).strip()
                        for item in list(metadata.get("required_refs") or [])
                        if str(item).strip()
                    ],
                    "memory_expectation": str(metadata.get("memory_expectation") or ""),
                },
            )
        )

    runtime_contracts = _compile_runtime_contracts(
        agent_profiles=agent_profiles,
        runtime_lane="",
        output_contract_id="",
        issues=issues,
    )

    return ContractManifest(
        manifest_id=f"contract-manifest:coordination:{graph_ref}",
        manifest_kind="coordination",
        task_ref=graph_ref,
        graph_id=graph_ref,
        graph_ref=graph_ref,
        global_contracts=tuple(global_contracts.values()),
        node_contracts=tuple(node_contracts),
        edge_handoff_contracts=tuple(edge_contracts),
        runtime_contracts=tuple(runtime_contracts),
        acceptance_contracts=tuple(acceptance_contracts.values()),
        issues=tuple(issues),
        metadata={
            "compiler": "contract_compiler.v1",
            "agent_group_id": coordination_task.agent_group_id,
            "communication_protocol_id": getattr(communication_protocol, "protocol_id", "") or "",
            "layered_graph": _layered_graph_manifest_payload(graph_spec),
        },
    )


def _layered_graph_manifest_payload(graph_spec: TaskGraphRuntimeSpec) -> dict[str, Any]:
    return {
        "authority": "task_system.layered_graph_runtime_spec",
        "graph_id": graph_spec.graph_id,
        "resource_nodes": [dict(item) for item in graph_spec.resource_nodes],
        "temporal_edges": [dict(item) for item in graph_spec.temporal_edges],
        "memory_edges": [dict(item) for item in graph_spec.memory_edges],
        "artifact_context_edges": [dict(item) for item in graph_spec.artifact_context_edges],
        "revision_edges": [dict(item) for item in graph_spec.revision_edges],
        "loop_frames": [dict(item) for item in graph_spec.loop_frames],
        "memory_matrix": dict(graph_spec.memory_matrix),
        "summary": {
            "resource_node_count": len(graph_spec.resource_nodes),
            "temporal_edge_count": len(graph_spec.temporal_edges),
            "memory_edge_count": len(graph_spec.memory_edges),
            "artifact_context_edge_count": len(graph_spec.artifact_context_edges),
            "revision_edge_count": len(graph_spec.revision_edges),
            "loop_frame_count": len(graph_spec.loop_frames),
        },
    }


def _collect_contract(
    *,
    registry: TaskContractRegistry,
    contract_id: str,
    source_ref: str,
    purpose: str,
    global_contracts: dict[str, CompiledGlobalContract],
    acceptance_contracts: dict[str, CompiledAcceptanceContract],
    issues: list[ContractCompileIssue],
    node_id: str = "",
    edge_id: str = "",
) -> ContractSpec | None:
    normalized = str(contract_id or "").strip()
    if not normalized:
        issues.append(
            ContractCompileIssue(
                code=f"{purpose}_missing",
                message=f"{purpose} 缺少契约引用。",
                severity="error",
                source_ref=source_ref,
                node_id=node_id,
                edge_id=edge_id,
            )
        )
        return None
    spec = registry.get_contract_spec(normalized)
    if spec is None:
        issues.append(
            ContractCompileIssue(
                code="contract_spec_missing",
                message=f"契约引用不存在：{normalized}",
                severity="error",
                source_ref=source_ref,
                contract_id=normalized,
                node_id=node_id,
                edge_id=edge_id,
            )
        )
        return None
    global_contracts[normalized] = CompiledGlobalContract(
        contract_id=spec.contract_id,
        title_zh=spec.title_zh,
        contract_kind=spec.contract_kind,
        source_ref=source_ref,
        input_fields=tuple(item.to_dict() for item in spec.input_fields),
        output_fields=tuple(item.to_dict() for item in spec.output_fields),
        metadata={"purpose": purpose, "version": spec.version},
    )
    acceptance_contracts[normalized] = CompiledAcceptanceContract(
        contract_id=spec.contract_id,
        rule_count=len(spec.acceptance_rules),
        rule_refs=tuple(item.rule_id for item in spec.acceptance_rules),
        source_ref=source_ref,
    )
    return spec


def _compile_runtime_contracts(
    *,
    agent_profiles: tuple[AgentRuntimeProfile, ...],
    runtime_lane: str,
    output_contract_id: str,
    issues: list[ContractCompileIssue],
) -> list[CompiledRuntimeContract]:
    compiled: list[CompiledRuntimeContract] = []
    for profile in agent_profiles:
        _validate_agent_profile(
            profile=profile,
            runtime_lane=runtime_lane,
            output_contract_id=output_contract_id,
            issues=issues,
        )
        profile_issue_count = sum(1 for item in issues if item.agent_id == profile.agent_id and item.severity == "error")
        compiled.append(
            CompiledRuntimeContract(
                agent_id=profile.agent_id,
                agent_profile_id=profile.agent_profile_id,
                allowed_runtime_lanes=profile.allowed_runtime_lanes,
                allowed_operations=profile.allowed_operations,
                allowed_memory_scopes=profile.allowed_memory_scopes,
                validation_state="invalid" if profile_issue_count else "valid",
                metadata={
                    "output_contracts": list(profile.output_contracts),
                },
            )
        )
    return compiled


def _validate_agent_profile(
    *,
    profile: AgentRuntimeProfile,
    runtime_lane: str,
    output_contract_id: str,
    issues: list[ContractCompileIssue],
    node_id: str = "",
) -> None:
    if runtime_lane and profile.allowed_runtime_lanes and runtime_lane not in profile.allowed_runtime_lanes:
        issues.append(
            ContractCompileIssue(
                code="runtime_lane_not_allowed",
                message=f"Agent runtime profile 不允许 runtime lane：{runtime_lane}",
                severity="error",
                agent_id=profile.agent_id,
                node_id=node_id,
            )
        )
    if output_contract_id and profile.output_contracts and output_contract_id not in profile.output_contracts:
        issues.append(
            ContractCompileIssue(
                code="runtime_output_contract_not_allowed",
                message=f"Agent runtime profile 不允许输出契约：{output_contract_id}",
                severity="error",
                contract_id=output_contract_id,
                agent_id=profile.agent_id,
                node_id=node_id,
            )
        )
