from __future__ import annotations

from typing import Any

from .conversation_memory import ConversationMemoryStoreAdapter
from .gate import build_blocked_memory_gate
from .messages import MemoryMessageAdapter
from .supply import build_memory_writeback_proposal


def _value_from_context(context: Any, key: str) -> str:
    if isinstance(context, dict):
        return str(context.get(key, "") or "").strip()
    return str(getattr(context, key, "") or "").strip()


def _summary_text(summary: Any) -> str:
    if isinstance(summary, dict):
        return str(summary.get("summary", "") or summary.get("query", "") or "").strip()
    return str(getattr(summary, "summary", "") or getattr(summary, "query", "") or "").strip()


class MemoryWritebackBuilderService:
    """Candidate-only writeback builder for the memory system."""

    def __init__(
        self,
        *,
        adapter: MemoryMessageAdapter,
        durable_memory: Any,
        conversation_memory: ConversationMemoryStoreAdapter,
    ) -> None:
        self.adapter = adapter
        self.durable_memory = durable_memory
        self.conversation_memory = conversation_memory

    def build_long_term_write_candidates(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        long_term_memory: Any,
    ):
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        notes = self.durable_memory.preview_extraction_notes(py_messages)
        return long_term_memory.write_candidates_from_notes(
            notes,
            source_event_refs=(session_id,),
            candidate_prefix=f"memory-write:{session_id or 'session'}:long-term",
        )

    def build_long_term_write_candidates_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
        long_term_memory: Any,
    ):
        notes = self.durable_memory.preview_extraction_notes_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
        return long_term_memory.write_candidates_from_notes(
            notes,
            source_event_refs=(session_id,),
            candidate_prefix=f"memory-write:{session_id or 'session'}:long-term",
        )

    def build_memory_writeback_proposal(
        self,
        *,
        session_id: str,
        task_id: str,
        write_candidates: list[Any] | None = None,
    ):
        return build_memory_writeback_proposal(
            session_id=session_id,
            task_id=task_id,
            write_candidates=write_candidates or [],
        )

    def build_session_memory_write_candidates_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ):
        content = self._render_session_memory_write_candidate(
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
        candidate = self.conversation_memory.propose_summary_update_candidate(
            session_id=session_id,
            content=content,
            source_event_refs=(session_id,),
        )
        return (candidate,) if candidate is not None else ()

    def build_memory_gate(
        self,
        write_candidates,
        *,
        gate_id: str = "memory-gate:writeback",
        reason: str = "memory_write_requires_commit_gate",
    ):
        return build_blocked_memory_gate(
            tuple(write_candidates or ()),
            gate_id=gate_id,
            reason=reason,
        )

    def commit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.durable_memory.commit_extraction(py_messages)

    async def acommit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return await self.durable_memory.acommit_extraction(py_messages)

    def commit_durable_memory_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        return self.durable_memory.commit_extraction_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )

    async def acommit_durable_memory_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        return await self.durable_memory.acommit_extraction_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )

    def submit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.durable_memory.schedule_extraction(py_messages)

    def submit_durable_memory_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        return self.durable_memory.schedule_extraction_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )

    def _render_session_memory_write_candidate(
        self,
        main_context: Any,
        *,
        task_summaries: list[Any] | None,
        corrections: list[str] | None,
    ) -> str:
        lines: list[str] = []
        active_goal = _value_from_context(main_context, "active_goal")
        if active_goal:
            lines.append(f"Active goal: {active_goal}")
        active_work_item = _value_from_context(main_context, "active_work_item")
        if active_work_item:
            lines.append(f"Active work item: {active_work_item}")
        next_step = _value_from_context(main_context, "next_step")
        if next_step:
            lines.append(f"Next step: {next_step}")
        for index, summary in enumerate(list(task_summaries or [])[:5]):
            value = _summary_text(summary)
            if value:
                lines.append(f"Task summary {index + 1}: {value}")
        for correction in list(corrections or [])[:5]:
            value = str(correction or "").strip()
            if value:
                lines.append(f"Correction: {value}")
        return "\n".join(lines).strip()
