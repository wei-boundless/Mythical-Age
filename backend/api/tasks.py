from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from tasks import TaskFlowRegistry, build_task_runtime_contract

router = APIRouter()


class TaskRuntimeContractRequest(BaseModel):
    session_id: str = Field(default="session-runtime")
    task_id: str = Field(default="task-runtime")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="manual_runtime")


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


@router.get("/tasks/agent-bindings")
async def task_system_agent_bindings() -> dict[str, object]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    return {"authority": "task_system.agent_bindings", "bindings": [item.to_dict() for item in registry.list_bindings()]}


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
