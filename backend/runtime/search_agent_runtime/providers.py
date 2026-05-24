from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from runtime_encoding import utf8_subprocess_text_kwargs

from .models import SearchRuntimeConfig


class TavilySearchProvider:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
        return await asyncio.to_thread(
            _run_tavily_search_sync,
            root_dir=self.root_dir,
            query=query,
            topic=topic,
            time_range=time_range,
            max_results=max_results,
            config=config,
        )


class FetchUrlProvider:
    async def fetch(self, *, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            return {"ok": False, "url": url, "error": str(exc)}
        content_type = response.headers.get("content-type", "")
        text = response.text[:5000]
        return {"ok": True, "url": url, "content_type": content_type, "content": text}


def _run_tavily_search_sync(
    *,
    root_dir: Path,
    query: str,
    topic: str,
    time_range: str,
    max_results: int,
    config: SearchRuntimeConfig,
) -> dict[str, Any]:
    script_path = Path(root_dir) / "capability_system" / "units" / "tools" / "tavily_search.py"
    if not script_path.exists() and (Path(root_dir) / "backend" / "capability_system" / "units" / "tools" / "tavily_search.py").exists():
        script_path = Path(root_dir) / "backend" / "capability_system" / "units" / "tools" / "tavily_search.py"
    if not script_path.exists():
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_script_not_found"}
    script_path = script_path.resolve()
    command = [
        sys.executable,
        str(script_path),
        "--query",
        query,
        "--topic",
        topic if topic in {"general", "news", "finance"} else "general",
        "--search-depth",
        config.search_depth,
        "--max-results",
        str(max(1, min(int(max_results or 5), 10))),
    ]
    if config.include_raw_content:
        command.extend(["--include-raw-content", "markdown"])
    if time_range in {"day", "week", "month", "year", "d", "w", "m", "y"}:
        command.extend(["--time-range", time_range])
    try:
        completed = subprocess.run(
            command,
            cwd=str(script_path.parents[3]),
            capture_output=True,
            timeout=25,
            check=False,
            **utf8_subprocess_text_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_timeout"}
    raw = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not raw and stderr:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_process_error", "details": stderr[:1000]}
    if not raw:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_empty_output"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "query": query, "topic": topic, "results": [], "error": "web_search_invalid_json", "raw": raw[:1000], "stderr": stderr[:1000]}
    payload.setdefault("query", query)
    payload.setdefault("topic", topic)
    return dict(payload)
