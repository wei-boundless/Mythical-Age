from __future__ import annotations

from typing import Any, Literal

from memory_system.storage.models import Message
from runtime.prompt_accounting import ContextUsageMeter, TokenCounterRegistry


TOKEN_COUNTER = TokenCounterRegistry()
CompactionMode = Literal["preview", "run", "auto"]
PressureLevel = Literal["auto", "microcompact", "full_compact"]
PressureSource = Literal["context", "history"]


def count_tokens(text: str) -> int:
    return TOKEN_COUNTER.count_text(text, provider="local", model="session_compaction").tokens


def prompt_accounting_ledger(runtime: Any) -> Any:
    host = (
        getattr(runtime, "single_agent_runtime_host", None)
        or getattr(getattr(runtime, "harness_runtime", None), "single_agent_runtime_host", None)
    )
    ledger = getattr(host, "prompt_accounting_ledger", None)
    if ledger is not None:
        return ledger

    class _EmptyPromptAccountingLedger:
        def list_token_usage(self, **_kwargs: Any) -> list[Any]:
            return []

        def list_prompt_cache(self, **_kwargs: Any) -> list[Any]:
            return []

        def summarize_session(self, _session_id: str) -> dict[str, Any]:
            return {}

    return _EmptyPromptAccountingLedger()


def build_context_usage_snapshot(runtime: Any, *, session_id: str, raw_messages: list[dict[str, Any]]) -> Any:
    ledger = prompt_accounting_ledger(runtime)
    static = getattr(getattr(runtime, "settings_service", None), "static", None)
    provider = str(getattr(static, "llm_provider", "") or "")
    model = str(getattr(static, "llm_model", "") or "")
    reserved_output_tokens = int(getattr(static, "llm_max_output_tokens", 0) or 0)
    meter = ContextUsageMeter(
        ledger,
        default_reserved_output_tokens=reserved_output_tokens,
    )
    return meter.build_snapshot(
        session_id=session_id,
        provider=provider,
        model=model,
        reserved_output_tokens=reserved_output_tokens,
        fallback_messages=raw_messages,
    )


def compact_session_history(
    runtime: Any,
    *,
    session_id: str,
    mode: CompactionMode,
    pressure_level: PressureLevel = "auto",
    reason: str = "manual_compact",
    reserved_output_tokens: int = 0,
    pressure_source: PressureSource = "context",
    context_snapshot: Any | None = None,
) -> dict[str, Any]:
    record = runtime.session_manager.get_history(session_id)
    raw_messages = list(record.get("messages") or [])
    py_messages = runtime.memory_facade.adapter.to_messages(raw_messages, session_id=session_id)
    compactor = runtime.memory_facade.session_memory.compactor(session_id)
    tokens_before = compactor.conversation_tokens(py_messages)
    history_budget_tokens = int(getattr(compactor, "effective_history_token_budget", 0) or 0)
    history_pressure_level = str(compactor.pressure_level(tokens_before, len(py_messages)) or "normal")
    snapshot = context_snapshot or build_context_usage_snapshot(runtime, session_id=session_id, raw_messages=raw_messages)
    context_pressure_level = str(getattr(snapshot, "pressure_level", "normal") or "normal")
    requested_level = str(pressure_level or "auto")
    if requested_level == "auto":
        effective_level = history_pressure_level if pressure_source == "history" else context_pressure_level
    else:
        effective_level = requested_level

    if mode == "auto" and not bool(getattr(snapshot, "auto_replacement_allowed", False)):
        return _not_applied_response(
            session_id=session_id,
            mode=mode,
            requested_level=requested_level,
            effective_level=effective_level,
            context_snapshot=snapshot,
            raw_message_count=len(raw_messages),
            tokens_before=tokens_before,
            history_budget_tokens=history_budget_tokens,
            history_pressure_level=history_pressure_level,
            context_pressure_level=context_pressure_level,
            skipped_reason="below_replacement_threshold",
        )

    trigger = "auto" if mode == "auto" else "preview" if mode == "preview" else "manual"
    result = compactor.apply_strategy(
        py_messages,
        pressure_level=effective_level,  # type: ignore[arg-type]
        request_id=f"context_compaction:{trigger}:{mode}:{session_id}",
        session_id=session_id,
        trigger=trigger,  # type: ignore[arg-type]
        reason=reason or ("auto_context_replacement" if mode == "auto" else "manual_compact"),
        reserved_output_tokens=int(reserved_output_tokens or 0),
        force_full_compact=requested_level == "full_compact" or (mode == "auto" and effective_level == "full_compact"),
    )
    return _compaction_response(
        runtime,
        session_id=session_id,
        mode=mode,
        requested_level=requested_level,
        effective_level=effective_level,
        context_snapshot=snapshot,
        record=record,
        raw_message_count=len(raw_messages),
        history_budget_tokens=history_budget_tokens,
        result=result,
        history_pressure_level=history_pressure_level,
        context_pressure_level=context_pressure_level,
    )


