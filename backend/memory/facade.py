from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from memory.context import MemoryContextLayer
from memory.durable import DurableMemoryLayer
from memory.messages import MemoryMessageAdapter
from memory.session import SessionMemoryLayer


class MemoryFacade:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.adapter = MemoryMessageAdapter()
        self.session_memory = SessionMemoryLayer(base_dir)
        self.durable_memory = DurableMemoryLayer(base_dir)
        self.context_memory = MemoryContextLayer(
            self.session_memory,
            self.durable_memory,
        )
        self.memory_manager = self.durable_memory.memory_manager
        self.extractor = self.durable_memory.extractor
        self.scheduler = self.durable_memory.scheduler
        self.session_root = self.session_memory.session_root

    def set_durable_memory_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.durable_memory.set_saved_callback(callback)

    def refresh_session_memory(self, session_id: str, messages: list[dict[str, Any]]) -> str:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.session_memory.refresh(session_id, py_messages)

    def build_session_memory_block(
        self,
        session_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        include_durable_context: bool = True,
    ) -> str:
        py_history = self.adapter.to_messages(history or [], session_id=session_id)
        return self.context_memory.build_session_memory_block(
            session_id,
            history=py_history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            include_durable_context=include_durable_context,
        )

    def build_context_package(
        self,
        session_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        rebuild_reason: str = "prompt_assembly",
    ):
        py_history = self.adapter.to_messages(history or [], session_id=session_id)
        return self.context_memory.build_context_package(
            session_id,
            history=py_history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            rebuild_reason=rebuild_reason,
        )

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        return self.durable_memory.build_persistent_memory_block(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            relevant_notes=relevant_notes,
        )

    def compact_history_for_query(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        py_history = self.adapter.to_messages(history, session_id=session_id)
        return self.context_memory.compact_history_for_query(session_id, py_history)

    def inspect_query_context(
        self,
        session_id: str,
        *,
        history: list[dict[str, Any]] | None = None,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
        context_compaction: dict[str, Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        py_history = self.adapter.to_messages(history or [], session_id=session_id)
        return self.context_memory.inspect_query_context(
            session_id,
            history=py_history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
            context_compaction=context_compaction,
            retrieval_results=retrieval_results,
        )

    def prefetch_relevant_notes(
        self,
        query: str,
        memory_intent: Any | None = None,
        *,
        limit: int = 3,
    ) -> list[Any]:
        return self.durable_memory.prefetch_relevant_notes(query, memory_intent, limit=limit)

    def extract_durable_memories(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.durable_memory.extract_durable_memories(py_messages)

    def commit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.durable_memory.extract_durable_memories(py_messages)

    def submit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.durable_memory.submit_extraction(py_messages)
