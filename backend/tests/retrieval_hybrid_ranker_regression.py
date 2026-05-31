from __future__ import annotations

from capability_system.units.mcp.local.retrieval.models import RetrievalHit
from knowledge_system.retrieval.hybrid_ranker import HybridRanker


def _hit(
    hit_id: str,
    *,
    score: float,
    source: str = "sample.pdf",
    doc_id: str = "doc:sample",
    page: int | None = 1,
    mode: str = "dense",
    text: str = "evidence",
) -> RetrievalHit:
    return RetrievalHit(
        text=text,
        source=source,
        modality="text",
        score=score,
        page=page,
        metadata={},
        hit_id=hit_id,
        doc_id=doc_id,
        block_id=hit_id,
        score_breakdown={"final": score},
        retrieval_modes=(mode,),
    )


def test_hybrid_ranker_rewards_cross_channel_evidence() -> None:
    ranker = HybridRanker()

    ranked = ranker.rank(
        {
            "dense": [_hit("dense-only", score=0.95), _hit("both", score=0.50)],
            "lexical": [_hit("both", score=0.80, mode="lexical")],
        },
        top_k=2,
        query_mode="semantic_lookup",
        weights={"dense": 0.6, "lexical": 1.0},
        chain_version="test",
    )

    assert ranked[0].hit_id == "both"
    assert "fusion" in ranked[0].retrieval_modes
    assert ranked[0].score_breakdown["multi_channel_boost"] > 0
    assert ranked[0].score_breakdown["hit_count"] == 2.0


def test_hybrid_ranker_applies_page_policy_and_diversity_breakdown() -> None:
    ranker = HybridRanker()

    ranked = ranker.rank(
        {
            "dense": [
                _hit("p1-a", score=0.90, page=1),
                _hit("p1-b", score=0.89, page=1),
                _hit("p2", score=0.88, page=2),
            ]
        },
        top_k=3,
        query_mode="page_grounded_lookup",
        weights={"dense": 1.0},
        chain_version="test",
    )

    assert ranked[0].score_breakdown["policy_boost"] == 0.05
    assert any("diversity_penalty" in item.score_breakdown for item in ranked[1:])
