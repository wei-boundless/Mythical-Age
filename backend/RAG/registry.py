from __future__ import annotations

import hashlib
import json
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

from .collections import CollectionConfig, build_default_collections
from .faiss_store import FaissIndexStore
from .hybrid import (
    BM25Index,
    attach_reason_list,
    build_searchable_text,
    merge_scores,
    normalize_dense_score,
    normalize_keyword_score,
    reciprocal_rank_fusion,
    required_bm25_term_matches,
)
from .models import RetrievalHit
from .parser_adapter import MultimodalParserAdapter


class CollectionIndexer:
    def __init__(self, base_dir: Path, config: CollectionConfig, adapter: MultimodalParserAdapter) -> None:
        self.base_dir = base_dir
        self.config = config
        self.adapter = adapter
        self._index: VectorStoreIndex | None = None
        self._faiss_store: FaissIndexStore | None = None
        self._documents_cache: list[Document] | None = None
        self._bm25_index: BM25Index | None = None
        self._lock = threading.RLock()
        self.config.storage_dir.mkdir(parents=True, exist_ok=True)

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
            path = self.config.storage_dir / name
            if path.exists():
                path.unlink()

    def _normalized_allowed_roots(self) -> tuple[Path, ...]:
        roots = self.config.allowed_roots or self.config.source_dirs
        return tuple(root.resolve() for root in roots)

    def _is_within_allowed_roots(self, path: Path) -> bool:
        resolved = path.resolve()
        for root in self._normalized_allowed_roots():
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    @property
    def _meta_path(self) -> Path:
        return self.config.storage_dir / "meta.json"

    def _supports_embeddings(self) -> bool:
        return bool(get_settings().embedding_api_key)

    def _build_embed_model(self):
        return build_embedding_model(get_settings())

    def _vector_backend(self) -> str:
        return get_settings().vector_store_backend

    def _faiss_metric(self) -> str:
        return get_settings().faiss_metric

    def _faiss_backend(self) -> FaissIndexStore:
        settings = get_settings()
        if self._faiss_store is None:
            self._faiss_store = FaissIndexStore(
                self.config.storage_dir,
                metric=settings.faiss_metric,
                index_type=settings.faiss_index_type,
                hnsw_m=settings.faiss_hnsw_m,
                hnsw_ef_construction=settings.faiss_hnsw_ef_construction,
                hnsw_ef_search=settings.faiss_hnsw_ef_search,
            )
        return self._faiss_store

    def _collect_source_files(self) -> list[Path]:
        files: list[Path] = []
        allowed_exts = {ext.lower() for ext in self.config.file_extensions}
        for source_dir in self.config.source_dirs:
            if not source_dir.exists():
                continue
            resolved_source = source_dir.resolve()
            if not self._is_within_allowed_roots(resolved_source):
                continue
            for path in resolved_source.rglob("*"):
                if not self.adapter.is_supported_file(path):
                    continue
                if allowed_exts and path.suffix.lower() not in allowed_exts:
                    continue
                if not self._is_within_allowed_roots(path):
                    continue
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

    def _build_documents(self) -> list[Document]:
        documents: list[Document] = []
        for path in self._collect_source_files():
            try:
                chunks = self.adapter.parse_file(path)
            except Exception:
                continue
            for chunk in chunks:
                if not chunk.text.strip():
                    continue
                documents.append(
                    Document(
                        text=chunk.text,
                        metadata={
                            "source": chunk.source,
                            "modality": chunk.modality,
                            "page": chunk.page,
                            "section": chunk.section or "",
                            "collection": self.config.name,
                            **chunk.metadata,
                        },
                    )
                )
        self._documents_cache = documents
        self._bm25_index = None
        return documents

    def _ensure_documents_cache(self) -> list[Document]:
        if self._documents_cache is None:
            self._documents_cache = self._build_documents()
        return self._documents_cache

    def _ensure_bm25_index(self) -> BM25Index | None:
        documents = self._ensure_documents_cache()
        if not documents:
            self._bm25_index = None
            return None
        if self._bm25_index is None:
            corpus = [
                build_searchable_text(
                    doc.text,
                    source=str(doc.metadata.get("source", self.config.name)),
                    metadata=dict(doc.metadata),
                )
                for doc in documents
            ]
            self._bm25_index = BM25Index.from_texts(corpus)
        return self._bm25_index

    def rebuild(self) -> dict[str, Any]:
        with self._lock:
            digest = self._file_digest()
            if not self._supports_embeddings():
                self._index = None
                payload = {"digest": digest, "status": "embedding_unavailable"}
                self._write_meta(payload)
                return payload

            try:
                LlamaSettings.embed_model = self._build_embed_model()
                documents = self._build_documents()
                if not documents:
                    self._index = None
                    self._faiss_store = None
                    payload = {"digest": digest, "status": "empty"}
                    self._write_meta(payload)
                    return payload

                settings = get_settings()
                splitter = SentenceSplitter(
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                )
                nodes = splitter.get_nodes_from_documents(documents)
                backend = self._vector_backend()
                self._cleanup_stale_index_files(backend)
                if backend == "faiss":
                    faiss_backend = self._faiss_backend()
                    if not faiss_backend.is_available():
                        raise RuntimeError("FAISS backend requested but faiss is not installed")
                    self._index = None
                    indexed_count = faiss_backend.build(nodes, self._build_embed_model())
                else:
                    self._index = VectorStoreIndex(nodes)
                    self._index.storage_context.persist(persist_dir=str(self.config.storage_dir))
                    indexed_count = len(nodes)
                payload = {
                    "digest": digest,
                    "status": "ready",
                    "documents": len(documents),
                    "nodes": indexed_count,
                    "collection": self.config.name,
                    "vector_backend": backend,
                }
                self._write_meta(payload)
                return payload
            except Exception as exc:
                self._index = None
                self._faiss_store = None
                payload = {
                    "digest": digest,
                    "status": "error",
                    "error": str(exc),
                    "vector_backend": self._vector_backend(),
                }
                self._write_meta(payload)
                return payload

    def _load(self) -> None:
        if not self._supports_embeddings():
            self._index = None
            self._faiss_store = None
            return
        persisted_files = [
            path for path in self.config.storage_dir.iterdir() if path.name not in {".gitkeep", "meta.json"}
        ]
        if not persisted_files:
            self.rebuild()
            return
        try:
            if self._vector_backend() == "faiss":
                self._index = None
                faiss_backend = self._faiss_backend()
                faiss_backend.load()
            else:
                LlamaSettings.embed_model = self._build_embed_model()
                storage_context = StorageContext.from_defaults(persist_dir=str(self.config.storage_dir))
                self._index = load_index_from_storage(storage_context)
        except Exception:
            self._index = None
            self._faiss_store = None

    def _maybe_reload(self) -> None:
        digest = self._file_digest()
        if digest != self._read_meta().get("digest"):
            self.rebuild()
            return
        backend = self._vector_backend()
        if backend == "faiss":
            if self._supports_embeddings():
                if self._faiss_store is None or not self._faiss_store.exists():
                    self._load()
                elif not self._faiss_store.is_loaded():
                    self._faiss_store.load()
            return
        if self._index is None and self._supports_embeddings():
            self._load()

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalHit]:
        with self._lock:
            self._maybe_reload()
            if self._vector_backend() == "faiss":
                faiss_backend = self._faiss_backend()
                if not faiss_backend.exists():
                    return []
                return faiss_backend.search(query, top_k, self._build_embed_model())
            if self._index is None:
                return []
            retriever = self._index.as_retriever(similarity_top_k=top_k)
            results = retriever.retrieve(query)
            hits: list[RetrievalHit] = []
            for item in results:
                node = getattr(item, "node", item)
                text = getattr(node, "text", "") or getattr(node, "get_content", lambda: "")()
                hits.append(
                    RetrievalHit(
                        text=text,
                        source=node.metadata.get("source", self.config.name),
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
            return hits

    def retrieve_hybrid(self, query: str, top_k: int = 5, dense_top_k: int | None = None) -> list[RetrievalHit]:
        with self._lock:
            self._maybe_reload()
            dense_hits = self.retrieve(query, top_k=dense_top_k or max(top_k, 8))
            keyword_hits = self._keyword_search(query, top_k=max(top_k, 8))

            fused: dict[str, dict[str, Any]] = {}
            for rank, hit in enumerate(dense_hits, start=1):
                key = f"{hit.source}::{hit.page}::{hit.text[:160]}"
                fused[key] = {
                    "hit": hit,
                    "score": merge_scores(
                        reciprocal_rank_fusion(rank, weight=self.config.weight),
                        normalize_dense_score(hit.score) * self.config.weight,
                    ),
                    "reasons": ["dense"],
                }

            best_keyword_score = max(float(row["keyword_score"]) for row in keyword_hits) if keyword_hits else 0.0
            for rank, item in enumerate(keyword_hits, start=1):
                key = f"{item['source']}::{item.get('page')}::{item['text'][:160]}"
                entry = fused.get(key)
                lexical = merge_scores(
                    reciprocal_rank_fusion(rank, weight=self.config.weight),
                    normalize_keyword_score(
                        float(item["keyword_score"]),
                        ceiling=best_keyword_score,
                    )
                    * self.config.weight,
                )
                if entry is None:
                    hit = RetrievalHit(
                        text=str(item["text"]),
                        source=str(item["source"]),
                        modality=str(item.get("modality", "text")),
                        score=float(item["keyword_score"]),
                        page=item.get("page"),
                        metadata=dict(item.get("metadata", {})),
                    )
                    fused[key] = {
                        "hit": hit,
                        "score": lexical,
                        "reasons": list(item.get("keyword_reasons", [])) + ["keyword"],
                    }
                else:
                    entry["score"] += lexical
                    entry["reasons"] = list(dict.fromkeys(entry["reasons"] + list(item.get("keyword_reasons", [])) + ["keyword"]))

            ranked = sorted(fused.values(), key=lambda row: float(row["score"]), reverse=True)
            results: list[RetrievalHit] = []
            for row in ranked[:top_k]:
                hit = row["hit"]
                metadata = dict(hit.metadata)
                attach_reason_list(metadata, row["reasons"])
                results.append(
                    RetrievalHit(
                        text=hit.text,
                        source=hit.source,
                        modality=hit.modality,
                        score=float(row["score"]),
                        page=hit.page,
                        metadata=metadata,
                    )
                )
            return results

    def _keyword_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        documents = self._ensure_documents_cache()
        bm25_index = self._ensure_bm25_index()
        if not documents or bm25_index is None:
            return []

        scored: list[dict[str, Any]] = []
        min_term_matches = required_bm25_term_matches(query)
        for match in bm25_index.search(query, top_k=top_k * 2):
            if match.matched_term_count < min_term_matches:
                continue
            doc = documents[match.index]
            metadata = dict(doc.metadata)
            scored.append(
                {
                    "text": doc.text,
                    "source": str(metadata.get("source", self.config.name)),
                    "modality": str(metadata.get("modality", "text")),
                    "page": metadata.get("page"),
                    "metadata": metadata,
                    "keyword_score": float(match.score),
                    "keyword_reasons": [
                        "bm25",
                        f"matched_terms:{len(match.matched_terms)}",
                        *[f"term:{term}" for term in match.matched_terms[:3]],
                    ],
                }
            )
            if len(scored) >= top_k:
                break
        return scored

    def status(self) -> dict[str, Any]:
        return {
            "collection": self.config.name,
            "source_dirs": [str(item) for item in self.config.source_dirs],
            "allowed_roots": [str(item) for item in (self.config.allowed_roots or self.config.source_dirs)],
            "storage_dir": str(self.config.storage_dir),
            "weight": self.config.weight,
            "allow_chat_queries": self.config.allow_chat_queries,
            "vector_backend": self._vector_backend(),
            "faiss_metric": self._faiss_metric(),
            "faiss_index_type": get_settings().faiss_index_type,
            "meta": self._read_meta(),
        }


class RAGIndexRegistry:
    def __init__(self, base_dir: Path, *, ocr_language: str = "eng") -> None:
        self.base_dir = base_dir
        self.adapter = MultimodalParserAdapter(repo_root=base_dir.parent, ocr_language=ocr_language)
        self.collections = build_default_collections(base_dir)
        self.indexers = {
            name: CollectionIndexer(base_dir, config, self.adapter)
            for name, config in self.collections.items()
        }

    def list_collections(self) -> list[dict[str, Any]]:
        return [self.indexers[name].status() for name in sorted(self.indexers)]

    def get(self, name: str) -> CollectionIndexer:
        if name not in self.indexers:
            raise KeyError(f"Unknown collection: {name}")
        return self.indexers[name]

    def rebuild(self, name: str) -> dict[str, Any]:
        return self.get(name).rebuild()

    def rebuild_all(self) -> dict[str, dict[str, Any]]:
        return {name: indexer.rebuild() for name, indexer in self.indexers.items()}
