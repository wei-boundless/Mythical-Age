from __future__ import annotations

from knowledge_system.indexing.embedding_cache import CachedEmbeddingModel


class _CountingEmbedding:
    model_name = "fake-embedding"
    dimensions = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_text_embedding_batch(self, texts: list[str], show_progress: bool | None = None) -> list[list[float]]:
        _ = show_progress
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def test_cached_embedding_model_reuses_vectors_across_instances(tmp_path) -> None:
    cache_path = tmp_path / "embedding.sqlite3"
    first_inner = _CountingEmbedding()
    first = CachedEmbeddingModel(first_inner, cache_path=cache_path, namespace="benchmark")

    assert first.get_text_embedding_batch(["alpha", "beta"]) == [[5.0, 1.0, 0.0], [4.0, 1.0, 0.0]]
    assert first_inner.calls == [["alpha", "beta"]]

    second_inner = _CountingEmbedding()
    second = CachedEmbeddingModel(second_inner, cache_path=cache_path, namespace="benchmark")

    assert second.get_text_embedding_batch(["alpha", "beta"]) == [[5.0, 1.0, 0.0], [4.0, 1.0, 0.0]]
    assert second_inner.calls == []


def test_cached_embedding_model_only_embeds_missing_texts(tmp_path) -> None:
    cache_path = tmp_path / "embedding.sqlite3"
    inner = _CountingEmbedding()
    cached = CachedEmbeddingModel(inner, cache_path=cache_path, namespace="benchmark")

    cached.get_text_embedding_batch(["alpha"])
    cached.get_text_embedding_batch(["alpha", "gamma"])

    assert inner.calls == [["alpha"], ["gamma"]]
