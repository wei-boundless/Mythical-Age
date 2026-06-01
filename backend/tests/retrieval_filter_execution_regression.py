from __future__ import annotations

from pathlib import Path
from typing import Any

from capability_system.capabilities.retrieval.router import RAGQueryRouter
from capability_system.capabilities.retrieval.models import RetrievalHit
from capability_system.capabilities.retrieval.service import RetrievalService
from knowledge_system.indexing.llamaindex_backend import LlamaIndexRetrievalBackend
from knowledge_system.indexing.retrievers import RetrievalRequest


def test_lexical_filter_predicate_accepts_table_row_window() -> None:
    backend = LlamaIndexRetrievalBackend(Path("backend"))
    item = {
        "unit_type": "table_row_window",
        "modality": "table",
        "block_type": "table",
        "page": None,
        "source_path": "knowledge/orders.csv",
        "quality_flags": [],
    }

    assert backend._unit_payload_matches_filters(
        item,
        {"modality_any": ["table"], "unit_type_any": ["table_row_window"]},
    )
    assert not backend._unit_payload_matches_filters(item, {"modality_any": ["text"]})


def test_qdrant_filter_is_built_from_retrieval_request() -> None:
    backend = LlamaIndexRetrievalBackend(Path("backend"))
    request = RetrievalRequest(
        query="订单",
        filters={"modality_any": ["table"], "unit_type_any": ["table_row_window"], "page_any": [2]},
    )

    query_filter = backend._qdrant_filter_from_request(request)

    assert query_filter is not None
    assert len(query_filter.must) == 3


class _CaptureBackend:
    def __init__(self) -> None:
        self.request: RetrievalRequest | None = None

    def retrieve(self, request: RetrievalRequest):
        self.request = request
        return []


class _Bootstrapper:
    def __init__(self, backend: _CaptureBackend) -> None:
        self.backend = backend


def test_retrieval_service_passes_plan_filters_to_backend() -> None:
    capture = _CaptureBackend()
    service = RetrievalService(Path("backend"))
    service.router = RAGQueryRouter(Path("backend"))
    service.bootstrapper = _Bootstrapper(capture)  # type: ignore[assignment]

    result = service.retrieve_execution("帮我查订单表格", top_k=3)

    assert result.status == "empty"
    assert capture.request is not None
    assert capture.request.filters["modality_any"] == ["table"]
    assert "table_row_window" in capture.request.filters["unit_type_any"]
    assert result.diagnostics["retrieval_plan"]["filters"]["modality_any"] == ["table"]


class _HitBackend:
    def retrieve(self, request: RetrievalRequest):
        del request
        return [
            RetrievalHit(
                text="订单表格证据",
                source="orders.csv",
                modality="table",
                score=0.9,
                metadata={"collection": "knowledge"},
                doc_id="doc:orders",
                block_id="block:orders",
            )
        ]


class _FailingReranker:
    def rerank_dict_results(self, **kwargs):
        del kwargs
        raise RuntimeError("reranker unavailable")


def test_retrieval_service_marks_rerank_failure_as_typed_degradation() -> None:
    router = RAGQueryRouter(Path("backend"))
    router._reranker = _FailingReranker()
    service = RetrievalService(Path("backend"))
    service.router = router
    service.bootstrapper = _Bootstrapper(_HitBackend())  # type: ignore[arg-type]

    result = service.retrieve_execution("帮我查订单表格", top_k=1)

    assert result.status == "ok"
    assert result.degraded_reason_typed == "rerank_execution_failed"
    assert result.results[0]["rerank_fallback"] is True
    assert result.results[0]["metadata"]["rerank_degraded_reason_typed"] == "rerank_execution_failed"