def auto_compact_session_if_needed(
    runtime: Any,
    *,
    session_id: str,
    reason: str = "auto_context_replacement",
) -> dict[str, Any]:
    get_history = getattr(getattr(runtime, "session_manager", None), "get_history", None)
    if not callable(get_history):
        return _auto_skipped_response(
            session_id=session_id,
            skipped_reason="session_history_store_unavailable",
        )
    record = get_history(session_id)
    raw_messages = list(record.get("messages") or [])
    snapshot = build_context_usage_snapshot(runtime, session_id=session_id, raw_messages=raw_messages)
    if not bool(getattr(snapshot, "auto_replacement_allowed", False)):
        return _auto_skipped_response(
            session_id=session_id,
            skipped_reason="below_replacement_threshold",
            context_snapshot=snapshot,
            raw_message_count=len(raw_messages),
            compressed_context_present=bool(str(record.get("compressed_context") or "")),
        )
    return compact_session_history(
        runtime,
        session_id=session_id,
        mode="auto",
        pressure_level="auto",
        reason=reason,
        pressure_source="context",
        context_snapshot=snapshot,
    )


def _auto_skipped_response(
    *,
    session_id: str,
    skipped_reason: str,
    context_snapshot: Any | None = None,
    raw_message_count: int = 0,
    compressed_context_present: bool = False,
) -> dict[str, Any]:
    current_tokens = int(getattr(context_snapshot, "current_context_tokens", 0) or 0) if context_snapshot is not None else 0
    pressure_level = str(getattr(context_snapshot, "pressure_level", "normal") or "normal") if context_snapshot is not None else "normal"
    return {
        "authority": "runtime.context_management.session_compaction",
        "mode": "auto",
        "session_id": session_id,
        "applied": False,
        "requested_pressure_level": "auto",
        "pressure_level": pressure_level,
        "history_pressure_level": "",
        "effective_pressure_level": pressure_level,
        "context_meter": context_snapshot.to_dict() if context_snapshot is not None else {},
        "strategy": "none",
        "did_compact": False,
        "did_microcompact": False,
        "did_full_compact": False,
        "estimated_tokens_before": current_tokens,
        "estimated_tokens_after": current_tokens,
        "history_budget_tokens": 0,
        "original_message_count": raw_message_count,
        "compacted_message_count": raw_message_count,
        "replaced_message_count": 0,
        "preserved_recent_count": raw_message_count,
        "blocked": False,
        "blocked_reason": "",
        "skipped_reason": skipped_reason,
        "compact_boundary_receipt": {},
        "compression_budget_decision": {},
        "microcompact_cache_decision": {},
        "message_preview": [],
        "persisted_message_count": raw_message_count,
        "compressed_context_present": compressed_context_present,
    }


