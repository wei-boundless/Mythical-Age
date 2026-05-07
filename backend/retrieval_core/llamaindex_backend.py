from __future__ import annotations

import hashlib
import json
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_settings
from capability_system.units.mcp.local.retrieval.models import RetrievalHit
from normalized_ingestion.models import IndexableUnit
from retrieval_core.adapters import to_retrieval_hit
from retrieval_core.index_store import RetrievalLayout
from retrieval_core.lexical import build_lexical_index_payload, build_searchable_text, lexical_tokens, score_lexical_query
from retrieval_core.retrievers import RetrievalRequest


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
    ) -> dict[str, Any]:
        if not self.settings.qdrant_url:
            with self._qdrant_local_access(collection):
                return self._build_collection_qdrant_locked(
                    collection,
                    units,
                    embed_model=embed_model,
                    build_meta=build_meta,
                )
        return self._build_collection_qdrant_locked(
            collection,
            units,
            embed_model=embed_model,
            build_meta=build_meta,
        )

    def _build_collection_qdrant_locked(
        self,
        collection: str,
        units: list[IndexableUnit],
        *,
        embed_model: object | None = None,
        build_meta: dict[str, Any] | None = None,
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
        try:
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
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

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

        verification = self._verify_qdrant_collection(
            collection,
            embed_model=active_model,
            smoke_query=self._dense_smoke_query(units),
        )
        status = "ready" if verification.get("available") and verification.get("query_ok") else "invalid"
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
                with_payload=True,
                with_vectors=False,
                using=self._qdrant_dense_vector_name(client, collection_name),
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

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
            "tokenizer": "mixed_word_cjk_bigram_v1",
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
        top_k = min(max(1, int(request.top_k or 1)), len(lexical_index["doc_ids"]))
        scored = self._score_lexical_query(lexical_index, self._lexical_tokens(request.query), top_k=top_k)
        hits: list[object] = []
        for doc_idx, score in scored:
            unit_id = str(lexical_index["doc_ids"][doc_idx])
            item = dict(units_by_id.get(unit_id, {}) or {})
            if not item:
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
        return hits

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
            "fusion_backend": "application_rrf_like",
            "coalesce_backend": "application_level",
            "strategy_name": "baseline_dense_lexical",
            "chain_version": self.baseline_chain_version(),
            "primary_chain": [
                "dense_retrieval",
                "application_lexical_retrieval",
                "application_fusion",
                "coalesce",
            ],
        }

    def baseline_chain_version(self) -> str:
        return "baseline_dense_lexical__qdrant_dense__app_bm25__app_fusion__coalesce_v1"

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

    def _bm25_available(self) -> bool:
        return True

    def _dense_backend(self) -> str:
        value = str(getattr(self.settings, "vector_store_backend", "qdrant") or "qdrant").strip().lower()
        if value in {"llamaindex", "qdrant"}:
            return value
        return "qdrant"

    def _qdrant_build_batch_size(self) -> int:
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
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @contextmanager
    def _qdrant_local_access(self, collection: str):
        lock = self._qdrant_local_lock(collection)
        lock.acquire()
        try:
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
        payload["strategy_name"] = "baseline_dense_lexical"
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
        if not dense_hits and not lexical_hits:
            return []
        if not dense_hits:
            return lexical_hits[: request.top_k]
        if not lexical_hits:
            return dense_hits[: request.top_k]

        weights = self._fusion_weights(request.query_mode)
        rank_constant = 60.0
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for mode, hits in (("dense", dense_hits), ("lexical", lexical_hits)):
            for rank, hit in enumerate(hits, start=1):
                key = self._hit_key(hit)
                entry = merged.setdefault(
                    key,
                    {
                        "primary": hit,
                        "modes": [],
                        "breakdown": {},
                        "score": 0.0,
                    },
                )
                if mode == "dense":
                    entry["primary"] = hit
                contribution = float(weights.get(mode, 1.0)) / (rank_constant + float(rank))
                entry["score"] += contribution
                entry["breakdown"][mode] = float(getattr(hit, "score", 0.0) or 0.0)
                if mode not in entry["modes"]:
                    entry["modes"].append(mode)
                if len(entry["modes"]) > 1 and "fusion" not in entry["modes"]:
                    entry["modes"].append("fusion")

        fused_hits: list[RetrievalHit] = []
        for entry in merged.values():
            base = entry["primary"]
            breakdown = dict(entry["breakdown"])
            breakdown["fusion"] = float(entry["score"])
            breakdown["final"] = float(entry["score"])
            metadata = dict(getattr(base, "metadata", {}) or {})
            metadata["retrieval_stage"] = "fused"
            metadata["result_granularity"] = self._result_granularity(
                object_ref_id=getattr(base, "object_ref_id", None),
                page=getattr(base, "page", None),
                query_mode=request.query_mode,
            )
            metadata["chain_version"] = self.baseline_chain_version()
            fused_hits.append(
                RetrievalHit(
                    text=str(getattr(base, "text", "")),
                    source=str(getattr(base, "source", "")),
                    modality=str(getattr(base, "modality", "text")),
                    score=float(entry["score"]),
                    page=getattr(base, "page", None),
                    metadata=metadata,
                    hit_id=getattr(base, "hit_id", None),
                    doc_id=getattr(base, "doc_id", None),
                    block_id=getattr(base, "block_id", None),
                    object_ref_id=getattr(base, "object_ref_id", None),
                    block_type=getattr(base, "block_type", None),
                    section_path=tuple(getattr(base, "section_path", ()) or ()),
                    score_breakdown=breakdown,
                    retrieval_modes=tuple(entry["modes"]),
                    parser_backend=str(getattr(base, "parser_backend", "") or ""),
                    quality_flags=tuple(getattr(base, "quality_flags", ()) or ()),
                )
            )
        fused_hits.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return fused_hits[: request.top_k]

    def _coalesce_hits(
        self,
        hits: list[object],
        request: RetrievalRequest,
    ) -> list[object]:
        if len(hits) <= 1:
            return hits

        grouped: dict[tuple[Any, ...], list[RetrievalHit]] = {}
        for raw_hit in hits:
            hit = raw_hit if isinstance(raw_hit, RetrievalHit) else RetrievalHit(
                text=str(getattr(raw_hit, "text", "")),
                source=str(getattr(raw_hit, "source", "")),
                modality=str(getattr(raw_hit, "modality", "text")),
                score=float(getattr(raw_hit, "score", 0.0) or 0.0),
                page=getattr(raw_hit, "page", None),
                metadata=dict(getattr(raw_hit, "metadata", {}) or {}),
                hit_id=getattr(raw_hit, "hit_id", None),
                doc_id=getattr(raw_hit, "doc_id", None),
                block_id=getattr(raw_hit, "block_id", None),
                object_ref_id=getattr(raw_hit, "object_ref_id", None),
                block_type=getattr(raw_hit, "block_type", None),
                section_path=tuple(getattr(raw_hit, "section_path", ()) or ()),
                score_breakdown=dict(getattr(raw_hit, "score_breakdown", {}) or {}),
                retrieval_modes=tuple(getattr(raw_hit, "retrieval_modes", ()) or ()),
                parser_backend=str(getattr(raw_hit, "parser_backend", "") or ""),
                quality_flags=tuple(getattr(raw_hit, "quality_flags", ()) or ()),
            )
            grouped.setdefault(self._coalesce_key(hit, request.query_mode), []).append(hit)

        merged_hits: list[RetrievalHit] = []
        for bucket in grouped.values():
            bucket.sort(key=lambda item: float(item.score or 0.0), reverse=True)
            primary = bucket[0]
            merged_text = self._merge_hit_texts(bucket)
            merged_modes = self._merge_hit_modes(bucket)
            merged_breakdown = self._merge_score_breakdown(bucket)
            merged_metadata = dict(primary.metadata)
            merged_metadata["merged_hit_count"] = len(bucket)
            merged_metadata["merged_block_ids"] = [
                str(item.block_id)
                for item in bucket
                if str(item.block_id or "").strip()
            ]
            merged_metadata["retrieval_stage"] = "coalesced"
            merged_metadata["result_granularity"] = self._result_granularity(
                object_ref_id=primary.object_ref_id,
                page=primary.page,
                query_mode=request.query_mode,
            )
            merged_metadata["chain_version"] = self.baseline_chain_version()
            merged_hits.append(
                RetrievalHit(
                    text=merged_text,
                    source=primary.source,
                    modality=primary.modality,
                    score=max(float(item.score or 0.0) for item in bucket),
                    page=primary.page,
                    metadata=merged_metadata,
                    hit_id=primary.hit_id,
                    doc_id=primary.doc_id,
                    block_id=primary.block_id,
                    object_ref_id=primary.object_ref_id,
                    block_type=primary.block_type,
                    section_path=primary.section_path,
                    score_breakdown=merged_breakdown,
                    retrieval_modes=merged_modes,
                    parser_backend=primary.parser_backend,
                    quality_flags=primary.quality_flags,
                )
            )
        merged_hits.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return merged_hits[: request.top_k]

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

    def _coalesce_key(self, hit: RetrievalHit, query_mode: str) -> tuple[Any, ...]:
        doc_id = str(hit.doc_id or "").strip()
        source = str(hit.source or "").strip()
        object_ref_id = str(hit.object_ref_id or "").strip()
        page = int(hit.page or 0)
        mode = str(query_mode or "semantic_lookup")
        if object_ref_id:
            return ("object", doc_id or source, object_ref_id)
        if mode == "document_overview":
            return ("doc", doc_id or source)
        if page > 0:
            return ("page", doc_id or source, page)
        return ("doc", doc_id or source)

    def _merge_hit_texts(self, hits: list[RetrievalHit]) -> str:
        snippets: list[str] = []
        seen: set[str] = set()
        total_chars = 0
        for hit in hits:
            text = re.sub(r"\s+", " ", str(hit.text or "")).strip()
            if not text:
                continue
            if text in seen:
                continue
            if any(text in existing for existing in seen):
                continue
            seen.add(text)
            snippets.append(text)
            total_chars += len(text)
            if len(snippets) >= 3 or total_chars >= 1800:
                break
        return "\n\n".join(snippets).strip()

    def _merge_hit_modes(self, hits: list[RetrievalHit]) -> tuple[str, ...]:
        modes: list[str] = []
        for hit in hits:
            for mode in hit.retrieval_modes:
                if mode not in modes:
                    modes.append(str(mode))
        return tuple(modes)

    def _merge_score_breakdown(self, hits: list[RetrievalHit]) -> dict[str, float]:
        merged: dict[str, float] = {}
        for hit in hits:
            for key, value in dict(hit.score_breakdown).items():
                merged[key] = max(float(merged.get(key, 0.0)), float(value or 0.0))
        merged["merged_hit_count"] = float(len(hits))
        merged["final"] = max(float(hit.score or 0.0) for hit in hits) if hits else 0.0
        return merged

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
