from __future__ import annotations

from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from context_system.compaction.compactor import ContextCompactor
from runtime.prompt_accounting import ContextUsageMeter, ModelTokenUsageRecord, PromptAccountingLedger


def test_context_usage_meter_uses_latest_provider_usage_not_cumulative_billing(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:first:provider_usage",
            request_id="modelreq:first",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=100_000,
            completion_tokens=1000,
            total_tokens=101_000,
            created_at=1.0,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:latest:provider_usage",
            request_id="modelreq:latest",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=10,
            cached_tokens=80,
            cache_read_tokens=80,
            total_tokens=110,
            created_at=2.0,
        )
    )

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=64_000).build_snapshot(session_id="session:test")
    billing = ledger.summarize_session("session:test")

    assert billing["exact_total_tokens"] == 101_110
    assert snapshot.provider_anchor_request_id == "modelreq:latest"
    assert snapshot.current_context_tokens == 110
    assert snapshot.cache_hit_rate_latest == 0.8
    assert snapshot.provider_cached_tokens == 80


def test_context_usage_meter_adds_only_pending_messages_after_anchor(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:latest:provider_usage",
            request_id="modelreq:latest",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            created_at=2.0,
        )
    )

    snapshot = ContextUsageMeter(ledger).build_snapshot(
        session_id="session:test",
        pending_messages=[{"role": "user", "content": "新增的一条用户消息，需要计入 pending。"}],
    )

    assert snapshot.estimate_mode == "provider_anchor"
    assert snapshot.estimated_pending_tokens > 0
    assert snapshot.current_context_tokens == 110 + snapshot.estimated_pending_tokens


def test_context_usage_meter_invalidates_anchor_when_environment_fingerprint_changes(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:provider:provider_usage",
            request_id="modelreq:provider",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            created_at=2.0,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:local:local_prediction",
            request_id="modelreq:local",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=300,
            total_tokens=300,
            created_at=3.0,
        )
    )

    snapshot = ContextUsageMeter(ledger).build_snapshot(
        session_id="session:test",
        context_fingerprint="env:new",
        previous_context_fingerprint="env:old",
    )

    assert snapshot.anchor_valid is False
    assert snapshot.invalidation_reason == "environment_fingerprint_changed"
    assert snapshot.estimate_mode == "local_predicted_anchor_invalid"
    assert snapshot.current_context_tokens == 300


def test_deepseek_compactor_does_not_full_compact_from_message_count_alone(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=900_000,
    )
    messages = [Message(role="user", content=f"small message {index}") for index in range(20)]

    level = compactor.pressure_level(compactor.conversation_tokens(messages), len(messages))

    assert level == "normal"
    assert compactor.full_compact_tokens == 900_000
