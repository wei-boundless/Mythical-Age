from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from config import get_settings, runtime_config
from context_system.budget.presets import get_context_budget_preset, normalize_context_budget_preset_id


CHARS_PER_TOKEN_ESTIMATE = 4

_DEEPSEEK_1M_MODELS = frozenset({"deepseek-v4-pro", "deepseek-v4-flash"})


@dataclass(frozen=True, slots=True)
class ModelAwareContextBudgetPolicy:
    invocation_kind: str
    provider: str
    model: str
    requested_preset_id: str
    effective_preset_id: str
    preset_source: str
    preset_status: str
    context_window_tokens: int
    available_context_tokens: int
    reserved_output_tokens: int
    max_output_tokens: int
    thinking_mode: str
    reasoning_effort: str
    allocation_tokens: dict[str, int]
    projection_limits: dict[str, int]
    volatile_char_budget: int
    diagnostics: dict[str, Any]
    authority: str = "harness.runtime.context_budget_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_projection_policy(self) -> dict[str, Any]:
        return {
            **dict(self.projection_limits),
            "volatile_char_budget": self.volatile_char_budget,
            "context_budget_policy": self.to_dict(),
        }


def build_model_aware_context_budget_policy(
    *,
    invocation_kind: str,
    model_selection: dict[str, Any] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
) -> ModelAwareContextBudgetPolicy:
    settings = get_settings()
    assembly = dict(runtime_assembly or {})
    selection = _merged_model_selection(model_selection=model_selection, runtime_assembly=assembly)
    provider = str(selection.get("provider") or getattr(settings, "llm_provider", "") or "").strip().lower()
    model = str(selection.get("model") or getattr(settings, "llm_model", "") or "").strip().lower()
    max_output_tokens = _positive_int(selection.get("max_output_tokens"), int(getattr(settings, "llm_max_output_tokens", 65536) or 65536))
    thinking_mode = str(selection.get("thinking_mode") or getattr(settings, "llm_thinking_mode", "disabled") or "disabled").strip().lower()
    reasoning_effort = str(selection.get("reasoning_effort") or getattr(settings, "llm_reasoning_effort", "auto") or "auto").strip().lower()
    requested_preset_id, preset_source = _requested_preset(selection=selection, runtime_assembly=assembly)
    effective_preset_id, preset_status = _effective_preset_for_model(
        requested_preset_id,
        provider=provider,
        model=model,
    )
    preset = get_context_budget_preset(effective_preset_id)
    reserved_output_tokens = max(int(preset.reserved_output_tokens), max_output_tokens)
    safety_margin_tokens = max(1024, int(preset.context_window_tokens * 0.02))
    available_context_tokens = min(
        int(preset.available_context_tokens),
        max(1000, int(preset.context_window_tokens) - reserved_output_tokens - safety_margin_tokens),
    )
    allocation_tokens = _allocation_tokens(
        invocation_kind=str(invocation_kind or ""),
        available_context_tokens=available_context_tokens,
    )
    projection_limits = _projection_limits(
        allocation_tokens=allocation_tokens,
        long_term_token_cap=int(preset.long_term_token_cap),
    )
    volatile_char_budget = _volatile_char_budget(allocation_tokens)
    diagnostics = {
        "requested_context_window_tokens": int(get_context_budget_preset(requested_preset_id).context_window_tokens),
        "safety_margin_tokens": safety_margin_tokens,
        "deepseek_1m_compatible": _is_deepseek_1m_model(provider=provider, model=model),
    }
    if preset_status != "selected":
        diagnostics["preset_rejection_reason"] = "deepseek_1m_requires_deepseek_v4_pro_or_flash"
    return ModelAwareContextBudgetPolicy(
        invocation_kind=str(invocation_kind or ""),
        provider=provider,
        model=model,
        requested_preset_id=requested_preset_id,
        effective_preset_id=effective_preset_id,
        preset_source=preset_source,
        preset_status=preset_status,
        context_window_tokens=int(preset.context_window_tokens),
        available_context_tokens=available_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        max_output_tokens=max_output_tokens,
        thinking_mode=thinking_mode,
        reasoning_effort=reasoning_effort,
        allocation_tokens=allocation_tokens,
        projection_limits=projection_limits,
        volatile_char_budget=volatile_char_budget,
        diagnostics=diagnostics,
    )


def _merged_model_selection(
    *,
    model_selection: dict[str, Any] | None,
    runtime_assembly: dict[str, Any],
) -> dict[str, Any]:
    return {
        **dict(runtime_assembly.get("model_selection") or {}),
        **dict(model_selection or {}),
    }


def _requested_preset(*, selection: dict[str, Any], runtime_assembly: dict[str, Any]) -> tuple[str, str]:
    for key, source in (
        ("context_budget_preset", "model_selection"),
        ("context_window_preset", "model_selection"),
    ):
        value = str(selection.get(key) or "").strip()
        if value:
            return normalize_context_budget_preset_id(value), source
    value = str(runtime_assembly.get("context_budget_preset") or "").strip()
    if value:
        return normalize_context_budget_preset_id(value), "runtime_assembly"
    return runtime_config.get_context_budget_preset(), "runtime_config"


