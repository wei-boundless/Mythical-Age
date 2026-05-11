from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolRepetitionGuard:
    max_repeated_calls: int = 2
    _seen: dict[str, int] = field(default_factory=dict)

    def record(self, tool_name: str, tool_args: dict[str, Any] | None) -> bool:
        signature = _tool_signature(tool_name, tool_args or {})
        if not signature:
            return False
        count = self._seen.get(signature, 0) + 1
        self._seen[signature] = count
        return count > self.max_repeated_calls


def _tool_signature(tool_name: str, tool_args: dict[str, Any]) -> str:
    name = str(tool_name or "").strip()
    if not name:
        return ""
    normalized_args = _normalize_args(tool_args)
    return f"{name}:{json.dumps(normalized_args, ensure_ascii=False, sort_keys=True)}"


def _normalize_args(tool_args: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in sorted(dict(tool_args or {}).items()):
        if key in {"max_chunks", "top_k", "limit"}:
            continue
        normalized[str(key)] = _normalize_value(value)
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.replace("\\", "/").lower().split())
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value
