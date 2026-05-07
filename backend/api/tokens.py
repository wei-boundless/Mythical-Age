from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import require_runtime
from token_accounting import count_text_tokens

router = APIRouter()

class FileTokensRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


def _count_tokens(text: str) -> int:
    return count_text_tokens(text)


@router.get("/tokens/session/{session_id}")
async def session_tokens(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()

    record = runtime.session_manager.get_history(session_id)
    system_prompt = runtime.query_runtime.build_system_prompt_for_session(session_id)
    message_text = []
    for item in record.get("messages", []):
        message_text.append(str(item.get("content", "")))
        for tool_call in item.get("tool_calls", []) or []:
            message_text.append(str(tool_call))

    system_tokens = _count_tokens(system_prompt)
    message_tokens = _count_tokens("\n".join(message_text))
    token_diagnostics = runtime.memory_facade.inspect_session_history_tokens(
        session_id=session_id,
        messages=list(record.get("messages", [])),
    )
    raw_history_tokens = int(token_diagnostics.get("raw_history_tokens", 0))
    context_compaction: dict[str, Any] = {}
    try:
        _compacted_history, context_compaction = runtime.memory_facade.inspect_memory_context_compaction(
            session_id,
            record.get("messages", []),
        )
    except Exception:
        context_compaction = {}
    history_tokens = int(context_compaction.get("estimated_tokens_after") or raw_history_tokens)
    history_budget_tokens = int(token_diagnostics.get("history_budget_tokens", 0))
    history_remaining_tokens = max(history_budget_tokens - history_tokens, 0)
    history_usage_ratio = (
        min(history_tokens / history_budget_tokens, 1.0)
        if history_budget_tokens > 0
        else 0.0
    )
    history_remaining_ratio = (
        max(history_remaining_tokens / history_budget_tokens, 0.0)
        if history_budget_tokens > 0
        else 0.0
    )
    history_pressure_level = str(
        context_compaction.get("pressure_level")
        or token_diagnostics.get("history_pressure_level", "normal")
    )
    return {
        "system_tokens": system_tokens,
        "message_tokens": message_tokens,
        "total_tokens": system_tokens + message_tokens,
        "raw_history_tokens": raw_history_tokens,
        "history_tokens": history_tokens,
        "history_budget_tokens": history_budget_tokens,
        "history_remaining_tokens": history_remaining_tokens,
        "history_usage_ratio": round(history_usage_ratio, 4),
        "history_remaining_ratio": round(history_remaining_ratio, 4),
        "history_pressure_level": history_pressure_level,
        "history_compaction_strategy": str(context_compaction.get("strategy") or "none"),
        "history_did_compact": bool(context_compaction.get("did_compact", False)),
        "history_did_microcompact": bool(context_compaction.get("did_microcompact", False)),
        "history_did_full_compact": bool(context_compaction.get("did_full_compact", False)),
    }


@router.post("/tokens/files")
async def file_tokens(payload: FileTokensRequest) -> dict[str, Any]:
    runtime = require_runtime()

    files: list[dict[str, Any]] = []
    total = 0
    for relative_path in payload.paths:
        path = (runtime.base_dir / relative_path).resolve()
        if not path.exists() or path.is_dir():
            continue
        count = _count_tokens(path.read_text(encoding="utf-8"))
        total += count
        files.append({"path": relative_path, "tokens": count})

    return {"files": files, "total_tokens": total}
