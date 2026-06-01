from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import get_settings
from knowledge_system.indexing.index_store import RetrievalLayout

from .collections import CollectionConfig, build_default_collections


class RAGIndexRegistry:
    def __init__(self, base_dir: Path, *, ocr_language: str = "eng") -> None:
        self.base_dir = base_dir
        self.ocr_language = ocr_language
        self.settings = get_settings()
        self.layout = RetrievalLayout(base_dir)
        self.collections = build_default_collections(base_dir)

    @property
    def backend_name(self) -> str:
        return "llamaindex"

    def list_collections(self) -> list[dict[str, Any]]:
        return [self.collection_status(name) for name in sorted(self.collections)]

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


