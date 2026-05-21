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

from capability_system.units.tools.workspace_paths import resolve_workspace_path


class ReadStructuredFileInput(BaseModel):
    path: str = Field(..., description="JSON/YAML/TOML file path relative to the project root")


class ReadStructuredFileTool(BaseTool):
    name: str = "read_structured_file"
    description: str = "Parse a known JSON, YAML, or TOML config file and return a compact structural summary."
    args_schema: Type[BaseModel] = ReadStructuredFileInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir.resolve()

    def _resolve_path(self, path: str) -> Path:
        return resolve_workspace_path(self._root_dir, path)

    def _run(self, path: str, run_manager: CallbackManagerForToolRun | None = None) -> str:
        try:
            file_path = self._resolve_path(path)
        except ValueError as exc:
            return f"Structured read failed: {exc}"
        if not file_path.exists():
            return "Structured read failed: file does not exist."
        if file_path.is_dir():
            return "Structured read failed: path is a directory."
        suffix = file_path.suffix.lower()
        try:
            if suffix == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
            elif suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            elif suffix == ".toml":
                data = tomllib.loads(file_path.read_text(encoding="utf-8"))
            else:
                return "Structured read failed: supported formats are JSON, YAML, and TOML."
        except Exception as exc:
            return f"Structured read failed: {exc}"
        return _summarize(data)

    async def _arun(self, path: str, run_manager: AsyncCallbackManagerForToolRun | None = None) -> str:
        return await asyncio.to_thread(self._run, path, None)


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
