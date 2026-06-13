from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from runtime_objects.tool_result_storage import (
    DEFAULT_REHYDRATION_SIZE_BYTES,
    MAX_REHYDRATION_SIZE_BYTES,
    read_persisted_tool_result,
)


class ReadPersistedToolResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement_id: str = Field(default="", description="Persisted result id from the rehydration plan, such as tool_result:<digest>.")
    path: str = Field(default="", description="Persisted result path from the rehydration plan.")
    task_run_id: str = Field(default="", description="Optional task run id to disambiguate a replacement id.")
    start_byte: int = Field(default=0, ge=0, description="Zero-based byte offset to start reading from.")
    max_bytes: int = Field(
        default=DEFAULT_REHYDRATION_SIZE_BYTES,
        ge=1,
        le=MAX_REHYDRATION_SIZE_BYTES,
        description="Maximum bytes to return.",
    )


class ReadPersistedToolResultTool(BaseTool):
    name: str = "read_persisted_tool_result"
    description: str = (
        "Read exact omitted output that the runtime context projector previously persisted. "
        "Use only with replacement_id/path values from a rehydration_plan."
    )
    args_schema: Type[BaseModel] = ReadPersistedToolResultInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir)

    def _run(
        self,
        replacement_id: str = "",
        path: str = "",
        task_run_id: str = "",
        start_byte: int = 0,
        max_bytes: int = DEFAULT_REHYDRATION_SIZE_BYTES,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        if replacement_id and not replacement_id.startswith("tool_result:"):
            return json.dumps(
                {
                    "ok": False,
                    "error": "replacement_id must start with tool_result:",
                    "structured_error": {
                        "code": "invalid_rehydration_replacement_id",
                        "message": "replacement_id must start with tool_result:",
                        "retryable": False,
                    },
                },
                ensure_ascii=False,
            )
        result = read_persisted_tool_result(
            root_dir=self._root_dir,
            replacement_id=replacement_id,
            path=path,
            task_run_id=task_run_id,
            start_byte=start_byte,
            max_bytes=max_bytes,
        )
        if result.get("ok") is not True:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(result.get("error") or "persisted tool result read failed"),
                    "structured_error": {
                        "code": "persisted_tool_result_read_failed",
                        "message": str(result.get("error") or "persisted tool result read failed"),
                        "retryable": False,
                    },
                },
                ensure_ascii=False,
            )
        return str(result.get("content") or "")

    async def _arun(
        self,
        replacement_id: str = "",
        path: str = "",
        task_run_id: str = "",
        start_byte: int = 0,
        max_bytes: int = DEFAULT_REHYDRATION_SIZE_BYTES,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._run,
            replacement_id,
            path,
            task_run_id,
            start_byte,
            max_bytes,
            None,
        )

__all__ = ["ReadPersistedToolResultInput", "ReadPersistedToolResultTool"]
