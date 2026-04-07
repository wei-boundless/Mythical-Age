from __future__ import annotations

import sys
from pathlib import Path

from llama_index.core import Document


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.eval_retrieval import _hybrid_fuse
from RAG.hybrid import BM25Index, build_searchable_text


def _bm25_from_docs(docs: list[Document]) -> BM25Index:
    return BM25Index.from_texts(
        [
            build_searchable_text(
                doc.text,
                source=str(doc.metadata.get("source", "")),
                metadata=dict(doc.metadata),
            )
            for doc in docs
        ]
    )


def main() -> None:
    english_docs = [
        Document(
            text="fresh red apple fruit for breakfast",
            metadata={"doc_id": "d1", "source": "knowledge/apple_note.txt", "section": "fruit"},
        ),
        Document(
            text="banana smoothie with oat milk",
            metadata={"doc_id": "d2", "source": "knowledge/banana.txt", "section": "drink"},
        ),
        Document(
            text="apple watch charging cable accessories",
            metadata={"doc_id": "d3", "source": "knowledge/apple_watch.txt", "section": "device"},
        ),
    ]
    english_bm25 = _bm25_from_docs(english_docs)
    english_hits = english_bm25.search("red apple breakfast", top_k=3)
    assert english_hits
    assert english_hits[0].index == 0
    assert english_hits[0].score > 0

    chinese_docs = [
        Document(
            text="现代客厅大落地窗设计案例，采光很好。",
            metadata={"doc_id": "c1", "source": "knowledge/living_room.txt", "section": "design"},
        ),
        Document(
            text="厨房水槽和龙头安装说明。",
            metadata={"doc_id": "c2", "source": "knowledge/kitchen.txt", "section": "guide"},
        ),
    ]
    chinese_bm25 = _bm25_from_docs(chinese_docs)
    chinese_hits = chinese_bm25.search("大落地窗", top_k=2)
    assert chinese_hits
    assert chinese_hits[0].index == 0
    assert chinese_hits[0].score > 0

    source_hits = english_bm25.search("apple_note fruit", top_k=2)
    assert source_hits
    assert source_hits[0].index == 0

    hybrid_payload = _hybrid_fuse(
        query="apple_note red apple",
        dense_payload=[],
        docs=english_docs,
        top_k=2,
        bm25_index=english_bm25,
    )
    assert hybrid_payload
    assert hybrid_payload[0]["metadata"]["doc_id"] == "d1"
    assert "bm25" in hybrid_payload[0]["hybrid_reasons"]
    assert "keyword" in hybrid_payload[0]["hybrid_reasons"]

    print("ALL PASSED (bm25 hybrid regression)")


if __name__ == "__main__":
    main()
