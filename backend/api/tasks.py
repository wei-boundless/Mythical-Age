from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from operations import RuntimeApprovalContext
from tasks import build_task_runtime_contract_preview

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
