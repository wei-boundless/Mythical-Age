from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Any, Callable

from memory.manifest_scan import MemoryHeader, format_memory_manifest, scan_memory_headers
from memory.read_agent import MemoryReadAgent
from memory.read_models import MemoryRecallRequest, MemoryRecallResult, MemoryRecallSelection
from memory.relevant_selector import RelevantMemorySelector
from structured_memory import (
    ExactMemoryMatch,
    ExtractionConfig,
    ExtractionScheduler,
    MemoryExtractor,
    MemoryManager,
    Message,
)


class DurableMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.memory_manager = MemoryManager(base_dir / "durable_memory")
        self.selector = RelevantMemorySelector(self.memory_manager)
        self.read_agent = MemoryReadAgent()
        self.extractor = MemoryExtractor(self.memory_manager)
        self.scheduler = ExtractionScheduler(
            self.extractor,
            config=ExtractionConfig(min_messages_between_runs=4),
        )
        self._runtime_governed = False

    def set_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.scheduler.on_saved = callback

    def set_message_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self.read_agent.set_message_invoker(callback)
        self.extractor.set_message_invoker(callback)

    def schedule_extraction(self, messages: list[Message]) -> int:
        return self.scheduler.submit(messages)

    def describe_extraction_runtime(self) -> dict[str, object]:
        return self.scheduler.describe_runtime_state()

    def commit_extraction(self, messages: list[Message]) -> int:
        notes = self.extractor.save_extracted(messages)
        return len(notes)

    def schedule_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        projected = self._project_context_state_messages(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
        return self.scheduler.submit(projected)

    def commit_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        projected = self._project_context_state_messages(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
        notes = self.extractor.save_extracted(projected)
        return len(notes)

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        recall_result = self.recall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            selected_notes=relevant_notes if relevant_notes else None,
        )
        return self._render_persistent_memory_block(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            recall_result=recall_result,
            relevant_notes=relevant_notes,
        )

    async def abuild_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        recall_result = await self.arecall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            selected_notes=relevant_notes if relevant_notes else None,
        )
        return self._render_persistent_memory_block(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            recall_result=recall_result,
            relevant_notes=relevant_notes,
        )

    def build_manifest_block(self, *, note_limit: int = 5) -> str:
        self._ensure_runtime_governance()
        self.memory_manager.ensure_index_consistent()
        manifest = format_memory_manifest(self._scan_headers(limit=max(note_limit, 5), runtime_visible_only=True))
        if not manifest:
            return ""
        return f"## Durable Memory Manifest\n{manifest}"

    def _render_persistent_memory_block(
        self,
        *,
        query: str | None,
        memory_intent: Any | None,
        note_limit: int,
        recall_result: MemoryRecallResult,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        self._ensure_runtime_governance()
        self.memory_manager.ensure_index_consistent()
        if not self._should_surface_durable_context(query, memory_intent, recall_result=recall_result):
            return ""
        sections: list[str] = []
        exact_matches = self.find_exact_matches(query, memory_intent, note_limit=note_limit)

        if exact_matches:
            sections.append("## Exact Durable Memory Matches")
            for match in exact_matches:
                sections.extend(["", *self._render_note_for_model(match)])

        exact_filenames = {match.filename for match in exact_matches}
        surfaced_relevant_notes = [
            note
            for note in self._notes_from_result_or_payload(recall_result, relevant_notes)
            if getattr(note, "filename", "") not in exact_filenames
        ]
        if surfaced_relevant_notes:
            sections.append("")
            sections.append("## Relevant Durable Memories")
            for note in surfaced_relevant_notes:
                sections.extend(["", *self._render_note_for_model(note)])

        if (
            not exact_matches
            and not surfaced_relevant_notes
            and recall_result.selection.manifest_only
        ):
            manifest_block = self.build_manifest_block(note_limit=note_limit)
            if manifest_block:
                sections.append("")
                sections.append(manifest_block)

        return "\n".join(section for section in sections if section is not None).strip()

    def build_recall_request(
        self,
        *,
        query: str | None,
        memory_intent: Any | None = None,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
    ) -> MemoryRecallRequest:
        intent_name = str(getattr(memory_intent, "intent", "") or "")
        explicit_mode = "inventory" if (
            bool(getattr(memory_intent, "explicit_read_inventory", False))
            or intent_name == "durable_memory_query"
        ) else "none"
        return MemoryRecallRequest(
            query=str(query or ""),
            main_context=dict(main_context or {}),
            task_summaries=list(task_summaries or []),
            session_summary=session_summary,
            manifest_headers=[self._header_to_dict(header) for header in self._scan_headers(runtime_visible_only=True)],
            recently_surfaced_note_ids=list(recently_surfaced_note_ids or []),
            explicit_memory_mode=explicit_mode,
            ignore_memory=bool(getattr(memory_intent, "ignore_memory", False)),
            recent_tools=list(recent_tools or []),
            preferred_types=list(getattr(memory_intent, "preferred_types", []) or []),
            preferred_memory_classes=list(getattr(memory_intent, "preferred_memory_classes", []) or []),
        )

    def recall_memories(
        self,
        *,
        query: str | None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
        selected_notes: list[Any] | None = None,
    ) -> MemoryRecallResult:
        self._ensure_runtime_governance()
        if not self._should_attempt_recall(query, memory_intent):
            return MemoryRecallResult(
                selection=MemoryRecallSelection(
                    should_recall=False,
                    reason="no_memory_signal",
                    confidence=1.0,
                    ignore_memory=bool(getattr(memory_intent, "ignore_memory", False)),
                ),
            )

        if selected_notes:
            note_dicts = [self._note_to_dict(note) for note in selected_notes]
            selected_headers = [self._header_dict_from_note_dict(note) for note in note_dicts]
            return MemoryRecallResult(
                selection=MemoryRecallSelection(
                    should_recall=bool(note_dicts),
                    selected_note_ids=[str(item.get("note_id", "") or "") for item in selected_headers],
                    reason="preselected_notes",
                    confidence=1.0 if note_dicts else 0.0,
                ),
                selected_headers=selected_headers,
                selected_notes=note_dicts,
                rendered_summary=self._render_selected_summary(note_dicts),
            )

        request = self.build_recall_request(
            query=query,
            memory_intent=memory_intent,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )
        if self._has_running_loop():
            selection = self.read_agent._select_with_fallback(request)
        else:
            selection = asyncio.run(self.read_agent.select_relevant(request))
        selected_headers = [
            header for header in request.manifest_headers
            if str(header.get("note_id", "") or "") in set(selection.selected_note_ids)
        ][:note_limit]
        note_dicts = self._load_selected_note_dicts(selected_headers, limit=note_limit)
        return MemoryRecallResult(
            selection=selection,
            selected_headers=selected_headers,
            selected_notes=note_dicts,
            rendered_summary=self._render_selected_summary(note_dicts),
        )

    async def arecall_memories(
        self,
        *,
        query: str | None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
        selected_notes: list[Any] | None = None,
    ) -> MemoryRecallResult:
        self._ensure_runtime_governance()
        if not self._should_attempt_recall(query, memory_intent):
            return MemoryRecallResult(
                selection=MemoryRecallSelection(
                    should_recall=False,
                    reason="no_memory_signal",
                    confidence=1.0,
                    ignore_memory=bool(getattr(memory_intent, "ignore_memory", False)),
                ),
            )

        if selected_notes:
            note_dicts = [self._note_to_dict(note) for note in selected_notes]
            selected_headers = [self._header_dict_from_note_dict(note) for note in note_dicts]
            return MemoryRecallResult(
                selection=MemoryRecallSelection(
                    should_recall=bool(note_dicts),
                    selected_note_ids=[str(item.get("note_id", "") or "") for item in selected_headers],
                    reason="preselected_notes",
                    confidence=1.0 if note_dicts else 0.0,
                ),
                selected_headers=selected_headers,
                selected_notes=note_dicts,
                rendered_summary=self._render_selected_summary(note_dicts),
            )

        request = self.build_recall_request(
            query=query,
            memory_intent=memory_intent,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )
        selection = await self.read_agent.select_relevant(request)
        selected_headers = [
            header for header in request.manifest_headers
            if str(header.get("note_id", "") or "") in set(selection.selected_note_ids)
        ][:note_limit]
        note_dicts = self._load_selected_note_dicts(selected_headers, limit=note_limit)
        return MemoryRecallResult(
            selection=selection,
            selected_headers=selected_headers,
            selected_notes=note_dicts,
            rendered_summary=self._render_selected_summary(note_dicts),
        )

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
        result = self.recall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=limit,
        )
        return [self._dict_to_note_proxy(item) for item in result.selected_notes[:limit]]

    def _should_prefetch_relevant_notes(
        self,
        query: str | None,
        memory_intent: Any | None,
    ) -> bool:
        if not str(query or "").strip():
            return False
        return self._should_attempt_recall(query, memory_intent)

    def _should_surface_durable_context(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        recall_result: MemoryRecallResult | None = None,
    ) -> bool:
        if not self._should_prefetch_relevant_notes(query, memory_intent):
            return False
        if recall_result is not None and recall_result.selected_notes:
            return True
        return bool(self.find_exact_matches(query, memory_intent, note_limit=3)) or (
            recall_result is not None and recall_result.selection.manifest_only
        )

    def _should_use_manifest_fallback(self, memory_intent: Any | None) -> bool:
        return bool(getattr(memory_intent, "explicit_read_inventory", False)) or str(
            getattr(memory_intent, "intent", "") or ""
        ) == "durable_memory_query"

    def find_exact_matches(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        note_limit: int,
    ) -> list[ExactMemoryMatch]:
        self._ensure_runtime_governance()
        return self.selector.select_exact(query, memory_intent, note_limit=note_limit)

    def _ensure_runtime_governance(self) -> None:
        if self._runtime_governed:
            return
        self.memory_manager.govern_note_store()
        self._runtime_governed = True

    def _has_running_loop(self) -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def _scan_headers(self, limit: int = 200, *, runtime_visible_only: bool = False) -> list[MemoryHeader]:
        headers = scan_memory_headers(self.memory_manager.root_dir, limit=limit)
        if not runtime_visible_only:
            return headers
        return [
            header
            for header in headers
            if header.eligible_for_injection and header.status == "active"
        ]

    def _should_attempt_recall(self, query: str | None, memory_intent: Any | None) -> bool:
        if not str(query or "").strip():
            return False
        if bool(getattr(memory_intent, "ignore_memory", False)):
            return False
        return True

    def _load_selected_note_dicts(
        self,
        selected_headers: list[dict[str, object]],
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        by_filename = {
            loaded.filename: loaded
            for loaded in self.memory_manager.list_notes()
        }
        selected: list[dict[str, object]] = []
        for header in selected_headers[:limit]:
            filename = str(header.get("filename", "") or "")
            loaded = by_filename.get(filename)
            if loaded is None:
                continue
            selected.append(self._note_to_dict(loaded, note_id=str(header.get("note_id", "") or "")))
        return selected

    def _render_selected_summary(self, note_dicts: list[dict[str, object]]) -> str:
        lines: list[str] = []
        for note in note_dicts:
            title = self._sanitize_for_model(str(note.get("title", "") or "")).strip()
            canonical = self._sanitize_for_model(str(note.get("canonical_statement", "") or "")).strip()
            summary = self._sanitize_for_model(str(note.get("summary", "") or "")).strip()
            detail = self._detail_excerpt(
                self._sanitize_for_model(str(note.get("content", "") or "")).strip(),
                canonical=canonical,
                summary=summary,
            )
            if not title:
                continue
            lines.append(f"### {title}")
            if canonical:
                lines.append(f"Canonical: {canonical}")
            if summary and summary != canonical:
                lines.append(f"Summary: {summary}")
            if detail:
                lines.append(f"Details: {detail}")
            lines.append("")
        return "\n".join(lines).strip()

    def _note_to_dict(self, note: Any, *, note_id: str = "") -> dict[str, object]:
        filename = str(getattr(note, "filename", "") or "")
        return {
            "note_id": note_id or filename.replace(".md", ""),
            "filename": filename,
            "title": str(getattr(note, "title", "") or ""),
            "summary": str(getattr(note, "summary", "") or ""),
            "canonical_statement": str(getattr(note, "canonical_statement", "") or ""),
            "content": str(getattr(note, "content", "") or getattr(note, "body", "") or ""),
            "memory_type": str(getattr(note, "memory_type", "") or ""),
            "memory_class": str(getattr(note, "memory_class", "") or ""),
            "confidence": str(getattr(note, "confidence", "") or ""),
            "status": str(getattr(note, "status", "") or ""),
            "retrieval_hints": list(getattr(note, "retrieval_hints", []) or []),
            "eligible_for_injection": str(getattr(note, "eligible_for_injection", "true") or "true").lower()
            not in {"false", "0", "no"},
        }

    def _header_dict_from_note_dict(self, note: dict[str, object]) -> dict[str, object]:
        return {
            "note_id": str(note.get("note_id", "") or ""),
            "filename": str(note.get("filename", "") or ""),
            "title": str(note.get("title", "") or ""),
            "description": str(note.get("summary", "") or note.get("canonical_statement", "") or ""),
            "memory_type": str(note.get("memory_type", "") or ""),
            "memory_class": str(note.get("memory_class", "") or ""),
            "status": str(note.get("status", "") or ""),
            "confidence": str(note.get("confidence", "") or ""),
            "eligible_for_injection": bool(note.get("eligible_for_injection", True)),
            "canonical_statement": str(note.get("canonical_statement", "") or ""),
            "retrieval_hints": list(note.get("retrieval_hints", []) or []),
        }

    def _header_to_dict(self, header: MemoryHeader) -> dict[str, object]:
        return {
            "note_id": header.note_id,
            "filename": header.filename,
            "file_path": header.file_path,
            "memory_type": header.memory_type,
            "memory_class": header.memory_class,
            "title": header.title,
            "description": header.description,
            "status": header.status,
            "confidence": header.confidence,
            "updated_at": header.updated_at,
            "retrieval_hints": list(header.retrieval_hints),
            "eligible_for_injection": header.eligible_for_injection,
            "canonical_statement": header.canonical_statement,
            "summary": header.summary,
        }

    def _notes_from_result_or_payload(
        self,
        result: MemoryRecallResult,
        payload: list[Any] | None,
    ) -> list[Any]:
        if payload is not None:
            return payload
        return [self._dict_to_note_proxy(item) for item in result.selected_notes]

    def _dict_to_note_proxy(self, payload: dict[str, object]) -> Any:
        class _NoteProxy:
            pass

        note = _NoteProxy()
        for key, value in payload.items():
            setattr(note, key, value)
        return note

    def _project_context_state_messages(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> list[Message]:
        active_goal = ""
        latest_correction = ""
        if isinstance(main_context, dict):
            active_goal = str(main_context.get("active_goal", "") or "").strip()
            latest_correction = str(main_context.get("latest_correction", "") or "").strip()
        else:
            active_goal = str(getattr(main_context, "active_goal", "") or "").strip()
            latest_correction = str(getattr(main_context, "latest_correction", "") or "").strip()

        label_parts = [item for item in [active_goal, latest_correction] if item]
        if not label_parts and task_summaries:
            first_summary = task_summaries[0]
            if isinstance(first_summary, dict):
                label_parts.append(str(first_summary.get("query", "") or "").strip())
            else:
                label_parts.append(str(getattr(first_summary, "query", "") or "").strip())
        if not label_parts and corrections:
            label_parts.extend(str(item).strip() for item in corrections if str(item).strip())

        signature_text = " | ".join(part for part in label_parts if part) or "session-state-projection"
        return [
            Message(
                role="assistant",
                content=signature_text,
                meta={
                    "session_id": session_id,
                    "projection": "durable_context_state",
                    "main_context": main_context,
                    "task_summaries": list(task_summaries or []),
                    "corrections": list(corrections or []),
                },
            )
        ]