def cache_metrics_from_context_meter(context_meter: dict[str, Any], billing_totals: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = int(context_meter.get("provider_prompt_tokens") or 0)
    cached_tokens = int(context_meter.get("provider_cached_tokens") or 0)
    miss_tokens = max(0, prompt_tokens - cached_tokens)
    return {
        "latest_prompt_tokens": prompt_tokens,
        "latest_cached_tokens": cached_tokens,
        "latest_miss_tokens": miss_tokens,
        "latest_cache_hit_rate": float(context_meter.get("cache_hit_rate_latest") or 0.0),
        "cache_hit_rate_last_5": float(context_meter.get("cache_hit_rate_last_5") or 0.0),
        "cache_hit_rate_last_10": float(context_meter.get("cache_hit_rate_last_10") or 0.0),
        "cache_hit_rate_last_20": float(context_meter.get("cache_hit_rate_last_20") or 0.0),
        "total_cached_tokens": int(billing_totals.get("cached_tokens") or 0),
        "total_cache_savings_tokens": int(billing_totals.get("cache_savings_tokens") or 0),
        "provider_usage_record_count": int(billing_totals.get("provider_usage_record_count") or 0),
    }


def _compaction_response(
    runtime: Any,
    *,
    session_id: str,
    mode: CompactionMode,
    requested_level: str,
    effective_level: str,
    context_snapshot: Any,
    record: dict[str, Any],
    raw_message_count: int,
    history_budget_tokens: int,
    result: Any,
    history_pressure_level: str,
    context_pressure_level: str,
) -> dict[str, Any]:
    receipt = dict(dict(getattr(result, "diagnostics", {}) or {}).get("compact_boundary_receipt") or {})
    blocked = bool(receipt.get("blocked"))
    applied = False
    persisted: dict[str, Any] = {}
    if mode in {"run", "auto"} and not blocked and _result_rewrites_history(result):
        compressed_context = _compressed_context_after_compact(record, getattr(result, "summary_message", None))
        stored_messages = _stored_messages_after_compact(list(getattr(result, "messages", []) or []))
        replace = getattr(runtime.session_manager, "replace_runtime_context", None)
        if callable(replace):
            persisted = replace(
                session_id,
                messages=stored_messages,
                compressed_context=compressed_context,
            )
            applied = True
    return {
        "authority": "runtime.context_management.session_compaction",
        "mode": mode,
        "session_id": session_id,
        "applied": applied,
        "requested_pressure_level": requested_level,
        "pressure_level": str(context_pressure_level),
        "history_pressure_level": str(history_pressure_level),
        "effective_pressure_level": str(effective_level),
        "context_meter": context_snapshot.to_dict(),
        "strategy": str(getattr(result, "strategy", "none") or "none"),
        "did_compact": bool(getattr(result, "did_compact", False)),
        "did_microcompact": bool(getattr(result, "did_microcompact", False)),
        "did_full_compact": bool(getattr(result, "did_full_compact", False)),
        "estimated_tokens_before": int(getattr(result, "estimated_tokens_before", 0) or 0),
        "estimated_tokens_after": int(getattr(result, "estimated_tokens_after", 0) or 0),
        "history_budget_tokens": int(history_budget_tokens or 0),
        "original_message_count": int(getattr(result, "original_message_count", raw_message_count) or 0),
        "compacted_message_count": int(getattr(result, "compacted_message_count", raw_message_count) or 0),
        "replaced_message_count": int(getattr(result, "replaced_message_count", 0) or 0),
        "preserved_recent_count": int(getattr(result, "preserved_recent_count", 0) or 0),
        "blocked": blocked,
        "blocked_reason": str(receipt.get("block_reason") or ""),
        "skipped_reason": "",
        "compact_boundary_receipt": receipt,
        "compression_budget_decision": dict(dict(getattr(result, "diagnostics", {}) or {}).get("compression_budget_decision") or {}),
        "microcompact_cache_decision": dict(dict(getattr(result, "diagnostics", {}) or {}).get("microcompact_cache_decision") or {}),
        "message_preview": [_message_preview(message) for message in list(getattr(result, "messages", []) or [])[:8]],
        "persisted_message_count": len(list(persisted.get("messages") or [])) if persisted else raw_message_count,
        "compressed_context_present": bool(str((persisted or record).get("compressed_context") or "")),
    }


def _not_applied_response(
    *,
    session_id: str,
    mode: CompactionMode,
    requested_level: str,
    effective_level: str,
    context_snapshot: Any,
    raw_message_count: int,
    tokens_before: int,
    history_budget_tokens: int,
    history_pressure_level: str,
    context_pressure_level: str,
    skipped_reason: str,
) -> dict[str, Any]:
    return {
        "authority": "runtime.context_management.session_compaction",
        "mode": mode,
        "session_id": session_id,
        "applied": False,
        "requested_pressure_level": requested_level,
        "pressure_level": str(context_pressure_level),
        "history_pressure_level": str(history_pressure_level),
        "effective_pressure_level": str(effective_level),
        "context_meter": context_snapshot.to_dict(),
        "strategy": "none",
        "did_compact": False,
        "did_microcompact": False,
        "did_full_compact": False,
        "estimated_tokens_before": int(tokens_before or 0),
        "estimated_tokens_after": int(tokens_before or 0),
        "history_budget_tokens": int(history_budget_tokens or 0),
        "original_message_count": raw_message_count,
        "compacted_message_count": raw_message_count,
        "replaced_message_count": 0,
        "preserved_recent_count": raw_message_count,
        "blocked": False,
        "blocked_reason": "",
        "skipped_reason": skipped_reason,
        "compact_boundary_receipt": {},
        "compression_budget_decision": {},
        "microcompact_cache_decision": {},
        "message_preview": [],
        "persisted_message_count": raw_message_count,
        "compressed_context_present": False,
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
        "tokens": count_tokens(content),
    }
