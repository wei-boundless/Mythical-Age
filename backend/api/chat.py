from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from query import QueryRequest

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str
    stream: bool = True
    ephemeral_system_messages: list[str] = Field(default_factory=list)
    explicit_subtasks: list[dict[str, Any]] = Field(default_factory=list)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(payload: ChatRequest):
    runtime = require_runtime()

    async def event_generator():
        async for event in runtime.query_runtime.astream(
            QueryRequest(
                session_id=payload.session_id,
                message=payload.message,
                ephemeral_system_messages=list(payload.ephemeral_system_messages or []),
                explicit_subtasks=list(payload.explicit_subtasks or []),
            )
        ):
            event_type = str(event.get("type", "message"))
            data = {key: value for key, value in event.items() if key != "type"}
            yield _sse(event_type, data)

    if payload.stream:
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    final_content = ""
    async for raw_event in event_generator():
        if raw_event.startswith("event: done"):
            data_start = raw_event.find("data:")
            if data_start >= 0:
                payload_data = json.loads(raw_event[data_start + 5 :].strip())
                final_content = str(payload_data.get("content", "") or "")
    return JSONResponse({"content": final_content})
