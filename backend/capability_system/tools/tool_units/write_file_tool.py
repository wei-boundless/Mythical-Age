from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Type

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import WorkspaceFileService


class WriteFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Relative path inside the project root. Use the argument name `path`, not `filepath` or `file_path`.")
    content: str = Field(..., description="Complete file content to write. Do not pass placeholders or partial fragments.")
    allow_overwrite: bool = Field(
        default=False,
        description="Set to true only after inspecting the existing file and intentionally replacing the entire file.",
    )
    expected_previous_sha256: str = Field(
        default="",
        description="Optional SHA-256 of the current file content; use it to prove the overwrite target has not changed since inspection.",
    )


class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Relative path inside the project root.")
    old_text: str = Field(..., description="Exact current text to replace. Read the file first and pass a unique verbatim span, including whitespace and line breaks.")
    new_text: str = Field(..., description="Replacement text. Keep unchanged surrounding content out of this value unless it is part of the exact replacement span.")


class _WorkspacePathMixin:
    _files: WorkspaceFileService = PrivateAttr()

    def _resolve_path(self, path: str) -> Path:
        return self._files.resolve(path, require_path=True)

    def _display_path(self, path: Path) -> str:
        return self._files.relative_path(path)


class WriteFileTool(_WorkspacePathMixin, BaseTool):
    name: str = "write_file"
    description: str = (
        "Create a new local workspace file or intentionally overwrite an entire file after runtime authorization. "
        "For existing files, prefer edit_file unless the task explicitly requires replacing the whole file. "
        "Before overwriting an existing file, read the current file and make sure the new content is complete, not a patch, placeholder, or partial fragment."
    )
    args_schema: Type[BaseModel] = WriteFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        path: str,
        content: str,
        allow_overwrite: bool = False,
        expected_previous_sha256: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        try:
            file_path = self._files.write_text(
                path,
                content,
                allow_overwrite=allow_overwrite,
                expected_previous_sha256=expected_previous_sha256,
            )
        except Exception as exc:
            return f"Write failed: {exc}"
        return f"Write succeeded: {self._display_path(file_path)}"

    async def _arun(
        self,
        path: str,
        content: str,
        allow_overwrite: bool = False,
        expected_previous_sha256: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, path, content, allow_overwrite, expected_previous_sha256, None)


class EditFileTool(_WorkspacePathMixin, BaseTool):
    name: str = "edit_file"
    description: str = (
        "Replace exact text in an existing local workspace file after runtime authorization. "
        "Read the file first in the current task before editing, then provide a unique verbatim old_text span with exact whitespace and line breaks. "
        "If old_text is not found, read or search the current file again and retry with the actual current text instead of guessing."
    )
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
            return "Edit failed: old_text not found. Read the current file content and retry with exact current text."
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