def _effective_preset_for_model(requested_preset_id: str, *, provider: str, model: str) -> tuple[str, str]:
    requested = normalize_context_budget_preset_id(requested_preset_id)
    if requested == "deepseek_1m" and not _is_deepseek_1m_model(provider=provider, model=model):
        return "long_128k", "incompatible_model_downgraded"
    return requested, "selected"


def _is_deepseek_1m_model(*, provider: str, model: str) -> bool:
    if str(provider or "").strip().lower() != "deepseek":
        return False
    normalized = str(model or "").strip().lower().split("/")[-1]
    return normalized in _DEEPSEEK_1M_MODELS


def _allocation_tokens(*, invocation_kind: str, available_context_tokens: int) -> dict[str, int]:
    weights = _allocation_weights(invocation_kind)
    total = max(1000, int(available_context_tokens or 0))
    return {
        name: max(_minimum_tokens_for_bucket(name), int(total * weight))
        for name, weight in weights.items()
    }


def _allocation_weights(invocation_kind: str) -> dict[str, float]:
    if invocation_kind == "task_execution":
        return {
            "stable_prefix": 0.28,
            "tool_schema": 0.10,
            "deferred_index": 0.05,
            "volatile_state": 0.34,
            "recent_history": 0.05,
            "observation": 0.12,
        }
    if invocation_kind == "tool_observation_followup":
        return {
            "stable_prefix": 0.22,
            "tool_schema": 0.08,
            "deferred_index": 0.05,
            "volatile_state": 0.22,
            "recent_history": 0.23,
            "observation": 0.20,
        }
    return {
        "stable_prefix": 0.24,
        "tool_schema": 0.07,
        "deferred_index": 0.05,
        "volatile_state": 0.24,
        "recent_history": 0.30,
        "observation": 0.10,
    }


def _minimum_tokens_for_bucket(name: str) -> int:
    return {
        "stable_prefix": 3000,
        "tool_schema": 1200,
        "deferred_index": 800,
        "volatile_state": 3000,
        "recent_history": 2000,
        "observation": 1500,
    }.get(name, 1000)


def _projection_limits(*, allocation_tokens: dict[str, int], long_term_token_cap: int) -> dict[str, int]:
    recent_history_tokens = int(allocation_tokens.get("recent_history") or 0)
    observation_tokens = int(allocation_tokens.get("observation") or 0)
    volatile_tokens = int(allocation_tokens.get("volatile_state") or 0)
    latest_observation_limit = _clamp_int(observation_tokens // 1200, low=8, high=48)
    recent_work_step_limit = _clamp_int(volatile_tokens // 1500, low=8, high=80)
    recent_history_message_limit = _clamp_int(recent_history_tokens // 600, low=6, high=240)
    history_message_chars = _clamp_int(
        (recent_history_tokens * CHARS_PER_TOKEN_ESTIMATE) // max(1, recent_history_message_limit),
        low=1200,
        high=6000,
    )
    tool_result_preview_chars = _clamp_int(
        (observation_tokens * CHARS_PER_TOKEN_ESTIMATE) // max(8, latest_observation_limit),
        low=4000,
        high=24000,
    )
    observation_summary_chars = _clamp_int(tool_result_preview_chars // 3, low=600, high=4000)
    return {
        "recent_history_message_limit": recent_history_message_limit,
        "history_message_chars": history_message_chars,
        "compressed_summary_chars": _clamp_int(long_term_token_cap * CHARS_PER_TOKEN_ESTIMATE, low=4000, high=96000),
        "tool_trajectory_limit": _clamp_int(recent_history_message_limit // 2, low=8, high=60),
        "tool_trajectory_result_chars": _clamp_int(history_message_chars // 3, low=300, high=2000),
        "latest_observation_limit": latest_observation_limit,
        "active_failure_limit": _clamp_int(latest_observation_limit // 2, low=8, high=40),
        "observation_summary_chars": observation_summary_chars,
        "tool_result_preview_chars": tool_result_preview_chars,
        "recent_work_step_limit": recent_work_step_limit,
        "work_step_summary_chars": _clamp_int((volatile_tokens * CHARS_PER_TOKEN_ESTIMATE) // max(8, recent_work_step_limit), low=500, high=4000),
        "work_progress_chars": _clamp_int((volatile_tokens * CHARS_PER_TOKEN_ESTIMATE) // 100, low=500, high=4000),
    }


def _volatile_char_budget(allocation_tokens: dict[str, int]) -> int:
    volatile_tokens = (
        int(allocation_tokens.get("volatile_state") or 0)
        + int(allocation_tokens.get("recent_history") or 0)
        + int(allocation_tokens.get("observation") or 0)
    )
    return max(1000, volatile_tokens * CHARS_PER_TOKEN_ESTIMATE)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def _clamp_int(value: Any, *, low: int, high: int) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(high, parsed))
