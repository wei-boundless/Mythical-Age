from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Any, Callable

from .manifest_scan import MemoryHeader, format_memory_manifest, scan_memory_headers
from memory_system.layout import durable_memory_layout_from_backend_dir
from .read_agent import MemoryReadAgent
from .read_models import MemoryRecallRequest, MemoryRecallResult, MemoryRecallSelection
from memory_system.storage.exact_lookup import ExactMemoryMatch, find_exact_memory_matches
from memory_system.storage.memory_manager import MemoryManager


class DurableMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        layout = durable_memory_layout_from_backend_dir(base_dir)
        self.memory_manager = MemoryManager(layout.root_dir)
        self.read_agent = MemoryReadAgent()
        self._runtime_governed = False

    def set_saved_callback(self, callback: Callable[[int], None]) -> None:
        return None

    def set_message_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self.read_agent.set_message_invoker(callback)

    def describe_maintenance_runtime(self) -> dict[str, object]:
        return {
            "authority": "memory_system.maintenance_coordinator",
            "durable_memory_maintained_by": "agent:1",
            "model_understanding_required": True,
        }

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
            return self._result_from_preselected_notes(selected_notes)

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
        return self._result_from_selection(
            selection,
            manifest_headers=request.manifest_headers,
            note_limit=note_limit,
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
            return self._result_from_preselected_notes(selected_notes)

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
        return self._result_from_selection(
            selection,
            manifest_headers=request.manifest_headers,
            note_limit=note_limit,
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
        self._ensure_runtime_governance()
        if memory_intent is None:
            return []
        result = self.recall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=limit,
        )
        return [self._dict_to_note_proxy(item) for item in result.selected_notes[:limit]]

    def _should_surface_durable_context(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        recall_result: MemoryRecallResult | None = None,
    ) -> bool:
        if not self._should_attempt_recall(query, memory_intent):
            return False
        if recall_result is not None and recall_result.selected_notes:
            return True
        return bool(self.find_exact_matches(query, memory_intent, note_limit=3)) or (
            recall_result is not None and recall_result.selection.manifest_only
        )

    def find_exact_matches(
        self,
        query: str | None,
        memory_intent: Any | None,
        *,
        note_limit: int,
    ) -> list[ExactMemoryMatch]:
        self._ensure_runtime_governance()
        if (
            not query
            or memory_intent is None
            or bool(getattr(memory_intent, "ignore_memory", False))
        ):
            return []
        if not (
            bool(getattr(memory_intent, "explicit_read_inventory", False))
            or str(getattr(memory_intent, "intent", "") or "") == "memory_read_signal"
            or list(getattr(memory_intent, "preferred_types", []) or [])
            or list(getattr(memory_intent, "preferred_memory_classes", []) or [])
            or getattr(memory_intent, "memory_read_mode", "none") == "durable_exact"
        ):
            return []
        return find_exact_memory_matches(
            self.memory_manager.root_dir,
            query,
            preferred_types=list(getattr(memory_intent, "preferred_types", []) or []),
            limit=min(3, note_limit),
        )

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

    def _result_from_preselected_notes(
        self,
        selected_notes: list[Any],
    ) -> MemoryRecallResult:
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

    def _result_from_selection(
        self,
        selection: MemoryRecallSelection,
        *,
        manifest_headers: list[dict[str, object]],
        note_limit: int,
    ) -> MemoryRecallResult:
        selected_ids = {
            str(note_id or "")
            for note_id in selection.selected_note_ids
            if str(note_id or "")
        }
        selected_headers = [
            header
            for header in manifest_headers
            if str(header.get("note_id", "") or "") in selected_ids
        ][:note_limit]
        note_dicts = self._load_selected_note_dicts(selected_headers, limit=note_limit)
        return MemoryRecallResult(
            selection=selection,
            selected_headers=selected_headers,
            selected_notes=note_dicts,
            rendered_summary=self._render_selected_summary(note_dicts),
        )

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

