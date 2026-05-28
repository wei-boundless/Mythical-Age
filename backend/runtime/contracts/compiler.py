from __future__ import annotations

from typing import Any

from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from task_system.contracts.contract_definition_models import ContractSpec
from task_system.registry.contract_registry import TaskContractRegistry
from task_system.compiler.coordination_graph_models import TaskGraphRuntimeSpec
from task_system.registry.flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol
from task_system.registry.workflow_models import TaskWorkflowBinding

DEFAULT_A2A_MESSAGE_TYPE = "message/send"
from .compiler_models import (
    CompiledAcceptanceContract,
    CompiledEdgeHandoffContract,
    CompiledGlobalContract,
    CompiledGraphModuleHandoffContract,
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
                input_contract_id=input_contract_id if index == 1 else "",
                output_contract_id=step_contract_id,
                contract_refs=tuple(ref for ref in (input_contract_id if index == 1 else "", step_contract_id) if ref),
                source_refs=(workflow.workflow_id, task.task_id),
            )
        )

    runtime_contracts = _compile_runtime_contracts(
        agent_profiles=tuple(item for item in (agent_profile,) if item is not None),
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
    graph_contract_bindings = _contract_bindings_payload(dict(graph_spec.diagnostics or {}).get("contract_bindings"))
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
        node_bindings = _contract_bindings_payload(node_metadata.get("contract_bindings"))
        schema_bindings = dict(node_bindings.get("schema") or {})
        execution_bindings = dict(node_bindings.get("execution") or {})
        artifact_bindings = dict(node_bindings.get("artifact") or {})
        memory_bindings = dict(node_bindings.get("memory") or {})
        acceptance_bindings = dict(node_bindings.get("acceptance") or {})
        runtime_bindings = dict(node_bindings.get("runtime") or {})
        unit_batch_bindings = dict(node_bindings.get("unit_batch") or {})
        governance_bindings = dict(node_bindings.get("governance") or {})
        legacy_contract_fields = dict(node_metadata.get("legacy_contract_fields") or {})
        legacy_input_contract_id = str(legacy_contract_fields.get("input_contract_id") or getattr(node, "input_contract_id", "") or node_metadata.get("input_contract_id") or "").strip()
        legacy_output_contract_id = str(legacy_contract_fields.get("output_contract_id") or getattr(node, "output_contract_id", "") or node_metadata.get("output_contract_id") or "").strip()
        legacy_node_contract_id = str(legacy_contract_fields.get("node_contract_id") or node_metadata.get("node_contract_id") or node_metadata.get("contract_id") or "").strip()
        binding_node_contract_id = str(execution_bindings.get("node_contract_id") or execution_bindings.get("contract_id") or "").strip()
        explicit_input_contract_id = str(
            schema_bindings.get("input_contract_id")
            or legacy_input_contract_id
            or ""
        ).strip()
        explicit_output_contract_id = str(
            schema_bindings.get("output_contract_id")
            or legacy_output_contract_id
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
                    binding_node_contract_id or legacy_node_contract_id,
                    *[
                        str(item).strip()
                        for item in list(node_metadata.get("contract_refs") or [])
                        if str(item).strip()
                    ],
                    *[
                        str(item).strip()
                        for item in list(execution_bindings.get("contract_refs") or [])
                        if str(item).strip()
                    ],
                ]
            )
            if ref
        )
        _append_contract_binding_conflicts(
            issues=issues,
            source_ref=f"{graph_ref}:{node.node_id}",
            node_id=node.node_id,
            legacy_values={
                "metadata.input_contract_id": legacy_input_contract_id,
                "metadata.output_contract_id": legacy_output_contract_id,
                "metadata.node_contract_id": legacy_node_contract_id,
            },
            binding_values={
                "schema.input_contract_id": str(schema_bindings.get("input_contract_id") or "").strip(),
                "schema.output_contract_id": str(schema_bindings.get("output_contract_id") or "").strip(),
                "execution.node_contract_id": str(execution_bindings.get("node_contract_id") or "").strip(),
            },
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
        elif node.task_id and not str(node.task_id or "").startswith("task_graph.node."):
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
                input_contract_id=input_contract_id,
                output_contract_id=output_contract_id,
                contract_refs=tuple(ref for ref in (input_contract_id, output_contract_id, *explicit_node_contract_refs) if ref),
                source_refs=(graph_ref, node.task_id),
                schema_bindings=schema_bindings,
                execution_bindings=execution_bindings,
                artifact_bindings=artifact_bindings,
                memory_bindings=memory_bindings,
                acceptance_bindings=acceptance_bindings,
                runtime_bindings=runtime_bindings,
                unit_batch_bindings=unit_batch_bindings,
                governance_bindings=governance_bindings,
                metadata={
                    "role": node.role,
                    "role_prompt": str(node_metadata.get("role_prompt") or "").strip(),
                    "explicit_node_contract_refs": explicit_node_contract_refs,
                    "context_visibility_policy": dict(getattr(node, "context_visibility_policy", {}) or {}),
                    "memory_read_policy": dict(getattr(node, "memory_read_policy", {}) or {}),
                    "memory_writeback_policy": dict(getattr(node, "memory_writeback_policy", {}) or {}),
                    "dynamic_memory_read_policy": dict(getattr(node, "dynamic_memory_read_policy", {}) or {}),
                    "review_gate_policy": dict(getattr(node, "review_gate_policy", {}) or {}),
                    "human_gate_policy": dict(getattr(node, "human_gate_policy", {}) or {}),
                    "artifact_policy": dict(getattr(node, "artifact_policy", {}) or {}),
                    "stream_policy": dict(getattr(node, "stream_policy", {}) or {}),
                    "contract_bindings": node_bindings,
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
                issues=issues,
                node_id=node.node_id,
            )

    edge_contracts: list[CompiledEdgeHandoffContract] = []
    protocol_payload_contracts = tuple(str(item).strip() for item in getattr(communication_protocol, "payload_contracts", ()) if str(item).strip())
    for edge in graph_spec.edges:
        metadata = dict(edge.metadata or {})
        edge_bindings = _contract_bindings_payload(metadata.get("contract_bindings"))
        edge_schema_bindings = dict(edge_bindings.get("schema") or {})
        edge_handoff_bindings = dict(edge_bindings.get("handoff") or {})
        edge_temporal_bindings = dict(edge_bindings.get("temporal") or {})
        edge_memory_bindings = dict(edge_bindings.get("memory") or {})
        edge_artifact_bindings = dict(edge_bindings.get("artifact") or {})
        edge_governance_bindings = dict(edge_bindings.get("governance") or {})
        legacy_contract_fields = dict(metadata.get("legacy_contract_fields") or {})
        legacy_payload_contract_id = str(legacy_contract_fields.get("payload_contract_id") or getattr(edge, "payload_contract_id", "") or metadata.get("payload_contract_id") or metadata.get("contract_id") or "").strip()
        binding_payload_contract_id = str(edge_schema_bindings.get("payload_contract_id") or "").strip()
        contract_refs = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in [
                    binding_payload_contract_id or legacy_payload_contract_id,
                    *list(metadata.get("contract_refs") or []),
                    *protocol_payload_contracts,
                ]
                if str(item or "").strip()
            )
        )
        _append_contract_binding_conflicts(
            issues=issues,
            source_ref=f"{graph_ref}:{edge.edge_id}",
            edge_id=edge.edge_id,
            legacy_values={"edge.payload_contract_id": legacy_payload_contract_id},
            binding_values={"schema.payload_contract_id": str(edge_schema_bindings.get("payload_contract_id") or "").strip()},
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
                schema_bindings=edge_schema_bindings,
                handoff_bindings=edge_handoff_bindings,
                temporal_bindings=edge_temporal_bindings,
                memory_bindings=edge_memory_bindings,
                artifact_bindings=edge_artifact_bindings,
                governance_bindings=edge_governance_bindings,
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
                    "contract_bindings": edge_bindings,
                },
            )
        )

    graph_module_handoff_contracts = _compile_graph_module_handoff_contracts(
        contract_registry=contract_registry,
        graph_ref=graph_ref,
        graph_spec=graph_spec,
        global_contracts=global_contracts,
        acceptance_contracts=acceptance_contracts,
        issues=issues,
    )

    runtime_contracts = _compile_runtime_contracts(
        agent_profiles=agent_profiles,
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
        graph_module_handoff_contracts=tuple(graph_module_handoff_contracts),
        runtime_contracts=tuple(runtime_contracts),
        acceptance_contracts=tuple(acceptance_contracts.values()),
        issues=tuple(issues),
        graph_contract_bindings=graph_contract_bindings,
        metadata={
            "compiler": "contract_compiler.v1",
            "agent_group_id": coordination_task.agent_group_id,
            "communication_protocol_id": getattr(communication_protocol, "protocol_id", "") or "",
            "layered_graph": _layered_graph_manifest_payload(graph_spec),
            "graph_module_runtime_plans": [item.to_dict() for item in getattr(graph_spec, "graph_module_runtime_plans", ())],
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
        "graph_module_runtime_plans": [item.to_dict() for item in getattr(graph_spec, "graph_module_runtime_plans", ())],
        "memory_matrix": dict(graph_spec.memory_matrix),
        "summary": {
            "resource_node_count": len(graph_spec.resource_nodes),
            "temporal_edge_count": len(graph_spec.temporal_edges),
            "memory_edge_count": len(graph_spec.memory_edges),
            "artifact_context_edge_count": len(graph_spec.artifact_context_edges),
            "revision_edge_count": len(graph_spec.revision_edges),
            "loop_frame_count": len(graph_spec.loop_frames),
            "graph_module_runtime_plan_count": len(getattr(graph_spec, "graph_module_runtime_plans", ())),
        },
    }


def _compile_graph_module_handoff_contracts(
    *,
    contract_registry: TaskContractRegistry,
    graph_ref: str,
    graph_spec: TaskGraphRuntimeSpec,
    global_contracts: dict[str, CompiledGlobalContract],
    acceptance_contracts: dict[str, CompiledAcceptanceContract],
    issues: list[ContractCompileIssue],
) -> list[CompiledGraphModuleHandoffContract]:
    compiled: list[CompiledGraphModuleHandoffContract] = []
    for plan in getattr(graph_spec, "graph_module_runtime_plans", ()) or ():
        metadata = dict(getattr(plan, "metadata", {}) or {})
        plan_bindings = _contract_bindings_payload(metadata.get("contract_bindings"))
        handoff_bindings = dict(plan_bindings.get("handoff") or {})
        runtime_bindings = dict(plan_bindings.get("runtime") or {})
        governance_bindings = dict(plan_bindings.get("governance") or {})
        raw_node = dict(metadata.get("raw_node") or {})
        binding_handoff_contract_id = str(handoff_bindings.get("handoff_contract_id") or "").strip()
        plan_handoff_contract_id = str(getattr(plan, "handoff_contract_id", "") or "").strip()
        metadata_legacy_fields = dict(metadata.get("legacy_contract_fields") or {})
        raw_node_legacy_fields = dict(dict(raw_node.get("metadata") or {}).get("legacy_contract_fields") or {})
        legacy_handoff_contract_id = str(
            metadata_legacy_fields.get("handoff_contract_id")
            or raw_node_legacy_fields.get("handoff_contract_id")
            or raw_node.get("handoff_contract_id")
            or ""
        ).strip()
        handoff_contract_id = binding_handoff_contract_id or plan_handoff_contract_id or legacy_handoff_contract_id
        source_ref = f"{graph_ref}:{plan.plan_id}"
        _append_contract_binding_conflicts(
            issues=issues,
            source_ref=source_ref,
            node_id=plan.runtime_node_id,
            legacy_values={"node.handoff_contract_id": legacy_handoff_contract_id},
            binding_values={"handoff.handoff_contract_id": binding_handoff_contract_id},
        )
        if handoff_contract_id:
            _collect_contract(
                registry=contract_registry,
                contract_id=handoff_contract_id,
                source_ref=source_ref,
                purpose="graph_module_handoff_contract",
                global_contracts=global_contracts,
                acceptance_contracts=acceptance_contracts,
                issues=issues,
                node_id=plan.runtime_node_id,
            )
        else:
            issues.append(
                ContractCompileIssue(
                    code="graph_module_handoff_contract_missing",
                    message=f"图模块缺少导入图模块提交包 handoff 契约：{plan.runtime_node_id}",
                    severity="warning",
                    source_ref=source_ref,
                    node_id=plan.runtime_node_id,
                )
            )
        compiled.append(
            CompiledGraphModuleHandoffContract(
                plan_id=plan.plan_id,
                importing_graph_id=plan.importing_graph_id,
                runtime_node_id=plan.runtime_node_id,
                unit_id=plan.unit_id,
                linked_graph_id=plan.linked_graph_id,
                handoff_contract_id=handoff_contract_id,
                contract_refs=tuple(ref for ref in (handoff_contract_id,) if ref),
                version_ref=plan.version_ref,
                input_port_id=plan.input_port_id,
                output_port_id=plan.output_port_id,
                source_refs=(graph_ref, source_ref),
                handoff_bindings=handoff_bindings,
                runtime_bindings=runtime_bindings,
                governance_bindings=governance_bindings,
                metadata={
                    "source_node_id": str(raw_node.get("node_id") or metadata.get("source_node_id") or ""),
                    "visibility_policy": plan.visibility_policy,
                    "isolation_policy": plan.isolation_policy,
                    "detach_policy": plan.detach_policy,
                    "contract_bindings": plan_bindings,
                    "legacy_handoff_contract_id": legacy_handoff_contract_id,
                    "binding_handoff_contract_id": binding_handoff_contract_id,
                    "authority": "task_system.graph_module_handoff_contract",
                },
            )
        )
    return compiled


def _contract_bindings_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): dict(item) for key, item in value.items() if str(key).strip() and isinstance(item, dict)}


