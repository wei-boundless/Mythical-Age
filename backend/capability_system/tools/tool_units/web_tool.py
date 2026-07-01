from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from capability_system.tools.base_tool import AsyncCallbackManagerForToolRun, BaseTool, CallbackManagerForToolRun
from capability_system.tools.tool_units.fetch_url_tool import FetchURLTool
from capability_system.tools.tool_units.web_search_tool import WebSearchTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class WebInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "fetch"] = Field(description="Web action: search or fetch.")
    query: str = Field(default="", description="Search query for action=search.")
    url: str = Field(default="", description="HTTP/HTTPS URL for action=fetch.")
    topic: str = Field(default="general", description="Search topic: general, news, or finance.")
    time_range: str | None = Field(default=None, description="Optional search time range: day, week, month, or year.")
    max_results: int = Field(default=5, ge=1, le=10, description="Maximum search results.")


class WebTool(BaseTool):
    name: str = "web"
    description: str = (
        "Search the web or fetch a specific URL for current external evidence. "
        "Use search to discover candidate sources, then fetch key primary pages when precision matters."
    )
    args_schema: type[BaseModel] = WebInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _root_dir: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._root_dir = Path(root_dir).resolve()

    def _run(
        self,
        action: str,
        query: str = "",
        url: str = "",
        topic: str = "general",
        time_range: str | None = None,
        max_results: int = 5,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized = str(action or "").strip()
        if normalized == "search":
            return str(WebSearchTool(root_dir=self._root_dir).invoke({"query": query, "topic": topic, "time_range": time_range, "max_results": max_results}))
        if normalized == "fetch":
            return str(FetchURLTool().invoke({"url": url}))
        return f"web failed: unsupported action {action!r}."

    async def _arun(
        self,
        action: str,
        query: str = "",
        url: str = "",
        topic: str = "general",
        time_range: str | None = None,
        max_results: int = 5,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, action, query, url, topic, time_range, max_results, None)
