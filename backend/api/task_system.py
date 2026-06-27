from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.deps import require_runtime
from api.session_summary import enrich_session_summaries, enrich_session_summary
from sessions import SessionTaskBindingConflict, SessionTaskBindingMissing
from agent_system.registry.agent_registry import AgentRegistry
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from graph_system.scheduler_view import build_scheduler_view
from prompt_library import PromptLibraryRegistry
from task_system import (
    TaskContractRegistry,
    TaskFlowRegistry,
    TaskWorkflowRegistry,
    apply_task_graph_standard_view_update,
    build_task_graph_standard_view,
    semantic_relation_catalog,
)
from task_system.compiler.executable_graph_config_publisher import (
    build_graph_config_from_graph,
    publish_graph_config_for_graph,
)
from task_system.environments import (
    TaskEnvironmentConfigError,
    TaskEnvironmentRepository,
    build_task_environment_catalog,
    task_environment_registry_from_backend_dir,
)
from task_system.environments.kind_templates import TaskEnvironmentKindTemplateRepository
from task_system.engagement import (
    EngagementPlanConfigError,
    EngagementPlanRepository,
    EngagementRunRepository,
    EngagementService,
    sync_engagement_run_closeout,
)
from task_system.graphs.task_graph_models import validate_task_graph
from task_system.node_configurations import (
    TaskNodeConfigurationSpec,
    TaskNodeConfigurationRepository,
    build_node_configuration_catalog,
)
from task_system.projects import ProjectFileService, ProjectLifecycleService
from task_system.session_scope import normalize_session_scope, session_scope_matches

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


def _build_task_graph_node_role_prompt(node: dict[str, object], metadata: dict[str, object]) -> str:
    role_prompt = str(node.get("role_prompt") or metadata.get("role_prompt") or "").strip()
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


def _consolidate_task_graph_prompt_metadata(
    metadata: dict[str, object],
    *,
    prompt_resource_id: str = "",
) -> dict[str, object]:
    cleaned = {
        key: value
        for key, value in metadata.items()
        if key not in TASK_GRAPH_PROMPT_METADATA_KEYS and key != "legacy_prompt_migration"
    }
    if prompt_resource_id:
        cleaned["prompt_resource_id"] = prompt_resource_id
    return cleaned


def _consolidate_task_graph_node_role_prompts(
    base_dir,
    *,
    graph_id: str,
    graph_title: str,
    domain_id: str,
    nodes: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    prompt_registry = PromptLibraryRegistry(base_dir)
    consolidated_nodes: list[dict[str, object]] = []
    for node in nodes:
        next_node = dict(node)
        metadata = dict(next_node.get("metadata") or {})
        prompt = _build_task_graph_node_role_prompt(next_node, metadata)
        metadata_has_prompt_source = any(key in metadata for key in TASK_GRAPH_PROMPT_METADATA_KEYS)
        prompt_resource_id = ""
        if prompt and metadata_has_prompt_source:
            resource = prompt_registry.upsert_task_graph_node_role_prompt(
                graph_id=graph_id,
                graph_title=graph_title,
                domain_id=domain_id,
                node=next_node,
                prompt=prompt,
            )
            prompt_resource_id = resource.resource_id
        if prompt:
            next_node["role_prompt"] = prompt
        if metadata_has_prompt_source or "legacy_prompt_migration" in metadata:
            next_node["metadata"] = _consolidate_task_graph_prompt_metadata(
                metadata,
                prompt_resource_id=prompt_resource_id,
            )
        consolidated_nodes.append(next_node)
    return tuple(consolidated_nodes)


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
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    conversation_entry_policy: str = Field(default="user_dialogue_to_main_agent", max_length=160)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskDomainUpsertRequest(BaseModel):
    domain_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    sort_order: int = 0
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
    execution_chain_type: str = Field(default="agent_harness_chain", max_length=120)
    runtime_agent_selection_policy: str = Field(default="orchestration_default", max_length=120)
    default_agent_id: str = Field(default="agent:0", max_length=160)
    task_level: str = Field(default="standard", max_length=80)
    task_privilege: str = Field(default="bounded", max_length=80)
    allow_worker_agent_spawn: bool = False
    worker_agent_blueprint_id: str = Field(default="", max_length=160)
    worker_agent_naming_rule: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskAssignmentUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    task_title: str = Field(..., min_length=1, max_length=200)
    task_kind: str = Field(default="specific_task", max_length=120)
    flow_id: str = Field(default="", max_length=160)
    domain_id: str = Field(default="", max_length=160)
    task_environment_id: str = Field(default="", max_length=200)
    default_agent_id: str = Field(default="agent:0", max_length=160)
    participant_agent_ids: list[str] = Field(default_factory=list)
    workflow_id: str = Field(default="", max_length=160)
    workflow_file_ref: str = Field(default="", max_length=260)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    safety_policy: dict[str, object] = Field(default_factory=dict)
    task_structure: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class EngagementPlanUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(..., min_length=3, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    version: str = Field(default="1.0.0", max_length=80)
    status: str = Field(default="draft", max_length=80)
    task_environment_id: str = Field(..., min_length=3, max_length=200)
    assignee: dict[str, object] = Field(default_factory=dict)
    runtime_profile: dict[str, object] = Field(default_factory=dict)
    execution_strategy: dict[str, object] = Field(default_factory=dict)
    input_contract: dict[str, object] = Field(default_factory=dict)
    output_contract: dict[str, object] = Field(default_factory=dict)
    prompt_contract: dict[str, object] = Field(default_factory=dict)
    resource_requirements: dict[str, object] = Field(default_factory=dict)
    capability_requirements: dict[str, object] = Field(default_factory=dict)
    memory_requirements: dict[str, object] = Field(default_factory=dict)
    acceptance_policy: dict[str, object] = Field(default_factory=dict)
    recovery_policy: dict[str, object] = Field(default_factory=dict)
    created_at: str = Field(default="", max_length=120)
    updated_at: str = Field(default="", max_length=120)
    supersedes_plan_id: str = Field(default="", max_length=200)
    metadata: dict[str, object] = Field(default_factory=dict)


class EngagementStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default="", max_length=200)


class TaskEnvironmentSessionResolveRequest(BaseModel):
    workspace_view: str = Field(default="chat", max_length=80)
    project_id: str = Field(default="", max_length=240)
    intent: str = Field(default="continue_conversation", max_length=80)
    title: str = Field(default="", max_length=120)
    preferred_session_id: str = Field(default="", max_length=200)
    create_if_missing: bool = False
    graph_run_id: str = Field(default="", max_length=240)
    startup_parameters: dict[str, object] = Field(default_factory=dict)


class ProjectLifecycleRunStartRequest(BaseModel):
    action: str = Field(..., min_length=3, max_length=160)
    execute: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskEnvironmentGroupUpsertRequest(BaseModel):
    group_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    authority: str = Field(default="task_system.task_environment_group", max_length=160)


class TaskEnvironmentKindTemplateUpsertRequest(BaseModel):
    kind_id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=1200)
    group_id: str = Field(default="", max_length=160)
    allowed_resource_refs: list[str] = Field(default_factory=list)
    default_sandbox_policy: dict[str, object] = Field(default_factory=dict)
    default_execution_policy: dict[str, object] = Field(default_factory=dict)
    default_risk_policy: dict[str, object] = Field(default_factory=dict)
    default_prompt_cache_scope: str = Field(default="static_environment", max_length=120)
    allowed_task_graph_kinds: list[str] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskEnvironmentUpsertRequest(BaseModel):
    record: dict[str, object] = Field(default_factory=dict)
    spec: dict[str, object] = Field(default_factory=dict)
    environment_id: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=1000)
    group_id: str = Field(default="environment_group.general", max_length=160)
    environment_kind: str = Field(default="custom", max_length=80)
    enabled: bool = True
    owner: str = Field(default="system", max_length=80)
    default_visibility: str = Field(default="system", max_length=80)
    environment_prompts: list[dict[str, object]] = Field(default_factory=list)
    sandbox_policy: dict[str, object] = Field(default_factory=dict)
    file_management: dict[str, object] = Field(default_factory=dict)
    resource_space: dict[str, object] = Field(default_factory=dict)
    memory_space: dict[str, object] = Field(default_factory=dict)
    execution_policy: dict[str, object] = Field(default_factory=dict)
    risk_policy: dict[str, object] = Field(default_factory=dict)
    artifact_policy: dict[str, object] = Field(default_factory=dict)
    observability_policy: dict[str, object] = Field(default_factory=dict)
    lifecycle_policy: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskNodeConfigurationUpsertRequest(BaseModel):
    node_config_id: str = Field(..., min_length=3, max_length=180)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    node_kind: str = Field(default="agent", max_length=120)
    environment_scope: list[str] = Field(default_factory=list)
    role_prompt: str = Field(default="", max_length=12000)
    executor_ref: dict[str, object] = Field(default_factory=dict)
    contract_bindings: dict[str, object] = Field(default_factory=dict)
    model_requirements: dict[str, object] = Field(default_factory=dict)
    tool_policy: dict[str, object] = Field(default_factory=dict)
    memory_policy: dict[str, object] = Field(default_factory=dict)
    artifact_policy: dict[str, object] = Field(default_factory=dict)
    failure_policy: dict[str, object] = Field(default_factory=dict)
    human_gate_policy: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True


