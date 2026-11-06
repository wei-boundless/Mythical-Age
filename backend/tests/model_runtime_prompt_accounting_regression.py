from __future__ import annotations

from types import SimpleNamespace

from runtime.model_gateway.model_runtime import ModelRuntime, ModelSpec


class _ExpensivePromptAccountingLedger:
    def __init__(self) -> None:
        self.segment_maps: list[object] = []
        self.token_usage: list[object] = []
        self.cache_plans: list[object] = []
        self.cache_anomalies: list[object] = []
        self.prefix_state: list[object] = []

    def scoped_reads_are_expensive(self) -> bool:
        return True

    def record_segment_map(self, record: object) -> None:
        self.segment_maps.append(record)

    def record_token_usage(self, record: object) -> None:
        self.token_usage.append(record)

    def record_context_usage_snapshot(self, *_args, **_kwargs) -> None:
        return None

    def record_cache_plan(self, record: object) -> None:
        self.cache_plans.append(record)

    def record_cache_anomaly(self, record: object) -> None:
        self.cache_anomalies.append(record)

    def record_prefix_state(self, record: object) -> None:
        self.prefix_state.append(record)

    def list_recent_prefix_state(self, **_kwargs):
        return []

    def list_prefix_state(self, **_kwargs):
        raise AssertionError("model hot path must not scan prefix state ledger when reads are expensive")

    def list_cache_plans(self, **_kwargs):
        raise AssertionError("model hot path must not scan cache plan ledger when reads are expensive")


def test_prompt_accounting_skips_history_scans_when_ledger_reads_are_expensive() -> None:
    ledger = _ExpensivePromptAccountingLedger()
    runtime = ModelRuntime(
        SimpleNamespace(static=SimpleNamespace(llm_timeout_seconds=1, llm_max_retries=0, llm_max_output_tokens=1024)),
        prompt_accounting_ledger=ledger,
    )

    accounting = runtime._begin_prompt_accounting(
        [{"role": "user", "content": "hello"}],
        tools=[],
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key=None,
            base_url="https://api.deepseek.com",
        ),
        accounting_context={
            "request_id": "providerreq:expensive-ledger",
            "run_id": "turnrun:expensive-ledger",
            "session_id": "session:expensive-ledger",
            "source": "turn_action",
        },
        attempt=1,
        call_kind="turn_action",
    )

    assert accounting["request_id"] == "providerreq:expensive-ledger"
    assert len(ledger.segment_maps) == 1
    assert len(ledger.token_usage) == 1
    assert len(ledger.cache_plans) == 1
    assert len(ledger.prefix_state) == 1


def test_model_runtime_maps_provider_402_balance_error_as_non_retryable() -> None:
    runtime = ModelRuntime(
        SimpleNamespace(static=SimpleNamespace(llm_timeout_seconds=1, llm_max_retries=0, llm_max_output_tokens=1024)),
    )
    spec = ModelSpec(
        provider="deepseek",
        model="deepseek-chat",
        api_key=None,
        base_url="https://api.deepseek.com",
    )

    error = runtime._map_error(
        RuntimeError('Provider request failed with HTTP 402: {"error":{"message":"Insufficient Balance"}}'),
        spec,
    )

    assert error.code == "insufficient_balance"
    assert error.provider == "deepseek"
    assert error.model == "deepseek-chat"
    assert error.retryable is False
    assert "余额不足" in error.user_message


def test_model_runtime_maps_insufficient_quota_before_rate_limit() -> None:
    runtime = ModelRuntime(
        SimpleNamespace(static=SimpleNamespace(llm_timeout_seconds=1, llm_max_retries=0, llm_max_output_tokens=1024)),
    )
    spec = ModelSpec(
        provider="openai",
        model="gpt-test",
        api_key=None,
        base_url="https://api.openai.com/v1",
    )

    error = runtime._map_error(
        RuntimeError("Error code: 429 - insufficient_quota: You exceeded your current quota."),
        spec,
    )

    assert error.code == "insufficient_balance"
    assert error.retryable is False
