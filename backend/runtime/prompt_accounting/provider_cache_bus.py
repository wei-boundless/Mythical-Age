from __future__ import annotations

from dataclasses import replace
from typing import Any

from .ledger import PROVIDER_CACHE_BUS_FILE
from .models import ModelTokenUsageRecord, PromptCacheRecord
from .provider_cache_ledger import ProviderCacheLedgerRecord, build_provider_cache_ledger_record


PROVIDER_CACHE_BUS_AUTHORITY = "runtime.prompt_accounting.provider_cache_bus"
PROVIDER_CACHE_LOG_SOURCE = f"prompt_accounting.{PROVIDER_CACHE_BUS_FILE}"


def publish_provider_cache_usage(
    *,
    ledger: Any,
    cache_record: PromptCacheRecord,
    provider_usage: ModelTokenUsageRecord,
    previous_cache_records: list[PromptCacheRecord] | tuple[PromptCacheRecord, ...] = (),
    created_at: float | None = None,
) -> ProviderCacheLedgerRecord:
    record = build_provider_cache_ledger_record(
        cache_record=cache_record,
        provider_usage=provider_usage,
        previous_cache_records=previous_cache_records,
        created_at=created_at,
    )
    record = replace(record, authority=PROVIDER_CACHE_BUS_AUTHORITY, ledger_version="provider_cache_bus.v1")
    writer = getattr(ledger, "record_provider_cache_bus", None)
    if callable(writer):
        writer(record)
    return record


