from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .collections import build_default_collections
from .page_hints import extract_page_hints
from .query_rewriter import QueryRewriteResult, QueryRewriter
from knowledge_system.retrieval.planning import QueryVariant, RetrievalFilter, RetrievalIntent, RetrievalPlan, RetrievalPolicy, RetrievalTrace

if TYPE_CHECKING:
    from .reranker import DictReranker


@dataclass(slots=True)
class RoutePlan:
    query: str
    rewritten_query: str
    selected_collections: list[str]
    reason: str
    rewrite: QueryRewriteResult
    retrieval_plan: RetrievalPlan | None = None

    @property
    def filters(self) -> dict[str, Any]:
        if self.retrieval_plan is None:
            return {}
        return self.retrieval_plan.filters.to_dict()

    @property
    def policy(self) -> dict[str, Any]:
        if self.retrieval_plan is None:
            return {}
        return self.retrieval_plan.policy.to_dict()


class RAGQueryRouter:
    def __init__(self, base_dir: Path, *, ocr_language: str = "eng") -> None:
        self.base_dir = base_dir
        self.ocr_language = ocr_language
        self.collection_configs = build_default_collections(base_dir)
        self.rewriter = QueryRewriter()
        self._reranker: DictReranker | Any | None = None

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
        filters = RetrievalFilter()
        policy = RetrievalPolicy()

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
            filters = RetrievalFilter(
                page_any=self._page_hints(query),
                unit_type_any=("page_summary", "content_block", "object_block"),
            )
            policy = RetrievalPolicy(strategy="precise", result_granularity="page", parent_child_expansion=True)
        elif rewrite.query_type == "document":
            reasons.append("document query")
            filters = RetrievalFilter(unit_type_any=("document_summary", "parent_section", "page_summary", "content_block"))
            policy = RetrievalPolicy(strategy="hierarchical", result_granularity="document", parent_child_expansion=True)
        elif rewrite.query_type == "table":
            reasons.append("table-like query")
            filters = RetrievalFilter(modality_any=("table",), unit_type_any=("table_row_window", "object_block"))
            policy = RetrievalPolicy(strategy="precise", result_granularity="object")
        elif rewrite.query_type == "memory":
            policy = RetrievalPolicy(strategy="precise", result_granularity="block")

        if not selected:
            selected = sorted(chat_enabled)

        intent = RetrievalIntent(
            intent_type=self._intent_type_from_query_type(rewrite.query_type),
            query_type=rewrite.query_type,
            page_hints=self._page_hints(query),
            modality_hints=filters.modality_any,
            source_terms=self._source_terms(query),
        )
        retrieval_plan = RetrievalPlan(
            query=query,
            rewritten_query=rewrite.rewritten_query,
            selected_collections=tuple(selected),
            intent=intent,
            filters=filters,
            policy=policy,
            query_variants=(QueryVariant(query=rewrite.rewritten_query, role="rewritten", weight=1.0),),
            trace=RetrievalTrace(reasons=tuple(reasons or ("default knowledge routing",))),
        )

        return RoutePlan(
            query=query,
            rewritten_query=rewrite.rewritten_query,
            selected_collections=selected,
            reason=", ".join(reasons) if reasons else "default knowledge routing",
            rewrite=rewrite,
            retrieval_plan=retrieval_plan,
        )

    def _intent_type_from_query_type(self, query_type: str) -> str:
        if query_type == "pdf_page":
            return "page_grounded_lookup"
        if query_type == "table":
            return "table_lookup"
        if query_type == "memory":
            return "memory_lookup"
        if query_type == "document":
            return "document_lookup"
        return "factual_lookup"

    def _page_hints(self, query: str) -> tuple[int, ...]:
        return extract_page_hints(query)

    def _source_terms(self, query: str) -> tuple[str, ...]:
        import re

        terms = re.findall(r"[\w\u4e00-\u9fff.-]+\.(?:pdf|docx|pptx|xlsx|csv|md|txt)", str(query or ""), flags=re.IGNORECASE)
        return tuple(dict.fromkeys(term.strip() for term in terms if term.strip()))
