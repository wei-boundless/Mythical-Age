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
    "BM25Index": ("retrieval_core.lexical", "BM25Index"),
    "LlamaIndexRetrievalBackend": ("retrieval_core.llamaindex_backend", "LlamaIndexRetrievalBackend"),
    "RebuildResult": ("retrieval_core.bootstrap", "RebuildResult"),
    "RetrievalBootstrapper": ("retrieval_core.bootstrap", "RetrievalBootstrapper"),
    "RetrievalRequest": ("retrieval_core.retrievers", "RetrievalRequest"),
    "RetrievalLayout": ("retrieval_core.index_store", "RetrievalLayout"),
    "build_lexical_index_payload": ("retrieval_core.lexical", "build_lexical_index_payload"),
    "build_searchable_text": ("retrieval_core.lexical", "build_searchable_text"),
    "lexical_tokens": ("retrieval_core.lexical", "lexical_tokens"),
    "required_bm25_term_matches": ("retrieval_core.lexical", "required_bm25_term_matches"),
    "score_lexical_query": ("retrieval_core.lexical", "score_lexical_query"),
    "to_retrieval_hit": ("retrieval_core.adapters", "to_retrieval_hit"),
}

if TYPE_CHECKING:
    from retrieval_core.adapters import to_retrieval_hit
    from retrieval_core.bootstrap import RebuildResult, RetrievalBootstrapper
    from retrieval_core.index_store import RetrievalLayout
    from retrieval_core.lexical import (
        BM25Index,
        build_lexical_index_payload,
        build_searchable_text,
        lexical_tokens,
        required_bm25_term_matches,
        score_lexical_query,
    )
    from retrieval_core.llamaindex_backend import LlamaIndexRetrievalBackend
    from retrieval_core.retrievers import RetrievalRequest


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
