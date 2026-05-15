from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import require_runtime
from orchestration.agent_registry import AgentRegistry
from orchestration.agent_runtime_registry import AgentRuntimeRegistry
from orchestration.runtime_loop.contract_compiler import (
    compile_coordination_contract_manifest,
    compile_workflow_contract_manifest,
)
from orchestration.runtime_loop.runtime_assembly_builder import (
    build_node_runtime_assembly,
    build_single_agent_runtime_assembly,
)
from soul.facade import SoulFacade
from tasks import (
    TaskContractRegistry,
    TaskFlowRegistry,
    TaskWorkflowRegistry,
    compile_task_graph_definition_runtime_spec,
)

router = APIRouter()


TASK_GRAPH_PROMPT_METADATA_KEYS = {
    "role_prompt",
    "role_identity",
    "responsibility_scope",
    "responsibility_exclusions",
    "definition_of_done",
}


def _slug_ref(value: object, fallback: str = "node") -> str:
    raw = str(value or "").strip().lower() or fallback
    chars: list[str] = []
    for char in raw:
        if char.isalnum():
            chars.append(char)
        elif char in {":", ".", "_", "-"}:
            chars.append(".")
    normalized = ".".join(part for part in "".join(chars).replace("..", ".").split(".") if part)
    return normalized or fallback


def _build_task_graph_node_projection_prompt(node: dict[str, object], metadata: dict[str, object]) -> str:
    role_prompt = str(metadata.get("role_prompt") or "").strip()
    if role_prompt:
        return role_prompt
    role_identity = str(metadata.get("role_identity") or "").strip()
    responsibility_scope = str(metadata.get("responsibility_scope") or "").strip()
    responsibility_exclusions = str(metadata.get("responsibility_exclusions") or "").strip()
    definition_of_done = str(metadata.get("definition_of_done") or "").strip()
    if not any((role_identity, responsibility_scope, responsibility_exclusions, definition_of_done)):
        return ""
    title = str(node.get("title") or node.get("label") or node.get("node_id") or "任务协作者").strip()
    return "\n".join(
        [
            role_identity or f"你是一名{title}。",
            responsibility_scope if responsibility_scope.startswith("你只负责") else f"你只负责{responsibility_scope or '完成当前节点明确交付给你的职责。'}",
            responsibility_exclusions if responsibility_exclusions.startswith("你不负责") else f"你不负责{responsibility_exclusions or '扩展未经确认的任务范围。'}",
            definition_of_done if definition_of_done.startswith("你必须") else f"你必须{definition_of_done or '输出清晰结论、依据、遗留问题和下一步建议。'}",
        ]
    )


def _strip_task_graph_prompt_metadata(
    metadata: dict[str, object],
    *,
    prompt: str = "",
    projection_id: str = "",
    migration_status: str = "migrated",
) -> dict[str, object]:
    legacy_values = {
        key: metadata.get(key)
        for key in TASK_GRAPH_PROMPT_METADATA_KEYS
        if str(metadata.get(key) or "").strip()
    }
    cleaned = {
        key: value
        for key, value in metadata.items()
        if key not in TASK_GRAPH_PROMPT_METADATA_KEYS
    }
    if legacy_values or prompt:
        existing_migration = cleaned.get("legacy_prompt_migration")
        cleaned["legacy_prompt_migration"] = {
            **(existing_migration if isinstance(existing_migration, dict) else {}),
            "legacy_field_names": sorted(str(key) for key in legacy_values.keys()),
            "projection_id": projection_id,
            "migration_status": migration_status,
        }
    return cleaned


def _base_projection_card(base_dir) -> dict[str, object] | None:
    catalog = SoulFacade(base_dir).list_projection_cards()
    cards = [item for item in list(catalog.get("cards") or []) if isinstance(item, dict)]
    selected_projection_id = str(catalog.get("selected_projection_id") or "").strip()
    return next((item for item in cards if str(item.get("projection_id") or "") == selected_projection_id), None) or (cards[0] if cards else None)


