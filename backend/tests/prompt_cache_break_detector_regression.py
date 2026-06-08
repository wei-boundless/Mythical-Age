from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.prompt_accounting import ModelTokenUsageRecord, PromptCacheBreakDetector, PromptCacheRecord


def test_cache_break_detector_reports_repeated_provider_payload_prefix_miss() -> None:
    current = _cache_record(
        request_id="modelreq:2",
        cache_key="key:provider-payload:a",
        prefix_hash="hash:provider-payload:a",
        created_at=2.0,
    )
    previous = _cache_record(
        request_id="modelreq:1",
        cache_key="key:provider-payload:a",
        prefix_hash="hash:provider-payload:a",
        created_at=1.0,
    )

    record = PromptCacheBreakDetector().detect(
        cache_record=current,
        provider_usage=_provider_usage("modelreq:2"),
        previous_cache_records=[previous],
        created_at=3.0,
    )

    assert record is not None
    assert record.reason == "provider_reported_miss_for_repeated_provider_payload_prefix"
    assert record.diagnostics["previous_request_ids"] == ["modelreq:1"]


def test_cache_break_detector_attributes_miss_to_tool_schema_hash_change() -> None:
    previous = _cache_record(
        request_id="modelreq:tool:1",
        cache_key="key:old-tool",
        prefix_hash="hash:old-tool",
        diagnostics={
            "stable_message_prefix_hash": "hash:messages",
            "tool_catalog_hash": "hash:tool:old",
            "cache_sensitive_params_hash": "hash:params",
            "provider_payload_prefix_hash": "hash:payload:old",
            "provider_payload_tool_prefix_segment_count": 1,
        },
        created_at=1.0,
    )
    current = _cache_record(
        request_id="modelreq:tool:2",
        cache_key="key:new-tool",
        prefix_hash="hash:new-tool",
        diagnostics={
            "stable_message_prefix_hash": "hash:messages",
            "tool_catalog_hash": "hash:tool:new",
            "cache_sensitive_params_hash": "hash:params",
            "provider_payload_prefix_hash": "hash:payload:new",
            "provider_payload_tool_prefix_segment_count": 1,
        },
        created_at=2.0,
    )

    record = PromptCacheBreakDetector().detect(
        cache_record=current,
        provider_usage=_provider_usage("modelreq:tool:2"),
        previous_cache_records=[previous],
        created_at=3.0,
    )

    assert record is not None
    assert record.reason == "tool_schema_hash_changed"
    assert record.diagnostics["provider_payload"]["tool_catalog_hash"] == {
        "previous": "hash:tool:old",
        "current": "hash:tool:new",
    }


def test_cache_break_detector_attributes_miss_to_cache_sensitive_params_change() -> None:
    previous = _cache_record(
        request_id="modelreq:params:1",
        cache_key="key:params:old",
        prefix_hash="hash:params:old",
        diagnostics={
            "stable_message_prefix_hash": "hash:messages",
            "tool_catalog_hash": "hash:tool",
            "cache_sensitive_params_hash": "hash:params:old",
            "provider_payload_prefix_hash": "hash:payload:old",
        },
        created_at=1.0,
    )
    current = _cache_record(
        request_id="modelreq:params:2",
        cache_key="key:params:new",
        prefix_hash="hash:params:new",
        diagnostics={
            "stable_message_prefix_hash": "hash:messages",
            "tool_catalog_hash": "hash:tool",
            "cache_sensitive_params_hash": "hash:params:new",
            "provider_payload_prefix_hash": "hash:payload:new",
        },
        created_at=2.0,
    )

    record = PromptCacheBreakDetector().detect(
        cache_record=current,
        provider_usage=_provider_usage("modelreq:params:2"),
        previous_cache_records=[previous],
        created_at=3.0,
    )

    assert record is not None
    assert record.reason == "cache_sensitive_params_changed"


def _cache_record(
    *,
    request_id: str,
    cache_key: str,
    prefix_hash: str,
    diagnostics: dict | None = None,
    created_at: float,
) -> PromptCacheRecord:
    return PromptCacheRecord(
        cache_record_id=f"pcache:{request_id}",
        request_id=request_id,
        provider="deepseek",
        model="deepseek-v4-pro",
        session_id="session:cache-break",
        cache_key=cache_key,
        prefix_hash=prefix_hash,
        status="miss",
        diagnostics={
            "stable_message_prefix_hash": "hash:messages",
            "tool_catalog_hash": "hash:tool",
            "cache_sensitive_params_hash": "hash:params",
            "provider_payload_prefix_hash": prefix_hash,
            **dict(diagnostics or {}),
        },
        created_at=created_at,
    )


def _provider_usage(request_id: str) -> ModelTokenUsageRecord:
    return ModelTokenUsageRecord(
        usage_id=f"tokuse:{request_id}:provider_usage",
        request_id=request_id,
        provider="deepseek",
        model="deepseek-v4-pro",
        session_id="session:cache-break",
        source="provider_usage",
        prompt_tokens=1000,
        cached_tokens=0,
        cache_read_tokens=0,
        total_tokens=1000,
    )
