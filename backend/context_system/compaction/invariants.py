from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from memory_system.storage.models import Message


_TOOL_CALL_ID_RE = re.compile(r"(?:tool_call_id|call_id|id)\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", re.IGNORECASE)
_TOOL_RESULT_ID_RE = re.compile(r"(?:tool_call_id|call_id)\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CompactionInvariantReport:
    ok: bool
    reasons: tuple[str, ...] = ()
    current_user_message_preserved: bool = True
    orphan_tool_result_ids: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "context_system.compaction.api_invariant_normalizer"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["orphan_tool_result_ids"] = list(self.orphan_tool_result_ids)
        return payload


def validate_compacted_messages(
    before: list[Message] | tuple[Message, ...],
    after: list[Message] | tuple[Message, ...],
) -> CompactionInvariantReport:
    before_messages = list(before or [])
    after_messages = list(after or [])
    reasons: list[str] = []

    current_user = _last_user_message(before_messages)
    current_user_preserved = True
    if current_user is not None:
        current_user_preserved = any(
            message.role == "user" and message.content == current_user.content
            for message in after_messages
        )
        if not current_user_preserved:
            reasons.append("current_user_message_missing_after_compaction")

    tool_call_ids = _tool_call_ids(after_messages)
    tool_result_ids = _tool_result_ids(after_messages)
    orphan_ids = tuple(sorted(tool_result_ids - tool_call_ids))
    if orphan_ids:
        reasons.append("orphan_tool_result_after_compaction")

    return CompactionInvariantReport(
        ok=not reasons,
        reasons=tuple(reasons),
        current_user_message_preserved=current_user_preserved,
        orphan_tool_result_ids=orphan_ids,
        diagnostics={
            "before_message_count": len(before_messages),
            "after_message_count": len(after_messages),
            "tool_call_ids": sorted(tool_call_ids),
            "tool_result_ids": sorted(tool_result_ids),
        },
    )


def _last_user_message(messages: list[Message]) -> Message | None:
    for message in reversed(messages):
        if message.role == "user":
            return message
    return None


def _tool_call_ids(messages: list[Message]) -> set[str]:
    result: set[str] = set()
    for message in messages:
        meta = dict(message.meta or {})
        if isinstance(meta.get("tool_calls"), list):
            for item in meta.get("tool_calls") or []:
                if isinstance(item, dict) and str(item.get("id") or "").strip():
                    result.add(str(item.get("id")).strip())
        for key in ("tool_call_id", "call_id"):
            if str(meta.get(key) or "").strip() and message.role == "assistant":
                result.add(str(meta.get(key)).strip())
        if message.role == "assistant":
            result.update(_TOOL_CALL_ID_RE.findall(str(message.content or "")))
    return result


def _tool_result_ids(messages: list[Message]) -> set[str]:
    result: set[str] = set()
    for message in messages:
        meta = dict(message.meta or {})
        for key in ("tool_call_id", "call_id"):
            if str(meta.get(key) or "").strip() and message.role in {"tool", "tool_result"}:
                result.add(str(meta.get(key)).strip())
        if message.role in {"tool", "tool_result"}:
            result.update(_TOOL_RESULT_ID_RE.findall(str(message.content or "")))
    return result
