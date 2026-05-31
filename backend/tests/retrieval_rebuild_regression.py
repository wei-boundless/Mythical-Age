from __future__ import annotations

from types import SimpleNamespace

from knowledge_system.indexing.llamaindex_backend import LlamaIndexRetrievalBackend
from knowledge_system.ingestion.models import IndexableUnit
from knowledge_system.retrieval.service import RetrievalService


def _unit(unit_id: str, text: str) -> IndexableUnit:
    return IndexableUnit(
        unit_id=unit_id,
        unit_type="content_block",
        collection="knowledge",
        doc_id=f"doc:{unit_id}",
        source_path=f"{unit_id}.md",
        text=text,
        modality="text",
    )


def test_units_cache_invalidates_after_write(tmp_path) -> None:
    backend = LlamaIndexRetrievalBackend(tmp_path)
    backend.ensure_layout(collections=("knowledge",))

    backend._write_units("knowledge", [_unit("old", "old text")])
    assert sorted(backend._load_units_payload("knowledge")) == ["old"]

    backend._write_units("knowledge", [_unit("new", "new text")])
    assert sorted(backend._load_units_payload("knowledge")) == ["new"]


def test_rebuild_collection_consumes_pending_rebuild(monkeypatch, tmp_path) -> None:
    from capability_system.units.mcp.local.retrieval import collections

    service = RetrievalService(tmp_path)
    config = SimpleNamespace(name="knowledge")
    pending_results: list[dict] = []
    calls: list[int] = []

    monkeypatch.setattr(collections, "build_default_collections", lambda base_dir: {"knowledge": config})

    class BootstrapperStub:
        def rebuild_collection(self, received_config):
            assert received_config is config
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                pending_results.append(service.rebuild_collection("knowledge"))
            return SimpleNamespace(
                collection="knowledge",
                discovered_files=0,
                converted_documents=0,
                normalized_blocks=0,
                normalized_objects=0,
                indexable_units=0,
                parser_backends=(),
                index_payload={"status": "ready"},
            )

    service.bootstrapper = BootstrapperStub()

    result = service.rebuild_collection("knowledge")

    assert pending_results[0]["status"] == "rebuild_already_running_pending"
    assert calls == [1, 2]
    assert result["status"] == "ready"
    assert result["rebuild_status"] == "rebuilt_after_pending"
    assert result["coalesced_rebuilds"] == 2
