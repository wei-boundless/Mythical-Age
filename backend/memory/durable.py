from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from structured_memory import (
    ExactMemoryMatch,
    ExtractionConfig,
    ExtractionScheduler,
    MemoryExtractor,
    MemoryManager,
    Message,
    find_exact_memory_matches,
)


class DurableMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.memory_manager = MemoryManager(base_dir / "durable_memory")
        self.extractor = MemoryExtractor(self.memory_manager)
        self.scheduler = ExtractionScheduler(
            self.extractor,
            config=ExtractionConfig(min_messages_between_runs=4),
        )

    def set_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.scheduler.on_saved = callback

    def submit_extraction(self, messages: list[Message]) -> int:
        return self.scheduler.submit(messages)

    def extract_durable_memories(self, messages: list[Message]) -> int:
        notes = self.extractor.save_extracted(messages)
        return len(notes)

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        self.memory_manager.ensure_index_consistent()
        sections: list[str] = []
        exact_matches = self.find_exact_matches(query, memory_intent, note_limit=note_limit)

        if exact_matches:
            sections.append("## Exact Durable Memory Matches")
            for match in exact_matches:
                sections.extend(["", *self._render_note_for_model(match)])

        exact_filenames = {match.filename for match in exact_matches}
        surfaced_relevant_notes = [
            note
            for note in (relevant_notes or [])
            if getattr(note, "filename", "") not in exact_filenames
        ]
        if surfaced_relevant_notes:
            sections.append("")
            sections.append("## Relevant Durable Memories")
            for note in surfaced_relevant_notes:
                sections.extend(["", *self._render_note_for_model(note)])

        notes = [] if surfaced_relevant_notes else [
            note
            for note in self.memory_manager.load_relevant_notes(limit=note_limit + len(exact_filenames))
            if getattr(note, "filename", "") not in exact_filenames
        ][:note_limit]
        if notes:
            sections.append("")
            sections.append("## Durable Memory Facts")
            for note in notes:
                sections.extend(["", *self._render_note_for_model(note)])

        return "\n".join(sections).strip()

    def _render_note_for_model(self, note: Any) -> list[str]:
        lines = [f"### {self._sanitize_for_model(getattr(note, 'title', '')).strip()}"]

        memory_class = self._sanitize_for_model(str(getattr(note, "memory_class", "") or "")).strip()
        memory_type = self._sanitize_for_model(str(getattr(note, "memory_type", "") or "")).strip()
        if memory_class or memory_type:
            lines.append(f"Kind: {memory_class or 'unknown'} / {memory_type or 'unknown'}")

        summary = self._sanitize_for_model(str(getattr(note, "summary", "") or "")).strip()
        canonical = self._sanitize_for_model(str(getattr(note, "canonical_statement", "") or "")).strip()
        detail = self._sanitize_for_model(
            str(getattr(note, "content", "") or getattr(note, "body", "") or "")
        ).strip()

        if canonical:
            lines.append(f"Canonical: {canonical}")
        elif summary:
            lines.append(f"Canonical: {summary}")

        if summary and summary != canonical:
            lines.append(f"Summary: {summary}")

        tags = [
            self._sanitize_for_model(str(tag)).strip()
            for tag in list(getattr(note, "tags", []) or [])
            if self._sanitize_for_model(str(tag)).strip()
        ]
        if tags:
            lines.append(f"Tags: {', '.join(tags[:6])}")

        retrieval_hints = [
            self._sanitize_for_model(str(hint)).strip()
            for hint in list(getattr(note, "retrieval_hints", []) or [])
            if self._sanitize_for_model(str(hint)).strip()
        ]
        if retrieval_hints:
            lines.append(f"Recall Hints: {', '.join(retrieval_hints[:6])}")

        detail_excerpt = self._detail_excerpt(detail, canonical=canonical, summary=summary)
        if detail_excerpt:
            lines.append(f"Details: {detail_excerpt}")

        return lines

    def _detail_excerpt(self, detail: str, *, canonical: str, summary: str) -> str:
        if not detail:
            return ""
        normalized = detail.replace("\r\n", "\n")
        useful_lines: list[str] = []
        for line in normalized.splitlines():
            stripped = line.strip(" -#*\t")
            if not stripped:
                continue
            if stripped in {canonical, summary}:
                continue
            if stripped.lower().startswith(("schema:", "source:", "created by:", "confidence:", "status:")):
                continue
            useful_lines.append(stripped)
        if not useful_lines:
            return ""
        excerpt = " ".join(useful_lines)
        return excerpt[:280].strip()

    def _sanitize_for_model(self, text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"`?[\w./\\:-]*durable_memory[\\/][^`\s]+`?", "长期记忆记录", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"`?[\w./\\:-]*session-memory[\\/][^`\s]+`?", "会话记录", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"`?[\w./\\-]+\.md`?", "长期记忆记录", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bMEMORY\.md\b", "长期记忆索引", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def prefetch_relevant_notes(
        self,
        query: str,
        memory_intent: Any | None = None,
        *,
        limit: int = 3,
    ) -> list[Any]:
        preferred_types = list(getattr(memory_intent, "preferred_types", []) or [])
        preferred_classes = list(getattr(memory_intent, "preferred_memory_classes", []) or [])
        if not preferred_classes:
            preferred_classes = self._infer_relevant_classes(query, preferred_types)
        return self.memory_manager.select_relevant_notes(
            query,
            preferred_types=preferred_types,
            preferred_classes=preferred_classes,
            limit=limit,
        )

    def find_exact_matches(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        note_limit: int,
    ) -> list[ExactMemoryMatch]:
        if (
            not query
            or memory_intent is None
            or getattr(memory_intent, "memory_read_mode", "none") != "durable_exact"
        ):
            return []
        return find_exact_memory_matches(
            self.memory_manager.root_dir,
            query,
            preferred_types=list(getattr(memory_intent, "preferred_types", []) or []),
            limit=min(3, note_limit),
        )

    def _infer_relevant_classes(
        self,
        query: str,
        preferred_types: list[str],
    ) -> list[str]:
        lowered = (query or "").lower()
        preferred: list[str] = []

        if any(item in {"user"} for item in preferred_types):
            preferred.append("preference")
        if any(item in {"project", "feedback", "reference"} for item in preferred_types):
            preferred.append("work")

        if any(marker in lowered for marker in ("喜欢", "偏好", "习惯", "风格", "要求", "默认")):
            preferred.append("preference")
        if any(marker in lowered for marker in ("项目", "架构", "流程", "工作流", "重点", "约定", "规范")):
            preferred.append("work")

        if not preferred:
            return ["work", "preference"]

        deduped: list[str] = []
        for item in preferred:
            if item not in deduped:
                deduped.append(item)
        return deduped
