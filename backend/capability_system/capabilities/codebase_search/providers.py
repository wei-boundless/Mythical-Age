from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from capability_system.tools.tool_units.file_system_tools import GlobPathsTool
from capability_system.tools.tool_units.git_tools import GitLogTool
from capability_system.tools.tool_units.search_files_tool import SearchFilesTool, SearchTextTool


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
        self.git_log_tool = GitLogTool(root_dir)

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
        raw = await self.git_log_tool._arun(max_count=max(1, min(max_results * 4, 50)))
        return _parse_git_log(raw, queries=queries, max_results=max_results)


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


def _parse_git_log(raw: str, *, queries: tuple[str, ...], max_results: int) -> list[dict[str, str]]:
    if str(raw or "").startswith("Git failed"):
        return []
    query_terms = [str(item or "").strip().lower() for item in queries if str(item or "").strip()]
    results: list[dict[str, str]] = []
    for line in str(raw or "").splitlines():
        item = line.strip()
        if not item or item == "(empty)":
            continue
        commit, subject = _split_git_log_line(item)
        if not commit or not subject:
            continue
        matched_query = _matching_query(subject, query_terms)
        if query_terms and not matched_query:
            continue
        results.append({"commit": commit, "subject": subject, "query": matched_query})
        if len(results) >= max_results:
            return results
    return results


def _split_git_log_line(line: str) -> tuple[str, str]:
    parts = line.split(maxsplit=1)
    if len(parts) != 2:
        return "", ""
    return parts[0].strip(), parts[1].strip()


def _matching_query(subject: str, query_terms: list[str]) -> str:
    lowered = subject.lower()
    for query in query_terms:
        if query in lowered:
            return query
    return ""


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _dedupe_hits(hits: list[TextHit]) -> list[TextHit]:
    seen: set[tuple[str, int]] = set()
    result: list[TextHit] = []
    for hit in hits:
        key = (hit.file, hit.line)
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
    return result


