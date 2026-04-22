from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from normalized_ingestion.models import IndexableUnit
from retrieval_core import LlamaIndexRetrievalBackend, RetrievalRequest


class DeterministicEmbedding:
    def get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def get_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        bucket = [0.0, 0.0, 0.0, 0.0]
        for index, char in enumerate(text.lower()):
            bucket[index % 4] += (ord(char) % 31) / 31.0
        norm = sum(value * value for value in bucket) ** 0.5 or 1.0
        return [value / norm for value in bucket]


def test_llamaindex_backend_can_build_and_retrieve_dense_hits(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    backend = LlamaIndexRetrievalBackend(backend_dir)
    embedding = DeterministicEmbedding()
    units = [
        IndexableUnit(
            unit_id="u1",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="AI governance risk categories include compliance, security, and misuse.",
            modality="text",
            block_id="b1",
            block_type="paragraph",
            metadata={"parser_backend": "test"},
        ),
        IndexableUnit(
            unit_id="u2",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-2",
            source_path="knowledge/beta.md",
            text="Retail staffing and inventory operations summary for store managers.",
            modality="text",
            block_id="b2",
            block_type="paragraph",
            metadata={"parser_backend": "test"},
        ),
    ]

    payload = backend.build_collection("knowledge", units, embed_model=embedding)
    hits = backend.retrieve(
        RetrievalRequest(
            query="AI governance compliance risk",
            top_k=2,
            collections=("knowledge",),
        ),
        embed_model=embedding,
    )

    assert payload["status"] == "ready"
    assert payload["vector_backend"] == "qdrant"
    assert payload["lexical_enabled"] is True
    assert payload["lexical_documents"] == 2
    assert payload["strategy_name"] == "baseline_dense_lexical"
    assert payload["chain_version"]
    assert hits
    assert {hit.doc_id for hit in hits} >= {"doc-1"}
    assert "dense" in hits[0].retrieval_modes
    assert hits[0].metadata["result_granularity"] == "block"
    assert hits[0].metadata["chain_version"] == payload["chain_version"]


def test_llamaindex_backend_can_retrieve_lexical_hits(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    backend = LlamaIndexRetrievalBackend(backend_dir)
    embedding = DeterministicEmbedding()
    units = [
        IndexableUnit(
            unit_id="u1",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="本页总结介绍人工智能治理框架和合规要求。",
            modality="text",
            block_id="b1",
            block_type="paragraph",
            metadata={"parser_backend": "test", "index_profiles": ["dense_main", "lexical_main"]},
        ),
        IndexableUnit(
            unit_id="u2",
            unit_type="object_block",
            collection="knowledge",
            doc_id="doc-2",
            source_path="knowledge/beta.md",
            text="SKU-8472 风险控制检查表",
            modality="text",
            block_id="b2",
            block_type="table",
            object_ref_id="obj-1",
            metadata={"parser_backend": "test"},
        ),
    ]

    payload = backend.build_collection("knowledge", units, embed_model=embedding)
    hits = backend.retrieve(
        RetrievalRequest(
            query="SKU-8472",
            top_k=2,
            collections=("knowledge",),
            query_mode="table_lookup",
        ),
        embed_model=embedding,
    )

    assert payload["lexical_enabled"] is True
    assert (backend_dir / "storage" / "indexes_v2" / "knowledge" / "lexical" / "index.json").exists()
    assert hits
    assert hits[0].doc_id == "doc-2"
    assert "lexical" in hits[0].retrieval_modes
    assert hits[0].metadata["result_granularity"] == "object"


def test_llamaindex_backend_coalesces_same_page_hits(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    backend = LlamaIndexRetrievalBackend(backend_dir)
    embedding = DeterministicEmbedding()
    units = [
        IndexableUnit(
            unit_id="u1",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="人工智能安全治理研究报告介绍总体框架。",
            modality="text",
            block_id="b1",
            page=3,
            block_type="paragraph",
            metadata={"parser_backend": "test", "index_profiles": ["dense_main", "lexical_main"]},
        ),
        IndexableUnit(
            unit_id="u2",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="报告进一步说明风险分类和治理要求。",
            modality="text",
            block_id="b2",
            page=3,
            block_type="paragraph",
            metadata={"parser_backend": "test", "index_profiles": ["dense_main", "lexical_main"]},
        ),
    ]

    backend.build_collection("knowledge", units, embed_model=embedding)
    hits = backend.retrieve(
        RetrievalRequest(
            query="人工智能安全治理研究报告",
            top_k=5,
            collections=("knowledge",),
            query_mode="document_overview",
        ),
        embed_model=embedding,
    )

    assert hits
    assert len(hits) == 1
    assert hits[0].doc_id == "doc-1"
    assert hits[0].metadata.get("merged_hit_count") == 2
    assert hits[0].metadata.get("result_granularity") == "document"
    assert "总体框架" in hits[0].text
    assert "风险分类" in hits[0].text


def test_llamaindex_backend_marks_dense_invalid_when_verification_fails(tmp_path: Path, monkeypatch) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    backend = LlamaIndexRetrievalBackend(backend_dir)
    embedding = DeterministicEmbedding()
    units = [
        IndexableUnit(
            unit_id="u1",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="AI governance risk categories include compliance, security, and misuse.",
            modality="text",
            block_id="b1",
            block_type="paragraph",
            metadata={"parser_backend": "test", "index_profiles": ["dense_main", "lexical_main"]},
        ),
    ]

    def _fake_verify(*args, **kwargs):
        return {
            "collection": "knowledge",
            "collection_name": "agent__knowledge",
            "vector_backend": "qdrant",
            "available": False,
            "query_ok": False,
            "points_count": 0,
            "status": "invalid",
            "error": "collection_missing",
        }

    monkeypatch.setattr(backend, "_verify_qdrant_collection", _fake_verify)
    payload = backend.build_collection("knowledge", units, embed_model=embedding)

    assert payload["status"] == "invalid"
    assert payload["dense_status"] == "invalid"
    assert payload["dense_verification"]["error"] == "collection_missing"


def test_llamaindex_backend_reports_dense_health_after_build(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    backend = LlamaIndexRetrievalBackend(backend_dir)
    embedding = DeterministicEmbedding()
    units = [
        IndexableUnit(
            unit_id="u1",
            unit_type="content_block",
            collection="knowledge",
            doc_id="doc-1",
            source_path="knowledge/alpha.md",
            text="AI governance risk categories include compliance, security, and misuse.",
            modality="text",
            block_id="b1",
            block_type="paragraph",
            metadata={"parser_backend": "test", "index_profiles": ["dense_main", "lexical_main"]},
        ),
    ]

    backend.build_collection("knowledge", units, embed_model=embedding)
    health = backend.dense_health("knowledge", embed_model=embedding, smoke_query=units[0].text)

    assert health["available"] is True
    assert health["query_ok"] is True
    assert health["status"] == "ready"
