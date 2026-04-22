from __future__ import annotations

from typing import Any

import httpx

from config import Settings, get_settings


class CompatibleOpenAIEmbedding:
    """Lightweight OpenAI-compatible embedding client.

    The retrieval stack only needs a small duck-typed surface:
    - get_query_embedding
    - get_text_embedding
    - get_text_embedding_batch

    Avoid inheriting from llama-index embedding classes here because importing
    those classes pulls in a large transitive dependency graph and stalls
    indexing before any real embedding work starts.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        api_base: str,
        dimensions: int | None = None,
        embed_batch_size: int = 64,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.model_name = str(model_name)
        self.api_key = str(api_key)
        self.api_base = str(api_base).rstrip("/")
        self.dimensions = dimensions
        self.embed_batch_size = max(int(embed_batch_size or 1), 1)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(
            base_url=self.api_base,
            headers=headers,
            timeout=timeout_seconds,
        )
        self._aclient = httpx.AsyncClient(
            base_url=self.api_base,
            headers=headers,
            timeout=timeout_seconds,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\n", " ").strip()

    def _request_payload(self, batch: list[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": batch,
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        return payload

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = [self._normalize_text(text) for text in texts]
        embeddings: list[list[float]] = []
        for start in range(0, len(payload), self.embed_batch_size):
            batch = payload[start : start + self.embed_batch_size]
            response = self._client.post("/embeddings", json=self._request_payload(batch))
            response.raise_for_status()
            data = response.json().get("data", []) or []
            embeddings.extend([list(item.get("embedding", []) or []) for item in data])
        return embeddings

    async def _acreate_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = [self._normalize_text(text) for text in texts]
        embeddings: list[list[float]] = []
        for start in range(0, len(payload), self.embed_batch_size):
            batch = payload[start : start + self.embed_batch_size]
            response = await self._aclient.post("/embeddings", json=self._request_payload(batch))
            response.raise_for_status()
            data = response.json().get("data", []) or []
            embeddings.extend([list(item.get("embedding", []) or []) for item in data])
        return embeddings

    def get_query_embedding(self, query: str) -> list[float]:
        return self._create_embeddings([query])[0]

    async def aget_query_embedding(self, query: str) -> list[float]:
        return (await self._acreate_embeddings([query]))[0]

    def get_text_embedding(self, text: str) -> list[float]:
        return self._create_embeddings([text])[0]

    async def aget_text_embedding(self, text: str) -> list[float]:
        return (await self._acreate_embeddings([text]))[0]

    def get_text_embedding_batch(self, texts: list[str], show_progress: bool | None = None) -> list[list[float]]:
        _ = show_progress
        return self._create_embeddings(texts)

    async def aget_text_embedding_batch(
        self,
        texts: list[str],
        show_progress: bool | None = None,
    ) -> list[list[float]]:
        _ = show_progress
        return await self._acreate_embeddings(texts)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self.get_query_embedding(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self.aget_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self.get_text_embedding(text)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return await self.aget_text_embedding(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self.get_text_embedding_batch(texts)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self.aget_text_embedding_batch(texts)


def build_embedding_model(settings: Settings | None = None) -> CompatibleOpenAIEmbedding:
    settings = settings or get_settings()
    if not settings.embedding_api_key:
        raise ValueError("Missing embedding API key.")
    return CompatibleOpenAIEmbedding(
        model_name=settings.embedding_model,
        api_key=settings.embedding_api_key,
        api_base=settings.embedding_base_url,
        dimensions=settings.embedding_dimensions,
        embed_batch_size=64,
    )
