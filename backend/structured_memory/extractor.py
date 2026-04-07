from __future__ import annotations

from understanding import evaluate_memory_write

from .dialogue_state import DialogueStateManager
from .durable_candidates import DurableCandidate, evaluate_durable_candidate
from .memory_manager import MemoryManager
from .models import MemoryNote, Message
from .text_utils import normalize_storage_text


class MemoryExtractor:
    """Heuristic extractor for durable memories.

    Replace or wrap this with an LLM call if you want smarter extraction.
    """

    TRIGGERS = (
        "remember",
        "preference",
        "prefer",
        "always",
        "never",
        "important",
        "use this",
        "my workflow",
        "our project",
        "\u8bb0\u4f4f",
        "\u8bb0\u4e00\u4e0b",
        "\u522b\u5fd8\u4e86",
        "\u4e0d\u8981\u5fd8",
        "\u6211\u559c\u6b22",
        "\u6211\u6700\u559c\u6b22",
        "\u6211\u66f4\u559c\u6b22",
        "\u6211\u7684\u504f\u597d",
        "\u6211\u4e60\u60ef",
        "\u6211\u901a\u5e38",
        "\u4ee5\u540e\u90fd",
        "\u9ed8\u8ba4\u7528",
        "\u8bf7\u7528",
        "\u9879\u76ee\u91cc",
        "\u6211\u4eec\u9879\u76ee",
        "\u6211\u4eec\u7684\u9879\u76ee",
        "\u5de5\u4f5c\u6d41",
        "\u6d41\u7a0b\u662f",
        "\u7ea6\u5b9a",
        "\u89c4\u8303",
        "\u4ee5\u540e\u6309\u8fd9\u4e2a",
    )

    def __init__(self, memory_manager: MemoryManager) -> None:
        self.memory_manager = memory_manager

    def extract(self, messages: list[Message]) -> list[MemoryNote]:
        session_id = self._session_id_from_messages(messages)
        if session_id:
            state_notes = self._extract_from_session_state(session_id)
            if state_notes:
                return self._dedupe(state_notes)

        extracted: list[MemoryNote] = []
        for msg in messages[-20:]:
            if msg.role != "user":
                continue
            content = normalize_storage_text(msg.content)
            lowered = content.lower()
            decision = evaluate_memory_write(content)
            if decision.action != "durable_fact":
                continue
            if not any(trigger in lowered for trigger in self.TRIGGERS) and decision.reason != "memory_policy_feedback":
                continue
            title = self._make_title(content)
            summary = self._summarize(content)
            canonical_statement = self._canonical_statement(content)
            tags = self._merge_tags(self._tags(content), decision.tags)
            retrieval_hints = self._retrieval_hints(title, summary, tags)
            source_excerpt = self._shorten_excerpt(content, 160)
            slug = self.memory_manager.slugify(title)
            note = MemoryNote(
                slug=slug,
                title=title,
                summary=summary,
                canonical_statement=canonical_statement,
                body=self._build_body(
                    canonical_statement=canonical_statement,
                    reason=decision.reason,
                    retrieval_hints=retrieval_hints,
                    source_excerpt=source_excerpt,
                ),
                memory_type=self._classify(content, decision.memory_type),
                memory_class=self._classify_memory_class(content, decision),
                tags=tags,
                retrieval_hints=retrieval_hints,
                created_by="memory_extractor",
                source_session_id=str(msg.meta.get("session_id", "") or ""),
                source_role=msg.role,
                source_message_excerpt=source_excerpt,
                confidence=self._confidence_from_decision(decision.reason),
                last_confirmed_at="",
            )
            extracted.append(note)
        return self._dedupe(extracted)

    def save_extracted(self, messages: list[Message]) -> list[MemoryNote]:
        notes = self.extract(messages)
        for note in notes:
            self.memory_manager.save_note(note)
        return notes

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

    def _classify(self, text: str, forced_type: str | None = None) -> str:
        if forced_type:
            return forced_type
        lowered = text.lower()
        if any(
            token in lowered
            for token in (
                "prefer",
                "always",
                "never",
                "\u8bb0\u4f4f",
                "\u6211\u559c\u6b22",
                "\u6211\u6700\u559c\u6b22",
                "\u6211\u66f4\u559c\u6b22",
                "\u504f\u597d",
                "\u4e60\u60ef",
                "\u9ed8\u8ba4\u7528",
            )
        ):
            return "preference"
        if any(
            token in lowered
            for token in (
                "project",
                "repo",
                "codebase",
                "\u9879\u76ee",
                "\u4ee3\u7801\u5e93",
                "\u4ed3\u5e93",
                "\u5de5\u7a0b",
            )
        ):
            return "project"
        if any(
            token in lowered
            for token in (
                "workflow",
                "process",
                "step",
                "\u5de5\u4f5c\u6d41",
                "\u6d41\u7a0b",
                "\u6b65\u9aa4",
                "\u4ee5\u540e\u6309\u8fd9\u4e2a",
                "\u89c4\u8303",
                "\u7ea6\u5b9a",
            )
        ):
            return "workflow"
        return "user"

    def _classify_memory_class(self, text: str, decision: object) -> str:
        explicit_class = getattr(decision, "memory_class", None)
        if explicit_class in {"work", "preference"}:
            return explicit_class
        memory_type = self._classify(text, getattr(decision, "memory_type", None))
        if memory_type in {"user", "preference"}:
            return "preference"
        return "work"

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
            "stable_work_convention": "Stable work convention",
            "stable_user_preference": "Stable user preference",
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
            "stable_work_convention": "high",
            "stable_user_preference": "high",
            "memory_policy_feedback": "medium",
        }
        return mapping.get(reason, "medium")

    def _session_id_from_messages(self, messages: list[Message]) -> str:
        for message in reversed(messages):
            session_id = str(message.meta.get("session_id", "") or "")
            if session_id:
                return session_id
        return ""

    def _extract_from_session_state(self, session_id: str) -> list[MemoryNote]:
        session_dir = self.memory_manager.root_dir.parent / "session-memory" / session_id
        if not session_dir.exists():
            return []
        state = DialogueStateManager(session_dir).load()
        extracted: list[MemoryNote] = []
        for candidate in state.durable_candidates:
            decision = evaluate_durable_candidate(candidate)
            if decision.action != "accept":
                continue
            extracted.append(self._note_from_candidate(session_id, candidate, decision.reason, decision.confidence))
        return extracted

    def _note_from_candidate(
        self,
        session_id: str,
        candidate: DurableCandidate,
        reason: str,
        confidence: str,
    ) -> MemoryNote:
        title = normalize_storage_text(candidate.title) or "Session Durable Memory"
        slug = self.memory_manager.slugify(title)
        source_excerpt = self._shorten_excerpt(candidate.source_excerpt or candidate.canonical_statement, 160)
        return MemoryNote(
            slug=slug,
            title=title,
            summary=normalize_storage_text(candidate.summary) or title,
            canonical_statement=normalize_storage_text(candidate.canonical_statement) or normalize_storage_text(candidate.summary) or title,
            body=self._build_body(
                canonical_statement=normalize_storage_text(candidate.canonical_statement) or title,
                reason=reason,
                retrieval_hints=list(candidate.retrieval_hints),
                source_excerpt=source_excerpt,
            ),
            memory_type=candidate.memory_type,
            memory_class=candidate.memory_class,
            tags=self._merge_tags([candidate.memory_class, candidate.memory_type], list(candidate.retrieval_hints)),
            retrieval_hints=list(candidate.retrieval_hints),
            created_by="session_state_extractor",
            source_session_id=session_id,
            source_role=candidate.source_role,
            source_message_excerpt=source_excerpt,
            confidence=confidence,
            last_confirmed_at="",
        )
