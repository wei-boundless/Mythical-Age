from __future__ import annotations

import hashlib
import json
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


def build_context_usage_snapshot(
    runtime: Any,
    *,
    session_id: str,
    raw_messages: list[dict[str, Any]],
    session_record: dict[str, Any] | None = None,
) -> Any:
    ledger = prompt_accounting_ledger(runtime)
    static = _runtime_static_settings(runtime)
    provider = str(getattr(static, "llm_provider", "") or "")
    model = str(getattr(static, "llm_model", "") or "")
    reserved_output_tokens = int(getattr(static, "llm_max_output_tokens", 0) or 0)
    meter = ContextUsageMeter(
        ledger,
        default_reserved_output_tokens=reserved_output_tokens,
    )
    context_fingerprint = _messages_context_fingerprint(raw_messages)
    previous_context_fingerprint = _latest_record_context_fingerprint(ledger, session_id=session_id)
    pressure = _build_session_pressure(
        runtime,
        session_id=session_id,
        raw_messages=raw_messages,
        session_record=session_record,
        provider=provider,
        model=model,
    )
    return meter.build_snapshot(
        session_id=session_id,
        provider=provider,
        model=model,
        reserved_output_tokens=reserved_output_tokens,
        fallback_messages=raw_messages,
        session_pressure_tokens=int(pressure.get("tokens") or 0),
        session_pressure_source="runtime.context_management.session_pressure",
        session_pressure_diagnostics={
            "session_pressure": {
                key: value
                for key, value in pressure.items()
                if key != "tokens"
            }
        },
        context_fingerprint=context_fingerprint,
        previous_context_fingerprint=previous_context_fingerprint,
    )


def _runtime_static_settings(runtime: Any) -> Any:
    for candidate in (
        getattr(runtime, "settings_service", None),
        getattr(runtime, "settings", None),
        getattr(getattr(runtime, "harness_runtime", None), "settings_service", None),
        getattr(getattr(runtime, "model_runtime", None), "settings_service", None),
    ):
        static = getattr(candidate, "static", None)
        if static is not None:
            return static
    return None


def _messages_context_fingerprint(messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    normalized = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("type") or "").strip()
        content = str(item.get("content") or item.get("text") or "")
        if not role or not content:
            continue
        payload: dict[str, Any] = {"role": role, "content": content}
        if item.get("tool_call_id"):
            payload["tool_call_id"] = str(item.get("tool_call_id") or "")
        if isinstance(item.get("tool_calls"), list) and item.get("tool_calls"):
            payload["tool_calls"] = [dict(call) for call in list(item.get("tool_calls") or []) if isinstance(call, dict)]
        normalized.append(payload)
    return _stable_hash(normalized)


def _latest_record_context_fingerprint(ledger: Any, *, session_id: str) -> str:
    list_token_usage = getattr(ledger, "list_token_usage", None)
    if not callable(list_token_usage):
        return ""
    records = sorted(
        list(list_token_usage(session_id=session_id) or []),
        key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0),
    )
    for record in reversed(records):
        fingerprint = _record_context_fingerprint(record)
        if fingerprint:
            return fingerprint
    return ""


def _record_context_fingerprint(record: Any) -> str:
    diagnostics = dict(getattr(record, "diagnostics", {}) or {})
    direct = str(diagnostics.get("context_fingerprint") or "").strip()
    if direct:
        return direct
    prompt_manifest = dict(diagnostics.get("prompt_manifest") or {})
    context_window = dict(prompt_manifest.get("context_window") or {})
    return str(context_window.get("active_history_fingerprint") or context_window.get("context_fingerprint") or "").strip()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _build_session_pressure(
    runtime: Any,
    *,
    session_id: str,
    raw_messages: list[dict[str, Any]],
    session_record: dict[str, Any] | None,
    provider: str,
    model: str,
) -> dict[str, Any]:
    record = dict(session_record or _load_session_record(runtime, session_id=session_id) or {})
    compressed_context = str(record.get("compressed_context") or "").strip()
    boundary_created_at = _safe_float(record.get("provider_protocol_compaction_created_at"))
    api_transcript = _load_api_transcript(runtime, session_id=session_id)
    public_messages = _public_pressure_messages(raw_messages)
    protocol_messages, protocol_stats = _protocol_pressure_messages(
        api_transcript,
        boundary_created_at=boundary_created_at,
        compressed_context_present=bool(compressed_context),
    )
    compressed_tokens = TOKEN_COUNTER.count_text(compressed_context, provider=provider, model=model).tokens if compressed_context else 0
    public_tokens = TOKEN_COUNTER.count_messages(public_messages, provider=provider, model=model).tokens if public_messages else 0
    protocol_tokens = TOKEN_COUNTER.count_messages(protocol_messages, provider=provider, model=model).tokens if protocol_messages else 0
    return {
        "tokens": max(0, int(compressed_tokens + public_tokens + protocol_tokens)),
        "compressed_context_tokens": int(compressed_tokens),
        "public_history_tokens": int(public_tokens),
        "provider_protocol_tokens": int(protocol_tokens),
        "public_message_count": len(public_messages),
        "api_transcript_message_count": len(api_transcript),
        "provider_protocol_message_count": len(protocol_messages),
        "provider_protocol_compaction_created_at": boundary_created_at,
        "compressed_context_present": bool(compressed_context),
        **protocol_stats,
        "authority": "runtime.context_management.session_pressure",
    }


