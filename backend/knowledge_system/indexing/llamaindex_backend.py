from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import portalocker

from config import get_settings
from capability_system.units.mcp.local.retrieval.models import RetrievalHit
from knowledge_system.ingestion.models import IndexableUnit
from knowledge_system.retrieval.candidate_graph import coalesce_with_candidate_graph
from knowledge_system.retrieval.hybrid_ranker import HybridRanker
from knowledge_system.indexing.adapters import to_retrieval_hit
from knowledge_system.indexing.index_store import RetrievalLayout
from knowledge_system.indexing.lexical import (
    build_lexical_index_payload,
    build_searchable_text,
    lexical_tokens,
    score_lexical_query,
    tokenizer_name,
)
from knowledge_system.indexing.retrievers import RetrievalRequest


class LlamaIndexRetrievalBackend:
    """Phase-2 retrieval backend with qdrant dense + application lexical BM25."""

    _qdrant_local_locks: dict[str, threading.RLock] = {}
    _qdrant_local_locks_guard = threading.Lock()

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.layout = RetrievalLayout(base_dir)
        self.settings = get_settings()
        self._lexical_cache: dict[str, dict[str, Any]] = {}
        self._units_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._hybrid_ranker = HybridRanker()

    def ensure_layout(self, *, collections: tuple[str, ...] = ("knowledge", "durable_memory", "session_memory")) -> None:
        self.layout.ensure(collections=collections)
        for collection in collections:
            self.layout.dense_dir(collection).mkdir(parents=True, exist_ok=True)
            self.layout.lexical_dir(collection).mkdir(parents=True, exist_ok=True)

    def build_collection(
        self,
        collection: str,
        units: list[IndexableUnit],
        *,
        embed_model: object | None = None,
        verify_dense_query: bool = True,
    ) -> dict[str, Any]:
        self.ensure_layout(collections=(collection,))
        self._write_units(collection, units)
        build_meta = self._new_build_meta(collection, units)

        lexical_units = self._lexical_candidate_units(units)
        lexical_payload = self._build_collection_lexical(collection, lexical_units, build_meta=build_meta)
        dense_units = [unit for unit in units if unit.text.strip()]

        if not dense_units:
            payload = self._merge_collection_payload(
                {
                    "collection": collection,
                    "status": "ready" if lexical_payload.get("lexical_documents", 0) else "empty",
                    "dense_documents": 0,
                    "vector_backend": self._dense_backend(),
                },
                lexical_payload,
                build_meta=build_meta,
            )
            self._write_metadata(collection, payload)
            return payload

        if self._dense_backend() == "qdrant":
            dense_payload = self._build_collection_qdrant(
                collection,
                dense_units,
                embed_model=embed_model,
                build_meta=build_meta,
                verify_dense_query=verify_dense_query,
            )
            payload = self._merge_collection_payload(dense_payload, lexical_payload, build_meta=build_meta)
            self._write_metadata(collection, payload)
            return payload

        from embedding_compat import build_embedding_model
        from llama_index.core import Settings as LlamaSettings, VectorStoreIndex

        dense_dir = self.layout.dense_dir(collection)
        documents = [self._document_from_unit(unit) for unit in dense_units]
        self._write_metadata(
            collection,
            self._merge_collection_payload(
                {
                    "collection": collection,
                    "status": "building",
                    "dense_documents": len(documents),
                    "vector_backend": self._dense_backend(),
                },
                lexical_payload,
                build_meta=build_meta,
            ),
        )
        LlamaSettings.embed_model = embed_model or build_embedding_model(self.settings)
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=str(dense_dir))
        dense_payload = {
            "collection": collection,
            "status": "ready",
            "dense_documents": len(documents),
            "parser_backends": sorted({str(doc.metadata.get("parser_backend", "") or "") for doc in documents}),
            "vector_backend": self._dense_backend(),
        }
        payload = self._merge_collection_payload(dense_payload, lexical_payload, build_meta=build_meta)
        self._write_metadata(collection, payload)
        return payload

    def retrieve(self, request: RetrievalRequest, *, embed_model: object | None = None) -> list[object]:
        collections = request.collections or ("knowledge",)
        hits: list[object] = []
        for collection in collections:
            dense_hits = self._retrieve_dense(collection, request, embed_model=embed_model)
            lexical_hits = self._retrieve_lexical(collection, request)
            fused_hits = self._fuse_hits(dense_hits, lexical_hits, request)
            hits.extend(self._coalesce_hits(fused_hits, request))
        hits.sort(key=lambda item: float(getattr(item, "score", 0.0) or 0.0), reverse=True)
        return hits[: request.top_k]

    def dense_health(
        self,
        collection: str,
        *,
        embed_model: object | None = None,
        smoke_query: str | None = None,
    ) -> dict[str, Any]:
        if self._dense_backend() != "qdrant":
            return {
                "collection": collection,
                "vector_backend": self._dense_backend(),
                "available": True,
                "query_ok": True,
                "status": "ready",
            }
        return self._verify_qdrant_collection(
            collection,
            embed_model=embed_model,
            smoke_query=smoke_query,
        )

    def _retrieve_dense(
        self,
        collection: str,
        request: RetrievalRequest,
        *,
        embed_model: object | None = None,
    ) -> list[object]:
        if self._dense_backend() == "qdrant":
            return self._retrieve_dense_qdrant(collection, request, embed_model=embed_model)

        from embedding_compat import build_embedding_model
        from llama_index.core import Settings as LlamaSettings, StorageContext, load_index_from_storage

        dense_dir = self.layout.dense_dir(collection)
        if not dense_dir.exists():
            return []
        persisted_files = list(dense_dir.iterdir())
        if not persisted_files:
            return []

        LlamaSettings.embed_model = embed_model or build_embedding_model(self.settings)
        storage_context = StorageContext.from_defaults(persist_dir=str(dense_dir))
        index = load_index_from_storage(storage_context)
        retriever = index.as_retriever(similarity_top_k=request.top_k)
        results = retriever.retrieve(request.query)
        hits: list[object] = []
        for item in results:
            node = getattr(item, "node", item)
            metadata = dict(getattr(node, "metadata", {}) or {})
            unit = IndexableUnit(
                unit_id=str(metadata.get("unit_id", "")),
                unit_type=str(metadata.get("unit_type", "content_block")),
                collection=collection,
                doc_id=str(metadata.get("doc_id", "")),
                source_path=str(metadata.get("source_path", collection)),
                text=str(getattr(node, "text", "") or getattr(node, "get_content", lambda: "")()),
                modality=str(metadata.get("modality", "text")),
                block_id=self._optional_str(metadata.get("block_id")),
                object_ref_id=self._optional_str(metadata.get("object_ref_id")),
                page=self._optional_int(metadata.get("page")),
                block_type=self._optional_str(metadata.get("block_type")),
                section_path=tuple(metadata.get("section_path", ()) or ()),
                metadata={key: value for key, value in metadata.items() if key not in self._reserved_metadata_keys()},
                quality_flags=tuple(metadata.get("quality_flags", ()) or ()),
            )
            hits.append(
                to_retrieval_hit(
                    unit,
                    score=float(getattr(item, "score", 0.0) or 0.0),
                    retrieval_modes=("dense",),
                    parser_backend=str(metadata.get("parser_backend", "") or ""),
                )
            )
        return hits

    def _build_collection_qdrant(
        self,
        collection: str,
        units: list[IndexableUnit],
        *,
        embed_model: object | None = None,
        build_meta: dict[str, Any] | None = None,
        verify_dense_query: bool = True,
    ) -> dict[str, Any]:
        if not self.settings.qdrant_url:
            with self._qdrant_local_access(collection):
                return self._build_collection_qdrant_locked(
                    collection,
                    units,
                    embed_model=embed_model,
                    build_meta=build_meta,
                    verify_dense_query=verify_dense_query,
                )
        return self._build_collection_qdrant_locked(
            collection,
            units,
            embed_model=embed_model,
            build_meta=build_meta,
            verify_dense_query=verify_dense_query,
        )

    def _build_collection_qdrant_locked(
        self,
        collection: str,
        units: list[IndexableUnit],
        *,
        embed_model: object | None = None,
        build_meta: dict[str, Any] | None = None,
        verify_dense_query: bool = True,
    ) -> dict[str, Any]:
        from qdrant_client import models as qmodels

        dense_dir = self.layout.dense_dir(collection)
        dense_dir.mkdir(parents=True, exist_ok=True)
        if not self.settings.qdrant_url:
            # One local qdrant root is dedicated to one collection. Reset it before
            # rebuild so stale on-disk state cannot survive when collection metadata
            # is missing or corrupted.
            self._reset_dir(dense_dir)
            dense_dir.mkdir(parents=True, exist_ok=True)
        if embed_model is None:
            from embedding_compat import build_embedding_model

        active_model = embed_model or build_embedding_model(self.settings)
        total_units = len(units)
        batch_size = self._qdrant_build_batch_size()
        parser_backends = sorted({str(unit.metadata.get("parser_backend", "") or "") for unit in units})
        client = self._qdrant_client(collection)
        collection_name = self._qdrant_collection_name(collection)
        processed = 0
        created = False
        self._write_metadata(
            collection,
            {
                "collection": collection,
                "status": "building",
                "dense_documents": total_units,
                "dense_documents_indexed": 0,
                "vector_backend": "qdrant",
                "qdrant_collection": collection_name,
                "build_batch_size": batch_size,
                **dict(build_meta or {}),
            },
        )
        for start in range(0, total_units, batch_size):
            batch_units = units[start : start + batch_size]
            batch_vectors = self._embed_texts(active_model, [unit.text for unit in batch_units])
            self._emit_embedding_cache_progress(
                collection=collection,
                embed_model=active_model,
                batch_size=len(batch_units),
            )
            if not batch_vectors:
                continue
            if not created:
                if client.collection_exists(collection_name):
                    client.delete_collection(collection_name)
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": qmodels.VectorParams(
                            size=len(batch_vectors[0]),
                            distance=qmodels.Distance.COSINE,
                        )
                    },
                )
                created = True
            points = [
                qmodels.PointStruct(
                    id=start + index + 1,
                    vector={"dense": vector},
                    payload=self._payload_from_unit(unit),
                )
                for index, (unit, vector) in enumerate(zip(batch_units, batch_vectors, strict=False))
            ]
            if points:
                client.upsert(collection_name=collection_name, points=points, wait=True)
            processed += len(points)
            progress_payload = {
                "collection": collection,
                "status": "building",
                "dense_documents": total_units,
                "dense_documents_indexed": processed,
                "vector_backend": "qdrant",
                "qdrant_collection": collection_name,
                "build_batch_size": batch_size,
                "parser_backends": parser_backends,
                **dict(build_meta or {}),
            }
            self._write_metadata(collection, progress_payload)
            self._emit_build_progress(
                collection=collection,
                processed=processed,
                total=total_units,
                batch_size=len(points),
            )

        if processed <= 0:
            return {
                "collection": collection,
                "status": "empty",
                "dense_documents": 0,
                "dense_documents_indexed": 0,
                "vector_backend": "qdrant",
                "qdrant_collection": collection_name,
                "build_batch_size": batch_size,
                "dense_status": "empty",
            }

        if verify_dense_query:
            verification = self._verify_qdrant_collection(
                collection,
                embed_model=active_model,
                smoke_query=self._dense_smoke_query(units),
            )
            status = "ready" if verification.get("available") and verification.get("query_ok") else "invalid"
        else:
            verification = {
                "collection": collection,
                "collection_name": collection_name,
                "vector_backend": "qdrant",
                "available": True,
                "query_ok": True,
                "points_count": processed,
                "status": "ready",
                "verification_skipped": True,
            }
            status = "ready" if processed == total_units else "invalid"
        return {
            "collection": collection,
            "status": status,
            "dense_documents": total_units,
            "dense_documents_indexed": processed,
            "parser_backends": parser_backends,
            "vector_backend": "qdrant",
            "qdrant_collection": collection_name,
            "build_batch_size": batch_size,
            "dense_status": status,
            "dense_verification": verification,
            "dense_vector_name": "dense",
        }

    def _retrieve_dense_qdrant(
        self,
        collection: str,
        request: RetrievalRequest,
        *,
        embed_model: object | None = None,
    ) -> list[object]:
        if not self.settings.qdrant_url:
            with self._qdrant_local_access(collection):
                return self._retrieve_dense_qdrant_locked(collection, request, embed_model=embed_model)
        return self._retrieve_dense_qdrant_locked(collection, request, embed_model=embed_model)

    def _retrieve_dense_qdrant_locked(
        self,
        collection: str,
        request: RetrievalRequest,
        *,
        embed_model: object | None = None,
    ) -> list[object]:
        client = self._qdrant_client(collection)
        collection_name = self._qdrant_collection_name(collection)
        try:
            if not client.collection_exists(collection_name):
                return []
            if embed_model is None:
                from embedding_compat import build_embedding_model

            active_model = embed_model or build_embedding_model(self.settings)
            query_vector = self._embed_query(active_model, request.query)
            if not query_vector:
                return []
            result = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=request.top_k,
                query_filter=self._qdrant_filter_from_request(request),
                with_payload=True,
                with_vectors=False,
                using=self._qdrant_dense_vector_name(client, collection_name),
            )
        finally:
            pass

        hits: list[object] = []
        for item in getattr(result, "points", []) or []:
            payload = dict(getattr(item, "payload", {}) or {})
            unit = IndexableUnit(
                unit_id=str(payload.get("unit_id", "")),
                unit_type=str(payload.get("unit_type", "content_block")),
                collection=collection,
                doc_id=str(payload.get("doc_id", "")),
                source_path=str(payload.get("source_path", collection)),
                text=str(payload.get("text", "")),
                modality=str(payload.get("modality", "text")),
                block_id=self._optional_str(payload.get("block_id")),
                object_ref_id=self._optional_str(payload.get("object_ref_id")),
                page=self._optional_int(payload.get("page")),
                block_type=self._optional_str(payload.get("block_type")),
                section_path=tuple(payload.get("section_path", ()) or ()),
                metadata={key: value for key, value in payload.items() if key not in self._reserved_payload_keys()},
                quality_flags=tuple(payload.get("quality_flags", ()) or ()),
            )
            hits.append(
                self._annotate_hit(
                    to_retrieval_hit(
                        unit,
                        score=float(getattr(item, "score", 0.0) or 0.0),
                        retrieval_modes=("dense",),
                        parser_backend=str(payload.get("parser_backend", "") or ""),
                    ),
                    query_mode=request.query_mode,
                    retrieval_stage="dense",
                )
            )
        return hits

    def _build_collection_lexical(
        self,
        collection: str,
        units: list[IndexableUnit],
        *,
        build_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lexical_dir = self.layout.lexical_dir(collection)
        self._reset_dir(lexical_dir)
        lexical_dir.mkdir(parents=True, exist_ok=True)
        self._lexical_cache.pop(collection, None)
        if not self._bm25_available() or not units:
            return {
                "collection": collection,
                "status": "disabled" if not self._bm25_available() else "empty",
                "lexical_documents": 0,
            }

        index_payload = self._build_lexical_index_payload(units)
        (lexical_dir / "index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        meta_payload = {
            "collection": collection,
            "status": "ready",
            "lexical_documents": len(units),
            "tokenizer": tokenizer_name(),
            "k1": index_payload["k1"],
            "b": index_payload["b"],
            **dict(build_meta or {}),
        }
        (lexical_dir / "meta.json").write_text(
            json.dumps(meta_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return meta_payload

    def _retrieve_lexical(self, collection: str, request: RetrievalRequest) -> list[object]:
        lexical_dir = self.layout.lexical_dir(collection)
        if not self._bm25_available() or not lexical_dir.exists():
            return []
        index_path = lexical_dir / "index.json"
        if not index_path.exists():
            return []
        lexical_index = self._load_lexical_index(collection)
        if not lexical_index.get("doc_ids"):
            return []
        units_by_id = self._load_units_payload(collection)
        filter_active = bool(request.filters)
        multiplier = 4 if filter_active else 1
        top_k = min(max(1, int(request.top_k or 1) * multiplier), len(lexical_index["doc_ids"]))
        scored = self._score_lexical_query(lexical_index, self._lexical_tokens(request.query), top_k=top_k)
        hits: list[object] = []
        for doc_idx, score in scored:
            unit_id = str(lexical_index["doc_ids"][doc_idx])
            item = dict(units_by_id.get(unit_id, {}) or {})
            if not item:
                continue
            if not self._unit_payload_matches_filters(item, request.filters):
                continue
            unit = IndexableUnit(
                unit_id=str(item.get("unit_id", "")),
                unit_type=str(item.get("unit_type", "content_block")),
                collection=collection,
                doc_id=str(item.get("doc_id", "")),
                source_path=str(item.get("source_path", collection)),
                text=str(item.get("text", "")),
                modality=str(item.get("modality", "text")),
                block_id=self._optional_str(item.get("block_id")),
                object_ref_id=self._optional_str(item.get("object_ref_id")),
                page=self._optional_int(item.get("page")),
                block_type=self._optional_str(item.get("block_type")),
                section_path=tuple(item.get("section_path", ()) or ()),
                metadata={key: value for key, value in item.items() if key not in self._reserved_payload_keys()},
                quality_flags=tuple(item.get("quality_flags", ()) or ()),
            )
            hits.append(
                self._annotate_hit(
                    to_retrieval_hit(
                        unit,
                        score=float(score or 0.0),
                        retrieval_modes=("lexical",),
                        parser_backend=str(item.get("parser_backend", "") or ""),
                    ),
                    query_mode=request.query_mode,
                    retrieval_stage="lexical",
                )
            )
        return hits[: request.top_k]

    def _document_from_unit(self, unit: IndexableUnit):
        from llama_index.core import Document

        return Document(
            text=unit.text,
            metadata=self._payload_from_unit(unit, include_text=False),
        )

    def _write_metadata(self, collection: str, payload: dict[str, Any]) -> None:
        self.layout.collection_dir(collection).mkdir(parents=True, exist_ok=True)
        enriched = dict(payload)
        enriched["metadata_schema_version"] = "retrieval_v2_meta_v1"
        enriched["layout_root"] = str(self.layout.root)
        enriched["collection_dir"] = str(self.layout.collection_dir(collection))
        enriched["metadata_path"] = str(self.layout.metadata_path(collection))
        enriched["written_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.layout.metadata_path(collection).write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def runtime_descriptor(self) -> dict[str, Any]:
        return {
            "retrieval_backend": "llamaindex",
            "dense_backend": self._dense_backend(),
            "sparse_backend": "none",
            "lexical_backend": "application_bm25",
            "fusion_backend": "hybrid_ranker_v1",
            "coalesce_backend": "application_level",
            "strategy_name": "hybrid_dense_lexical",
            "chain_version": self.baseline_chain_version(),
            "primary_chain": [
                "dense_retrieval",
                "application_lexical_retrieval",
                "hybrid_ranker",
                "coalesce",
            ],
        }

    def baseline_chain_version(self) -> str:
        return "hybrid_dense_lexical__qdrant_dense__app_bm25__hybrid_ranker__coalesce_v2"

    def _write_units(self, collection: str, units: list[IndexableUnit]) -> None:
        payload = [
            {
                "unit_id": unit.unit_id,
                "unit_type": unit.unit_type,
                "collection": unit.collection,
                "doc_id": unit.doc_id,
                "source_path": unit.source_path,
                "text": unit.text,
                "modality": unit.modality,
                "block_id": unit.block_id,
                "object_ref_id": unit.object_ref_id,
                "page": unit.page,
                "block_type": unit.block_type,
                "section_path": list(unit.section_path),
                "metadata": dict(unit.metadata),
                "quality_flags": list(unit.quality_flags),
            }
            for unit in units
        ]
        self.layout.units_path(collection).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._units_cache.pop(collection, None)

    def _bm25_available(self) -> bool:
        return True

    def _dense_backend(self) -> str:
        value = str(getattr(self.settings, "vector_store_backend", "qdrant") or "qdrant").strip().lower()
        if value in {"llamaindex", "qdrant"}:
            return value
        return "qdrant"

    def _qdrant_build_batch_size(self) -> int:
        configured = getattr(self.settings, "qdrant_build_batch_size", None)
        if configured is not None:
            try:
                return max(int(configured), 1)
            except (TypeError, ValueError):
                pass
        return 128

    def _emit_build_progress(
        self,
        *,
        collection: str,
        processed: int,
        total: int,
        batch_size: int,
    ) -> None:
        safe_total = max(int(total or 0), 1)
        percent = (float(processed) / float(safe_total)) * 100.0
        print(
            f"[retrieval-build] collection={collection} processed={processed}/{safe_total} "
            f"batch={batch_size} percent={percent:.1f}",
            flush=True,
        )

    def _emit_embedding_cache_progress(self, *, collection: str, embed_model: object, batch_size: int) -> None:
        stats = getattr(embed_model, "last_batch_stats", None)
        if not isinstance(stats, dict):
            return
        print(
            f"[retrieval-build-cache] collection={collection} "
            f"requested={int(stats.get('requested') or batch_size)} "
            f"hits={int(stats.get('hits') or 0)} "
            f"misses={int(stats.get('misses') or 0)}",
            flush=True,
        )

    def _qdrant_client(self, collection: str):
        from qdrant_client import QdrantClient

        if self.settings.qdrant_url:
            return QdrantClient(url=self.settings.qdrant_url, api_key=self.settings.qdrant_api_key)
        dense_dir = self.layout.dense_dir(collection)
        dense_dir.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(dense_dir))

    def _qdrant_collection_name(self, collection: str) -> str:
        prefix = str(self.settings.qdrant_collection_prefix or "agent").strip().replace(" ", "_")
        return f"{prefix}__{collection}"

    def _verify_qdrant_collection(
        self,
        collection: str,
        *,
        embed_model: object | None,
        smoke_query: str | None,
    ) -> dict[str, Any]:
        if not self.settings.qdrant_url:
            with self._qdrant_local_access(collection):
                return self._verify_qdrant_collection_locked(
                    collection,
                    embed_model=embed_model,
                    smoke_query=smoke_query,
                )
        return self._verify_qdrant_collection_locked(
            collection,
            embed_model=embed_model,
            smoke_query=smoke_query,
        )

    def _verify_qdrant_collection_locked(
        self,
        collection: str,
        *,
        embed_model: object | None,
        smoke_query: str | None,
    ) -> dict[str, Any]:
        client = self._qdrant_client(collection)
        collection_name = self._qdrant_collection_name(collection)
        payload: dict[str, Any] = {
            "collection": collection,
            "collection_name": collection_name,
            "vector_backend": "qdrant",
            "available": False,
            "query_ok": False,
            "points_count": 0,
            "status": "invalid",
        }
        try:
            exists = bool(client.collection_exists(collection_name))
            payload["available"] = exists
            if not exists:
                payload["error"] = "collection_missing"
                return payload
            info = client.get_collection(collection_name)
            points_count = int(getattr(info, "points_count", 0) or 0)
            payload["points_count"] = points_count
            if points_count <= 0:
                payload["error"] = "collection_empty"
                return payload
            query = str(smoke_query or "").strip()
            if not query or embed_model is None:
                payload["query_ok"] = True
                payload["status"] = "ready"
                return payload
            query_vector = self._embed_query(embed_model, query)
            if not query_vector:
                payload["error"] = "smoke_query_embedding_empty"
                return payload
            result = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=1,
                with_payload=False,
                with_vectors=False,
                using=self._qdrant_dense_vector_name(client, collection_name),
            )
            payload["query_ok"] = bool(getattr(result, "points", []) or [])
            payload["status"] = "ready" if payload["query_ok"] else "invalid"
            if not payload["query_ok"]:
                payload["error"] = "smoke_query_no_hits"
            return payload
        except Exception as exc:
            payload["error"] = str(exc)
            return payload

    @contextmanager
    def _qdrant_local_access(self, collection: str):
        lock = self._qdrant_local_lock(collection)
        dense_dir = self.layout.dense_dir(collection)
        dense_dir.mkdir(parents=True, exist_ok=True)
        file_lock_path = dense_dir / ".access.lock"
        lock.acquire()
        try:
            with portalocker.Lock(str(file_lock_path), timeout=300, flags=portalocker.LockFlags.EXCLUSIVE):
                yield
        finally:
            lock.release()

    def _qdrant_local_lock(self, collection: str) -> threading.RLock:
        dense_dir = self.layout.dense_dir(collection).resolve()
        key = str(dense_dir).lower()
        with self._qdrant_local_locks_guard:
            lock = self._qdrant_local_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._qdrant_local_locks[key] = lock
            return lock

    @staticmethod
    def _dense_smoke_query(units: list[IndexableUnit]) -> str | None:
        for unit in units:
            text = str(unit.text or "").strip()
            if text:
                return text[:512]
        return None

    def _qdrant_dense_vector_name(self, client: Any, collection_name: str) -> str | None:
        try:
            info = client.get_collection(collection_name)
        except Exception:
            return None
        params = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(params, "vectors", None)
        if isinstance(vectors, dict):
            if "dense" in vectors:
                return "dense"
            keys = [str(key) for key in vectors.keys() if str(key).strip()]
            if len(keys) == 1:
                return keys[0]
        return None

    def _qdrant_filter_from_request(self, request: RetrievalRequest) -> Any | None:
        filters = dict(request.filters or {})
        if not filters:
            return None
        from qdrant_client import models as qmodels

        must: list[Any] = []
        for field_name, key in (
            ("modality", "modality_any"),
            ("unit_type", "unit_type_any"),
            ("block_type", "block_type_any"),
            ("doc_id", "doc_id_any"),
            ("page", "page_any"),
        ):
            values = list(filters.get(key, []) or [])
            if values:
                must.append(qmodels.FieldCondition(key=field_name, match=qmodels.MatchAny(any=values)))
        for term in list(filters.get("source_path_contains_any", []) or []):
            if str(term).strip():
                must.append(qmodels.FieldCondition(key="source_path", match=qmodels.MatchText(text=str(term).strip())))
        if not must:
            return None
        return qmodels.Filter(must=must)

    def _unit_payload_matches_filters(self, item: dict[str, Any], filters: dict[str, Any]) -> bool:
        if not filters:
            return True
        for key, field_name in (
            ("modality_any", "modality"),
            ("unit_type_any", "unit_type"),
            ("block_type_any", "block_type"),
            ("doc_id_any", "doc_id"),
        ):
            expected = {str(value) for value in list(filters.get(key, []) or []) if str(value).strip()}
            if expected and str(item.get(field_name, "") or "") not in expected:
                return False
        page_values = {int(value) for value in list(filters.get("page_any", []) or []) if str(value).strip()}
        if page_values:
            try:
                page = int(item.get("page", 0) or 0)
            except (TypeError, ValueError):
                page = 0
            if page not in page_values:
                return False
        source_terms = [str(value).strip().lower() for value in list(filters.get("source_path_contains_any", []) or []) if str(value).strip()]
        if source_terms:
            source = str(item.get("source_path", "") or "").lower()
            if not any(term in source for term in source_terms):
                return False
        excluded_flags = {str(value) for value in list(filters.get("quality_flags_exclude_any", []) or []) if str(value).strip()}
        if excluded_flags:
            quality_flags = {str(value) for value in list(item.get("quality_flags", []) or [])}
            if quality_flags & excluded_flags:
                return False
        return True

    def _embed_texts(self, embed_model: object, texts: list[str]) -> list[list[float]]:
        batch = getattr(embed_model, "get_text_embedding_batch", None)
        if callable(batch):
            return [list(item) for item in batch(texts)]
        batch = getattr(embed_model, "_get_text_embeddings", None)
        if callable(batch):
            return [list(item) for item in batch(texts)]
        single = getattr(embed_model, "get_text_embedding", None)
        if callable(single):
            return [list(single(text)) for text in texts]
        single = getattr(embed_model, "_get_text_embedding", None)
        if callable(single):
            return [list(single(text)) for text in texts]
        raise TypeError("Embedding model does not expose a supported text embedding method")

    def _embed_query(self, embed_model: object, query: str) -> list[float]:
        getter = getattr(embed_model, "get_query_embedding", None)
        if callable(getter):
            return list(getter(query))
        getter = getattr(embed_model, "_get_query_embedding", None)
        if callable(getter):
            return list(getter(query))
        getter = getattr(embed_model, "get_text_embedding", None)
        if callable(getter):
            return list(getter(query))
        getter = getattr(embed_model, "_get_text_embedding", None)
        if callable(getter):
            return list(getter(query))
        raise TypeError("Embedding model does not expose a supported query embedding method")

    def _payload_from_unit(self, unit: IndexableUnit, *, include_text: bool = True) -> dict[str, Any]:
        payload = {
            "unit_id": unit.unit_id,
            "unit_type": unit.unit_type,
            "collection": unit.collection,
            "doc_id": unit.doc_id,
            "source_path": unit.source_path,
            "modality": unit.modality,
            "block_id": unit.block_id,
            "object_ref_id": unit.object_ref_id,
            "page": unit.page,
            "block_type": unit.block_type,
            "section_path": list(unit.section_path),
            "parser_backend": str(unit.metadata.get("parser_backend", "") or ""),
            "quality_flags": list(unit.quality_flags),
            **dict(unit.metadata),
        }
        if include_text:
            payload["text"] = unit.text
        return payload

    def _lexical_candidate_units(self, units: list[IndexableUnit]) -> list[IndexableUnit]:
        selected: list[IndexableUnit] = []
        for unit in units:
            if not unit.text.strip():
                continue
            index_profiles = {str(item) for item in unit.metadata.get("index_profiles", []) or []}
            if (
                "lexical_main" in index_profiles
                or unit.unit_type in {"object_block", "page_summary"}
                or (unit.unit_type == "content_block" and not index_profiles)
                or (unit.unit_type == "document" and not index_profiles)
            ):
                selected.append(unit)
        return selected

    def _merge_collection_payload(
        self,
        dense_payload: dict[str, Any],
        lexical_payload: dict[str, Any],
        *,
        build_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(dense_payload)
        lexical_documents = int(lexical_payload.get("lexical_documents", 0) or 0)
        payload["lexical_enabled"] = bool(lexical_documents > 0)
        payload["lexical_documents"] = lexical_documents
        if lexical_payload.get("status"):
            payload["lexical_status"] = str(lexical_payload["status"])
        payload["strategy_name"] = "hybrid_dense_lexical"
        payload["chain_version"] = self.baseline_chain_version()
        payload["runtime_descriptor"] = self.runtime_descriptor()
        if build_meta:
            payload.update(dict(build_meta))
        return payload

    def _fuse_hits(
        self,
        dense_hits: list[object],
        lexical_hits: list[object],
        request: RetrievalRequest,
    ) -> list[object]:
        return self._hybrid_ranker.rank(
            {"dense": [self._coerce_retrieval_hit(item) for item in dense_hits], "lexical": [self._coerce_retrieval_hit(item) for item in lexical_hits]},
            top_k=request.top_k,
            query_mode=request.query_mode,
            weights=self._fusion_weights(request.query_mode),
            key_fn=self._hit_key,
            result_granularity_fn=lambda hit: self._result_granularity(
                object_ref_id=hit.object_ref_id,
                page=hit.page,
                query_mode=request.query_mode,
            ),
            chain_version=self.baseline_chain_version(),
        )

    def _coalesce_hits(
        self,
        hits: list[object],
        request: RetrievalRequest,
    ) -> list[object]:
        if len(hits) <= 1:
            return hits
        return coalesce_with_candidate_graph(
            hits,
            query_mode=request.query_mode,
            chain_version=self.baseline_chain_version(),
            top_k=request.top_k,
        )

    def _fusion_weights(self, query_mode: str) -> dict[str, float]:
        mode = str(query_mode or "semantic_lookup")
        if mode == "table_lookup":
            return {"dense": 0.7, "lexical": 1.0}
        if mode == "document_overview":
            return {"dense": 1.0, "lexical": 0.6}
        if mode == "page_grounded_lookup":
            return {"dense": 1.0, "lexical": 0.7}
        return {"dense": 1.0, "lexical": 0.8}

    def _hit_key(self, hit: object) -> tuple[Any, ...]:
        hit_id = getattr(hit, "hit_id", None)
        if hit_id:
            return ("hit_id", hit_id)
        return (
            str(getattr(hit, "doc_id", "") or ""),
            str(getattr(hit, "block_id", "") or ""),
            str(getattr(hit, "object_ref_id", "") or ""),
            str(getattr(hit, "source", "") or ""),
            int(getattr(hit, "page", 0) or 0),
        )

    def _coerce_retrieval_hit(self, hit: object) -> RetrievalHit:
        if isinstance(hit, RetrievalHit):
            return hit
        return RetrievalHit(
            text=str(getattr(hit, "text", "")),
            source=str(getattr(hit, "source", "")),
            modality=str(getattr(hit, "modality", "text")),
            score=float(getattr(hit, "score", 0.0) or 0.0),
            page=getattr(hit, "page", None),
            metadata=dict(getattr(hit, "metadata", {}) or {}),
            hit_id=getattr(hit, "hit_id", None),
            doc_id=getattr(hit, "doc_id", None),
            block_id=getattr(hit, "block_id", None),
            object_ref_id=getattr(hit, "object_ref_id", None),
            block_type=getattr(hit, "block_type", None),
            section_path=tuple(getattr(hit, "section_path", ()) or ()),
            score_breakdown=dict(getattr(hit, "score_breakdown", {}) or {}),
            retrieval_modes=tuple(getattr(hit, "retrieval_modes", ()) or ()),
            parser_backend=str(getattr(hit, "parser_backend", "") or ""),
            quality_flags=tuple(getattr(hit, "quality_flags", ()) or ()),
        )

    def _annotate_hit(
        self,
        hit: RetrievalHit,
        *,
        query_mode: str,
        retrieval_stage: str,
    ) -> RetrievalHit:
        metadata = dict(hit.metadata)
        metadata["result_granularity"] = self._result_granularity(
            object_ref_id=hit.object_ref_id,
            page=hit.page,
            query_mode=query_mode,
        )
        metadata["retrieval_stage"] = retrieval_stage
        metadata["chain_version"] = self.baseline_chain_version()
        return RetrievalHit(
            text=hit.text,
            source=hit.source,
            modality=hit.modality,
            score=hit.score,
            page=hit.page,
            metadata=metadata,
            hit_id=hit.hit_id,
            doc_id=hit.doc_id,
            block_id=hit.block_id,
            object_ref_id=hit.object_ref_id,
            block_type=hit.block_type,
            section_path=hit.section_path,
            score_breakdown=dict(hit.score_breakdown),
            retrieval_modes=tuple(hit.retrieval_modes),
            parser_backend=hit.parser_backend,
            quality_flags=hit.quality_flags,
        )

    def _result_granularity(self, *, object_ref_id: object | None, page: object | None, query_mode: str) -> str:
        if str(object_ref_id or "").strip():
            return "object"
        if str(query_mode or "") == "document_overview":
            return "document"
        if page not in (None, "", 0):
            return "page"
        return "block"

    def _new_build_meta(self, collection: str, units: list[IndexableUnit]) -> dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        digest = hashlib.sha1()
        digest.update(collection.encode("utf-8", errors="ignore"))
        digest.update(str(len(units)).encode("utf-8"))
        digest.update(started.encode("utf-8"))
        for unit in units[:32]:
            digest.update(str(unit.unit_id).encode("utf-8", errors="ignore"))
            digest.update(str(unit.doc_id).encode("utf-8", errors="ignore"))
        return {
            "build_id": f"{collection}-{digest.hexdigest()[:12]}",
            "build_started_at_utc": started,
        }

    def _payload_to_unit_payload(self, value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            converted = tolist()
            if isinstance(converted, dict):
                return dict(converted)
        return {}

    def _build_lexical_index_payload(self, units: list[IndexableUnit]) -> dict[str, Any]:
        payload = build_lexical_index_payload(
            [
                build_searchable_text(
                    unit.text,
                    source=unit.source_path,
                    metadata=dict(unit.metadata),
                )
                for unit in units
            ]
        )
        payload["doc_ids"] = [unit.unit_id for unit in units]
        return payload

    def _load_lexical_index(self, collection: str) -> dict[str, Any]:
        cached = self._lexical_cache.get(collection)
        if cached is not None:
            return cached
        index_path = self.layout.lexical_dir(collection) / "index.json"
        if not index_path.exists():
            payload = {"doc_ids": [], "doc_lengths": [], "avg_doc_length": 0.0, "doc_count": 0, "k1": 1.5, "b": 0.75, "postings": {}}
            self._lexical_cache[collection] = payload
            return payload
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self._lexical_cache[collection] = payload
        return payload

    def _load_units_payload(self, collection: str) -> dict[str, dict[str, Any]]:
        cached = self._units_cache.get(collection)
        if cached is not None:
            return cached
        units_path = self.layout.units_path(collection)
        if not units_path.exists():
            self._units_cache[collection] = {}
            return {}
        payload = json.loads(units_path.read_text(encoding="utf-8"))
        mapped = {str(item.get("unit_id", "")): dict(item) for item in payload}
        self._units_cache[collection] = mapped
        return mapped

    def _score_lexical_query(
        self,
        lexical_index: dict[str, Any],
        query_tokens: list[str],
        *,
        top_k: int,
    ) -> list[tuple[int, float]]:
        return score_lexical_query(lexical_index, query_tokens, top_k=top_k)

    def _lexical_tokens(self, text: str) -> list[str]:
        return lexical_tokens(text)

    def _reset_dir(self, path: Path) -> None:
        if not path.exists():
            return
        for child in path.iterdir():
            if child.name == ".access.lock":
                continue
            if child.is_dir():
                self._reset_dir(child)
                child.rmdir()
            else:
                child.unlink()

    @staticmethod
    def _reserved_metadata_keys() -> set[str]:
        return {
            "unit_id",
            "unit_type",
            "doc_id",
            "source_path",
            "modality",
            "block_id",
            "object_ref_id",
            "page",
            "block_type",
            "section_path",
            "parser_backend",
            "quality_flags",
        }

    @staticmethod
    def _reserved_payload_keys() -> set[str]:
        return {
            "unit_id",
            "unit_type",
            "doc_id",
            "source_path",
            "text",
            "modality",
            "block_id",
            "object_ref_id",
            "page",
            "block_type",
            "section_path",
            "parser_backend",
            "quality_flags",
        }

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


