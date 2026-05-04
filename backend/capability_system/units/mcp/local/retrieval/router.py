from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .collections import build_default_collections
from .models import RetrievalHit
from .query_rewriter import QueryRewriteResult, QueryRewriter

if TYPE_CHECKING:
    from .registry import RAGIndexRegistry
    from .reranker import DictReranker


@dataclass(slots=True)
class RoutePlan:
    query: str
    rewritten_query: str
    selected_collections: list[str]
    reason: str
    rewrite: QueryRewriteResult


class RAGQueryRouter:
    def __init__(self, base_dir: Path, *, ocr_language: str = "eng") -> None:
        self.base_dir = base_dir
        self.ocr_language = ocr_language
        self.collection_configs = build_default_collections(base_dir)
        self.rewriter = QueryRewriter()
        self._settings: Any | None = None
        self._registry: RAGIndexRegistry | Any | None = None
        self._reranker: DictReranker | Any | None = None

    @property
    def settings(self) -> Any:
        if self._settings is None:
            from config import get_settings

            self._settings = get_settings()
        return self._settings

    @property
    def registry(self) -> Any:
        if self._registry is None:
            from .registry import RAGIndexRegistry

            self._registry = RAGIndexRegistry(self.base_dir, ocr_language=self.ocr_language)
        return self._registry

    @property
    def reranker(self) -> Any:
        if self._reranker is None:
            from config import get_settings

            from .reranker import build_reranker

            self._reranker = build_reranker(get_settings())
        return self._reranker

    def _chat_enabled_collections(self) -> set[str]:
        return {
            name
            for name, config in self.collection_configs.items()
            if config.allow_chat_queries
        }

    def plan(self, query: str) -> RoutePlan:
        rewrite = self.rewriter.rewrite(query)
        lowered = rewrite.rewritten_query.lower()
        chat_enabled = self._chat_enabled_collections()
        selected: list[str] = ["knowledge"] if "knowledge" in chat_enabled else []
        reasons: list[str] = []

        if (
            "durable_memory" in chat_enabled
            and (
                rewrite.query_type == "memory"
                or any(token in lowered for token in ("remember", "preference", "workflow", "project", "session", "memory"))
            )
        ):
            selected.append("durable_memory")
            reasons.append("memory intent")

        if rewrite.query_type == "pdf_page":
            reasons.append("page-aware query")
        elif rewrite.query_type == "document":
            reasons.append("document query")
        elif rewrite.query_type == "table":
            reasons.append("table-like query")

        if not selected:
            selected = sorted(chat_enabled)

        return RoutePlan(
            query=query,
            rewritten_query=rewrite.rewritten_query,
            selected_collections=selected,
            reason=", ".join(reasons) if reasons else "default knowledge routing",
            rewrite=rewrite,
        )

    def retrieve(self, query: str, *, top_k: int = 6) -> list[dict[str, Any]]:
        plan = self.plan(query)
        results_by_collection: dict[str, list[RetrievalHit]] = {}

        with ThreadPoolExecutor(max_workers=max(1, len(plan.selected_collections))) as pool:
            future_map = {
                pool.submit(self.registry.get(name).retrieve, plan.rewritten_query, top_k): name
                for name in plan.selected_collections
            }
            for future, name in future_map.items():
                try:
                    results_by_collection[name] = future.result()
                except Exception:
                    results_by_collection[name] = []

        fused = self._fuse(plan.selected_collections, results_by_collection)
        candidate_top_k = self._candidate_top_k(top_k)
        payload: list[dict[str, Any]] = []
        for candidate_rank, item in enumerate(fused[:candidate_top_k], start=1):
            hit = item["hit"]
            payload.append(
                {
                    "text": hit.text,
                    "source": hit.source,
                    "modality": hit.modality,
                    "page": hit.page,
                    "score": item["score"],
                    "retrieval_score": item["score"],
                    "candidate_rank": candidate_rank,
                    "collection": item["collection"],
                    "reason": plan.reason,
                    "rewritten_query": plan.rewritten_query,
                    "rewrite_keywords": plan.rewrite.keywords,
                    "rewrite_rules": plan.rewrite.applied_rules,
                    "retrieval_backend": getattr(self.registry, "backend_name", "llamaindex_v2"),
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
        ranked = self.reranker.rerank_dict_results(
            query=plan.rewrite.original_query,
            results=payload,
        )
        return ranked[:top_k]

    def _candidate_top_k(self, top_k: int) -> int:
        requested = max(int(top_k or 1), 1)
        if not bool(getattr(self.settings, "rerank_enabled", False)):
            return requested
        rerank_top_n = max(int(getattr(self.settings, "rerank_top_n", requested) or requested), 1)
        rerank_candidate_pool = max(int(getattr(self.settings, "rerank_candidate_pool", 20) or 20), 1)
        return max(requested, rerank_top_n, rerank_candidate_pool)

    def _fuse(
        self,
        ordered_collections: list[str],
        results_by_collection: dict[str, list[RetrievalHit]],
    ) -> list[dict[str, Any]]:
        fused: dict[str, dict[str, Any]] = {}
        for collection_name in ordered_collections:
            config = self.collection_configs[collection_name]
            hits = results_by_collection.get(collection_name, [])
            for rank, hit in enumerate(hits, start=1):
                key = f"{hit.source}::{hit.page}::{hit.text[:160]}"
                weighted_rrf = config.weight / (rank + 50.0)
                weighted_score = config.weight * max(hit.score, 0.0)
                entry = fused.setdefault(
                    key,
                    {
                        "hit": hit,
                        "collection": collection_name,
                        "score": 0.0,
                    },
                )
                entry["score"] += weighted_rrf + weighted_score
                self._apply_metadata_bias(entry, hit)
        return sorted(fused.values(), key=lambda item: item["score"], reverse=True)

    def _apply_metadata_bias(self, entry: dict[str, object], hit: RetrievalHit) -> None:
        text = hit.text.lower()
        metadata = hit.metadata
        score = float(entry["score"])
        modality = hit.modality.lower()

        if modality == "table":
            score += 0.08
        elif modality == "image":
            score += 0.03

        if metadata.get("ocr") is True:
            score -= 0.01

        if metadata.get("collection") == "durable_memory":
            score += 0.05

        if any(token in text for token in ("table", "inventory", "sheet", "stock")) and modality == "table":
            score += 0.04
        if any(token in text for token in ("image", "screenshot", "ocr")) and modality == "image":
            score += 0.02

        entry["score"] = score
