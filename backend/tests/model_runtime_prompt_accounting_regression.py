from __future__ import annotations

from types import SimpleNamespace

from harness.runtime.compiler import _fixed_context_package_message_specs
from harness.runtime.prompt_segment_plan import build_prompt_segment_plan
from prompt_composition import build_model_message_spec
from runtime.context_management import (
    PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS,
    load_provider_visible_context_ledger,
)
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


def _context_spec(*, kind: str, content: str) -> dict:
    return build_model_message_spec(
        role="system",
        content=content,
        kind=kind,
        source_ref=kind,
        cache_scope="task",
        cache_role="session_stable",
        compression_role="preserve",
    )


def _runtime_for_confirmation() -> ModelRuntime:
    return ModelRuntime(
        SimpleNamespace(static=SimpleNamespace(llm_timeout_seconds=1, llm_max_retries=0, llm_max_output_tokens=1024)),
    )


def _accounting_for_provider_visible_context(runtime: ModelRuntime, *, backend_dir, scope: str, request_id: str) -> dict:
    specs = _fixed_context_package_message_specs(
        [_context_spec(kind="runtime_memory_context", content="Memory\nprovider success boundary")],
        invocation_kind="single_agent_turn",
        provider_visible_context_scope=scope,
        storage_root=backend_dir,
    )
    segment_plan = build_prompt_segment_plan(
        packet_id=f"rtpacket:{request_id}",
        invocation_kind="single_agent_turn",
        message_specs=specs,
    ).to_dict()
    return runtime._begin_prompt_accounting(
        [dict(item.get("model_message") or {"role": item["role"], "content": item["content"]}) for item in specs],
        tools=[],
        spec=ModelSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key=None,
            base_url="https://api.deepseek.com",
        ),
        accounting_context={
            "request_id": request_id,
            "session_id": scope,
            "source": "single_agent_turn",
            "segment_plan": segment_plan,
        },
        attempt=1,
        call_kind="single_agent_turn",
    )


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


def test_model_runtime_confirms_provider_visible_context_after_success_response(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    scope = "session:runtime-provider-success"
    runtime = _runtime_for_confirmation()
    accounting = _accounting_for_provider_visible_context(
        runtime,
        backend_dir=backend_dir,
        scope=scope,
        request_id="modelreq:runtime-provider-success",
    )

    runtime._finish_prompt_accounting(accounting, response=SimpleNamespace(content="ok", id="resp:ok"))

    ledger = load_provider_visible_context_ledger(
        storage_root=backend_dir,
        scope=f"single_agent_turn:{scope}",
    )
    assert ledger["entries"][0]["commit_status"] == PROVIDER_VISIBLE_CONTEXT_LEDGER_CONFIRMED_STATUS


def test_model_runtime_does_not_confirm_provider_visible_context_after_error(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    scope = "session:runtime-provider-error"
    runtime = _runtime_for_confirmation()
    accounting = _accounting_for_provider_visible_context(
        runtime,
        backend_dir=backend_dir,
        scope=scope,
        request_id="modelreq:runtime-provider-error",
    )

    runtime._finish_prompt_accounting(accounting, response=None, error=RuntimeError("provider failed"))

    ledger = load_provider_visible_context_ledger(
        storage_root=backend_dir,
        scope=f"single_agent_turn:{scope}",
    )
    assert ledger == {}


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
