from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from capability_system.tools.tool_units.fetch_url_tool import FetchURLTool, FetchURLToolError
from capability_system.tools.tool_units.memory_search_tool import MemorySearchTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool, SearchTextTool
from capability_system.tools.tool_units.tavily_search import API_URL, build_headers, compact_text, load_backend_env, shape_response
from capability_system.capabilities.retrieval.service import RetrievalService

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


class LocalFilesSearchProvider:
    source_id = "local_files"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
        _ = topic, time_range, config
        return await asyncio.to_thread(
            _run_local_files_search_sync,
            root_dir=self.root_dir,
            query=query,
            max_results=max_results,
        )


class RAGSearchProvider:
    source_id = "rag"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
        _ = topic, time_range, config
        return await asyncio.to_thread(
            _run_rag_search_sync,
            root_dir=self.root_dir,
            query=query,
            max_results=max_results,
        )


class MemorySearchProvider:
    source_id = "memory"

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config: SearchRuntimeConfig) -> dict[str, Any]:
        _ = topic, time_range, config
        return await asyncio.to_thread(
            _run_memory_search_sync,
            root_dir=self.root_dir,
            query=query,
            max_results=max_results,
        )


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


def _run_local_files_search_sync(*, root_dir: Path, query: str, max_results: int) -> dict[str, Any]:
    try:
        text_output = SearchTextTool(root_dir).invoke({"query": query, "max_results": max(1, min(int(max_results or 5), 20))})
        file_output = SearchFilesTool(root_dir).invoke({"query": query, "max_results": max(1, min(int(max_results or 5), 20))})
    except Exception as exc:
        return {"ok": False, "query": query, "source": "local_files", "results": [], "error": str(exc)}
    results = _local_results_from_text(str(text_output or ""), query=query)
    if not results:
        results = _local_results_from_file_list(str(file_output or ""), query=query)
    return {"ok": bool(results), "query": query, "source": "local_files", "results": results, "raw": {"search_text": text_output, "search_files": file_output}}


def _run_rag_search_sync(*, root_dir: Path, query: str, max_results: int) -> dict[str, Any]:
    try:
        result = RetrievalService(_backend_dir(root_dir)).retrieve_execution(query, top_k=max(1, min(int(max_results or 5), 20)))
    except Exception as exc:
        return {"ok": False, "query": query, "source": "rag", "results": [], "error": str(exc)}
    payload = result.to_dict()
    return {
        "ok": result.status == "ok",
        "query": query,
        "source": "rag",
        "results": [_rag_result_item(item, index=index) for index, item in enumerate(result.results, start=1)],
        "diagnostics": payload.get("diagnostics", {}),
        "degraded_reason_typed": payload.get("degraded_reason_typed", ""),
    }


def _run_memory_search_sync(*, root_dir: Path, query: str, max_results: int) -> dict[str, Any]:
    try:
        raw = MemorySearchTool(_storage_root(root_dir)).invoke({"query": query, "limit": max(1, min(int(max_results or 5), 20))})
        payload = json.loads(str(raw or "{}"))
    except Exception as exc:
        return {"ok": False, "query": query, "source": "memory", "results": [], "error": str(exc)}
    results = [_memory_result_item(item, index=index) for index, item in enumerate(list(payload.get("results") or []), start=1)]
    return {"ok": bool(results), "query": query, "source": "memory", "results": results, "diagnostics": dict(payload.get("diagnostics") or {})}


def _local_results_from_text(output: str, *, query: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, line in enumerate([item.strip() for item in output.splitlines() if item.strip()], start=1):
        if line.startswith("没有找到匹配项") or line.startswith("Search failed"):
            continue
        path, line_number, snippet = _parse_rg_line(line)
        if not path:
            continue
        results.append(
            {
                "title": f"{path}:{line_number}" if line_number else path,
                "url": f"file://{path}",
                "source": path,
                "content": snippet or line,
                "score": max(0.2, 1.0 - index * 0.03),
                "_source_type": "local_files",
                "search_source": "local_files",
                "artifact_ref": path,
                "published_date": "",
                "query": query,
            }
        )
    return results


def _local_results_from_file_list(output: str, *, query: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, line in enumerate([item.strip() for item in output.splitlines() if item.strip()], start=1):
        if line.startswith("没有找到匹配项") or line.startswith("Search failed"):
            continue
        path = line.split("]", 1)[-1].strip() if "]" in line else line
        if not path:
            continue
        results.append(
            {
                "title": path,
                "url": f"file://{path}",
                "source": path,
                "content": f"Local file path matched query '{query}': {path}",
                "score": max(0.2, 1.0 - index * 0.03),
                "_source_type": "local_files",
                "search_source": "local_files",
                "artifact_ref": path,
                "published_date": "",
                "query": query,
            }
        )
    return results


def _parse_rg_line(line: str) -> tuple[str, str, str]:
    parts = line.split(":", 3)
    if len(parts) >= 4 and parts[1].isdigit():
        return parts[0], parts[1], parts[3]
    return "", "", line


def _rag_result_item(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    source = str(item.get("source") or item.get("collection") or f"rag:{index}").strip()
    metadata = dict(item.get("metadata") or {})
    page = item.get("page")
    title = source if page in ("", None) else f"{source}#page={page}"
    return {
        "title": title,
        "url": f"rag://{source}",
        "source": source,
        "content": str(item.get("text") or ""),
        "score": item.get("score") or item.get("retrieval_score") or 0.0,
        "_source_type": "rag",
        "search_source": "rag",
        "artifact_ref": str(metadata.get("object_ref_id") or metadata.get("block_id") or metadata.get("doc_id") or source),
        "published_date": "",
        "metadata": metadata,
    }


def _memory_result_item(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    memory_ref = str(item.get("memory_ref") or f"memory:{index}").strip()
    title = str(item.get("record_key") or memory_ref)
    return {
        "title": title,
        "url": f"memory://{memory_ref}",
        "source": memory_ref,
        "content": str(item.get("canonical_text_preview") or item.get("summary") or ""),
        "score": item.get("score") or 0.0,
        "_source_type": "memory",
        "search_source": "memory",
        "artifact_ref": memory_ref,
        "published_date": "",
        "metadata": dict(item),
    }


def _backend_dir(root_dir: Path) -> Path:
    root = Path(root_dir)
    if (root / "knowledge_system").exists():
        return root
    if (root / "backend" / "knowledge_system").exists():
        return root / "backend"
    return root


def _storage_root(root_dir: Path) -> Path:
    root = Path(root_dir)
    if root.name == "storage":
        return root
    if (root / "storage").exists():
        return root / "storage"
    if (root.parent / "storage").exists():
        return root.parent / "storage"
    return root


