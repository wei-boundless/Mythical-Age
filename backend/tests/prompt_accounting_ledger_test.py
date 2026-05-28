from __future__ import annotations

from types import SimpleNamespace

from runtime.prompt_accounting import (
    CanonicalPromptSerializer,
    ModelTokenUsageRecord,
    PromptAccountingLedger,
    PromptCachePlanner,
    extract_provider_usage,
)


def test_prompt_accounting_ledger_records_prediction_provider_usage_and_cache(tmp_path) -> None:
    ledger = PromptAccountingLedger(tmp_path)
    segment_map = CanonicalPromptSerializer().build_segment_map(
        request_id="modelreq:test",
        session_id="session:test",
        task_run_id="taskrun:test",
        provider="openai",
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "你是一名可靠的执行代理。"},
            {"role": "user", "content": "hello"},
        ],
    )
    cache_record = PromptCachePlanner().plan(segment_map)
    provider_usage = ModelTokenUsageRecord(
        usage_id="tokuse:modelreq:test:provider_usage",
        request_id="modelreq:test",
        session_id="session:test",
        task_run_id="taskrun:test",
        provider="openai",
        model="gpt-4.1-mini",
        source="provider_usage",
        prompt_tokens=10,
        completion_tokens=5,
        cached_tokens=4,
        cache_read_tokens=4,
        total_tokens=15,
        created_at=2.0,
    )

    ledger.record_segment_map(segment_map)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:test:local_prediction",
            request_id="modelreq:test",
            session_id="session:test",
            task_run_id="taskrun:test",
            provider="openai",
            model="gpt-4.1-mini",
            source="local_prediction",
            prompt_tokens=segment_map.predicted_prompt_tokens,
            total_tokens=segment_map.predicted_prompt_tokens,
            created_at=1.0,
        )
    )
    ledger.record_token_usage(provider_usage)
    ledger.record_prompt_cache(PromptCachePlanner().with_provider_usage(cache_record, provider_usage))

    summary = ledger.summarize_task("taskrun:test")
    segment_maps = ledger.list_segment_maps(task_run_id="taskrun:test")
    cache_records = ledger.list_prompt_cache(task_run_id="taskrun:test")

    assert len(segment_maps) == 1
    assert segment_maps[0]["request_id"] == "modelreq:test"
    assert summary["exact_total_tokens"] == 15
    assert summary["effective_total_tokens"] == 15
    assert summary["predicted_total_tokens"] == segment_map.predicted_prompt_tokens
    assert summary["cached_tokens"] == 4
    assert summary["cache_savings_tokens"] == 4
    assert cache_records[-1].status == "hit"


def test_provider_usage_extractor_handles_openai_and_anthropic_shapes() -> None:
    openai_response = SimpleNamespace(
        content="ok",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 20,
                "completion_tokens": 7,
                "total_tokens": 27,
                "prompt_tokens_details": {"cached_tokens": 8},
            }
        },
    )
    anthropic_response = SimpleNamespace(
        content="ok",
        usage_metadata={
            "input_tokens": 11,
            "output_tokens": 3,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 2,
        },
    )

    openai_usage = extract_provider_usage(openai_response, request_id="modelreq:openai")
    anthropic_usage = extract_provider_usage(anthropic_response, request_id="modelreq:anthropic")

    assert openai_usage is not None
    assert openai_usage.prompt_tokens == 20
    assert openai_usage.cached_tokens == 8
    assert openai_usage.total_tokens == 27
    assert anthropic_usage is not None
    assert anthropic_usage.prompt_tokens == 11
    assert anthropic_usage.completion_tokens == 3
    assert anthropic_usage.cache_read_tokens == 5
    assert anthropic_usage.cache_creation_tokens == 2
    assert anthropic_usage.total_tokens == 14
