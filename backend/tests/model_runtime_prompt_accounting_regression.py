from __future__ import annotations

from types import SimpleNamespace

from runtime.model_gateway.model_runtime import ModelRuntime, ModelSpec


class _ExpensivePromptAccountingLedger:
    def __init__(self) -> None:
        self.segment_maps: list[object] = []
        self.token_usage: list[object] = []
        self.prompt_cache: list[object] = []
        self.prompt_cache_breaks: list[object] = []
        self.prompt_stability: list[object] = []
        self.prompt_cache_baselines: list[object] = []

    def scoped_reads_are_expensive(self) -> bool:
        return True

    def record_segment_map(self, record: object) -> None:
        self.segment_maps.append(record)

    def record_token_usage(self, record: object) -> None:
        self.token_usage.append(record)

    def record_prompt_cache(self, record: object) -> None:
        self.prompt_cache.append(record)

    def record_prompt_cache_break(self, record: object) -> None:
        self.prompt_cache_breaks.append(record)

    def record_prompt_stability(self, record: object) -> None:
        self.prompt_stability.append(record)

    def record_prompt_cache_baseline(self, record: object) -> None:
        self.prompt_cache_baselines.append(record)

    def list_prompt_stability(self, **_kwargs):
        raise AssertionError("model hot path must not scan prompt stability history")

    def list_prompt_cache_baselines(self, **_kwargs):
        raise AssertionError("model hot path must not scan prompt cache baseline history")


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
            "request_id": "modelreq:expensive-ledger",
            "run_id": "turnrun:expensive-ledger",
            "session_id": "session:expensive-ledger",
            "source": "turn_action",
        },
        attempt=1,
        call_kind="turn_action",
    )

    assert accounting["request_id"] == "modelreq:expensive-ledger"
    assert len(ledger.segment_maps) == 1
    assert len(ledger.token_usage) == 1
    assert len(ledger.prompt_cache) == 1
    assert len(ledger.prompt_stability) == 1
    assert len(ledger.prompt_cache_baselines) == 1
