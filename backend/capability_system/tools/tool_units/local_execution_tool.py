from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.terminal_tool import TerminalTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class LocalExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["command"] = Field(default="command", description="Execute a local shell command.")
    command: str = Field(description="Shell command to execute inside the project root.")


class LocalExecutionTool(BaseTool):
    name: str = "local_execution"
    description: str = (
        "Execute local shell commands inside the project root. "
        "Use command action; Python snippets should be run through an explicit shell command."
    )
    args_schema: type[BaseModel] = LocalExecutionInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _delegate: TerminalTool = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delegate = TerminalTool(root_dir=root_dir)

    def _run(
        self,
        command: str,
        action: str = "command",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        if str(action or "command").strip() != "command":
            return f"local_execution failed: unsupported action {action!r}."
        return str(self._delegate.invoke({"command": command}))

    async def _arun(
        self,
        command: str,
        action: str = "command",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, command, action, None)
