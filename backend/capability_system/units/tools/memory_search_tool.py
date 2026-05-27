from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from memory_system.runtime_services import MemoryRuntimeServices


class MemorySearchInput(BaseModel):
    query: str = Field(..., description="Search terms for formal task memory.")
    task_run_id: str = Field(default="", description="Optional task run id. When omitted, searches all formal task memory visible in storage.")
    project_id: str = Field(default="", description="Optional project id. Project-scoped formal memory is searched when provided.")
    repositories: list[str] = Field(default_factory=list, description="Optional logical repository ids to search.")
    collections: list[str] = Field(default_factory=list, description="Optional collection ids to search.")
    limit: int = Field(default=8, ge=1, le=20, description="Maximum result count.")


class MemorySearchTool(BaseTool):
    name: str = "memory_search"
    description: str = (
        "Search the formal task memory database. Use it to retrieve approved world, outline, character, "
        "manuscript fact, continuity, and foreshadowing memory before drafting or reviewing."
    )
    args_schema: Type[BaseModel] = MemorySearchInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _storage_root: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._storage_root = Path(root_dir).resolve()

    def _run(
        self,
        query: str,
        task_run_id: str = "",
        project_id: str = "",
        repositories: list[str] | None = None,
        collections: list[str] | None = None,
        limit: int = 8,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return json.dumps({"error": "memory_search requires query"}, ensure_ascii=False)
        repo_filter = {str(item or "").strip() for item in list(repositories or []) if str(item or "").strip()}
        collection_filter = {str(item or "").strip() for item in list(collections or []) if str(item or "").strip()}
        result_limit = max(1, min(int(limit or 8), 20))
        service = MemoryRuntimeServices.from_runtime_root(self._storage_root).formal_memory
        task_scope = str(task_run_id or "").strip()
        project_scope = str(project_id or "").strip() or _project_id_for_task_run(self._storage_root, task_scope)
        versions = _searchable_versions(service, task_run_id=task_scope, project_id=project_scope)
        terms = _query_terms(normalized_query)
        matches: list[dict[str, Any]] = []
        for version in versions:
            if version.status not in {"accepted", "committed"}:
                continue
            if repo_filter and version.logical_repository_id not in repo_filter and version.repository_id not in repo_filter:
                continue
            if collection_filter and version.collection_id not in collection_filter:
                continue
            haystack_parts = [
                version.logical_repository_id,
                version.collection_id,
                version.record_key,
                version.record_kind,
                version.summary,
                version.canonical_text,
                json.dumps(version.payload, ensure_ascii=False, sort_keys=True),
            ]
            haystack = "\n".join(str(item or "") for item in haystack_parts).lower()
            score = _match_score(terms, haystack)
            if score <= 0:
                continue
            matches.append(
                {
                    "score": score,
                    "memory_ref": version.version_id,
                    "record_key": version.record_key,
                    "record_kind": version.record_kind,
                    "repository": version.logical_repository_id or version.repository_id,
                    "effective_repository": version.repository_id,
                    "collection": version.collection_id,
                    "summary": version.summary,
                    "canonical_text_preview": _preview(version.canonical_text),
                    "artifact_refs": list(version.artifact_refs),
                    "source_node_id": version.source_node_id,
                    "source_clock": version.source_clock,
                }
            )
        matches.sort(key=lambda item: (-int(item["score"]), str(item["repository"]), str(item["collection"]), str(item["record_key"])))
        payload = {
            "authority": "formal_memory.memory_search_tool",
            "query": normalized_query,
            "task_run_id": task_scope,
            "project_id": project_scope,
            "repositories": sorted(repo_filter),
            "collections": sorted(collection_filter),
            "result_count": min(len(matches), result_limit),
            "results": matches[:result_limit],
            "diagnostics": {
                "candidate_version_count": len(versions),
                "matched_version_count": len(matches),
                "search_terms": terms,
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    async def _arun(
        self,
        query: str,
        task_run_id: str = "",
        project_id: str = "",
        repositories: list[str] | None = None,
        collections: list[str] | None = None,
        limit: int = 8,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, task_run_id, project_id, repositories, collections, limit, None)


def _searchable_versions(service: Any, *, task_run_id: str, project_id: str) -> tuple[Any, ...]:
    if not task_run_id and not project_id:
        return service.store.list_versions(limit=500)
    return tuple(
        version
        for version in service.store.list_versions(limit=2000)
        if _version_visible_to_search(version, task_run_id=task_run_id, project_id=project_id)
    )


def _version_visible_to_search(version: Any, *, task_run_id: str, project_id: str) -> bool:
    if task_run_id and str(getattr(version, "task_run_id", "") or "") == task_run_id:
        return True
    if project_id and str(getattr(version, "scope_kind", "") or "") == "project_scoped":
        return str(getattr(version, "scope_id", "") or "") == project_id
    return False


def _project_id_for_task_run(storage_root: Path, task_run_id: str) -> str:
    if not task_run_id:
        return ""
    from runtime.memory.state_index import RuntimeStateIndex

    runtime_root = storage_root / "runtime_state" if storage_root.name == "storage" else storage_root
    if runtime_root.name != "runtime_state":
        runtime_root = MemoryRuntimeServices.from_runtime_root(storage_root).storage_root / "runtime_state"
    try:
        task_run = RuntimeStateIndex(runtime_root).get_task_run(task_run_id)
    except Exception:
        task_run = None
    if task_run is None:
        return ""
    return str(dict(getattr(task_run, "diagnostics", {}) or {}).get("project_id") or "").strip()


def _query_terms(query: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9_.\-\u4e00-\u9fff]+", query.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for term in [query.lower(), *raw_terms]:
        normalized = term.strip("._- \t\r\n")
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms


def _match_score(terms: list[str], haystack: str) -> int:
    score = 0
    for term in terms:
        if term in haystack:
            score += max(1, min(len(term), 20))
    return score


def _preview(text: str, *, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


