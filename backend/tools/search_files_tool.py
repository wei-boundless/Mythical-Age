from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Type

from langchain_core.callbacks.manager import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


_DEFAULT_ROOTS = ("docs", "backend", "frontend")
_EXCLUDED_DIRS = (
    ".git",
    ".pytest_cache",
    ".tmp-tests-runtime",
    "__pycache__",
    "node_modules",
    "output",
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
    glob: str = Field(default="", description="可选 glob，例如 **/*.md 或 backend/**/*.py")
    max_results: int = Field(default=20, ge=1, le=100, description="最大返回条数")


def _workspace_root(root_dir: Path) -> Path:
    resolved = root_dir.resolve()
    if resolved.name == "backend" and resolved.parent.exists():
        return resolved.parent
    return resolved


def _safe_roots(workspace_root: Path, roots: list[str] | tuple[str, ...] | None) -> list[Path]:
    requested = [str(item or "").strip().replace("\\", "/") for item in list(roots or [])]
    if not requested:
        requested = list(_DEFAULT_ROOTS)
    safe: list[Path] = []
    seen: set[Path] = set()
    for item in requested:
        if not item or item.startswith("-"):
            continue
        candidate = (workspace_root / item).resolve()
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            continue
        if not candidate.exists() or candidate in seen:
            continue
        seen.add(candidate)
        safe.append(candidate)
    return safe


def _relative_path(workspace_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(workspace_root)).replace("\\", "/")


def _is_excluded(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return any(excluded.lower() in parts for excluded in _EXCLUDED_DIRS)


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
    except (FileNotFoundError, subprocess.TimeoutExpired):
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
        "returns safe project-relative paths that can be passed to read_file, pdf_analysis, or structured_data_analysis."
    )
    args_schema: Type[BaseModel] = SearchFilesInput
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _workspace_root: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._workspace_root = _workspace_root(root_dir)

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
        safe_roots = _safe_roots(self._workspace_root, roots)
        if not safe_roots:
            return "Search failed: no safe search roots."

        limit = max(1, min(int(max_results or 20), 100))
        root_args = [_relative_path(self._workspace_root, root) for root in safe_roots]
        completed = _run_rg(["--files", *root_args], cwd=self._workspace_root)
        paths: list[str] = []
        if completed is not None and completed.returncode in {0, 1}:
            paths = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
        else:
            for root in safe_roots:
                for path in root.rglob("*"):
                    if path.is_file() and not _is_excluded(path):
                        paths.append(_relative_path(self._workspace_root, path))

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
    _workspace_root: Path = PrivateAttr()

    def __init__(self, root_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._workspace_root = _workspace_root(root_dir)

    def _run(
        self,
        query: str,
        roots: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        _ = run_manager
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Search failed: query is required."
        safe_roots = _safe_roots(self._workspace_root, roots)
        if not safe_roots:
            return "Search failed: no safe search roots."

        limit = max(1, min(int(max_results or 20), 100))
        args = [
            "--line-number",
            "--column",
            "--ignore-case",
            "--hidden",
            "--max-count",
            str(limit),
        ]
        for excluded in _EXCLUDED_DIRS:
            args.extend(["--glob", f"!**/{excluded}/**"])
        if str(glob or "").strip():
            args.extend(["--glob", str(glob).strip()])
        args.append(normalized_query)
        args.extend(_relative_path(self._workspace_root, root) for root in safe_roots)

        completed = _run_rg(args, cwd=self._workspace_root)
        if completed is None:
            return self._fallback_search(normalized_query, safe_roots, glob=str(glob or ""), limit=limit)
        if completed.returncode not in {0, 1}:
            error = (completed.stderr or "").strip()
            return f"Search failed: {error[:300] or 'ripgrep returned an error.'}"
        lines = [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return _format_no_results(normalized_query)
        return "\n".join(lines[:limit])

    def _fallback_search(self, query: str, roots: list[Path], *, glob: str, limit: int) -> str:
        matches: list[str] = []
        pattern = glob.strip() or "*"
        for root in roots:
            for path in root.rglob(pattern):
                if len(matches) >= limit:
                    break
                if not path.is_file() or _is_excluded(path):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if query.lower() not in line.lower():
                        continue
                    rel = _relative_path(self._workspace_root, path)
                    matches.append(f"{rel}:{line_number}:1:{line[:240]}")
                    break
        if not matches:
            return _format_no_results(query)
        return "\n".join(matches[:limit])

    async def _arun(
        self,
        query: str,
        roots: list[str] | None = None,
        glob: str = "",
        max_results: int = 20,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        return await asyncio.to_thread(self._run, query, roots, glob, max_results, None)
