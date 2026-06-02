from __future__ import annotations

import asyncio
import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from capability_system.tools.workspace_file_service import (
    DEFAULT_EXCLUDED_DIRS,
    DEFAULT_SEARCH_EXCLUDED_PATHS,
    WorkspaceFileService,
)


class SearchFilesInput(BaseModel):
    query: str = Field(..., description="文件名或路径关键词，例如 OpenClaw、计划书、task_understanding.py")
    roots: list[str] = Field(
        default_factory=list,
        description="可选搜索根目录，默认搜索 docs/backend/frontend；路径必须在项目根目录内",
    )
    max_results: int = Field(default=20, ge=1, le=100, description="最大返回条数")


class SearchTextInput(BaseModel):
    query: str = Field(..., description="要在文件内容里搜索的文本或正则关键词")
    roots: list[str] = Field(
        default_factory=list,
        description="可选搜索根目录，默认搜索 docs/backend/frontend；路径必须在项目根目录内",
    )
    paths: list[str] = Field(
        default_factory=list,
        description="可选具体文件路径；当只想在一个或多个已知文件里搜索时使用，不要放入 roots",
    )
    glob: str = Field(default="", description="可选 glob，例如 **/*.md 或 backend/**/*.py")
    max_results: int = Field(default=20, ge=1, le=100, description="最大返回条数")


def _run_rg(args: list[str], *, cwd: Path, timeout: float = 8.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["rg", *args],
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return None


def _format_no_results(query: str) -> str:
    return f"没有找到匹配项：{query}"


def _query_terms(query: str) -> list[str]:
    normalized = str(query or "").strip()
    terms = [normalized.lower()] if normalized else []
    for item in re.findall(r"[A-Za-z0-9_.\-\u4e00-\u9fff]+", normalized):
        lowered = item.lower().strip("._-")
        if len(lowered) < 2:
            continue
        if lowered in {"文件", "查找", "搜索", "帮我", "找到", "打开", "读取", "一下", "路径"}:
            continue
        terms.append(lowered)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if not term or term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


class SearchFilesTool(BaseTool):
    name: str = "search_files"
    description: str = (
        "Search local workspace file paths before reading files. Use this when a filename or path is uncertain; "
        "returns safe project-relative paths that can be passed to read_file or the appropriate MCP route."
    )
    args_schema: Type[BaseModel] = SearchFilesInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 20,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        using_default_roots = not [str(item or "").strip() for item in list(roots or [])]
        safe_roots = self._files.safe_roots(roots)
        if not safe_roots:
            return "Search failed: no safe search roots."

        limit = max(1, min(int(max_results or 20), 100))
        completed = None
        if self._files.search_root_args_are_workspace_relative(safe_roots):
            root_args = [self._files.relative_path(root) for root in safe_roots]
            completed = _run_rg(
                ["--files", *_default_search_exclude_args(using_default_roots), *root_args],
                cwd=self._files.workspace_root,
            )
        paths: list[str] = []
        if completed is not None and completed.returncode in {0, 1}:
            paths = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
        else:
            for root in safe_roots:
                for path in root.rglob("*"):
                    if path.is_file() and not self._files.is_excluded(
                        path,
                        include_default_search_excludes=using_default_roots,
                    ):
                        paths.append(self._files.relative_path(path))

        terms = _query_terms(normalized_query)
        matches = [path for path in paths if any(term in path.lower() for term in terms)]
        matches = sorted(dict.fromkeys(matches))[:limit]
        if not matches:
            return _format_no_results(normalized_query)
        return "\n".join(f"[{index}] {path}" for index, path in enumerate(matches, start=1))

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        max_results: int = 20,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, roots, max_results, None)


