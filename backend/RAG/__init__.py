from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "CollectionConfig",
    "ParsedChunk",
    "QueryRewriteResult",
    "QueryRewriter",
    "HeuristicReranker",
    "CrossEncoderReranker",
    "RerankScore",
    "build_reranker",
    "RetrievalHit",
    "RAGIndexRegistry",
    "RAGQueryRouter",
    "MultimodalParserAdapter",
    "RAGAnythingParserAdapter",
    "RoutePlan",
    "build_default_collections",
]

_EXPORTS = {
    "CollectionConfig": ("RAG.collections", "CollectionConfig"),
    "ParsedChunk": ("RAG.models", "ParsedChunk"),
    "QueryRewriteResult": ("RAG.query_rewriter", "QueryRewriteResult"),
    "QueryRewriter": ("RAG.query_rewriter", "QueryRewriter"),
    "HeuristicReranker": ("RAG.reranker", "HeuristicReranker"),
    "CrossEncoderReranker": ("RAG.reranker", "CrossEncoderReranker"),
    "RerankScore": ("RAG.reranker", "RerankScore"),
    "build_reranker": ("RAG.reranker", "build_reranker"),
    "RetrievalHit": ("RAG.models", "RetrievalHit"),
    "RAGIndexRegistry": ("RAG.registry", "RAGIndexRegistry"),
    "RAGQueryRouter": ("RAG.router", "RAGQueryRouter"),
    "MultimodalParserAdapter": ("RAG.parser_adapter", "MultimodalParserAdapter"),
    "RAGAnythingParserAdapter": ("RAG.parser_adapter", "RAGAnythingParserAdapter"),
    "RoutePlan": ("RAG.router", "RoutePlan"),
    "build_default_collections": ("RAG.collections", "build_default_collections"),
}

if TYPE_CHECKING:
    from RAG.collections import CollectionConfig, build_default_collections
    from RAG.models import ParsedChunk, RetrievalHit
    from RAG.parser_adapter import MultimodalParserAdapter, RAGAnythingParserAdapter
    from RAG.query_rewriter import QueryRewriteResult, QueryRewriter
    from RAG.reranker import CrossEncoderReranker, HeuristicReranker, RerankScore, build_reranker
    from RAG.registry import RAGIndexRegistry
    from RAG.router import RAGQueryRouter, RoutePlan


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
