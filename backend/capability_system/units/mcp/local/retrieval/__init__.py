from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from .unit import RETRIEVAL_LOCAL_MCP_UNIT

__all__ = [
    "RETRIEVAL_LOCAL_MCP_UNIT",
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
    "CollectionConfig": ("capability_system.units.mcp.local.retrieval.collections", "CollectionConfig"),
    "ParsedChunk": ("capability_system.units.mcp.local.retrieval.models", "ParsedChunk"),
    "QueryRewriteResult": ("capability_system.units.mcp.local.retrieval.query_rewriter", "QueryRewriteResult"),
    "QueryRewriter": ("capability_system.units.mcp.local.retrieval.query_rewriter", "QueryRewriter"),
    "HeuristicReranker": ("capability_system.units.mcp.local.retrieval.reranker", "HeuristicReranker"),
    "CrossEncoderReranker": ("capability_system.units.mcp.local.retrieval.reranker", "CrossEncoderReranker"),
    "RerankScore": ("capability_system.units.mcp.local.retrieval.reranker", "RerankScore"),
    "build_reranker": ("capability_system.units.mcp.local.retrieval.reranker", "build_reranker"),
    "RetrievalHit": ("capability_system.units.mcp.local.retrieval.models", "RetrievalHit"),
    "RAGIndexRegistry": ("capability_system.units.mcp.local.retrieval.registry", "RAGIndexRegistry"),
    "RAGQueryRouter": ("capability_system.units.mcp.local.retrieval.router", "RAGQueryRouter"),
    "MultimodalParserAdapter": ("capability_system.units.mcp.local.retrieval.parser_adapter", "MultimodalParserAdapter"),
    "RAGAnythingParserAdapter": ("capability_system.units.mcp.local.retrieval.parser_adapter", "RAGAnythingParserAdapter"),
    "RoutePlan": ("capability_system.units.mcp.local.retrieval.router", "RoutePlan"),
    "build_default_collections": ("capability_system.units.mcp.local.retrieval.collections", "build_default_collections"),
}

if TYPE_CHECKING:
    from .collections import CollectionConfig, build_default_collections
    from .models import ParsedChunk, RetrievalHit
    from .parser_adapter import MultimodalParserAdapter, RAGAnythingParserAdapter
    from .query_rewriter import QueryRewriteResult, QueryRewriter
    from .reranker import CrossEncoderReranker, HeuristicReranker, RerankScore, build_reranker
    from .registry import RAGIndexRegistry
    from .router import RAGQueryRouter, RoutePlan


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
