from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from llama_index.core import (
    Document,
    Settings as LlamaSettings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.node_parser import SentenceSplitter

from config import get_settings
from embedding_compat import build_embedding_model

from .models import ParsedChunk, RetrievalHit
from .parser_adapter import MultimodalParserAdapter


class RAGMultimodalIndexer:
    """Independent multimodal RAG prototype under backend/RAG.

    It keeps the current graph RAG untouched while adding a separate pipeline
    that uses a local multimodal parsing layer before vector retrieval.
    """

    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self._index: VectorStoreIndex | None = None
        self._lock = threading.RLock()
        self._adapter: MultimodalParserAdapter | None = None

    def configure(
        self,
        base_dir: Path,
        *,
        ocr_language: str = "eng",
    ) -> None:
        with self._lock:
            self.base_dir = base_dir
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._source_dir.mkdir(parents=True, exist_ok=True)
            self._adapter = MultimodalParserAdapter(
                repo_root=base_dir.parent,
                ocr_language=ocr_language,
            )

    @property
    def _storage_dir(self) -> Path:
        if self.base_dir is None:
            raise RuntimeError("RAGMultimodalIndexer is not configured")
        return self.base_dir / "storage" / "rag_index"

    @property
    def _meta_path(self) -> Path:
        return self._storage_dir / "meta.json"

    @property
    def _source_dir(self) -> Path:
        if self.base_dir is None:
            raise RuntimeError("RAGMultimodalIndexer is not configured")
        return self.base_dir / "knowledge"

    def parser_status(self) -> dict[str, Any]:
        with self._lock:
            available = bool(self._adapter and self._adapter.parser_available())
            capabilities = self._adapter.capabilities() if self._adapter else {}
            return {
                "configured": self.base_dir is not None,
                "parser_available": available,
                "capabilities": capabilities,
                "knowledge_dir": str(self._source_dir) if self.base_dir else "",
                "vector_store_dir": str(self._storage_dir) if self.base_dir else "",
            }

    def _supports_embeddings(self) -> bool:
        return bool(get_settings().embedding_api_key)

    def _build_embed_model(self):
        return build_embedding_model(get_settings())

    def _collect_source_files(self) -> list[Path]:
        if self.base_dir is None or self._adapter is None:
            return []
        files: list[Path] = []
        for path in self._source_dir.rglob("*"):
            if self._adapter.is_supported_file(path):
                files.append(path)
        return sorted(files, key=lambda item: str(item).lower())

    def _file_digest(self) -> str:
        digest = hashlib.md5()
        for path in self._collect_source_files():
            stat = path.stat()
            digest.update(str(path).encode("utf-8", errors="ignore"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        return digest.hexdigest()

    def _read_meta(self) -> dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_meta(self, payload: dict[str, Any]) -> None:
        self._meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _chunk_to_document(self, chunk: ParsedChunk) -> Document:
        return Document(
            text=chunk.text,
            metadata={
                "source": chunk.source,
                "modality": chunk.modality,
                "page": chunk.page,
                "section": chunk.section or "",
                **chunk.metadata,
            },
        )

    def _build_documents(self) -> list[Document]:
        if self.base_dir is None or self._adapter is None:
            return []

        documents: list[Document] = []
        for path in self._collect_source_files():
            try:
                chunks = self._adapter.parse_file(path)
            except Exception:
                continue
            for chunk in chunks:
                if chunk.text.strip():
                    documents.append(self._chunk_to_document(chunk))
        return documents

    def rebuild_index(self) -> None:
        with self._lock:
            if self.base_dir is None:
                return

            parser_info = self.parser_status()
            digest = self._file_digest()

            if not parser_info["parser_available"]:
                self._index = None
                self._write_meta(
                    {
                        "digest": digest,
                        "status": "parser_unavailable",
                    }
                )
                return

            if not self._supports_embeddings():
                self._index = None
                self._write_meta(
                    {
                        "digest": digest,
                        "status": "embedding_unavailable",
                    }
                )
                return

            try:
                LlamaSettings.embed_model = self._build_embed_model()
                documents = self._build_documents()
                if not documents:
                    self._index = None
                    self._write_meta({"digest": digest, "status": "empty"})
                    return

                settings = get_settings()
                splitter = SentenceSplitter(
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                )
                nodes = splitter.get_nodes_from_documents(documents)
                self._index = VectorStoreIndex(nodes)
                self._index.storage_context.persist(persist_dir=str(self._storage_dir))
                self._write_meta(
                    {
                        "digest": digest,
                        "status": "ready",
                        "documents": len(documents),
                        "nodes": len(nodes),
                    }
                )
            except Exception as exc:
                self._index = None
                self._write_meta(
                    {
                        "digest": digest,
                        "status": "error",
                        "error": str(exc),
                    }
                )

    def _load_index(self) -> None:
        if not self._supports_embeddings():
            self._index = None
            return

        persisted_files = [
            path
            for path in self._storage_dir.iterdir()
            if path.name not in {".gitkeep", "meta.json"}
        ]
        if not persisted_files:
            self.rebuild_index()
            return

        try:
            LlamaSettings.embed_model = self._build_embed_model()
            storage_context = StorageContext.from_defaults(
                persist_dir=str(self._storage_dir)
            )
            self._index = load_index_from_storage(storage_context)
        except Exception:
            self._index = None

    def _maybe_rebuild(self) -> None:
        if self.base_dir is None:
            return
        digest = self._file_digest()
        if digest != self._read_meta().get("digest"):
            self.rebuild_index()
            return
        if self._index is None and self._supports_embeddings():
            self._load_index()

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalHit]:
        with self._lock:
            if self.base_dir is None:
                return []

            self._maybe_rebuild()
            if self._index is None:
                return []

            retriever = self._index.as_retriever(similarity_top_k=top_k)
            results = retriever.retrieve(query)
            payload: list[RetrievalHit] = []
            for item in results:
                node = getattr(item, "node", item)
                text = getattr(node, "text", "") or getattr(
                    node, "get_content", lambda: ""
                )()
                payload.append(
                    RetrievalHit(
                        text=text,
                        source=node.metadata.get("source", "knowledge"),
                        modality=node.metadata.get("modality", "text"),
                        score=float(getattr(item, "score", 0.0) or 0.0),
                        page=node.metadata.get("page"),
                        metadata={
                            key: value
                            for key, value in node.metadata.items()
                            if key not in {"source", "modality", "page"}
                        },
                    )
                )
            return payload

    def retrieve_as_dicts(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "text": hit.text,
                "source": hit.source,
                "modality": hit.modality,
                "score": hit.score,
                "page": hit.page,
                "metadata": hit.metadata,
            }
            for hit in self.retrieve(query, top_k=top_k)
        ]


rag_multimodal_indexer = RAGMultimodalIndexer()
