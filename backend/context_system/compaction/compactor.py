from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from structured_memory.models import Message
from structured_memory.session_memory import SessionMemoryManager
from token_accounting import count_text_tokens


@dataclass(slots=True)
class CompactResult:
    did_compact: bool
    messages: list[Message]
    summary_message: Message | None = None
    pressure_level: Literal["normal", "warning", "microcompact", "full_compact"] = "normal"
    strategy: str = "none"
    estimated_tokens_before: int = 0
    estimated_tokens_after: int = 0
    original_message_count: int = 0
    compacted_message_count: int = 0
    did_microcompact: bool = False
    did_full_compact: bool = False
    replaced_message_count: int = 0
    preserved_recent_count: int = 0


class ContextCompactor:
    """Applies token-aware runtime compaction using session memory as working state."""

    def __init__(
        self,
        session_memory_manager: SessionMemoryManager,
        max_messages: int = 18,
        keep_recent_messages: int = 8,
        effective_history_token_budget: int = 6_000,
        warning_ratio: float = 0.65,
        microcompact_ratio: float = 0.82,
        full_compact_ratio: float = 0.94,
        bulky_message_token_threshold: int = 220,
        full_compact_recent_messages: int = 6,
    ) -> None:
        if keep_recent_messages >= max_messages:
            raise ValueError("keep_recent_messages must be smaller than max_messages")
        if full_compact_recent_messages <= 0:
            raise ValueError("full_compact_recent_messages must be positive")
        self.session_memory_manager = session_memory_manager
        self.max_messages = max_messages
        self.keep_recent_messages = keep_recent_messages
        self.full_compact_recent_messages = min(full_compact_recent_messages, keep_recent_messages)
        self.effective_history_token_budget = effective_history_token_budget
        self.warning_tokens = max(1, int(effective_history_token_budget * warning_ratio))
        self.microcompact_tokens = max(self.warning_tokens + 1, int(effective_history_token_budget * microcompact_ratio))
        self.full_compact_tokens = max(self.microcompact_tokens + 1, int(effective_history_token_budget * full_compact_ratio))
        self.bulky_message_token_threshold = bulky_message_token_threshold

    def count_tokens(self, text: str) -> int:
        return self._count_tokens(text)

    def message_tokens(self, message: Message) -> int:
        return self._message_tokens(message)

    def conversation_tokens(self, messages: list[Message]) -> int:
        return self._conversation_tokens(messages)

    def pressure_level(
        self,
        tokens: int,
        message_count: int,
    ) -> Literal["normal", "warning", "microcompact", "full_compact"]:
        return self._pressure_level(tokens, message_count)

    def _count_tokens(self, text: str) -> int:
        return count_text_tokens(text)

    def _message_tokens(self, message: Message) -> int:
        return self._count_tokens(message.content)

    def _conversation_tokens(self, messages: list[Message]) -> int:
        return sum(self._message_tokens(message) for message in messages)

    def _pressure_level(self, tokens: int, message_count: int) -> Literal["normal", "warning", "microcompact", "full_compact"]:
        if tokens >= self.full_compact_tokens or message_count > self.max_messages:
            return "full_compact"
        if tokens >= self.microcompact_tokens:
            return "microcompact"
        if tokens >= self.warning_tokens:
            return "warning"
        return "normal"

    def _looks_like_bulk_output(self, message: Message) -> bool:
        if message.role != "assistant":
            return False
        content = message.content.strip()
        lowered = content.lower()
        if self._message_tokens(message) < self.bulky_message_token_threshold:
            return False
        if "[rag retrieved context]" in lowered:
            return True
        markers = (
            "数据源：",
            "总行数：",
            "总商品数：",
            "列名：",
            "前 10 项",
            "结果（前 10 项）",
            "Extracted chunks:",
            "Rows:",
            "Sheet:",
            "Source:",
            "Modalities:",
            "tool call",
            "tool calls",
            "工具调用",
        )
        if any(marker.lower() in lowered for marker in markers):
            return True
        if content.count("|") >= 10:
            return True
        if content.count("{") + content.count("[") >= 8:
            return True
        if len(re.findall(r"https?://", lowered)) >= 2:
            return True
        return False

    def _microcompact_stub(self, message: Message) -> Message:
        content = message.content.strip()
        lowered = content.lower()
        label = "assistant output"
        if "[rag retrieved context]" in lowered:
            label = "retrieval context"
        elif any(
            token in lowered
            for token in ("数据源：", "总商品数：", "总行数：", "前 10 项", "结果（前 10 项）", "工具调用")
        ):
            label = "structured analysis output"
        elif "source:" in lowered or "http" in lowered:
            label = "source-heavy output"
        preview = re.sub(r"\s+", " ", content)[:160].strip()
        return Message(
            role=message.role,
            content=(
                f"[Earlier {label} was microcompacted to reduce context pressure. "
                f"Use session memory for the working state. Preview: {preview}]"
            ),
            meta={**message.meta, "kind": "microcompact_stub"},
        )

    def _apply_microcompact(self, messages: list[Message]) -> tuple[list[Message], int]:
        if len(messages) <= self.keep_recent_messages:
            return list(messages), 0

        boundary = len(messages) - self.keep_recent_messages
        compacted: list[Message] = []
        replaced = 0
        for index, message in enumerate(messages):
            if index < boundary and self._looks_like_bulk_output(message):
                compacted.append(self._microcompact_stub(message))
                replaced += 1
            else:
                compacted.append(message)
        return compacted, replaced

    def _build_full_compact_messages(
        self,
        messages: list[Message],
        *,
        max_chars_per_section: int,
        recent_count: int,
        summary_content: str | None = None,
    ) -> tuple[list[Message], Message]:
        recent = self._select_recent_core_messages(messages, recent_count)
        session_summary = (
            summary_content.strip()
            if summary_content is not None
            else self.session_memory_manager.compact_view(max_chars_per_section=max_chars_per_section).strip()
        )
        summary_message = Message(
            role="system",
            content=(
                "Conversation history was compacted because runtime context pressure became high. "
                "Treat the following session-memory summary as the authoritative working context.\n\n"
                f"{session_summary}"
            ),
            meta={"kind": "compact_summary"},
        )
        return [summary_message, *recent], summary_message

    def apply_strategy(
        self,
        messages: list[Message],
        *,
        pressure_level: Literal["normal", "warning", "microcompact", "full_compact"],
        summary_content: str | None = None,
        summary_source_content: str | None = None,
    ) -> CompactResult:
        working = list(messages)
        tokens_before = self._conversation_tokens(working)

        if pressure_level in {"normal", "warning"}:
            return CompactResult(
                did_compact=False,
                messages=working,
                pressure_level=pressure_level,
                strategy="warning_only" if pressure_level == "warning" else "none",
                estimated_tokens_before=tokens_before,
                estimated_tokens_after=tokens_before,
                original_message_count=len(messages),
                compacted_message_count=len(working),
                preserved_recent_count=min(len(working), self.keep_recent_messages),
            )

        micro_messages, replaced = self._apply_microcompact(working)
        tokens_after_micro = self._conversation_tokens(micro_messages)
        post_micro_level = self._pressure_level(tokens_after_micro, len(micro_messages))
        if pressure_level == "microcompact" or post_micro_level in {"normal", "warning", "microcompact"}:
            return CompactResult(
                did_compact=replaced > 0,
                messages=micro_messages,
                pressure_level="microcompact",
                strategy="microcompact",
                estimated_tokens_before=tokens_before,
                estimated_tokens_after=tokens_after_micro,
                original_message_count=len(messages),
                compacted_message_count=len(micro_messages),
                did_microcompact=replaced > 0,
                did_full_compact=False,
                replaced_message_count=replaced,
                preserved_recent_count=min(len(micro_messages), self.keep_recent_messages),
            )

        summary_message: Message | None = None
        compacted = micro_messages
        tokens_after = tokens_after_micro
        recent_count = self.full_compact_recent_messages
        max_chars_per_section = 420
        resolved_summary_content = summary_content
        while True:
            if summary_source_content is not None:
                resolved_summary_content = self.session_memory_manager.compact_view(
                    content=summary_source_content,
                    max_chars_per_section=max_chars_per_section,
                ).strip()
            compacted, summary_message = self._build_full_compact_messages(
                micro_messages,
                max_chars_per_section=max_chars_per_section,
                recent_count=recent_count,
                summary_content=resolved_summary_content,
            )
            tokens_after = self._conversation_tokens(compacted)
            if tokens_after <= self.effective_history_token_budget:
                break
            if recent_count > 3:
                recent_count -= 1
                continue
            if max_chars_per_section > 240:
                max_chars_per_section = 240
                if summary_source_content is None and summary_content is None:
                    resolved_summary_content = self.session_memory_manager.compact_view(
                        max_chars_per_section=max_chars_per_section,
                    ).strip()
                continue
            break

        if tokens_after >= tokens_before and summary_message is not None:
            fallback_summary = resolved_summary_content
            if fallback_summary is None:
                if summary_source_content is not None:
                    fallback_summary = self.session_memory_manager.compact_view(
                        content=summary_source_content,
                        max_chars_per_section=160,
                    ).strip()
                else:
                    fallback_summary = self.session_memory_manager.compact_view(max_chars_per_section=160).strip()
            compacted, summary_message = self._build_full_compact_messages(
                micro_messages,
                max_chars_per_section=160,
                recent_count=min(2, len(micro_messages)),
                summary_content=fallback_summary,
            )
            tokens_after = self._conversation_tokens(compacted)

        return CompactResult(
            did_compact=True,
            messages=compacted,
            summary_message=summary_message,
            pressure_level="full_compact",
            strategy="full_compact",
            estimated_tokens_before=tokens_before,
            estimated_tokens_after=tokens_after,
            original_message_count=len(messages),
            compacted_message_count=len(compacted),
            did_microcompact=replaced > 0,
            did_full_compact=True,
            replaced_message_count=replaced,
            preserved_recent_count=min(len(micro_messages), recent_count),
        )

    def _select_recent_core_messages(self, messages: list[Message], recent_count: int) -> list[Message]:
        if recent_count <= 0:
            return []
        tail = list(messages)
        recent: list[Message] = []
        for message in reversed(tail):
            if len(recent) >= recent_count:
                break
            if not self._looks_like_bulk_output(message):
                recent.append(message)
        if len(recent) < recent_count:
            for message in reversed(tail):
                if len(recent) >= recent_count:
                    break
                if message in recent:
                    continue
                recent.append(message)
        recent.reverse()
        return recent

    def maybe_compact(self, messages: list[Message]) -> CompactResult:
        working = list(messages)
        tokens_before = self._conversation_tokens(working)
        level = self._pressure_level(tokens_before, len(working))
        return self.apply_strategy(working, pressure_level=level)
