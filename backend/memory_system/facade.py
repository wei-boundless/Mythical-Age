from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context_management import ContextPackage
from .bundle_service import MemoryBundleService
from .conversation_memory import ConversationMemoryStoreAdapter
from .durable import DurableMemoryLayer
from .governance_service import DurableMemoryGovernanceService
from .long_term_memory import LongTermMemoryStoreAdapter
from .messages import MemoryMessageAdapter
from .request_service import MemoryRequestService
from .session import SessionMemoryLayer
from .state_memory import StateMemoryStoreAdapter
from .writeback_service import MemoryWritebackBuilderService


def _render_context_package_for_legacy_block(
    package: ContextPackage,
    *,
    include_durable_context: bool,
) -> str:
    sections = package.sections_for("model") if hasattr(package, "sections_for") else package.model_visible_sections
    skipped = set() if include_durable_context else {"exact_durable_context", "relevant_durable_context"}
    lines: list[str] = []
    for section_name in (
        "active_process_context",
        "hot_truth_window",
        "retrieval_evidence",
        "warm_snapshots",
        "exact_durable_context",
        "relevant_durable_context",
    ):
        if section_name in skipped:
            continue
        items = [str(item).strip() for item in list(sections.get(section_name, []) or []) if str(item).strip()]
        if not items:
            continue
        lines.append(f"## {section_name}")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines).strip()


