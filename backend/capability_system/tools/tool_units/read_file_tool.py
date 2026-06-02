from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import WorkspaceFileService


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Relative path inside the project root")
    offset: int = Field(default=0, ge=0, description="Zero-based character offset to start reading from.")
    limit: int = Field(default=10000, ge=1, le=120000, description="Maximum characters to return from the offset.")


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = "Read a local file under the project/workspace root. Use search_files first if the exact path is uncertain."
    args_schema: Type[BaseModel] = ReadFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        path: str,
        offset: int = 0,
        limit: int = 10000,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._files.resolve(path, require_path=True)
        except ValueError as exc:
            return f"Read failed: {exc}"
        if not file_path.exists():
            return "Read failed: file does not exist."
        if file_path.is_dir():
            return "Read failed: path is a directory."
        text = self._files.read_text(file_path, limit=None)
        start = max(0, int(offset or 0))
        size = max(1, min(int(limit or 10000), 120000))
        return text[start : start + size]

    async def _arun(
        self,
        path: str,
        offset: int = 0,
        limit: int = 10000,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, offset, limit, None)


