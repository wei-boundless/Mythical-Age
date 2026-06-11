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
    DEFAULT_RUNTIME_PRIVATE_PATHS,
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
    output_mode: str = Field(default="content", description="输出模式：content、files_with_matches 或 count")
    context: int = Field(default=0, ge=0, le=20, description="推荐读取窗口时每个命中行前后包含的上下文行数")
    case_sensitive: bool = Field(default=False, description="是否区分大小写搜索")
    head_limit: int = Field(default=0, ge=0, le=100, description="分页返回条数；0 表示使用 max_results")
    offset: int = Field(default=0, ge=0, description="分页偏移，跳过前 N 条匹配")


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
                ["--files", *_runtime_private_exclude_args(), *_default_search_exclude_args(using_default_roots), *root_args],
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
        output_mode: str = "content",
        context: int = 0,
        case_sensitive: bool = False,
        head_limit: int = 0,
        offset: int = 0,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        limit = _search_limit(max_results=max_results, head_limit=head_limit)
        scan_limit = min(100, limit + max(0, int(offset or 0)) + 1)
        mode = _normalize_output_mode(output_mode)
        requested_paths = _nonempty_path_args(paths)
        if requested_paths:
            target_paths, path_error = _resolve_search_paths(self._files, requested_paths)
            if path_error:
                return f"Search failed: {path_error}"
            matches = _search_specific_paths(
                    self._files,
                    normalized_query,
                    target_paths,
                    glob=str(glob or ""),
                    limit=scan_limit,
                    case_sensitive=case_sensitive,
                )
            return _format_search_matches(
                _slice_matches(matches, offset=offset, limit=limit),
                query=normalized_query,
                output_mode=mode,
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
            "--hidden",
            "--max-count",
            str(scan_limit),
        ]
        if not bool(case_sensitive):
            args.append("--ignore-case")
        for excluded in DEFAULT_EXCLUDED_DIRS:
            args.extend(["--glob", f"!**/{excluded}/**"])
        args.extend(_runtime_private_exclude_args())
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
                limit=scan_limit,
                using_default_roots=using_default_roots,
                case_sensitive=case_sensitive,
            )
        if completed.returncode not in {0, 1}:
            error = (completed.stderr or "").strip()
            return f"Search failed: {error[:300] or 'ripgrep returned an error.'}"
        lines = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return _format_no_results(normalized_query)
        return _format_search_matches(
            _slice_raw_match_lines(lines, offset=offset, limit=limit),
            query=normalized_query,
            output_mode=mode,
        )

    def _fallback_search(
        self,
        query: str,
        roots: list[Path],
        *,
        glob: str,
        limit: int,
        using_default_roots: bool,
        case_sensitive: bool,
    ) -> str:
        matches: list[str] = []
        pattern = glob.strip() or "*"
        query_cmp = query if case_sensitive else query.lower()
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
                    line_cmp = line if case_sensitive else line.lower()
                    if query_cmp not in line_cmp:
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
        output_mode: str = "content",
        context: int = 0,
        case_sensitive: bool = False,
        head_limit: int = 0,
        offset: int = 0,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._run,
            query,
            roots,
            paths,
            glob,
            max_results,
            output_mode,
            context,
            case_sensitive,
            head_limit,
            offset,
            None,
        )


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
    case_sensitive: bool,
) -> list[str]:
    matches: list[str] = []
    pattern = str(glob or "").strip()
    query_cmp = query if case_sensitive else query.lower()
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
            line_cmp = line if case_sensitive else line.lower()
            column = line_cmp.find(query_cmp) + 1
            if column <= 0:
                continue
            matches.append(f"{rel}:{line_number}:{column}:{line[:240]}")
            if len(matches) >= limit:
                return matches
    return matches[:limit]


def _format_search_matches(matches: list[str], *, query: str, output_mode: str = "content") -> str:
    if not matches:
        return _format_no_results(query)
    if output_mode == "files_with_matches":
        paths = [line.split(":", 1)[0] for line in matches if ":" in line]
        return "\n".join(dict.fromkeys(paths)) or _format_no_results(query)
    if output_mode == "count":
        counts: dict[str, int] = {}
        for line in matches:
            path = line.split(":", 1)[0] if ":" in line else ""
            if path:
                counts[path] = counts.get(path, 0) + 1
        return "\n".join(f"{path}:{count}" for path, count in counts.items()) or _format_no_results(query)
    return "\n".join(matches)


def _search_limit(*, max_results: int, head_limit: int = 0) -> int:
    selected = int(head_limit or 0) or int(max_results or 20)
    return max(1, min(selected, 100))


def _normalize_output_mode(value: str) -> str:
    mode = str(value or "content").strip()
    return mode if mode in {"content", "files_with_matches", "count"} else "content"


def _slice_matches(matches: list[str], *, offset: int, limit: int) -> list[str]:
    start = max(0, int(offset or 0))
    return list(matches)[start : start + max(1, int(limit or 1))]


def _slice_raw_match_lines(lines: list[str], *, offset: int, limit: int) -> list[str]:
    return _slice_matches(lines, offset=offset, limit=limit)


def _default_search_exclude_args(enabled: bool) -> list[str]:
    if not enabled:
        return []
    args: list[str] = []
    for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
        args.extend(["--glob", f"!{excluded}/**"])
    return args


def _runtime_private_exclude_args() -> list[str]:
    args: list[str] = []
    for excluded in DEFAULT_RUNTIME_PRIVATE_PATHS:
        args.extend(["--glob", f"!{excluded}"])
    return args