class TaskNodeRuntimePreviewRequest(BaseModel):
    environment_id: str = Field(default="", max_length=200)
    graph_id: str = Field(default="", max_length=200)


class TaskWorkflowUpsertRequest(BaseModel):
    workflow_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    task_mode: str = Field(default="", max_length=120)
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
    loop_frames: list[dict[str, object]] = Field(default_factory=list)
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


def _environment_kind_management_payload(base_dir) -> dict[str, object]:
    templates = [item.to_dict() for item in TaskEnvironmentKindTemplateRepository(base_dir).list()]
    return {
        "authority": "task_system.environment_kind_management",
        "kind_templates": templates,
        "summary": {
            "kind_template_count": len(templates),
            "enabled_kind_template_count": sum(1 for item in templates if item.get("enabled") is not False),
        },
    }


def _environment_task_inventory(task_assignments: list[dict[str, object]]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for task in task_assignments:
        metadata = dict(task.get("metadata") or {})
        task_structure = dict(task.get("task_structure") or {})
        environment_id = str(
            task.get("task_environment_id")
            or metadata.get("task_environment_id")
            or metadata.get("environment_id")
            or task_structure.get("task_environment_id")
            or task_structure.get("environment_id")
            or ""
        ).strip()
        rows.append({
            "environment_id": environment_id,
            "task_id": str(task.get("task_id") or ""),
            "task_title": str(task.get("task_title") or ""),
            "flow_id": str(task.get("flow_id") or ""),
            "domain_id": str(task.get("domain_id") or ""),
            "input_contract_id": str(task.get("input_contract_id") or ""),
            "output_contract_id": str(task.get("output_contract_id") or ""),
            "execution_chain_type": str(task.get("execution_chain_type") or ""),
            "enabled": bool(task.get("enabled", True)),
            "authority": "task_system.environment_task_inventory_item",
        })
    by_environment: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_environment.setdefault(str(row.get("environment_id") or ""), []).append(row)
    return {
        "authority": "task_system.environment_task_inventory",
        "items": rows,
        "by_environment": by_environment,
        "summary": {"task_inventory_count": len(rows)},
    }


def _environment_graph_inventory(task_graphs: list[dict[str, object]]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for graph in task_graphs:
        runtime_policy = dict(graph.get("runtime_policy") or {})
        context_policy = dict(graph.get("context_policy") or {})
        metadata = dict(graph.get("metadata") or {})
        environment_id = str(
            runtime_policy.get("task_environment_id")
            or runtime_policy.get("environment_id")
            or context_policy.get("task_environment_id")
            or context_policy.get("environment_id")
            or metadata.get("task_environment_id")
            or metadata.get("environment_id")
            or ""
        ).strip()
        rows.append({
            "environment_id": environment_id,
            "graph_id": str(graph.get("graph_id") or ""),
            "title": str(graph.get("title") or ""),
            "domain_id": str(graph.get("domain_id") or ""),
            "graph_kind": str(graph.get("graph_kind") or ""),
            "entry_node_id": str(graph.get("entry_node_id") or ""),
            "output_node_id": str(graph.get("output_node_id") or ""),
            "node_count": len(list(graph.get("nodes") or [])),
            "edge_count": len(list(graph.get("edges") or [])),
            "publish_state": str(graph.get("publish_state") or ""),
            "enabled": bool(graph.get("enabled", True)),
            "authority": "task_system.environment_graph_inventory_item",
        })
    by_environment: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_environment.setdefault(str(row.get("environment_id") or ""), []).append(row)
    return {
        "authority": "task_system.environment_graph_inventory",
        "items": rows,
        "by_environment": by_environment,
        "summary": {"graph_inventory_count": len(rows)},
    }


def _visible_task_environment_ids(task_environment_management: dict[str, object]) -> list[str]:
    environment_ids: list[str] = []
    records = task_environment_management.get("records")
    if not isinstance(records, list):
        return environment_ids
    for record in records:
        if not isinstance(record, dict):
            continue
        environment_id = str(record.get("environment_id") or "").strip()
        if not environment_id:
            continue
        if record.get("enabled") is False:
            continue
        if str(record.get("management_scope") or "").strip() == "system_internal":
            continue
        environment_ids.append(environment_id)
    return environment_ids


def _project_instance_management(base_dir, *, environment_ids: list[str]) -> dict[str, object]:
    service = ProjectFileService(base_dir)
    projects = []
    for environment_id in environment_ids:
        projects.extend(service.list_environment_projects(environment_id))
    by_environment: dict[str, list[dict[str, object]]] = {}
    for project in projects:
        by_environment.setdefault(str(project.get("environment_id") or ""), []).append(project)
    return {
        "authority": "task_system.project_instance_management",
        "environment_ids": environment_ids,
        "projects": projects,
        "by_environment": by_environment,
        "summary": {"project_count": len(projects)},
    }


def _contract_usage_index(
    *,
    task_assignments: list[dict[str, object]],
    task_flows: list[dict[str, object]],
    task_graphs: list[dict[str, object]],
) -> dict[str, object]:
    usages: dict[str, list[dict[str, object]]] = {}

    def add(contract_id: object, *, source_kind: str, source_id: str, field: str, title: str = "") -> None:
        normalized = str(contract_id or "").strip()
        if not normalized:
            return
        usages.setdefault(normalized, []).append({
            "contract_id": normalized,
            "source_kind": source_kind,
            "source_id": source_id,
            "field": field,
            "title": title,
            "authority": "task_system.contract_usage_item",
        })

    for task in task_assignments:
        task_id = str(task.get("task_id") or "")
        title = str(task.get("task_title") or "")
        add(task.get("input_contract_id"), source_kind="task_assignment", source_id=task_id, field="input_contract_id", title=title)
        add(task.get("output_contract_id"), source_kind="task_assignment", source_id=task_id, field="output_contract_id", title=title)

    for flow in task_flows:
        flow_id = str(flow.get("flow_id") or "")
        title = str(flow.get("title") or "")
        add(flow.get("input_contract_id"), source_kind="task_flow", source_id=flow_id, field="input_contract_id", title=title)
        add(flow.get("output_contract_id"), source_kind="task_flow", source_id=flow_id, field="output_contract_id", title=title)

    for graph in task_graphs:
        graph_id = str(graph.get("graph_id") or "")
        title = str(graph.get("title") or "")
        add(graph.get("graph_contract_id"), source_kind="task_graph", source_id=graph_id, field="graph_contract_id", title=title)
        _scan_contract_bindings(dict(graph.get("contract_bindings") or {}), add, source_kind="task_graph", source_id=graph_id, title=title)
        for node in list(graph.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "")
            node_title = str(node.get("title") or node_id)
            add(node.get("input_contract_id"), source_kind="task_graph_node", source_id=f"{graph_id}:{node_id}", field="input_contract_id", title=node_title)
            add(node.get("output_contract_id"), source_kind="task_graph_node", source_id=f"{graph_id}:{node_id}", field="output_contract_id", title=node_title)
            add(node.get("node_contract_id") or node.get("contract_id"), source_kind="task_graph_node", source_id=f"{graph_id}:{node_id}", field="node_contract_id", title=node_title)
            _scan_contract_bindings(dict(node.get("contract_bindings") or {}), add, source_kind="task_graph_node", source_id=f"{graph_id}:{node_id}", title=node_title)
        for edge in list(graph.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            edge_id = str(edge.get("edge_id") or "")
            add(edge.get("payload_contract_id") or edge.get("contract_id"), source_kind="task_graph_edge", source_id=f"{graph_id}:{edge_id}", field="payload_contract_id", title=edge_id)
            _scan_contract_bindings(dict(edge.get("contract_bindings") or {}), add, source_kind="task_graph_edge", source_id=f"{graph_id}:{edge_id}", title=edge_id)

    return {
        "authority": "task_system.contract_usage_index",
        "by_contract_id": usages,
        "summary": {
            "contract_with_usage_count": len(usages),
            "usage_count": sum(len(items) for items in usages.values()),
        },
    }


def _scan_contract_bindings(bindings: dict[str, object], add, *, source_kind: str, source_id: str, title: str) -> None:
    for section_name, section in bindings.items():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if str(key).endswith("contract_id") or str(key) == "contract_id":
                add(value, source_kind=source_kind, source_id=source_id, field=f"contract_bindings.{section_name}.{key}", title=title)


def _task_system_payload(base_dir) -> dict[str, object]:
    registry = TaskFlowRegistry(base_dir)
    workflow_registry = TaskWorkflowRegistry(base_dir)
    agent_registry = AgentRegistry(base_dir)
    agents = [item.to_dict() for item in agent_registry.list_agents()]
    runtime_profiles = [item.to_dict() for item in AgentRuntimeRegistry(base_dir).list_profiles()]
    contract_registry = TaskContractRegistry(base_dir)
    task_flows = [item.to_dict() for item in registry.list_flows()]
    entry_policies = [item.to_dict() for item in registry.list_general_task_profiles()]
    task_assignments = [item.to_dict() for item in registry.list_task_assignments()]
    engagement_plans = [item.to_dict() for item in EngagementPlanRepository(base_dir).list()]
    specific_task_records: list[dict[str, object]] = []
    flow_contract_binding_models = registry.list_flow_contract_bindings()
    explicit_flow_contract_binding_models = registry.list_explicit_flow_contract_bindings()
    execution_policy_models = registry.list_task_execution_policies()
    explicit_execution_policy_models = registry.list_explicit_task_execution_policies()
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
    task_graph_models = registry.list_task_graphs()
    full_task_graphs = [item.to_dict() for item in task_graph_models]
    task_graphs = [_task_graph_overview_item(item) for item in task_graph_models]
    semantic_relations = semantic_relation_catalog()
    communication_protocols = [item.to_dict() for item in registry.list_task_communication_protocols()]
    task_environment_management = build_task_environment_catalog(
        registry=task_environment_registry_from_backend_dir(base_dir),
        engagement_plans=engagement_plans,
    ).management_payload()
    communication_protocol_by_id = {
        str(item.get("protocol_id") or ""): item
        for item in communication_protocols
    }
    contract_catalog = [item.to_dict() for item in registry.list_contract_descriptors()]
    contract_management = contract_registry.build_catalog()
    contract_ids = {str(item.get("contract_id") or "") for item in contract_management.get("contract_specs", [])}
    environment_kind_management = _environment_kind_management_payload(base_dir)
    environment_task_inventory = _environment_task_inventory(task_assignments)
    environment_graph_inventory = _environment_graph_inventory(full_task_graphs)
    project_instance_management = _project_instance_management(
        base_dir,
        environment_ids=_visible_task_environment_ids(task_environment_management),
    )
    contract_usage_index = _contract_usage_index(
        task_assignments=task_assignments,
        task_flows=task_flows,
        task_graphs=full_task_graphs,
    )
    node_configuration_management = build_node_configuration_catalog(
        base_dir,
        task_graphs=full_task_graphs,
        agents=agents,
        profiles=runtime_profiles,
        contract_ids=contract_ids,
    )
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
            "engagement_plan_count": len(engagement_plans),
            "specific_task_record_count": 0,
            "task_assignment_count": len(task_assignments),
            "task_flow_count": len(task_flows),
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
                key_attr="policy_id",
            ),
            "effective_execution_policy_count": len(execution_policy_models),
            "task_domain_count": len(task_domains),
            "task_graph_count": len(task_graphs),
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
            "engagement_plans": engagement_plans,
            "specific_task_records": [],
            "task_flow_definitions": task_flows,
            "flow_contract_bindings": flow_contract_bindings,
            "execution_policies": execution_policies,
            "contract_catalog": contract_catalog,
            "task_assignments": task_assignments,
            "workflow_resources": workflow_resources,
        },
        "task_environment_management": task_environment_management,
        "project_instance_management": project_instance_management,
        "environment_kind_management": environment_kind_management,
        "environment_task_inventory": environment_task_inventory,
        "environment_graph_inventory": environment_graph_inventory,
        "contract_management": contract_management,
        "contract_usage_index": contract_usage_index,
        "node_configuration_management": node_configuration_management,
        "task_graph_management": {
            "task_graphs": task_graphs,
            "task_graph_specs": [],
            "semantic_relation_catalog": semantic_relations,
            "semantic_relations": semantic_relations["relations"],
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


def _task_node_configuration_for_preview(base_dir, node_config_id: str) -> TaskNodeConfigurationSpec | None:
    spec = TaskNodeConfigurationRepository(base_dir).get(node_config_id)
    if spec is not None:
        return spec

    task_graphs = [item.to_dict() for item in TaskFlowRegistry(base_dir).list_task_graphs()]
    catalog = build_node_configuration_catalog(base_dir, task_graphs=task_graphs)
    for item in list(catalog.get("node_configurations") or []):
        if str(item.get("node_config_id") or "") == node_config_id:
            return TaskNodeConfigurationSpec.from_dict(dict(item))
    return None


@router.get("/tasks/overview")
async def task_system_overview() -> dict[str, object]:
    runtime = require_runtime()
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/environments/catalog")
async def task_environment_catalog() -> dict[str, object]:
    runtime = require_runtime()
    return build_task_environment_catalog(
        registry=task_environment_registry_from_backend_dir(runtime.base_dir),
    ).management_payload()


@router.get("/tasks/next-ids")
async def task_system_next_ids() -> dict[str, object]:
    runtime = require_runtime()
    flow_registry = TaskFlowRegistry(runtime.base_dir)
    task_id = flow_registry.next_specific_task_id()
    flow_id = flow_registry.next_flow_id()
    workflow_id = TaskWorkflowRegistry(runtime.base_dir).next_workflow_id()
    graph_id = flow_registry.next_task_graph_id()
    return {
        "authority": "task_system.id_registry",
        "task_id": task_id,
        "flow_id": flow_id,
        "workflow_id": workflow_id,
        "graph_id": graph_id,
        "display_numbers": {
            "task": _display_number(task_id, prefix="task.", fallback="任务"),
            "flow": _display_number(flow_id, prefix="flow.", fallback="流程"),
            "workflow": _display_number(workflow_id, prefix="workflow.", fallback="流程"),
            "graph": _display_number(graph_id, prefix="graph.", fallback="任务图"),
            "coordination": _display_number(graph_id, prefix="graph.", fallback="协作"),
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



def _scheduler_view_payload(graph_config: object) -> dict[str, object]:
    scheduler = build_scheduler_view(graph_config)  # type: ignore[arg-type]
    return {
        "authority": "graph_system.scheduler_view",
        "config_id": scheduler.config_id,
        "config_hash": scheduler.config_hash,
        "dependency_edges": [dict(item) for item in scheduler.dependency_edges],
        "executable_node_ids": list(scheduler.executable_node_ids),
        "start_node_ids": list(scheduler.start_node_ids),
        "terminal_node_ids": list(scheduler.terminal_node_ids),
        "diagnostics": dict(scheduler.diagnostics),
    }


def _graph_system_trace_index(*, graph: object, graph_config: object, scheduler_view: dict[str, object]) -> list[dict[str, object]]:
    config_payload = graph_config.to_dict() if hasattr(graph_config, "to_dict") else dict(graph_config or {})
    config_nodes = {
        str(item.get("node_id") or ""): dict(item)
        for item in list(config_payload.get("nodes") or [])
        if isinstance(item, dict) and str(item.get("node_id") or "")
    }
    config_edges = {
        str(item.get("edge_id") or ""): dict(item)
        for item in list(config_payload.get("edges") or [])
        if isinstance(item, dict) and str(item.get("edge_id") or "")
    }
    dependency_edge_ids = {
        str(item.get("edge_id") or "")
        for item in list(scheduler_view.get("dependency_edges") or [])
        if isinstance(item, dict) and str(item.get("edge_id") or "")
    }
    start_ids = set(str(item) for item in list(scheduler_view.get("start_node_ids") or []) if str(item))
    terminal_ids = set(str(item) for item in list(scheduler_view.get("terminal_node_ids") or []) if str(item))
    traces: list[dict[str, object]] = [
        {
            "object_type": "graph",
            "object_id": str(getattr(graph, "graph_id", "") or config_payload.get("graph_id") or ""),
            "title": str(getattr(graph, "title", "") or config_payload.get("graph_title") or config_payload.get("graph_id") or ""),
            "source_path": "graph",
            "runtime_ref": {
                "graph_config_id": str(config_payload.get("config_id") or ""),
                "graph_config_hash": str(config_payload.get("content_hash") or ""),
            },
            "scheduler_ref": {
                "start_node_ids": list(scheduler_view.get("start_node_ids") or []),
                "terminal_node_ids": list(scheduler_view.get("terminal_node_ids") or []),
                "dependency_edge_count": len(list(scheduler_view.get("dependency_edges") or [])),
            },
            "status": "ready",
        }
    ]
    for node in tuple(getattr(graph, "nodes", ()) or ()):
        node_id = str(getattr(node, "node_id", "") or "")
        compiled = config_nodes.get(node_id, {})
        traces.append(
            {
                "object_type": "node",
                "object_id": node_id,
                "title": str(getattr(node, "title", "") or node_id),
                "source_path": f"graph.nodes[{node_id}]",
                "runtime_ref": {
                    "node_id": str(compiled.get("node_id") or ""),
                    "node_type": str(compiled.get("node_type") or ""),
                    "task_ref": str(compiled.get("task_ref") or ""),
                    "executor_type": str(dict(compiled.get("executor") or {}).get("executor_type") or ""),
                },
                "scheduler_ref": {
                    "role": "start" if node_id in start_ids else "terminal" if node_id in terminal_ids else "scheduled",
                    "is_start": node_id in start_ids,
                    "is_terminal": node_id in terminal_ids,
                },
                "status": "ready" if compiled else "not_in_harness_config",
            }
        )
    for edge in tuple(getattr(graph, "edges", ()) or ()):
        edge_id = str(getattr(edge, "edge_id", "") or "")
        compiled = config_edges.get(edge_id, {})
        traces.append(
            {
                "object_type": "edge",
                "object_id": edge_id,
                "title": edge_id,
                "source_path": f"graph.edges[{edge_id}]",
                "runtime_ref": {
                    "edge_id": str(compiled.get("edge_id") or ""),
                    "source_node_id": str(compiled.get("source_node_id") or ""),
                    "target_node_id": str(compiled.get("target_node_id") or ""),
                    "edge_type": str(compiled.get("edge_type") or ""),
                    "scheduler_role": str(compiled.get("scheduler_role") or ""),
                },
                "scheduler_ref": {
                    "is_dependency": edge_id in dependency_edge_ids,
                },
                "status": "ready" if compiled else "not_in_harness_config",
            }
        )
    for source in list(config_payload.get("composition_sources") or []):
        if not isinstance(source, dict):
            continue
        composition_node_id = str(source.get("composition_node_id") or "")
        traces.append(
            {
                "object_type": "graph_composition",
                "object_id": composition_node_id or str(source.get("composition_id") or ""),
                "title": str(source.get("linked_graph_id") or source.get("composition_id") or composition_node_id),
                "source_path": f"graph.nodes[{composition_node_id}]" if composition_node_id else "graph.composition_sources",
                "runtime_ref": {
                    "composition_id": str(source.get("composition_id") or ""),
                    "composition_node_id": composition_node_id,
                    "linked_graph_id": str(source.get("linked_graph_id") or ""),
                    "expanded_node_ids": list(source.get("expanded_node_ids") or []),
                },
                "scheduler_ref": {},
                "status": "expanded_into_harness_config",
            }
        )
    return traces


def _compile_task_graph_contract(graph_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = _graph_or_404(registry=registry, graph_id=graph_id)
    try:
        graph_config = build_graph_config_from_graph(
            graph=graph,
            publish_version="preview",
            graph_lookup=registry,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler_view = _scheduler_view_payload(graph_config)
    diagnostics = dict(graph_config.diagnostics or {})
    issues = [dict(item) for item in list(diagnostics.get("issues") or []) if isinstance(item, dict)]
    if not list(scheduler_view.get("executable_node_ids") or []):
        issues.append(
            {
                "code": "graph_system_no_executable_nodes",
                "message": "图契约没有可执行节点，图任务无法启动。",
                "severity": "error",
                "scope": "graph",
            }
        )
    valid = not any(str(item.get("severity") or "error") == "error" for item in issues)
    config_payload = graph_config.to_dict()
    split_plans = [
        dict(item)
        for item in list(dict(dict(config_payload.get("control") or {}).get("batch_policy") or {}).get("split_plans") or [])
        if isinstance(item, dict)
    ]
    object_trace_index = _graph_system_trace_index(
        graph=graph,
        graph_config=graph_config,
        scheduler_view=scheduler_view,
    )
    return {
        "authority": "task_system.task_graph_contract_compiler",
        "contract_id": f"task-graph-contract:{graph_id}",
        "graph_id": graph_id,
        "title": str(getattr(graph, "title", "") or graph_id),
        "valid": valid,
        "graph_config": config_payload,
        "scheduler_view": scheduler_view,
        "composition_sources": [dict(item) for item in graph_config.composition_sources],
        "split_plans": split_plans,
        "object_trace_index": object_trace_index,
        "issues": issues,
        "summary": {
            "node_count": len(graph_config.nodes),
            "edge_count": len(graph_config.edges),
            "executable_node_count": len(list(scheduler_view.get("executable_node_ids") or [])),
            "dependency_edge_count": len(list(scheduler_view.get("dependency_edges") or [])),
            "start_node_count": len(list(scheduler_view.get("start_node_ids") or [])),
            "terminal_node_count": len(list(scheduler_view.get("terminal_node_ids") or [])),
            "composition_source_count": len(graph_config.composition_sources),
            "split_plan_count": len(split_plans),
            "object_trace_count": len(object_trace_index),
            "issue_count": len(issues),
        },
    }

@router.get("/tasks/task-graph-contracts/task-graphs/{graph_id}/compile")
async def compile_task_system_task_graph_contract(graph_id: str) -> dict[str, object]:
    return _compile_task_graph_contract(graph_id)



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
    view = build_task_graph_standard_view(
        graph=graph,
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
            loop_frames=tuple(dict(item) for item in next_graph.loop_frames),
            publish_state=next_graph.publish_state,
            enabled=next_graph.enabled,
            metadata=next_graph.metadata,
        )
        if next_graph.publish_state == "published":
            publish_graph_config_for_graph(base_dir=runtime.base_dir, graph_id=next_graph.graph_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_task_system_task_graph_standard_view(graph_id)



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


@router.get("/tasks/engagement-plans")
async def list_task_system_engagement_plans() -> dict[str, object]:
    runtime = require_runtime()
    plans = [item.to_dict() for item in EngagementPlanRepository(runtime.base_dir).list()]
    return {
        "authority": "task_system.engagement_plan_api",
        "engagement_plans": plans,
        "summary": {"engagement_plan_count": len(plans)},
    }


@router.get("/tasks/engagement-plans/{plan_id}")
async def get_task_system_engagement_plan(plan_id: str) -> dict[str, object]:
    runtime = require_runtime()
    plan = EngagementPlanRepository(runtime.base_dir).get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="engagement plan not found")
    return {"authority": "task_system.engagement_plan_api", "engagement_plan": plan.to_dict()}


@router.put("/tasks/engagement-plans/{plan_id}")
async def upsert_task_system_engagement_plan(plan_id: str, payload: EngagementPlanUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    raw = payload.model_dump()
    raw["plan_id"] = plan_id
    raw.setdefault("assignee", {})
    raw["assignee"] = {
        "kind": str(dict(raw.get("assignee") or {}).get("kind") or "agent"),
        "agent_id": str(dict(raw.get("assignee") or {}).get("agent_id") or "agent:0"),
        "agent_profile_id": str(dict(raw.get("assignee") or {}).get("agent_profile_id") or ""),
        "workflow_id": str(dict(raw.get("assignee") or {}).get("workflow_id") or ""),
        "participant_agent_ids": list(dict(raw.get("assignee") or {}).get("participant_agent_ids") or []),
    }
    raw["runtime_profile"] = {
        "runtime_policy": dict(dict(raw.get("runtime_profile") or {}).get("runtime_policy") or {}),
    }
    raw["execution_strategy"] = {
        "kind": str(dict(raw.get("execution_strategy") or {}).get("kind") or "graph_task_run"),
        "startup_policy": dict(dict(raw.get("execution_strategy") or {}).get("startup_policy") or {}),
        "lifecycle_policy": dict(dict(raw.get("execution_strategy") or {}).get("lifecycle_policy") or {}),
    }
    try:
        EngagementPlanRepository(runtime.base_dir).upsert(raw)
    except EngagementPlanConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/engagement-plans/{plan_id}")
async def delete_task_system_engagement_plan(plan_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        deletion = EngagementPlanRepository(runtime.base_dir).delete(plan_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = _task_system_payload(runtime.base_dir)
    payload["last_deletion"] = deletion.to_dict()
    return payload


@router.post("/tasks/engagement-plans/{plan_id}/start")
async def start_task_system_engagement_plan(plan_id: str, payload: EngagementStartRequest) -> dict[str, object]:
    runtime = require_runtime()
    startup = dict(payload.startup_parameters or {})
    forbidden = {"environment_id", "task_environment_id", "execution_strategy_override", "runtime_policy_override", "requires_approval"}
    invalid = sorted(key for key in forbidden if key in startup)
    if invalid:
        raise HTTPException(status_code=400, detail={"errors": [f"forbidden_start_field:{key}" for key in invalid]})
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    return EngagementService(runtime.base_dir).start(
        runtime_host=runtime_host,
        plan_id=plan_id,
        session_id=payload.session_id or "session:engagement",
        startup_parameters=startup,
        requested_by="user",
    )


@router.get("/tasks/engagement-runs")
async def list_task_system_engagement_runs() -> dict[str, object]:
    runtime = require_runtime()
    repository = EngagementRunRepository(runtime.base_dir)
    runs = repository.list_runs()
    events = repository.list_events()
    return {
        "authority": "task_system.engagement_run_api",
        "engagement_runs": runs,
        "engagement_events": events,
        "summary": {
            "engagement_run_count": len(runs),
            "engagement_event_count": len(events),
        },
    }


@router.get("/tasks/engagement-runs/{engagement_run_id}")
async def get_task_system_engagement_run(engagement_run_id: str) -> dict[str, object]:
    runtime = require_runtime()
    repository = EngagementRunRepository(runtime.base_dir)
    run = repository.get_run(engagement_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="engagement run not found")
    events = [
        item
        for item in repository.list_events()
        if str(item.get("engagement_run_id") or "") == engagement_run_id
    ]
    return {
        "authority": "task_system.engagement_run_api",
        "engagement_run": run.to_dict(),
        "engagement_events": events,
    }


@router.post("/tasks/engagement-runs/{engagement_run_id}/sync-closeout")
async def sync_task_system_engagement_run_closeout(engagement_run_id: str) -> dict[str, object]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    try:
        result = sync_engagement_run_closeout(
            backend_dir=runtime.base_dir,
            runtime_host=runtime_host,
            engagement_run_id=engagement_run_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


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
        TaskFlowRegistry(runtime.base_dir).upsert_task_execution_policy(
            task_id=payload.task_id,
            execution_mode=(
                "task_graph"
                if payload.allow_worker_agent_spawn
                else "agent_harness"
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


@router.put("/tasks/task-assignments/{task_id}")
async def upsert_task_system_task_assignment(
    task_id: str,
    payload: TaskAssignmentUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_assignment(
            task_id=payload.task_id,
            task_title=payload.task_title,
            task_kind=payload.task_kind,
            flow_id=payload.flow_id or f"flow.{task_id.removeprefix('task.')}",
            domain_id=payload.domain_id,
            task_environment_id=payload.task_environment_id,
            default_agent_id=payload.default_agent_id,
            participant_agent_ids=tuple(payload.participant_agent_ids),
            workflow_id=payload.workflow_id,
            workflow_file_ref=payload.workflow_file_ref,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            safety_policy=payload.safety_policy,
            task_structure=payload.task_structure,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/task-assignments/{task_id}")
async def delete_task_system_task_assignment(task_id: str) -> dict[str, object]:
    runtime = require_runtime()
    TaskFlowRegistry(runtime.base_dir).assignment_repository.delete_for_task_ids({task_id})
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/environments/{environment_id}/tasks")
async def list_task_system_environment_tasks(environment_id: str) -> dict[str, object]:
    runtime = require_runtime()
    task_assignments = [item.to_dict() for item in TaskFlowRegistry(runtime.base_dir).list_task_assignments()]
    inventory = _environment_task_inventory(task_assignments)
    tasks = list(dict(inventory.get("by_environment") or {}).get(environment_id) or [])
    return {
        "authority": "task_system.environment_tasks_api",
        "environment_id": environment_id,
        "tasks": tasks,
        "summary": {"task_count": len(tasks)},
    }


@router.get("/tasks/environments/{environment_id}/projects")
async def list_task_system_environment_projects(environment_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        projects = ProjectFileService(runtime.base_dir).list_environment_projects(environment_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authority": "task_system.environment_projects_api",
        "environment_id": environment_id,
        "projects": projects,
        "summary": {"project_count": len(projects)},
    }


@router.get("/task-environments/{environment_id}/sessions")
async def list_task_environment_sessions(
    environment_id: str,
    workspace_view: str = "chat",
    project_id: str = "",
) -> dict[str, object]:
    runtime = require_runtime()
    scope = normalize_session_scope(
        {
            "workspace_view": workspace_view,
            "task_environment_id": environment_id,
            "project_id": project_id,
        }
    )
    sessions = enrich_session_summaries(runtime.session_manager.list_sessions(**scope.to_dict()), runtime)
    return {
        "authority": "task_environment.session_list",
        "scope": scope.to_dict(),
        "sessions": sessions,
    }


@router.post("/task-environments/{environment_id}/sessions/resolve")
async def resolve_task_environment_session(
    environment_id: str,
    payload: TaskEnvironmentSessionResolveRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    scope = normalize_session_scope(
        {
            "workspace_view": payload.workspace_view,
            "task_environment_id": environment_id,
            "project_id": payload.project_id,
        }
    )
    intent = str(payload.intent or "continue_conversation").strip() or "continue_conversation"
    create_if_missing = bool(payload.create_if_missing)

    if intent == "open_project":
        return {
            "authority": "task_environment.session_resolver",
            "scope": scope.to_dict(),
            "session": None,
            "created": False,
            "reason": "open_project_does_not_create_session",
        }

    if intent == "resume_graph":
        graph_run_id = str(payload.graph_run_id or "").strip()
        if not graph_run_id:
            raise HTTPException(status_code=400, detail="graph_run_id is required for resume_graph")
        graph_run = runtime.harness_runtime.graph_system.get_graph_run(graph_run_id)
        graph_run_payload = dict(graph_run or {})
        if not graph_run_payload:
            raise HTTPException(status_code=404, detail="GraphRun not found")
        graph_session_id = str(graph_run_payload.get("session_id") or "")
        if not graph_session_id:
            raise HTTPException(status_code=409, detail="GraphRun is not bound to a session")
        try:
            runtime.session_manager.assert_session_graph_instance(graph_session_id, graph_run_id)
        except (SessionTaskBindingConflict, SessionTaskBindingMissing, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        history = runtime.session_manager.get_history(graph_session_id)
        if not session_scope_matches(history.get("scope"), scope):
            raise HTTPException(status_code=409, detail="GraphRun session scope mismatch")
        return {
            "authority": "task_environment.session_resolver",
            "scope": scope.to_dict(),
            "session": enrich_session_summary(runtime.session_manager._summary_from_payload(history), runtime),
            "created": False,
            "reason": "resume_graph_session",
        }

    preferred_session_id = str(payload.preferred_session_id or "").strip()
    if preferred_session_id:
        history = runtime.session_manager.get_history(preferred_session_id)
        if not session_scope_matches(history.get("scope"), scope):
            raise HTTPException(status_code=409, detail="Preferred session scope mismatch")
        preferred_graph_run_id = str(payload.graph_run_id or "").strip()
        if preferred_graph_run_id:
            try:
                runtime.session_manager.assert_session_graph_instance(preferred_session_id, preferred_graph_run_id)
            except (SessionTaskBindingConflict, SessionTaskBindingMissing, ValueError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "authority": "task_environment.session_resolver",
            "scope": scope.to_dict(),
            "session": enrich_session_summary(runtime.session_manager._summary_from_payload(history), runtime),
            "created": False,
            "reason": "preferred_session_valid",
        }

    if intent == "new_conversation":
        if not create_if_missing:
            raise HTTPException(status_code=400, detail="create_if_missing is required for new_conversation")
        created = runtime.session_manager.create_session(
            title=payload.title or "New Session",
            scope=scope.to_dict(),
        )
        return {
            "authority": "task_environment.session_resolver",
            "scope": scope.to_dict(),
            "session": enrich_session_summary(created, runtime),
            "created": True,
            "reason": "new_conversation_created",
        }

    if intent == "continue_conversation":
        sessions = enrich_session_summaries(runtime.session_manager.list_sessions(**scope.to_dict()), runtime)
        if sessions:
            return {
                "authority": "task_environment.session_resolver",
                "scope": scope.to_dict(),
                "session": sessions[0],
                "created": False,
                "reason": "latest_scope_session",
            }

    if create_if_missing:
        created = runtime.session_manager.create_session(
            title=payload.title or "New Session",
            scope=scope.to_dict(),
        )
        return {
            "authority": "task_environment.session_resolver",
            "scope": scope.to_dict(),
            "session": enrich_session_summary(created, runtime),
            "created": True,
            "reason": f"{intent}_created",
        }

    raise HTTPException(status_code=404, detail="Scoped session not found")


@router.get("/tasks/projects/{project_id}")
async def get_task_system_project(project_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectFileService(runtime.base_dir).project_payload(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/library")
async def get_task_system_project_library(project_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectFileService(runtime.base_dir).project_payload(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/repositories")
async def list_task_system_project_repositories(project_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectFileService(runtime.base_dir).repositories(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/lifecycle-actions")
async def list_task_system_project_lifecycle_actions(project_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectLifecycleService(runtime.base_dir).list_actions(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/repositories/{repository_id}/tree")
async def get_task_system_project_repository_tree(
    project_id: str,
    repository_id: str,
    path: str = "",
    max_depth: int = 4,
    max_entries: int = 500,
) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectFileService(runtime.base_dir).tree(
            project_id,
            repository_id,
            path,
            max_depth=max_depth,
            max_entries=max_entries,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/repositories/{repository_id}/files")
async def get_task_system_project_repository_file(
    project_id: str,
    repository_id: str,
    path: str,
) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectFileService(runtime.base_dir).read_file(project_id, repository_id, path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/lifecycle-preview/{action}")
async def preview_task_system_project_lifecycle(project_id: str, action: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectLifecycleService(runtime.base_dir).preview(project_id=project_id, action=action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/projects/{project_id}/lifecycle-runs")
async def list_task_system_project_lifecycle_runs(project_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectLifecycleService(runtime.base_dir).list_runs(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/projects/{project_id}/lifecycle-runs")
async def start_task_system_project_lifecycle_run(
    project_id: str,
    payload: ProjectLifecycleRunStartRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    try:
        return ProjectLifecycleService(runtime.base_dir).start(
            project_id=project_id,
            action=payload.action,
            execute=payload.execute,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/tasks/environment-groups/{group_id}")
async def upsert_task_system_environment_group(
    group_id: str,
    payload: TaskEnvironmentGroupUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.group_id != group_id:
        payload = payload.model_copy(update={"group_id": group_id})
    try:
        TaskEnvironmentRepository(runtime.base_dir).upsert_group(payload.model_dump())
    except TaskEnvironmentConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/environment-kind-templates")
async def list_task_system_environment_kind_templates() -> dict[str, object]:
    runtime = require_runtime()
    templates = [item.to_dict() for item in TaskEnvironmentKindTemplateRepository(runtime.base_dir).list()]
    return {
        "authority": "task_system.environment_kind_template_api",
        "kind_templates": templates,
        "summary": {"kind_template_count": len(templates)},
    }


@router.put("/tasks/environment-kind-templates/{kind_id}")
async def upsert_task_system_environment_kind_template(
    kind_id: str,
    payload: TaskEnvironmentKindTemplateUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    raw = payload.model_dump()
    raw["kind_id"] = kind_id
    try:
        TaskEnvironmentKindTemplateRepository(runtime.base_dir).upsert(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/environment-kind-templates/{kind_id}")
async def delete_task_system_environment_kind_template(kind_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        TaskEnvironmentKindTemplateRepository(runtime.base_dir).delete(kind_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/environments/{environment_id}")
async def upsert_task_system_environment(
    environment_id: str,
    payload: TaskEnvironmentUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    raw = payload.model_dump()
    if raw.get("record") or raw.get("spec"):
        record = dict(raw.get("record") or {})
        spec = dict(raw.get("spec") or {})
        record.setdefault("environment_id", environment_id)
        spec.setdefault("environment_id", environment_id)
        environment_payload = {"record": record, "spec": spec}
    else:
        environment_payload = {
            "record": {
                "environment_id": environment_id,
                "title": raw.get("title") or environment_id,
                "description": raw.get("description") or "",
                "group_id": raw.get("group_id") or "environment_group.general",
                "enabled": bool(raw.get("enabled", True)),
                "owner": raw.get("owner") or "system",
                "environment_kind": raw.get("environment_kind") or "custom",
                "default_visibility": raw.get("default_visibility") or "system",
                "metadata": dict(raw.get("metadata") or {}),
            },
            "spec": {
                "spec_id": f"envspec.{environment_id}.configured",
                "environment_id": environment_id,
                "environment_prompts": list(raw.get("environment_prompts") or []),
                "sandbox_policy": dict(raw.get("sandbox_policy") or {}),
                "file_management": dict(raw.get("file_management") or {}),
                "resource_space": dict(raw.get("resource_space") or {}),
                "memory_space": dict(raw.get("memory_space") or {}),
                "execution_policy": dict(raw.get("execution_policy") or {}),
                "risk_policy": dict(raw.get("risk_policy") or {}),
                "artifact_policy": dict(raw.get("artifact_policy") or {}),
                "observability_policy": dict(raw.get("observability_policy") or {}),
                "lifecycle_policy": dict(raw.get("lifecycle_policy") or {}),
                "metadata": dict(raw.get("metadata") or {}),
            },
        }
    try:
        TaskEnvironmentRepository(runtime.base_dir).upsert_environment(environment_payload)
    except (TaskEnvironmentConfigError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/environments/{environment_id}")
async def delete_task_system_environment(environment_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        TaskEnvironmentRepository(runtime.base_dir).delete_environment(environment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskEnvironmentConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/node-configurations")
async def list_task_system_node_configurations() -> dict[str, object]:
    runtime = require_runtime()
    payload = _task_system_payload(runtime.base_dir)
    return dict(payload.get("node_configuration_management") or {})


@router.put("/tasks/node-configurations/{node_config_id}")
async def upsert_task_system_node_configuration(
    node_config_id: str,
    payload: TaskNodeConfigurationUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    raw = payload.model_dump()
    raw["node_config_id"] = node_config_id
    try:
        TaskNodeConfigurationRepository(runtime.base_dir).upsert(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/node-configurations/{node_config_id}")
async def delete_task_system_node_configuration(node_config_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        TaskNodeConfigurationRepository(runtime.base_dir).delete(node_config_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.post("/tasks/node-configurations/{node_config_id}/runtime-preview")
async def preview_task_system_node_configuration_runtime(
    node_config_id: str,
    payload: TaskNodeRuntimePreviewRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    spec = _task_node_configuration_for_preview(runtime.base_dir, node_config_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="node configuration not found")
    environment_id = payload.environment_id or (spec.environment_scope[0] if spec.environment_scope else "")
    environment_payload: dict[str, object] = {}
    if environment_id:
        try:
            environment_payload = build_task_environment_catalog(
                registry=task_environment_registry_from_backend_dir(runtime.base_dir),
                engagement_plans=[],
            ).runtime_environment_payload(environment_id)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile_id = str(spec.executor_ref.get("agent_profile_id") or "")
    agent_id = str(spec.executor_ref.get("agent_id") or "")
    runtime_profile = {}
    if profile_id or agent_id:
        registry = AgentRuntimeRegistry(runtime.base_dir)
        profile = registry.get_profile_by_profile_id(profile_id) if profile_id else None
        if profile is None and agent_id:
            profile = registry.get_profile(agent_id)
        runtime_profile = profile.to_dict() if profile is not None else {}
    return {
        "authority": "task_system.node_configuration_runtime_preview",
        "node_configuration": spec.to_dict(),
        "task_environment": environment_payload,
        "runtime_profile": runtime_profile,
        "runtime_start_packet_preview": {
            "environment_id": environment_id,
            "environment_prompt_refs": [
                str(item.get("prompt_id") or "")
                for item in list(environment_payload.get("environment_prompts") or [])
                if isinstance(item, dict)
            ],
            "resource_space": dict(environment_payload.get("resource_space") or {}),
            "memory_space": dict(environment_payload.get("memory_space") or {}),
            "executor_ref": dict(spec.executor_ref),
            "contract_bindings": dict(spec.contract_bindings),
            "role_prompt": spec.role_prompt,
            "tool_policy": dict(spec.tool_policy),
            "failure_policy": dict(spec.failure_policy),
            "human_gate_policy": dict(spec.human_gate_policy),
        },
    }


@router.put("/tasks/task-graphs/{graph_id}")
async def upsert_task_system_task_graph(
    graph_id: str,
    payload: TaskGraphUpsertRequest,
) -> dict[str, object]:
    runtime = require_runtime()
    if payload.graph_id != graph_id:
        payload = payload.model_copy(update={"graph_id": graph_id})
    try:
        consolidated_nodes = _consolidate_task_graph_node_role_prompts(
            runtime.base_dir,
            graph_id=payload.graph_id,
            graph_title=payload.title,
            domain_id=payload.domain_id,
            nodes=tuple(dict(item) for item in payload.nodes),
        )
        TaskFlowRegistry(runtime.base_dir).upsert_task_graph(
            graph_id=payload.graph_id,
            title=payload.title,
            domain_id=payload.domain_id,
            graph_kind=payload.graph_kind,
            entry_node_id=payload.entry_node_id,
            output_node_id=payload.output_node_id,
            nodes=consolidated_nodes,
            edges=tuple(dict(item) for item in payload.edges),
            graph_contract_id=payload.graph_contract_id,
            contract_bindings=payload.contract_bindings,
            default_protocol_id=payload.default_protocol_id,
            working_memory_policy_profile_id=payload.working_memory_policy_profile_id,
            working_memory_policy=payload.working_memory_policy,
            runtime_policy=payload.runtime_policy,
            context_policy=payload.context_policy,
            loop_frames=tuple(dict(item) for item in payload.loop_frames),
            publish_state=payload.publish_state,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
        if payload.publish_state == "published":
            publish_graph_config_for_graph(base_dir=runtime.base_dir, graph_id=payload.graph_id)
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
