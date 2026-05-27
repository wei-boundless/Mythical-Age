from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import get_settings
from knowledge_system.indexing.index_store import RetrievalLayout

from .collections import CollectionConfig, build_default_collections
from .models import RetrievalHit

if TYPE_CHECKING:
    from knowledge_system.indexing import RetrievalBootstrapper, RetrievalRequest


class CollectionHandle:
    def __init__(self, registry: "RAGIndexRegistry", name: str, config: CollectionConfig) -> None:
        self._registry = registry
        self.name = name
        self.config = config

    def retrieve(self, query: str, top_k: int = 5, dense_top_k: int | None = None) -> list[RetrievalHit]:
        limit = max(int(top_k or 1), int(dense_top_k or 0))
        return self._registry.retrieve_collection(
            self.name,
            query,
            top_k=max(limit, 1),
        )

    def rebuild(self) -> dict[str, Any]:
        return self._registry.rebuild(self.name)

    def status(self) -> dict[str, Any]:
        return self._registry.collection_status(self.name)


class RAGIndexRegistry:
    def __init__(self, base_dir: Path, *, ocr_language: str = "eng") -> None:
        self.base_dir = base_dir
        self.ocr_language = ocr_language
        self.settings = get_settings()
        self.layout = RetrievalLayout(base_dir)
        self.collections = build_default_collections(base_dir)
        self._handles: dict[str, CollectionHandle] = {}
        self._bootstrapper: RetrievalBootstrapper | None = None

    @property
    def backend_name(self) -> str:
        return "llamaindex"

    @property
    def bootstrapper(self):
        if self._bootstrapper is None:
            from knowledge_system.indexing import RetrievalBootstrapper

            self._bootstrapper = RetrievalBootstrapper(self.base_dir)
        return self._bootstrapper

    @property
    def backend(self):
        return self.bootstrapper.backend

    def list_collections(self) -> list[dict[str, Any]]:
        return [self.collection_status(name) for name in sorted(self.collections)]

    def get(self, name: str) -> CollectionHandle:
        config = self._require_collection(name)
        handle = self._handles.get(name)
        if handle is None:
            handle = CollectionHandle(self, name, config)
            self._handles[name] = handle
        return handle

    def rebuild(self, name: str) -> dict[str, Any]:
        config = self._require_collection(name)
        result = self.bootstrapper.rebuild_collection(config)
        payload = {
            "collection": result.collection,
            "status": str(result.index_payload.get("status", "unknown")),
            "discovered_files": result.discovered_files,
            "converted_documents": result.converted_documents,
            "normalized_blocks": result.normalized_blocks,
            "eligible_blocks": result.eligible_blocks,
            "dropped_blocks": result.dropped_blocks,
            "normalized_objects": result.normalized_objects,
            "indexable_units": result.indexable_units,
            "page_summary_units": result.page_summary_units,
            "parser_backends": list(result.parser_backends),
            "retrieval_backend": self.backend_name,
            "storage_dir": str(self.layout.collection_dir(name)),
            "index_payload": dict(result.index_payload),
        }
        return payload

    def rebuild_all(self) -> dict[str, dict[str, Any]]:
        return {name: self.rebuild(name) for name in self.collections}

    def retrieve_collection(
        self,
        name: str,
        query: str,
        *,
        top_k: int = 5,
        query_mode: str = "semantic_lookup",
    ) -> list[RetrievalHit]:
        self._require_collection(name)
        request = self._build_request(
            query=query,
            top_k=top_k,
            query_mode=query_mode,
            collections=(name,),
        )
        hits = self.backend.retrieve(request)
        payload: list[RetrievalHit] = []
        for hit in hits:
            payload.append(self._coerce_hit(hit))
        return payload

    def collection_status(self, name: str) -> dict[str, Any]:
        config = self._require_collection(name)
        meta = self._read_meta(name)
        return {
            "collection": config.name,
            "description": config.description,
            "source_dirs": [str(item) for item in config.source_dirs],
            "allowed_roots": [str(item) for item in (config.allowed_roots or config.source_dirs)],
            "storage_dir": str(self.layout.collection_dir(name)),
            "weight": config.weight,
            "allow_chat_queries": config.allow_chat_queries,
            "vector_backend": self.settings.vector_store_backend,
            "retrieval_backend": self.backend_name,
            "meta": meta,
        }

    def _build_request(
        self,
        *,
        query: str,
        top_k: int,
        query_mode: str,
        collections: tuple[str, ...],
    ):
        from knowledge_system.indexing import RetrievalRequest

        return RetrievalRequest(
            query=query,
            top_k=max(int(top_k or 1), 1),
            query_mode=str(query_mode or "semantic_lookup"),
            collections=collections,
        )

    def _read_meta(self, name: str) -> dict[str, Any]:
        path = self.layout.metadata_path(name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _require_collection(self, name: str) -> CollectionConfig:
        if name not in self.collections:
            raise KeyError(f"Unknown collection: {name}")
        return self.collections[name]

    def _coerce_hit(self, hit: Any) -> RetrievalHit:
        if isinstance(hit, RetrievalHit):
            return hit
        return RetrievalHit(
            text=str(getattr(hit, "text", "") or ""),
            source=str(getattr(hit, "source", "") or ""),
            modality=str(getattr(hit, "modality", "text") or "text"),
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


