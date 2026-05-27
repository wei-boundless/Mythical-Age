from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from config import get_settings

if TYPE_CHECKING:
    from capability_system.units.mcp.local.retrieval.router import RAGQueryRouter
    from knowledge_system.indexing import RetrievalBootstrapper, RetrievalRequest

logger = logging.getLogger(__name__)


RetrievalExecutionStatus = Literal["ok", "empty", "error"]


@dataclass(slots=True, frozen=True)
class RetrievalFailureDiagnostics:
    query: str
    selected_collections: tuple[str, ...] = ()
    query_mode: str = ""
    failure_stage: str = ""
    error_type: str = ""
    error_message: str = ""
    candidate_top_k: int = 0
    requested_top_k: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "selected_collections": list(self.selected_collections),
            "query_mode": self.query_mode,
            "failure_stage": self.failure_stage,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "candidate_top_k": self.candidate_top_k,
            "requested_top_k": self.requested_top_k,
        }


@dataclass(slots=True, frozen=True)
class RetrievalExecutionResult:
    status: RetrievalExecutionStatus
    results: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    degraded_reason_typed: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "results": [dict(item) for item in self.results],
            "diagnostics": dict(self.diagnostics),
            "degraded_reason_typed": self.degraded_reason_typed,
        }


class RetrievalService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._settings = get_settings()
        self._router: RAGQueryRouter | Any | None = None
        self._bootstrapper: RetrievalBootstrapper | Any | None = None
        self._collection_rebuild_locks: dict[str, threading.Lock] = {}
        self._collection_rebuild_locks_guard = threading.Lock()
        self._collection_rebuild_pending: dict[str, bool] = {}

    @property
    def router(self) -> Any:
        if self._router is None:
            from capability_system.units.mcp.local.retrieval.router import RAGQueryRouter

            self._router = RAGQueryRouter(self.base_dir)
        return self._router

    @router.setter
    def router(self, value: Any) -> None:
        self._router = value

    @property
    def bootstrapper(self) -> Any:
        if self._bootstrapper is None:
            from knowledge_system.indexing import RetrievalBootstrapper

            self._bootstrapper = RetrievalBootstrapper(self.base_dir)
        return self._bootstrapper

    @bootstrapper.setter
    def bootstrapper(self, value: Any) -> None:
        self._bootstrapper = value

    def retrieve(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        return list(self.retrieve_execution(query, top_k=top_k).results)

    def retrieve_execution(self, query: str, *, top_k: int = 5) -> RetrievalExecutionResult:
        try:
            plan = self.router.plan(query)
        except Exception as exc:
            logger.exception("Failed to build retrieval plan")
            diagnostics = RetrievalFailureDiagnostics(
                query=str(query or ""),
                failure_stage="plan",
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                requested_top_k=max(int(top_k or 1), 1),
            )
            return RetrievalExecutionResult(
                status="error",
                diagnostics={
                    "result_count": 0,
                    "retrieval_failure": diagnostics.to_dict(),
                },
                degraded_reason_typed="retrieval_plan_failed",
            )
        return self._retrieve_execution_from_plan(plan, top_k=top_k)

    def retrieve_memory(self, query: str, *, top_k: int = 3) -> list[dict[str, Any]]:
        from knowledge_system.indexing import RetrievalRequest

        hits = self.bootstrapper.backend.retrieve(
            RetrievalRequest(
                query=query,
                top_k=max(int(top_k or 1), 1),
                query_mode="semantic_lookup",
                collections=("durable_memory", "session_memory"),
            )
        )
        payload: list[dict[str, Any]] = []
        for hit in hits[:top_k]:
            payload.append(
                {
                    "text": hit.text,
                    "score": float(hit.score or 0.0),
                    "source": hit.source,
                    "collection": str(getattr(hit, "metadata", {}).get("collection", "") or "durable_memory"),
                    "retrieval_backend": "llamaindex",
                    "metadata": {
                        **dict(getattr(hit, "metadata", {}) or {}),
                        "doc_id": getattr(hit, "doc_id", None),
                        "block_id": getattr(hit, "block_id", None),
                        "object_ref_id": getattr(hit, "object_ref_id", None),
                    },
                }
            )
        return payload

    def rebuild_registry_collection(self, name: str) -> None:
        try:
            self.router.registry.rebuild(name)
        except Exception:
            pass

    def rebuild_durable_memory(self) -> None:
        self.rebuild_collection("durable_memory")

    def rebuild_session_memory(self) -> None:
        self.rebuild_collection("session_memory")

    def rebuild_knowledge(self) -> None:
        self.rebuild_collection("knowledge")

    def rebuild_collection(self, name: str) -> dict[str, Any]:
        from capability_system.units.mcp.local.retrieval.collections import build_default_collections

        config = build_default_collections(self.base_dir).get(name)
        if config is None:
            return {"collection": name, "status": "missing_collection"}
        lock = self._collection_rebuild_lock(name)
        acquired = lock.acquire(blocking=False)
        if not acquired:
            self._collection_rebuild_pending[name] = True
            return {"collection": name, "status": "rebuild_already_running"}
        try:
            self._collection_rebuild_pending.pop(name, None)
            return self._rebuild_collection_once(name, config)
        except Exception as exc:
            logger.exception("Failed to rebuild retrieval collection %s", name)
            return {"collection": name, "status": "error", "error": str(exc)}
        finally:
            lock.release()

    def _rebuild_collection_once(self, name: str, config) -> dict[str, Any]:
        result = self.bootstrapper.rebuild_collection(config)
        return {
            "collection": result.collection,
            "status": str(result.index_payload.get("status", "unknown")),
            "discovered_files": result.discovered_files,
            "converted_documents": result.converted_documents,
            "normalized_blocks": result.normalized_blocks,
            "normalized_objects": result.normalized_objects,
            "indexable_units": result.indexable_units,
            "parser_backends": list(result.parser_backends),
            "index_payload": dict(result.index_payload),
        }

    def _collection_rebuild_lock(self, name: str) -> threading.Lock:
        normalized = str(name or "").strip().lower()
        with self._collection_rebuild_locks_guard:
            lock = self._collection_rebuild_locks.get(normalized)
            if lock is None:
                lock = threading.Lock()
                self._collection_rebuild_locks[normalized] = lock
            return lock

    def rebuild_all_collections(self) -> dict[str, dict[str, Any]]:
        payload: dict[str, dict[str, Any]] = {}
        for name in ("durable_memory", "session_memory", "knowledge"):
            payload[name] = self.rebuild_collection(name)
        return payload

    def rebuild_all(self) -> None:
        self.rebuild_durable_memory()
        self.rebuild_session_memory()
        self.rebuild_knowledge()

    def audit_memory_sources(self) -> dict[str, Any]:
        from knowledge_system.conversion import discover_source_files
        from capability_system.units.mcp.local.retrieval.collections import build_default_collections

        payload: dict[str, Any] = {}
        collections = build_default_collections(self.base_dir)
        for name in ("durable_memory", "session_memory"):
            config = collections.get(name)
            if config is None:
                continue
            records = discover_source_files(config, backend_dir=self.base_dir)
            payload[name] = {
                "source_count": len(records),
                "indexed_sources": [record.source_path for record in records],
            }
        return payload

    def _retrieve_from_plan(self, plan: Any, *, top_k: int) -> list[dict[str, Any]]:
        from knowledge_system.indexing import RetrievalRequest

        candidate_top_k = self._candidate_top_k(top_k)
        runtime_descriptor = self._runtime_descriptor()
        hits = self.bootstrapper.backend.retrieve(
            RetrievalRequest(
                query=str(plan.rewritten_query or plan.query),
                top_k=candidate_top_k,
                query_mode=self._query_mode_from_plan(plan),
                collections=tuple(plan.selected_collections),
                filters=self._filters_from_plan(plan),
            )
        )
        payload: list[dict[str, Any]] = []
        for candidate_rank, hit in enumerate(hits[:candidate_top_k], start=1):
            score_breakdown = dict(getattr(hit, "score_breakdown", {}) or {})
            score_breakdown.setdefault("retrieval_score", float(hit.score or 0.0))
            payload.append(
                {
                    "text": hit.text,
                    "source": hit.source,
                    "modality": hit.modality,
                    "page": hit.page,
                    "score": hit.score,
                    "retrieval_score": hit.score,
                    "candidate_rank": candidate_rank,
                    "collection": self._collection_from_hit(hit, plan),
                    "reason": str(plan.reason or ""),
                    "rewritten_query": str(plan.rewritten_query or plan.query),
                    "rewrite_keywords": list(getattr(plan.rewrite, "keywords", []) or []),
                    "rewrite_rules": list(getattr(plan.rewrite, "applied_rules", []) or []),
                    "retrieval_backend": "llamaindex",
                    "result_granularity": str(dict(hit.metadata).get("result_granularity", "") or "block"),
                    "score_breakdown": score_breakdown,
                    "chain_version": str(runtime_descriptor.get("chain_version", "") or ""),
                    "metadata": {
                        **dict(hit.metadata),
                        "doc_id": hit.doc_id,
                        "block_id": hit.block_id,
                        "object_ref_id": hit.object_ref_id,
                        "block_type": hit.block_type,
                        "section_path": list(hit.section_path),
                        "retrieval_modes": list(hit.retrieval_modes),
                        "parser_backend": hit.parser_backend,
                        "quality_flags": list(hit.quality_flags),
                    },
                }
            )
        reranked = self._rerank_payload(query=str(plan.query or plan.rewrite.original_query), payload=payload)
        finalized: list[dict[str, Any]] = []
        for rerank_rank, item in enumerate(reranked, start=1):
            updated = dict(item)
            updated["rerank_rank"] = rerank_rank
            finalized.append(updated)
        return finalized[:top_k]

    def _retrieve_execution_from_plan(self, plan: Any, *, top_k: int) -> RetrievalExecutionResult:
        candidate_top_k = self._candidate_top_k(top_k)
        query = str(getattr(plan, "query", "") or "")
        query_mode = self._query_mode_from_plan(plan)
        selected_collections = tuple(str(item) for item in list(getattr(plan, "selected_collections", []) or []))
        try:
            results = self._retrieve_from_plan(plan, top_k=top_k)
        except Exception as exc:
            logger.exception("Failed to execute retrieval plan")
            diagnostics = RetrievalFailureDiagnostics(
                query=query,
                selected_collections=selected_collections,
                query_mode=query_mode,
                failure_stage=self._failure_stage_from_exception(exc),
                error_type=exc.__class__.__name__,
                error_message=str(exc),
                candidate_top_k=candidate_top_k,
                requested_top_k=max(int(top_k or 1), 1),
            )
            return RetrievalExecutionResult(
                status="error",
                diagnostics={
                    "result_count": 0,
                    "retrieval_failure": diagnostics.to_dict(),
                    "plan_reason": str(getattr(plan, "reason", "") or ""),
                },
                degraded_reason_typed="retrieval_execution_failed",
            )
        status: RetrievalExecutionStatus = "ok" if results else "empty"
        retrieval_plan_diagnostics = self._retrieval_plan_diagnostics(plan)
        return RetrievalExecutionResult(
            status=status,
            results=tuple(dict(item) for item in results),
            diagnostics={
                "result_count": len(results),
                "query_mode": query_mode,
                "selected_collections": list(selected_collections),
                "plan_reason": str(getattr(plan, "reason", "") or ""),
                "retrieval_plan": retrieval_plan_diagnostics,
                "evidence_pack": self._evidence_pack_diagnostics(
                    query=query,
                    results=results,
                    retrieval_plan=retrieval_plan_diagnostics,
                ),
            },
        )

    def _retrieval_plan_diagnostics(self, plan: Any) -> dict[str, Any]:
        retrieval_plan = getattr(plan, "retrieval_plan", None)
        to_dict = getattr(retrieval_plan, "to_dict", None)
        if callable(to_dict):
            return dict(to_dict())
        return {
            "filters": dict(getattr(plan, "filters", {}) or {}),
            "policy": dict(getattr(plan, "policy", {}) or {}),
        }

    def _filters_from_plan(self, plan: Any) -> dict[str, Any]:
        retrieval_plan = getattr(plan, "retrieval_plan", None)
        filters = getattr(retrieval_plan, "filters", None)
        to_dict = getattr(filters, "to_dict", None)
        if callable(to_dict):
            return dict(to_dict())
        return dict(getattr(plan, "filters", {}) or {})

    def _evidence_pack_diagnostics(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        retrieval_plan: dict[str, Any],
    ) -> dict[str, Any]:
        from knowledge_system.retrieval.evidence_packager import build_evidence_pack

        return build_evidence_pack(
            query=query,
            results=results,
            retrieval_plan=retrieval_plan,
        ).to_dict()

    def _rerank_payload(self, *, query: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payload:
            return payload
        reranker = getattr(self.router, "reranker", None)
        rerank = getattr(reranker, "rerank_dict_results", None)
        if not callable(rerank):
            return payload
        try:
            ranked = rerank(query=query, results=payload)
        except Exception:
            logger.exception("Failed to rerank retrieval payload")
            return payload
        return [dict(item) for item in ranked]

    def _candidate_top_k(self, top_k: int) -> int:
        requested = max(int(top_k or 1), 1)
        if not bool(getattr(self._settings, "rerank_enabled", False)):
            return max(requested, 8)
        rerank_top_n = max(int(getattr(self._settings, "rerank_top_n", requested) or requested), 1)
        rerank_candidate_pool = max(int(getattr(self._settings, "rerank_candidate_pool", 20) or 20), 1)
        return max(requested, rerank_top_n, rerank_candidate_pool)

    def _query_mode_from_plan(self, plan: Any) -> str:
        query_type = str(getattr(plan.rewrite, "query_type", "") or "")
        if query_type == "pdf_page":
            return "page_grounded_lookup"
        if query_type == "table":
            return "table_lookup"
        if query_type == "document":
            return "document_overview"
        return "semantic_lookup"

    def _collection_from_hit(self, hit: Any, plan: Any) -> str:
        metadata = dict(getattr(hit, "metadata", {}) or {})
        collection = str(metadata.get("collection", "") or "").strip()
        if collection:
            return collection
        collections = list(getattr(plan, "selected_collections", []) or [])
        return collections[0] if collections else "knowledge"

    def _payload_mode_counts(self, payload: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"dense": 0, "lexical": 0, "fusion": 0}
        for item in payload:
            metadata = dict(item.get("metadata", {}) or {})
            modes = [str(mode) for mode in metadata.get("retrieval_modes", []) or []]
            if "dense" in modes:
                counts["dense"] += 1
            if "lexical" in modes:
                counts["lexical"] += 1
            if "fusion" in modes or len(modes) > 1:
                counts["fusion"] += 1
        return counts

    def _payload_granularity_counts(self, payload: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"document": 0, "page": 0, "block": 0, "object": 0}
        for item in payload:
            granularity = str(item.get("result_granularity", "") or dict(item.get("metadata", {}) or {}).get("result_granularity", "") or "block")
            if granularity not in counts:
                counts[granularity] = 0
            counts[granularity] += 1
        return counts

    def _runtime_descriptor(self) -> dict[str, Any]:
        descriptor = getattr(self.bootstrapper.backend, "runtime_descriptor", None)
        if callable(descriptor):
            return dict(descriptor())
        return {"chain_version": "", "strategy_name": ""}

    def _failure_stage_from_exception(self, exc: Exception) -> str:
        message = str(exc or "").lower()
        if "rerank" in message:
            return "rerank"
        if "retrieve" in message or "index" in message or "faiss" in message:
            return "backend"
        return "execution"


