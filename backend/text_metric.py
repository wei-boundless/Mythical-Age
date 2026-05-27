from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class TextMetricResult:
    measurement_mode: str
    text_units: int
    cjk_chars: int
    latin_words: int
    char_count: int
    non_whitespace_chars: int
    line_count: int
    paragraph_count: int
    diagnostics: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def count_text_units(content: str) -> int:
    metric = measure_text(content, measurement_mode="text_units")
    return metric.text_units


def measure_text(content: str, *, measurement_mode: str = "text_units") -> TextMetricResult:
    text = str(content or "")
    normalized_mode = str(measurement_mode or "text_units").strip() or "text_units"
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))
    non_whitespace_chars = len(re.findall(r"\S", text))
    lines = text.splitlines()
    paragraph_count = len([part for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]) if text.strip() else 0
    diagnostics: dict[str, object] = {
        "authority": "platform.text_metric",
        "counter": "cjk_chars_plus_latin_words",
    }
    if normalized_mode in {"tokens", "hybrid"}:
        diagnostics["measurement_fallback"] = (
            "text_units_counter_used_until_token_meter_is_bound"
        )
    return TextMetricResult(
        measurement_mode=normalized_mode,
        text_units=cjk_chars + latin_words,
        cjk_chars=cjk_chars,
        latin_words=latin_words,
        char_count=len(text),
        non_whitespace_chars=non_whitespace_chars,
        line_count=len(lines),
        paragraph_count=paragraph_count,
        diagnostics=diagnostics,
    )