def _migrate_task_graph_legacy_prompt_nodes(
    base_dir,
    *,
    graph_id: str,
    graph_title: str,
    task_family: str,
    nodes: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    base_card = _base_projection_card(base_dir)
    migrated_nodes: list[dict[str, object]] = []
    for node in nodes:
        next_node = dict(node)
        metadata = dict(next_node.get("metadata") or {})
        prompt = _build_task_graph_node_projection_prompt(next_node, metadata)
        projection_id = str(next_node.get("projection_id") or next_node.get("projection_overlay_id") or "").strip()
        if prompt and not projection_id and base_card:
            node_id = str(next_node.get("node_id") or next_node.get("id") or next_node.get("title") or "node").strip()
            projection_id = f"projection.taskgraph.{_slug_ref(graph_id, 'graph')}.{_slug_ref(node_id)}"
            SoulFacade(base_dir).upsert_projection_card(
                request={
                    "projection_id": projection_id,
                    "soul_id": str(base_card.get("soul_id") or ""),
                    "projection_kind": "task_graph_node",
                    "owner_system": "task_system",
                    "source_task_graph_refs": [graph_id],
                    "projection_name": f"{str(next_node.get('title') or node_id)} / 节点职责",
                    "role_type": str(next_node.get("work_posture") or next_node.get("role") or "task_graph_node"),
                    "task_mode": task_family or "task_graph_node",
                    "agent_profile_id": str(base_card.get("agent_profile_id") or "task_graph_node_agent"),
                    "projection_prompt": prompt,
                    "usage_summary": f"由 TaskGraph {graph_title or graph_id} 的节点职责迁移生成。",
                    "memory_policy_summary": "记忆读写权限由 TaskGraph 节点策略与 Agent Runtime Profile 决定。",
                    "output_contract_summary": "输出边界由 TaskGraph 节点契约和边交接契约决定。",
                },
                select_after_create=False,
            )
            next_node["projection_id"] = projection_id
            next_node["projection_overlay_id"] = projection_id
        if prompt or any(key in metadata for key in TASK_GRAPH_PROMPT_METADATA_KEYS):
            next_node["metadata"] = _strip_task_graph_prompt_metadata(
                metadata,
                prompt=prompt,
                projection_id=projection_id,
                migration_status="migrated" if projection_id else "pending_no_projection_base",
            )
        migrated_nodes.append(next_node)
    return tuple(migrated_nodes)


def _derived_count(effective_items: list[object], explicit_items: list[object], *, key_attr: str) -> int:
    explicit_keys = {
        str(getattr(item, key_attr, "") or "").strip()
        for item in explicit_items
        if str(getattr(item, key_attr, "") or "").strip()
    }
    return sum(
        1
        for item in effective_items
        if str(getattr(item, key_attr, "") or "").strip()
        and str(getattr(item, key_attr, "") or "").strip() not in explicit_keys
    )


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
    default_agent_id: str = Field(default="agent:0", max_length=160)
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


class TaskGraphUpsertRequest(BaseModel):
    graph_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    domain_id: str = Field(default="", max_length=160)
    task_family: str = Field(default="", max_length=80)
    graph_kind: str = Field(default="single_agent", max_length=80)
    entry_node_id: str = Field(default="", max_length=160)
    output_node_id: str = Field(default="", max_length=160)
    nodes: list[dict[str, object]] = Field(default_factory=list)
    edges: list[dict[str, object]] = Field(default_factory=list)
    graph_contract_id: str = Field(default="", max_length=160)
    default_protocol_id: str = Field(default="", max_length=160)
    working_memory_policy_profile_id: str = Field(default="", max_length=160)
    working_memory_policy: dict[str, object] = Field(default_factory=dict)
    runtime_policy: dict[str, object] = Field(default_factory=dict)
    context_policy: dict[str, object] = Field(default_factory=dict)
    publish_state: str = Field(default="draft", max_length=80)
    enabled: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskGraphBundleUpsertRequest(BaseModel):
    graph_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    coordination_mode: str = Field(default="review_merge", max_length=120)
    coordinator_agent_id: str = Field(default="agent:0", max_length=160)
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


CoordinationTaskUpsertRequest = TaskGraphBundleUpsertRequest


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
    agent_registry = AgentRegistry(base_dir)
    agents = [item.to_dict() for item in agent_registry.list_agents()]
    contract_registry = TaskContractRegistry(base_dir)
    workflows = TaskWorkflowRegistry(base_dir).build_catalog()
    visible_workflows = list(workflows.get("workflows") or [])
    task_flows = [item.to_dict() for item in registry.list_flows()]
    entry_policies = [item.to_dict() for item in registry.list_general_task_profiles()]
    task_assignments = [item.to_dict() for item in registry.list_task_assignments()]
    specific_task_records = [item.to_dict() for item in registry.list_specific_task_records()]
    projection_binding_models = registry.list_projection_bindings()
    explicit_projection_binding_models = registry.list_explicit_projection_bindings()
    flow_contract_binding_models = registry.list_flow_contract_bindings()
    explicit_flow_contract_binding_models = registry.list_explicit_flow_contract_bindings()
    execution_policy_models = registry.list_task_agent_adoption_plans()
    explicit_execution_policy_models = registry.list_explicit_task_agent_adoption_plans()
    memory_request_profile_models = registry.list_task_memory_request_profiles()
    explicit_memory_request_profile_models = registry.list_explicit_task_memory_request_profiles()
    projection_bindings = [model.to_dict() for model in projection_binding_models]
    flow_contract_bindings = [model.to_dict() for model in flow_contract_binding_models]
    execution_policies = [item.to_dict() for item in execution_policy_models]
    memory_request_profiles = [model.to_dict() for model in memory_request_profile_models]
    task_domains = [item.to_dict() for item in registry.list_task_domains()]
    task_graphs = [item.to_dict() for item in registry.list_task_graphs()]
    visible_task_ids = {str(item.get("task_id") or "") for item in specific_task_records}
    specific_task_records_by_id = {
        item.task_id: item
        for item in registry.list_specific_task_records()
        if item.task_id in visible_task_ids
    }
    topology_templates = [item.to_dict() for item in registry.list_topology_templates()]
    communication_protocols = [item.to_dict() for item in registry.list_task_communication_protocols()]
    communication_protocol_by_id = {
        str(item.get("protocol_id") or ""): item
        for item in communication_protocols
    }
    task_graph_specs = [
        compile_task_graph_definition_runtime_spec(
            graph=graph,
            specific_tasks=tuple(specific_task_records_by_id.values()),
            communication_protocol=registry.get_task_communication_protocol(
                str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
            )
            if str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "") in communication_protocol_by_id
            else None,
        ).to_dict()
        for graph in registry.list_task_graphs()
    ]
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
            "task_assignment_count": len(task_assignments),
            "task_flow_count": len(task_flows),
            "workflow_count": len(visible_workflows),
            "projection_binding_count": len(explicit_projection_binding_models),
            "derived_projection_binding_count": _derived_count(
                projection_binding_models,
                explicit_projection_binding_models,
                key_attr="binding_id",
            ),
            "effective_projection_binding_count": len(projection_binding_models),
            "flow_contract_binding_count": len(explicit_flow_contract_binding_models),
            "derived_flow_contract_binding_count": _derived_count(
                flow_contract_binding_models,
                explicit_flow_contract_binding_models,
                key_attr="binding_id",
            ),
            "effective_flow_contract_binding_count": len(flow_contract_binding_models),
            "execution_policy_count": len(explicit_execution_policy_models),
            "derived_execution_policy_count": _derived_count(
                execution_policy_models,
                explicit_execution_policy_models,
                key_attr="plan_id",
            ),
            "effective_execution_policy_count": len(execution_policy_models),
            "memory_request_profile_count": len(explicit_memory_request_profile_models),
            "derived_memory_request_profile_count": _derived_count(
                memory_request_profile_models,
                explicit_memory_request_profile_models,
                key_attr="profile_id",
            ),
            "effective_memory_request_profile_count": len(memory_request_profile_models),
            "task_domain_count": len(task_domains),
            "task_graph_count": len(task_graphs),
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
            "workflow_resources": visible_workflows,
            "projection_bindings": projection_bindings,
            "flow_contract_bindings": flow_contract_bindings,
            "execution_policies": execution_policies,
            "memory_request_profiles": memory_request_profiles,
            "contract_catalog": contract_catalog,
            "task_assignments": task_assignments,
        },
        "contract_management": contract_management,
        "task_graph_management": {
            "task_graphs": task_graphs,
            "task_graph_specs": task_graph_specs,
            "topology_templates": topology_templates,
            "communication_protocols": communication_protocols,
            "a2a": {
                "protocol_version": "0.3.0",
                "transport": "JSONRPC",
                "protocol_locked": True,
                "agent_cards": agents,
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
    graph_id = flow_registry.next_task_graph_id()
    topology_template_id = flow_registry.next_topology_template_id()
    return {
        "authority": "task_system.id_registry",
        "task_id": task_id,
        "flow_id": flow_id,
        "workflow_id": workflow_id,
        "graph_id": graph_id,
        "topology_template_id": topology_template_id,
        "display_numbers": {
            "task": _display_number(task_id, prefix="task.", fallback="任务"),
            "flow": _display_number(flow_id, prefix="flow.", fallback="流程"),
            "workflow": _display_number(workflow_id, prefix="workflow.", fallback="流程"),
            "graph": _display_number(graph_id, prefix="graph.", fallback="任务图"),
            "coordination": _display_number(graph_id, prefix="graph.", fallback="协作"),
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


def _graph_or_404(*, registry: TaskFlowRegistry, graph_id: str):
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="task graph not found")
    return graph


@router.get("/tasks/contract-manifests/task-graphs/{graph_id}")
async def compile_task_system_task_graph_contract_manifest(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = _graph_or_404(registry=registry, graph_id=graph_id)
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    graph_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
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
    graph_view = registry.derive_coordination_task_view_from_graph(graph)
    manifest = compile_coordination_contract_manifest(
        contract_registry=TaskContractRegistry(runtime.base_dir),
        coordination_task=graph_view,
        graph_spec=graph_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    return manifest.to_dict()


@router.get("/tasks/runtime-specs/task-graphs/{graph_id}")
async def compile_task_system_task_graph_runtime_spec(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="task graph not found")
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    graph_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
    )
    return graph_spec.to_dict()


@router.get("/tasks/runtime-assemblies/workflows/{workflow_id}")
async def build_task_system_workflow_runtime_assembly(
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
    agent_profile = AgentRuntimeRegistry(runtime.base_dir).get_profile(agent_id)
    manifest = compile_workflow_contract_manifest(
        contract_registry=TaskContractRegistry(runtime.base_dir),
        task=task,
        workflow=workflow,
        agent_profile=agent_profile,
        agent_id=agent_id,
        runtime_lane=runtime_lane,
    )
    assembly = build_single_agent_runtime_assembly(
        manifest=manifest,
        agent_profile=agent_profile,
        explicit_inputs={},
        runtime_lane=runtime_lane,
    )
    return assembly.to_dict()


@router.get("/tasks/runtime-assemblies/task-graphs/{graph_id}/nodes/{node_id}")
async def build_task_system_task_graph_node_runtime_assembly(
    graph_id: str,
    node_id: str,
) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = _graph_or_404(registry=registry, graph_id=graph_id)
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    graph_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
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
    coordination_task = registry.derive_coordination_task_view_from_graph(graph)
    manifest = compile_coordination_contract_manifest(
        contract_registry=TaskContractRegistry(runtime.base_dir),
        coordination_task=coordination_task,
        graph_spec=graph_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    graph_node = next((node for node in graph_spec.nodes if node.node_id == node_id), None)
    if graph_node is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="node not found")
    assembly = build_node_runtime_assembly(
        manifest=manifest,
        node_id=node_id,
        agent_profile=runtime_registry.get_profile(graph_node.agent_id),
        explicit_inputs={},
    )
    return assembly.to_dict()


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
            default_agent_id=payload.default_agent_id,
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


@router.put("/tasks/task-graphs/{graph_id}")
async def upsert_task_system_task_graph(
    graph_id: str,
    payload: TaskGraphUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.graph_id != graph_id:
        payload = payload.model_copy(update={"graph_id": graph_id})
    try:
        migrated_nodes = _migrate_task_graph_legacy_prompt_nodes(
            runtime.base_dir,
            graph_id=payload.graph_id,
            graph_title=payload.title,
            task_family=payload.task_family,
            nodes=tuple(dict(item) for item in payload.nodes),
        )
        TaskFlowRegistry(runtime.base_dir).upsert_task_graph(
            graph_id=payload.graph_id,
            title=payload.title,
            domain_id=payload.domain_id,
            task_family=payload.task_family,
            graph_kind=payload.graph_kind,
            entry_node_id=payload.entry_node_id,
            output_node_id=payload.output_node_id,
            nodes=migrated_nodes,
            edges=tuple(dict(item) for item in payload.edges),
            graph_contract_id=payload.graph_contract_id,
            default_protocol_id=payload.default_protocol_id,
            working_memory_policy_profile_id=payload.working_memory_policy_profile_id,
            working_memory_policy=payload.working_memory_policy,
            runtime_policy=payload.runtime_policy,
            context_policy=payload.context_policy,
            publish_state=payload.publish_state,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/task-graph-bundles/{graph_id}")
async def upsert_task_system_task_graph_bundle(
    graph_id: str,
    payload: TaskGraphBundleUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.graph_id != graph_id:
        payload = payload.model_copy(update={"graph_id": graph_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_graph_task(
            graph_id=payload.graph_id,
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
