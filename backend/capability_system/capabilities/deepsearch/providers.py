from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from capability_system.tools.tool_units.fetch_url_tool import FetchURLTool, FetchURLToolError
from capability_system.tools.tool_units.tavily_search import API_URL, build_headers, compact_text, load_backend_env, shape_response

from .models import SearchRuntimeConfig


class TavilySearchProvider:
    def __init__(self, root_dir: Path, *, timeout_seconds: float = 20.0) -> None:
        self.root_dir = Path(root_dir)
        self.timeout_seconds = timeout_seconds

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
        load_backend_env()
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            return {
                "ok": False,
                "query": query,
                "topic": topic,
                "source": "web",
                "results": [],
                "error": "TAVILY_API_KEY is not set.",
            }
        payload = _build_tavily_payload(query=query, topic=topic, time_range=time_range, max_results=max_results, config=config)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    API_URL,
                    headers=build_headers(api_key, os.getenv("TAVILY_PROJECT")),
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "query": query,
                "topic": topic,
                "source": "web",
                "results": [],
                "status_code": exc.response.status_code,
                "error": "Tavily returned an error response.",
                "body": compact_text(exc.response.text, 1500),
            }
        except httpx.TimeoutException:
            return {"ok": False, "query": query, "topic": topic, "source": "web", "results": [], "error": "web_search_timeout"}
        except httpx.HTTPError as exc:
            return {"ok": False, "query": query, "topic": topic, "source": "web", "results": [], "error": "HTTP request to Tavily failed.", "details": str(exc)}

        try:
            data = response.json()
        except ValueError:
            return {"ok": False, "query": query, "topic": topic, "source": "web", "results": [], "error": "web_search_invalid_json"}
        if not isinstance(data, dict):
            return {"ok": False, "query": query, "topic": topic, "source": "web", "results": [], "error": "web_search_invalid_payload"}
        shaped = shape_response(data)
        shaped.setdefault("query", query)
        shaped.setdefault("topic", topic)
        shaped["source"] = "web"
        return shaped


class FetchUrlProvider:
    def __init__(self, tool: FetchURLTool | None = None) -> None:
        self.tool = tool or FetchURLTool()

    async def fetch(self, *, url: str) -> dict[str, Any]:
        try:
            content = await self.tool._arun(url=url)
        except FetchURLToolError as exc:
            return {"ok": False, "url": url, "error": str(exc), "structured_error": dict(exc.structured_error)}
        except Exception as exc:
            return {"ok": False, "url": url, "error": str(exc)}
        return {"ok": True, "url": url, "content_type": "", "content": str(content or "")[:5000]}


def _build_tavily_payload(*, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "topic": topic if topic in {"general", "news", "finance"} else "general",
        "search_depth": config.search_depth,
        "max_results": max(1, min(int(max_results or 5), 10)),
    }
    if config.include_raw_content:
        payload["include_raw_content"] = "markdown"
    if time_range in {"day", "week", "month", "year", "d", "w", "m", "y"}:
        payload["time_range"] = time_range
    return payload


