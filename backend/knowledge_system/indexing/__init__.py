from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "LlamaIndexRetrievalBackend",
    "BM25Index",
    "RebuildResult",
    "RetrievalBootstrapper",
    "RetrievalRequest",
    "RetrievalLayout",
    "build_lexical_index_payload",
    "build_searchable_text",
    "lexical_tokens",
    "required_bm25_term_matches",
    "score_lexical_query",
    "to_retrieval_hit",
]

_EXPORTS = {
    "BM25Index": ("knowledge_system.indexing.lexical", "BM25Index"),
    "LlamaIndexRetrievalBackend": ("knowledge_system.indexing.llamaindex_backend", "LlamaIndexRetrievalBackend"),
    "RebuildResult": ("knowledge_system.indexing.bootstrap", "RebuildResult"),
    "RetrievalBootstrapper": ("knowledge_system.indexing.bootstrap", "RetrievalBootstrapper"),
    "RetrievalRequest": ("knowledge_system.indexing.retrievers", "RetrievalRequest"),
    "RetrievalLayout": ("knowledge_system.indexing.index_store", "RetrievalLayout"),
    "build_lexical_index_payload": ("knowledge_system.indexing.lexical", "build_lexical_index_payload"),
    "build_searchable_text": ("knowledge_system.indexing.lexical", "build_searchable_text"),
    "lexical_tokens": ("knowledge_system.indexing.lexical", "lexical_tokens"),
    "required_bm25_term_matches": ("knowledge_system.indexing.lexical", "required_bm25_term_matches"),
    "score_lexical_query": ("knowledge_system.indexing.lexical", "score_lexical_query"),
    "to_retrieval_hit": ("knowledge_system.indexing.adapters", "to_retrieval_hit"),
}

if TYPE_CHECKING:
    from knowledge_system.indexing.adapters import to_retrieval_hit
    from knowledge_system.indexing.bootstrap import RebuildResult, RetrievalBootstrapper
    from knowledge_system.indexing.index_store import RetrievalLayout
    from knowledge_system.indexing.lexical import (
        BM25Index,
        build_lexical_index_payload,
        build_searchable_text,
        lexical_tokens,
        required_bm25_term_matches,
        score_lexical_query,
    )
    from knowledge_system.indexing.llamaindex_backend import LlamaIndexRetrievalBackend
    from knowledge_system.indexing.retrievers import RetrievalRequest


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


