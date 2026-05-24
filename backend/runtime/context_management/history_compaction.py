from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .budget import estimate_text_bytes
from .tool_result_storage import DEFAULT_PREVIEW_SIZE_BYTES, ToolResultStore


def microcompact_history(
    history: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    root_dir: Path,
    session_id: str,
    task_id: str,
    keep_last_messages: int = 6,
    field_limit_bytes: int = 6000,
    preview_size_bytes: int = DEFAULT_PREVIEW_SIZE_BYTES,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    normalized = _normalize_history(history)
    if not normalized:
        return [], {"applied": False, "mode": "history_microcompact", "compacted_message_count": 0, "content_replacements": []}
    keep_tail = max(0, int(keep_last_messages or 0))
    split_at = max(0, len(normalized) - keep_tail)
    older = normalized[:split_at]
    tail = normalized[split_at:]
    store = ToolResultStore(
        root_dir,
        run_id=f"{session_id or 'session'}-{task_id or 'task'}",
        namespace="runtime_context",
    )
    compacted: list[dict[str, str]] = []
    replacements: list[dict[str, Any]] = []
    compacted_count = 0
    for index, message in enumerate(older, start=1):
        content = str(message.get("content") or "")
        if not _should_compact_message(message, field_limit_bytes=field_limit_bytes):
            compacted.append(message)
            continue
        payload = {"message": {"role": message.get("role") or "user", "content": content}}
        budgeted, content_replacements = store.apply_budget(
            payload,
            field_limit_bytes=field_limit_bytes,
            preview_size_bytes=preview_size_bytes,
        )
        replacement_text = str(dict(budgeted.get("message") or {}).get("content") or "")
        if not replacement_text:
            replacement_text = _fallback_summary(message, index=index, original_bytes=estimate_text_bytes(content))
        compacted.append({"role": str(message.get("role") or "user"), "content": replacement_text})
        replacements.extend(item.to_dict() for item in content_replacements)
        compacted_count += 1
    diagnostics = {
        "applied": compacted_count > 0,
        "mode": "history_microcompact",
        "compacted_message_count": compacted_count,
        "content_replacements": replacements,
        "older_message_count": len(older),
        "tail_message_count": len(tail),
    }
    return [*compacted, *tail], diagnostics


def _normalize_history(history: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in list(history or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user")
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        messages.append({"role": role, "content": content})
    return messages


def _should_compact_message(message: dict[str, str], *, field_limit_bytes: int) -> bool:
    content = str(message.get("content") or "")
    if estimate_text_bytes(content) > field_limit_bytes:
        return True
    lowered = content.lower()
    return any(token in lowered for token in ("agent_evidence_packet", "web_payload", "tool_result", "<persisted-output>")) and estimate_text_bytes(content) > max(1500, field_limit_bytes // 2)


def _fallback_summary(message: dict[str, str], *, index: int, original_bytes: int) -> str:
    preview = str(message.get("content") or "")[:500].strip()
    payload = {
        "compacted_history_message": index,
        "role": str(message.get("role") or ""),
        "original_bytes": original_bytes,
        "preview": preview,
    }
    return "Compacted prior context:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
