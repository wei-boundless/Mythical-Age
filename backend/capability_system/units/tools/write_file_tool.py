from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class WriteFileInput(BaseModel):
    path: str = Field(..., description="Relative path inside the project root")
    content: str = Field(..., description="Complete file content to write")


class EditFileInput(BaseModel):
    path: str = Field(..., description="Relative path inside the project root")
    old_text: str = Field(..., description="Exact text to replace")
    new_text: str = Field(..., description="Replacement text")


class _WorkspacePathMixin:
    _root_dir: Path = PrivateAttr()

    def _workspace_root(self) -> Path:
        if self._root_dir.name == "backend" and self._root_dir.parent.exists():
            return self._root_dir.parent.resolve()
        return self._root_dir

    def _resolve_path(self, path: str) -> Path:
        normalized = str(path or "").strip()
        if not normalized:
            raise ValueError("Path is required.")
        workspace_root = self._workspace_root()
        candidate = (workspace_root / normalized).resolve()
        if workspace_root not in candidate.parents and candidate != workspace_root:
            raise ValueError("Path traversal detected.")
        return candidate

    def _display_path(self, path: Path) -> str:
        workspace_root = self._workspace_root()
        try:
            return path.resolve().relative_to(workspace_root).as_posix()
        except ValueError:
            return str(path.resolve())


class WriteFileTool(_WorkspacePathMixin, BaseTool):
    name: str = "write_file"
    description: str = "Create or overwrite a local workspace file after runtime authorization."
    args_schema: Type[BaseModel] = WriteFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()

    def _run(
        self,
        path: str,
        content: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._resolve_path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(str(content or ""), encoding="utf-8")
        except Exception as exc:
            return f"Write failed: {exc}"
        return f"Write succeeded: {self._display_path(file_path)}"

    async def _arun(
        self,
        path: str,
        content: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, content, None)


class EditFileTool(_WorkspacePathMixin, BaseTool):
    name: str = "edit_file"
    description: str = "Replace exact text in a local workspace file after runtime authorization."
    args_schema: Type[BaseModel] = EditFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()

    def _run(
        self,
        path: str,
        old_text: str,
        new_text: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                return "Edit failed: file does not exist."
            if file_path.is_dir():
                return "Edit failed: path is a directory."
            content = file_path.read_text(encoding="utf-8")
            target = str(old_text or "")
            if not target:
                return "Edit failed: old_text is required."
            if target not in content:
                return "Edit failed: old_text not found."
            file_path.write_text(content.replace(target, str(new_text or ""), 1), encoding="utf-8")
        except Exception as exc:
            return f"Edit failed: {exc}"
        return f"Edit succeeded: {self._display_path(file_path)}"

    async def _arun(
        self,
        path: str,
        old_text: str,
        new_text: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, old_text, new_text, None)
