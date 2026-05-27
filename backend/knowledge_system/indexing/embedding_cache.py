from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class CachedEmbeddingModel:
    """Persistent cache wrapper for expensive embedding calls."""

    def __init__(
        self,
        inner: Any,
        *,
        cache_path: Path,
        namespace: str,
    ) -> None:
        self.inner = inner
        self.cache_path = Path(cache_path)
        self.namespace = str(namespace or "default")
        self._lock = threading.RLock()
        self.last_batch_stats: dict[str, int] = {"requested": 0, "hits": 0, "misses": 0}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def get_query_embedding(self, query: str) -> list[float]:
        getter = getattr(self.inner, "get_query_embedding", None)
        if callable(getter):
            return list(getter(query))
        return self.get_text_embedding(query)

    def get_text_embedding(self, text: str) -> list[float]:
        return self.get_text_embedding_batch([text])[0]

    def get_text_embedding_batch(self, texts: list[str], show_progress: bool | None = None) -> list[list[float]]:
        _ = show_progress
        normalized = [self._normalize_text(text) for text in texts]
        keys = [self._cache_key(text) for text in normalized]
        cached = self._load_many(keys)
        missing_positions = [index for index, key in enumerate(keys) if key not in cached]
        self.last_batch_stats = {
            "requested": len(keys),
            "hits": len(keys) - len(missing_positions),
            "misses": len(missing_positions),
        }
        if missing_positions:
            missing_texts = [normalized[index] for index in missing_positions]
            vectors = self._embed_missing(missing_texts)
            rows = {keys[index]: vector for index, vector in zip(missing_positions, vectors, strict=False)}
            self._store_many(rows)
            cached.update(rows)
        return [list(cached.get(key, [])) for key in keys]

    def _embed_missing(self, texts: list[str]) -> list[list[float]]:
        batch = getattr(self.inner, "get_text_embedding_batch", None)
        if callable(batch):
            return [list(item) for item in batch(texts)]
        batch = getattr(self.inner, "_get_text_embeddings", None)
        if callable(batch):
            return [list(item) for item in batch(texts)]
        single = getattr(self.inner, "get_text_embedding", None)
        if callable(single):
            return [list(single(text)) for text in texts]
        single = getattr(self.inner, "_get_text_embedding", None)
        if callable(single):
            return [list(single(text)) for text in texts]
        raise TypeError("Embedding model does not expose a supported text embedding method")

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )

    def _load_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        found: dict[str, list[float]] = {}
        with self._lock, self._connect() as conn:
            for key in dict.fromkeys(keys):
                row = conn.execute(
                    "SELECT vector_json FROM embedding_cache WHERE namespace = ? AND cache_key = ?",
                    (self.namespace, key),
                ).fetchone()
                if row is None:
                    continue
                try:
                    found[key] = [float(item) for item in json.loads(str(row[0]))]
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        return found

    def _store_many(self, rows: dict[str, list[float]]) -> None:
        if not rows:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO embedding_cache(namespace, cache_key, vector_json)
                VALUES (?, ?, ?)
                """,
                [
                    (self.namespace, key, json.dumps([float(value) for value in vector], ensure_ascii=False))
                    for key, vector in rows.items()
                    if vector
                ],
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.cache_path))

    def _cache_key(self, text: str) -> str:
        model_name = str(getattr(self.inner, "model_name", "") or getattr(self.inner, "model", "") or "unknown")
        dimensions = str(getattr(self.inner, "dimensions", "") or "")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{model_name}:{dimensions}:{digest}"

    @staticmethod
    def _normalize_text(text: str) -> str:
        return str(text or "").replace("\n", " ").strip()


