from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_models import AgentRuntimeProfile
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from runtime.contracts.compiler import (
    compile_coordination_contract_manifest,
)
from runtime.contracts.compiler_models import ContractManifest
from runtime.contracts.runtime_assembly_builder import (
    build_node_runtime_assembly,
)
from runtime import bootstrap_scheduler_state
from soul.facade import SoulFacade
from task_system import (
    TaskContractRegistry,
    TaskFlowRegistry,
    TaskWorkflowRegistry,
    apply_task_graph_standard_view_update,
    build_task_graph_standard_view,
    compile_task_graph_definition_runtime_spec,
)
from task_system.compiler.coordination_graph_models import TaskGraphRuntimeSpec
from task_system.registry.flow_models import SpecificTaskRecord
from task_system.graphs.task_graph_models import validate_task_graph

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
    description: str = Field(default="", max_length=1000)
    runtime_lane: str = Field(default="", max_length=120)
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
    allow_worker_agent_spawn: bool = False
    worker_agent_blueprint_id: str = Field(default="", max_length=160)
    worker_agent_naming_rule: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskWorkflowUpsertRequest(BaseModel):
    workflow_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    task_mode: str = Field(default="", max_length=120)
    compatible_projection_ids: list[str] = Field(default_factory=list)
    visible_skill_ids: list[str] = Field(default_factory=list)
    steps: list[dict[str, object]] = Field(default_factory=list)
    input_boundary: str = Field(default="", max_length=1000)
    output_boundary: str = Field(default="", max_length=1000)
    stop_conditions: list[str] = Field(default_factory=list)
    required_evidence_refs: list[str] = Field(default_factory=list)
    output_contract_id: str = Field(default="", max_length=160)
    prompt: str = Field(default="", max_length=4000)
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
    contract_bindings: dict[str, object] = Field(default_factory=dict)
    default_protocol_id: str = Field(default="", max_length=160)
    working_memory_policy_profile_id: str = Field(default="", max_length=160)
    working_memory_policy: dict[str, object] = Field(default_factory=dict)
    runtime_policy: dict[str, object] = Field(default_factory=dict)
    context_policy: dict[str, object] = Field(default_factory=dict)
    publish_state: str = Field(default="draft", max_length=80)
    enabled: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskGraphStandardViewUpsertRequest(BaseModel):
    graph: dict[str, object] = Field(default_factory=dict)
    nodes: list[dict[str, object]] = Field(default_factory=list)
    edges: list[dict[str, object]] = Field(default_factory=list)
    resources: list[dict[str, object]] = Field(default_factory=list)
    timeline: dict[str, object] = Field(default_factory=dict)
    runtime_isolation: dict[str, object] = Field(default_factory=dict)
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


def _task_graph_overview_item(graph) -> dict[str, object]:
    issues = [item.to_dict() for item in validate_task_graph(graph)]
    error_count = sum(1 for item in issues if str(item.get("severity") or "") == "error")
    warning_count = sum(1 for item in issues if str(item.get("severity") or "") == "warning")
    return {
        "graph_id": graph.graph_id,
        "title": graph.title,
        "domain_id": graph.domain_id,
        "task_family": graph.task_family,
        "graph_kind": graph.graph_kind,
        "entry_node_id": graph.entry_node_id,
        "output_node_id": graph.output_node_id,
        "nodes": [],
        "edges": [],
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "graph_contract_id": graph.graph_contract_id,
        "default_protocol_id": graph.default_protocol_id,
        "working_memory_policy_profile_id": graph.working_memory_policy_profile_id,
        "working_memory_policy": graph.working_memory_policy,
        "runtime_policy": graph.runtime_policy,
        "context_policy": graph.context_policy,
        "publish_state": graph.publish_state,
        "enabled": graph.enabled,
        "metadata": graph.metadata,
        "issues": issues[:8],
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "valid": error_count == 0,
        "overview_mode": "summary",
    }


