from __future__ import annotations

from pathlib import Path

from runtime.prompt_accounting import ContextUsageMeter, ModelTokenUsageRecord, PromptAccountingLedger


class _Ledger:
    def __init__(self, records: list[ModelTokenUsageRecord]) -> None:
        self._records = records

    def list_token_usage(self, **_kwargs):
        return list(self._records)


def _runtime_record(*, prompt_tokens: int) -> ModelTokenUsageRecord:
    return ModelTokenUsageRecord(
        usage_id="tokuse:modelreq:pressure:local_prediction",
        request_id="modelreq:pressure",
        session_id="session:pressure",
        provider="deepseek",
        model="deepseek-v4-pro",
        source="local_prediction",
        prompt_tokens=prompt_tokens,
        total_tokens=prompt_tokens,
        created_at=1.0,
        diagnostics={"cache_metric_scope": "agent_runtime", "packet_ref": "rtpacket:pressure"},
    )


def test_compaction_pressure_uses_session_pressure_when_model_accounting_is_lower() -> None:
    meter = ContextUsageMeter(_Ledger([_runtime_record(prompt_tokens=20_000)]))

    snapshot = meter.build_snapshot(
        session_id="session:pressure",
        provider="deepseek",
        model="deepseek-v4-pro",
        reserved_output_tokens=65_536,
        session_pressure_tokens=120_000,
        session_pressure_source="runtime.context_management.session_pressure",
    )

    assert snapshot.current_context_tokens == 20_000
    assert snapshot.compaction_pressure_tokens == 120_000
    assert snapshot.diagnostics["session_pressure_used_as_current_context"] is False
    assert snapshot.diagnostics["current_context_authority"] == "runtime.prompt_accounting.model_request_accounting"
    assert snapshot.diagnostics["compaction_pressure_authority"] == "runtime.context_management.session_pressure"


def test_compaction_pressure_keeps_model_accounting_when_it_is_higher() -> None:
    meter = ContextUsageMeter(_Ledger([_runtime_record(prompt_tokens=120_000)]))

    snapshot = meter.build_snapshot(
        session_id="session:pressure",
        provider="deepseek",
        model="deepseek-v4-pro",
        reserved_output_tokens=65_536,
        session_pressure_tokens=20_000,
        session_pressure_source="runtime.context_management.session_pressure",
    )

    assert snapshot.current_context_tokens == 120_000
    assert snapshot.compaction_pressure_tokens == 120_000
    assert snapshot.diagnostics["compaction_pressure_authority"] == "runtime.prompt_accounting.model_request_accounting"


def test_prompt_accounting_ledger_can_read_recent_token_usage_without_full_scan(tmp_path: Path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(_runtime_record(prompt_tokens=30_000))
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:other:local_prediction",
            request_id="modelreq:other",
            session_id="session:other",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="local_prediction",
            prompt_tokens=999_000,
            total_tokens=999_000,
            created_at=2.0,
            diagnostics={"cache_metric_scope": "agent_runtime", "packet_ref": "rtpacket:other"},
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:pressure:newer",
            request_id="modelreq:pressure:newer",
            session_id="session:pressure",
            provider="deepseek",
            model="deepseek-v4-pro",
            source="provider_usage",
            prompt_tokens=44_000,
            total_tokens=45_000,
            created_at=3.0,
            diagnostics={"cache_metric_scope": "agent_runtime", "packet_ref": "rtpacket:pressure:newer"},
        )
    )

    records = ledger.list_recent_token_usage(session_id="session:pressure", limit=1)

    assert [record.prompt_tokens for record in records] == [44_000]
