from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from project_layout import ProjectLayout
from .bundle_service import MemoryBundleService
from .conversation_memory import ConversationMemoryStoreAdapter
from .durable import DurableMemoryLayer
from .governance_service import DurableMemoryGovernanceService
from .long_term_memory import LongTermMemoryStoreAdapter
from .messages import MemoryMessageAdapter
from .request_service import MemoryRequestService
from .session import SessionMemoryLayer
from .state_memory import StateMemoryStoreAdapter
from .task_durable_memory_service import TaskDurableMemoryService
from .working_memory_service import WorkingMemoryService
from .working_memory_finalizer import WorkingMemoryFinalizer
from .writeback_service import MemoryWritebackBuilderService


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
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.working_memory = WorkingMemoryService(layout.working_memory_dir)
        self.task_durable_memory = TaskDurableMemoryService(layout.task_durable_memory_dir)
        self.working_memory_finalizer = WorkingMemoryFinalizer(self.working_memory)
        self.request_service = MemoryRequestService()
        self.bundle_service = MemoryBundleService(
            session_memory=self.session_memory,
            conversation_memory=self.conversation_memory,
            state_memory=self.state_memory,
            working_memory=self.working_memory,
            task_durable_memory=self.task_durable_memory,
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

    def build_working_memory_context_candidates(self, **payload: Any):
        return self.bundle_service.build_working_memory_context_candidates(**payload)

    def build_task_durable_memory_context_candidates(self, **payload: Any):
        return self.bundle_service.build_task_durable_memory_context_candidates(**payload)

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

    def create_working_memory_item(self, **payload: Any):
        return self.working_memory.create_item(**payload)

    def get_working_memory_item(self, work_memory_id: str):
        return self.working_memory.get_item(work_memory_id)

    def query_working_memory_items(self, **filters: Any):
        return self.working_memory.query_items(**filters)

    def accept_working_memory_item(self, work_memory_id: str, **payload: Any):
        return self.working_memory.accept_item(work_memory_id, **payload)

    def discard_working_memory_item(self, work_memory_id: str, **payload: Any):
        return self.working_memory.discard_item(work_memory_id, **payload)

    def mark_working_memory_conflict(self, work_memory_id: str, **payload: Any):
        return self.working_memory.mark_conflict(work_memory_id, **payload)

    def record_working_memory_read(self, **payload: Any):
        return self.working_memory.record_read(**payload)

    def select_working_memory_for_node(self, **payload: Any):
        return self.working_memory.select_for_node(**payload)

    def list_working_memory_read_logs(self, task_run_id: str = "", *, limit: int = 200):
        return self.working_memory.list_read_logs(task_run_id, limit=limit)

    def create_working_memory_temporal_edge(self, **payload: Any):
        return self.working_memory.create_temporal_edge(**payload)

    def list_working_memory_temporal_edges(self, task_run_id: str = ""):
        return self.working_memory.list_temporal_edges(task_run_id)

    def create_working_memory_handoff_transaction(self, **payload: Any):
        return self.working_memory.create_handoff_transaction(**payload)

    def resolve_working_memory_handoff(self, **payload: Any):
        return self.working_memory.resolve_handoff_into_working_memory(**payload)

    def commit_working_memory_handoff_transaction(self, transaction_id: str, **payload: Any):
        return self.working_memory.commit_handoff_transaction(transaction_id, **payload)

    def list_working_memory_handoff_transactions(self, task_run_id: str = ""):
        return self.working_memory.list_handoff_transactions(task_run_id)

    def save_working_memory_policy_profile(self, **payload: Any):
        return self.working_memory.save_policy_profile(**payload)

    def get_working_memory_policy_profile(self, profile_id: str):
        return self.working_memory.get_policy_profile(profile_id)

    def finalize_working_memory_task_run(self, task_run_id: str, **payload: Any):
        return self.working_memory_finalizer.finalize_task_run(task_run_id, **payload)

    def create_task_durable_memory_item(self, **payload: Any):
        return self.task_durable_memory.create_item(**payload)

    def get_task_durable_memory_item(self, task_memory_id: str):
        return self.task_durable_memory.get_item(task_memory_id)

    def query_task_durable_memory_items(self, **filters: Any):
        return self.task_durable_memory.query_items(**filters)

    def list_task_durable_memory_namespaces(self):
        return self.task_durable_memory.list_namespaces()

    def promote_working_memory_item_to_task_durable(self, work_memory_id: str, **payload: Any) -> dict[str, Any]:
        item = self.working_memory.get_item(work_memory_id)
        if item is None:
            raise KeyError(f"Unknown working memory item: {work_memory_id}")
        task_memory_item = self.task_durable_memory.promote_working_memory_item(item, **payload)
        updated = self.working_memory.store.update_item_lifecycle(
            item.work_memory_id,
            status="promoted",
            promotion_state="promoted_to_task_durable",
            authority="human_gate_adopted",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "promoted_task_memory_id": task_memory_item.task_memory_id,
                "promoted_task_memory_namespace_id": task_memory_item.namespace_id,
                "promoted_task_memory_title": task_memory_item.title,
                "promotion_reason": str(payload.get("reason") or "manual_working_memory_promotion"),
                "promotion_target": "task_durable_memory",
            },
            event_type="promoted_to_task_durable",
        )
        return {
            "task_memory": task_memory_item,
            "item": updated,
        }

    def mark_task_durable_item_global_candidate(self, task_memory_id: str, **payload: Any) -> dict[str, Any]:
        updated = self.task_durable_memory.store.update_lifecycle(
            task_memory_id,
            eligible_for_global_promotion=True,
            global_promotion_state="candidate",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "global_candidate_reason": str(payload.get("reason") or "manual_global_candidate"),
                "global_candidate_actor_id": str(payload.get("actor_id") or "memory_governance_ui"),
            },
            event_type="global_candidate_marked",
        )
        return {"task_memory": updated}

    def promote_task_durable_item_to_global_durable(self, task_memory_id: str, **payload: Any) -> dict[str, Any]:
        item = self.task_durable_memory.get_item(task_memory_id)
        if item is None:
            raise KeyError(f"Unknown task durable memory item: {task_memory_id}")
        if not item.eligible_for_global_promotion and item.global_promotion_state not in {"candidate", "approved"}:
            raise ValueError("Task durable memory item must be marked as global promotion candidate first")
        allowed_kinds = {"user_preference", "system_rule", "cross_task_policy", "global_working_convention"}
        promotion_kind = str(payload.get("global_kind") or item.metadata.get("global_kind") or item.kind or "").strip()
        if promotion_kind not in allowed_kinds:
            raise ValueError("Task durable memory item is not an allowed global promotion kind")
        result = self.create_durable_memory_note(
            title=str(payload.get("title") or item.title or item.task_memory_id),
            canonical_statement=str(payload.get("canonical_statement") or item.canonical_statement or item.summary),
            summary=str(payload.get("summary") or item.summary or item.canonical_statement),
            memory_type=str(payload.get("memory_type") or "project"),
            memory_class=str(payload.get("memory_class") or "work"),
            retrieval_hints=list(item.retrieval_hints)[:8],
            confidence=str(payload.get("confidence") or item.confidence or "medium"),
            source_kind="task_durable_global_promotion",
            source_message_excerpt=(
                f"task_memory_id: {item.task_memory_id}\n"
                f"namespace_id: {item.namespace_id}\n"
                f"task_id: {item.task_id}\n"
                f"graph_id: {item.graph_id}\n"
                f"canonical_statement: {item.canonical_statement}\n"
            )[:1600],
        )
        updated = self.task_durable_memory.store.update_lifecycle(
            task_memory_id,
            eligible_for_global_promotion=True,
            global_promotion_state="promoted_to_global",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "promoted_global_durable_filename": result.get("filename", ""),
                "promoted_global_durable_title": str(payload.get("title") or item.title or item.task_memory_id),
                "global_promotion_reason": str(payload.get("reason") or "manual_task_durable_global_promotion"),
                "global_kind": promotion_kind,
            },
            event_type="promoted_to_global_durable",
        )
        return {
            "filename": result["filename"],
            "header": result.get("header"),
            "task_memory": updated,
        }

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