class MemoryFacade:
    def __init__(self, base_dir: Path, context_budget_provider: Callable[[], dict[str, Any]] | None = None) -> None:
        self.base_dir = base_dir
        self._context_budget_provider = context_budget_provider
        self.adapter = MemoryMessageAdapter()
        self.session_memory = SessionMemoryLayer(base_dir, context_budget_provider=context_budget_provider)
        self.durable_memory = DurableMemoryLayer(base_dir)
        self.memory_manager = self.durable_memory.memory_manager
        self.extractor = self.durable_memory.extractor
        self.scheduler = self.durable_memory.scheduler
        self.session_root = self.session_memory.session_root
        self.conversation_memory = ConversationMemoryStoreAdapter(self.session_root)
        self.state_memory = StateMemoryStoreAdapter(self.session_root)
        self.long_term_memory = LongTermMemoryStoreAdapter(self.memory_manager.root_dir)
        self.request_service = MemoryRequestService()
        self.bundle_service = MemoryBundleService(
            session_memory=self.session_memory,
            conversation_memory=self.conversation_memory,
            state_memory=self.state_memory,
            long_term_memory=self.long_term_memory,
            durable_memory=self.durable_memory,
            request_service=self.request_service,
            context_budget_provider=context_budget_provider,
        )
        self.writeback_builder = MemoryWritebackBuilderService(
            adapter=self.adapter,
            durable_memory=self.durable_memory,
            conversation_memory=self.conversation_memory,
        )
        self.governance_service = DurableMemoryGovernanceService(
            base_dir,
            memory_manager=self.memory_manager,
        )

    def set_durable_memory_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.durable_memory.set_saved_callback(callback)

    def set_model_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self.durable_memory.set_message_invoker(callback)

    def refresh_session_memory(self, session_id: str, messages: list[dict[str, Any]]) -> str:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        return self.session_memory.refresh(session_id, py_messages)

    def refresh_session_memory_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        bundle_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> str:
        return self.session_memory.refresh_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            bundle_summaries=bundle_summaries,
            corrections=corrections,
        )

    def delete_session_memory(self, session_id: str) -> bool:
        return self.session_memory.delete_session(session_id)

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
        package = self.build_context_package(
            session_id,
            history=history,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            rebuild_reason="legacy_session_memory_block_result",
        )
        return _render_context_package_for_legacy_block(
            package,
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
        return self.build_memory_context_package_result(
            session_id=session_id,
            query=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
        ).package

    def build_state_memory_snapshot(self, session_id: str):
        return self.bundle_service.build_state_memory_snapshot(session_id)

    def build_state_memory_restore_candidates(self, session_id: str):
        return self.bundle_service.build_state_memory_restore_candidates(session_id)

    def build_state_memory_context_candidates(self, session_id: str):
        return self.bundle_service.build_state_memory_context_candidates(session_id)

    def build_conversation_memory_snapshot(self, session_id: str):
        return self.bundle_service.build_conversation_memory_snapshot(session_id)

    def build_conversation_memory_context_candidates(self, session_id: str):
        return self.bundle_service.build_conversation_memory_context_candidates(session_id)

    def build_long_term_memory_records(self, *, limit: int = 200, runtime_visible_only: bool = True):
        return self.bundle_service.build_long_term_memory_records(
            limit=limit,
            runtime_visible_only=runtime_visible_only,
        )

    def build_long_term_memory_context_candidates(
        self,
        *,
        session_id: str = "",
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
        relevant_notes: list[Any] | None = None,
    ):
        return self.bundle_service.build_long_term_memory_context_candidates(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
            relevant_notes=relevant_notes,
        )

    def build_memory_runtime_view(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_runtime_view(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )

    def build_memory_request(
        self,
        *,
        task_id: str,
        session_id: str,
        agent_id: str,
        memory_request_profile: dict[str, Any] | None = None,
        reason: str = "",
    ):
        return self.request_service.build_memory_request(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
            reason=reason,
        )

    def build_memory_scope_policy(
        self,
        *,
        agent_id: str,
        memory_request_profile: dict[str, Any] | None = None,
    ):
        return self.request_service.build_memory_scope_policy(
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
        )

    def build_memory_context_package_result(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        available_context_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        long_term_token_cap: int | None = None,
    ):
        return self.bundle_service.build_memory_context_package_result(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            note_limit=note_limit,
            available_context_tokens=available_context_tokens,
            reserved_output_tokens=reserved_output_tokens,
            long_term_token_cap=long_term_token_cap,
        )

    def build_memory_context_package(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_context_package(
            session_id=session_id,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            note_limit=note_limit,
        )

    def build_memory_bundle(
        self,
        *,
        task_id: str,
        session_id: str,
        agent_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_bundle(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )

    def build_memory_compaction_result(
        self,
        *,
        session_id: str,
        history: list[dict[str, Any]] | None = None,
    ):
        return self.bundle_service.build_memory_compaction_result(
            session_id=session_id,
            history=history,
        )

    def inspect_memory_context_compaction(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self.bundle_service.inspect_memory_context_compaction(session_id, history)

    def build_durable_memory_write_candidates(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ):
        return self.writeback_builder.build_long_term_write_candidates(
            session_id,
            messages,
            long_term_memory=self.long_term_memory,
        )

    def build_durable_memory_write_candidates_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ):
        return self.writeback_builder.build_long_term_write_candidates_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
            long_term_memory=self.long_term_memory,
        )

    def build_memory_writeback_proposal(
        self,
        *,
        session_id: str,
        task_id: str,
        write_candidates: list[Any] | None = None,
    ):
        return self.writeback_builder.build_memory_writeback_proposal(
            session_id=session_id,
            task_id=task_id,
            write_candidates=write_candidates,
        )

    def build_session_memory_write_candidates_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ):
        return self.writeback_builder.build_session_memory_write_candidates_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )

    def build_memory_gate(
        self,
        write_candidates,
        *,
        gate_id: str = "memory-gate:writeback",
        reason: str = "memory_write_requires_commit_gate",
    ):
        return self.writeback_builder.build_memory_gate(
            write_candidates,
            gate_id=gate_id,
            reason=reason,
        )

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        return self.bundle_service.build_persistent_memory_block(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
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
        return await self.bundle_service.abuild_persistent_memory_block(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            relevant_notes=relevant_notes,
        )

    def build_memory_recall_request(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
    ):
        return self.bundle_service.build_memory_recall_request(
            query=query,
            memory_intent=memory_intent,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )

    def recall_durable_memories(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
    ):
        return self.bundle_service.recall_durable_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )

    async def arecall_durable_memories(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        main_context: dict[str, object] | None = None,
        task_summaries: list[dict[str, object]] | None = None,
        session_summary: str = "",
        recently_surfaced_note_ids: list[str] | None = None,
        recent_tools: list[str] | None = None,
    ):
        return await self.bundle_service.arecall_durable_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )

    def build_durable_manifest_block(self, *, note_limit: int = 5) -> str:
        return self.bundle_service.build_durable_manifest_block(note_limit=note_limit)

    def compact_history_for_query(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        compacted_history, result = self.inspect_memory_context_compaction(session_id, history)
        return compacted_history, {
            **result,
            "legacy_adapter": "compact_history_for_query",
        }

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
        return self.bundle_service.inspect_query_context(
            session_id,
            history=history,
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
        return self.bundle_service.prefetch_relevant_notes(query, memory_intent, limit=limit)

    def commit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        return self.writeback_builder.commit_durable_memory_extraction(session_id, messages)

    async def acommit_durable_memory_extraction(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        return await self.writeback_builder.acommit_durable_memory_extraction(session_id, messages)

    def commit_durable_memory_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        return self.writeback_builder.commit_durable_memory_extraction_from_context_state(
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
        return await self.writeback_builder.acommit_durable_memory_extraction_from_context_state(
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
        return self.writeback_builder.submit_durable_memory_extraction(session_id, messages)

    def submit_durable_memory_extraction_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ) -> int:
        return self.writeback_builder.submit_durable_memory_extraction_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )

    def describe_durable_extraction_runtime(self) -> dict[str, object]:
        return self.bundle_service.describe_durable_extraction_runtime()

    def govern_durable_notes(self) -> dict[str, Any]:
        return self.governance_service.govern_durable_notes()

    def scan_durable_memory_headers(self, *, limit: int = 200):
        return self.governance_service.scan_durable_memory_headers(limit=limit)

    def create_durable_memory_note(self, **payload: Any) -> dict[str, Any]:
        return self.governance_service.create_durable_memory_note(**payload)

    def set_durable_memory_note_status(self, **payload: Any) -> dict[str, Any]:
        return self.governance_service.set_durable_memory_note_status(**payload)

    def delete_durable_memory_note(self, **payload: Any) -> dict[str, Any]:
        return self.governance_service.delete_durable_memory_note(**payload)

    def merge_durable_memory_notes(self, **payload: Any) -> dict[str, Any]:
        return self.governance_service.merge_durable_memory_notes(**payload)

    def load_durable_memory_note(self, filename: str) -> dict[str, Any]:
        return self.governance_service.load_durable_memory_note(filename)

    def inspect_session_history_tokens(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        compactor = self.session_memory.compactor(session_id)
        raw_history_tokens = compactor.conversation_tokens(py_messages)
        pressure_level = compactor.pressure_level(raw_history_tokens, len(py_messages))
        return {
            "raw_history_tokens": raw_history_tokens,
            "history_budget_tokens": int(compactor.effective_history_token_budget),
            "history_pressure_level": str(pressure_level),
        }
