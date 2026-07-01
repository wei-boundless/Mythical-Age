from __future__ import annotations

from pathlib import Path

from capability_system.tools.tool_units.git_tools import GitLogTool
from capability_system.tools.tool_units.python_ast_tools import PythonSymbolSearchTool
from capability_system.tools.workspace_file_service import WorkspaceFileService
from capability_system.tools.workspace_search_service import WorkspaceSearchService
from .models import SearchCandidate


TextHit = SearchCandidate


class CodebaseSearchProviders:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.files = WorkspaceFileService(root_dir)
        self.search_service = WorkspaceSearchService(root_dir, file_service=self.files)
        self.symbol_search_tool = PythonSymbolSearchTool(root_dir)
        self.git_log_tool = GitLogTool(root_dir)
        self.last_path_search_meta: list[dict[str, object]] = []
        self.last_symbol_search_meta: list[dict[str, object]] = []
        self.last_text_search_meta: list[dict[str, object]] = []
        self.last_glob_search_meta: list[dict[str, object]] = []

    async def search_paths(
        self,
        *,
        queries: tuple[str, ...],
        roots: tuple[str, ...],
        max_results: int,
        include_default_search_excludes: bool = False,
    ) -> list[str]:
        path_queries = tuple(str(query or "").strip() for query in queries if str(query or "").strip())
        if not path_queries:
            return []
        found: list[str] = []
        meta: list[dict[str, object]] = []
        per_query = max(1, max_results // max(1, len(path_queries)))
        for query in path_queries:
            result = self.search_service.search_paths(
                query=query,
                roots=list(roots),
                limit=per_query,
                fallback_to_workspace=not bool([item for item in roots if str(item or "").strip()]),
                include_default_search_excludes=include_default_search_excludes,
            )
            matches = [
                str(item.get("path") or "")
                for item in list(result.get("matches") or [])
                if isinstance(item, dict) and str(item.get("path") or "")
            ]
            meta.append(
                {
                    "query": query,
                    **dict(result.get("search_meta") or {}),
                    "match_count": len(matches),
                }
            )
            found.extend(matches)
        self.last_path_search_meta = meta
        return _dedupe(found)[:max_results]

    async def search_symbols(self, *, queries: tuple[str, ...], roots: tuple[str, ...], max_results: int) -> list[TextHit]:
        symbol_queries = tuple(str(query or "").strip() for query in queries if str(query or "").strip())
        if not symbol_queries:
            self.last_symbol_search_meta = []
            return []
        hits: list[TextHit] = []
        meta: list[dict[str, object]] = []
        per_query = max(1, max_results // max(1, len(symbol_queries)))
        for query in symbol_queries:
            raw = await self.symbol_search_tool._arun(
                query=query,
                roots=list(roots),
                max_results=per_query,
            )
            payload = dict(dict(raw or {}).get("structured_payload") or {}).get("tool_result")
            tool_result = dict(payload or {})
            symbols = [dict(item or {}) for item in list(tool_result.get("symbols") or []) if isinstance(item, dict)]
            meta.append(
                {
                    "query": query,
                    "backend": "python_ast_symbol_search",
                    "status": "ok" if bool(tool_result.get("ok", True)) else "error",
                    "matched_count": len(symbols),
                    "limit": per_query,
                    "truncated": bool(tool_result.get("truncated")),
                    "has_more": bool(tool_result.get("truncated")),
                    "searched_roots": list(roots),
                    "authority": "capability_system.capabilities.code_intelligence.python_ast_indexer",
                }
            )
            hits.extend(_symbol_hits_from_payload(symbols, query=query))
        self.last_symbol_search_meta = meta
        return _dedupe_hits(hits)[:max_results]

    async def search_text(
        self,
        *,
        queries: tuple[str, ...],
        roots: tuple[str, ...],
        max_results: int,
        include_default_search_excludes: bool = False,
    ) -> list[TextHit]:
        hits: list[TextHit] = []
        meta: list[dict[str, object]] = []
        query_budgets = _query_budgets(queries, max_results=max_results)
        for query, per_query in query_budgets:
            result = self.search_service.search_text(
                query=query,
                roots=list(roots),
                limit=per_query,
                fallback_to_workspace=not bool([item for item in roots if str(item or "").strip()]),
                include_default_search_excludes=include_default_search_excludes,
            )
            meta.append(
                {
                    "query": query,
                    **dict(result.get("search_meta") or {}),
                    "match_count": len(list(result.get("matches") or [])),
                }
            )
            hits.extend(_text_hits_from_matches(list(result.get("matches") or []), query=query))
        self.last_text_search_meta = meta
        return _dedupe_hits(hits)[:max_results]

    async def glob_paths(self, *, patterns: tuple[str, ...], max_results: int) -> list[str]:
        found: list[str] = []
        meta: list[dict[str, object]] = []
        per_pattern = max(1, max_results // max(1, len(patterns)))
        for pattern in patterns:
            result = self.search_service.glob_paths(pattern=pattern, limit=per_pattern)
            matches = [
                str(item.get("path") or "")
                for item in list(result.get("matches") or [])
                if isinstance(item, dict) and str(item.get("path") or "")
            ]
            meta.append(
                {
                    "pattern": pattern,
                    **dict(result.get("search_meta") or {}),
                    "match_count": len(matches),
                }
            )
            found.extend(matches)
        self.last_glob_search_meta = meta
        return _dedupe(found)[:max_results]

    async def git_log(self, *, queries: tuple[str, ...], max_results: int = 8) -> list[dict[str, str]]:
        raw = await self.git_log_tool._arun(max_count=max(1, min(max_results * 4, 50)))
        return _parse_git_log(raw, queries=queries, max_results=max_results)


def _text_hits_from_matches(matches: list[dict[str, object]], *, query: str) -> list[TextHit]:
    hits: list[TextHit] = []
    for raw in list(matches or []):
        item = dict(raw or {})
        try:
            parsed_line = int(item.get("line") or 0)
            parsed_column = int(item.get("column") or 0)
        except (TypeError, ValueError):
            continue
        file = str(item.get("path") or "").replace("\\", "/")
        if not file or parsed_line <= 0:
            continue
        hits.append(
            TextHit(
                file=file,
                line=parsed_line,
                column=max(1, parsed_column),
                snippet=str(item.get("text") or "")[:500],
                query=query,
                source_layer="text",
                evidence_kind="text_match",
                score=_safe_float(item.get("score")),
                match_reason=str(item.get("match_reason") or ""),
                matched_terms=tuple(str(term) for term in list(item.get("matched_terms") or []) if str(term)),
                recommended_read_window=dict(item.get("recommended_read_window") or {}),
            )
        )
    return hits


def _symbol_hits_from_payload(symbols: list[dict[str, object]], *, query: str) -> list[TextHit]:
    hits: list[TextHit] = []
    for symbol in list(symbols or []):
        path = str(symbol.get("path") or "").replace("\\", "/")
        name = str(symbol.get("name") or "")
        qualname = str(symbol.get("qualname") or name)
        kind = str(symbol.get("kind") or "symbol")
        if not path or not name:
            continue
        try:
            line = int(symbol.get("lineno") or 0)
            column = int(symbol.get("col_offset") or 0) + 1
        except (TypeError, ValueError):
            continue
        if line <= 0:
            continue
        hits.append(
            TextHit(
                file=path,
                line=line,
                column=max(1, column),
                snippet=f"symbol match: {kind} {qualname}",
                query=query,
                source_layer="symbol",
                evidence_kind="symbol_match",
                score=_symbol_match_score(query=query, name=name, qualname=qualname),
                match_reason="python_ast_symbol_search",
                matched_terms=tuple(dict.fromkeys([str(query or ""), name, qualname])),
                recommended_read_window={
                    "path": path,
                    "start_line": line,
                    "end_line": int(symbol.get("end_lineno") or line),
                    "line_count": max(1, int(symbol.get("end_lineno") or line) - line + 1),
                    "match_line": line,
                    "read_intent": "symbol_search_candidate",
                    "authority": "capability_system.capabilities.code_intelligence.python_ast_indexer",
                },
            )
        )
    return hits


def _symbol_match_score(*, query: str, name: str, qualname: str) -> float:
    compact_query = _compact_identifier(query)
    compact_name = _compact_identifier(name)
    compact_qualname = _compact_identifier(qualname)
    if compact_query and compact_query == compact_name:
        return 48.0
    if compact_query and compact_query == compact_qualname:
        return 46.0
    if compact_query and compact_query in compact_qualname:
        return 34.0
    return 18.0


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


def _query_budgets(queries: tuple[str, ...], *, max_results: int) -> list[tuple[str, int]]:
    normalized = tuple(str(query or "").strip() for query in tuple(queries or ()) if str(query or "").strip())
    if not normalized:
        return []
    total = max(1, int(max_results or 1))
    first = normalized[0]
    if len(normalized) == 1:
        return [(first, total)]
    if " " in first:
        first_budget = max(2, min(total, int(total * 0.6)))
        remaining_budget = max(1, total - first_budget)
        per_remaining = max(1, remaining_budget // max(1, len(normalized) - 1))
        return [(first, first_budget), *[(query, per_remaining) for query in normalized[1:]]]
    per_query = max(1, total // len(normalized))
    return [(query, per_query) for query in normalized]


def _safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _compact_identifier(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


