from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from memory_system.storage.models import Message


_HIGH_AUTHORITY_MARKERS = (
    "<tool_call",
    "<tool_result",
    "tool_call_id",
    "rehydration_plan",
    "evidence_ref",
    "artifact_ref",
    "content_ref",
    "file_path",
    "read_file",
    "git diff",
    "```",
)


@dataclass(frozen=True, slots=True)
class LowAuthorityTextCompression:
    applied: bool
    content: str
    reason: str = ""
    original_chars: int = 0
    compressed_chars: int = 0
    authority: str = "context_system.compaction.low_authority_text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "reason": self.reason,
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "authority": self.authority,
        }


def is_low_authority_natural_text_message(message: Message, *, token_count: int, threshold_tokens: int) -> bool:
    if message.role != "assistant":
        return False
    if token_count < max(1, int(threshold_tokens or 0)):
        return False
    meta = dict(message.meta or {})
    if str(meta.get("kind") or "") in {
        "compact_summary",
        "microcompact_stub",
        "low_authority_text_compressed",
        "tool_result",
        "code_structure",
        "file_evidence",
    }:
        return False
    content = str(message.content or "").strip()
    if not content:
        return False
    lowered = content.lower()
    if any(marker in lowered for marker in _HIGH_AUTHORITY_MARKERS):
        return False
    if _looks_like_structured_payload(content):
        return False
    if _looks_like_table_or_log(content):
        return False
    return _natural_language_ratio(content) >= 0.55


def compress_low_authority_text(content: str, *, target_chars: int) -> LowAuthorityTextCompression:
    normalized = _normalize_text(content)
    original_chars = len(str(content or ""))
    limit = max(120, int(target_chars or 0))
    if len(normalized) <= limit:
        return LowAuthorityTextCompression(
            applied=False,
            content=normalized,
            reason="under_target",
            original_chars=original_chars,
            compressed_chars=len(normalized),
        )
    sentences = _split_sentences(normalized)
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*kept, sentence]).strip()
        if kept and len(candidate) > limit:
            break
        kept.append(sentence)
        if len(kept) >= 4:
            break
    summary = " ".join(kept).strip() or normalized[:limit].rstrip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip()
    if len(summary) >= len(normalized):
        return LowAuthorityTextCompression(
            applied=False,
            content=normalized,
            reason="not_smaller",
            original_chars=original_chars,
            compressed_chars=len(normalized),
        )
    return LowAuthorityTextCompression(
        applied=True,
        content=summary,
        reason="assistant_natural_history",
        original_chars=original_chars,
        compressed_chars=len(summary),
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _split_sentences(value: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?\.])\s+", value)
    return [part.strip() for part in parts if part.strip()]


def _looks_like_structured_payload(content: str) -> bool:
    braces = content.count("{") + content.count("}") + content.count("[") + content.count("]")
    if braces >= 8:
        return True
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) >= 6 and sum(1 for line in lines if ":" in line or "=" in line) >= 4:
        return True
    return False


def _looks_like_table_or_log(content: str) -> bool:
    lines = [line for line in content.splitlines() if line.strip()]
    if sum(1 for line in lines if line.count("|") >= 2) >= 2:
        return True
    if sum(1 for line in lines if re.match(r"^\s*(debug|info|warn|error|trace)\b", line, re.IGNORECASE)) >= 2:
        return True
    return False


def _natural_language_ratio(content: str) -> float:
    text = str(content or "")
    if not text:
        return 0.0
    natural = sum(1 for char in text if char.isalpha() or "\u4e00" <= char <= "\u9fff")
    structural = sum(1 for char in text if char in "{}[]<>|`=;$")
    total = max(1, len(text))
    return max(0.0, (natural - structural * 2) / total)
