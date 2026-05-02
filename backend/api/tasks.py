from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from operations import AgentRegistry
from tasks import TaskFlowRegistry, TaskTemplateRegistry, build_task_runtime_contract

router = APIRouter()


class TaskRuntimeContractRequest(BaseModel):
    session_id: str = Field(default="session-runtime")
    task_id: str = Field(default="task-runtime")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="manual_runtime")


class TaskAgentUpsertRequest(BaseModel):
    agent_id: str = Field(..., min_length=3)
    display_name: str = Field(..., min_length=1, max_length=120)
    owner_system: str = Field(default="task_system", max_length=80)
    profile_type: str = Field(default="worker_sub_agent", max_length=40)
    lifecycle_state: str = Field(default="enabled", max_length=40)
    default_soul_id: str = Field(default="", max_length=80)
    default_projection_template_id: str = Field(default="", max_length=160)
    governance_status: str = Field(default="task_managed", max_length=80)
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskFlowUpsertRequest(BaseModel):
    flow_id: str = Field(..., min_length=3, max_length=160)
    task_family: str = Field(..., min_length=1, max_length=80)
    task_mode: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    default_agent_id: str = Field(..., min_length=3, max_length=160)
    default_workflow_id: str = Field(default="", max_length=160)
    default_projection_template_id: str = Field(default="", max_length=160)
    default_runtime_lane: str = Field(default="", max_length=120)
    default_memory_scope: str = Field(default="", max_length=120)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class GeneralTaskProfileUpsertRequest(BaseModel):
    profile_id: str = Field(..., min_length=3, max_length=160)
    title: str = Field(..., min_length=1, max_length=160)
    default_agent_id: str = Field(default="agent:main", min_length=3, max_length=160)
    default_workflow_id: str = Field(default="", max_length=160)
    default_projection_template_id: str = Field(default="", max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    conversation_entry_policy: str = Field(default="user_dialogue_to_main_agent", max_length=160)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskAssignmentUpsertRequest(BaseModel):
    task_id: str = Field(..., min_length=3, max_length=160)
    task_title: str = Field(..., min_length=1, max_length=160)
    task_kind: str = Field(default="specific_task", max_length=40)
    task_family: str = Field(..., min_length=1, max_length=80)
    task_mode: str = Field(..., min_length=1, max_length=80)
    flow_id: str = Field(default="", max_length=160)
    default_agent_id: str = Field(default="agent:main", min_length=3, max_length=160)
    participant_agent_ids: list[str] = Field(default_factory=list)
    workflow_id: str = Field(default="", max_length=160)
    workflow_file_ref: str = Field(default="", max_length=260)
    projection_template_id: str = Field(default="", max_length=160)
    input_contract_id: str = Field(default="", max_length=160)
    output_contract_id: str = Field(default="", max_length=160)
    task_structure: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


@router.get("/tasks")
async def list_tasks(session_id: str | None = Query(default=None)) -> list[dict[str, object]]:
    runtime = require_runtime()
    return [task.to_dict() for task in runtime.task_coordinator.list_tasks(session_id=session_id)]


@router.get("/tasks/overview")
async def task_system_overview() -> dict[str, object]:
    runtime = require_runtime()
    return TaskFlowRegistry(runtime.base_dir).build_overview()


@router.get("/tasks/flows")
async def task_system_flows() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {"authority": "task_system.task_flows", "flows": [item.to_dict() for item in registry.list_flows()]}


@router.get("/tasks/general-profiles")
async def task_system_general_profiles() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {
        "authority": "task_system.general_task_profiles",
        "profiles": [item.to_dict() for item in registry.list_general_task_profiles()],
    }


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
            default_projection_template_id=payload.default_projection_template_id,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            conversation_entry_policy=payload.conversation_entry_policy,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskFlowRegistry(runtime.base_dir).build_overview()


@router.get("/tasks/specific-assignments")
async def task_system_specific_assignments() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {
        "authority": "task_system.task_assignments",
        "assignments": [item.to_dict() for item in registry.list_task_assignments()],
    }


@router.put("/tasks/specific-assignments/{task_id}")
async def upsert_task_system_specific_assignment(task_id: str, payload: TaskAssignmentUpsertRequest) -> dict[str, object]:
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
            projection_template_id=payload.projection_template_id,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            task_structure=payload.task_structure,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskFlowRegistry(runtime.base_dir).build_overview()


@router.put("/tasks/agents/{agent_id}")
async def upsert_task_system_agent(agent_id: str, payload: TaskAgentUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.agent_id != agent_id:
        payload = payload.model_copy(update={"agent_id": agent_id})
    try:
        AgentRegistry(runtime.base_dir).upsert_agent(
            agent_id=payload.agent_id,
            display_name=payload.display_name,
            owner_system=payload.owner_system,
            profile_type=payload.profile_type,
            lifecycle_state=payload.lifecycle_state,
            default_soul_id=payload.default_soul_id,
            default_projection_template_id=payload.default_projection_template_id,
            governance_status=payload.governance_status,
            metadata=payload.metadata,
        )
    except (PermissionError, ValueError) as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskFlowRegistry(runtime.base_dir).build_overview()


@router.put("/tasks/flows/{flow_id}")
async def upsert_task_system_flow(flow_id: str, payload: TaskFlowUpsertRequest) -> dict[str, object]:
    runtime = require_runtime()
    if payload.flow_id != flow_id:
        payload = payload.model_copy(update={"flow_id": flow_id})
    try:
        TaskFlowRegistry(runtime.base_dir).upsert_flow(
            flow_id=payload.flow_id,
            task_mode=payload.task_mode,
            task_family=payload.task_family,
            title=payload.title,
            input_contract_id=payload.input_contract_id,
            output_contract_id=payload.output_contract_id,
            default_agent_id=payload.default_agent_id,
            default_workflow_id=payload.default_workflow_id,
            default_projection_template_id=payload.default_projection_template_id,
            default_runtime_lane=payload.default_runtime_lane,
            default_memory_scope=payload.default_memory_scope,
            enabled=payload.enabled,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskFlowRegistry(runtime.base_dir).build_overview()


@router.get("/tasks/agent-bindings")
async def task_system_agent_bindings() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {"authority": "task_system.agent_bindings", "bindings": [item.to_dict() for item in registry.list_bindings()]}


@router.get("/tasks/agent-task-connections")
async def task_system_agent_task_connections(
    owner_system: str = Query(default=""),
    task_family: str = Query(default=""),
) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return registry.build_agent_task_connection_overview(owner_system=owner_system, task_family=task_family)


@router.get("/tasks/agent-task-connections/{agent_id}")
async def task_system_agent_task_connection(agent_id: str) -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    profile = next((item for item in registry.list_agent_task_connection_profiles() if item.agent_id == agent_id), None)
    if profile is None:
        return {
            "authority": "task_system.agent_task_connection",
            "profile": {},
            "status": "not_found",
        }
    return {
        "authority": "task_system.agent_task_connection",
        "profile": profile.to_dict(),
        "status": "found",
    }


@router.get("/tasks/agent-carrying-profiles")
async def task_system_agent_carrying_profiles() -> dict[str, object]:
    runtime = require_runtime()
    return TaskFlowRegistry(runtime.base_dir).build_agent_carrying_overview()


@router.get("/tasks/agent-carrying-profiles/{agent_id}")
async def task_system_agent_carrying_profile(agent_id: str) -> dict[str, object]:
    runtime = require_runtime()
    profile = next((item for item in TaskFlowRegistry(runtime.base_dir).list_agent_task_carrying_profiles() if item.agent_id == agent_id), None)
    if profile is None:
        return {
            "authority": "task_system.agent_carrying_profile",
            "profile": {},
            "status": "not_found",
        }
    return {
        "authority": "task_system.agent_carrying_profile",
        "profile": profile.to_dict(),
        "status": "found",
    }


@router.get("/tasks/connection-diagnostics")
async def task_system_connection_diagnostics() -> dict[str, object]:
    runtime = require_runtime()
    return TaskFlowRegistry(runtime.base_dir).build_connection_diagnostics()


@router.get("/tasks/templates")
async def task_system_templates() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskTemplateRegistry(runtime.base_dir)
    return {"authority": "task_system.templates", "templates": [item.to_dict() for item in registry.list_templates()]}


@router.get("/tasks/template-validation-matrix")
async def task_system_template_validation_matrix() -> dict[str, object]:
    runtime = require_runtime()
    return TaskTemplateRegistry(runtime.base_dir).build_validation_matrix()


@router.get("/tasks/link-permission-matrix")
async def task_system_link_permission_matrix() -> dict[str, object]:
    runtime = require_runtime()
    return TaskFlowRegistry(runtime.base_dir).build_link_permission_matrix()


@router.get("/tasks/coordination-tasks")
async def task_system_coordination_tasks() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {
        "authority": "task_system.coordination_tasks",
        "coordination_tasks": [item.to_dict() for item in registry.list_coordination_tasks()],
    }


@router.get("/tasks/topology-templates")
async def task_system_topology_templates() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {
        "authority": "task_system.topology_templates",
        "topology_templates": [item.to_dict() for item in registry.list_topology_templates()],
    }


@router.post("/tasks/runtime-contract")
async def task_runtime_contract(payload: TaskRuntimeContractRequest) -> dict[str, object]:
    return build_task_runtime_contract(
        session_id=payload.session_id,
        task_id=payload.task_id,
        user_goal=payload.user_goal,
        source=payload.source,
    )
