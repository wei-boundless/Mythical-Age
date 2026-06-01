from __future__ import annotations

from pathlib import Path

from capability_system.capabilities.retrieval.router import RAGQueryRouter
from capability_system.capabilities.retrieval.evidence_packager import build_evidence_pack
from capability_system.capabilities.retrieval.service import RetrievalService
from knowledge_system.indexing.retrievers import RetrievalRequest


def test_evidence_pack_uses_agent_facing_contract() -> None:
    pack = build_evidence_pack(
        query="第 2 页说了什么",
        retrieval_plan={"filters": {"page_any": [2]}},
        results=[
            {
                "text": "第二页证据",
                "source": "sample.pdf",
                "page": 2,
                "score": 0.8,
                "metadata": {
                    "doc_id": "doc-1",
                    "retrieval_stage": "candidate_graph",
                    "candidate_graph_bucket_kind": "page",
                },
            }
        ],
    )

    payload = pack.to_dict()
    assert "本地资料证据" in payload["answer_contract"]
    assert "retrieval planner" not in payload["answer_contract"].lower()
    assert payload["evidence_items"][0]["source_ref"] == "sample.pdf#page=2"
    assert payload["evidence_items"][0]["confidence"] == "high"
    assert payload["evidence_items"][0]["retrieval_reason"] == "candidate_graph:page"


class _StaticBackend:
    def retrieve(self, request: RetrievalRequest):
        from capability_system.capabilities.retrieval.models import RetrievalHit

        return [
            RetrievalHit(
                text="表格证据",
                source="orders.csv",
                modality="table",
                score=0.9,
                metadata={
                    "retrieval_stage": "candidate_graph",
                    "candidate_graph_bucket_kind": "table_window",
                    "retrieval_modes": ["lexical"],
                },
                doc_id="doc-1",
                block_id="b1",
                retrieval_modes=("lexical",),
            )
        ]


class _Bootstrapper:
    backend = _StaticBackend()


def test_retrieval_service_includes_evidence_pack_diagnostics() -> None:
    service = RetrievalService(Path("backend"))
    service.router = RAGQueryRouter(Path("backend"))
    service.bootstrapper = _Bootstrapper()  # type: ignore[assignment]

    result = service.retrieve_execution("查订单表格", top_k=1)

    assert result.status == "ok"
    pack = result.diagnostics["evidence_pack"]
    assert pack["evidence_items"][0]["text"] == "表格证据"
    assert pack["evidence_items"][0]["retrieval_reason"] == "candidate_graph:table_window"
    assert pack["trace"]["evidence_count"] == 1


