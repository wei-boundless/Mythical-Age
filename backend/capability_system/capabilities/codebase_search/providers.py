from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from capability_system.tools.tool_units.file_system_tools import GlobPathsTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool, SearchTextTool
from runtime_encoding import utf8_subprocess_text_kwargs


@dataclass(frozen=True, slots=True)
class TextHit:
    file: str
    line: int
    column: int
    snippet: str
    query: str


class CodebaseSearchProviders:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.search_files_tool = SearchFilesTool(root_dir)
        self.search_text_tool = SearchTextTool(root_dir)
        self.glob_paths_tool = GlobPathsTool(root_dir)

    async def search_paths(self, *, queries: tuple[str, ...], roots: tuple[str, ...], max_results: int) -> list[str]:
        found: list[str] = []
        for query in queries:
            raw = await self.search_files_tool._arun(query=query, roots=list(roots), max_results=max_results)
            found.extend(_parse_path_results(raw))
        return _dedupe(found)[:max_results]

    async def search_text(self, *, queries: tuple[str, ...], roots: tuple[str, ...], max_results: int) -> list[TextHit]:
        hits: list[TextHit] = []
        per_query = max(1, max_results // max(1, len(queries)))
        for query in queries:
            raw = await self.search_text_tool._arun(query=query, roots=list(roots), max_results=per_query)
            hits.extend(_parse_text_hits(raw, query=query))
        return _dedupe_hits(hits)[:max_results]

    async def glob_paths(self, *, patterns: tuple[str, ...], max_results: int) -> list[str]:
        found: list[str] = []
        per_pattern = max(1, max_results // max(1, len(patterns)))
        for pattern in patterns:
            raw = await self.glob_paths_tool._arun(pattern=pattern, max_results=per_pattern)
            found.extend(line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip() and not line.startswith("No paths"))
        return _dedupe(found)[:max_results]

    async def git_log(self, *, queries: tuple[str, ...], max_results: int = 8) -> list[dict[str, str]]:
        return await asyncio.to_thread(_git_log_sync, self.root_dir, queries, max_results)


def _parse_path_results(raw: str) -> list[str]:
    paths: list[str] = []
    for line in str(raw or "").splitlines():
        item = line.strip()
        if not item or item.startswith("没有找到") or item.startswith("Search failed"):
            continue
        if "] " in item:
            item = item.split("] ", 1)[1]
        paths.append(item.replace("\\", "/"))
    return paths


def _parse_text_hits(raw: str, *, query: str) -> list[TextHit]:
    hits: list[TextHit] = []
    for line in str(raw or "").splitlines():
        item = line.strip()
        if not item or item.startswith("没有找到") or item.startswith("Search failed"):
            continue
        parts = item.split(":", 3)
        if len(parts) < 4:
            continue
        file, line_number, column, snippet = parts
        try:
            parsed_line = int(line_number)
            parsed_column = int(column)
        except ValueError:
            continue
        hits.append(TextHit(file=file.replace("\\", "/"), line=parsed_line, column=parsed_column, snippet=snippet[:500], query=query))
    return hits


def _git_log_sync(root_dir: Path, queries: tuple[str, ...], max_results: int) -> list[dict[str, str]]:
    cwd = _project_root(root_dir)
    if not (cwd / ".git").exists():
        return []
    results: list[dict[str, str]] = []
    for query in queries:
        command = ["git", "log", "--all", "--max-count", str(max(1, min(max_results, 20))), "--pretty=format:%h%x09%s", "--", "."]
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                timeout=8,
                check=False,
                **utf8_subprocess_text_kwargs(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            return results
        lowered = query.lower()
        for line in (completed.stdout or "").splitlines():
            if lowered and lowered not in line.lower():
                continue
            if "\t" in line:
                commit, subject = line.split("\t", 1)
            else:
                commit, subject = line[:12], line
            results.append({"commit": commit.strip(), "subject": subject.strip(), "query": query})
            if len(results) >= max_results:
                return results
    return results


def _project_root(root_dir: Path) -> Path:
    current = Path(root_dir).resolve()
    if current.name == "backend":
        return current.parent
    if (current / "backend").exists() or (current / ".git").exists():
        return current
    return current.parent


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dedupe_hits(hits: list[TextHit]) -> list[TextHit]:
    seen: set[tuple[str, int, str]] = set()
    result: list[TextHit] = []
    for hit in hits:
        key = (hit.file, hit.line, hit.query)
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
    return result


