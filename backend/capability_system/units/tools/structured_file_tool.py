from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path
from typing import Any, Type

import yaml
from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.workspace_file_service import WorkspaceFileService


class StructuredToolResult(dict):
    def __str__(self) -> str:
        return str(self.get("text") or "")


class ReadStructuredFileInput(BaseModel):
    path: str = Field(..., description="JSON/YAML/TOML file path relative to the project root")


class ReadStructuredFileTool(BaseTool):
    name: str = "read_structured_file"
    description: str = "Parse a known JSON, YAML, or TOML config file and return a compact structural summary."
    args_schema: Type[BaseModel] = ReadStructuredFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(self, path: str, run_manager: CallbackManagerForToolRun | None = None) -> StructuredToolResult:
        try:
            file_path = self._files.resolve(path, require_path=True)
        except ValueError as exc:
            return _error_result(f"Structured read failed: {exc}")
        if not file_path.exists():
            return _error_result("Structured read failed: file does not exist.")
        if file_path.is_dir():
            return _error_result("Structured read failed: path is a directory.")
        suffix = file_path.suffix.lower()
        try:
            if suffix == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
                data_format = "json"
            elif suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
                data_format = "yaml"
            elif suffix == ".toml":
                data = tomllib.loads(file_path.read_text(encoding="utf-8"))
                data_format = "toml"
            else:
                return _error_result("Structured read failed: supported formats are JSON, YAML, and TOML.")
        except Exception as exc:
            return _error_result(f"Structured read failed: {exc}")
        summary = _summarize(data)
        return StructuredToolResult(
            {
                "text": summary,
                "structured_payload": {
                    "tool_result": {
                        "kind": "structured_file",
                        "path": str(path or "").strip(),
                        "format": data_format,
                        "root_type": type(data).__name__,
                        "data": data,
                        "summary": summary,
                    }
                },
            }
        )

    async def _arun(self, path: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> StructuredToolResult:
        return await asyncio.to_thread(self._run, path, None)


def _error_result(message: str) -> StructuredToolResult:
    return StructuredToolResult(
        {
            "text": str(message or ""),
            "structured_payload": {
                "tool_result": {
                    "kind": "structured_file",
                    "status": "error",
                    "error": str(message or ""),
                }
            },
        }
    )


def _summarize(value: Any, *, max_items: int = 30) -> str:
    lines: list[str] = [f"root_type: {type(value).__name__}"]
    _walk(value, "$", lines, max_items=max_items)
    return "\n".join(lines[: max_items + 1])


def _walk(value: Any, path: str, lines: list[str], *, max_items: int) -> None:
    if len(lines) > max_items:
        return
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        lines.append(f"{path}: object keys={keys[:20]}")
        for key, item in list(value.items())[:8]:
            _walk(item, f"{path}.{key}", lines, max_items=max_items)
        return
    if isinstance(value, list):
        lines.append(f"{path}: array len={len(value)}")
        if value:
            _walk(value[0], f"{path}[0]", lines, max_items=max_items)
        return
    if isinstance(value, (str, int, float, bool)) or value is None:
        preview = str(value)
        if len(preview) > 120:
            preview = preview[:117] + "..."
        lines.append(f"{path}: {type(value).__name__} = {preview}")
        return
    lines.append(f"{path}: {type(value).__name__}")


