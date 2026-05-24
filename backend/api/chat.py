from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from query import QueryRequest
from sessions import validate_session_id

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str
    stream: bool = True
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)
    search_policy: list[str] | None = None
    task_selection: dict[str, Any] = Field(default_factory=dict)
    task_order_intent: dict[str, Any] = Field(default_factory=dict)
    model_selection: dict[str, Any] = Field(default_factory=dict)
    image_generation: dict[str, Any] = Field(default_factory=dict)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_status(code: str) -> int:
    if code == "timeout":
        return 504
    if code == "rate_limit":
        return 429
    if code == "provider_unavailable":
        return 503
    return 500


@router.post("/chat")
async def chat(payload: ChatRequest):
    runtime = require_runtime()
    session_id = validate_session_id(payload.session_id)
    request = QueryRequest(
        session_id=session_id,
        message=payload.message,
        ephemeral_system_messages=list(payload.ephemeral_system_messages or []),
        explicit_subtasks=list(payload.explicit_subtasks or []),
        search_policy=list(payload.search_policy) if payload.search_policy is not None else None,
        task_selection=dict(payload.task_selection or {}),
        task_order_intent=dict(payload.task_order_intent or {}),
        model_selection=dict(payload.model_selection or {}),
        image_generation=dict(payload.image_generation or {}),
    )

    async def event_generator():
        async for event in runtime.query_runtime.astream(request):
            event_type = str(event.get("type", "message"))
            data = {key: value for key, value in event.items() if key != "type"}
            yield _sse(event_type, data)

    if payload.stream:
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    async for event in runtime.query_runtime.astream(request):
        event_type = str(event.get("type", "message"))
        if event_type == "done":
            response: dict[str, Any] = {"content": str(event.get("content", "") or "")}
            image = event.get("image")
            if image is not None:
                response["image"] = image
            return JSONResponse(response)
        if event_type == "error":
            code = str(event.get("code", "") or "").strip()
            return JSONResponse(
                {
                    "error": str(event.get("error", "") or "Request failed"),
                    "code": code or None,
                },
                status_code=_error_status(code),
            )

    return JSONResponse(
        {
            "error": "Request finished without a final response.",
            "code": "missing_done",
        },
        status_code=500,
    )
