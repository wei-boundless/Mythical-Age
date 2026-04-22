from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.collections import CollectionConfig
from document_conversion import DoclingConverter
from retrieval_core import RetrievalV2Bootstrapper


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
            bucket[index % 4] += (ord(char) % 37) / 37.0
        norm = sum(value * value for value in bucket) ** 0.5 or 1.0
        return [value / norm for value in bucket]


def test_retrieval_bootstrapper_rebuilds_collection_end_to_end(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "alpha.md").write_text("# Alpha\n\nAI governance risk management baseline.", encoding="utf-8")
    (knowledge_dir / "beta.md").write_text("# Beta\n\nRetail workforce planning and inventory.", encoding="utf-8")

    config = CollectionConfig(
        name="knowledge",
        source_dirs=(knowledge_dir,),
        storage_dir=backend_dir / "storage" / "indexes" / "knowledge",
        description="test knowledge",
        allowed_roots=(knowledge_dir,),
        file_extensions=(".md",),
    )
    bootstrapper = RetrievalV2Bootstrapper(backend_dir, converter=DoclingConverter(enabled=False))
    result = bootstrapper.rebuild_collection(config, embed_model=DeterministicEmbedding())

    assert result.discovered_files == 2
    assert result.converted_documents == 2
    assert result.indexable_units >= 2
    assert result.eligible_blocks >= 2
    assert result.dropped_blocks == 0
    assert result.index_payload["status"] == "ready"
    assert result.index_payload["vector_backend"] == "qdrant"
    assert result.index_payload["lexical_enabled"] is True
    assert result.index_payload["lexical_documents"] >= 2
    assert (backend_dir / "storage" / "indexes_v2" / "knowledge" / "dense").exists()
    assert (backend_dir / "storage" / "indexes_v2" / "knowledge" / "lexical" / "index.json").exists()
    assert (backend_dir / "storage" / "document_cache_v2" / "conversion").exists()
