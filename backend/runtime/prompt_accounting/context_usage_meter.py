from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from context_system.budget.presets import match_context_budget_preset_for_model

from .models import ModelTokenUsageRecord
from .token_counter import TokenCounterRegistry


ContextEstimateMode = Literal[
    "provider_anchor",
    "session_pressure",
    "local_predicted_no_provider_anchor",
    "local_predicted_anchor_invalid",
    "local_predicted_newer_than_provider",
    "empty",
]
ContextPressureLevel = Literal["normal", "warning", "microcompact", "full_compact"]


@dataclass(frozen=True, slots=True)
class ContextUsageSnapshot:
    session_id: str = ""
    run_id: str = ""
    task_run_id: str = ""
    provider: str = ""
    model: str = ""
    context_window_tokens: int = 0
    reserved_output_tokens: int = 0
    safety_margin_tokens: int = 0
    input_capacity_tokens: int = 0
    warning_threshold_tokens: int = 0
    ready_threshold_tokens: int = 0
    replacement_threshold_tokens: int = 0
    provider_anchor_request_id: str = ""
    provider_anchor_created_at: float = 0.0
    provider_prompt_tokens: int = 0
    provider_completion_tokens: int = 0
    provider_reasoning_tokens: int = 0
    provider_total_tokens: int = 0
    provider_cached_tokens: int = 0
    estimated_pending_tokens: int = 0
    current_context_tokens: int = 0
    compaction_pressure_tokens: int = 0
    current_context_ratio: float = 0.0
    compaction_pressure_ratio: float = 0.0
    compaction_remaining_tokens: int = 0
    compaction_remaining_ratio: float = 0.0
    pressure_level: ContextPressureLevel = "normal"
    auto_replacement_allowed: bool = False
    cache_hit_rate_latest: float = 0.0
    cache_hit_rate_last_5: float = 0.0
    cache_hit_rate_last_10: float = 0.0
    cache_hit_rate_last_20: float = 0.0
    estimate_mode: ContextEstimateMode = "empty"
    anchor_valid: bool = False
    invalidation_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.context_usage_snapshot"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextUsageMeter:
    """Builds the current session pressure meter for a model context window.

    Billing totals remain owned by PromptAccountingLedger summaries. Provider
    records are kept here as cache diagnostics, not as the pressure authority
    when a deterministic session pressure is supplied by context management.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        token_counter: TokenCounterRegistry | None = None,
        default_context_window_tokens: int = 128_000,
        default_reserved_output_tokens: int = 8_192,
        safety_margin_tokens: int = 8_192,
    ) -> None:
        self.ledger = ledger
        self.token_counter = token_counter or TokenCounterRegistry()
        self.default_context_window_tokens = max(1, int(default_context_window_tokens or 128_000))
        self.default_reserved_output_tokens = max(0, int(default_reserved_output_tokens or 0))
        self.safety_margin_tokens = max(0, int(safety_margin_tokens or 0))

    def build_snapshot(
        self,
        *,
        session_id: str = "",
        run_id: str = "",
        task_run_id: str = "",
        provider: str = "",
        model: str = "",
        context_window_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        pending_messages: list[Any] | tuple[Any, ...] | None = None,
        fallback_messages: list[Any] | tuple[Any, ...] | None = None,
        session_pressure_tokens: int | None = None,
        session_pressure_source: str = "",
        session_pressure_diagnostics: dict[str, Any] | None = None,
        context_fingerprint: str = "",
        previous_context_fingerprint: str = "",
    ) -> ContextUsageSnapshot:
        records = self._list_token_usage(session_id=session_id, run_id=run_id, task_run_id=task_run_id)
        candidate_records = self._context_meter_candidate_records(records)
        candidate_scope = "agent_runtime" if len(candidate_records) != len(records) else "all_session_usage"
        provider_records = [record for record in candidate_records if record.source == "provider_usage"]
        local_records = [record for record in candidate_records if record.source == "local_prediction"]
        anchor = provider_records[-1] if provider_records else None
        local_anchor = local_records[-1] if local_records else None
        local_newer_than_provider = self._record_newer(local_anchor, anchor)
        effective_anchor = local_anchor if local_newer_than_provider else (anchor or local_anchor)
        resolved_provider = str(provider or getattr(effective_anchor, "provider", "") or "")
        resolved_model = str(model or getattr(effective_anchor, "model", "") or "")
        window = max(1, int(context_window_tokens or self._default_window_for_model(resolved_provider, resolved_model)))
        reserved = max(0, int(reserved_output_tokens if reserved_output_tokens is not None else self.default_reserved_output_tokens))
        input_capacity_tokens = self._input_capacity_tokens(context_window_tokens=window, reserved_output_tokens=reserved)
        thresholds = self._thresholds(provider=resolved_provider, model=resolved_model, context_window_tokens=window, reserved_output_tokens=reserved)
        invalidation_reason = self._invalidation_reason(
            context_fingerprint=context_fingerprint,
            previous_context_fingerprint=previous_context_fingerprint,
        )
        if anchor is not None and not invalidation_reason and not local_newer_than_provider:
            provider_context_tokens = self._provider_context_tokens(anchor)
            observation_anchor_created_at = float(getattr(anchor, "created_at", 0.0) or 0.0)
            estimate_mode: ContextEstimateMode = "provider_anchor"
            provider_anchor_valid = True
            observed_context_source = "provider_usage"
        elif local_anchor is not None:
            provider_context_tokens = 0
            observation_anchor_created_at = float(getattr(local_anchor, "created_at", 0.0) or 0.0)
            if invalidation_reason:
                estimate_mode = "local_predicted_anchor_invalid"
            elif anchor is not None and local_newer_than_provider:
                estimate_mode = "local_predicted_newer_than_provider"
            else:
                estimate_mode = "local_predicted_no_provider_anchor"
            provider_anchor_valid = False
            observed_context_source = "local_prediction"
        else:
            provider_context_tokens = 0
            observation_anchor_created_at = 0.0
            estimate_mode = "empty"
            provider_anchor_valid = False
            observed_context_source = "provided_model_messages" if pending_messages is not None else "fallback_messages"
        provider_pending_tokens = self._estimate_pending_tokens(
            pending_messages=pending_messages,
            fallback_messages=fallback_messages,
            anchor_created_at=observation_anchor_created_at,
            provider=resolved_provider,
            model=resolved_model,
        )
        if observed_context_source == "provider_usage":
            observed_context_tokens = provider_context_tokens + provider_pending_tokens
        elif observed_context_source == "local_prediction":
            observed_context_tokens = int(local_anchor.total_tokens or local_anchor.prompt_tokens or 0) + provider_pending_tokens
        else:
            observed_context_tokens = self._estimate_messages(fallback_messages or pending_messages or (), provider=resolved_provider, model=resolved_model)
            estimate_mode = "empty" if observed_context_tokens <= 0 else "local_predicted_no_provider_anchor"

        pressure_tokens_supplied = session_pressure_tokens is not None
        accounting_observation_available = observed_context_source in {"provider_usage", "local_prediction"}
        session_pressure_is_current_source = (
            pressure_tokens_supplied
            and not accounting_observation_available
            and pending_messages is None
        )
        if session_pressure_is_current_source:
            current_context_tokens = max(0, int(session_pressure_tokens or 0))
            estimate_mode = "session_pressure"
            pending_tokens = 0
        else:
            current_context_tokens = observed_context_tokens
            pending_tokens = provider_pending_tokens

        session_pressure_value = max(0, int(session_pressure_tokens or 0)) if pressure_tokens_supplied else 0
        compaction_pressure_tokens = max(0, int(current_context_tokens or 0))
        current_context_authority = (
            str(session_pressure_source or "runtime.context_management.session_pressure")
            if session_pressure_is_current_source
            else (
                "runtime.prompt_accounting.model_request_accounting"
                if accounting_observation_available
                else "runtime.prompt_accounting.provided_model_messages"
            )
        )
        compaction_pressure_authority = current_context_authority
        pressure_level = self._pressure_level(compaction_pressure_tokens, thresholds)
        ratio = round(current_context_tokens / window, 6) if window > 0 else 0.0
        replacement_threshold = int(thresholds.get("replacement") or input_capacity_tokens)
        compaction_pressure_ratio = round(compaction_pressure_tokens / replacement_threshold, 6) if replacement_threshold > 0 else 0.0
        compaction_remaining_tokens = max(0, replacement_threshold - int(compaction_pressure_tokens or 0))
        compaction_remaining_ratio = round(compaction_remaining_tokens / replacement_threshold, 6) if replacement_threshold > 0 else 0.0
        cache_rates = self._cache_hit_rates(provider_records)
        latest_cache_hit_rate = self._cache_hit_rate(anchor)
        return ContextUsageSnapshot(
            session_id=str(session_id or getattr(anchor, "session_id", "") or getattr(local_anchor, "session_id", "") or ""),
            run_id=str(run_id or getattr(anchor, "run_id", "") or getattr(local_anchor, "run_id", "") or ""),
            task_run_id=str(task_run_id or getattr(anchor, "task_run_id", "") or getattr(local_anchor, "task_run_id", "") or ""),
            provider=resolved_provider,
            model=resolved_model,
            context_window_tokens=window,
            reserved_output_tokens=reserved,
            safety_margin_tokens=self.safety_margin_tokens,
            input_capacity_tokens=input_capacity_tokens,
            warning_threshold_tokens=thresholds["warning"],
            ready_threshold_tokens=thresholds["ready"],
            replacement_threshold_tokens=thresholds["replacement"],
            provider_anchor_request_id=str(getattr(anchor, "request_id", "") or ""),
            provider_anchor_created_at=float(getattr(anchor, "created_at", 0.0) or 0.0),
            provider_prompt_tokens=int(getattr(anchor, "prompt_tokens", 0) or 0),
            provider_completion_tokens=int(getattr(anchor, "completion_tokens", 0) or 0),
            provider_reasoning_tokens=int(getattr(anchor, "reasoning_tokens", 0) or 0),
            provider_total_tokens=int(getattr(anchor, "total_tokens", 0) or 0),
            provider_cached_tokens=int(getattr(anchor, "cached_tokens", 0) or 0),
            estimated_pending_tokens=pending_tokens,
            current_context_tokens=max(0, int(current_context_tokens or 0)),
            compaction_pressure_tokens=compaction_pressure_tokens,
            current_context_ratio=ratio,
            compaction_pressure_ratio=compaction_pressure_ratio,
            compaction_remaining_tokens=compaction_remaining_tokens,
            compaction_remaining_ratio=compaction_remaining_ratio,
            pressure_level=pressure_level,
            auto_replacement_allowed=compaction_pressure_tokens >= thresholds["replacement"],
            cache_hit_rate_latest=latest_cache_hit_rate,
            cache_hit_rate_last_5=cache_rates[5],
            cache_hit_rate_last_10=cache_rates[10],
            cache_hit_rate_last_20=cache_rates[20],
            estimate_mode=estimate_mode,
            anchor_valid=provider_anchor_valid,
            invalidation_reason=invalidation_reason,
            diagnostics={
                "record_count": len(candidate_records),
                "raw_record_count": len(records),
                "candidate_scope": candidate_scope,
                "provider_usage_record_count": len(provider_records),
                "local_prediction_record_count": len(local_records),
                "pressure_authority": str(session_pressure_source or "provider_accounting"),
                "session_pressure_supplied": bool(pressure_tokens_supplied),
                "session_pressure_tokens": session_pressure_value,
                "session_pressure_used_as_current_context": bool(session_pressure_is_current_source),
                "current_context_authority": current_context_authority,
                "compaction_pressure_tokens": compaction_pressure_tokens,
                "compaction_pressure_authority": compaction_pressure_authority,
                "observed_context_source": observed_context_source,
                "prompt_accounting_observed_context_tokens": max(0, int(observed_context_tokens or 0)),
                "provider_observed_context_tokens": max(0, int(observed_context_tokens or 0)),
                "provider_estimated_pending_tokens": provider_pending_tokens,
                "provider_context_tokens": provider_context_tokens,
                "effective_anchor_source": str(getattr(effective_anchor, "source", "") or ""),
                "effective_anchor_request_id": str(getattr(effective_anchor, "request_id", "") or ""),
                "effective_anchor_created_at": float(getattr(effective_anchor, "created_at", 0.0) or 0.0),
                "local_prediction_newer_than_provider": bool(local_newer_than_provider),
                "context_fingerprint": str(context_fingerprint or ""),
                "previous_context_fingerprint": str(previous_context_fingerprint or ""),
                **dict(session_pressure_diagnostics or {}),
            },
            authority=(
                "runtime.context_management.session_pressure_snapshot"
                if session_pressure_is_current_source
                else "runtime.prompt_accounting.context_usage_snapshot"
            ),
        )

    def _list_token_usage(self, *, session_id: str, run_id: str, task_run_id: str) -> list[ModelTokenUsageRecord]:
        list_token_usage = getattr(self.ledger, "list_token_usage", None)
        if not callable(list_token_usage):
            return []
        records = list_token_usage(session_id=session_id, run_id=run_id, task_run_id=task_run_id)
        return sorted(list(records or []), key=lambda item: float(getattr(item, "created_at", 0.0) or 0.0))

    def _context_meter_candidate_records(self, records: list[ModelTokenUsageRecord]) -> list[ModelTokenUsageRecord]:
        runtime_records = [record for record in records if self._is_agent_runtime_record(record)]
        return runtime_records or records

    def _provider_context_tokens(self, record: ModelTokenUsageRecord) -> int:
        prompt = int(record.prompt_tokens or 0)
        if prompt > 0:
            return prompt
        total = int(record.total_tokens or 0)
        if total > 0:
            completion = int(record.completion_tokens or 0) + int(record.reasoning_tokens or 0)
            return max(0, total - completion)
        return 0

    def _is_agent_runtime_record(self, record: ModelTokenUsageRecord) -> bool:
        request_id = str(getattr(record, "request_id", "") or "")
        if not request_id.startswith("modelreq:"):
            return False
        diagnostics = dict(getattr(record, "diagnostics", {}) or {})
        cache_metric_scope = str(diagnostics.get("cache_metric_scope") or "")
        if cache_metric_scope == "agent_runtime" or cache_metric_scope.startswith("agent_runtime."):
            return True
        if str(diagnostics.get("packet_ref") or "").startswith("rtpacket:"):
            return True
        return "rtpacket:" in request_id

    def _record_newer(self, candidate: ModelTokenUsageRecord | None, baseline: ModelTokenUsageRecord | None) -> bool:
        if candidate is None:
            return False
        if baseline is None:
            return True
        return float(candidate.created_at or 0.0) > float(baseline.created_at or 0.0)

    def _estimate_pending_tokens(
        self,
        *,
        pending_messages: list[Any] | tuple[Any, ...] | None,
        fallback_messages: list[Any] | tuple[Any, ...] | None,
        anchor_created_at: float,
        provider: str,
        model: str,
    ) -> int:
        if pending_messages is not None:
            return self._estimate_messages(pending_messages, provider=provider, model=model)
        if not fallback_messages or anchor_created_at <= 0:
            return 0
        pending = []
        for message in list(fallback_messages or []):
            created_at = self._message_created_at(message)
            if created_at and created_at > anchor_created_at:
                pending.append(message)
        return self._estimate_messages(pending, provider=provider, model=model)

    def _estimate_messages(self, messages: list[Any] | tuple[Any, ...], *, provider: str, model: str) -> int:
        if not messages:
            return 0
        return self.token_counter.count_messages(list(messages), provider=provider, model=model).tokens

    def _message_created_at(self, message: Any) -> float:
        if isinstance(message, dict):
            value = message.get("created_at") or message.get("updated_at") or message.get("timestamp")
        else:
            value = getattr(message, "created_at", None) or getattr(message, "updated_at", None) or getattr(message, "timestamp", None)
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _default_window_for_model(self, provider: str, model: str) -> int:
        normalized_provider = str(provider or "").strip().lower()
        normalized_model = str(model or "").strip().lower()
        if normalized_provider == "deepseek" or "deepseek" in normalized_model:
            return 1_000_000
        if normalized_model.startswith("gpt-4.1") or normalized_model.startswith("gpt-5"):
            return 1_000_000
        if normalized_model.startswith(("gpt-4o", "o3", "o4")):
            return 128_000
        return self.default_context_window_tokens

    def _input_capacity_tokens(self, *, context_window_tokens: int, reserved_output_tokens: int) -> int:
        return max(1, int(context_window_tokens or 0) - int(reserved_output_tokens or 0) - self.safety_margin_tokens)

    def _thresholds(self, *, provider: str, model: str, context_window_tokens: int, reserved_output_tokens: int) -> dict[str, int]:
        available_input = self._input_capacity_tokens(context_window_tokens=context_window_tokens, reserved_output_tokens=reserved_output_tokens)
        preset = match_context_budget_preset_for_model(
            provider=provider,
            model=model,
            context_window_tokens=context_window_tokens,
        )
        if preset is not None:
            thresholds = preset.compaction_threshold_tokens()
            return {
                "warning": min(int(thresholds["warning"]), available_input),
                "ready": min(int(thresholds["ready"]), available_input),
                "replacement": min(int(thresholds["replacement"]), available_input),
            }
        return {
            "warning": max(1, int(available_input * 0.75)),
            "ready": max(1, int(available_input * 0.85)),
            "replacement": max(1, int(available_input * 0.92)),
        }

    def _pressure_level(self, tokens: int, thresholds: dict[str, int]) -> ContextPressureLevel:
        if tokens >= int(thresholds.get("replacement") or 0):
            return "full_compact"
        if tokens >= int(thresholds.get("ready") or 0):
            return "microcompact"
        if tokens >= int(thresholds.get("warning") or 0):
            return "warning"
        return "normal"

    def _cache_hit_rates(self, records: list[ModelTokenUsageRecord]) -> dict[int, float]:
        return {
            size: self._cache_hit_rate_for_records(records[-size:])
            for size in (5, 10, 20)
        }

    def _cache_hit_rate_for_records(self, records: list[ModelTokenUsageRecord]) -> float:
        returned_records = [record for record in records if _provider_hit_miss_available(record)]
        if returned_records:
            cached_tokens = sum(int(record.cached_tokens or record.cache_read_tokens or 0) for record in returned_records)
            miss_tokens = sum(int(record.cache_miss_tokens or 0) for record in returned_records)
            return round(cached_tokens / (cached_tokens + miss_tokens), 4) if (cached_tokens + miss_tokens) > 0 else 0.0
        cached_tokens = sum(int(record.cached_tokens or record.cache_read_tokens or 0) for record in records)
        prompt_tokens = sum(int(record.prompt_tokens or 0) for record in records)
        return round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0

    def _cache_hit_rate(self, record: ModelTokenUsageRecord | None) -> float:
        if record is None or int(record.prompt_tokens or 0) <= 0:
            return 0.0
        cached_tokens = max(int(record.cached_tokens or 0), int(record.cache_read_tokens or 0))
        miss_tokens = int(record.cache_miss_tokens or 0)
        if _provider_hit_miss_available(record):
            return round(cached_tokens / (cached_tokens + miss_tokens), 4) if (cached_tokens + miss_tokens) > 0 else 0.0
        return round(cached_tokens / int(record.prompt_tokens or 0), 4)

    def _invalidation_reason(self, *, context_fingerprint: str, previous_context_fingerprint: str) -> str:
        current = str(context_fingerprint or "").strip()
        previous = str(previous_context_fingerprint or "").strip()
        if current and previous and current != previous:
            return "environment_fingerprint_changed"
        return ""


def _provider_hit_miss_available(record: ModelTokenUsageRecord) -> bool:
    diagnostics = dict(record.diagnostics or {})
    return str(diagnostics.get("provider_cache_hit_rate_source") or "") == "provider_hit_miss_tokens"
