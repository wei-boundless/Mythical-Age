from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from capability_system.units.tools.memory_search_tool import MemorySearchTool
from capability_system.units.tools.search_files_tool import SearchFilesTool, SearchTextTool
from knowledge_system.retrieval.service import RetrievalService
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
