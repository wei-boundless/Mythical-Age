from __future__ import annotations

from typing import Any

from orchestration.agent_runtime_models import AgentRuntimeProfile
from tasks.contract_definition_models import ContractSpec
from tasks.contract_registry import TaskContractRegistry
from tasks.coordination_graph_models import CoordinationGraphSpec
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
        task_mode=workflow.task_mode or task.task_mode,
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
                task_mode=workflow.task_mode,
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
    graph_spec: CoordinationGraphSpec,
    specific_tasks: tuple[SpecificTaskRecord, ...] = (),
    communication_protocol: TaskCommunicationProtocol | None = None,
    agent_profiles: tuple[AgentRuntimeProfile, ...] = (),
) -> ContractManifest:
    issues: list[ContractCompileIssue] = [
        ContractCompileIssue(
            code=f"graph_{item.code}",
            message=item.message,
            severity=item.severity,
            node_id=item.node_id,
            edge_id=item.edge_id,
            source_ref=graph_spec.graph_id,
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
        input_contract_id = str(getattr(task, "input_contract_id", "") or "").strip()
        output_contract_id = str(getattr(task, "output_contract_id", "") or "").strip()
        node_metadata = dict(node.metadata or {})
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
        if task is not None:
            for contract_id, purpose in (
                (input_contract_id, "node_input_contract"),
                (output_contract_id, "node_output_contract"),
            ):
                _collect_contract(
                    registry=contract_registry,
                    contract_id=contract_id,
                    source_ref=f"{coordination_task.coordination_task_id}:{node.node_id}",
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
                    source_ref=coordination_task.coordination_task_id,
                    node_id=node.node_id,
                    contract_id=node.task_id,
                )
            )
        for contract_id in explicit_node_contract_refs:
            _collect_contract(
                registry=contract_registry,
                contract_id=contract_id,
                source_ref=f"{coordination_task.coordination_task_id}:{node.node_id}",
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
                input_contract_id=input_contract_id,
                output_contract_id=output_contract_id,
                contract_refs=tuple(ref for ref in (input_contract_id, output_contract_id, *explicit_node_contract_refs) if ref),
                source_refs=(coordination_task.coordination_task_id, node.task_id),
                metadata={"role": node.role, "explicit_node_contract_refs": explicit_node_contract_refs},
            )
        )
        profile = profiles_by_agent.get(node.agent_id)
        if profile is None and node.agent_id:
            issues.append(
                ContractCompileIssue(
                    code="runtime_profile_missing",
                    message=f"节点 Agent 缺少 runtime profile：{node.agent_id}",
                    severity="error",
                    source_ref=coordination_task.coordination_task_id,
                    node_id=node.node_id,
                    agent_id=node.agent_id,
                )
            )
        elif profile is not None and task is not None:
            _validate_agent_profile(
                profile=profile,
                task_mode=task.task_mode,
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
                source_ref=f"{coordination_task.coordination_task_id}:{edge.edge_id}",
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
                    source_ref=coordination_task.coordination_task_id,
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
                metadata={"business_mode": edge.mode, "protocol_id": getattr(communication_protocol, "protocol_id", "") or ""},
            )
        )

    runtime_contracts = _compile_runtime_contracts(
        agent_profiles=agent_profiles,
        task_mode="",
        runtime_lane="",
        output_contract_id="",
        issues=issues,
    )

    return ContractManifest(
        manifest_id=f"contract-manifest:coordination:{coordination_task.coordination_task_id}",
        manifest_kind="coordination",
        task_ref=coordination_task.coordination_task_id,
        coordination_task_id=coordination_task.coordination_task_id,
        graph_id=graph_spec.graph_id,
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
        },
    )


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
    task_mode: str,
    runtime_lane: str,
    output_contract_id: str,
    issues: list[ContractCompileIssue],
) -> list[CompiledRuntimeContract]:
    compiled: list[CompiledRuntimeContract] = []
    for profile in agent_profiles:
        _validate_agent_profile(
            profile=profile,
            task_mode=task_mode,
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
                    "allowed_task_modes": list(profile.allowed_task_modes),
                    "output_contracts": list(profile.output_contracts),
                },
            )
        )
    return compiled


def _validate_agent_profile(
    *,
    profile: AgentRuntimeProfile,
    task_mode: str,
    runtime_lane: str,
    output_contract_id: str,
    issues: list[ContractCompileIssue],
    node_id: str = "",
) -> None:
    if task_mode and profile.allowed_task_modes and task_mode not in profile.allowed_task_modes:
        issues.append(
            ContractCompileIssue(
                code="runtime_task_mode_not_allowed",
                message=f"Agent runtime profile 不允许任务模式：{task_mode}",
                severity="error",
                agent_id=profile.agent_id,
                node_id=node_id,
            )
        )
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
