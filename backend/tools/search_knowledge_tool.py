from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from RAG.registry import RAGIndexRegistry


class SearchKnowledgeInput(BaseModel):
    query: str = Field(..., description="Semantic search query")
    top_k: int = Field(default=3, ge=1, le=10, description="How many passages to return")


class SearchKnowledgeBaseTool(BaseTool):
    name: str = "search_knowledge"
    description: str = "Search local knowledge documents through the unified v2 retrieval backend."
    args_schema: Type[BaseModel] = SearchKnowledgeInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _registry: RAGIndexRegistry = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir
        self._registry = RAGIndexRegistry(root_dir)

    def _knowledge_index_ready(self) -> bool:
        status = self._registry.collection_status("knowledge")
        meta = dict(status.get("meta", {}) or {})
        return str(meta.get("status", "") or "").strip().lower() in {"ready", "empty"}

    def _run(
        self,
        query: str,
        top_k: int = 3,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        if not self._knowledge_index_ready():
            return "Knowledge index is not ready. Rebuild the knowledge collection before searching."
        hits = self._registry.retrieve_collection(
            "knowledge",
            query,
            top_k=max(int(top_k or 1), 1),
            query_mode="semantic_lookup",
        )
        if not hits:
            return "No relevant knowledge documents found."

        chunks: list[str] = []
        for index, hit in enumerate(hits[:top_k], start=1):
            modes = ",".join(hit.retrieval_modes) if hit.retrieval_modes else "unknown"
            chunks.append(
                (
                    f"[{index}] {hit.source} (score={float(hit.score or 0.0):.3f}, modes={modes})\n"
                    f"{hit.text[:1200]}"
                )
            )
        return "\n\n".join(chunks)[:5000]

    async def _arun(
        self,
        query: str,
        top_k: int = 3,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, top_k, None)
