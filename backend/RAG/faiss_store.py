from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from llama_index.core.base.embeddings.base import BaseEmbedding

from .models import RetrievalHit

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional at runtime
    faiss = None


def _normalize_metric(metric: str) -> str:
    normalized = (metric or "cosine").strip().lower()
    if normalized in {"cos", "cosine"}:
        return "cosine"
    if normalized in {"ip", "inner_product", "dot"}:
        return "inner_product"
    if normalized in {"l2", "euclidean"}:
        return "l2"
    return "cosine"


def _make_json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _make_json_safe(sub_value) for key, sub_value in value.items()}
    return str(value)


def _node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    getter = getattr(node, "get_content", None)
    if callable(getter):
        try:
            return str(getter()).strip()
        except Exception:
            return ""
    return ""


class FaissIndexStore:
    def __init__(
        self,
        storage_dir: Path,
        *,
        metric: str = "cosine",
        index_type: str = "flat",
        hnsw_m: int = 32,
        hnsw_ef_construction: int = 40,
        hnsw_ef_search: int = 64,
    ) -> None:
        self.storage_dir = storage_dir
        self.metric = _normalize_metric(metric)
        self.index_type = self._normalize_index_type(index_type)
        self.hnsw_m = max(4, int(hnsw_m))
        self.hnsw_ef_construction = max(8, int(hnsw_ef_construction))
        self.hnsw_ef_search = max(8, int(hnsw_ef_search))
        self._index = None
        self._records: list[dict[str, Any]] = []

    @property
    def index_path(self) -> Path:
        return self.storage_dir / "faiss.index"

    @property
    def records_path(self) -> Path:
        return self.storage_dir / "faiss_records.json"

    def is_available(self) -> bool:
        return faiss is not None

    def exists(self) -> bool:
        return self.index_path.exists() and self.records_path.exists()

    def is_loaded(self) -> bool:
        return self._index is not None and bool(self._records)

    @staticmethod
    def _normalize_index_type(index_type: str) -> str:
        normalized = (index_type or "flat").strip().lower()
        if normalized in {"flat", "hnsw"}:
            return normalized
        return "flat"

    def _build_index(self, dimension: int):
        if faiss is None:
            raise RuntimeError("FAISS is not installed")
        if self.index_type == "hnsw":
            if self.metric in {"cosine", "inner_product"}:
                index = faiss.IndexHNSWFlat(dimension, self.hnsw_m, faiss.METRIC_INNER_PRODUCT)
            else:
                index = faiss.IndexHNSWFlat(dimension, self.hnsw_m, faiss.METRIC_L2)
            index.hnsw.efConstruction = self.hnsw_ef_construction
            index.hnsw.efSearch = self.hnsw_ef_search
            return index
        if self.metric in {"cosine", "inner_product"}:
            return faiss.IndexFlatIP(dimension)
        return faiss.IndexFlatL2(dimension)

    def _configure_search_params(self) -> None:
        if faiss is None or self._index is None:
            return
        if self.index_type == "hnsw" and hasattr(self._index, "hnsw"):
            self._index.hnsw.efSearch = self.hnsw_ef_search

    def _prepare_vectors(self, vectors: list[list[float]]) -> np.ndarray:
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2:
            raise ValueError("FAISS vectors must be a 2D float32 matrix")
        if self.metric == "cosine":
            faiss.normalize_L2(matrix)
        return matrix

    def build(self, nodes: list[Any], embed_model: BaseEmbedding) -> int:
        if faiss is None:
            raise RuntimeError("FAISS is not installed")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        records: list[dict[str, Any]] = []
        texts: list[str] = []
        for node in nodes:
            text = _node_text(node)
            if not text:
                continue
            metadata = _make_json_safe(dict(getattr(node, "metadata", {}) or {}))
            records.append({"text": text, "metadata": metadata})
            texts.append(text)

        if not texts:
            self._index = None
            self._records = []
            return 0

        vectors = embed_model.get_text_embedding_batch(texts, show_progress=False)
        matrix = self._prepare_vectors(vectors)
        index = self._build_index(matrix.shape[1])
        index.add(matrix)

        index_bytes = faiss.serialize_index(index)
        self.index_path.write_bytes(bytes(index_bytes))
        self.records_path.write_text(
            json.dumps(
                {
                    "metric": self.metric,
                    "index_type": self.index_type,
                    "hnsw_m": self.hnsw_m,
                    "hnsw_ef_construction": self.hnsw_ef_construction,
                    "hnsw_ef_search": self.hnsw_ef_search,
                    "dimension": int(matrix.shape[1]),
                    "records": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._index = index
        self._configure_search_params()
        self._records = records
        return len(records)

    def load(self) -> None:
        if faiss is None:
            raise RuntimeError("FAISS is not installed")
        if not self.exists():
            raise FileNotFoundError("FAISS artifacts are missing")

        payload = json.loads(self.records_path.read_text(encoding="utf-8"))
        self.metric = _normalize_metric(str(payload.get("metric", self.metric)))
        self.index_type = self._normalize_index_type(str(payload.get("index_type", self.index_type)))
        self.hnsw_m = max(4, int(payload.get("hnsw_m", self.hnsw_m)))
        self.hnsw_ef_construction = max(8, int(payload.get("hnsw_ef_construction", self.hnsw_ef_construction)))
        self.hnsw_ef_search = max(8, int(payload.get("hnsw_ef_search", self.hnsw_ef_search)))
        self._records = list(payload.get("records", []))
        index_buffer = np.frombuffer(self.index_path.read_bytes(), dtype="uint8")
        self._index = faiss.deserialize_index(index_buffer)
        self._configure_search_params()

    def search(self, query: str, top_k: int, embed_model: BaseEmbedding) -> list[RetrievalHit]:
        if faiss is None:
            return []
        if not self.is_loaded() and self.exists():
            self.load()
        if self._index is None or not self._records or top_k <= 0:
            return []

        query_vector = np.asarray([embed_model.get_query_embedding(query)], dtype="float32")
        if self.metric == "cosine":
            faiss.normalize_L2(query_vector)

        limit = min(top_k, len(self._records))
        scores, indices = self._index.search(query_vector, limit)
        hits: list[RetrievalHit] = []
        for score, row_id in zip(scores[0], indices[0], strict=False):
            if row_id < 0 or row_id >= len(self._records):
                continue
            record = self._records[int(row_id)]
            metadata = dict(record.get("metadata", {}))
            hits.append(
                RetrievalHit(
                    text=str(record.get("text", "")),
                    source=str(metadata.get("source", "")),
                    modality=str(metadata.get("modality", "text")),
                    score=float(score),
                    page=metadata.get("page"),
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key not in {"source", "modality", "page"}
                    },
                )
            )
        return hits