def _load_session_record(runtime: Any, *, session_id: str) -> dict[str, Any]:
    get_history = getattr(getattr(runtime, "session_manager", None), "get_history", None)
    if not callable(get_history):
        return {}
    try:
        record = get_history(session_id)
    except Exception:
        return {}
    return dict(record or {}) if isinstance(record, dict) else {}


def _load_api_transcript(runtime: Any, *, session_id: str) -> list[dict[str, Any]]:
    load_session_for_api = getattr(getattr(runtime, "session_manager", None), "load_session_for_api", None)
    if not callable(load_session_for_api):
        return []
    try:
        transcript = load_session_for_api(session_id)
    except Exception:
        return []
    return [dict(item) for item in list(transcript or []) if isinstance(item, dict)]


def _public_pressure_messages(messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("type") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or item.get("text") or "")
        if not content.strip():
            continue
        result.append({"role": role, "content": content})
    return result


def _protocol_pressure_messages(
    transcript: list[dict[str, Any]],
    *,
    boundary_created_at: float,
    compressed_context_present: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if compressed_context_present and boundary_created_at <= 0:
        return [], {
            "provider_protocol_omitted_before_boundary_count": len(transcript),
            "provider_protocol_omitted_unbounded_compaction": True,
            "provider_protocol_bounded_chars": 0,
            "provider_protocol_omitted_chars": 0,
        }
    messages: list[dict[str, Any]] = []
    omitted_before_boundary = 0
    omitted_chars = 0
    bounded_chars = 0
    for item in list(transcript or []):
        if boundary_created_at > 0 and _message_created_at(item) < boundary_created_at:
            omitted_before_boundary += 1
            continue
        projected, stats = _protocol_pressure_message(item)
        omitted_chars += int(stats.get("omitted_chars") or 0)
        bounded_chars += int(stats.get("bounded_chars") or 0)
        if projected:
            messages.append(projected)
    return messages, {
        "provider_protocol_omitted_before_boundary_count": omitted_before_boundary,
        "provider_protocol_omitted_unbounded_compaction": False,
        "provider_protocol_bounded_chars": bounded_chars,
        "provider_protocol_omitted_chars": omitted_chars,
    }


def _protocol_pressure_message(message: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    role = str(message.get("role") or message.get("type") or "").strip()
    if role == "tool":
        content, omitted = _bounded_protocol_text(message.get("content"), limit=3_000)
        if not content and not str(message.get("tool_call_id") or "").strip():
            return {}, {"bounded_chars": 0, "omitted_chars": omitted}
        payload: dict[str, Any] = {"role": "tool", "content": content}
        tool_call_id = str(message.get("tool_call_id") or "").strip()
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        name = str(message.get("name") or "").strip()
        if name:
            payload["name"] = name
        return payload, {"bounded_chars": len(content), "omitted_chars": omitted}
    if role != "assistant":
        return {}, {"bounded_chars": 0, "omitted_chars": 0}

    reasoning = str(message.get("reasoning_content") or "").strip()
    tool_calls = message.get("tool_calls")
    has_tool_calls = isinstance(tool_calls, list) and bool(tool_calls)
    if not reasoning and not has_tool_calls:
        return {}, {"bounded_chars": 0, "omitted_chars": 0}

    payload = {"role": "assistant"}
    bounded_chars = 0
    omitted_chars = 0
    if has_tool_calls:
        content, content_omitted = _bounded_protocol_text(message.get("content"), limit=4_000)
        if content:
            payload["content"] = content
            bounded_chars += len(content)
            omitted_chars += content_omitted
    if reasoning:
        payload["reasoning_content"] = reasoning
        bounded_chars += len(reasoning)
    if has_tool_calls:
        payload["tool_calls"] = _json_stable(tool_calls)
        bounded_chars += len(json.dumps(payload["tool_calls"], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if len(payload) <= 1:
        return {}, {"bounded_chars": 0, "omitted_chars": omitted_chars}
    return payload, {"bounded_chars": bounded_chars, "omitted_chars": omitted_chars}


def _bounded_protocol_text(value: Any, *, limit: int) -> tuple[str, int]:
    text = str(value or "")
    if not text:
        return "", 0
    limit = max(120, int(limit or 120))
    if len(text) <= limit:
        return text, 0
    return text[:limit].rstrip() + "\n[provider protocol content omitted from pressure estimate]", len(text) - limit


def _message_created_at(message: dict[str, Any]) -> float:
    return _safe_float(message.get("created_at") or message.get("updated_at") or message.get("timestamp"))


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _history_recovery_summary_source(raw_messages: list[dict[str, Any]]) -> str:
    public_messages = _public_pressure_messages(raw_messages)
    if not public_messages:
        return ""
    older_messages = public_messages[:-6] if len(public_messages) > 6 else public_messages
    if not older_messages:
        return ""
    lines = [
        "# Warm Context",
        f"- Automatic context replacement is summarizing {len(older_messages)} earlier public session messages.",
    ]
    for index, message in enumerate(older_messages[:12], start=1):
        role = str(message.get("role") or "").strip() or "message"
        content = _compact_history_recovery_text(message.get("content"), limit=360 if index <= 4 else 220)
        if content:
            lines.append(f"- {role}: {content}")
    if len(older_messages) > 12:
        lines.append(f"- {len(older_messages) - 12} additional earlier messages were omitted from this compact checkpoint source.")
    recent_messages = public_messages[-6:] if len(public_messages) > 6 else []
    if recent_messages:
        lines.extend(["", "# Next Step"])
        latest_user = next((item for item in reversed(recent_messages) if item.get("role") == "user"), None)
        if latest_user is not None:
            latest = _compact_history_recovery_text(latest_user.get("content"), limit=220)
            if latest:
                lines.append(f"- Continue from the latest user request: {latest}")
    return "\n".join(lines).strip()


def _compact_history_recovery_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").replace("\r\n", "\n").replace("\r", "\n").split())
    if not text:
        return ""
    bounded = max(80, int(limit or 80))
    if len(text) <= bounded:
        return text
    return text[:bounded].rstrip() + "..."


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
    snapshot = context_snapshot or build_context_usage_snapshot(
        runtime,
        session_id=session_id,
        raw_messages=raw_messages,
        session_record=record,
    )
    context_pressure_level = str(getattr(snapshot, "pressure_level", "normal") or "normal")
    requested_level = str(pressure_level or "auto")
    if requested_level == "auto":
        effective_level = history_pressure_level if pressure_source == "history" else context_pressure_level
    else:
        effective_level = requested_level

    context_replacement_allowed = bool(getattr(snapshot, "auto_replacement_allowed", False))
    if mode == "auto" and not context_replacement_allowed:
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
    summary_source_content = (
        _history_recovery_summary_source(raw_messages)
        if effective_level == "full_compact"
        else None
    )
    result = compactor.apply_strategy(
        py_messages,
        pressure_level=effective_level,  # type: ignore[arg-type]
        summary_source_content=summary_source_content,
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
    if not raw_messages:
        return _auto_skipped_response(
            session_id=session_id,
            skipped_reason="empty_history",
            raw_message_count=0,
            compressed_context_present=bool(str(record.get("compressed_context") or "")),
        )
    if not _runtime_history_compactor_available(runtime):
        return _auto_skipped_response(
            session_id=session_id,
            skipped_reason="history_compactor_unavailable",
            raw_message_count=len(raw_messages),
            compressed_context_present=bool(str(record.get("compressed_context") or "")),
        )
    snapshot = build_context_usage_snapshot(
        runtime,
        session_id=session_id,
        raw_messages=raw_messages,
        session_record=record,
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


def _runtime_history_compactor_available(runtime: Any) -> bool:
    facade = getattr(runtime, "memory_facade", None)
    adapter = getattr(facade, "adapter", None)
    session_memory = getattr(facade, "session_memory", None)
    return callable(getattr(adapter, "to_messages", None)) and callable(getattr(session_memory, "compactor", None))


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
        summary_message = getattr(result, "summary_message", None)
        stored_messages = _stored_messages_after_compact(list(getattr(result, "messages", []) or []))
        replace = getattr(runtime.session_manager, "replace_runtime_context", None)
        if callable(replace):
            kwargs: dict[str, Any] = {"messages": stored_messages}
            if summary_message is not None:
                kwargs["compressed_context"] = _compressed_context_after_compact(record, summary_message)
            persisted = replace(session_id, **kwargs)
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
        if message.role not in {"user", "assistant"}:
            continue
        content = str(message.content or "")
        if not content:
            continue
        stored.append(_message_to_session_dict(message, content=content))
    return stored


def _message_to_session_dict(message: Message, *, content: str) -> dict[str, Any]:
    payload = {
        "role": message.role,
        "content": content,
    }
    meta = dict(message.meta or {})
    message_id = str(meta.get("message_id") or meta.get("id") or "").strip()
    if message_id:
        payload["message_id"] = message_id
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
