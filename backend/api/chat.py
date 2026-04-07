from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from graph.agent import agent_manager

router = APIRouter()
logger = logging.getLogger(__name__)

HIDDEN_SKILL_NOTICE = "[internal skill instructions hidden]"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str
    stream: bool = True


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _new_segment() -> dict[str, Any]:
    return {"content": "", "tool_calls": []}


def _is_internal_skill_read_tool_call(tool_call: dict[str, Any]) -> bool:
    tool_name = str(tool_call.get("tool", "") or "").strip().lower()
    raw = f"{tool_call.get('input', '')}\n{tool_call.get('output', '')}".lower()
    return tool_name == "read_file" and "skills/" in raw and "/skill.md" in raw


def _looks_like_skill_document(content: str) -> bool:
    normalized = content.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    has_skill_frontmatter = (
        (normalized.startswith("---") or lowered.startswith("name:"))
        and "metadata:" in lowered
        and "description:" in lowered
    )
    has_skill_sections = "display_name:" in lowered and (
        "## execution steps" in lowered
        or "## output format" in lowered
        or "鐩爣" in normalized
        or "鎵ц姝ラ" in normalized
        or "杈撳嚭鏍煎紡" in normalized
        or "鏁呴殰鎺掓煡" in normalized
        or "鏌ヨ绛栫暐" in normalized
    )
    return has_skill_frontmatter or has_skill_sections


def _sanitize_tool_call(tool_call: dict[str, Any]) -> dict[str, Any] | None:
    if _is_internal_skill_read_tool_call(tool_call):
        return None

    sanitized = {
        "tool": tool_call.get("tool", "tool"),
        "input": str(tool_call.get("input", "") or ""),
        "output": str(tool_call.get("output", "") or ""),
    }
    input_is_skill = _looks_like_skill_document(sanitized["input"])
    output_is_skill = _looks_like_skill_document(sanitized["output"])

    if (input_is_skill and not sanitized["output"].strip()) or (input_is_skill and output_is_skill):
        return None

    if input_is_skill:
        sanitized["input"] = HIDDEN_SKILL_NOTICE
    if output_is_skill:
        sanitized["output"] = HIDDEN_SKILL_NOTICE
    return sanitized


def _finalize_segments(
    segments: list[dict[str, Any]],
    current_segment: dict[str, Any],
    *,
    fallback_content: str = "",
) -> list[dict[str, Any]]:
    finalized = list(segments)
    candidate = {
        "content": current_segment.get("content", ""),
        "tool_calls": list(current_segment.get("tool_calls", [])),
    }
    if not str(candidate["content"]).strip() and fallback_content:
        candidate["content"] = fallback_content
    if str(candidate["content"]).strip() or candidate["tool_calls"]:
        finalized.append(candidate)
    return finalized


def _build_assistant_messages(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    persisted: list[dict[str, Any]] = []
    for segment in segments:
        filtered_tool_calls = [
            sanitized
            for tool_call in (segment.get("tool_calls") or [])
            for sanitized in [_sanitize_tool_call(tool_call)]
            if sanitized is not None
        ]
        content = str(segment.get("content", "") or "")
        if _looks_like_skill_document(content) and not filtered_tool_calls:
            continue
        persisted.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": filtered_tool_calls or None,
            }
        )
    return persisted


async def _run_post_turn_tasks(session_id: str, *, title_seed: str | None = None) -> None:
    session_manager = agent_manager.session_manager

    try:
        await asyncio.to_thread(agent_manager.refresh_session_memory, session_id)
    except Exception:
        logger.exception("Failed to refresh session memory for %s", session_id)

    try:
        await asyncio.to_thread(agent_manager.extract_durable_memories, session_id)
    except Exception:
        logger.exception("Failed to extract durable memories for %s", session_id)

    if title_seed and session_manager is not None:
        try:
            title = await agent_manager.generate_title(title_seed)
            session_manager.set_title(session_id, title)
        except Exception:
            logger.exception("Failed to generate title for session %s", session_id)


@router.post("/chat")
async def chat(payload: ChatRequest):
    session_manager = agent_manager.session_manager
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Agent manager is not initialized")

    history_record = session_manager.load_session_record(payload.session_id)
    history = session_manager.load_session_for_agent(
        payload.session_id,
        include_compressed_context=False,
    )
    is_first_user_message = not any(
        message.get("role") == "user"
        for message in history_record.get("messages", [])
    )

    async def event_generator():
        segments: list[dict[str, Any]] = []
        current_segment = _new_segment()
        assistant_persisted = False

        try:
            session_manager.save_message(payload.session_id, "user", payload.message)

            async for event in agent_manager.astream(payload.session_id, payload.message, history):
                event_type = event["type"]

                if event_type == "token":
                    current_segment["content"] += event.get("content", "")
                elif event_type == "tool_start":
                    current_segment["tool_calls"].append(
                        {
                            "tool": event.get("tool", "tool"),
                            "input": event.get("input", ""),
                            "output": "",
                        }
                    )
                elif event_type == "tool_end":
                    if current_segment["tool_calls"]:
                        current_segment["tool_calls"][-1]["output"] = event.get("output", "")
                elif event_type == "new_response":
                    segments = _finalize_segments(segments, current_segment)
                    current_segment = _new_segment()
                elif event_type == "done":
                    segments = _finalize_segments(
                        segments,
                        current_segment,
                        fallback_content=str(event.get("content", "") or ""),
                    )
                    assistant_messages = _build_assistant_messages(segments)
                    if assistant_messages:
                        session_manager.append_messages(payload.session_id, assistant_messages)
                        assistant_persisted = True

                    asyncio.create_task(
                        _run_post_turn_tasks(
                            payload.session_id,
                            title_seed=payload.message if is_first_user_message else None,
                        )
                    )

                    data = {key: value for key, value in event.items() if key != "type"}
                    yield _sse(event_type, data)
                    break

                data = {key: value for key, value in event.items() if key != "type"}
                yield _sse(event_type, data)
        except Exception as exc:
            if not assistant_persisted:
                try:
                    partial_segments = _finalize_segments(segments, current_segment)
                    assistant_messages = _build_assistant_messages(partial_segments)
                    if assistant_messages:
                        session_manager.append_messages(payload.session_id, assistant_messages)
                    else:
                        session_manager.save_message(
                            payload.session_id,
                            "assistant",
                            f"Request failed: {exc}",
                        )
                except Exception:
                    logger.exception(
                        "Failed to persist errored assistant response for session %s",
                        payload.session_id,
                    )
            yield _sse("error", {"error": str(exc)})

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
