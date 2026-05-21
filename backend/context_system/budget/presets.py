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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        model_hint="1M 上下文模型",
        context_window_tokens=1_000_000,
        available_context_tokens=900_000,
        reserved_output_tokens=64_000,
        long_term_token_cap=120_000,
        description="当前推荐档位。为 1M 窗口保留输出和安全余量，压缩阈值大幅后移。",
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
