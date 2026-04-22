from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.collections import build_default_collections
from document_conversion import DoclingConverter
from retrieval.service import RetrievalService
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
            bucket[index % 4] += (ord(char) % 29) / 29.0
        norm = sum(value * value for value in bucket) ** 0.5 or 1.0
        return [value / norm for value in bucket]


def test_memory_collections_can_rebuild_into_v2_and_be_queried(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    durable_notes = backend_dir / "durable_memory" / "notes"
    durable_index = backend_dir / "durable_memory" / "index"
    session_dir = backend_dir / "session-memory" / "session-1"
    durable_notes.mkdir(parents=True)
    durable_index.mkdir(parents=True)
    session_dir.mkdir(parents=True)

    (durable_notes / "powershell.md").write_text(
        "# Shell Preference\n\nPowerShell is the default terminal for this workspace.\n",
        encoding="utf-8",
    )
    (durable_index / "MEMORY.md").write_text(
        "# Memory Index\n\n- [Shell Preference](powershell.md) - PowerShell is the default terminal.\n",
        encoding="utf-8",
    )
    (session_dir / "summary.md").write_text(
        "# Session Summary\n\nCurrent task is to continue the retrieval refactor and verify session state.\n",
        encoding="utf-8",
    )

    bootstrapper = RetrievalV2Bootstrapper(backend_dir, converter=DoclingConverter(enabled=False))
    collections = build_default_collections(backend_dir)
    embedding = DeterministicEmbedding()

    durable_result = bootstrapper.rebuild_collection(collections["durable_memory"], embed_model=embedding)
    session_result = bootstrapper.rebuild_collection(collections["session_memory"], embed_model=embedding)

    assert durable_result.index_payload["status"] == "ready"
    assert session_result.index_payload["status"] == "ready"
    assert (backend_dir / "storage" / "indexes_v2" / "durable_memory" / "meta.json").exists()
    assert (backend_dir / "storage" / "indexes_v2" / "session_memory" / "meta.json").exists()

    service = RetrievalService(backend_dir)
    service.v2_bootstrapper = bootstrapper
    backend = bootstrapper.backend
    original_retrieve = backend.retrieve
    backend.retrieve = lambda request: original_retrieve(request, embed_model=embedding)
    payload = service.retrieve_memory("PowerShell retrieval refactor", top_k=4)

    sources = {str(item.get("source", "")) for item in payload}
    assert any(source.startswith("durable_memory/") for source in sources)
    assert any(source.startswith("session-memory/") for source in sources)
    assert all(item.get("retrieval_backend") == "llamaindex_v2" for item in payload)
