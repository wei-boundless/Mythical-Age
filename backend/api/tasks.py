from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from operations import RuntimeApprovalContext
from tasks import TaskFlowRegistry, build_task_runtime_contract_preview

router = APIRouter()


class TaskPreviewApprovalContextRequest(BaseModel):
    interactive_ui_available: bool = True
    approval_hook_available: bool = False
    bubble_to_parent_allowed: bool = False
    headless_mode: bool = False


class TaskRuntimeContractPreviewRequest(BaseModel):
    session_id: str = Field(default="session-preview")
    task_id: str = Field(default="task-preview")
    user_goal: str = Field(..., min_length=1)
    source: str = Field(default="manual_preview")
    approval_context: TaskPreviewApprovalContextRequest = Field(default_factory=TaskPreviewApprovalContextRequest)


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


@router.post("/tasks/runtime-contract/preview")
async def task_runtime_contract_preview(payload: TaskRuntimeContractPreviewRequest) -> dict[str, object]:
    return build_task_runtime_contract_preview(
        session_id=payload.session_id,
        task_id=payload.task_id,
        user_goal=payload.user_goal,
        source=payload.source,
        approval_context=RuntimeApprovalContext(
            interactive_ui_available=payload.approval_context.interactive_ui_available,
            approval_hook_available=payload.approval_context.approval_hook_available,
            bubble_to_parent_allowed=payload.approval_context.bubble_to_parent_allowed,
            headless_mode=payload.approval_context.headless_mode,
        ),
    )
