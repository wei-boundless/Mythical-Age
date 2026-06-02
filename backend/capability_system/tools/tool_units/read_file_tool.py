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
    start_line: int = Field(default=1, ge=1, description="One-based line number to start reading from.")
    line_count: int = Field(default=240, ge=1, le=2000, description="Maximum number of lines to return.")


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
        start_line: int = 1,
        line_count: int = 240,
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
        return _line_window_text(text, start_line=start_line, line_count=line_count)

    async def _arun(
        self,
        path: str,
        start_line: int = 1,
        line_count: int = 240,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, start_line, line_count, None)


def _line_window_text(content: str, *, start_line: int, line_count: int) -> str:
    lines = str(content or "").splitlines()
    total_lines = len(lines)
    start = max(1, int(start_line or 1))
    count = max(1, min(int(line_count or 240), 2000))
    if total_lines == 0:
        return ""
    if start > total_lines:
        return f"Read failed: start_line {start} exceeds total_lines {total_lines}."
    end = min(total_lines, start + count - 1)
    width = max(1, len(str(max(end, start, total_lines))))
    return "\n".join(f"{line_no:>{width}} | {lines[line_no - 1]}" for line_no in range(start, end + 1))


