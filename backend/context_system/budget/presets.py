from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_CONTEXT_BUDGET_PRESET = "deepseek_1m"


@dataclass(frozen=True, slots=True)
class ContextBudgetPreset:
    preset_id: str
    title: str
    model_hint: str
    context_window_tokens: int
    available_context_tokens: int
    reserved_output_tokens: int
    long_term_token_cap: int
    description: str
    warning_context_tokens: int | None = None
    ready_context_tokens: int | None = None
    replacement_context_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["compaction_threshold_tokens"] = self.compaction_threshold_tokens()
        return payload

    def compaction_threshold_tokens(self) -> dict[str, int]:
        replacement = _positive_int(self.replacement_context_tokens, self.available_context_tokens)
        ready = _positive_int(self.ready_context_tokens, int(replacement * 0.85))
        warning = _positive_int(self.warning_context_tokens, int(replacement * 0.75))
        return {
            "warning": min(warning, replacement),
            "ready": min(max(warning, ready), replacement),
            "replacement": replacement,
        }

    def has_explicit_compaction_thresholds(self) -> bool:
        return any(
            value is not None
            for value in (
                self.warning_context_tokens,
                self.ready_context_tokens,
                self.replacement_context_tokens,
            )
        )


CONTEXT_BUDGET_PRESETS: tuple[ContextBudgetPreset, ...] = (
    ContextBudgetPreset(
        preset_id="compact_32k",
        title="32K 通用档",
        model_hint="常规 32K 上下文模型",
        context_window_tokens=32_000,
        available_context_tokens=24_000,
        reserved_output_tokens=4_000,
        long_term_token_cap=4_000,
        description="兼容较小上下文窗口，适合轻量对话和快速验证。",
    ),
    ContextBudgetPreset(
        preset_id="long_128k",
        title="128K 长上下文档",
        model_hint="主流长上下文模型",
        context_window_tokens=128_000,
        available_context_tokens=96_000,
        reserved_output_tokens=8_000,
        long_term_token_cap=12_000,
        description="适合常规长任务，能显著减少过早压缩。",
    ),
    ContextBudgetPreset(
        preset_id="extended_200k",
        title="200K 扩展档",
        model_hint="200K 级长上下文模型",
        context_window_tokens=200_000,
        available_context_tokens=160_000,
        reserved_output_tokens=12_000,
        long_term_token_cap=20_000,
        description="适合多文档、多轮链路和较长健康复盘。",
    ),
    ContextBudgetPreset(
        preset_id="deepseek_1m",
        title="DeepSeek 1M 档",
        model_hint="deepseek-v4-pro / deepseek-v4-flash",
        context_window_tokens=1_000_000,
        available_context_tokens=850_000,
        reserved_output_tokens=64_000,
        long_term_token_cap=120_000,
        description="默认 DeepSeek V4 档。匹配 V4 Pro/Flash 的 1M 上下文窗口，为输出和安全余量预留空间；预算上限不代表每轮都会装满。",
        warning_context_tokens=750_000,
        ready_context_tokens=800_000,
        replacement_context_tokens=850_000,
    ),
)


def list_context_budget_presets() -> list[dict[str, Any]]:
    return [preset.to_dict() for preset in CONTEXT_BUDGET_PRESETS]


def get_context_budget_preset(preset_id: str | None) -> ContextBudgetPreset:
    normalized = normalize_context_budget_preset_id(preset_id)
    return next(
        preset for preset in CONTEXT_BUDGET_PRESETS
        if preset.preset_id == normalized
    )


def normalize_context_budget_preset_id(preset_id: str | None) -> str:
    value = str(preset_id or DEFAULT_CONTEXT_BUDGET_PRESET).strip().lower()
    known = {preset.preset_id for preset in CONTEXT_BUDGET_PRESETS}
    return value if value in known else DEFAULT_CONTEXT_BUDGET_PRESET


def match_context_budget_preset_for_model(
    *,
    provider: str,
    model: str,
    context_window_tokens: int | None = None,
) -> ContextBudgetPreset | None:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_provider != "deepseek" and "deepseek" not in normalized_model:
        return None

    preset = get_context_budget_preset("deepseek_1m")
    large_window_floor = int(int(preset.context_window_tokens) * 0.9)
    if int(context_window_tokens or 0) < large_window_floor:
        return None
    return preset


def match_context_budget_preset_for_available_context_tokens(
    available_context_tokens: int,
) -> ContextBudgetPreset | None:
    target = int(available_context_tokens or 0)
    for preset in CONTEXT_BUDGET_PRESETS:
        if int(preset.available_context_tokens) == target and preset.has_explicit_compaction_thresholds():
            return preset
    return None


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(1, parsed if parsed > 0 else int(fallback or 1))


