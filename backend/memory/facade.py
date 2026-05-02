from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context_policy import build_context_package_result
from context_management import ContextPackage
from context_management.budget_presets import get_context_budget_preset
from memory.durable import DurableMemoryLayer
from memory.messages import MemoryMessageAdapter
from memory.session import SessionMemoryLayer
from memory_system.compaction import build_memory_compaction_result
from memory_system.conversation_memory import ConversationMemoryStoreAdapter
from memory_system.gate import build_blocked_memory_gate
from memory_system.governance import MemoryGovernance
from memory_system.long_term_memory import LongTermMemoryStoreAdapter
from memory_system.runtime_view import build_memory_runtime_view
from memory_system.state_memory import StateMemoryStoreAdapter


def _value_from_context(context: Any, key: str) -> str:
    if isinstance(context, dict):
        return str(context.get(key, "") or "").strip()
    return str(getattr(context, key, "") or "").strip()


def _summary_text(summary: Any) -> str:
    if isinstance(summary, dict):
        return str(summary.get("summary", "") or summary.get("query", "") or "").strip()
    return str(getattr(summary, "summary", "") or getattr(summary, "query", "") or "").strip()


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
        self.governance = MemoryGovernance(base_dir)

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
        return self.state_memory.load_snapshot(session_id)

    def build_state_memory_restore_candidates(self, session_id: str):
        return self.state_memory.restore_candidates(session_id)

    def build_state_memory_context_candidates(self, session_id: str):
        return self.state_memory.context_candidates(session_id)

    def build_conversation_memory_snapshot(self, session_id: str):
        return self.conversation_memory.load_snapshot(session_id)

    def build_conversation_memory_context_candidates(self, session_id: str):
        return self.conversation_memory.context_candidates(session_id)

    def build_long_term_memory_records(self, *, limit: int = 200, runtime_visible_only: bool = True):
        return self.long_term_memory.load_records(limit=limit, runtime_visible_only=runtime_visible_only)

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
        recall_result = self.durable_memory.recall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
            selected_notes=relevant_notes,
        )
        return self.long_term_memory.context_candidates_from_recall_result(
            recall_result,
            session_id=session_id,
            query=str(query or ""),
        )

    def build_memory_runtime_view(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
    ):
        return build_memory_runtime_view(
            self,
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )

    def build_memory_context_package_result(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        available_context_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        long_term_token_cap: int | None = None,
    ):
        budget = self._context_budget()
        memory_view = self.build_memory_runtime_view(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        return build_context_package_result(
            memory_view,
            rebuild_reason="memory_facade_context_package_result",
            retrieval_results=retrieval_results,
            available_context_tokens=available_context_tokens if available_context_tokens is not None else int(budget["available_context_tokens"]),
            reserved_output_tokens=reserved_output_tokens if reserved_output_tokens is not None else int(budget["reserved_output_tokens"]),
            long_term_token_cap=long_term_token_cap if long_term_token_cap is not None else int(budget["long_term_token_cap"]),
        )

    def build_memory_context_package(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
    ):
        return self.build_memory_context_package_result(
            session_id=session_id,
            query=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            retrieval_results=retrieval_results,
            note_limit=note_limit,
        )

    def build_memory_compaction_result(
        self,
        *,
        session_id: str,
        history: list[dict[str, Any]] | None = None,
    ):
        memory_view = self.build_memory_runtime_view(session_id=session_id)
        return build_memory_compaction_result(
            session_id=session_id,
            history_count=len(history or []),
            context_candidate_count=len(memory_view.context_candidates),
            restore_candidate_count=len(memory_view.restore_candidates),
        )

    def inspect_memory_context_compaction(
        self,
        session_id: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        result = self.build_memory_compaction_result(
            session_id=session_id,
            history=history,
        )
        return list(history or []), result.to_dict()

    def build_durable_memory_write_candidates(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ):
        py_messages = self.adapter.to_messages(messages, session_id=session_id)
        notes = self.durable_memory.preview_extraction_notes(py_messages)
        return self.long_term_memory.write_candidates_from_notes(
            notes,
            source_event_refs=(session_id,),
            candidate_prefix=f"memory-write:{session_id or 'session'}:long-term",
        )

    def build_durable_memory_write_candidates_from_context_state(
        self,
        session_id: str,
        main_context: Any,
        *,
        task_summaries: list[Any] | None = None,
        corrections: list[str] | None = None,
    ):
        notes = self.durable_memory.preview_extraction_notes_from_context_state(
            session_id,
            main_context,
            task_summaries=task_summaries,
            corrections=corrections,
        )
        return self.long_term_memory.write_candidates_from_notes(
            notes,
            source_event_refs=(session_id,),
            candidate_prefix=f"memory-write:{session_id or 'session'}:long-term",
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

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        candidates = self.build_long_term_memory_context_candidates(
            session_id="legacy",
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            relevant_notes=relevant_notes,
        )
        return "\n\n".join(candidate.rendered_preview for candidate in candidates if candidate.rendered_preview).strip()

    async def abuild_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        return self.build_persistent_memory_block(
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
        return self.durable_memory.build_recall_request(
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
        return self.durable_memory.recall_memories(
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
        return await self.durable_memory.arecall_memories(
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
        return self.durable_memory.build_manifest_block(note_limit=note_limit)

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
        memory_view = self.build_memory_runtime_view(
            session_id=session_id,
            query=pending_user_message,
            memory_intent=memory_intent,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        context_result = build_context_package_result(
            memory_view,
            rebuild_reason="legacy_inspect_query_context_result",
            retrieval_results=retrieval_results,
            available_context_tokens=int(self._context_budget()["available_context_tokens"]),
            reserved_output_tokens=int(self._context_budget()["reserved_output_tokens"]),
            long_term_token_cap=int(self._context_budget()["long_term_token_cap"]),
        )
        return {
            "memory_runtime_view": memory_view.to_dict(),
            "context_policy_result": context_result.to_dict(),
            "context_compaction": dict(context_compaction or {}),
            "legacy_inspection": False,
            "inspection_mode": "read_only",
        }

    def _context_budget(self) -> dict[str, Any]:
        if self._context_budget_provider is not None:
            try:
                payload = dict(self._context_budget_provider())
                if payload:
                    return payload
            except Exception:
                pass
        return get_context_budget_preset("deepseek_1m").to_dict()

    def prefetch_relevant_notes(
        self,
        query: str,
        memory_intent: Any | None = None,
        *,
        limit: int = 3,
    ) -> list[Any]:
        return self.durable_memory.prefetch_relevant_notes(query, memory_intent, limit=limit)

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

    def describe_durable_extraction_runtime(self) -> dict[str, object]:
        return self.durable_memory.describe_extraction_runtime()

    def govern_durable_notes(self) -> dict[str, Any]:
        return self.memory_manager.govern_note_store()
