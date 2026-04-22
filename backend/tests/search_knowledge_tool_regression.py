from __future__ import annotations

import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from RAG.collections import build_default_collections
from document_conversion import DoclingConverter
from retrieval_core import RetrievalV2Bootstrapper
from tools.search_knowledge_tool import SearchKnowledgeBaseTool


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
            bucket[index % 4] += (ord(char) % 23) / 23.0
        norm = sum(value * value for value in bucket) ** 0.5 or 1.0
        return [value / norm for value in bucket]


@contextmanager
def _workspace_tmp_dir(prefix: str):
    root = BACKEND_DIR.parent / ".tmp-tests" / f"{prefix}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_search_knowledge_tool_uses_v2_registry(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "alpha.md").write_text(
        "# Alpha\n\nAI governance baseline and control requirements.\n",
        encoding="utf-8",
    )

    embedding = DeterministicEmbedding()
    bootstrapper = RetrievalV2Bootstrapper(backend_dir, converter=DoclingConverter(enabled=False))
    config = build_default_collections(backend_dir)["knowledge"]
    bootstrapper.rebuild_collection(config, embed_model=embedding)

    tool = SearchKnowledgeBaseTool(root_dir=backend_dir)
    backend = tool._registry.backend
    original_retrieve = backend.retrieve
    backend.retrieve = lambda request: original_retrieve(request, embed_model=embedding)
    output = tool._run("AI governance", top_k=3)

    assert "alpha.md" in output
    assert "modes=" in output
    assert (backend_dir / "storage" / "indexes_v2" / "knowledge" / "meta.json").exists()


def main() -> None:
    with _workspace_tmp_dir("search-knowledge") as root:
        test_search_knowledge_tool_uses_v2_registry(root)
    print("PASS test_search_knowledge_tool_uses_v2_registry")
    print("ALL PASSED (1 test)")


if __name__ == "__main__":
    main()