class SearchTextTool(BaseTool):
    name: str = "search_text"
    description: str = (
        "Search local workspace file contents with ripgrep-style matching. Use this to locate code, docs, headings, "
        "or references before choosing a file to read."
    )
    args_schema: Type[BaseModel] = SearchTextInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _files: WorkspaceFileService = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._files = WorkspaceFileService(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        paths: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        limit = max(1, min(int(max_results or 20), 100))
        requested_paths = _nonempty_path_args(paths)
        if requested_paths:
            target_paths, path_error = _resolve_search_paths(self._files, requested_paths)
            if path_error:
                return f"Search failed: {path_error}"
            return _format_search_matches(
                _search_specific_paths(
                    self._files,
                    normalized_query,
                    target_paths,
                    glob=str(glob or ""),
                    limit=limit,
                ),
                query=normalized_query,
            )
        roots_error = _roots_file_misuse_error(self._files, roots)
        if roots_error:
            return f"Search failed: {roots_error}"
        using_default_roots = not [str(item or "").strip() for item in list(roots or [])]
        safe_roots = self._files.safe_roots(roots)
        if not safe_roots:
            return "Search failed: no safe search roots."

        args = [
            "--line-number",
            "--column",
            "--ignore-case",
            "--hidden",
            "--max-count",
            str(limit),
        ]
        for excluded in DEFAULT_EXCLUDED_DIRS:
            args.extend(["--glob", f"!**/{excluded}/**"])
        args.extend(_default_search_exclude_args(using_default_roots))
        if str(glob or "").strip():
            args.extend(["--glob", str(glob).strip()])
        args.append(normalized_query)
        completed = None
        if self._files.search_root_args_are_workspace_relative(safe_roots):
            args.extend(self._files.relative_path(root) for root in safe_roots)
            completed = _run_rg(args, cwd=self._files.workspace_root)
        if completed is None:
            return self._fallback_search(
                normalized_query,
                safe_roots,
                glob=str(glob or ""),
                limit=limit,
                using_default_roots=using_default_roots,
            )
        if completed.returncode not in {0, 1}:
            error = (completed.stderr or "").strip()
            return f"Search failed: {error[:300] or 'ripgrep returned an error.'}"
        lines = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return _format_no_results(normalized_query)
        return "\n".join(lines[:limit])

    def _fallback_search(
        self,
        query: str,
        roots: list[Path],
        *,
        glob: str,
        limit: int,
        using_default_roots: bool,
    ) -> str:
        matches: list[str] = []
        pattern = glob.strip() or "*"
        for root in roots:
            for path in root.rglob(pattern):
                if len(matches) >= limit:
                    break
                if not path.is_file() or self._files.is_excluded(
                    path,
                    include_default_search_excludes=using_default_roots,
                ):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query.lower() not in line.lower():
                        continue
                    rel = self._files.relative_path(path)
                    matches.append(f"{rel}:{line_number}:1:{line[:240]}")
                    break
        if not matches:
            return _format_no_results(query)
        return "\n".join(matches[:limit])

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        paths: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, roots, paths, glob, max_results, None)


def _nonempty_path_args(paths: list[str] | str | None) -> list[str]:
    values = [paths] if isinstance(paths, str) else list(paths or [])
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def _roots_file_misuse_error(files: WorkspaceFileService, roots: list[str] | None) -> str:
    for item in _nonempty_path_args(roots):
        try:
            target = files.resolve(item, require_path=True)
        except ValueError:
            continue
        if target.exists() and target.is_file():
            rel = files.relative_path(target)
            return f"roots accepts directories only. Put file paths in paths instead, for example paths=[\"{rel}\"]."
    return ""


def _resolve_search_paths(files: WorkspaceFileService, paths: list[str]) -> tuple[list[Path], str]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in paths:
        try:
            target = files.resolve(item, require_path=True)
        except ValueError as exc:
            return [], str(exc)
        if not target.exists():
            return [], f"path does not exist: {item}"
        if target.is_dir():
            return [], f"paths accepts files only. Put directory roots in roots instead: {item}"
        if target not in seen:
            seen.add(target)
            resolved.append(target)
    return resolved, ""


def _search_specific_paths(
    files: WorkspaceFileService,
    query: str,
    paths: list[Path],
    *,
    glob: str,
    limit: int,
) -> list[str]:
    matches: list[str] = []
    pattern = str(glob or "").strip()
    for path in paths:
        if len(matches) >= limit:
            break
        rel = files.relative_path(path)
        if pattern and not fnmatch.fnmatch(rel, pattern):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            column = line.lower().find(query.lower()) + 1
            if column <= 0:
                continue
            matches.append(f"{rel}:{line_number}:{column}:{line[:240]}")
            if len(matches) >= limit:
                return matches
    return matches[:limit]


def _format_search_matches(matches: list[str], *, query: str) -> str:
    return "\n".join(matches) if matches else _format_no_results(query)


def _default_search_exclude_args(enabled: bool) -> list[str]:
    if not enabled:
        return []
    args: list[str] = []
    for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
        args.extend(["--glob", f"!{excluded}/**"])
    return args


