from __future__ import annotations

from understanding import evaluate_memory_write

from .dialogue_state import DialogueStateManager
from .durable_candidates import DurableCandidate, evaluate_durable_candidate
from .memory_manager import MemoryManager
from .models import MemoryNote, Message
from .note_hygiene import is_runtime_noise_note, looks_like_synthetic_memory_text
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
        extracted: list[MemoryNote] = []
        if session_id:
            state_notes = self._extract_from_session_state(session_id)
            if state_notes:
                extracted.extend(state_notes)

        for msg in messages[-20:]:
            if msg.role != "user":
                continue
            content = normalize_storage_text(msg.content)
            lowered = content.lower()
            decision = evaluate_memory_write(content)
            if (
                decision.action != "durable_fact"
                or decision.memory_type is None
                or decision.memory_class is None
            ):
                continue
            if not any(trigger in lowered for trigger in self.TRIGGERS) and decision.reason != "memory_policy_feedback":
                continue
            extracted.append(
                self._note_from_statement(
                    content,
                    created_by="memory_extractor",
                    source_session_id=str(msg.meta.get("session_id", "") or ""),
                    source_role=msg.role,
                    reason=decision.reason,
                    memory_type=decision.memory_type,
                    memory_class=decision.memory_class,
                    extra_tags=decision.tags,
                    confidence=self._confidence_from_decision(decision.reason),
                )
            )
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

    def _extract_from_session_state(self, session_id: str) -> list[MemoryNote]:
        session_dir = self.memory_manager.root_dir.parent / "session-memory" / session_id
        if not session_dir.exists():
            return []
        state = DialogueStateManager(session_dir).load()
        extracted = self._extract_request_notes_from_state(session_id, state.key_user_requests)
        for candidate in state.durable_candidates:
            if not self._should_commit_candidate(candidate):
                continue
            decision = evaluate_durable_candidate(candidate)
            if decision.action != "accept":
                continue
            extracted.append(
                self._note_from_candidate(
                    session_id,
                    candidate,
                    memory_type=decision.memory_type,
                    memory_class=decision.memory_class,
                    reason=decision.reason,
                    confidence=decision.confidence,
                )
            )
        return self._dedupe(extracted)

    def _note_from_candidate(
        self,
        session_id: str,
        candidate: DurableCandidate,
        *,
        memory_type: str,
        memory_class: str,
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
            memory_type=memory_type,
            memory_class=memory_class,
            tags=self._merge_tags([memory_class, memory_type], list(candidate.retrieval_hints)),
            retrieval_hints=list(candidate.retrieval_hints),
            created_by="session_state_extractor",
            source_session_id=session_id,
            source_role=candidate.source_role,
            source_message_excerpt=source_excerpt,
            confidence=confidence,
            last_confirmed_at="",
        )

    def _should_commit_candidate(self, candidate: DurableCandidate) -> bool:
        statement = normalize_storage_text(candidate.canonical_statement or candidate.source_excerpt or candidate.title)
        if not statement:
            return False
        if looks_like_synthetic_memory_text(statement):
            return False
        if statement.endswith("?") or statement.endswith("？"):
            return False
        if is_runtime_noise_note(
            source_role=candidate.source_role,
            created_by="session_state_extractor",
            title=candidate.title,
            summary=candidate.summary,
            canonical_statement=candidate.canonical_statement,
            source_message_excerpt=candidate.source_excerpt,
        ):
            return False
        return True

    def _extract_request_notes_from_state(
        self,
        session_id: str,
        requests: list[str],
    ) -> list[MemoryNote]:
        extracted: list[MemoryNote] = []
        for request in requests:
            statement = normalize_storage_text(request)
            if not statement or statement.endswith("?") or statement.endswith("？"):
                continue
            decision = evaluate_memory_write(statement)
            if decision.action != "durable_fact" or not decision.memory_type or not decision.memory_class:
                continue
            extracted.append(
                self._note_from_statement(
                    statement,
                    created_by="session_state_extractor",
                    source_session_id=session_id,
                    source_role="user",
                    reason=decision.reason,
                    memory_type=decision.memory_type,
                    memory_class=decision.memory_class,
                    extra_tags=decision.tags,
                    confidence=self._confidence_from_decision(decision.reason),
                )
            )
        return extracted

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
