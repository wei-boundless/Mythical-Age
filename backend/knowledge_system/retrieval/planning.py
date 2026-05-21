from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RetrievalIntentType = Literal[
    "factual_lookup",
    "document_lookup",
    "page_grounded_lookup",
    "table_lookup",
    "memory_lookup",
    "source_constrained_lookup",
    "exploratory_lookup",
]


@dataclass(frozen=True, slots=True)
class QueryVariant:
    query: str
    role: str = "original"
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "role": self.role, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class RetrievalIntent:
    intent_type: RetrievalIntentType = "factual_lookup"
    query_type: str = "general"
    page_hints: tuple[int, ...] = ()
    modality_hints: tuple[str, ...] = ()
    source_terms: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "query_type": self.query_type,
            "page_hints": list(self.page_hints),
            "modality_hints": list(self.modality_hints),
            "source_terms": list(self.source_terms),
            "entities": list(self.entities),
        }


@dataclass(frozen=True, slots=True)
class RetrievalFilter:
    modality_any: tuple[str, ...] = ()
    unit_type_any: tuple[str, ...] = ()
    block_type_any: tuple[str, ...] = ()
    page_any: tuple[int, ...] = ()
    doc_id_any: tuple[str, ...] = ()
    source_path_contains_any: tuple[str, ...] = ()
    quality_flags_exclude_any: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "modality_any": list(self.modality_any),
                "unit_type_any": list(self.unit_type_any),
                "block_type_any": list(self.block_type_any),
                "page_any": list(self.page_any),
                "doc_id_any": list(self.doc_id_any),
                "source_path_contains_any": list(self.source_path_contains_any),
                "quality_flags_exclude_any": list(self.quality_flags_exclude_any),
            }.items()
            if value
        }


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    strategy: str = "balanced"
    result_granularity: str = "block"
    dense_top_k: int = 20
    lexical_top_k: int = 20
    fusion_top_k: int = 20
    rerank_top_n: int = 5
    query_variant_limit: int = 1
    parent_child_expansion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "result_granularity": self.result_granularity,
            "dense_top_k": self.dense_top_k,
            "lexical_top_k": self.lexical_top_k,
            "fusion_top_k": self.fusion_top_k,
            "rerank_top_n": self.rerank_top_n,
            "query_variant_limit": self.query_variant_limit,
            "parent_child_expansion": self.parent_child_expansion,
        }


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    planner_version: str = "retrieval_planner_v1"
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "planner_version": self.planner_version,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    query: str
    rewritten_query: str
    selected_collections: tuple[str, ...]
    intent: RetrievalIntent = field(default_factory=RetrievalIntent)
    filters: RetrievalFilter = field(default_factory=RetrievalFilter)
    policy: RetrievalPolicy = field(default_factory=RetrievalPolicy)
    query_variants: tuple[QueryVariant, ...] = ()
    trace: RetrievalTrace = field(default_factory=RetrievalTrace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "rewritten_query": self.rewritten_query,
            "selected_collections": list(self.selected_collections),
            "intent": self.intent.to_dict(),
            "filters": self.filters.to_dict(),
            "policy": self.policy.to_dict(),
            "query_variants": [variant.to_dict() for variant in self.query_variants],
            "trace": self.trace.to_dict(),
        }
