from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import require_runtime
from operations import AgentRegistry
from tasks import TaskFlowRegistry, TaskWorkflowRegistry, build_task_runtime_contract

router = APIRouter()


class TaskRuntimeContractRequest(BaseModel):
    session_id: str = Field(default="session-runtime")
    task_id: str = Field(default="task-runtime")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="manual_runtime")


class TaskAgentUpsertRequest(BaseModel):
    agent_id: str = Field(..., min_length=3)
    agent_name: str = Field(..., min_length=1, max_length=120)
    agent_category: str = Field(default="worker_sub_agent", max_length=40)
    interface_target: str = Field(default="worker_task_console", max_length=120)
    description: str = Field(default="", max_length=400)
    enabled: bool = True
    editable: bool = True
    default_soul_id: str = Field(default="", max_length=80)
    default_projection_id: str = Field(default="", max_length=160)
    task_scope: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class GeneralTaskProfileUpsertRequest(BaseModel):
    profile_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    default_agent_id: str = Field(default="agent:0", min_length=3, max_length=160)
    default_workflow_id: str = Field(default="", max_length=160)
    default_projection_id: str = Field(default="", max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    conversation_entry_policy: str = Field(default="user_dialogue_to_main_agent", max_length=160)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class SpecificTaskUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    task_title: str = Field(..., min_length=1, max_length=160)
    task_kind: str = Field(default="specific_task", max_length=40)
    task_family: str = Field(..., min_length=1, max_length=80)
    task_mode: str = Field(..., min_length=1, max_length=80)
    flow_id: str = Field(default="", max_length=160)
    default_agent_id: str = Field(default="agent:0", min_length=3, max_length=160)
    participant_agent_ids: list[str] = Field(default_factory=list)
    workflow_id: str = Field(default="", max_length=160)
    workflow_file_ref: str = Field(default="", max_length=260)
    projection_id: str = Field(default="", max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    trigger_signals: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)
    task_structure: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskWorkflowUpsertRequest(BaseModel):
    workflow_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    task_mode: str = Field(default="", max_length=80)
    default_projection_id: str = Field(default="", max_length=160)
    allowed_projection_ids: list[str] = Field(default_factory=list)
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
    participant_agent_ids: list[str] = Field(default_factory=list)
    topology_template_id: str = Field(default="", max_length=160)
    shared_context_policy: str = Field(default="explicit_refs_only", max_length=120)
    memory_sharing_policy: str = Field(default="isolated_by_default", max_length=120)
    handoff_policy: str = Field(default="filtered_handoff", max_length=120)
    conflict_resolution_policy: str = Field(default="coordinator_review", max_length=120)
    output_merge_policy: str = Field(default="coordinator_final_merge", max_length=120)
    stop_conditions: list[str] = Field(default_factory=list)
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


def _task_system_payload(base_dir) -> dict[str, object]:
    registry = TaskFlowRegistry(base_dir)
    agent_catalog = AgentRegistry(base_dir).build_catalog()
    workflows = TaskWorkflowRegistry(base_dir).build_catalog()
    general_tasks = [item.to_dict() for item in registry.list_general_task_profiles()]
    specific_tasks = [item.to_dict() for item in registry.list_task_assignments()]
    coordination_tasks = [item.to_dict() for item in registry.list_coordination_tasks()]
    topology_templates = [item.to_dict() for item in registry.list_topology_templates()]
    return {
        "authority": "task_system.management_console",
        "summary": {
            **agent_catalog["summary"],
            "general_task_count": len(general_tasks),
            "specific_task_count": len(specific_tasks),
            "workflow_count": workflows["summary"]["workflow_count"],
            "coordination_task_count": len(coordination_tasks),
            "topology_template_count": len(topology_templates),
        },
        "agent_management": {
            "categories": [
                {
                    "category_id": "main_agent",
                    "title": "主 Agent",
                    "editable": False,
                    "agents": [item for item in agent_catalog["agents"] if item.get("agent_category") == "main_agent"],
                },
                {
                    "category_id": "system_management_agent",
                    "title": "系统管理 Agent",
                    "editable": False,
                    "agents": [item for item in agent_catalog["agents"] if item.get("agent_category") == "system_management_agent"],
                },
                {
                    "category_id": "worker_sub_agent",
                    "title": "工作子 Agent",
                    "editable": True,
                    "agents": [item for item in agent_catalog["agents"] if item.get("agent_category") == "worker_sub_agent"],
                },
            ]
        },
        "task_management": {
            "general_tasks": general_tasks,
            "specific_tasks": specific_tasks,
            "workflow_resources": workflows["workflows"],
        },
        "coordination_management": {
            "coordination_tasks": coordination_tasks,
            "topology_templates": topology_templates,
        },
    }


@router.get("/tasks/overview")
async def task_system_overview() -> dict[str, object]:
    runtime = require_runtime()
    return _task_system_payload(runtime.base_dir)


@router.get("/tasks/agents/next-worker-id")
async def task_system_next_worker_agent_id() -> dict[str, str]:
    runtime = require_runtime()
    return {
        "agent_id": AgentRegistry(runtime.base_dir).next_worker_agent_id(),
        "authority": "task_system.agent_registry",
    }


@router.get("/tasks/workflows")
async def task_system_workflows() -> dict[str, object]:
    runtime = require_runtime()
    return TaskWorkflowRegistry(runtime.base_dir).build_catalog()


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
            default_projection_id=payload.default_projection_id,
            allowed_projection_ids=tuple(payload.allowed_projection_ids),
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


@router.put("/tasks/agents/{agent_id}")
async def upsert_task_system_agent(agent_id: str, payload: TaskAgentUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.agent_id != agent_id:
        payload = payload.model_copy(update={"agent_id": agent_id})
    try:
        AgentRegistry(runtime.base_dir).upsert_agent(
            agent_id=payload.agent_id,
            agent_name=payload.agent_name,
            agent_category=payload.agent_category,
            interface_target=payload.interface_target,
            description=payload.description,
            enabled=payload.enabled,
            editable=payload.editable,
            default_soul_id=payload.default_soul_id,
            default_projection_id=payload.default_projection_id,
            task_scope=tuple(payload.task_scope),
            metadata=payload.metadata,
        )
    except (PermissionError, ValueError) as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.delete("/tasks/agents/{agent_id}")
async def delete_task_system_agent(agent_id: str) -> dict[str, object]:
    runtime = require_runtime()
    try:
        AgentRegistry(runtime.base_dir).delete_agent(agent_id)
    except KeyError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="agent not found") from exc
    except PermissionError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.put("/tasks/general-profiles/{profile_id}")
async def upsert_task_system_general_profile(profile_id: str, payload: GeneralTaskProfileUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.profile_id != profile_id:
        payload = payload.model_copy(update={"profile_id": profile_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_general_task_profile(
            profile_id=payload.profile_id,
            title=payload.title,
            default_agent_id=payload.default_agent_id,
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


@router.put("/tasks/specific-assignments/{task_id}")
async def upsert_task_system_specific_assignment(task_id: str, payload: SpecificTaskUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.task_id != task_id:
        payload = payload.model_copy(update={"task_id": task_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_task_assignment(
            task_id=payload.task_id,
            task_title=payload.task_title,
            task_kind=payload.task_kind,
            task_family=payload.task_family,
            task_mode=payload.task_mode,
            flow_id=payload.flow_id,
            default_agent_id=payload.default_agent_id,
            participant_agent_ids=tuple(payload.participant_agent_ids),
            workflow_id=payload.workflow_id,
            workflow_file_ref=payload.workflow_file_ref,
            projection_id=payload.projection_id,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            task_structure={
                **payload.task_structure,
                "trigger_signals": payload.trigger_signals,
                "notes": payload.notes,
            },
            enabled=payload.enabled,
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
            participant_agent_ids=tuple(payload.participant_agent_ids),
            topology_template_id=payload.topology_template_id,
            shared_context_policy=payload.shared_context_policy,
            memory_sharing_policy=payload.memory_sharing_policy,
            handoff_policy=payload.handoff_policy,
            conflict_resolution_policy=payload.conflict_resolution_policy,
            output_merge_policy=payload.output_merge_policy,
            stop_conditions=tuple(payload.stop_conditions),
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
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _task_system_payload(runtime.base_dir)


@router.post("/tasks/runtime-contract")
async def task_runtime_contract(payload: TaskRuntimeContractRequest) -> dict[str, object]:
    return build_task_runtime_contract(
        session_id=payload.session_id,
        task_id=payload.task_id,
        user_goal=payload.user_goal,
        source=payload.source,
    )
