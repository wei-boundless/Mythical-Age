from __future__ import annotations

from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import Field, PrivateAttr
from openai import AsyncOpenAI, OpenAI

from config import Settings, get_settings


class CompatibleOpenAIEmbedding(BaseEmbedding):
    """OpenAI-compatible embedding adapter for providers like Bailian.

    LlamaIndex's built-in OpenAIEmbedding validates model names against the
    official OpenAI enum, which breaks OpenAI-compatible providers that expose
    custom model ids such as Bailian's ``text-embedding-v3``.
    """

    model_name: str = Field(description="Embedding model name.")
    api_key: str = Field(description="API key.", exclude=True, repr=False)
    api_base: str = Field(description="OpenAI-compatible API base URL.")
    dimensions: int | None = Field(default=None, description="Optional embedding dimensions.")

    _client: OpenAI = PrivateAttr()
    _aclient: AsyncOpenAI = PrivateAttr()

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        api_base: str,
        dimensions: int | None = None,
        embed_batch_size: int = 10,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            api_base=api_base.rstrip("/"),
            dimensions=dimensions,
            embed_batch_size=embed_batch_size,
            **kwargs,
        )
        self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)
        self._aclient = AsyncOpenAI(api_key=self.api_key, base_url=self.api_base)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\n", " ").strip()

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = [self._normalize_text(text) for text in texts]
        embeddings: list[list[float]] = []
        for start in range(0, len(payload), self.embed_batch_size):
            batch = payload[start : start + self.embed_batch_size]
            response = self._client.embeddings.create(
                model=self.model_name,
                input=batch,
                dimensions=self.dimensions,
            )
            embeddings.extend([list(item.embedding) for item in response.data])
        return embeddings

    async def _acreate_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = [self._normalize_text(text) for text in texts]
        embeddings: list[list[float]] = []
        for start in range(0, len(payload), self.embed_batch_size):
            batch = payload[start : start + self.embed_batch_size]
            response = await self._aclient.embeddings.create(
                model=self.model_name,
                input=batch,
                dimensions=self.dimensions,
            )
            embeddings.extend([list(item.embedding) for item in response.data])
        return embeddings

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._create_embeddings([query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await self._acreate_embeddings([query]))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._create_embeddings([text])[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._acreate_embeddings([text]))[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._create_embeddings(texts)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self._acreate_embeddings(texts)


def build_embedding_model(settings: Settings | None = None) -> BaseEmbedding:
    settings = settings or get_settings()
    if not settings.embedding_api_key:
        raise ValueError("Missing embedding API key.")
    return CompatibleOpenAIEmbedding(
        model_name=settings.embedding_model,
        api_key=settings.embedding_api_key,
        api_base=settings.embedding_base_url,
        dimensions=settings.embedding_dimensions,
    )