def _task_system_payload(base_dir) -> dict[str, object]:
    registry = TaskFlowRegistry(base_dir)
    workflow_registry = TaskWorkflowRegistry(base_dir)
    agent_registry = AgentRegistry(base_dir)
    agents = [item.to_dict() for item in agent_registry.list_agents()]
    contract_registry = TaskContractRegistry(base_dir)
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
    projection_bindings = [model.to_dict() for model in projection_binding_models]
    flow_contract_bindings = [model.to_dict() for model in flow_contract_binding_models]
    explicit_execution_task_ids = {item.task_id for item in explicit_execution_policy_models}
    execution_policies = [item.to_dict() for item in execution_policy_models]
    execution_policies.sort(
        key=lambda item: (
            str(item.get("task_id") or "") not in explicit_execution_task_ids,
            str(item.get("task_id") or ""),
        )
    )
    task_domains = [item.to_dict() for item in registry.list_task_domains()]
    workflow_resources = [item.to_dict() for item in workflow_registry.list_workflows()]
    task_graphs = [_task_graph_overview_item(item) for item in registry.list_task_graphs()]
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
    contract_catalog = [item.to_dict() for item in registry.list_contract_descriptors()]
    contract_management = contract_registry.build_catalog()
    runtime_recipe_validation_matrix = {
        "authority": "task_system.runtime_recipe_validation",
        "status": "removed",
        "rows": [],
        "template_protocol_removed": True,
        "replacement": "TaskGraph + runtime.recipe",
    }
    return {
        "authority": "task_system.management_console",
        "summary": {
            "entry_policy_count": len(entry_policies),
            "specific_task_record_count": len(specific_task_records),
            "task_assignment_count": len(task_assignments),
            "task_flow_count": len(task_flows),
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
            "task_domain_count": len(task_domains),
            "task_graph_count": len(task_graphs),
            "topology_template_count": len(topology_templates),
            "communication_protocol_count": len(communication_protocols),
            "contract_descriptor_count": len(contract_catalog),
            "contract_spec_count": int(contract_management["summary"]["contract_spec_count"]),
            "contract_spec_validation_issue_count": int(contract_management["summary"]["validation_issue_count"]),
            "invalid_task_connection_count": 0,
            "connection_issue_count": 0,
        },
        "task_management": {
            "entry_policies": entry_policies,
            "task_domains": task_domains,
            "specific_task_records": specific_task_records,
            "task_flow_definitions": task_flows,
            "projection_bindings": projection_bindings,
            "flow_contract_bindings": flow_contract_bindings,
            "execution_policies": execution_policies,
            "contract_catalog": contract_catalog,
            "task_assignments": task_assignments,
            "workflow_resources": workflow_resources,
        },
        "contract_management": contract_management,
        "task_graph_management": {
            "task_graphs": task_graphs,
            "task_graph_specs": [],
            "topology_templates": [],
            "communication_protocols": communication_protocols,
            "a2a": {
                "protocol_version": "0.3.0",
                "transport": "JSONRPC",
                "protocol_locked": True,
                "agent_cards": [],
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
                "overview_mode": "protocol_only",
            },
            "overview_mode": "lightweight",
        },
        "diagnostics": {
            "runtime_recipe_validation_matrix": runtime_recipe_validation_matrix,
            "template_validation_matrix": runtime_recipe_validation_matrix,
            "overview_mode": "lightweight",
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
    task_id = flow_registry.next_specific_task_id()
    flow_id = flow_registry.next_flow_id()
    workflow_id = TaskWorkflowRegistry(runtime.base_dir).next_workflow_id()
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


def _graph_or_404(*, registry: TaskFlowRegistry, graph_id: str):
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="task graph not found")
    return graph


def _compiled_task_graph_execution_parts(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    contract_registry = TaskContractRegistry(runtime.base_dir)
    runtime_registry = AgentRuntimeRegistry(runtime.base_dir)
    graph = _graph_or_404(registry=registry, graph_id=graph_id)
    specific_tasks = tuple(registry.list_specific_task_records())
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    standard_view = build_task_graph_standard_view(
        graph=graph,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        graph_lookup=registry,
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
    )
    agent_profiles = _agent_profiles_for_runtime_spec(
        runtime_registry=runtime_registry,
        runtime_spec=runtime_spec,
    )
    coordination_task = registry.derive_coordination_task_view_from_graph(graph)
    manifest = compile_coordination_contract_manifest(
        contract_registry=contract_registry,
        coordination_task=coordination_task,
        graph_spec=runtime_spec,
        specific_tasks=specific_tasks,
        communication_protocol=protocol,
        agent_profiles=agent_profiles,
    )
    scheduler_state = bootstrap_scheduler_state(
        runtime_spec=runtime_spec,
        mode="shadow",
    )
    assemblies, assembly_errors, graph_module_node_ids = _node_runtime_assemblies_for_spec(
        runtime_registry=runtime_registry,
        runtime_spec=runtime_spec,
        manifest=manifest,
    )
    graph_module_execution_plans, graph_module_plan_issues = _graph_module_execution_plans(
        registry=registry,
        contract_registry=contract_registry,
        runtime_registry=runtime_registry,
        importing_graph_id=graph.graph_id,
        runtime_spec=runtime_spec,
        specific_tasks=specific_tasks,
    )
    runtime_diagnostics = dict(getattr(runtime_spec, "diagnostics", {}) or {})
    return {
        "graph": graph,
        "standard_view": standard_view,
        "runtime_spec": runtime_spec,
        "manifest": manifest,
        "scheduler_state": scheduler_state,
        "node_runtime_assemblies": assemblies,
        "assembly_errors": assembly_errors,
        "graph_module_node_ids": sorted(graph_module_node_ids),
        "graph_module_execution_plans": graph_module_execution_plans,
        "graph_module_plan_issues": graph_module_plan_issues,
        "split_plans": [dict(item) for item in list(runtime_diagnostics.get("split_plans") or []) if isinstance(item, dict)],
        "split_merge_issues": [dict(item) for item in list(runtime_diagnostics.get("split_merge_issues") or []) if isinstance(item, dict)],
    }


def _agent_profiles_for_runtime_spec(
    *,
    runtime_registry: AgentRuntimeRegistry,
    runtime_spec: TaskGraphRuntimeSpec,
) -> tuple[AgentRuntimeProfile, ...]:
    return tuple(
        profile
        for profile in (
            runtime_registry.get_profile(str(node.agent_id or "").strip())
            for node in runtime_spec.nodes
            if str(node.agent_id or "").strip()
        )
        if profile is not None
    )


def _node_runtime_assemblies_for_spec(
    *,
    runtime_registry: AgentRuntimeRegistry,
    runtime_spec: TaskGraphRuntimeSpec,
    manifest: ContractManifest,
) -> tuple[list[dict[str, object]], list[dict[str, object]], set[str]]:
    assemblies: list[dict[str, object]] = []
    assembly_errors: list[dict[str, object]] = []
    graph_module_node_ids = {
        node.node_id
        for node in runtime_spec.nodes
        if node.node_type == "graph_module" or bool(dict(node.metadata or {}).get("graph_module"))
    }
    for node in runtime_spec.nodes:
        if node.node_id in graph_module_node_ids:
            continue
        try:
            assemblies.append(
                build_node_runtime_assembly(
                    manifest=manifest,
                    node_id=node.node_id,
                    agent_profile=runtime_registry.get_profile(node.agent_id),
                    explicit_inputs={},
                ).to_dict()
            )
        except ValueError as exc:
            assembly_errors.append(
                {
                    "node_id": node.node_id,
                    "code": "runtime_assembly_unavailable",
                    "message": str(exc),
                    "severity": "warning",
                }
            )
    return assemblies, assembly_errors, graph_module_node_ids


def _graph_module_execution_plans(
    *,
    registry: TaskFlowRegistry,
    contract_registry: TaskContractRegistry,
    runtime_registry: AgentRuntimeRegistry,
    importing_graph_id: str,
    runtime_spec: TaskGraphRuntimeSpec,
    specific_tasks: tuple[SpecificTaskRecord, ...],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    plans: list[dict[str, object]] = []
    package_issues: list[dict[str, object]] = []
    for graph_module_plan in getattr(runtime_spec, "graph_module_runtime_plans", ()) or ():
        plan_payload = graph_module_plan.to_dict()
        runtime_node = next((node for node in runtime_spec.nodes if node.node_id == graph_module_plan.runtime_node_id), None)
        linked_graph_id = str(graph_module_plan.linked_graph_id or "").strip()
        plan_issues: list[dict[str, object]] = []
        package = {
            "authority": "task_system.graph_module_execution_plan",
            "plan_id": graph_module_plan.plan_id,
            "importing_graph_id": importing_graph_id,
            "unit_id": graph_module_plan.unit_id,
            "runtime_node_id": graph_module_plan.runtime_node_id,
            "linked_graph_id": linked_graph_id,
            "version_ref": graph_module_plan.version_ref,
            "handoff_contract_id": graph_module_plan.handoff_contract_id,
            "input_port_id": graph_module_plan.input_port_id,
            "output_port_id": graph_module_plan.output_port_id,
            "isolation_policy": graph_module_plan.isolation_policy,
            "visibility_policy": graph_module_plan.visibility_policy,
            "detach_policy": graph_module_plan.detach_policy,
            "runtime_node": runtime_node.to_dict() if runtime_node is not None else None,
            "graph_module_runtime_plan": plan_payload,
            "imported_graph": None,
            "imported_standard_view_summary": {},
            "imported_runtime_spec_summary": {},
            "imported_contract_manifest_summary": {},
            "imported_scheduler_summary": {},
            "imported_node_runtime_assembly_summary": {},
            "issues": plan_issues,
            "valid": False,
        }
        if not linked_graph_id:
            plan_issues.append(
                _graph_module_execution_issue(
                    code="graph_module_linked_graph_id_missing",
                    message="图模块缺少 linked_graph_id，无法编译导入图模块执行计划。",
                    importing_graph_id=importing_graph_id,
                    runtime_node_id=graph_module_plan.runtime_node_id,
                    plan_id=graph_module_plan.plan_id,
                    linked_graph_id=linked_graph_id,
                    severity="error",
                )
            )
        elif linked_graph_id == importing_graph_id:
            plan_issues.append(
                _graph_module_execution_issue(
                    code="graph_module_self_reference",
                    message="图模块不能直接引用当前图自身作为导入图模块，否则运行计划会形成无限递归。",
                    importing_graph_id=importing_graph_id,
                    runtime_node_id=graph_module_plan.runtime_node_id,
                    plan_id=graph_module_plan.plan_id,
                    linked_graph_id=linked_graph_id,
                    severity="error",
                )
            )
        else:
            imported_graph = registry.get_task_graph(linked_graph_id)
            if imported_graph is None:
                plan_issues.append(
                    _graph_module_execution_issue(
                        code="graph_module_linked_graph_not_found",
                        message=f"图模块引用的导入图模块不存在：{linked_graph_id}",
                        importing_graph_id=importing_graph_id,
                        runtime_node_id=graph_module_plan.runtime_node_id,
                        plan_id=graph_module_plan.plan_id,
                        linked_graph_id=linked_graph_id,
                        severity="error",
                    )
                )
            else:
                imported_protocol = registry.get_task_communication_protocol(
                    str(imported_graph.default_protocol_id or dict(imported_graph.metadata or {}).get("protocol_id") or "")
                )
                imported_standard_view = build_task_graph_standard_view(
                    graph=imported_graph,
                    specific_tasks=specific_tasks,
                    communication_protocol=imported_protocol,
                    graph_lookup=registry,
                )
                imported_runtime_spec = compile_task_graph_definition_runtime_spec(
                    graph=imported_graph,
                    specific_tasks=specific_tasks,
                    communication_protocol=imported_protocol,
                )
                imported_agent_profiles = _agent_profiles_for_runtime_spec(
                    runtime_registry=runtime_registry,
                    runtime_spec=imported_runtime_spec,
                )
                imported_manifest = compile_coordination_contract_manifest(
                    contract_registry=contract_registry,
                    coordination_task=registry.derive_coordination_task_view_from_graph(imported_graph),
                    graph_spec=imported_runtime_spec,
                    specific_tasks=specific_tasks,
                    communication_protocol=imported_protocol,
                    agent_profiles=imported_agent_profiles,
                )
                imported_scheduler_state = bootstrap_scheduler_state(
                    runtime_spec=imported_runtime_spec,
                    mode="shadow",
                )
                imported_assemblies, imported_assembly_errors, imported_graph_module_node_ids = _node_runtime_assemblies_for_spec(
                    runtime_registry=runtime_registry,
                    runtime_spec=imported_runtime_spec,
                    manifest=imported_manifest,
                )
                standard_payload = imported_standard_view.to_dict()
                package["imported_graph"] = {
                    "graph_id": imported_graph.graph_id,
                    "title": imported_graph.title,
                    "domain_id": imported_graph.domain_id,
                    "task_family": imported_graph.task_family,
                    "publish_state": imported_graph.publish_state,
                    "enabled": imported_graph.enabled,
                }
                package["imported_standard_view_summary"] = {
                    "unit_count": len(standard_payload.get("units") or []),
                    "interface_count": len(standard_payload.get("interfaces") or []),
                    "port_edge_count": len(standard_payload.get("port_edges") or []),
                    "graph_module_runtime_count": len(standard_payload.get("graph_module_runtime") or []),
                    "issue_count": len(standard_payload.get("issues") or []),
                }
                package["imported_runtime_spec_summary"] = {
                    "graph_id": imported_runtime_spec.graph_id,
                    "valid": imported_runtime_spec.valid,
                    "node_count": len(imported_runtime_spec.nodes),
                    "edge_count": len(imported_runtime_spec.edges),
                    "start_node_ids": list(imported_runtime_spec.start_node_ids),
                    "terminal_node_ids": list(imported_runtime_spec.terminal_node_ids),
                    "graph_module_count": len(getattr(imported_runtime_spec, "graph_module_runtime_plans", ()) or ()),
                    "graph_module_node_ids": sorted(imported_graph_module_node_ids),
                    "issue_count": len(imported_runtime_spec.issues),
                }
                package["imported_contract_manifest_summary"] = {
                    "manifest_id": imported_manifest.manifest_id,
                    "valid": imported_manifest.valid,
                    "node_contract_count": len(imported_manifest.node_contracts),
                    "edge_handoff_contract_count": len(imported_manifest.edge_handoff_contracts),
                    "runtime_contract_count": len(imported_manifest.runtime_contracts),
                    "acceptance_contract_count": len(imported_manifest.acceptance_contracts),
                    "issue_count": len(imported_manifest.issues),
                }
                package["imported_scheduler_summary"] = {
                    "authority": imported_scheduler_state.authority,
                    "mode": imported_scheduler_state.mode,
                    "ready_node_ids": list(imported_scheduler_state.ready_node_ids),
                    "blocked_node_ids": list(imported_scheduler_state.blocked_node_ids),
                    "running_node_ids": list(imported_scheduler_state.running_node_ids),
                    "completed_node_ids": list(imported_scheduler_state.completed_node_ids),
                    "failed_node_ids": list(imported_scheduler_state.failed_node_ids),
                    "terminal_status": imported_scheduler_state.terminal_status,
                }
                package["imported_node_runtime_assembly_summary"] = {
                    "assembly_count": len(imported_assemblies),
                    "assembly_error_count": len(imported_assembly_errors),
                    "graph_module_node_count": len(imported_graph_module_node_ids),
                    "assembly_node_ids": [str(item.get("node_id") or "") for item in imported_assemblies],
                    "assembly_errors": imported_assembly_errors,
                }
                if not imported_runtime_spec.valid:
                    plan_issues.append(
                        _graph_module_execution_issue(
                            code="graph_module_imported_runtime_spec_invalid",
                            message=f"图模块导入图模块 RuntimeSpec 存在阻塞问题：{linked_graph_id}",
                            importing_graph_id=importing_graph_id,
                            runtime_node_id=graph_module_plan.runtime_node_id,
                            plan_id=graph_module_plan.plan_id,
                            linked_graph_id=linked_graph_id,
                            severity="error",
                        )
                    )
                if not imported_manifest.valid:
                    plan_issues.append(
                        _graph_module_execution_issue(
                            code="graph_module_imported_contract_manifest_invalid",
                            message=f"图模块导入图模块 ContractManifest 存在阻塞问题：{linked_graph_id}",
                            importing_graph_id=importing_graph_id,
                            runtime_node_id=graph_module_plan.runtime_node_id,
                            plan_id=graph_module_plan.plan_id,
                            linked_graph_id=linked_graph_id,
                            severity="error",
                        )
                    )
                package["imported_runtime_issues"] = [item.to_dict() for item in imported_runtime_spec.issues]
                package["imported_contract_issues"] = [item.to_dict() for item in imported_manifest.issues]
        package["valid"] = not any(str(issue.get("severity") or "error") == "error" for issue in plan_issues)
        plans.append(package)
        package_issues.extend(plan_issues)
    return plans, package_issues


def _graph_module_execution_issue(
    *,
    code: str,
    message: str,
    importing_graph_id: str,
    runtime_node_id: str,
    plan_id: str,
    linked_graph_id: str,
    severity: str,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "scope": "graph_module",
        "source_ref": f"{importing_graph_id}:{plan_id}",
        "node_id": runtime_node_id,
        "graph_id": importing_graph_id,
        "plan_id": plan_id,
        "linked_graph_id": linked_graph_id,
    }


def _task_graph_execution_object_trace_index(
    *,
    graph: object,
    runtime_spec: TaskGraphRuntimeSpec,
    manifest: ContractManifest,
    scheduler_state: object,
    node_runtime_assemblies: list[dict[str, object]],
    graph_module_execution_plans: list[dict[str, object]],
    split_plans: list[dict[str, object]],
) -> list[dict[str, object]]:
    runtime_nodes_by_id = {node.node_id: node for node in runtime_spec.nodes}
    runtime_edges_by_id = {edge.edge_id: edge for edge in runtime_spec.edges}
    node_contracts_by_id = {item.node_id: item for item in manifest.node_contracts}
    edge_contracts_by_id = {item.edge_id: item for item in manifest.edge_handoff_contracts}
    graph_module_contracts_by_plan_id = {
        item.plan_id: item
        for item in getattr(manifest, "graph_module_handoff_contracts", ()) or ()
    }
    assemblies_by_node_id = {
        str(item.get("node_id") or ""): item
        for item in node_runtime_assemblies
        if str(item.get("node_id") or "")
    }
    scheduler_payload = scheduler_state.to_dict() if hasattr(scheduler_state, "to_dict") else dict(scheduler_state or {})
    scheduler_nodes_by_id = {
        str(item.get("node_id") or ""): dict(item)
        for item in list(scheduler_payload.get("node_states") or [])
        if isinstance(item, dict) and str(item.get("node_id") or "")
    }
    scheduler_edges_by_id = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(scheduler_payload.get("edge_states") or [])
        if isinstance(item, dict) and str(item.get("edge_id") or "")
    }
    imported_plans_by_plan_id = {
        str(item.get("plan_id") or ""): dict(item)
        for item in graph_module_execution_plans
        if isinstance(item, dict) and str(item.get("plan_id") or "")
    }
    split_plans_by_node_id: dict[str, list[dict[str, object]]] = {}
    for item in split_plans:
        node_id = str(item.get("node_id") or "").strip()
        if node_id:
            split_plans_by_node_id.setdefault(node_id, []).append(dict(item))
    traces: list[dict[str, object]] = [
        {
            "object_type": "graph",
            "object_id": str(getattr(graph, "graph_id", "") or runtime_spec.graph_id),
            "title": str(getattr(graph, "title", "") or runtime_spec.graph_id),
            "source_path": "graph",
            "runtime_ref": {
                "runtime_spec_graph_id": runtime_spec.graph_id,
                "scheduler_graph_id": str(scheduler_payload.get("graph_id") or ""),
            },
            "manifest_ref": {
                "manifest_id": manifest.manifest_id,
                "graph_contract_binding_sections": sorted(str(key) for key in dict(manifest.graph_contract_bindings or {}).keys()),
            },
            "assembly_ref": {},
            "scheduler_ref": {
                "terminal_status": str(scheduler_payload.get("terminal_status") or ""),
                "ready_node_ids": list(scheduler_payload.get("ready_node_ids") or []),
                "blocked_node_ids": list(scheduler_payload.get("blocked_node_ids") or []),
            },
            "imported_plan_ref": {},
            "status": "ready" if runtime_spec.valid and manifest.valid else "blocked",
        }
    ]
    for node in getattr(graph, "nodes", ()) or ():
        node_id = str(getattr(node, "node_id", "") or "")
        runtime_node = runtime_nodes_by_id.get(node_id)
        node_contract = node_contracts_by_id.get(node_id)
        assembly = assemblies_by_node_id.get(node_id)
        scheduler_node = scheduler_nodes_by_id.get(node_id, {})
        node_split_plans = split_plans_by_node_id.get(node_id, [])
        traces.append(
            {
                "object_type": "node",
                "object_id": node_id,
                "title": str(getattr(node, "title", "") or node_id),
                "source_path": f"graph.nodes[{node_id}]",
                "runtime_ref": {
                    "node_id": runtime_node.node_id if runtime_node is not None else "",
                    "node_type": runtime_node.node_type if runtime_node is not None else "",
                    "task_ref": runtime_node.task_id if runtime_node is not None else "",
                },
                "manifest_ref": {
                    "node_contract_id": node_contract.node_id if node_contract is not None else "",
                    "contract_refs": list(node_contract.contract_refs) if node_contract is not None else [],
                },
                "assembly_ref": {
                    "assembly_id": str(assembly.get("assembly_id") or "") if assembly else "",
                    "context_section_count": len(list(assembly.get("context_sections") or [])) if assembly else 0,
                },
                "scheduler_ref": _scheduler_node_trace(scheduler_node),
                "imported_plan_ref": {
                    "split_plan_count": len(node_split_plans),
                    "split_plan_ids": [str(item.get("plan_id") or "") for item in node_split_plans],
                    "batch_count": sum(len(list(item.get("batches") or [])) for item in node_split_plans),
                },
                "status": str(scheduler_node.get("status") or ("ready" if runtime_node is not None else "uncompiled")),
            }
        )
    for edge in getattr(graph, "edges", ()) or ():
        edge_id = str(getattr(edge, "edge_id", "") or "")
        runtime_edge = runtime_edges_by_id.get(edge_id)
        edge_contract = edge_contracts_by_id.get(edge_id)
        scheduler_edge = scheduler_edges_by_id.get(edge_id, {})
        traces.append(
            {
                "object_type": "edge",
                "object_id": edge_id,
                "title": edge_id,
                "source_path": f"graph.edges[{edge_id}]",
                "runtime_ref": {
                    "edge_id": runtime_edge.edge_id if runtime_edge is not None else "",
                    "source_node_id": runtime_edge.source_node_id if runtime_edge is not None else "",
                    "target_node_id": runtime_edge.target_node_id if runtime_edge is not None else "",
                    "payload_contract_id": runtime_edge.payload_contract_id if runtime_edge is not None else "",
                },
                "manifest_ref": {
                    "edge_contract_id": edge_contract.edge_id if edge_contract is not None else "",
                    "contract_refs": list(edge_contract.contract_refs) if edge_contract is not None else [],
                },
                "assembly_ref": {},
                "scheduler_ref": {
                    "edge_id": str(scheduler_edge.get("edge_id") or ""),
                    "status": str(scheduler_edge.get("status") or ""),
                    "ack_required": bool(scheduler_edge.get("ack_required", False)),
                    "wait_policy": str(scheduler_edge.get("wait_policy") or ""),
                },
                "imported_plan_ref": {},
                "status": str(scheduler_edge.get("status") or ("ready" if runtime_edge is not None else "uncompiled")),
            }
        )
    for plan in getattr(runtime_spec, "graph_module_runtime_plans", ()) or ():
        runtime_node = runtime_nodes_by_id.get(plan.runtime_node_id)
        graph_module_contract = graph_module_contracts_by_plan_id.get(plan.plan_id)
        scheduler_node = scheduler_nodes_by_id.get(plan.runtime_node_id, {})
        imported_plan = imported_plans_by_plan_id.get(plan.plan_id, {})
        traces.append(
            {
                "object_type": "graph_module",
                "object_id": plan.unit_id,
                "title": plan.linked_graph_id or plan.unit_id,
                "source_path": f"metadata.timeline_blocks[{dict(plan.metadata or {}).get('timeline_block_id') or plan.plan_id}]",
                "runtime_ref": {
                    "plan_id": plan.plan_id,
                    "runtime_node_id": plan.runtime_node_id,
                    "linked_graph_id": plan.linked_graph_id,
                    "node_type": runtime_node.node_type if runtime_node is not None else "",
                },
                "manifest_ref": {
                    "graph_module_handoff_plan_id": graph_module_contract.plan_id if graph_module_contract is not None else "",
                    "handoff_contract_id": graph_module_contract.handoff_contract_id if graph_module_contract is not None else "",
                    "contract_refs": list(graph_module_contract.contract_refs) if graph_module_contract is not None else [],
                },
                "assembly_ref": {},
                "scheduler_ref": _scheduler_node_trace(scheduler_node),
                "imported_plan_ref": {
                    "plan_id": str(imported_plan.get("plan_id") or ""),
                    "valid": bool(imported_plan.get("valid", False)),
                    "linked_graph_id": str(imported_plan.get("linked_graph_id") or ""),
                    "issue_count": len(list(imported_plan.get("issues") or [])),
                },
                "status": str(scheduler_node.get("status") or ("ready" if runtime_node is not None else "uncompiled")),
            }
        )
    for plan in split_plans:
        plan_id = str(plan.get("plan_id") or "").strip()
        node_id = str(plan.get("node_id") or "").strip()
        batch_lifecycle_plans = [
            dict(item)
            for item in list(plan.get("batch_lifecycle_plans") or [])
            if isinstance(item, dict)
        ]
        merge_readiness_plan = dict(plan.get("merge_readiness_plan") or {})
        plan_issues = [dict(item) for item in list(plan.get("issues") or []) if isinstance(item, dict)]
        traces.append(
            {
                "object_type": "split_plan",
                "object_id": plan_id,
                "title": f"{str(plan.get('unit_kind') or 'unit')} x {len(list(plan.get('batches') or []))}",
                "source_path": f"graph.nodes[{node_id}].contract_bindings.unit_batch",
                "runtime_ref": {
                    "plan_id": plan_id,
                    "node_id": node_id,
                    "unit_kind": str(plan.get("unit_kind") or ""),
                    "batch_count": len(list(plan.get("batches") or [])),
                    "batch_lifecycle_plan_count": len(batch_lifecycle_plans),
                    "batch_lifecycle_step_count": sum(len(list(item.get("steps") or [])) for item in batch_lifecycle_plans),
                    "requested_count": int(plan.get("requested_count") or 0),
                    "batch_size": int(plan.get("batch_size") or 0),
                },
                "manifest_ref": {
                    "acceptance_mode": str(dict(plan.get("acceptance_policy") or {}).get("mode") or ""),
                    "merge_mode": str(dict(plan.get("merge_policy") or {}).get("mode") or ""),
                },
                "assembly_ref": {},
                "scheduler_ref": _scheduler_node_trace(scheduler_nodes_by_id.get(node_id, {})),
                "imported_plan_ref": {},
                "status": "blocked" if any(str(issue.get("severity") or "error") == "error" for issue in plan_issues) else "ready",
            }
        )
        for lifecycle_plan in batch_lifecycle_plans:
            lifecycle_steps = [
                dict(item)
                for item in list(lifecycle_plan.get("steps") or [])
                if isinstance(item, dict)
            ]
            traces.append(
                {
                    "object_type": "batch_lifecycle_plan",
                    "object_id": str(lifecycle_plan.get("plan_id") or ""),
                    "title": f"{str(lifecycle_plan.get('batch_id') or 'batch')} · {len(lifecycle_steps)} steps",
                    "source_path": f"graph.nodes[{node_id}].contract_bindings.runtime.batch_acceptance_policy",
                    "runtime_ref": {
                        "plan_id": str(lifecycle_plan.get("plan_id") or ""),
                        "split_plan_id": plan_id,
                        "node_id": node_id,
                        "batch_id": str(lifecycle_plan.get("batch_id") or ""),
                        "step_count": len(lifecycle_steps),
                        "step_types": [str(item.get("step_type") or "") for item in lifecycle_steps],
                    },
                    "manifest_ref": {
                        "acceptance_mode": str(dict(plan.get("acceptance_policy") or {}).get("mode") or ""),
                        "merge_mode": str(dict(plan.get("merge_policy") or {}).get("mode") or ""),
                    },
                    "assembly_ref": {},
                    "scheduler_ref": {
                        "status": "planned",
                        "note": "compile_only_preview",
                    },
                    "imported_plan_ref": {
                        "split_plan_id": plan_id,
                    },
                    "status": "planned",
                }
            )
        if merge_readiness_plan:
            traces.append(
                {
                    "object_type": "batch_merge_readiness_plan",
                    "object_id": str(merge_readiness_plan.get("plan_id") or ""),
                    "title": f"{str(merge_readiness_plan.get('mode') or 'merge')} · {len(list(merge_readiness_plan.get('depends_on_batch_ids') or []))} batches",
                    "source_path": f"graph.nodes[{node_id}].contract_bindings.runtime.merge_policy",
                    "runtime_ref": {
                        "plan_id": str(merge_readiness_plan.get("plan_id") or ""),
                        "split_plan_id": plan_id,
                        "node_id": node_id,
                        "merge_id": str(merge_readiness_plan.get("merge_id") or ""),
                        "ready_condition": str(merge_readiness_plan.get("ready_condition") or ""),
                    },
                    "manifest_ref": {
                        "merge_mode": str(merge_readiness_plan.get("mode") or ""),
                        "result_order": str(merge_readiness_plan.get("result_order") or ""),
                        "final_review_required": bool(merge_readiness_plan.get("final_review_required", True)),
                    },
                    "assembly_ref": {},
                    "scheduler_ref": {
                        "status": "planned",
                        "note": "compile_only_preview",
                    },
                    "imported_plan_ref": {
                        "split_plan_id": plan_id,
                    },
                    "status": "planned",
                }
            )
    return traces


def _scheduler_node_trace(scheduler_node: dict[str, object]) -> dict[str, object]:
    return {
        "node_id": str(scheduler_node.get("node_id") or ""),
        "status": str(scheduler_node.get("status") or ""),
        "phase_id": str(scheduler_node.get("phase_id") or ""),
        "upstream_node_ids": list(scheduler_node.get("upstream_node_ids") or []),
        "downstream_node_ids": list(scheduler_node.get("downstream_node_ids") or []),
        "blocked_reasons": list(scheduler_node.get("blocked_reasons") or []),
    }


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


@router.get("/tasks/execution-packages/task-graphs/{graph_id}")
async def build_task_system_task_graph_execution_package(graph_id: str) -> dict[str, object]:
    parts = _compiled_task_graph_execution_parts(graph_id)
    graph = parts["graph"]
    standard_view = parts["standard_view"]
    runtime_spec = parts["runtime_spec"]
    manifest = parts["manifest"]
    scheduler_state = parts["scheduler_state"]
    node_runtime_assemblies = list(parts["node_runtime_assemblies"])
    assembly_errors = list(parts["assembly_errors"])
    graph_module_execution_plans = list(parts["graph_module_execution_plans"])
    graph_module_plan_issues = list(parts["graph_module_plan_issues"])
    split_plans = list(parts["split_plans"])
    split_merge_issues = list(parts["split_merge_issues"])
    split_batch_lifecycle_plan_count = sum(
        len(list(item.get("batch_lifecycle_plans") or []))
        for item in split_plans
        if isinstance(item, dict)
    )
    split_batch_lifecycle_step_count = sum(
        len(list(lifecycle_plan.get("steps") or []))
        for item in split_plans
        if isinstance(item, dict)
        for lifecycle_plan in list(item.get("batch_lifecycle_plans") or [])
        if isinstance(lifecycle_plan, dict)
    )
    split_merge_readiness_plan_count = sum(
        1
        for item in split_plans
        if isinstance(item, dict) and isinstance(item.get("merge_readiness_plan"), dict)
    )
    object_trace_index = _task_graph_execution_object_trace_index(
        graph=graph,  # type: ignore[arg-type]
        runtime_spec=runtime_spec,  # type: ignore[arg-type]
        manifest=manifest,  # type: ignore[arg-type]
        scheduler_state=scheduler_state,  # type: ignore[arg-type]
        node_runtime_assemblies=node_runtime_assemblies,
        graph_module_execution_plans=graph_module_execution_plans,
        split_plans=split_plans,
    )
    runtime_issues = [item.to_dict() for item in runtime_spec.issues]  # type: ignore[attr-defined]
    manifest_issues = [item.to_dict() for item in manifest.issues]  # type: ignore[attr-defined]
    valid = bool(runtime_spec.valid and manifest.valid and not assembly_errors and not any(str(item.get("severity") or "error") == "error" for item in graph_module_plan_issues))  # type: ignore[attr-defined]
    return {
        "authority": "task_system.task_graph_execution_package",
        "package_id": f"execution-package:task-graph:{graph_id}",
        "graph_id": graph_id,
        "title": str(getattr(graph, "title", "") or graph_id),
        "valid": valid,
        "standard_view": standard_view.to_dict(),  # type: ignore[attr-defined]
        "contract_manifest": manifest.to_dict(),  # type: ignore[attr-defined]
        "runtime_spec": runtime_spec.to_dict(),  # type: ignore[attr-defined]
        "node_runtime_assemblies": node_runtime_assemblies,
        "scheduler_state": scheduler_state.to_dict(),  # type: ignore[attr-defined]
        "graph_modules": [item.to_dict() for item in getattr(runtime_spec, "graph_module_runtime_plans", ()) or ()],  # type: ignore[attr-defined]
        "graph_module_execution_plans": graph_module_execution_plans,
        "split_plans": split_plans,
        "split_merge_issues": split_merge_issues,
        "object_trace_index": object_trace_index,
        "issues": [
            *manifest_issues,
            *runtime_issues,
            *assembly_errors,
            *graph_module_plan_issues,
        ],
        "summary": {
            "node_count": len(getattr(runtime_spec, "nodes", ()) or ()),
            "edge_count": len(getattr(runtime_spec, "edges", ()) or ()),
            "contract_issue_count": len(manifest_issues),
            "runtime_issue_count": len(runtime_issues),
            "assembly_count": len(node_runtime_assemblies),
            "assembly_error_count": len(assembly_errors),
            "graph_module_count": len(getattr(runtime_spec, "graph_module_runtime_plans", ()) or ()),
            "graph_module_handoff_contract_count": len(getattr(manifest, "graph_module_handoff_contracts", ()) or ()),
            "graph_module_execution_plan_count": len(graph_module_execution_plans),
            "graph_module_execution_plan_issue_count": len(graph_module_plan_issues),
            "split_plan_count": len(split_plans),
            "split_batch_count": sum(len(list(item.get("batches") or [])) for item in split_plans if isinstance(item, dict)),
            "split_batch_lifecycle_plan_count": split_batch_lifecycle_plan_count,
            "split_batch_lifecycle_step_count": split_batch_lifecycle_step_count,
            "split_merge_readiness_plan_count": split_merge_readiness_plan_count,
            "split_merge_issue_count": len(split_merge_issues),
            "object_trace_count": len(object_trace_index),
            "scheduler_ready_count": len(getattr(scheduler_state, "ready_node_ids", ()) or ()),
            "scheduler_blocked_count": len(getattr(scheduler_state, "blocked_node_ids", ()) or ()),
        },
    }


@router.get("/tasks/task-graphs/{graph_id}")
async def get_task_system_task_graph(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    graph = TaskFlowRegistry(runtime.base_dir).get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="task graph not found")
    return graph.to_dict()


@router.get("/tasks/task-graphs/{graph_id}/standard-view")
async def get_task_system_task_graph_standard_view(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = _graph_or_404(registry=registry, graph_id=graph_id)
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    view = build_task_graph_standard_view(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
        graph_lookup=registry,
    )
    return view.to_dict()


@router.put("/tasks/task-graphs/{graph_id}/standard-view")
async def upsert_task_system_task_graph_standard_view(
    graph_id: str,
    payload: TaskGraphStandardViewUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    current_graph = _graph_or_404(registry=registry, graph_id=graph_id)
    try:
        next_graph = apply_task_graph_standard_view_update(
            graph=current_graph,
            payload=payload.model_dump(),
        )
        TaskFlowRegistry(runtime.base_dir).upsert_task_graph(
            graph_id=next_graph.graph_id,
            title=next_graph.title,
            domain_id=next_graph.domain_id,
            task_family=next_graph.task_family,
            graph_kind=next_graph.graph_kind,
            entry_node_id=next_graph.entry_node_id,
            output_node_id=next_graph.output_node_id,
            nodes=tuple(dict(item) for item in next_graph.to_dict().get("nodes", [])),
            edges=tuple(dict(item) for item in next_graph.to_dict().get("edges", [])),
            graph_contract_id=next_graph.graph_contract_id,
            contract_bindings=next_graph.contract_bindings,
            default_protocol_id=next_graph.default_protocol_id,
            working_memory_policy_profile_id=next_graph.working_memory_policy_profile_id,
            working_memory_policy=next_graph.working_memory_policy,
            runtime_policy=next_graph.runtime_policy,
            context_policy=next_graph.context_policy,
            publish_state=next_graph.publish_state,
            enabled=next_graph.enabled,
            metadata=next_graph.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_task_system_task_graph_standard_view(graph_id)


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


@router.put("/tasks/workflows/{workflow_id}")
async def upsert_task_system_workflow(workflow_id: str, payload: TaskWorkflowUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.workflow_id != workflow_id:
        payload = payload.model_copy(update={"workflow_id": workflow_id})
    metadata = {**dict(payload.metadata), **({"task_mode": payload.task_mode} if payload.task_mode else {})}
    try:
        TaskWorkflowRegistry(runtime.base_dir).upsert_workflow(
            workflow_id=payload.workflow_id,
            title=payload.title,
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
            metadata=metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


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
            description=payload.description,
            enabled=payload.enabled,
            runtime_lane=payload.runtime_lane,
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
            contract_bindings=payload.contract_bindings,
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
