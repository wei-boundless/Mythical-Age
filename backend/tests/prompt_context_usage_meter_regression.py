from __future__ import annotations

from memory_system.storage.models import Message
from memory_system.storage.session_memory import SessionMemoryManager
from context_system.compaction.compactor import ContextCompactor
from runtime.context_management.session_compaction import build_context_usage_snapshot
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
    assert snapshot.current_context_tokens == 100
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
    assert snapshot.current_context_tokens == 100 + snapshot.estimated_pending_tokens


def test_context_usage_meter_uses_session_pressure_as_current_context_authority(tmp_path) -> None:
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

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=65_536).build_snapshot(
        session_id="session:test",
        session_pressure_tokens=35_000,
        session_pressure_source="runtime.context_management.session_pressure",
    )

    assert snapshot.estimate_mode == "session_pressure"
    assert snapshot.authority == "runtime.context_management.session_pressure_snapshot"
    assert snapshot.current_context_tokens == 35_000
    assert snapshot.compaction_pressure_ratio == 0.041176
    assert snapshot.compaction_remaining_tokens == 815_000
    assert snapshot.provider_prompt_tokens == 100
    assert snapshot.diagnostics["pressure_authority"] == "runtime.context_management.session_pressure"
    assert snapshot.diagnostics["provider_observed_context_tokens"] == 100


def test_context_usage_meter_reports_compaction_remaining_against_replacement_threshold(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:latest:provider_usage",
            request_id="modelreq:latest",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=35_000,
            completion_tokens=600,
            total_tokens=35_600,
            created_at=2.0,
        )
    )

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=65_536).build_snapshot(session_id="session:test")

    assert snapshot.context_window_tokens == 1_000_000
    assert snapshot.input_capacity_tokens == 926_272
    assert snapshot.warning_threshold_tokens == 750_000
    assert snapshot.ready_threshold_tokens == 800_000
    assert snapshot.replacement_threshold_tokens == 850_000
    assert snapshot.current_context_ratio == 0.035
    assert snapshot.compaction_pressure_ratio == 0.041176
    assert snapshot.compaction_remaining_tokens == 815_000
    assert snapshot.compaction_remaining_ratio == 0.958824


def test_context_usage_meter_uses_newer_local_prediction_until_provider_usage_arrives(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:provider:provider_usage",
            request_id="modelreq:provider",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=35_000,
            completion_tokens=500,
            cached_tokens=20_000,
            total_tokens=35_500,
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
            prompt_tokens=88_000,
            total_tokens=88_000,
            created_at=3.0,
        )
    )

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=65_536).build_snapshot(session_id="session:test")

    assert snapshot.estimate_mode == "local_predicted_newer_than_provider"
    assert snapshot.anchor_valid is False
    assert snapshot.current_context_tokens == 88_000
    assert snapshot.compaction_remaining_tokens == 762_000
    assert snapshot.cache_hit_rate_latest == round(20_000 / 35_000, 4)
    assert snapshot.diagnostics["effective_anchor_source"] == "local_prediction"
    assert snapshot.diagnostics["effective_anchor_request_id"] == "modelreq:local"
    assert snapshot.diagnostics["local_prediction_newer_than_provider"] is True