def build_provider_cache_log_view(
    ledger: Any,
    *,
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    limit: int = 50,
    authority: str = PROVIDER_CACHE_BUS_AUTHORITY,
) -> dict[str, Any]:
    records = list_provider_cache_log_records(
        ledger,
        run_id=run_id,
        task_run_id=task_run_id,
        session_id=session_id,
        limit=limit,
    )
    rows = [provider_cache_log_row(record) for record in records]
    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in rows)
    cached_tokens = sum(int(row.get("cached_tokens") or 0) for row in rows)
    miss_tokens = sum(int(row.get("miss_tokens") or 0) for row in rows)
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("cache_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    latest = rows[0] if rows else {}
    latest_health = dict(latest.get("provider_prefix_cache_health") or {}) if latest else {}
    latest_status = str(latest.get("cache_status") or "")
    latest_under_read_tokens = _row_under_read_tokens(latest)
    history_under_read_tokens = sum(_row_under_read_tokens(row) for row in rows[1:])
    cold_start_under_read_tokens = sum(
        _row_under_read_tokens(row)
        for row in rows
        if str(row.get("cache_status") or "") == "cold_start"
    )
    warm_provider_under_read_tokens = sum(
        _row_under_read_tokens(row)
        for row in rows
        if str(row.get("cache_status") or "") != "cold_start"
    )
    current_prefix_covered = bool(
        latest
        and latest_under_read_tokens <= 0
        and (
            latest_status == "hit"
            or str(latest_health.get("verdict") or "") == "covered"
        )
    )
    return {
        "authority": authority,
        "source": PROVIDER_CACHE_LOG_SOURCE,
        "run_id": str(run_id or ""),
        "task_run_id": str(task_run_id or ""),
        "session_id": str(session_id or ""),
        "summary": {
            "record_count": len(rows),
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "miss_tokens": miss_tokens,
            "hit_rate": round(cached_tokens / max(1, prompt_tokens), 4) if rows else 0.0,
            "latest_status": latest_status,
            "latest_prefix_health": latest_health,
            "latest_under_read_tokens": latest_under_read_tokens,
            "warm_provider_under_read_tokens": warm_provider_under_read_tokens,
            "cold_start_under_read_tokens": cold_start_under_read_tokens,
            "history_under_read_tokens": history_under_read_tokens,
            "current_prefix_covered": current_prefix_covered,
            "current_cache_spine_hash": str(latest.get("physical_cache_spine_hash") or ""),
            "current_transport_contract_hash": str(latest.get("transport_contract_hash") or ""),
            "provider_under_read_count": int(status_counts.get("provider_under_read", 0)),
            "local_physical_break_count": int(status_counts.get("local_physical_break", 0)),
            "cold_start_count": int(status_counts.get("cold_start", 0)),
            "hit_count": int(status_counts.get("hit", 0)),
            "status_counts": status_counts,
        },
        "records": rows,
        "updated_at": max((float(row.get("created_at") or 0.0) for row in rows), default=0.0),
    }


def list_provider_cache_log_records(
    ledger: Any,
    *,
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> list[ProviderCacheLedgerRecord]:
    target = max(1, min(int(limit or 50), 200))
    list_records = getattr(ledger, "list_provider_cache_bus", None)
    if callable(list_records):
        try:
            records = list(
                list_records(
                    run_id=str(run_id or ""),
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                )
            )
        except Exception:
            records = []
        if records:
            return sorted(records, key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0), reverse=True)[:target]
    list_recent = getattr(ledger, "list_recent_provider_cache_bus", None)
    if callable(list_recent):
        try:
            return list(
                list_recent(
                    run_id=str(run_id or ""),
                    task_run_id=str(task_run_id or ""),
                    session_id=str(session_id or ""),
                    limit=target,
                )
            )
        except Exception:
            return []
    return []


def provider_cache_log_row(record: ProviderCacheLedgerRecord) -> dict[str, Any]:
    diagnostics = dict(getattr(record, "diagnostics", {}) or {})
    provider_prefix_cache_health = dict(diagnostics.get("provider_prefix_cache_health") or {})
    return {
        "ledger_id": str(getattr(record, "ledger_id", "") or ""),
        "request_id": str(getattr(record, "request_id", "") or ""),
        "run_id": str(getattr(record, "run_id", "") or ""),
        "task_run_id": str(getattr(record, "task_run_id", "") or ""),
        "session_id": str(getattr(record, "session_id", "") or ""),
        "provider": str(getattr(record, "provider", "") or ""),
        "model": str(getattr(record, "model", "") or ""),
        "provider_lane": str(getattr(record, "provider_lane", "") or ""),
        "cache_status": str(getattr(record, "cache_status", "") or ""),
        "break_status": str(getattr(record, "break_status", "") or ""),
        "prompt_tokens": int(getattr(record, "prompt_tokens", 0) or 0),
        "cached_tokens": int(getattr(record, "cached_tokens", 0) or 0),
        "miss_tokens": int(getattr(record, "miss_tokens", 0) or 0),
        "hit_rate": float(getattr(record, "hit_rate", 0.0) or 0.0),
        "expected_cacheable_tokens": int(getattr(record, "expected_cacheable_tokens", 0) or 0),
        "physical_cache_spine_hash": str(getattr(record, "physical_cache_spine_hash", "") or ""),
        "transport_contract_hash": str(diagnostics.get("transport_contract_hash") or ""),
        "physical_cache_spine_provider_scaled_tokens": int(
            getattr(record, "physical_cache_spine_provider_scaled_tokens", 0)
            or 0
        ),
        "physical_cache_spine_segment_kinds": list(getattr(record, "physical_cache_spine_segment_kinds", ()) or ()),
        "provider_under_read_tokens": int(getattr(record, "provider_under_read_tokens", 0) or 0),
        "current_context_append_tokens": int(getattr(record, "current_context_append_tokens", 0) or 0),
        "dynamic_tail_tokens": int(getattr(record, "dynamic_tail_tokens", 0) or 0),
        "tool_schema_blocker_tokens": int(getattr(record, "tool_schema_blocker_tokens", 0) or 0),
        "non_spine_prompt_tokens": int(getattr(record, "non_spine_prompt_tokens", 0) or 0),
        "first_break_segment": dict(getattr(record, "first_break_segment", {}) or {}),
        "provider_prefix_cache_health": provider_prefix_cache_health,
        "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
    }


def _row_under_read_tokens(row: dict[str, Any]) -> int:
    if not row:
        return 0
    health = dict(row.get("provider_prefix_cache_health") or {})
    try:
        return max(
            0,
            int(
                row.get("provider_under_read_tokens")
                or health.get("under_read_tokens")
                or 0
            ),
        )
    except (TypeError, ValueError):
        return 0
