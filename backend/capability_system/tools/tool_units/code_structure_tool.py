from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.python_ast_tools import (
    PythonCodeOutlineTool,
    PythonParseCheckTool,
    PythonSymbolSearchTool,
)
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


CodeStructureAction = Literal["outline", "symbols", "diagnostics"]


class CodeStructureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CodeStructureAction = Field(description="Code structure action: outline, symbols, or diagnostics.")
    path: str = Field(default="", description="Python file path for outline or diagnostics.")
    query: str = Field(default="", description="Symbol query for symbols action.")
    roots: list[str] = Field(default_factory=list, description="Workspace roots for symbols action.")
    max_symbols: int = Field(default=80, ge=1, le=300, description="Maximum symbols returned by outline.")
    max_results: int = Field(default=40, ge=1, le=200, description="Maximum symbol search matches.")


class CodeStructureTool(BaseTool):
    name: str = "code_structure"
    description: str = (
        "Read Python code structure through the official AST-backed index. "
        "Use outline for one file, symbols for workspace symbol lookup, and diagnostics for parse errors."
    )
    args_schema: type[BaseModel] = CodeStructureInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir).resolve()

    def _run(
        self,
        action: str,
        path: str = "",
        query: str = "",
        roots: list[str] | None = None,
        max_symbols: int = 80,
        max_results: int = 40,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> Any:
        _ = run_manager
        normalized = str(action or "").strip()
        if normalized == "outline":
            return PythonCodeOutlineTool(root_dir=self._root_dir).invoke({"path": path, "max_symbols": max_symbols})
        if normalized == "symbols":
            return PythonSymbolSearchTool(root_dir=self._root_dir).invoke({"query": query, "roots": list(roots or []), "max_results": max_results})
        if normalized == "diagnostics":
            return PythonParseCheckTool(root_dir=self._root_dir).invoke({"path": path})
        return {"text": f"code_structure failed: unsupported action {action!r}", "structured_payload": {"tool_result": {"ok": False}}}

    async def _arun(
        self,
        action: str,
        path: str = "",
        query: str = "",
        roots: list[str] | None = None,
        max_symbols: int = 80,
        max_results: int = 40,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> Any:
        return await asyncio.to_thread(self._run, action, path, query, roots, max_symbols, max_results, None)
