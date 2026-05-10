from __future__ import annotations

import pytest

from capability_system.units.mcp.local.retrieval.benchmark_runner import (
    _index_payload_ready,
    _load_existing_index_payload,
    _publish_benchmark_collection,
)


class _FakeLayout:
    def __init__(self, path):
        self._path = path

    def metadata_path(self, collection: str):
        return self._path

    def collection_dir(self, collection: str):
        return self._path.parent


class _FakeBackend:
    def __init__(self, path):
        self.layout = _FakeLayout(path)


def test_index_payload_ready_rejects_interrupted_build() -> None:
    assert not _index_payload_ready(
        {
            "status": "building",
            "dense_documents": 10,
            "dense_documents_indexed": 4,
        }
    )


def test_load_existing_index_payload_fails_on_partial_meta(tmp_path) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(
        '{"collection":"benchmark","status":"building","dense_documents":10,"dense_documents_indexed":4}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="not ready"):
        _load_existing_index_payload(_FakeBackend(meta), "benchmark")


class _FakeBenchmarkLayout:
    def __init__(self, root):
        self.root = root

    def collection_dir(self, collection: str):
        return self.root / "storage" / "indexes" / collection


class _FakeBenchmarkBackend:
    def __init__(self, root):
        self.layout = _FakeBenchmarkLayout(root)


def test_publish_benchmark_collection_keeps_existing_index_if_publish_fails(tmp_path, monkeypatch) -> None:
    final_backend = _FakeBenchmarkBackend(tmp_path / "final")
    staging_backend = _FakeBenchmarkBackend(tmp_path / "staging")
    final_collection = final_backend.layout.collection_dir("benchmark")
    staging_collection = staging_backend.layout.collection_dir("benchmark")
    final_collection.mkdir(parents=True)
    staging_collection.mkdir(parents=True)
    (final_collection / "meta.json").write_text('{"status":"ready","marker":"old"}', encoding="utf-8")
    (staging_collection / "meta.json").write_text('{"status":"ready","marker":"new"}', encoding="utf-8")

    def fail_move(source: str, destination: str) -> None:
        raise RuntimeError("forced publish failure")

    monkeypatch.setattr("capability_system.units.mcp.local.retrieval.benchmark_runner.shutil.move", fail_move)

    with pytest.raises(RuntimeError, match="forced publish failure"):
        _publish_benchmark_collection(staging_backend, final_backend)

    assert (final_collection / "meta.json").read_text(encoding="utf-8") == '{"status":"ready","marker":"old"}'
