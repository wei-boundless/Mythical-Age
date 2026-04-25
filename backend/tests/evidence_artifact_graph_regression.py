from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.evidence_graph import EvidenceArtifactGraph
from query.evidence_models import EvidenceArtifact, EvidenceEnvelope, ResultHandle, SourceObjectRef, SubsetHandle
from query.evidence_store import EvidenceGraphStore


def test_evidence_graph_preserves_source_artifact_edges_from_envelope() -> None:
    envelope = EvidenceEnvelope(
        query="查询库存缺货",
        source_worker="retrieval",
        source_objects=[
            SourceObjectRef(
                object_id="source:inventory",
                object_type="dataset",
                uri="knowledge/E-commerce Data/inventory.xlsx",
            )
        ],
        derived_artifacts=[
            EvidenceArtifact(
                artifact_id="artifact:inventory-summary",
                artifact_type="dataset_summary",
                source_object_id="source:inventory",
                content_ref="knowledge/E-commerce Data/inventory.xlsx#summary",
                consumable_by=["structured_data"],
                metadata={"confidence": 0.91},
            )
        ],
    )

    graph = EvidenceArtifactGraph.from_envelope(
        session_id="graph-session",
        turn_id="turn-1",
        envelope=envelope,
    )
    delta = graph.to_delta()

    assert delta["session_id"] == "graph-session"
    assert delta["turn_id"] == "turn-1"
    assert delta["source_objects"][0]["object_id"] == "source:inventory"
    assert delta["artifacts"][0]["artifact_id"] == "artifact:inventory-summary"
    assert delta["edges"] == [
        {
            "from_id": "source:inventory",
            "to_id": "artifact:inventory-summary",
            "relation": "derived_from",
            "confidence": 0.91,
            "worker": "retrieval",
            "metadata": {},
        }
    ]


def test_evidence_graph_store_merges_session_scoped_artifacts() -> None:
    store = EvidenceGraphStore()
    first = EvidenceArtifactGraph(
        session_id="graph-session",
        source_objects={
            "source:pdf": SourceObjectRef(
                object_id="source:pdf",
                object_type="pdf",
                uri="knowledge/report.pdf",
            )
        },
        artifacts={
            "source:pdf:page:1": EvidenceArtifact(
                artifact_id="source:pdf:page:1",
                artifact_type="pdf_page",
                source_object_id="source:pdf",
            )
        },
    )
    second = EvidenceArtifactGraph(
        session_id="graph-session",
        source_objects={
            "source:dataset": SourceObjectRef(
                object_id="source:dataset",
                object_type="dataset",
                uri="knowledge/inventory.xlsx",
            )
        },
        artifacts={
            "artifact:dataset_analysis": EvidenceArtifact(
                artifact_id="artifact:dataset_analysis",
                artifact_type="dataset_analysis",
                source_object_id="source:dataset",
            )
        },
    )

    store.merge("graph-session", first)
    store.merge("graph-session", second)
    snapshot = store.snapshot("graph-session")

    assert {item["object_type"] for item in snapshot["source_objects"]} == {"pdf", "dataset"}
    assert {item["artifact_type"] for item in snapshot["artifacts"]} == {"pdf_page", "dataset_analysis"}


def test_evidence_graph_store_persists_result_and_subset_handles() -> None:
    store = EvidenceGraphStore()
    graph = EvidenceArtifactGraph(session_id="graph-session")
    graph.add_result_handle(
        ResultHandle(
            result_id="result:structured:primary",
            result_kind="structured_answer",
            source_object_id="source:dataset",
            identity="inventory shortage answer",
        ),
        worker="structured_data",
    )
    graph.add_subset_handle(
        SubsetHandle(
            subset_id="subset:selection:primary",
            subset_kind="selection",
            result_id="result:structured:primary",
            identity="shortage cities",
            metadata={"labels": ["武汉", "上海"], "filter_column": "city"},
        ),
        worker="structured_data",
    )

    store.merge("graph-session", graph)
    snapshot = store.snapshot("graph-session")
    restored = EvidenceGraphStore()
    restored.restore("graph-session", snapshot)

    assert snapshot["result_handles"][0]["result_id"] == "result:structured:primary"
    assert snapshot["subset_handles"][0]["subset_id"] == "subset:selection:primary"
    assert restored.get_result_handle("graph-session", "result:structured:primary").result_kind == "structured_answer"
    assert restored.get_subset_handle("graph-session", "subset:selection:primary").metadata["labels"] == ["武汉", "上海"]


def main() -> None:
    test_evidence_graph_preserves_source_artifact_edges_from_envelope()
    test_evidence_graph_store_merges_session_scoped_artifacts()
    test_evidence_graph_store_persists_result_and_subset_handles()
    print("ALL PASSED (evidence artifact graph)")


if __name__ == "__main__":
    main()
