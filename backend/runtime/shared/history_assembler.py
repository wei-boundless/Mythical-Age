from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


COMPRESSED_CONTEXT_PREFIX = "[Compressed session context]"


@dataclass(frozen=True, slots=True)
class HistoryAssemblyResult:
    model_history: tuple[dict[str, str], ...]
    compressed_context: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_history": [dict(item) for item in self.model_history],
            "compressed_context": self.compressed_context,
            "diagnostics": dict(self.diagnostics),
        }


def assemble_runtime_history(
    *,
    history: list[dict[str, Any]] | None,
    compressed_context: str | None = None,
) -> HistoryAssemblyResult:
    normalized = _normalize_history(history or [])
    compressed = str(compressed_context or "").strip()
    assembled: list[dict[str, str]] = []
    assembled.extend(normalized)
    return HistoryAssemblyResult(
        model_history=tuple(assembled),
        compressed_context=compressed,
        diagnostics={
            "raw_history_message_count": len(normalized),
            "assembled_history_message_count": len(assembled),
            "active_history_message_count": len(assembled),
            "compressed_context_included": bool(compressed),
            "authority": "runtime.history_assembly",
        },
    )


def _normalize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(dict(item or {}).get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(dict(item or {}).get("content") or "")
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


