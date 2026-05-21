from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.workspace_file_service import WorkspaceFileService


class ReadFileInput(BaseModel):
    path: str = Field(..., description="Relative path inside the project root")


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
        return self._files.read_text(file_path, limit=10000)

    async def _arun(
        self,
        path: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, None)
