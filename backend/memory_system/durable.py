from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .manifest_scan import MemoryHeader, format_memory_manifest, scan_memory_headers
from memory_system.layout import durable_memory_layout_from_backend_dir
from memory_system.storage.memory_manager import MemoryManager


MessageInvoker = Callable[[list[dict[str, str]]], Any]


class MemoryRecallRequest(BaseModel):
    query: str = ""
    main_context: dict[str, object] = Field(default_factory=dict)
    task_summaries: list[dict[str, object]] = Field(default_factory=list)
    session_summary: str = ""
    manifest_headers: list[dict[str, object]] = Field(default_factory=list)
    recently_surfaced_note_ids: list[str] = Field(default_factory=list)
    explicit_memory_mode: str = "none"
    ignore_memory: bool = False
    recent_tools: list[str] = Field(default_factory=list)
    preferred_types: list[str] = Field(default_factory=list)
    preferred_memory_classes: list[str] = Field(default_factory=list)


class MemoryRecallSelection(BaseModel):
    should_recall: bool = False
    selected_note_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    needs_verification: bool = False
    manifest_only: bool = False
    ignore_memory: bool = False


class MemoryRecallResult(BaseModel):
    selection: MemoryRecallSelection = Field(default_factory=MemoryRecallSelection)
    selected_headers: list[dict[str, object]] = Field(default_factory=list)
    selected_notes: list[dict[str, object]] = Field(default_factory=list)
    rendered_summary: str = ""


class MemoryReadAgent:
    def __init__(self, *, message_invoker: MessageInvoker | None = None) -> None:
        self._message_invoker = message_invoker

    def set_message_invoker(self, message_invoker: MessageInvoker | None) -> None:
        self._message_invoker = message_invoker

    async def select_relevant(self, request: MemoryRecallRequest) -> MemoryRecallSelection:
        if request.ignore_memory:
            return MemoryRecallSelection(
                should_recall=False,
                reason="ignore_memory",
                confidence=1.0,
                ignore_memory=True,
            )

        headers = list(request.manifest_headers)
        if not headers:
            return MemoryRecallSelection(
                should_recall=False,
                reason="no_manifest_headers",
                confidence=1.0,
            )

        if request.explicit_memory_mode == "inventory":
            return MemoryRecallSelection(
                should_recall=False,
                reason="explicit_memory_inventory",
                confidence=1.0,
                manifest_only=True,
            )

        if self._message_invoker is None:
            return MemoryRecallSelection(
                should_recall=False,
                reason="no_durable_memory_selector_configured",
                confidence=1.0,
            )

        selection = await self._select_with_model(request)
        if selection is not None:
            return selection
        return MemoryRecallSelection(
            should_recall=False,
            reason="durable_memory_selector_failed",
            confidence=1.0,
        )

    async def _select_with_model(self, request: MemoryRecallRequest) -> MemoryRecallSelection | None:
        assert self._message_invoker is not None
        headers = request.manifest_headers[:80]
        manifest = "\n".join(
            f"- {header.get('note_id', '')} | {header.get('memory_type', '')}/{header.get('memory_class', '')} | "
            f"{header.get('title', '')} | {header.get('description', '')}"
            for header in headers
        )
        system_prompt = (
            "You are the durable memory recall subagent. "
            "Given a user query, main working context, and a manifest of available durable memory headers, "
            "select only the memory note ids that are clearly useful for answering the current query. "
            "Be strict. If nothing is clearly useful, return an empty selection. "
            "Never answer the user directly. Return JSON with keys: should_recall, selected_note_ids, reason, confidence, "
            "needs_verification, manifest_only, ignore_memory."
        )
        user_prompt = json.dumps(
            {
                "query": request.query,
                "main_context": request.main_context,
                "task_summaries": request.task_summaries[:4],
                "session_summary": request.session_summary[:600],
                "explicit_memory_mode": request.explicit_memory_mode,
                "ignore_memory": request.ignore_memory,
                "preferred_types": request.preferred_types,
                "preferred_memory_classes": request.preferred_memory_classes,
                "recent_tools": request.recent_tools[:8],
                "recently_surfaced_note_ids": request.recently_surfaced_note_ids[:12],
                "manifest": manifest,
            },
            ensure_ascii=False,
        )
        try:
            response = await self._message_invoker(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            content = getattr(response, "content", "")
            if isinstance(content, list):
                text = "".join(
                    str(block.get("text", ""))
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                text = str(content or "")
            payload = self._extract_json(text)
            selection = MemoryRecallSelection.model_validate(payload)
            valid_ids = {str(header.get("note_id", "") or "") for header in request.manifest_headers}
            selection.selected_note_ids = [
                note_id for note_id in selection.selected_note_ids if note_id in valid_ids
            ][:5]
            if not selection.selected_note_ids and not selection.manifest_only:
                selection.should_recall = False
            return selection
        except Exception:
            return None

    def _extract_json(self, text: str) -> dict[str, object]:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise ValueError("No JSON object found in model response")


class DurableMemoryLayer:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        layout = durable_memory_layout_from_backend_dir(base_dir)
        self.memory_manager = MemoryManager(layout.root_dir)
        self.read_agent = MemoryReadAgent()
        self._runtime_governed = False

    def set_message_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self.read_agent.set_message_invoker(callback)

    def describe_maintenance_runtime(self) -> dict[str, object]:
        return {
            "authority": "memory_system.maintenance_coordinator",
            "durable_memory_maintained_by": "agent:1",
            "model_turn_decision_required": True,
        }

    def build_manifest_block(self, *, note_limit: int = 5) -> str:
        self._ensure_runtime_governance()
        self.memory_manager.ensure_index_consistent()
        manifest = format_memory_manifest(self._scan_headers(limit=max(note_limit, 5), runtime_visible_only=True))
        if not manifest:
            return ""
        return f"## Durable Memory Manifest\n{manifest}"

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
            selection = MemoryRecallSelection(
                should_recall=False,
                reason="sync_recall_inside_running_loop_requires_preselected_notes_or_async_call",
                confidence=1.0,
            )
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
            title = str(note.get("title", "") or "").strip()
            canonical = str(note.get("canonical_statement", "") or "").strip()
            summary = str(note.get("summary", "") or "").strip()
            detail = self._detail_excerpt(
                str(note.get("content", "") or "").strip(),
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
        slug = str(getattr(note, "slug", "") or "")
        return {
            "note_id": note_id or slug or filename.replace(".md", ""),
            "filename": filename or (f"{slug}.md" if slug else ""),
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



