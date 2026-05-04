from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from RAG.registry import RAGIndexRegistry


class IndexMultimodalFileInput(BaseModel):
    path: str = Field(
        ...,
        description="Relative path inside the backend project for the file that should be added into backend/knowledge",
    )
    rename_on_conflict: bool = Field(
        default=True,
        description="Whether to auto-rename the copied file if another file with the same name already exists in knowledge",
    )


class IndexMultimodalFileTool(BaseTool):
    name: str = "index_multimodal_file"
    description: str = (
        "Copy a local multimodal file into backend/knowledge and rebuild the standalone multimodal RAG index. "
        "Use this when the user wants a file added into long-term retrieval."
    )
    args_schema: Type[BaseModel] = IndexMultimodalFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()
    _knowledge_dir: Path = PrivateAttr()
    _registry: RAGIndexRegistry = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()
        self._knowledge_dir = self._root_dir / "knowledge"
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._registry = RAGIndexRegistry(self._root_dir)

    def _resolve_path(self, path: str) -> Path:
        candidate = (self._root_dir / path).resolve()
        if self._root_dir not in candidate.parents and candidate != self._root_dir:
            raise ValueError("Path traversal detected.")
        return candidate

    def _target_path(self, source: Path, rename_on_conflict: bool) -> Path:
        target = (self._knowledge_dir / source.name).resolve()
        if target == source:
            return target
        if not target.exists() or not rename_on_conflict:
            return target

        digest = hashlib.md5(str(source).encode("utf-8", errors="ignore")).hexdigest()[:8]
        return (self._knowledge_dir / f"{source.stem}_{digest}{source.suffix}").resolve()

    def _run(
        self,
        path: str,
        rename_on_conflict: bool = True,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            source = self._resolve_path(path)
        except ValueError as exc:
            return f"Index failed: {exc}"

        if not source.exists():
            return "Index failed: file does not exist."
        if source.is_dir():
            return "Index failed: path is a directory."

        target = self._target_path(source, rename_on_conflict)
        if source != target:
            shutil.copy2(source, target)

        rebuild_meta = self._registry.rebuild("knowledge")
        collection_status = self._registry.get("knowledge").status()

        relative_target = str(target.relative_to(self._root_dir)).replace("\\", "/")
        return (
            f"Indexed file into multimodal RAG.\n"
            f"Source: {path}\n"
            f"Stored as: {relative_target}\n"
            f"Knowledge dir: {self._knowledge_dir}\n"
            f"Vector store dir: {collection_status.get('storage_dir')}\n"
            f"Collection: knowledge\n"
            f"Rebuild status: {rebuild_meta.get('status')}\n"
            f"Rebuild meta: {rebuild_meta}"
        )

    async def _arun(
        self,
        path: str,
        rename_on_conflict: bool = True,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, rename_on_conflict, None)