def test_context_usage_meter_prefers_agent_runtime_records_over_utility_calls(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:rtpacket:provider:provider_usage",
            request_id="modelreq:rtpacket:turn:session:test:1:single_agent_turn:1:1",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=40_000,
            total_tokens=40_000,
            created_at=2.0,
            diagnostics={
                "cache_metric_scope": "agent_runtime",
                "packet_ref": "rtpacket:turn:session:test:1",
            },
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:rtpacket:local:local_prediction",
            request_id="modelreq:rtpacket:turn:session:test:2:single_agent_turn:1:1",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=92_000,
            total_tokens=92_000,
            created_at=3.0,
            diagnostics={
                "cache_metric_scope": "agent_runtime",
                "packet_ref": "rtpacket:turn:session:test:2",
            },
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:utility:provider_usage",
            request_id="modelreq:utility",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=1_000,
            total_tokens=1_000,
            created_at=4.0,
        )
    )

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=65_536).build_snapshot(session_id="session:test")

    assert snapshot.estimate_mode == "local_predicted_newer_than_provider"
    assert snapshot.current_context_tokens == 92_000
    assert snapshot.diagnostics["candidate_scope"] == "agent_runtime"
    assert snapshot.diagnostics["record_count"] == 2
    assert snapshot.diagnostics["raw_record_count"] == 3
    assert snapshot.diagnostics["effective_anchor_request_id"] == "modelreq:rtpacket:turn:session:test:2:single_agent_turn:1:1"


def test_context_usage_meter_ignores_protocol_repair_model_response_records(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:main:provider_usage",
            request_id="modelreq:rtpacket:turn:session:test:1:single_agent_turn:1:1",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=31_000,
            completion_tokens=400,
            total_tokens=31_400,
            created_at=2.0,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:model-response:repair:provider_usage",
            request_id="model-response:rtpacket:turn:session:test:1:single_agent_turn:1:tool:1:repair",
            session_id="session:test",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=24_000,
            completion_tokens=100,
            total_tokens=24_100,
            created_at=3.0,
        )
    )

    snapshot = ContextUsageMeter(ledger, default_reserved_output_tokens=65_536).build_snapshot(session_id="session:test")

    assert snapshot.provider_anchor_request_id == "modelreq:rtpacket:turn:session:test:1:single_agent_turn:1:1"
    assert snapshot.current_context_tokens == 31_000
    assert snapshot.diagnostics["record_count"] == 1
    assert snapshot.diagnostics["raw_record_count"] == 2


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


def test_session_context_usage_snapshot_passes_active_history_fingerprint(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    previous_fingerprint = "sha256:previous-active-history"
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
            prompt_tokens=100,
            total_tokens=100,
            created_at=1.0,
            diagnostics={
                "prompt_manifest": {
                    "context_window": {
                        "active_history_fingerprint": previous_fingerprint,
                    }
                }
            },
        )
    )
    runtime = type(
        "Runtime",
        (),
        {
            "settings": type(
                "Settings",
                (),
                {
                    "static": type(
                        "Static",
                        (),
                        {
                            "llm_provider": "deepseek",
                            "llm_model": "deepseek-v4-pro",
                            "llm_max_output_tokens": 65_536,
                        },
                    )()
                },
            )(),
            "single_agent_runtime_host": type("Host", (), {"prompt_accounting_ledger": ledger})(),
        },
    )()

    snapshot = build_context_usage_snapshot(
        runtime,
        session_id="session:test",
        raw_messages=[
            {"role": "user", "content": "旧消息"},
            {"role": "assistant", "content": "新回复让历史发生变化"},
        ],
    )

    assert snapshot.anchor_valid is False
    assert snapshot.invalidation_reason == "environment_fingerprint_changed"
    assert snapshot.diagnostics["previous_context_fingerprint"] == previous_fingerprint
    assert snapshot.diagnostics["context_fingerprint"].startswith("sha256:")


def test_deepseek_compactor_does_not_full_compact_from_message_count_alone(tmp_path) -> None:
    manager = SessionMemoryManager(tmp_path)
    compactor = ContextCompactor(
        manager,
        max_messages=4,
        keep_recent_messages=2,
        effective_history_token_budget=850_000,
    )
    messages = [Message(role="user", content=f"small message {index}") for index in range(20)]

    level = compactor.pressure_level(compactor.conversation_tokens(messages), len(messages))

    assert level == "normal"
    assert compactor.warning_tokens == 750_000
    assert compactor.microcompact_tokens == 800_000
    assert compactor.full_compact_tokens == 850_000
