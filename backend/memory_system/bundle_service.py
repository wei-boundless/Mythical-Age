from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from context_system.policy import build_context_package_result
from context_system.budget.presets import get_context_budget_preset
from core.token_accounting import count_text_tokens

from .contracts import MemoryContextCandidate
from .continuity import SessionMemoryLayer
from .conversation_memory import ConversationMemoryStoreAdapter
from .runtime_supply import (
    MemoryOrchestrator,
    MemorySupplier,
    abuild_memory_runtime_view as abuild_runtime_view,
    apply_memory_scope_policy,
    build_memory_bundle,
    build_memory_request,
    build_memory_runtime_view as build_runtime_view,
    build_memory_scope_policy,
)
from .state_memory import StateMemoryStoreAdapter
from .working_memory_service import WorkingMemoryService


@dataclass(slots=True, frozen=True)
class MemoryCompactionResult:
    """Read-only context compaction result for runtime adapters."""

    session_id: str
    pressure_level: str = "normal"
    compaction_strategy: str = "none"
    compacted: bool = False
    read_only: bool = True
    authority: str = "memory_compaction_result"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ValueError("MemoryCompactionResult must remain read_only")
        if self.authority != "memory_compaction_result":
            raise ValueError("MemoryCompactionResult cannot carry runtime authority")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryBundleService:
    """Read-only memory supply chain for runtime consumption."""

    def __init__(
        self,
        *,
        session_memory: SessionMemoryLayer,
        conversation_memory: ConversationMemoryStoreAdapter,
        state_memory: StateMemoryStoreAdapter,
        working_memory: WorkingMemoryService,
        durable_memory: Any,
        durable_memory_resolver: Callable[[dict[str, Any] | None], Any] | None = None,
        context_budget_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.session_memory = session_memory
        self.conversation_memory = conversation_memory
        self.state_memory = state_memory
        self.working_memory = working_memory
        self.durable_memory = durable_memory
        self.durable_memory_resolver = durable_memory_resolver
        self._context_budget_provider = context_budget_provider
        self.orchestrator = MemoryOrchestrator()
        self.supplier = MemorySupplier()

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
        environment_scope: dict[str, Any] | None = None,
        global_common_allowed: bool = True,
    ):
        kwargs = self._durable_recall_kwargs(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )
        results = [
            layer.recall_memories(**kwargs)
            for layer in self._durable_layers_for_read(environment_scope, global_common_allowed=global_common_allowed)
        ]
        return self._long_term_candidates_from_results(results, session_id=session_id, query=query, note_limit=note_limit)

    async def abuild_long_term_memory_context_candidates(
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
        environment_scope: dict[str, Any] | None = None,
        global_common_allowed: bool = True,
    ):
        kwargs = self._durable_recall_kwargs(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )
        results = []
        for layer in self._durable_layers_for_read(environment_scope, global_common_allowed=global_common_allowed):
            results.append(await layer.arecall_memories(**kwargs))
        return self._long_term_candidates_from_results(results, session_id=session_id, query=query, note_limit=note_limit)

    def _durable_recall_kwargs(
        self,
        *,
        query: str | None,
        memory_intent: Any | None,
        note_limit: int,
        main_context: dict[str, object] | None,
        task_summaries: list[dict[str, object]] | None,
        session_summary: str,
        recently_surfaced_note_ids: list[str] | None,
        recent_tools: list[str] | None,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "memory_intent": memory_intent,
            "note_limit": note_limit,
            "main_context": main_context,
            "task_summaries": task_summaries,
            "session_summary": session_summary,
            "recently_surfaced_note_ids": recently_surfaced_note_ids,
            "recent_tools": recent_tools,
        }

    def _durable_layers_for_read(self, environment_scope: dict[str, Any] | None, *, global_common_allowed: bool) -> tuple[Any, ...]:
        layers = []
        scoped_layer = self._durable_layer_for_scope(environment_scope)
        if scoped_layer is not self.durable_memory:
            layers.append(scoped_layer)
        if global_common_allowed:
            layers.append(self.durable_memory)
        return tuple(layers)

    def _long_term_candidates_from_results(
        self,
        results: list[Any],
        *,
        session_id: str,
        query: str | None,
        note_limit: int,
    ) -> tuple[MemoryContextCandidate, ...]:
        candidates: list[MemoryContextCandidate] = []
        for result in results:
            candidates.extend(
                _long_term_context_candidates_from_recall_result(
                    result,
                    session_id=session_id,
                    query=str(query or ""),
                )
            )
        return tuple(candidates[: max(1, int(note_limit or 5))])

    def _durable_layer_for_scope(self, environment_scope: dict[str, Any] | None):
        if self.durable_memory_resolver is None:
            return self.durable_memory
        return self.durable_memory_resolver(environment_scope or {})

    def build_memory_runtime_view(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        note_limit: int = 5,
    ):
        return build_runtime_view(
            self,
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            note_limit=note_limit,
            orchestrator=self.orchestrator,
            supplier=self.supplier,
        )

    async def abuild_memory_runtime_view(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        note_limit: int = 5,
    ):
        return await abuild_runtime_view(
            self,
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            note_limit=note_limit,
            orchestrator=self.orchestrator,
            supplier=self.supplier,
        )

    def build_memory_context_package_result(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        memory_view: Any | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        available_context_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        long_term_token_cap: int | None = None,
    ):
        if memory_view is None:
            memory_view = self.build_memory_runtime_view(
                session_id=session_id,
                query=query,
                memory_intent=memory_intent,
                memory_request_profile=memory_request_profile,
                note_limit=note_limit,
            )
        return self._build_context_package_result_from_view(
            memory_view,
            retrieval_results=retrieval_results,
            available_context_tokens=available_context_tokens,
            reserved_output_tokens=reserved_output_tokens,
            long_term_token_cap=long_term_token_cap,
        )

    async def abuild_memory_context_package_result(
        self,
        *,
        session_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        memory_view: Any | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
        available_context_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        long_term_token_cap: int | None = None,
    ):
        if memory_view is None:
            memory_view = await self.abuild_memory_runtime_view(
                session_id=session_id,
                query=query,
                memory_intent=memory_intent,
                memory_request_profile=memory_request_profile,
                note_limit=note_limit,
            )
        return self._build_context_package_result_from_view(
            memory_view,
            retrieval_results=retrieval_results,
            available_context_tokens=available_context_tokens,
            reserved_output_tokens=reserved_output_tokens,
            long_term_token_cap=long_term_token_cap,
        )

    def _build_context_package_result_from_view(
        self,
        memory_view: Any,
        *,
        retrieval_results: list[dict[str, Any]] | None = None,
        available_context_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        long_term_token_cap: int | None = None,
    ):
        budget = self._context_budget()
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
        memory_view: Any | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
    ):
        return self.build_memory_context_package_result(
            session_id=session_id,
            query=pending_user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            memory_view=memory_view,
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
        note_limit: int = 5,
    ):
        request = build_memory_request(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
            reason="memory_bundle_service_bundle_request",
        )
        scope_policy = build_memory_scope_policy(
            agent_id=agent_id,
            memory_request_profile=memory_request_profile,
        )
        request = apply_memory_scope_policy(request, scope_policy)
        runtime_view = self.build_memory_runtime_view(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=request.to_dict(),
            note_limit=note_limit,
        )
        context_result = self.build_memory_context_package_result(
            session_id=session_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=request.to_dict(),
            memory_view=runtime_view,
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
        memory_view = self.build_memory_runtime_view(
            session_id=session_id,
            memory_request_profile={"requested_memory_layers": ["state", "conversation"]},
        )
        return MemoryCompactionResult(
            session_id=session_id,
            diagnostics={
                "history_count": len(history or []),
                "context_candidate_count": len(memory_view.context_candidates),
                "restore_candidate_count": len(memory_view.restore_candidates),
            },
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
        environment_scope: dict[str, Any] | None = None,
    ):
        layer = self._durable_layer_for_scope(environment_scope)
        return layer.recall_memories(
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
        environment_scope: dict[str, Any] | None = None,
    ):
        layer = self._durable_layer_for_scope(environment_scope)
        return await layer.arecall_memories(
            query=query,
            memory_intent=memory_intent,
            note_limit=note_limit,
            main_context=main_context,
            task_summaries=task_summaries,
            session_summary=session_summary,
            recently_surfaced_note_ids=recently_surfaced_note_ids,
            recent_tools=recent_tools,
        )

    def describe_durable_maintenance_runtime(self) -> dict[str, object]:
        return self.durable_memory.describe_maintenance_runtime()

    def _context_budget(self) -> dict[str, Any]:
        default_budget = get_context_budget_preset("deepseek_1m").to_dict()
        if self._context_budget_provider is not None:
            payload = dict(self._context_budget_provider())
            if not payload:
                raise ValueError("context budget provider returned an empty payload")
            return {**default_budget, **payload}
        return default_budget

def _long_term_context_candidates_from_recall_result(
    recall_result: Any,
    *,
    session_id: str = "",
    query: str = "",
) -> tuple[MemoryContextCandidate, ...]:
    selected_notes = list(getattr(recall_result, "selected_notes", []) or [])
    if not selected_notes and isinstance(recall_result, dict):
        selected_notes = list(recall_result.get("selected_notes", []) or [])
    candidates: list[MemoryContextCandidate] = []
    for index, note in enumerate(selected_notes):
        payload = dict(note or {}) if isinstance(note, dict) else _note_to_dict(note)
        note_id = str(payload.get("note_id", "") or payload.get("filename", "") or f"note-{index}").strip()
        title = str(payload.get("title", "") or note_id).strip()
        canonical = str(payload.get("canonical_statement", "") or "").strip()
        summary = str(payload.get("summary", "") or "").strip()
        content = str(payload.get("content", "") or "").strip()
        namespace_id = str(payload.get("namespace_id", "") or "global_common")
        preview = _render_long_term_preview(title=title, canonical=canonical, summary=summary, content=content)
        if not preview:
            continue
        candidates.append(
            MemoryContextCandidate(
                candidate_id=f"memory-context:{session_id or 'session'}:long-term:{namespace_id}:{note_id}",
                memory_layer="long_term",
                source="durable_memory.recall",
                content_ref=str(payload.get("filename", "") or note_id),
                rendered_preview=preview,
                relevance=0.7,
                confidence=_confidence_score(str(payload.get("confidence", "") or "")),
                staleness="durable_memory_may_drift",
                token_estimate=max(1, count_text_tokens(preview)),
                budget_class="optional",
                requires_verification_before_use=True,
                metadata={
                    "query": query,
                    "memory_type": str(payload.get("memory_type", "") or ""),
                    "memory_class": str(payload.get("memory_class", "") or ""),
                    "status": str(payload.get("status", "") or ""),
                    "namespace_id": namespace_id,
                    "verification_policy": "verify_file_function_flag_claims_against_current_state",
                },
            )
        )
    return tuple(candidates)


def _note_to_dict(note: Any) -> dict[str, object]:
    slug = str(getattr(note, "slug", "") or "")
    filename = str(getattr(note, "filename", "") or "")
    return {
        "note_id": str(getattr(note, "note_id", "") or slug or filename.replace(".md", "")),
        "filename": filename or (f"{slug}.md" if slug else ""),
        "title": str(getattr(note, "title", "") or ""),
        "summary": str(getattr(note, "summary", "") or ""),
        "canonical_statement": str(getattr(note, "canonical_statement", "") or ""),
        "content": str(getattr(note, "content", "") or getattr(note, "body", "") or ""),
        "memory_type": str(getattr(note, "memory_type", "") or ""),
        "memory_class": str(getattr(note, "memory_class", "") or ""),
        "confidence": str(getattr(note, "confidence", "") or ""),
        "status": str(getattr(note, "status", "") or ""),
        "namespace_id": str(getattr(note, "namespace_id", "") or ""),
    }


def _render_long_term_preview(*, title: str, canonical: str, summary: str, content: str) -> str:
    lines: list[str] = []
    if title:
        lines.append(f"### {title}")
    if canonical:
        lines.append(f"Canonical: {canonical}")
    elif summary:
        lines.append(f"Canonical: {summary}")
    if summary and summary != canonical:
        lines.append(f"Summary: {summary}")
    detail = " ".join(line.strip(" -#*\t") for line in content.splitlines() if line.strip())[:280].strip()
    if detail and detail not in {canonical, summary}:
        lines.append(f"Details: {detail}")
    return "\n".join(lines).strip()


def _confidence_score(confidence: str) -> float:
    normalized = str(confidence or "").strip().lower()
    if normalized == "high":
        return 0.82
    if normalized == "low":
        return 0.35
    if normalized == "medium":
        return 0.6
    return 0.5



