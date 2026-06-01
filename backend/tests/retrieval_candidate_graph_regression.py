from __future__ import annotations

from capability_system.capabilities.retrieval.models import RetrievalHit
from capability_system.capabilities.retrieval.candidate_graph import coalesce_with_candidate_graph
from knowledge_system.indexing.llamaindex_backend import LlamaIndexRetrievalBackend
from knowledge_system.indexing.retrievers import RetrievalRequest


def _hit(
    text: str,
    *,
    score: float,
    page: int | None = 1,
    block_id: str | None = None,
    object_ref_id: str | None = None,
    metadata: dict | None = None,
) -> RetrievalHit:
    return RetrievalHit(
        text=text,
        source="sample.pdf",
        modality="text",
        score=score,
        page=page,
        metadata=dict(metadata or {}),
        doc_id="doc-1",
        block_id=block_id,
        object_ref_id=object_ref_id,
        score_breakdown={"final": score},
        retrieval_modes=("dense",),
    )


def test_candidate_graph_merges_page_bucket() -> None:
    hits = [
        _hit("第一页第一段", score=0.5, block_id="b1"),
        _hit("第一页第二段", score=0.7, block_id="b2"),
    ]

    merged = coalesce_with_candidate_graph(
        hits,
        query_mode="page_grounded_lookup",
        chain_version="test_chain",
        top_k=5,
    )

    assert len(merged) == 1
    assert merged[0].score == 0.7
    assert merged[0].metadata["retrieval_stage"] == "candidate_graph"
    assert merged[0].metadata["candidate_graph_bucket_kind"] == "page"
    assert merged[0].metadata["merged_block_ids"] == ["b2", "b1"]
    assert "第一页第一段" in merged[0].text
    assert "第一页第二段" in merged[0].text


def test_candidate_graph_keeps_object_bucket_separate() -> None:
    hits = [
        _hit("正文段落", score=0.5, block_id="b1"),
        _hit("表格对象", score=0.9, block_id="b2", object_ref_id="obj-1"),
    ]

    merged = coalesce_with_candidate_graph(
        hits,
        query_mode="semantic_lookup",
        chain_version="test_chain",
        top_k=5,
    )

    bucket_kinds = {item.metadata["candidate_graph_bucket_kind"] for item in merged}
    assert bucket_kinds == {"page", "object"}


def test_candidate_graph_preserves_upstream_rank_order_between_buckets() -> None:
    hits = [
        _hit("上游第一名", score=0.2, page=1, block_id="b1"),
        _hit("上游第二名", score=0.9, page=2, block_id="b2"),
    ]

    merged = coalesce_with_candidate_graph(
        hits,
        query_mode="page_grounded_lookup",
        chain_version="test_chain",
        top_k=5,
    )

    assert [item.page for item in merged] == [1, 2]


def test_backend_coalesce_uses_candidate_graph_metadata() -> None:
    backend = LlamaIndexRetrievalBackend(__import__("pathlib").Path("backend"))
    request = RetrievalRequest(query="第一页", top_k=5, query_mode="page_grounded_lookup")

    merged = backend._coalesce_hits(
        [_hit("第一页第一段", score=0.5, block_id="b1"), _hit("第一页第二段", score=0.7, block_id="b2")],
        request,
    )

    assert len(merged) == 1
    assert merged[0].metadata["retrieval_stage"] == "candidate_graph"


