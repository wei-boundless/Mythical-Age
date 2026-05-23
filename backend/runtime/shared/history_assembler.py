from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


COMPRESSED_CONTEXT_PREFIX = "[Compressed session context]"
DEFAULT_RECENT_MESSAGE_LIMIT = 12


@dataclass(frozen=True, slots=True)
class HistoryAssemblyResult:
    model_history: tuple[dict[str, str], ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_history": [dict(item) for item in self.model_history],
            "diagnostics": dict(self.diagnostics),
        }


def assemble_runtime_history(
    *,
    history: list[dict[str, Any]] | None,
    compressed_context: str | None = None,
    recent_message_limit: int = DEFAULT_RECENT_MESSAGE_LIMIT,
) -> HistoryAssemblyResult:
    normalized = _normalize_history(history or [])
    compressed = str(compressed_context or "").strip()
    limit = max(0, int(recent_message_limit or 0))
    recent = normalized[-limit:] if limit else []
    assembled: list[dict[str, str]] = []
    if compressed:
        assembled.append(
            {
                "role": "assistant",
                "content": f"{COMPRESSED_CONTEXT_PREFIX}\n{compressed}",
            }
        )
    assembled.extend(recent)
    return HistoryAssemblyResult(
        model_history=tuple(assembled),
        diagnostics={
            "raw_history_message_count": len(normalized),
            "assembled_history_message_count": len(assembled),
            "recent_history_message_count": len(recent),
            "compressed_context_included": bool(compressed),
            "dropped_history_message_count": max(len(normalized) - len(recent), 0),
            "recent_message_limit": limit,
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