def _append_contract_binding_conflicts(
    *,
    issues: list[ContractCompileIssue],
    source_ref: str,
    legacy_values: dict[str, str],
    binding_values: dict[str, str],
    node_id: str = "",
    edge_id: str = "",
) -> None:
    for legacy_path, legacy_value in legacy_values.items():
        legacy = str(legacy_value or "").strip()
        if not legacy:
            continue
        legacy_key = legacy_path.rsplit(".", 1)[-1]
        binding_path = next((key for key in binding_values if key.endswith(f".{legacy_key}")), "")
        if not binding_path:
            continue
        binding = str(binding_values.get(binding_path) or "").strip()
        if not binding or binding == legacy:
            continue
        issues.append(
            ContractCompileIssue(
                code="contract_binding_conflict",
                message=f"历史契约字段 {legacy_path} 与 contract_bindings.{binding_path} 冲突：{legacy} != {binding}",
                severity="error",
                source_ref=source_ref,
                node_id=node_id,
                edge_id=edge_id,
                contract_id=binding,
            )
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
    issues: list[ContractCompileIssue],
) -> list[CompiledRuntimeContract]:
    compiled: list[CompiledRuntimeContract] = []
    for profile in agent_profiles:
        _validate_agent_profile(
            profile=profile,
            issues=issues,
        )
        profile_issue_count = sum(1 for item in issues if item.agent_id == profile.agent_id and item.severity == "error")
        compiled.append(
            CompiledRuntimeContract(
                agent_id=profile.agent_id,
                agent_profile_id=profile.agent_profile_id,
                allowed_operations=profile.allowed_operations,
                allowed_memory_scopes=profile.allowed_memory_scopes,
                validation_state="invalid" if profile_issue_count else "valid",
                metadata={},
            )
        )
    return compiled


def _validate_agent_profile(
    *,
    profile: AgentRuntimeProfile,
    issues: list[ContractCompileIssue],
    node_id: str = "",
) -> None:
    _ = node_id
    if not profile.enabled_runtime_modes:
        issues.append(
            ContractCompileIssue(
                code="runtime_modes_missing",
                message="Agent runtime profile 缺少 enabled_runtime_modes，无法确认可装配运行模式。",
                severity="warning",
                agent_id=profile.agent_id,
                node_id=node_id,
            )
        )
