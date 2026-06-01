from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from runtime.prompt_accounting import TokenCounterRegistry
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()
TOKEN_COUNTER = TokenCounterRegistry()

class FileTokensRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


def _count_tokens(text: str) -> int:
    return TOKEN_COUNTER.count_text(text, provider="local", model="session_token_api").tokens


@router.get("/tokens/session/{session_id}")
async def session_tokens(
    session_id: str,
    workspace_view: str | None = Query(default=None, max_length=80),
    task_environment_id: str | None = Query(default=None, max_length=200),
    project_id: str | None = Query(default=None, max_length=240),
) -> dict[str, Any]:
    runtime = require_runtime()
    assert_optional_session_scope(
        runtime.session_manager,
        session_id,
        request_scope_from_query(workspace_view=workspace_view, task_environment_id=task_environment_id, project_id=project_id),
    )

    record = runtime.session_manager.get_history(session_id)
    prompt_usage = runtime.harness_runtime.single_agent_runtime_host.prompt_accounting_ledger.summarize_session(session_id)
    message_text = []
    for item in record.get("messages", []):
        message_text.append(str(item.get("content", "")))
        for tool_call in item.get("tool_calls", []) or []:
            message_text.append(str(tool_call))

    system_tokens = int(prompt_usage.get("prompt_tokens") or prompt_usage.get("predicted_total_tokens") or 0)
    message_tokens = _count_tokens("\n".join(message_text))
    messages = list(record.get("messages", []))
    py_messages = runtime.memory_facade.adapter.to_messages(messages, session_id=session_id)
    compactor = runtime.memory_facade.session_memory.compactor(session_id)
    raw_history_tokens = compactor.conversation_tokens(py_messages)
    pressure_level = compactor.pressure_level(raw_history_tokens, len(py_messages))
    token_diagnostics = {
        "raw_history_tokens": raw_history_tokens,
        "history_budget_tokens": int(compactor.effective_history_token_budget),
        "history_pressure_level": str(pressure_level),
    }
    raw_history_tokens = int(token_diagnostics.get("raw_history_tokens", 0))
    context_compaction: dict[str, Any] = {}
    try:
        _compacted_history, context_compaction = runtime.memory_facade.bundle_service.inspect_memory_context_compaction(
            session_id,
            messages,
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
        "prompt_accounting": prompt_usage,
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


