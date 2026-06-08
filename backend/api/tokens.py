from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.deps import require_runtime
from runtime.context_management.session_compaction import (
    build_context_usage_snapshot,
    cache_metrics_from_context_meter,
    compact_session_history,
    count_tokens,
    prompt_accounting_ledger,
)
from task_system.session_scope import assert_optional_session_scope, request_scope_from_query

router = APIRouter()

class FileTokensRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class CompactSessionRequest(BaseModel):
    pressure_level: Literal["auto", "microcompact", "full_compact"] = "auto"
    reason: str = Field(default="manual_compact", max_length=240)
    reserved_output_tokens: int | None = Field(default=None, ge=0, le=200000)


def _count_tokens(text: str) -> int:
    return count_tokens(text)


def _messages_token_text(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        chunks.append(str(item.get("content", "")))
        reasoning = str(item.get("reasoning_content") or "").strip()
        if reasoning:
            chunks.append(reasoning)
        for tool_call in item.get("tool_calls", []) or []:
            chunks.append(str(tool_call))
    return "\n".join(chunks)


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
    ledger = prompt_accounting_ledger(runtime)
    prompt_usage = ledger.summarize_session(session_id)

    raw_messages = list(record.get("messages", []))
    api_transcript_loader = getattr(runtime.session_manager, "load_session_for_api", None)
    cumulative_messages = (
        list(api_transcript_loader(session_id))
        if callable(api_transcript_loader)
        else raw_messages
    )
    context_snapshot = build_context_usage_snapshot(
        runtime,
        session_id=session_id,
        raw_messages=raw_messages,
        session_record=record,
    )
    context_meter = context_snapshot.to_dict()
    context_recovery_package = _context_recovery_package_status(
        runtime,
        session_id=session_id,
        raw_messages=raw_messages,
    )
    system_tokens = int(prompt_usage.get("prompt_tokens") or prompt_usage.get("predicted_total_tokens") or 0)
    message_tokens = _count_tokens(_messages_token_text(raw_messages))
    cumulative_transcript_tokens = _count_tokens(_messages_token_text(cumulative_messages))
    context_compaction = compact_session_history(
        runtime,
        session_id=session_id,
        mode="preview",
        pressure_level="auto",
        reason="session_token_status_preview",
        pressure_source="history",
        context_snapshot=context_snapshot,
    )
    raw_history_tokens = int(context_compaction.get("estimated_tokens_before") or 0)
    history_tokens = int(context_compaction.get("estimated_tokens_after") or raw_history_tokens)
    compression_saved_tokens = max(cumulative_transcript_tokens - history_tokens, 0)
    compression_ratio = (
        min(history_tokens / cumulative_transcript_tokens, 1.0)
        if cumulative_transcript_tokens > 0
        else 1.0
    )
    history_budget_tokens = int(context_compaction.get("history_budget_tokens") or 0)
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
        context_compaction.get("history_pressure_level")
        or context_compaction.get("pressure_level")
        or "normal"
    )
    billing_totals = dict(prompt_usage or {})
    cache_metrics = cache_metrics_from_context_meter(context_meter, billing_totals)
    compaction_readiness = {
        "pressure_level": context_meter.get("pressure_level", "normal"),
        "auto_replacement_allowed": bool(context_meter.get("auto_replacement_allowed", False)),
        "replacement_threshold_tokens": int(context_meter.get("replacement_threshold_tokens") or 0),
        "warning_threshold_tokens": int(context_meter.get("warning_threshold_tokens") or 0),
        "ready_threshold_tokens": int(context_meter.get("ready_threshold_tokens") or 0),
        "current_context_tokens": int(context_meter.get("current_context_tokens") or 0),
        "blocked_reason": "" if bool(context_meter.get("auto_replacement_allowed", False)) else "below_replacement_threshold",
        "context_recovery_package_present": bool(context_recovery_package.get("present", False)),
        "context_recovery_package_fresh": bool(context_recovery_package.get("fresh", False)),
        "context_recovery_package_source": str(context_recovery_package.get("source") or ""),
    }
    return {
        "system_tokens": system_tokens,
        "message_tokens": message_tokens,
        "total_tokens": system_tokens + message_tokens,
        "billing_totals": billing_totals,
        "context_meter": context_meter,
        "context_recovery_package": context_recovery_package,
        "cache_metrics": cache_metrics,
        "compaction_readiness": compaction_readiness,
        "cumulative_transcript_tokens": cumulative_transcript_tokens,
        "cumulative_transcript_message_count": len(cumulative_messages),
        "compression_saved_tokens": compression_saved_tokens,
        "compression_ratio": round(compression_ratio, 4),
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


def _context_recovery_package_status(
    runtime: Any,
    *,
    session_id: str,
    raw_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    session_memory = getattr(getattr(runtime, "memory_facade", None), "session_memory", None)
    manager_ref = getattr(session_memory, "manager", None)
    if callable(manager_ref):
        manager = manager_ref(session_id)
    elif manager_ref is not None and callable(getattr(manager_ref, "load_context_recovery_package", None)):
        manager = manager_ref
    else:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": "session_memory_unavailable",
        }
    try:
        package = manager.load_context_recovery_package()
    except Exception as exc:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": str(exc) or "context_recovery_package_unreadable",
        }
    if not package:
        return {
            "authority": "runtime.context_management.context_recovery_package_status",
            "present": False,
            "fresh": False,
            "reason": "context_recovery_package_missing",
        }
    try:
        validation = manager.validate_compaction_state(raw_messages)
    except Exception as exc:
        validation = {"ok": False, "reason": str(exc) or "compaction_state_validation_failed"}
    coverage = dict(package.get("coverage") or {})
    freshness = dict(package.get("freshness") or {})
    stale_reason = str(
        dict(validation or {}).get("reason") if not bool(dict(validation or {}).get("ok")) else ""
    )
    if not stale_reason:
        stale_reason = str(freshness.get("stale_reason") or coverage.get("stale_reason") or "")
    return {
        "authority": "runtime.context_management.context_recovery_package_status",
        "present": True,
        "fresh": bool(dict(validation or {}).get("ok")) and not stale_reason,
        "source": str(package.get("source") or ""),
        "schema_version": str(package.get("schema_version") or ""),
        "covered_message_count": int(coverage.get("covered_message_count") or 0),
        "covered_event_run_id": str(coverage.get("covered_event_run_id") or ""),
        "covered_event_offset_end": coverage.get("covered_event_offset_end"),
        "summary_hash": str(coverage.get("summary_hash") or ""),
        "source_summary_hash": str(coverage.get("source_summary_hash") or ""),
        "freshness_status": str(freshness.get("status") or ""),
        "stale_reason": stale_reason,
        "validation": dict(validation or {}),
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
    compact_payload = payload or CompactSessionRequest()
    return compact_session_history(
        runtime,
        session_id=session_id,
        mode="preview",
        pressure_level=compact_payload.pressure_level,
        reason=compact_payload.reason or "manual_compact",
        reserved_output_tokens=int(compact_payload.reserved_output_tokens or 0),
        pressure_source="context",
    )


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
    compact_payload = payload or CompactSessionRequest()
    return compact_session_history(
        runtime,
        session_id=session_id,
        mode="run",
        pressure_level=compact_payload.pressure_level,
        reason=compact_payload.reason or "manual_compact",
        reserved_output_tokens=int(compact_payload.reserved_output_tokens or 0),
        pressure_source="context",
    )


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

