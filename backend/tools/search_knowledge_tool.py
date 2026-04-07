from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from llama_index.core import Document, Settings as LlamaSettings, StorageContext, VectorStoreIndex, load_index_from_storage
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from config import get_settings
from embedding_compat import build_embedding_model
from RAG.hybrid import BM25Index, build_searchable_text, required_bm25_term_matches


def _read_text_with_fallback(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding).strip()
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore").strip()


class SearchKnowledgeInput(BaseModel):
    query: str = Field(..., description="Semantic search query")
    top_k: int = Field(default=3, ge=1, le=10, description="How many passages to return")


class KnowledgeIndex:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.knowledge_dir = root_dir / "knowledge"
        self.storage_dir = root_dir / "storage" / "knowledge"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._index: VectorStoreIndex | None = None
        self._documents_cache: list[Document] | None = None
        self._bm25_index: BM25Index | None = None

    @property
    def _meta_path(self) -> Path:
        return self.storage_dir / "meta.json"

    def _supports_embeddings(self) -> bool:
        return bool(get_settings().embedding_api_key)

    def _embed_model(self):
        return build_embedding_model(get_settings())

    def _fingerprint(self) -> str:
        payload: list[str] = []
        for path in sorted(self.knowledge_dir.rglob("*")):
            if path.is_file():
                stat = path.stat()
                payload.append(f"{path.relative_to(self.root_dir)}:{stat.st_mtime_ns}:{stat.st_size}")
        return hashlib.md5("\n".join(payload).encode("utf-8")).hexdigest()

    def _read_meta(self) -> dict[str, Any]:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_meta(self, digest: str) -> None:
        self._meta_path.write_text(
            json.dumps({"digest": digest}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_documents(self) -> list[Document]:
        docs: list[Document] = []
        for path in sorted(self.knowledge_dir.rglob("*")):
            if not path.is_file():
                continue
            text = _read_text_with_fallback(path)
            if not text:
                continue
            docs.append(
                Document(
                    text=text,
                    metadata={"source": str(path.relative_to(self.root_dir)).replace("\\", "/")},
                )
            )
        self._documents_cache = docs
        self._bm25_index = None
        return docs

    def _ensure_documents(self) -> list[Document]:
        if self._documents_cache is None:
            self._documents_cache = self._load_documents()
        return self._documents_cache

    def _ensure_bm25_index(self) -> BM25Index | None:
        docs = self._ensure_documents()
        if not docs:
            self._bm25_index = None
            return None
        if self._bm25_index is None:
            self._bm25_index = BM25Index.from_texts(
                [
                    build_searchable_text(
                        doc.text,
                        source=str(doc.metadata.get("source", "knowledge")),
                        metadata=dict(doc.metadata),
                    )
                    for doc in docs
                ]
            )
        return self._bm25_index

    def rebuild(self) -> None:
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._write_meta(self._fingerprint())
        self._documents_cache = None
        self._bm25_index = None
        if not self._supports_embeddings():
            self._index = None
            return

        docs = self._load_documents()
        if not docs:
            self._index = None
            return

        try:
            LlamaSettings.embed_model = self._embed_model()
            self._index = VectorStoreIndex.from_documents(docs)
            self._index.storage_context.persist(persist_dir=str(self.storage_dir))
        except Exception:
            self._index = None

    def _load_index(self) -> None:
        if not self._supports_embeddings():
            self._index = None
            return
        persisted_files = [
            path for path in self.storage_dir.iterdir() if path.name not in {".gitkeep", "meta.json"}
        ]
        if not persisted_files:
            self.rebuild()
            return
        try:
            LlamaSettings.embed_model = self._embed_model()
            storage_context = StorageContext.from_defaults(persist_dir=str(self.storage_dir))
            self._index = load_index_from_storage(storage_context)
        except Exception:
            self._index = None

    def _keyword_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        docs = self._ensure_documents()
        bm25_index = self._ensure_bm25_index()
        if not docs or bm25_index is None:
            return []

        matches = bm25_index.search(query, top_k=top_k)
        best_score = max((match.score for match in matches), default=0.0)
        min_term_matches = required_bm25_term_matches(query)

        rows: list[dict[str, Any]] = []
        for match in matches:
            if match.matched_term_count < min_term_matches:
                continue
            doc = docs[match.index]
            rows.append(
                {
                    "text": doc.text[:1200],
                    "score": float(match.score / best_score) if best_score > 0 else 0.0,
                    "bm25_score": float(match.score),
                    "source": doc.metadata.get("source", "knowledge"),
                }
            )
            if len(rows) >= top_k:
                break
        return rows

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        fingerprint = self._fingerprint()
        if fingerprint != self._read_meta().get("digest"):
            self.rebuild()
        elif self._index is None and self._supports_embeddings():
            self._load_index()

        combined: dict[str, dict[str, Any]] = {}

        if self._index is not None:
            try:
                retriever = self._index.as_retriever(similarity_top_k=max(top_k, 5))
                for item in retriever.retrieve(query):
                    node = getattr(item, "node", item)
                    text = getattr(node, "text", "") or getattr(node, "get_content", lambda: "")()
                    source = node.metadata.get("source", "knowledge")
                    combined[source] = {
                        "text": text[:1200],
                        "score": float(getattr(item, "score", 0.0) or 0.0),
                        "source": source,
                    }
            except Exception:
                self._index = None

        for item in self._keyword_search(query, top_k=max(top_k, 5)):
            source = item["source"]
            if source in combined:
                combined[source]["score"] += item["score"]
            else:
                combined[source] = item

        results = sorted(combined.values(), key=lambda item: item["score"], reverse=True)
        return results[:top_k]


class SearchKnowledgeBaseTool(BaseTool):
    name: str = "search_knowledge"
    description: str = "Search local knowledge documents with semantic retrieval and keyword fallback."
    args_schema: Type[BaseModel] = SearchKnowledgeInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _index: KnowledgeIndex = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._index = KnowledgeIndex(root_dir)

    def _run(
        self,
        query: str,
        top_k: int = 3,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        results = self._index.search(query, top_k=top_k)
        if not results:
            return "No relevant knowledge documents found."
        chunks = []
        for idx, item in enumerate(results, start=1):
            chunks.append(
                f"[{idx}] {item['source']} (score={item['score']:.3f})\n{item['text']}"
            )
        return "\n\n".join(chunks)[:5000]

    async def _arun(
        self,
        query: str,
        top_k: int = 3,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, top_k, None)
