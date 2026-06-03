from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from memory_system.storage.models import Message
from runtime.prompt_accounting import TokenCounterRegistry
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()
TOKEN_COUNTER = TokenCounterRegistry()

class FileTokensRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class CompactSessionRequest(BaseModel):
    pressure_level: Literal["auto", "microcompact", "full_compact"] = "auto"
    reason: str = Field(default="manual_compact", max_length=240)
    reserved_output_tokens: int | None = Field(default=None, ge=0, le=200000)


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


@router.post("/tokens/session/{session_id}/compact/preview")
async def preview_session_compaction(
    session_id: str,
    payload: CompactSessionRequest | None = None,
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
    return _compact_session(runtime, session_id=session_id, payload=payload or CompactSessionRequest(), mode="preview")


@router.post("/tokens/session/{session_id}/compact/run")
async def run_session_compaction(
    session_id: str,
    payload: CompactSessionRequest | None = None,
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
    return _compact_session(runtime, session_id=session_id, payload=payload or CompactSessionRequest(), mode="run")


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


def _compact_session(
    runtime: Any,
    *,
    session_id: str,
    payload: CompactSessionRequest,
    mode: Literal["preview", "run"],
) -> dict[str, Any]:
    record = runtime.session_manager.get_history(session_id)
    raw_messages = list(record.get("messages") or [])
    py_messages = runtime.memory_facade.adapter.to_messages(raw_messages, session_id=session_id)
    compactor = runtime.memory_facade.session_memory.compactor(session_id)
    tokens_before = compactor.conversation_tokens(py_messages)
    pressure_level = compactor.pressure_level(tokens_before, len(py_messages))
    requested_level = str(payload.pressure_level or "auto")
    effective_level = pressure_level if requested_level == "auto" else requested_level
    result = compactor.apply_strategy(
        py_messages,
        pressure_level=effective_level,
        request_id=f"context_compaction:manual:{mode}:{session_id}",
        session_id=session_id,
        trigger="preview" if mode == "preview" else "manual",
        reason=payload.reason or "manual_compact",
        reserved_output_tokens=int(payload.reserved_output_tokens or 0),
        force_full_compact=requested_level == "full_compact",
    )
    receipt = dict(dict(result.diagnostics or {}).get("compact_boundary_receipt") or {})
    blocked = bool(receipt.get("blocked"))
    applied = False
    persisted: dict[str, Any] = {}
    if mode == "run" and not blocked and _result_rewrites_history(result):
        compressed_context = _compressed_context_after_compact(record, result.summary_message)
        stored_messages = _stored_messages_after_compact(result.messages)
        replace = getattr(runtime.session_manager, "replace_runtime_context", None)
        if callable(replace):
            persisted = replace(
                session_id,
                messages=stored_messages,
                compressed_context=compressed_context,
            )
            applied = True
    return {
        "authority": "api.tokens.session_compaction",
        "mode": mode,
        "session_id": session_id,
        "applied": applied,
        "requested_pressure_level": requested_level,
        "pressure_level": str(pressure_level),
        "effective_pressure_level": str(effective_level),
        "strategy": result.strategy,
        "did_compact": result.did_compact,
        "did_microcompact": result.did_microcompact,
        "did_full_compact": result.did_full_compact,
        "estimated_tokens_before": result.estimated_tokens_before,
        "estimated_tokens_after": result.estimated_tokens_after,
        "original_message_count": result.original_message_count,
        "compacted_message_count": result.compacted_message_count,
        "replaced_message_count": result.replaced_message_count,
        "preserved_recent_count": result.preserved_recent_count,
        "blocked": blocked,
        "blocked_reason": str(receipt.get("block_reason") or ""),
        "compact_boundary_receipt": receipt,
        "compression_budget_decision": dict(dict(result.diagnostics or {}).get("compression_budget_decision") or {}),
        "microcompact_cache_decision": dict(dict(result.diagnostics or {}).get("microcompact_cache_decision") or {}),
        "message_preview": [_message_preview(message) for message in result.messages[:8]],
        "persisted_message_count": len(list(persisted.get("messages") or [])) if persisted else len(raw_messages),
        "compressed_context_present": bool(str((persisted or record).get("compressed_context") or "")),
    }


def _result_rewrites_history(result: Any) -> bool:
    return bool(getattr(result, "did_full_compact", False)) or int(getattr(result, "replaced_message_count", 0) or 0) > 0


def _compressed_context_after_compact(record: dict[str, Any], summary_message: Message | None) -> str:
    if summary_message is None:
        return str(record.get("compressed_context") or "")
    return str(summary_message.content or "").strip()


def _stored_messages_after_compact(messages: list[Message]) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for message in list(messages or []):
        meta = dict(message.meta or {})
        if str(meta.get("kind") or "") == "compact_summary":
            continue
        if message.role == "system":
            continue
        stored.append(_message_to_session_dict(message))
    return stored


def _message_to_session_dict(message: Message) -> dict[str, Any]:
    payload = {
        "role": message.role,
        "content": message.content,
    }
    meta = dict(message.meta or {})
    if meta:
        payload["meta"] = meta
    return payload


def _message_preview(message: Message) -> dict[str, Any]:
    content = str(message.content or "")
    return {
        "role": message.role,
        "kind": str(dict(message.meta or {}).get("kind") or ""),
        "content_preview": content[:240],
        "tokens": _count_tokens(content),
    }


