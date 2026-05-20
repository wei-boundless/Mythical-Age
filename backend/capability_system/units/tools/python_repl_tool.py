from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from runtime_encoding import utf8_subprocess_text_kwargs


class PythonReplInput(BaseModel):
    code: str = Field(..., description="Python code to execute")


class PythonReplTool(BaseTool):
    name: str = "python_repl"
    description: str = "Execute short Python snippets in a subprocess and return stdout/stderr."
    args_schema: Type[BaseModel] = PythonReplInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        code: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        lowered = str(code or "").lower()
        if any(pattern in lowered for pattern in ("../", "..\\", "c:\\", "c:/", "d:\\", "d:/", "/etc/", "/var/", "/usr/")):
            return "Blocked: code references a path outside the sandbox workspace."
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code],
                cwd=self._root_dir,
                capture_output=True,
                timeout=15,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return "Timed out after 15 seconds."
        combined = (completed.stdout or "") + (completed.stderr or "")
        return (combined.strip() or "[no output]")[:5000]

    async def _arun(
        self,
        code: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, code, None)
