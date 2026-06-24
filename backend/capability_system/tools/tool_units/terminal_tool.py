from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Type

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from core.config import get_settings
from core.runtime_encoding import (
    build_windows_powershell_command,
    is_windows,
    utf8_subprocess_text_kwargs,
)
from capability_system.tools.tool_units.sandbox_command_guard import validate_sandbox_command_text


class TerminalToolInput(BaseModel):
    command: str = Field(
        ...,
        description=(
            "Shell command to execute inside the project root. "
            "IMPORTANT: On Windows this tool runs in PowerShell, not bash. "
            "Use PowerShell syntax and cmdlets, not bash operators like ||, &&, "
            "2>/dev/null, ls, cat, or grep."
        ),
    )


class TerminalTool(BaseTool):
    name: str = "terminal"
    description: str = (
        "Execute shell commands inside the project root. Use this for quick inspection, "
        "building, or local commands. Dangerous system-destructive commands are blocked. "
        "This project runs on Windows PowerShell, so commands must use PowerShell syntax "
        "instead of bash syntax."
    )
    args_schema: Type[BaseModel] = TerminalToolInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root_dir = root_dir

    def _run(
        self,
        command: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        blocked_reason = validate_sandbox_command_text(command, kind="command", workspace_root=self._root_dir)
        if blocked_reason:
            return blocked_reason

        settings = get_settings()
        shell_command = (
            build_windows_powershell_command(command)
            if is_windows()
            else ["bash", "-lc", command]
        )
        try:
            completed = subprocess.run(
                shell_command,
                cwd=self._root_dir,
                capture_output=True,
                timeout=settings.terminal_timeout_seconds,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return "Timed out after 30 seconds."

        combined = (completed.stdout or "") + (completed.stderr or "")
        combined = combined.strip() or "[no output]"
        return combined[:5000]

    async def _arun(
        self,
        command: str,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, command, None)



