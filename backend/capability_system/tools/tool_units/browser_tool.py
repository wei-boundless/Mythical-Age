from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.browser_control_tool import BrowserAction, BrowserControlInput, BrowserControlTool
from pydantic import BaseModel, ConfigDict, PrivateAttr


class BrowserInput(BrowserControlInput):
    model_config = ConfigDict(extra="forbid")


class BrowserTool(BaseTool):
    name: str = "browser"
    description: str = (
        "Operate a real local browser page for navigation, snapshots, interaction, extraction, and screenshots. "
        "Inspect with snapshot before interacting."
    )
    args_schema: type[BaseModel] = BrowserInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _delegate: BrowserControlTool = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delegate = BrowserControlTool(root_dir=root_dir)

    def _run(
        self,
        action: BrowserAction,
        url: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        timeout_ms: int = 8000,
        screenshot_name: str = "",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        return str(
            self._delegate.invoke(
                {
                    "action": action,
                    "url": url,
                    "selector": selector,
                    "text": text,
                    "value": value,
                    "timeout_ms": timeout_ms,
                    "screenshot_name": screenshot_name,
                }
            )
        )

    async def _arun(
        self,
        action: BrowserAction,
        url: str = "",
        selector: str = "",
        text: str = "",
        value: str = "",
        timeout_ms: int = 8000,
        screenshot_name: str = "",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, action, url, selector, text, value, timeout_ms, screenshot_name, None)
