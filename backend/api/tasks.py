from __future__ import annotations

from fastapi import APIRouter, Query

from api.deps import require_runtime

router = APIRouter()


@router.get("/tasks")
async def list_tasks(session_id: str | None = Query(default=None)) -> list[dict[str, object]]:
    runtime = require_runtime()
    return [task.to_dict() for task in runtime.task_coordinator.list_tasks(session_id=session_id)]
