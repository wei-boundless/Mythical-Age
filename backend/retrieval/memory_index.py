from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from llama_index.core import Document, Settings as LlamaSettings, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.node_parser import SentenceSplitter

from config import get_settings
from memory_layout import DurableMemoryLayout
from RAG.faiss_store import FaissIndexStore
from embedding_compat import build_embedding_model
from structured_memory import MemoryManager


class MemoryIndexer:
    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self._index: VectorStoreIndex | None = None
        self._faiss_store: FaissIndexStore | None = None
        self._lock = threading.RLock()
        self._max_workers = max(2, min(8, os.cpu_count() or 4))

    def _cleanup_stale_index_files(self, backend: str) -> None:
        stale_for_faiss = {
            "default__vector_store.json",
            "docstore.json",
            "graph_store.json",
            "image__vector_store.json",
            "index_store.json",
        }
        stale_for_llamaindex = {"faiss.index", "faiss_records.json"}
        stale = stale_for_faiss if backend == "faiss" else stale_for_llamaindex
        for name in stale:
            path = self._storage_dir / name
            if path.exists():
                path.unlink()

    def configure(self, base_dir: Path) -> None:
        with self._lock:
            self.base_dir = base_dir
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _memory_path(self) -> Path:
        if self.base_dir is None:
            raise RuntimeError("MemoryIndexer is not configured")
        return DurableMemoryLayout(self.base_dir / "durable_memory").index_path

    @property
    def _durable_memory_dir(self) -> Path:
        if self.base_dir is None:
            raise RuntimeError("MemoryIndexer is not configured")
        return self.base_dir / "durable_memory"

    @property
    def _storage_dir(self) -> Path:
        if self.base_dir is None:
            raise RuntimeError("MemoryIndexer is not configured")
        return self.base_dir / "storage" / "memory_index"

    @property
    def _meta_path(self) -> Path:
        return self._storage_dir / "meta.json"

    def _supports_embeddings(self) -> bool:
        return bool(get_settings().embedding_api_key)

    def _build_embed_model(self):
        return build_embedding_model(get_settings())

    def _vector_backend(self) -> str:
        return get_settings().vector_store_backend

    def _faiss_metric(self) -> str:
        return get_settings().faiss_metric

    def _get_faiss_store(self) -> FaissIndexStore:
        settings = get_settings()
        if self._faiss_store is None:
            self._faiss_store = FaissIndexStore(
                self._storage_dir,
                metric=settings.faiss_metric,
                index_type=settings.faiss_index_type,
                hnsw_m=settings.faiss_hnsw_m,
                hnsw_ef_construction=settings.faiss_hnsw_ef_construction,
                hnsw_ef_search=settings.faiss_hnsw_ef_search,
            )
        return self._faiss_store

    def _collect_source_files(self) -> list[Path]:
        files: list[Path] = []

        if self._memory_path.exists():
            files.append(self._memory_path)

        manager = MemoryManager(self._durable_memory_dir)
        files.extend(manager.list_note_paths())

        return sorted(files, key=lambda p: str(p).lower())

    def audit_sources(self) -> dict[str, Any]:
        if self.base_dir is None:
            return {}
        manager = MemoryManager(self._durable_memory_dir)
        store_audit = manager.ensure_index_consistent()
        return {
            "store": store_audit,
            "indexed_sources": [
                str(path.relative_to(self.base_dir)).replace(os.sep, "/")
                for path in self._collect_source_files()
            ],
        }

    def _file_digest(self) -> str:
        digest = hashlib.md5()
        for path in self._collect_source_files():
            stat = path.stat()
            digest.update(str(path).encode("utf-8", errors="ignore"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        return digest.hexdigest()

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    def _extract_json_text(self, raw_text: str) -> str:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text

        chunks: list[str] = []

        def _walk(value: Any, prefix: str = "") -> None:
            if isinstance(value, dict):
                for key, sub_value in value.items():
                    next_prefix = f"{prefix}.{key}" if prefix else str(key)
                    _walk(sub_value, next_prefix)
                return
            if isinstance(value, list):
                for idx, sub_value in enumerate(value):
                    next_prefix = f"{prefix}[{idx}]"
                    _walk(sub_value, next_prefix)
                return
            text = str(value).strip()
            if text:
                chunks.append(f"{prefix}: {text}" if prefix else text)

        _walk(payload)
        return "\n".join(chunks) if chunks else raw_text

    def _extract_csv_text(self, path: Path, max_rows: int = 60) -> str:
        rows: list[list[str]] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                for idx, row in enumerate(reader):
                    if idx >= max_rows:
                        break
                    rows.append([cell.strip() for cell in row])
        except UnicodeDecodeError:
            with path.open("r", encoding="gb18030", newline="") as handle:
                reader = csv.reader(handle)
                for idx, row in enumerate(reader):
                    if idx >= max_rows:
                        break
                    rows.append([cell.strip() for cell in row])
        except Exception:
            return self._read_text_file(path)

        if not rows:
            return ""

        header = rows[0]
        lines = ["CSV Preview:"]
        lines.append(" | ".join(header))
        lines.append(" | ".join(["---"] * len(header)))
        for row in rows[1:]:
            normalized = row + [""] * (len(header) - len(row))
            lines.append(" | ".join(normalized[: len(header)]))
        return "\n".join(lines)

    def _extract_pdf_text(self, path: Path) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return ""

        try:
            reader = PdfReader(str(path))
            page_texts: list[str] = []
            for page in reader.pages[:20]:
                text = (page.extract_text() or "").strip()
                if text:
                    page_texts.append(text)
            return "\n\n".join(page_texts)
        except Exception:
            return ""

    def _read_source_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".md", ".txt"}:
            return self._read_text_file(path)
        if suffix == ".json":
            return self._extract_json_text(self._read_text_file(path))
        if suffix == ".csv":
            return self._extract_csv_text(path)
        if suffix == ".pdf":
            return self._extract_pdf_text(path)
        return self._read_text_file(path)

    def _build_documents(self) -> list[Document]:
        if self.base_dir is None:
            return []

        paths = self._collect_source_files()
        if not paths:
            return []

        with ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="memory-indexer",
        ) as pool:
            docs = list(pool.map(self._build_document_for_path, paths))

        return [doc for doc in docs if doc is not None]

    def _read_meta(self) -> dict[str, Any]:
        with self._lock:
            if not self._meta_path.exists():
                return {}
            try:
                return json.loads(self._meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}

    def _write_meta(self, digest: str) -> None:
        with self._lock:
            self._meta_path.write_text(
                json.dumps({"digest": digest}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _build_document_for_path(self, path: Path) -> Document | None:
        if self.base_dir is None:
            return None

        text = self._read_source_text(path).strip()
        if not text:
            return None

        rel_source = str(path.relative_to(self.base_dir)).replace(os.sep, "/")
        if len(text) > 30_000:
            text = text[:30_000] + "\n...[truncated]"

        return Document(
            text=text,
            metadata={
                "source": rel_source,
                "kind": path.suffix.lower().lstrip("."),
            },
        )

    def rebuild_index(self) -> None:
        with self._lock:
            if self.base_dir is None:
                return

            MemoryManager(self._durable_memory_dir).ensure_index_consistent()

            digest = self._file_digest()
            self._write_meta(digest)

            if not self._supports_embeddings():
                self._index = None
                self._faiss_store = None
                return

            try:
                LlamaSettings.embed_model = self._build_embed_model()
                documents = self._build_documents()
                if not documents:
                    self._index = None
                    self._faiss_store = None
                    return
                settings = get_settings()
                splitter = SentenceSplitter(
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                )
                nodes = splitter.get_nodes_from_documents(documents)
                backend = self._vector_backend()
                self._cleanup_stale_index_files(backend)
                if backend == "faiss":
                    faiss_store = self._get_faiss_store()
                    if not faiss_store.is_available():
                        raise RuntimeError("FAISS backend requested but faiss is not installed")
                    self._index = None
                    faiss_store.build(nodes, self._build_embed_model())
                else:
                    self._index = VectorStoreIndex(nodes)
                    self._index.storage_context.persist(persist_dir=str(self._storage_dir))
            except Exception:
                self._index = None
                self._faiss_store = None

    def _load_index(self) -> None:
        with self._lock:
            if not self._supports_embeddings():
                self._index = None
                self._faiss_store = None
                return
            persisted_files = [
                path for path in self._storage_dir.iterdir() if path.name not in {".gitkeep", "meta.json"}
            ]
            if not persisted_files:
                self.rebuild_index()
                return
            try:
                if self._vector_backend() == "faiss":
                    self._index = None
                    self._get_faiss_store().load()
                else:
                    LlamaSettings.embed_model = self._build_embed_model()
                    storage_context = StorageContext.from_defaults(persist_dir=str(self._storage_dir))
                    self._index = load_index_from_storage(storage_context)
            except Exception:
                self._index = None
                self._faiss_store = None

    def _maybe_rebuild(self) -> None:
        with self._lock:
            if self.base_dir is None:
                return
            digest = self._file_digest()
            if digest != self._read_meta().get("digest"):
                self.rebuild_index()
                return
            if self._vector_backend() == "faiss":
                faiss_store = self._get_faiss_store()
                if self._supports_embeddings():
                    if not faiss_store.exists():
                        self._load_index()
                    elif not faiss_store.is_loaded():
                        faiss_store.load()
                return
            if self._index is None and self._supports_embeddings():
                self._load_index()

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            if self.base_dir is None:
                return []

            self._maybe_rebuild()
            if self._vector_backend() == "faiss":
                faiss_store = self._get_faiss_store()
                if not faiss_store.exists():
                    return []
                hits = faiss_store.search(query, top_k, self._build_embed_model())
                return [
                    {
                        "text": hit.text,
                        "score": float(hit.score),
                        "source": hit.source or "durable_memory/index/MEMORY.md",
                    }
                    for hit in hits
                ]
            if self._index is None:
                return []

            retriever = self._index.as_retriever(similarity_top_k=top_k)
            results = retriever.retrieve(query)
            payload: list[dict[str, Any]] = []
            for item in results:
                node = getattr(item, "node", item)
                text = getattr(node, "text", "") or getattr(node, "get_content", lambda: "")()
                payload.append(
                    {
                        "text": text,
                        "score": float(getattr(item, "score", 0.0) or 0.0),
                        "source": node.metadata.get("source", "durable_memory/index/MEMORY.md"),
                    }
                )
            return payload


memory_indexer = MemoryIndexer()
