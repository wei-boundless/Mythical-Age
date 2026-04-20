from __future__ import annotations

from pathlib import Path
from typing import Any

from RAG.router import RAGQueryRouter
from retrieval.memory_index import memory_indexer


class RetrievalService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        memory_indexer.configure(base_dir)
        self.router = RAGQueryRouter(base_dir)

    def retrieve(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        return self.router.retrieve(query, top_k=top_k)

    def retrieve_memory(self, query: str, *, top_k: int = 3) -> list[dict[str, Any]]:
        return memory_indexer.retrieve(query, top_k=top_k)

    def rebuild_collection(self, name: str) -> None:
        try:
            self.router.registry.rebuild(name)
        except Exception:
            pass

    def rebuild_durable_memory(self) -> None:
        memory_indexer.rebuild_index()
        self.rebuild_collection("durable_memory")

    def rebuild_session_memory(self) -> None:
        self.rebuild_collection("session_memory")

    def rebuild_knowledge(self) -> None:
        self.rebuild_collection("knowledge")

    def rebuild_all(self) -> None:
        self.rebuild_durable_memory()
        self.rebuild_session_memory()
        self.rebuild_knowledge()

    def audit_memory_sources(self) -> dict[str, Any]:
        return memory_indexer.audit_sources()
