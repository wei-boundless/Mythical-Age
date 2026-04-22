from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from config import runtime_config

if TYPE_CHECKING:
    from RAG.router import RAGQueryRouter
    from retrieval_core import RetrievalRequest, RetrievalV2Bootstrapper

logger = logging.getLogger(__name__)


class RetrievalService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._last_shadow_compare: dict[str, Any] | None = None
        self._settings = get_settings()
        self._router: RAGQueryRouter | Any | None = None
        self._v2_bootstrapper: RetrievalV2Bootstrapper | Any | None = None

    @property
    def router(self) -> Any:
        if self._router is None:
            from RAG.router import RAGQueryRouter

            self._router = RAGQueryRouter(self.base_dir)
        return self._router

    @router.setter
    def router(self, value: Any) -> None:
        self._router = value

    @property
    def v2_bootstrapper(self) -> Any:
        if self._v2_bootstrapper is None:
            from retrieval_core import RetrievalV2Bootstrapper

            self._v2_bootstrapper = RetrievalV2Bootstrapper(self.base_dir)
        return self._v2_bootstrapper

    @v2_bootstrapper.setter
    def v2_bootstrapper(self, value: Any) -> None:
        self._v2_bootstrapper = value

    def retrieve(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        mode = runtime_config.get_retrieval_cutover_mode()
        if mode == "legacy_only":
            return self.router.retrieve(query, top_k=top_k)

        plan = self.router.plan(query)
        v2_started = time.perf_counter()
        v2_payload = self._retrieve_v2_from_plan(plan, top_k=top_k)
        v2_latency_ms = (time.perf_counter() - v2_started) * 1000.0
        if mode == "shadow_read":
            legacy_started = time.perf_counter()
            legacy_payload = self.router.retrieve(query, top_k=top_k)
            legacy_latency_ms = (time.perf_counter() - legacy_started) * 1000.0
            self._record_shadow_compare(
                query,
                legacy_payload,
                v2_payload,
                plan=plan,
                legacy_latency_ms=legacy_latency_ms,
                v2_latency_ms=v2_latency_ms,
            )
            return legacy_payload
        if mode == "v2_primary":
            if runtime_config.get_retrieval_shadow_compare():
                legacy_started = time.perf_counter()
                legacy_payload = self.router.retrieve(query, top_k=top_k)
                legacy_latency_ms = (time.perf_counter() - legacy_started) * 1000.0
                self._record_shadow_compare(
                    query,
                    legacy_payload,
                    v2_payload,
                    plan=plan,
                    legacy_latency_ms=legacy_latency_ms,
                    v2_latency_ms=v2_latency_ms,
                )
            return v2_payload
        return self.router.retrieve(query, top_k=top_k)

    def retrieve_memory(self, query: str, *, top_k: int = 3) -> list[dict[str, Any]]:
        from retrieval_core import RetrievalRequest

        hits = self.v2_bootstrapper.backend.retrieve(
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
                    "retrieval_backend": "llamaindex_v2",
                    "metadata": {
                        **dict(getattr(hit, "metadata", {}) or {}),
                        "doc_id": getattr(hit, "doc_id", None),
                        "block_id": getattr(hit, "block_id", None),
                        "object_ref_id": getattr(hit, "object_ref_id", None),
                    },
                }
            )
        return payload

    def rebuild_collection(self, name: str) -> None:
        try:
            self.router.registry.rebuild(name)
        except Exception:
            pass

    def rebuild_durable_memory(self) -> None:
        self.rebuild_collection_v2("durable_memory")

    def rebuild_session_memory(self) -> None:
        self.rebuild_collection_v2("session_memory")

    def rebuild_knowledge(self) -> None:
        self.rebuild_collection_v2("knowledge")

    def rebuild_collection_v2(self, name: str) -> dict[str, Any]:
        from RAG.collections import build_default_collections

        config = build_default_collections(self.base_dir).get(name)
        if config is None:
            return {"collection": name, "status": "missing_collection"}
        try:
            result = self.v2_bootstrapper.rebuild_collection(config)
            payload = {
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
            return payload
        except Exception as exc:
            logger.exception("Failed to rebuild v2 collection %s", name)
            return {"collection": name, "status": "error", "error": str(exc)}

    def rebuild_knowledge_v2(self) -> dict[str, Any]:
        return self.rebuild_collection_v2("knowledge")

    def rebuild_all_v2(self) -> dict[str, dict[str, Any]]:
        payload: dict[str, dict[str, Any]] = {}
        for name in ("durable_memory", "session_memory", "knowledge"):
            payload[name] = self.rebuild_collection_v2(name)
        return payload

    def rebuild_all(self) -> None:
        self.rebuild_durable_memory()
        self.rebuild_session_memory()
        self.rebuild_knowledge()

    def audit_memory_sources(self) -> dict[str, Any]:
        from document_conversion import discover_source_files
        from RAG.collections import build_default_collections

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

    def last_shadow_compare(self) -> dict[str, Any] | None:
        return dict(self._last_shadow_compare) if self._last_shadow_compare is not None else None

    def _retrieve_v2_from_plan(self, plan: Any, *, top_k: int) -> list[dict[str, Any]]:
        from retrieval_core import RetrievalRequest

        candidate_top_k = self._v2_candidate_top_k(top_k)
        hits = self.v2_bootstrapper.backend.retrieve(
            RetrievalRequest(
                query=str(plan.rewritten_query or plan.query),
                top_k=candidate_top_k,
                query_mode=self._query_mode_from_plan(plan),
                collections=tuple(plan.selected_collections),
            )
        )
        payload: list[dict[str, Any]] = []
        for hit in hits[:candidate_top_k]:
            payload.append(
                {
                    "text": hit.text,
                    "source": hit.source,
                    "modality": hit.modality,
                    "page": hit.page,
                    "score": hit.score,
                    "collection": self._collection_from_hit(hit, plan),
                    "reason": str(plan.reason or ""),
                    "rewritten_query": str(plan.rewritten_query or plan.query),
                    "rewrite_keywords": list(getattr(plan.rewrite, "keywords", []) or []),
                    "rewrite_rules": list(getattr(plan.rewrite, "applied_rules", []) or []),
                    "retrieval_backend": "llamaindex_v2",
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
        reranked = self._rerank_v2_payload(query=str(plan.query or plan.rewrite.original_query), payload=payload)
        return reranked[:top_k]

    def _rerank_v2_payload(self, *, query: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payload:
            return payload
        reranker = getattr(self.router, "reranker", None)
        rerank = getattr(reranker, "rerank_dict_results", None)
        if not callable(rerank):
            return payload
        try:
            ranked = rerank(query=query, results=payload)
        except Exception:
            logger.exception("Failed to rerank v2 payload")
            return payload
        return [dict(item) for item in ranked]

    def _v2_candidate_top_k(self, top_k: int) -> int:
        rerank_top_n = int(getattr(self._settings, "rerank_top_n", 8) or 8)
        return max(int(top_k or 1), rerank_top_n, 8)

    def _record_shadow_compare(
        self,
        query: str,
        legacy_payload: list[dict[str, Any]],
        v2_payload: list[dict[str, Any]],
        *,
        plan: Any,
        legacy_latency_ms: float | None = None,
        v2_latency_ms: float | None = None,
    ) -> None:
        mode_counts = self._payload_mode_counts(v2_payload)
        compare = {
            "query": query,
            "query_mode": self._query_mode_from_plan(plan),
            "collections": list(plan.selected_collections),
            "legacy_hit_count": len(legacy_payload),
            "v2_hit_count": len(v2_payload),
            "legacy_top_sources": [str(item.get("source", "")) for item in legacy_payload[:3]],
            "v2_top_sources": [str(item.get("source", "")) for item in v2_payload[:3]],
            "legacy_latency_ms": round(float(legacy_latency_ms or 0.0), 3) if legacy_latency_ms is not None else None,
            "v2_latency_ms": round(float(v2_latency_ms or 0.0), 3) if v2_latency_ms is not None else None,
            "retrieval_backend": "llamaindex_v2",
            "dense_hit_count": mode_counts["dense"],
            "lexical_hit_count": mode_counts["lexical"],
            "fusion_hit_count": mode_counts["fusion"],
        }
        self._last_shadow_compare = compare
        logger.info("retrieval shadow compare: %s", compare)

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
            if len(modes) > 1:
                counts["fusion"] += 1
        return counts
