from __future__ import annotations

from capability_system.units.mcp.local.retrieval.reranker import RemoteApiReranker


def test_remote_reranker_failure_returns_typed_degraded_results(monkeypatch) -> None:
    reranker = RemoteApiReranker(
        provider="remote",
        model_name="rerank-test",
        api_key="key",
        base_url="https://example.com/v1",
        top_n=2,
    )

    def fail_remote(**kwargs):
        raise RuntimeError("remote unavailable")

    monkeypatch.setattr(reranker, "_remote_rerank", fail_remote)

    ranked = reranker.rerank_dict_results(
        query="alpha",
        results=[
            {"text": "alpha evidence", "score": 0.2, "metadata": {}},
            {"text": "beta evidence", "score": 0.1, "metadata": {}},
        ],
    )

    assert ranked[0]["rerank_backend"] == "heuristic_fallback"
    assert ranked[0]["rerank_fallback"] is True
    assert ranked[0]["rerank_degraded_reason_typed"] == "remote_rerank_failed"
    assert ranked[0]["metadata"]["rerank_degraded_reason_typed"] == "remote_rerank_failed"
