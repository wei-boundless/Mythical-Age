from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agents.a2a_official_adapter import build_official_agent_card_catalog
from api.deps import require_runtime
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_loop.contract_compiler import (
    compile_coordination_contract_manifest,
    compile_workflow_contract_manifest,
)
from tasks import TaskContractRegistry, TaskFlowRegistry, TaskWorkflowRegistry, compile_coordination_graph_spec

router = APIRouter()


class ConversationEntryPolicyUpsertRequest(BaseModel):
    profile_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    default_workflow_id: str = Field(default="", max_length=160)
    default_projection_id: str = Field(default="", max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    conversation_entry_policy: str = Field(default="user_dialogue_to_main_agent", max_length=160)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class SpecificTaskRecordUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    task_title: str = Field(..., min_length=1, max_length=160)
    task_family: str = Field(..., min_length=1, max_length=80)
    task_mode: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    acceptance_profile_id: str = Field(default="", max_length=160)
    default_flow_contract_id: str = Field(default="", max_length=160)
    default_workflow_id: str = Field(default="", max_length=160)
    default_projection_policy: str = Field(default="", max_length=160)
    task_policy: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskDomainUpsertRequest(BaseModel):
    domain_id: str = Field(..., min_length=3, max_length=160)
    task_family: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    sort_order: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskProjectionBindingUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    projection_selection_mode: str = Field(default="task_default", max_length=120)
    allowed_projection_ids: list[str] = Field(default_factory=list)
    default_projection_id: str = Field(default="", max_length=160)
    projection_required: bool = False
    notes: str = Field(default="", max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskFlowContractBindingUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    flow_contract_id: str = Field(..., min_length=3, max_length=160)
    override_policy: str = Field(default="task_default", max_length=120)
    verification_gate_profile: str = Field(default="", max_length=160)
    fallback_policy: str = Field(default="fail_closed", max_length=120)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskExecutionPolicyUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    execution_chain_type: str = Field(default="single_agent_chain", max_length=120)
    runtime_agent_selection_policy: str = Field(default="orchestration_default", max_length=120)
    task_level: str = Field(default="standard", max_length=80)
    task_privilege: str = Field(default="bounded", max_length=80)
    allowed_agent_categories: list[str] = Field(default_factory=list)
    allow_worker_agent_spawn: bool = False
    worker_agent_blueprint_id: str = Field(default="", max_length=160)
    worker_agent_naming_rule: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskMemoryRequestProfileUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    requested_memory_layers: list[str] = Field(default_factory=list)
    requested_topics: list[str] = Field(default_factory=list)
    memory_priority: str = Field(default="normal", max_length=80)
    writeback_policy: str = Field(default="task_default", max_length=120)
    allow_long_term_memory: bool = False
    memory_scope_hint: str = Field(default="", max_length=160)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskWorkflowUpsertRequest(BaseModel):
    workflow_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    task_mode: str = Field(default="", max_length=80)
    compatible_projection_ids: list[str] = Field(default_factory=list)
    visible_skill_ids: list[str] = Field(default_factory=list)
    steps: list[dict[str, object]] = Field(default_factory=list)
    input_boundary: str = Field(default="")
    output_boundary: str = Field(default="")
    stop_conditions: list[str] = Field(default_factory=list)
    required_evidence_refs: list[str] = Field(default_factory=list)
    output_contract_id: str = Field(default="", max_length=160)
    prompt: str = Field(default="")
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class CoordinationTaskUpsertRequest(BaseModel):
    coordination_task_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    coordination_mode: str = Field(default="review_merge", max_length=80)
    coordinator_agent_id: str = Field(default="agent:0", min_length=3, max_length=160)
    task_family: str = Field(default="", max_length=80)
    domain_id: str = Field(default="", max_length=160)
    agent_group_id: str = Field(default="", max_length=160)
    participant_agent_ids: list[str] = Field(default_factory=list)
    topology_template_id: str = Field(default="", max_length=160)
    shared_context_policy: str = Field(default="explicit_refs_only", max_length=120)
    memory_sharing_policy: str = Field(default="isolated_by_default", max_length=120)
    handoff_policy: str = Field(default="filtered_handoff", max_length=120)
    conflict_resolution_policy: str = Field(default="coordinator_review", max_length=120)
    output_merge_policy: str = Field(default="coordinator_final_merge", max_length=120)
    stop_conditions: list[str] = Field(default_factory=list)
    subtask_refs: list[str] = Field(default_factory=list)
    graph_nodes: list[dict[str, object]] = Field(default_factory=list)
    graph_edges: list[dict[str, object]] = Field(default_factory=list)
    communication_modes: list[str] = Field(default_factory=list)
    enabled: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TopologyTemplateUpsertRequest(BaseModel):
    template_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    nodes: list[dict[str, object]] = Field(default_factory=list)
    edges: list[dict[str, object]] = Field(default_factory=list)
    handoff_rules: list[dict[str, object]] = Field(default_factory=list)
    join_policy: str = Field(default="explicit_join", max_length=120)
    failure_policy: str = Field(default="fail_closed", max_length=120)
    terminal_policy: str = Field(default="coordinator_terminal", max_length=120)
    enabled: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskCommunicationProtocolUpsertRequest(BaseModel):
    protocol_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    message_types: list[str] = Field(default_factory=list)
    payload_contracts: list[str] = Field(default_factory=list)
    signal_rules: list[str] = Field(default_factory=list)
    handoff_rules: list[str] = Field(default_factory=list)
    ack_policy: str = Field(default="explicit_ack", max_length=120)
    timeout_policy: str = Field(default="fail_closed", max_length=120)
    error_signal_policy: str = Field(default="raise_to_coordinator", max_length=120)
    enabled: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class ContractSpecUpsertRequest(BaseModel):
    contract_id: str = Field(..., min_length=3, max_length=200)
    title_zh: str = Field(..., min_length=1, max_length=200)
    title_en: str = Field(default="", max_length=200)
    contract_kind: str = Field(default="workflow", max_length=80)
    description: str = Field(default="", max_length=2000)
    input_fields: list[dict[str, object]] = Field(default_factory=list)
    output_fields: list[dict[str, object]] = Field(default_factory=list)
    artifact_requirements: list[dict[str, object]] = Field(default_factory=list)
    acceptance_rules: list[dict[str, object]] = Field(default_factory=list)
    runtime_requirements: list[dict[str, object]] = Field(default_factory=list)
    context_visibility_policy: dict[str, object] = Field(default_factory=dict)
    handoff_policy: dict[str, object] = Field(default_factory=dict)
    failure_policy: dict[str, object] = Field(default_factory=dict)
    human_gate_policy: dict[str, object] = Field(default_factory=dict)
    allowed_agent_kinds: list[str] = Field(default_factory=list)
    allowed_runtime_lanes: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", max_length=80)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


def _display_number(internal_id: str, *, prefix: str, fallback: str) -> str:
    value = str(internal_id or "").strip()
    if value.startswith(prefix):
        suffix = value[len(prefix):]
        if suffix.isdigit():
            return f"{fallback}-{int(suffix):03d}"
    return "未生成"


def _task_system_payload(base_dir) -> dict[str, object]:
    registry = TaskFlowRegistry(base_dir)
    contract_registry = TaskContractRegistry(base_dir)
    workflows = TaskWorkflowRegistry(base_dir).build_catalog()
    task_flows = [item.to_dict() for item in registry.list_flows()]
    entry_policies = [item.to_dict() for item in registry.list_general_task_profiles()]
    compat_specific_tasks = [item.to_dict() for item in registry.list_task_assignments()]
    specific_task_records = [item.to_dict() for item in registry.list_specific_task_records()]
    projection_bindings = [item.to_dict() for item in registry.list_projection_bindings()]
    flow_contract_bindings = [item.to_dict() for item in registry.list_flow_contract_bindings()]
    execution_policies = [item.to_dict() for item in registry.list_task_agent_adoption_plans()]
    memory_request_profiles = [item.to_dict() for item in registry.list_task_memory_request_profiles()]
    task_domains = [item.to_dict() for item in registry.list_task_domains()]
    coordination_tasks = [item.to_dict() for item in registry.list_coordination_tasks()]
    specific_task_records_by_id = {
        item.task_id: item
        for item in registry.list_specific_task_records()
    }
    coordination_graph_specs = [
        compile_coordination_graph_spec(
            coordination_task=item,
            specific_tasks=tuple(specific_task_records_by_id.values()),
            topology_template=registry.get_topology_template(item.topology_template_id),
            communication_protocol=registry.get_task_communication_protocol(
                str(dict(item.metadata or {}).get("protocol_id") or "")
            ),
        ).to_dict()
        for item in registry.list_coordination_tasks()
    ]
    topology_templates = [item.to_dict() for item in registry.list_topology_templates()]
    communication_protocols = [item.to_dict() for item in registry.list_task_communication_protocols()]
    contract_catalog = [item.to_dict() for item in registry.list_contract_descriptors()]
    contract_management = contract_registry.build_catalog()
    template_validation_matrix = registry.template_registry.build_validation_matrix()
    link_permission_matrix = registry.build_link_permission_matrix()
    agent_task_connections = registry.build_agent_task_connection_overview()
    agent_carrying_profiles = registry.build_agent_carrying_overview()
    connection_diagnostics = registry.build_connection_diagnostics()
    return {
        "authority": "task_system.management_console",
        "summary": {
            "entry_policy_count": len(entry_policies),
            "specific_task_record_count": len(specific_task_records),
            "specific_task_compat_view_count": len(compat_specific_tasks),
            "task_flow_count": len(task_flows),
            "workflow_count": workflows["summary"]["workflow_count"],
            "projection_binding_count": len(projection_bindings),
            "flow_contract_binding_count": len(flow_contract_bindings),
            "execution_policy_count": len(execution_policies),
            "memory_request_profile_count": len(memory_request_profiles),
            "task_domain_count": len(task_domains),
            "coordination_task_count": len(coordination_tasks),
            "topology_template_count": len(topology_templates),
            "communication_protocol_count": len(communication_protocols),
            "contract_descriptor_count": len(contract_catalog),
            "contract_spec_count": int(contract_management["summary"]["contract_spec_count"]),
            "contract_spec_validation_issue_count": int(contract_management["summary"]["validation_issue_count"]),
            "invalid_task_connection_count": int(agent_task_connections["summary"]["invalid_profile_count"]),
            "connection_issue_count": int(connection_diagnostics["summary"]["issue_count"]),
        },
        "task_management": {
            "entry_policies": entry_policies,
            "task_domains": task_domains,
            "specific_task_records": specific_task_records,
            "task_flow_definitions": task_flows,
            "workflow_resources": workflows["workflows"],
            "projection_bindings": projection_bindings,
            "flow_contract_bindings": flow_contract_bindings,
            "execution_policies": execution_policies,
            "memory_request_profiles": memory_request_profiles,
            "contract_catalog": contract_catalog,
            "compatibility_views": {
                "specific_tasks": compat_specific_tasks,
            },
        },
        "contract_management": contract_management,
        "coordination_management": {
            "coordination_tasks": coordination_tasks,
            "coordination_graph_specs": coordination_graph_specs,
            "topology_templates": topology_templates,
            "communication_protocols": communication_protocols,
            "a2a": {
                "protocol_version": "0.3.0",
                "transport": "JSONRPC",
                "protocol_locked": True,
                "agent_cards": build_official_agent_card_catalog(),
                "message_types": [
                    "message/send",
                    "message/stream",
                    "task/status",
                    "task/artifact",
                ],
                "part_types": ["text", "data", "file"],
                "task_states": [
                    "submitted",
                    "working",
                    "input-required",
                    "completed",
                    "canceled",
                    "failed",
                    "rejected",
                    "auth-required",
                    "unknown",
                ],
            },
        },
        "diagnostics": {
            "template_validation_matrix": template_validation_matrix,
            "link_permission_matrix": link_permission_matrix,
            "agent_task_connections": agent_task_connections,
            "agent_carrying_profiles": agent_carrying_profiles,
            "connection_diagnostics": connection_diagnostics,
        },
    }


@router.get("/tasks/overview")
async def task_system_overview() -> dict[str, object]:
    runtime = require_runtime()
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/next-ids")
async def task_system_next_ids() -> dict[str, object]:
    runtime = require_runtime()
    flow_registry = TaskFlowRegistry(runtime.base_dir)
    workflow_registry = TaskWorkflowRegistry(runtime.base_dir)
    task_id = flow_registry.next_specific_task_id()
    flow_id = flow_registry.next_flow_id()
    workflow_id = workflow_registry.next_workflow_id()
    coordination_task_id = flow_registry.next_coordination_task_id()
    topology_template_id = flow_registry.next_topology_template_id()
    return {
        "authority": "task_system.id_registry",
        "task_id": task_id,
        "flow_id": flow_id,
        "workflow_id": workflow_id,
        "coordination_task_id": coordination_task_id,
        "topology_template_id": topology_template_id,
        "display_numbers": {
            "task": _display_number(task_id, prefix="task.", fallback="任务"),
            "flow": _display_number(flow_id, prefix="flow.", fallback="流程"),
            "workflow": _display_number(workflow_id, prefix="workflow.", fallback="流程"),
            "coordination": _display_number(coordination_task_id, prefix="coord.", fallback="协作"),
            "topology": _display_number(topology_template_id, prefix="topology.", fallback="拓扑"),
        },
    }


@router.get("/tasks/workflows")
async def task_system_workflows() -> dict[str, object]:
    runtime = require_runtime()
    return TaskWorkflowRegistry(runtime.base_dir).build_catalog()


@router.put("/tasks/contracts/{contract_id}")
async def upsert_task_system_contract(contract_id: str, payload: ContractSpecUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.contract_id != contract_id:
        payload = payload.model_copy(update={"contract_id": contract_id})
    try:
        TaskContractRegistry(runtime.base_dir).upsert_contract_spec(payload.model_dump())
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/contracts/{contract_id}")
async def delete_task_system_contract(contract_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        deletion = TaskContractRegistry(runtime.base_dir).delete_contract_spec(contract_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _task_system_payload(runtime.base_dir)
    payload["last_deletion"] = deletion
    return payload


@router.get("/tasks/contract-manifests/workflows/{workflow_id}")
async def compile_task_system_workflow_contract_manifest(
    workflow_id: str,
    task_id: str = "",
) -> dict[str, object]:
    runtime = require_runtime()
    flow_registry = TaskFlowRegistry(runtime.base_dir)
    workflow_registry = TaskWorkflowRegistry(runtime.base_dir)
    workflow = workflow_registry.get_workflow(workflow_id)
    task = flow_registry.get_specific_task_record(task_id)
    if workflow is None or task is None:
        from fastapi import HTTPException

        missing = "workflow" if workflow is None else "task"
        raise HTTPException(status_code=404, detail=f"{missing} not found")
    task_policy = dict(task.task_policy or {})
    task_structure = dict(task_policy.get("task_structure") or {})
    metadata = dict(task.metadata or {})
    agent_id = str(metadata.get("agent_id") or "agent:0").strip() or "agent:0"
    runtime_lane = str(task_structure.get("runtime_lane") or metadata.get("runtime_lane") or "").strip()
    manifest = compile_workflow_contract_manifest(
        contract_registry=TaskContractRegistry(runtime.base_dir),
        task=task,
        workflow=workflow,
        agent_profile=AgentRuntimeRegistry(runtime.base_dir).get_profile(agent_id),
        agent_id=agent_id,
        runtime_lane=runtime_lane,
    )
    return manifest.to_dict()


@router.get("/tasks/contract-manifests/coordination/{coordination_task_id}")
async def compile_task_system_coordination_contract_manifest(coordination_task_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    coordination_task = registry.get_coordination_task(coordination_task_id)
    if coordination_task is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="coordination task not found")
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(str(dict(coordination_task.metadata or {}).get("protocol_id") or ""))
    graph_spec = compile_coordination_graph_spec(
        coordination_task=coordination_task,
        specific_tasks=specific_tasks,
        topology_template=registry.get_topology_template(coordination_task.topology_template_id),
        communication_protocol=protocol,
    )
    runtime_registry = AgentRuntimeRegistry(runtime.base_dir)
    agent_profiles = tuple(
        profile
        for profile in (
            runtime_registry.get_profile(str(node.agent_id or "").strip())
            for node in graph_spec.nodes
            if str(node.agent_id or "").strip()
        )
        if profile is not None
    )
    manifest = compile_coordination_contract_manifest(
        contract_registry=TaskContractRegistry(runtime.base_dir),
        coordination_task=coordination_task,
        graph_spec=graph_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    return manifest.to_dict()


@router.put("/tasks/workflows/{workflow_id}")
async def upsert_task_system_workflow(workflow_id: str, payload: TaskWorkflowUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.workflow_id != workflow_id:
        payload = payload.model_copy(update={"workflow_id": workflow_id})
    try:
        TaskWorkflowRegistry(runtime.base_dir).upsert_workflow(
            workflow_id=payload.workflow_id,
            title=payload.title,
            task_mode=payload.task_mode,
            compatible_projection_ids=tuple(payload.compatible_projection_ids),
            visible_skill_ids=tuple(payload.visible_skill_ids),
            steps=tuple(dict(item) for item in payload.steps),
            input_boundary=payload.input_boundary,
            output_boundary=payload.output_boundary,
            stop_conditions=tuple(payload.stop_conditions),
            required_evidence_refs=tuple(payload.required_evidence_refs),
            output_contract_id=payload.output_contract_id,
            prompt=payload.prompt,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/entry-policies/{profile_id}")
async def upsert_task_system_entry_policy(profile_id: str, payload: ConversationEntryPolicyUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.profile_id != profile_id:
        payload = payload.model_copy(update={"profile_id": profile_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_general_task_profile(
            profile_id=payload.profile_id,
            title=payload.title,
            default_agent_id="agent:0",
            default_workflow_id=payload.default_workflow_id,
            default_projection_id=payload.default_projection_id,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            conversation_entry_policy=payload.conversation_entry_policy,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/domains/{domain_id}")
async def upsert_task_system_domain(domain_id: str, payload: TaskDomainUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.domain_id != domain_id:
        payload = payload.model_copy(update={"domain_id": domain_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_domain(
            domain_id=payload.domain_id,
            task_family=payload.task_family,
            title=payload.title,
            description=payload.description,
            enabled=payload.enabled,
            sort_order=payload.sort_order,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/domains/{domain_id}")
async def delete_task_system_domain(domain_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        deletion = TaskFlowRegistry(runtime.base_dir).delete_task_domain(domain_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _task_system_payload(runtime.base_dir)
    payload["last_deletion"] = deletion
    return payload


@router.put("/tasks/specific-records/{task_id}")
async def upsert_task_system_specific_record(task_id: str, payload: SpecificTaskRecordUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_specific_task_record(
            task_id=payload.task_id,
            task_title=payload.task_title,
            task_family=payload.task_family,
            task_mode=payload.task_mode,
            description=payload.description,
            enabled=payload.enabled,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            acceptance_profile_id=payload.acceptance_profile_id,
            default_flow_contract_id=payload.default_flow_contract_id,
            default_workflow_id=payload.default_workflow_id,
            default_projection_policy=payload.default_projection_policy,
            task_policy=payload.task_policy,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/specific-records/{task_id}")
async def delete_task_system_specific_record(task_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        deletion = TaskFlowRegistry(runtime.base_dir).delete_specific_task_record(task_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _task_system_payload(runtime.base_dir)
    payload["last_deletion"] = deletion
    return payload


@router.put("/tasks/projection-bindings/{task_id}")
async def upsert_task_system_projection_binding(
    task_id: str,
    payload: TaskProjectionBindingUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_projection_binding(
            task_id=payload.task_id,
            projection_selection_mode=payload.projection_selection_mode,
            allowed_projection_ids=tuple(payload.allowed_projection_ids),
            default_projection_id=payload.default_projection_id,
            projection_required=payload.projection_required,
            notes=payload.notes,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/flow-contract-bindings/{task_id}")
async def upsert_task_system_flow_contract_binding(
    task_id: str,
    payload: TaskFlowContractBindingUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_flow_contract_binding(
            task_id=payload.task_id,
            flow_contract_id=payload.flow_contract_id,
            override_policy=payload.override_policy,
            verification_gate_profile=payload.verification_gate_profile,
            fallback_policy=payload.fallback_policy,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/execution-policies/{task_id}")
async def upsert_task_system_execution_policy(
    task_id: str,
    payload: TaskExecutionPolicyUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_agent_adoption_plan(
            task_id=payload.task_id,
            adoption_mode=(
                "adopt_with_projection"
                if payload.allow_worker_agent_spawn
                else "adopt_existing"
            ),
            default_agent_id="agent:0",
            allowed_agent_categories=tuple(payload.allowed_agent_categories),
            allow_worker_agent_spawn=payload.allow_worker_agent_spawn,
            worker_agent_blueprint_id=payload.worker_agent_blueprint_id,
            worker_agent_naming_rule=payload.worker_agent_naming_rule,
            notes=payload.notes,
            metadata={
                **payload.metadata,
                "execution_chain_type": payload.execution_chain_type,
                "runtime_agent_selection_policy": payload.runtime_agent_selection_policy,
                "task_level": payload.task_level,
                "task_privilege": payload.task_privilege,
            },
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/memory-request-profiles/{task_id}")
async def upsert_task_system_memory_request_profile(
    task_id: str,
    payload: TaskMemoryRequestProfileUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_memory_request_profile(
            task_id=payload.task_id,
            requested_memory_layers=tuple(payload.requested_memory_layers),
            requested_topics=tuple(payload.requested_topics),
            memory_priority=payload.memory_priority,
            writeback_policy=payload.writeback_policy,
            allow_long_term_memory=payload.allow_long_term_memory,
            memory_scope_hint=payload.memory_scope_hint,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/coordination-tasks/{coordination_task_id}")
async def upsert_task_system_coordination_task(
    coordination_task_id: str,
    payload: CoordinationTaskUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.coordination_task_id != coordination_task_id:
        payload = payload.model_copy(update={"coordination_task_id": coordination_task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_coordination_task(
            coordination_task_id=payload.coordination_task_id,
            title=payload.title,
            coordination_mode=payload.coordination_mode,
            coordinator_agent_id=payload.coordinator_agent_id,
            task_family=payload.task_family,
            domain_id=payload.domain_id,
            agent_group_id=payload.agent_group_id,
            participant_agent_ids=tuple(payload.participant_agent_ids),
            topology_template_id=payload.topology_template_id,
            shared_context_policy=payload.shared_context_policy,
            memory_sharing_policy=payload.memory_sharing_policy,
            handoff_policy=payload.handoff_policy,
            conflict_resolution_policy=payload.conflict_resolution_policy,
            output_merge_policy=payload.output_merge_policy,
            stop_conditions=tuple(payload.stop_conditions),
            subtask_refs=tuple(payload.subtask_refs),
            graph_nodes=tuple(dict(item) for item in payload.graph_nodes),
            graph_edges=tuple(dict(item) for item in payload.graph_edges),
            communication_modes=tuple(payload.communication_modes),
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/topology-templates/{template_id}")
async def upsert_task_system_topology_template(template_id: str, payload: TopologyTemplateUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.template_id != template_id:
        payload = payload.model_copy(update={"template_id": template_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_topology_template(
            template_id=payload.template_id,
            title=payload.title,
            nodes=tuple(dict(item) for item in payload.nodes),
            edges=tuple(dict(item) for item in payload.edges),
            handoff_rules=tuple(dict(item) for item in payload.handoff_rules),
            join_policy=payload.join_policy,
            failure_policy=payload.failure_policy,
            terminal_policy=payload.terminal_policy,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/communication-protocols/{protocol_id}")
async def upsert_task_system_communication_protocol(
    protocol_id: str,
    payload: TaskCommunicationProtocolUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.protocol_id != protocol_id:
        payload = payload.model_copy(update={"protocol_id": protocol_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_communication_protocol(
            protocol_id=payload.protocol_id,
            title=payload.title,
            message_types=tuple(payload.message_types),
            payload_contracts=tuple(payload.payload_contracts),
            signal_rules=tuple(payload.signal_rules),
            handoff_rules=tuple(payload.handoff_rules),
            ack_policy=payload.ack_policy,
            timeout_policy=payload.timeout_policy,
            error_signal_policy=payload.error_signal_policy,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)
