from __future__ import annotations

from typing import Any, Callable

from context_policy import build_context_package_result
from context_management.budget_presets import get_context_budget_preset

from .compaction import build_memory_compaction_result
from .conversation_memory import ConversationMemoryStoreAdapter
from .long_term_memory import LongTermMemoryStoreAdapter
from .request_service import MemoryRequestService
from .runtime_view import build_memory_runtime_view as build_runtime_view
from .session import SessionMemoryLayer
from .state_memory import StateMemoryStoreAdapter
from .task_durable_memory_service import TaskDurableMemoryService
from .supply import build_memory_bundle
from .working_memory_service import WorkingMemoryService


class MemoryBundleService:
    """Read-only memory supply chain for runtime consumption."""

    def __init__(
        self,
        *,
        session_memory: SessionMemoryLayer,
        conversation_memory: ConversationMemoryStoreAdapter,
        state_memory: StateMemoryStoreAdapter,
        working_memory: WorkingMemoryService,
        long_term_memory: LongTermMemoryStoreAdapter,
        task_durable_memory: TaskDurableMemoryService | None = None,
        durable_memory: Any,
        request_service: MemoryRequestService,
        context_budget_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.session_memory = session_memory
        self.conversation_memory = conversation_memory
        self.state_memory = state_memory
        self.working_memory = working_memory
        self.task_durable_memory = task_durable_memory
        self.long_term_memory = long_term_memory
        self.durable_memory = durable_memory
        self.request_service = request_service
        self._context_budget_provider = context_budget_provider

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

    def build_working_memory_context_candidates(
        self,
        *,
        task_run_id: str = "",
        task_id: str = "",
        graph_id: str = "",
        owner_node_id: str = "",
        node_run_id: str = "",
        run_attempt_id: str = "",
        requested_kinds: list[str] | tuple[str, ...] = (),
        requested_semantics: list[str] | tuple[str, ...] = (),
        limit: int = 20,
    ):
        return self.working_memory.context_candidates(
            task_run_id=task_run_id,
            task_id=task_id,
            graph_id=graph_id,
            owner_node_id=owner_node_id,
            node_run_id=node_run_id,
            run_attempt_id=run_attempt_id,
            requested_kinds=requested_kinds,
            requested_semantics=requested_semantics,
            limit=limit,
        )

    def build_task_durable_memory_context_candidates(
        self,
        *,
        namespace_id: str = "",
        task_family: str = "",
        domain_id: str = "",
        task_id: str = "",
        graph_id: str = "",
        project_id: str = "",
        artifact_namespace: str = "",
        requested_kinds: list[str] | tuple[str, ...] = (),
        requested_semantics: list[str] | tuple[str, ...] = (),
        limit: int = 20,
    ):
        if self.task_durable_memory is None:
            return ()
        return self.task_durable_memory.context_candidates(
            namespace_id=namespace_id,
            task_family=task_family,
            domain_id=domain_id,
            task_id=task_id,
            graph_id=graph_id,
            project_id=project_id,
            artifact_namespace=artifact_namespace,
            requested_kinds=requested_kinds,
            requested_semantics=requested_semantics,
            limit=limit,
        )

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
        memory_request_profile: dict[str, Any] | None = None,
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
    ):
        return build_runtime_view(
            self,
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
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
        budget = self._context_budget()
        memory_view = self.build_memory_runtime_view(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        return build_context_package_result(
            memory_view,
            rebuild_reason="memory_bundle_service_context_package_result",
            retrieval_results=retrieval_results,
            available_context_tokens=available_context_tokens
            if available_context_tokens is not None
            else int(budget["available_context_tokens"]),
            reserved_output_tokens=reserved_output_tokens
            if reserved_output_tokens is not None
            else int(budget["reserved_output_tokens"]),
            long_term_token_cap=long_term_token_cap
            if long_term_token_cap is not None
            else int(budget["long_term_token_cap"]),
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
        return self.build_memory_context_package_result(
            session_id=session_id,
            query=pending_user_message,
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
        request, _scope_policy = self.request_service.build_effective_memory_request(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
            reason="memory_bundle_service_bundle_request",
        )
        runtime_view = self.build_memory_runtime_view(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=request.to_dict(),
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        context_result = self.build_memory_context_package_result(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=request.to_dict(),
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
        return build_memory_bundle(
            request=request,
            runtime_view=runtime_view,
            context_policy_result=context_result,
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

    def build_persistent_memory_block(
        self,
        *,
        query: str | None = None,
        memory_intent: Any | None = None,
        note_limit: int = 5,
        relevant_notes: list[Any] | None = None,
    ) -> str:
        candidates = self.build_long_term_memory_context_candidates(
            session_id="persistent_memory_preview",
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            relevant_notes=relevant_notes,
        )
        return "\n\n".join(
            candidate.rendered_preview for candidate in candidates if candidate.rendered_preview
        ).strip()

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

    def prefetch_relevant_notes(
        self,
        query: str,
        memory_intent: Any | None = None,
        *,
        limit: int = 3,
    ) -> list[Any]:
        return self.durable_memory.prefetch_relevant_notes(query, memory_intent, limit=limit)

    def describe_durable_maintenance_runtime(self) -> dict[str, object]:
        return self.durable_memory.describe_maintenance_runtime()

    def _context_budget(self) -> dict[str, Any]:
        if self._context_budget_provider is not None:
            try:
                payload = dict(self._context_budget_provider())
                if payload:
                    return payload
            except Exception:
                pass
        return get_context_budget_preset("deepseek_1m").to_dict()
