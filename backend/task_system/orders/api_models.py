from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskOrderCreateRequest(BaseModel):
    session_id: str
    message: str = ""
    task_id: str = ""
    environment_id: str = ""
    source: str = "task_library"
    source_ref: str = ""
    objective: str = ""
    idempotency_key: str = ""
    task_selection: dict[str, Any] = Field(default_factory=dict)
    task_order_intent: dict[str, Any] = Field(default_factory=dict)


class TaskOrderProjectionResponse(BaseModel):
    projection: dict[str, Any]
