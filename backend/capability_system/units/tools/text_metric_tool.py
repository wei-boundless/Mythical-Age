from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.workspace_file_service import WorkspaceFileService
from text_metric import measure_text


class TextMetricInput(BaseModel):
    text: str = Field(default="", description="Text to measure. Use this for direct content already in context.")
    path: str = Field(default="", description="Optional workspace-relative text file path to measure instead of the text field.")
    measurement_mode: str = Field(default="text_units", description="text_units, tokens, or hybrid.")


class TextMetricTool(BaseTool):
    name: str = "text_metric"
    description: str = (
        "Measure text length for task contracts. Returns CJK character count, Latin word count, "
        "combined text_units, and structural counts. Token modes currently report a text_units fallback."
    )
    args_schema: Type[BaseModel] = TextMetricInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        text: str = "",
        path: str = "",
        measurement_mode: str = "text_units",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        content = str(text or "")
        source = "inline_text"
        if str(path or "").strip():
            try:
                file_path = self._files.resolve(path, require_path=True)
            except ValueError as exc:
                return f"Text metric failed: {exc}"
            if not file_path.exists():
                return "Text metric failed: file does not exist."
            if file_path.is_dir():
                return "Text metric failed: path is a directory."
            content = self._files.read_text(file_path)
            source = "workspace_file"
        result = measure_text(content, measurement_mode=measurement_mode).to_dict()
        result["source"] = source
        result["path"] = str(path or "").strip()
        return json.dumps(result, ensure_ascii=False, sort_keys=True)

    async def _arun(
        self,
        text: str = "",
        path: str = "",
        measurement_mode: str = "text_units",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, text, path, measurement_mode, None)
