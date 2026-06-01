from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import WorkspaceFileService


class _WorkspacePathMixin:
    _files: WorkspaceFileService

    def _resolve_path(self, path: str = "") -> Path:
        return self._files.resolve(path)

    def _relative_path(self, path: Path) -> str:
        return self._files.relative_path(path)


class ListDirInput(BaseModel):
    path: str = Field(default=".", description="Directory path relative to the project root")
    max_entries: int = Field(default=80, ge=1, le=300, description="Maximum directory entries to return")


class ListDirTool(_WorkspacePathMixin, BaseTool):
    name: str = "list_dir"
    description: str = "List entries in a known workspace directory. Use this when the directory path is known."
    args_schema: Type[BaseModel] = ListDirInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str = ".", max_entries: int = 80, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            entries = self._files.list_dir(path)
        except ValueError as exc:
            return f"List failed: {exc}"
        except FileNotFoundError:
            return "List failed: directory does not exist."
        except NotADirectoryError:
            return "List failed: path is not a directory."
        lines = []
        for item in entries[: max(1, min(int(max_entries or 80), 300))]:
            kind = "dir" if item.is_dir() else "file"
            size = "" if item.is_dir() else f" {item.stat().st_size} bytes"
            lines.append(f"{kind}\t{self._relative_path(item)}{size}")
        if len(entries) > len(lines):
            lines.append(f"... {len(entries) - len(lines)} more entries")
        return "\n".join(lines) or "Directory is empty."

    async def _arun(self, path: str = ".", max_entries: int = 80, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, path, max_entries, None)


class StatPathInput(BaseModel):
    path: str = Field(..., description="Path relative to the project root")


class StatPathTool(_WorkspacePathMixin, BaseTool):
    name: str = "stat_path"
    description: str = "Return metadata for a known workspace path without reading file contents."
    args_schema: Type[BaseModel] = StatPathInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            target = self._resolve_path(path)
        except ValueError as exc:
            return f"Stat failed: {exc}"
        if not target.exists():
            return "exists: false"
        stat = target.stat()
        kind = "directory" if target.is_dir() else "file"
        return "\n".join(
            [
                "exists: true",
                f"type: {kind}",
                f"path: {self._relative_path(target)}",
                f"size_bytes: {stat.st_size}",
                f"suffix: {target.suffix.lower()}",
            ]
        )

    async def _arun(self, path: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, path, None)


class PathExistsInput(BaseModel):
    path: str = Field(..., description="Path relative to the project root")


class PathExistsTool(_WorkspacePathMixin, BaseTool):
    name: str = "path_exists"
    description: str = "Check whether a known workspace path exists."
    args_schema: Type[BaseModel] = PathExistsInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            target = self._resolve_path(path)
        except ValueError as exc:
            return f"Exists failed: {exc}"
        return "true" if target.exists() else "false"

    async def _arun(self, path: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, path, None)


class GlobPathsInput(BaseModel):
    pattern: str = Field(..., description="Glob pattern relative to the project root, such as docs/**/*.md")
    max_results: int = Field(default=80, ge=1, le=300, description="Maximum matched paths to return")


class GlobPathsTool(_WorkspacePathMixin, BaseTool):
    name: str = "glob_paths"
    description: str = "Find workspace paths by an explicit glob pattern. Use for path discovery, not content search."
    args_schema: Type[BaseModel] = GlobPathsInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, pattern: str, max_results: int = 80, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            unique = self._files.glob_paths(pattern, max_results=max_results)
        except ValueError:
            return "Glob failed: invalid pattern."
        return "\n".join(unique) or "No paths matched."

    async def _arun(self, pattern: str, max_results: int = 80, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, pattern, max_results, None)


