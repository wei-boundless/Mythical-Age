from __future__ import annotations

import asyncio

from memory_system.admission_policy import DurableAdmissionPolicy
from memory_system.manifest_scan import scan_memory_headers
from memory_system.mutation_planner import DurableMutationPlanner
from memory_system.store_writer import DurableStoreWriter
from memory_system.write_agent import DurableWriteExtractorAgent
from memory_system.write_models import DurableExtractionBundle
from understanding.memory_policy import evaluate_memory_write

from .memory_manager import MemoryManager
from .models import MemoryNote, Message
from .text_utils import normalize_storage_text


class MemoryExtractor:
    """Heuristic extractor for durable memories.

    Replace or wrap this with an LLM call if you want smarter extraction.
    """

    EXPLICIT_WRITE_MARKERS = (
        "记住",
        "记一下",
        "别忘了",
        "记到长期记忆",
        "remember",
        "remember that",
        "don't forget",
    )

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager
        self.write_agent = DurableWriteExtractorAgent()
        self.admission_policy = DurableAdmissionPolicy()
        self.mutation_planner = DurableMutationPlanner()
        self.store_writer = DurableStoreWriter(memory_manager)

    def set_message_invoker(self, callback) -> None:
        self.write_agent.set_message_invoker(callback)

    def extract(self, messages: list[Message]) -> list[MemoryNote]:
        extracted = self._extract_from_projection_messages(messages)
        if extracted:
            return self._dedupe(extracted)
        return self._dedupe(self._extract_from_explicit_messages(messages))

    async def aextract(self, messages: list[Message]) -> list[MemoryNote]:
        extracted = await self._aextract_from_projection_messages(messages)
        if extracted:
            return self._dedupe(extracted)
        return self._dedupe(await self._aextract_from_explicit_messages(messages))

    def save_extracted(self, messages: list[Message]) -> list[MemoryNote]:
        notes = self.extract(messages)
        return self.store_writer.save_notes(notes)

    async def asave_extracted(self, messages: list[Message]) -> list[MemoryNote]:
        notes = await self.aextract(messages)
        return self.store_writer.save_notes(notes)

    def _make_title(self, text: str) -> str:
        compact = " ".join(text.strip().split())
        if not compact:
            return "User Memory"
        if any("\u4e00" <= char <= "\u9fff" for char in compact):
            return compact[:24]
        stripped = compact
        for prefix in (
            "remember that ",
            "remember ",
            "please remember that ",
            "please remember ",
            "don't forget that ",
            "do not forget that ",
        ):
            if stripped.lower().startswith(prefix):
                stripped = stripped[len(prefix) :].strip()
                break
        words = stripped.split()
        return " ".join(words[:8]) or "User Memory"

    def _summarize(self, text: str) -> str:
        compact = " ".join(text.strip().split())
        return compact[:100] + ("..." if len(compact) > 100 else "")

    def _merge_tags(self, primary: list[str], extra: list[str]) -> list[str]:
        merged: list[str] = []
        for tag in primary + extra:
            normalized = normalize_storage_text(tag)
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    def _tags(self, text: str) -> list[str]:
        lowered = text.lower()
        tags: list[str] = []
        tag_candidates = {
            "testing": ("testing", "test", "\u6d4b\u8bd5"),
            "python": ("python",),
            "project": ("project", "repo", "\u9879\u76ee", "\u4ed3\u5e93", "\u4ee3\u7801\u5e93"),
            "workflow": ("workflow", "\u6d41\u7a0b", "\u6b65\u9aa4", "\u89c4\u8303", "\u7ea6\u5b9a"),
            "ui": ("ui", "\u524d\u7aef", "\u754c\u9762"),
            "api": ("api", "\u63a5\u53e3"),
            "preference": ("\u504f\u597d", "\u559c\u6b22", "\u4e60\u60ef", "\u9ed8\u8ba4"),
            "memory": ("\u8bb0\u4f4f", "\u8bb0\u5fc6"),
        }
        for tag, candidates in tag_candidates.items():
            if any(candidate in lowered for candidate in candidates):
                tags.append(tag)
        return tags

    def _dedupe(self, notes: list[MemoryNote]) -> list[MemoryNote]:
        deduped: dict[str, MemoryNote] = {}
        for note in notes:
            deduped[note.slug] = note
        return list(deduped.values())

    def _build_body(
        self,
        *,
        canonical_statement: str,
        reason: str,
        retrieval_hints: list[str],
        source_excerpt: str,
    ) -> str:
        reason_label = {
            "stable_user_preference": "Stable user preference",
            "stable_feedback": "Stable feedback",
            "stable_project_fact": "Stable project fact",
            "stable_reference_pointer": "Stable reference pointer",
            "memory_policy_feedback": "Memory policy feedback",
        }.get(reason, "Durable memory candidate")
        lines = [
            "## Canonical Memory",
            normalize_storage_text(canonical_statement),
            "",
        ]
        if retrieval_hints:
            lines.extend(
                [
                    "## Retrieval Hints",
                    *[f"- {hint}" for hint in retrieval_hints],
                    "",
                ]
            )
        lines.extend(
            [
                "## Why Stored",
                reason_label,
                "",
                "## Source Evidence",
                normalize_storage_text(source_excerpt),
            ]
        )
        return "\n".join(lines).strip()

    def _canonical_statement(self, text: str) -> str:
        compact = " ".join(normalize_storage_text(text).split())
        return compact[:180] + ("..." if len(compact) > 180 else "")

    def _retrieval_hints(self, title: str, summary: str, tags: list[str]) -> list[str]:
        hints: list[str] = []
        for candidate in [title, summary, *tags]:
            normalized = normalize_storage_text(candidate)
            if normalized and normalized not in hints:
                hints.append(normalized)
        return hints[:8]

    def _shorten_excerpt(self, text: str, limit: int) -> str:
        compact = " ".join(normalize_storage_text(text).split())
        return compact[:limit] + ("..." if len(compact) > limit else "")

    def _confidence_from_decision(self, reason: str) -> str:
        mapping = {
            "stable_user_preference": "high",
            "stable_feedback": "high",
            "stable_project_fact": "high",
            "stable_reference_pointer": "medium",
            "memory_policy_feedback": "medium",
        }
        return mapping.get(reason, "medium")

    def _session_id_from_messages(self, messages: list[Message]) -> str:
        for message in reversed(messages):
            session_id = str(message.meta.get("session_id", "") or "")
            if session_id:
                return session_id
        return ""

    def _extract_from_projection_messages(self, messages: list[Message]) -> list[MemoryNote]:
        extracted: list[MemoryNote] = []
        for message in messages:
            if str(message.meta.get("projection", "") or "") != "durable_context_state":
                continue
            bundle = self._projection_bundle(message, messages)
            extracted.extend(self._extract_notes_from_bundle(bundle))
        return extracted

    async def _aextract_from_projection_messages(self, messages: list[Message]) -> list[MemoryNote]:
        extracted: list[MemoryNote] = []
        for message in messages:
            if str(message.meta.get("projection", "") or "") != "durable_context_state":
                continue
            bundle = self._projection_bundle(message, messages)
            extracted.extend(await self._aextract_notes_from_bundle(bundle))
        return extracted

    def _extract_from_explicit_messages(self, messages: list[Message]) -> list[MemoryNote]:
        bundle = self._explicit_bundle(messages)
        if bundle is None:
            return []
        return self._extract_notes_from_bundle(bundle)

    async def _aextract_from_explicit_messages(self, messages: list[Message]) -> list[MemoryNote]:
        bundle = self._explicit_bundle(messages)
        if bundle is None:
            return []
        return await self._aextract_notes_from_bundle(bundle)

    def _projection_bundle(self, message: Message, messages: list[Message]) -> DurableExtractionBundle:
        return DurableExtractionBundle(
            session_id=str(message.meta.get("session_id", "") or ""),
            turn_id=str(message.meta.get("turn_id", "") or ""),
            message_slice=[
                {
                    "role": msg.role,
                    "content": msg.content,
                }
                for msg in messages[-8:]
            ],
            main_context=dict(message.meta.get("main_context", {}) or {}),
            task_summaries=[
                item
                for item in list(message.meta.get("task_summaries", []) or [])
                if isinstance(item, dict)
            ],
            corrections=[
                str(item)
                for item in list(message.meta.get("corrections", []) or [])
                if str(item).strip()
            ],
            session_projection={},
            manifest_headers=self._manifest_headers(),
        )

    def _explicit_bundle(self, messages: list[Message]) -> DurableExtractionBundle | None:
        candidates = [
            {
                "role": msg.role,
                "content": normalize_storage_text(msg.content),
                "session_id": str(msg.meta.get("session_id", "") or ""),
            }
            for msg in messages[-20:]
            if msg.role == "user" and self._is_explicit_write_candidate(normalize_storage_text(msg.content))
        ]
        if not candidates:
            return None
        return DurableExtractionBundle(
            session_id=str(candidates[-1].get("session_id", "") or ""),
            turn_id="explicit-fallback",
            message_slice=candidates,
            main_context={},
            task_summaries=[],
            corrections=[],
            session_projection={},
            manifest_headers=self._manifest_headers(),
        )

    def _manifest_headers(self) -> list[dict[str, object]]:
        return [
            {
                "note_id": header.note_id,
                "filename": header.filename,
                "memory_type": header.memory_type,
                "memory_class": header.memory_class,
                "title": header.title,
                "description": header.description,
                "status": header.status,
                "confidence": header.confidence,
                "eligible_for_injection": header.eligible_for_injection,
                "canonical_statement": header.canonical_statement,
                "summary": header.summary,
            }
            for header in scan_memory_headers(self.memory_manager.root_dir, limit=200)
        ]

    def _extract_notes_from_bundle(self, bundle: DurableExtractionBundle) -> list[MemoryNote]:
        drafts = asyncio.run(self.write_agent.extract(bundle))
        return self._notes_from_drafts(drafts)

    async def _aextract_notes_from_bundle(self, bundle: DurableExtractionBundle) -> list[MemoryNote]:
        drafts = await self.write_agent.extract(bundle)
        return self._notes_from_drafts(drafts)

    def _notes_from_drafts(self, drafts) -> list[MemoryNote]:
        if not drafts:
            return []
        decisions = self.admission_policy.evaluate_many(
            drafts,
            existing_headers=scan_memory_headers(self.memory_manager.root_dir, limit=200),
        )
        plan = self.mutation_planner.build_plan(decisions)
        return self.store_writer.plan_notes(plan)

    def _note_from_statement(
        self,
        statement: str,
        *,
        created_by: str,
        source_session_id: str,
        source_role: str,
        reason: str,
        memory_type: str,
        memory_class: str,
        extra_tags: list[str],
        confidence: str,
    ) -> MemoryNote:
        title = self._make_title(statement)
        summary = self._summarize(statement)
        canonical_statement = self._canonical_statement(statement)
        tags = self._merge_tags(self._tags(statement), extra_tags)
        retrieval_hints = self._retrieval_hints(title, summary, tags)
        source_excerpt = self._shorten_excerpt(statement, 160)
        return MemoryNote(
            slug=self.memory_manager.slugify(title),
            title=title,
            summary=summary,
            canonical_statement=canonical_statement,
            body=self._build_body(
                canonical_statement=canonical_statement,
                reason=reason,
                retrieval_hints=retrieval_hints,
                source_excerpt=source_excerpt,
            ),
            memory_type=memory_type,
            memory_class=memory_class,
            tags=tags,
            retrieval_hints=retrieval_hints,
            created_by=created_by,
            source_session_id=source_session_id,
            source_role=source_role,
            source_message_excerpt=source_excerpt,
            confidence=confidence,
            last_confirmed_at="",
        )

    def _is_explicit_write_candidate(self, text: str) -> bool:
        lowered = normalize_storage_text(text).lower()
        return any(marker in lowered for marker in self.EXPLICIT_WRITE_MARKERS)
