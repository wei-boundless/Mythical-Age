from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from retrieval.service import RetrievalService


class _DummyRewrite:
    def __init__(self) -> None:
        self.keywords = ["ai", "governance"]
        self.applied_rules = ["rewrite"]
        self.query_type = "document"


class _DummyPlan:
    def __init__(self) -> None:
        self.query = "q"
        self.rewritten_query = "rewritten q"
        self.selected_collections = ["knowledge"]
        self.reason = "default knowledge routing"
        self.rewrite = _DummyRewrite()


class _DummyRouter:
    class reranker:  # noqa: N801
        @staticmethod
        def rerank_dict_results(*, query: str, results: list[dict], text_key: str = "text", metadata_key: str = "metadata"):
            _ = text_key, metadata_key
            ranked: list[dict] = []
            for item in results:
                updated = dict(item)
                updated["rerank_backend"] = "dummy"
                updated["rerank_query"] = query
                updated["score"] = float(updated.get("score", 0.0) or 0.0) + 1.0
                ranked.append(updated)
            return ranked

    def retrieve(self, query: str, *, top_k: int = 5):
        _ = query, top_k
        return [{"text": "legacy answer", "source": "legacy.md", "modality": "text", "page": None, "score": 0.8, "collection": "knowledge", "reason": "", "rewritten_query": "", "rewrite_keywords": [], "rewrite_rules": [], "metadata": {}}]

    def plan(self, query: str):
        _ = query
        return _DummyPlan()

    class registry:  # noqa: N801
        @staticmethod
        def rebuild(name: str) -> None:
            _ = name


class _DummyBackend:
    def retrieve(self, request):
        collections = tuple(getattr(request, "collections", ()) or ())
        class Hit:
            text = "v2 answer" if "durable_memory" not in collections else "memory answer"
            source = "v2.md" if "durable_memory" not in collections else "durable_memory/note.md"
            modality = "text"
            page = None
            score = 0.9
            metadata = {"collection": "knowledge" if "durable_memory" not in collections else "durable_memory"}
            doc_id = "doc-1" if "durable_memory" not in collections else "doc-memory"
            block_id = "block-1" if "durable_memory" not in collections else "block-memory"
            object_ref_id = None
            block_type = "paragraph"
            section_path = ()
            retrieval_modes = ("dense",) if "durable_memory" not in collections else ("dense", "lexical")
            parser_backend = "docling"
            quality_flags = ()
        return [Hit()]


def test_retrieval_service_defaults_to_legacy_only(tmp_path: Path, monkeypatch) -> None:
    service = RetrievalService(tmp_path)
    service.router = _DummyRouter()
    service.v2_bootstrapper.backend = _DummyBackend()
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_cutover_mode", lambda: "legacy_only")
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_shadow_compare", lambda: False)

    payload = service.retrieve("query", top_k=3)

    assert payload[0]["text"] == "legacy answer"


def test_retrieval_service_init_is_lazy(tmp_path: Path) -> None:
    service = RetrievalService(tmp_path)

    assert service._router is None
    assert service._v2_bootstrapper is None


def test_retrieval_service_shadow_read_keeps_legacy_and_records_compare(tmp_path: Path, monkeypatch) -> None:
    service = RetrievalService(tmp_path)
    service.router = _DummyRouter()
    service.v2_bootstrapper.backend = _DummyBackend()
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_cutover_mode", lambda: "shadow_read")
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_shadow_compare", lambda: False)

    payload = service.retrieve("query", top_k=3)
    compare = service.last_shadow_compare()

    assert payload[0]["text"] == "legacy answer"
    assert compare is not None
    assert compare["legacy_hit_count"] == 1
    assert compare["v2_hit_count"] == 1
    assert compare["retrieval_backend"] == "llamaindex_v2"
    assert compare["dense_hit_count"] == 1
    assert compare["legacy_latency_ms"] is not None
    assert compare["v2_latency_ms"] is not None


def test_retrieval_service_v2_primary_returns_v2_payload(tmp_path: Path, monkeypatch) -> None:
    service = RetrievalService(tmp_path)
    service.router = _DummyRouter()
    service.v2_bootstrapper.backend = _DummyBackend()
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_cutover_mode", lambda: "v2_primary")
    monkeypatch.setattr("retrieval.service.runtime_config.get_retrieval_shadow_compare", lambda: False)

    payload = service.retrieve("query", top_k=3)

    assert payload[0]["text"] == "v2 answer"
    assert payload[0]["metadata"]["doc_id"] == "doc-1"
    assert payload[0]["rerank_backend"] == "dummy"
    assert payload[0]["rerank_query"] == "q"


def test_retrieval_service_memory_queries_use_v2_backend(tmp_path: Path) -> None:
    service = RetrievalService(tmp_path)
    service.v2_bootstrapper.backend = _DummyBackend()

    payload = service.retrieve_memory("remember my preference", top_k=2)

    assert payload[0]["text"] == "memory answer"
    assert payload[0]["collection"] == "durable_memory"
    assert payload[0]["retrieval_backend"] == "llamaindex_v2"
    assert payload[0]["metadata"]["doc_id"] == "doc-memory"
