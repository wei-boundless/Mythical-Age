from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.workspace_file_service import WorkspaceFileService


class WriteFileInput(BaseModel):
    path: str = Field(..., description="Relative path inside the project root")
    content: str = Field(..., description="Complete file content to write")


class EditFileInput(BaseModel):
    path: str = Field(..., description="Relative path inside the project root")
    old_text: str = Field(..., description="Exact text to replace")
    new_text: str = Field(..., description="Replacement text")


class _WorkspacePathMixin:
    _files: WorkspaceFileService = PrivateAttr()

    def _resolve_path(self, path: str) -> Path:
        return self._files.resolve(path, require_path=True)

    def _display_path(self, path: Path) -> str:
        return self._files.relative_path(path)


class WriteFileTool(_WorkspacePathMixin, BaseTool):
    name: str = "write_file"
    description: str = "Create or overwrite a local workspace file after runtime authorization."
    args_schema: Type[BaseModel] = WriteFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        path: str,
        content: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._files.write_text(path, content)
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
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        path: str,
        old_text: str,
        new_text: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._files.edit_text(path, old_text, new_text)
        except FileNotFoundError:
            return "Edit failed: file does not exist."
        except IsADirectoryError:
            return "Edit failed: path is a directory."
        except LookupError:
            return "Edit failed: old_text not found."
        except ValueError as exc:
            return f"Edit failed: {exc}"
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
