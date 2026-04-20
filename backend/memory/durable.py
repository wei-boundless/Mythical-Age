from __future__ import annotations

from pathlib import Path
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
                sections.extend(
                    [
                        "",
                        f"### {match.title}",
                        f"Schema: {getattr(match, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {match.memory_class}",
                        f"Type: {match.memory_type}",
                    ]
                )
                if match.summary:
                    sections.append(f"Summary: {match.summary}")
                if getattr(match, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(match, 'canonical_statement', '')}")
                if match.tags:
                    sections.append(f"Tags: {', '.join(match.tags)}")
                if getattr(match, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(match, 'retrieval_hints', []))}")
                if getattr(match, "confidence", ""):
                    sections.append(f"Confidence: {getattr(match, 'confidence', '')}")
                if getattr(match, "created_by", ""):
                    sections.append(f"Created By: {getattr(match, 'created_by', '')}")
                if getattr(match, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(match, 'source_message_excerpt', '')}")
                sections.append(match.body.strip())

        index_text = self.memory_manager.load_index().strip()
        if index_text:
            if sections:
                sections.append("")
            sections.extend(["## Persistent Memory Index", index_text])

        manifest = self.memory_manager.build_manifest(limit=note_limit).strip()
        if manifest:
            sections.extend(["", "## Persistent Memory Manifest", manifest])

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
                sections.extend(
                    [
                        "",
                        f"### {note.title}",
                        f"Schema: {getattr(note, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {note.memory_class}",
                        f"Type: {note.memory_type}",
                    ]
                )
                if note.summary:
                    sections.append(f"Summary: {note.summary}")
                if getattr(note, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(note, 'canonical_statement', '')}")
                if getattr(note, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(note, 'retrieval_hints', []))}")
                if getattr(note, "confidence", ""):
                    sections.append(f"Confidence: {getattr(note, 'confidence', '')}")
                if getattr(note, "created_by", ""):
                    sections.append(f"Created By: {getattr(note, 'created_by', '')}")
                if getattr(note, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(note, 'source_message_excerpt', '')}")
                sections.append(note.content.strip())

        if exact_matches:
            notes = [self.memory_manager.load_note(Path(match.filename).stem) for match in exact_matches]
            note_blocks = [note.strip() for note in notes if note]
            if note_blocks:
                sections.append("")
                sections.append("## Loaded Memory Notes")
                for block in note_blocks:
                    sections.append("")
                    sections.append(block)
                return "\n".join(sections).strip()

        notes = [] if surfaced_relevant_notes else self.memory_manager.load_relevant_notes(limit=note_limit)
        if notes:
            sections.append("")
            sections.append("## Loaded Memory Notes")
            for note in notes:
                sections.extend(
                    [
                        "",
                        f"### {note.title}",
                        f"Schema: {getattr(note, 'schema_version', 'durable-memory.v2')}",
                        f"Memory Class: {note.memory_class}",
                        f"Type: {note.memory_type}",
                    ]
                )
                if note.summary:
                    sections.append(f"Summary: {note.summary}")
                if getattr(note, "canonical_statement", ""):
                    sections.append(f"Canonical: {getattr(note, 'canonical_statement', '')}")
                if getattr(note, "retrieval_hints", []):
                    sections.append(f"Retrieval Hints: {', '.join(getattr(note, 'retrieval_hints', []))}")
                if getattr(note, "confidence", ""):
                    sections.append(f"Confidence: {getattr(note, 'confidence', '')}")
                if getattr(note, "created_by", ""):
                    sections.append(f"Created By: {getattr(note, 'created_by', '')}")
                if getattr(note, "source_message_excerpt", ""):
                    sections.append(f"Source: {getattr(note, 'source_message_excerpt', '')}")
                sections.append(note.content.strip())

        return "\n".join(sections).strip()

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

        if any(item in {"preference", "user"} for item in preferred_types):
            preferred.append("preference")
        if any(item in {"project", "workflow", "reference"} for item in preferred_types):
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
