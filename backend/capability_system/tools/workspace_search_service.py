from __future__ import annotations

import fnmatch
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from capability_system.tools.workspace_file_service import (
    DEFAULT_EXCLUDED_DIRS,
    DEFAULT_RUNTIME_PRIVATE_PATHS,
    DEFAULT_SEARCH_EXCLUDED_PATHS,
    WorkspaceFileService,
)

_PATH_SEARCH_SCAN_LIMIT = 25000
_PATH_SEARCH_TIME_BUDGET_SECONDS = 5.0
_DEFAULT_READ_WINDOW_CONTEXT_LINES = 12
_KEYWORD_SEARCH_TIME_BUDGET_SECONDS = 8.0
_GENERIC_PATH_TERMS = {
    "api",
    "app",
    "backend",
    "code",
    "context",
    "core",
    "data",
    "file",
    "files",
    "frontend",
    "handler",
    "index",
    "lib",
    "manager",
    "model",
    "models",
    "page",
    "policy",
    "runtime",
    "service",
    "state",
    "system",
    "tool",
    "tools",
    "utils",
}
_LOW_VALUE_CONTENT_TERMS = {
    "about",
    "check",
    "find",
    "locate",
    "please",
    "show",
    "tell",
    "what",
    "where",
    "which",
    "帮我",
    "查找",
    "搜索",
    "检查",
    "一下",
    "哪里",
    "在哪",
    "在哪里",
    "定位",
}


class WorkspaceSearchService:
    """Structured ripgrep-backed workspace content search."""

    def __init__(self, root_dir: str | Path, *, file_service: WorkspaceFileService | None = None) -> None:
        self.files = file_service or WorkspaceFileService(root_dir)

    def search_paths(
        self,
        *,
        query: str,
        roots: list[str] | tuple[str, ...] | None = None,
        limit: int = 20,
        fallback_to_workspace: bool = True,
        include_default_search_excludes: bool | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        capped_limit = max(1, min(int(limit or 20), 100))
        if not normalized_query:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="input_validation",
                    status="error",
                    limit=capped_limit,
                    error="query is required",
                ),
            )
        using_default_roots = not _nonempty(roots)
        use_default_excludes = self._use_default_search_excludes(
            roots,
            include_default_search_excludes,
        )
        safe_roots = self.files.safe_roots(roots, fallback_to_workspace=fallback_to_workspace)
        if not safe_roots:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="input_validation",
                    status="error",
                    limit=capped_limit,
                    error="no safe search roots",
                ),
            )
        matches, path_meta = self._search_path_matches(
            safe_roots=safe_roots,
            query=normalized_query,
            terms=_query_terms(normalized_query),
            limit=capped_limit,
            using_default_roots=use_default_excludes,
        )
        boundary = self._path_search_boundary(
            safe_roots=safe_roots,
            using_default_roots=using_default_roots,
        )
        meta = self._meta(
            backend="python_path_scan",
            status="ok" if matches else "no_match",
            limit=capped_limit,
            matched_count=len(matches),
            truncated=bool(path_meta.get("truncated")),
            searched_roots=list(boundary.get("searched_roots") or []),
        )
        meta.update(path_meta)
        meta.update(boundary)
        meta["used_default_search_excludes"] = bool(use_default_excludes)
        return self._result(
            matches=matches,
            meta=_drop_empty(meta),
        )

    def search_text(
        self,
        *,
        query: str,
        roots: list[str] | tuple[str, ...] | None = None,
        paths: list[str] | tuple[str, ...] | None = None,
        glob: str = "",
        limit: int = 20,
        case_sensitive: bool = False,
        fallback_to_workspace: bool = True,
        include_default_search_excludes: bool | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        capped_limit = max(1, int(limit or 1))
        if not normalized_query:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="input_validation",
                    status="error",
                    limit=capped_limit,
                    error="query is required",
                ),
            )
        requested_paths = _nonempty(paths)
        keyword_terms = _content_query_terms(normalized_query)
        if requested_paths:
            target_paths, path_error = self._resolve_search_paths(requested_paths)
            if path_error:
                return self._result(
                    matches=[],
                    meta=self._meta(
                        backend="input_validation",
                        status="error",
                        limit=capped_limit,
                        error=path_error,
                    ),
                )
            matches = self._search_paths(
                query=normalized_query,
                paths=target_paths,
                glob=str(glob or ""),
                limit=capped_limit,
                case_sensitive=case_sensitive,
            )
            backend = "python_paths"
            strategy = "literal_substring"
            keyword_meta: dict[str, Any] = {}
            if not matches and len(keyword_terms) >= 2:
                matches, keyword_meta = self._keyword_search_text(
                    query=normalized_query,
                    terms=keyword_terms,
                    roots=[path.parent for path in target_paths],
                    paths=target_paths,
                    glob=str(glob or ""),
                    limit=capped_limit,
                    using_default_roots=False,
                    case_sensitive=case_sensitive,
                )
                backend = "python_paths_keyword_ranked"
                strategy = str(keyword_meta.get("strategy") or "keyword_and_bm25_lite")
            return self._result(
                matches=matches,
                meta=self._meta(
                    backend=backend,
                    status="ok" if matches else "no_match",
                    limit=capped_limit,
                    matched_count=len(matches),
                    truncated=_matches_hit_limit(matches, limit=capped_limit, keyword_meta=keyword_meta),
                    searched_roots=[self.files.relative_path(path) for path in target_paths],
                )
                | _drop_empty({"text_search_strategy": strategy, "keyword_search_meta": keyword_meta}),
            )
        safe_roots = self.files.safe_roots(roots, fallback_to_workspace=fallback_to_workspace)
        if not safe_roots:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="input_validation",
                    status="error",
                    limit=capped_limit,
                    error="no safe search roots",
                ),
            )
        use_default_excludes = self._use_default_search_excludes(
            roots,
            include_default_search_excludes,
            glob=str(glob or ""),
        )
        searched_roots = [self.files.relative_path(root) or "." for root in safe_roots]
        args = self._rg_args(
            query=normalized_query,
            roots=safe_roots,
            glob=str(glob or ""),
            limit=capped_limit,
            case_sensitive=case_sensitive,
            using_default_roots=use_default_excludes,
        )
        if self.files.search_root_args_are_workspace_relative(safe_roots):
            try:
                completed = subprocess.run(
                    ["rg", *args],
                    cwd=self.files.workspace_root,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=8.0,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                matches = _parse_rg_matches(_timeout_stdout_text(exc), limit=capped_limit)
                return self._result(
                    matches=matches,
                    meta=self._meta(
                        backend="ripgrep",
                        status="timeout",
                        args=args,
                        limit=capped_limit,
                        matched_count=len(matches),
                        truncated=True,
                        stderr=str(getattr(exc, "stderr", "") or "")[:500],
                        searched_roots=searched_roots,
                    )
                    | {"used_default_search_excludes": bool(use_default_excludes)},
                )
            except FileNotFoundError:
                completed = None
            except PermissionError as exc:
                return self._result(
                    matches=[],
                    meta=self._meta(
                        backend="ripgrep",
                        status="permission_error",
                        args=args,
                        limit=capped_limit,
                        error=str(exc),
                        searched_roots=searched_roots,
                    )
                    | {"used_default_search_excludes": bool(use_default_excludes)},
                )
            except OSError as exc:
                return self._result(
                    matches=[],
                    meta=self._meta(
                        backend="ripgrep",
                        status="error",
                        args=args,
                        limit=capped_limit,
                        error=str(exc),
                        searched_roots=searched_roots,
                    )
                    | {"used_default_search_excludes": bool(use_default_excludes)},
                )
            if completed is not None:
                if completed.returncode not in {0, 1}:
                    matches = _parse_rg_matches(completed.stdout, limit=capped_limit)
                    if matches:
                        return self._result(
                            matches=matches,
                            meta=self._meta(
                                backend="ripgrep_partial",
                                status="ok",
                                args=args,
                                returncode=completed.returncode,
                                limit=capped_limit,
                                matched_count=len(matches),
                                truncated=True,
                                stderr=(completed.stderr or "").strip()[:500],
                                searched_roots=searched_roots,
                            )
                            | {
                                "text_search_strategy": "literal_or_regex_partial",
                                "recovered_from_backend_error": "ripgrep_returncode",
                                "used_default_search_excludes": bool(use_default_excludes),
                            },
                        )
                    matches = self._fallback_search_text(
                        query=normalized_query,
                        roots=safe_roots,
                        glob=str(glob or ""),
                        limit=capped_limit,
                        using_default_roots=use_default_excludes,
                        case_sensitive=case_sensitive,
                    )
                    backend = "python_fallback_after_ripgrep_error"
                    strategy = "literal_substring"
                    keyword_meta: dict[str, Any] = {}
                    if not matches and len(keyword_terms) >= 2:
                        matches, keyword_meta = self._keyword_search_text(
                            query=normalized_query,
                            terms=keyword_terms,
                            roots=safe_roots,
                            glob=str(glob or ""),
                            limit=capped_limit,
                            using_default_roots=use_default_excludes,
                            case_sensitive=case_sensitive,
                        )
                        backend = "python_keyword_ranked_after_ripgrep_error"
                        strategy = str(keyword_meta.get("strategy") or "keyword_and_bm25_lite")
                    return self._result(
                        matches=matches,
                        meta=self._meta(
                            backend=backend,
                            status="ok" if matches else "no_match",
                            args=args,
                            returncode=completed.returncode,
                            limit=capped_limit,
                            matched_count=len(matches),
                            truncated=_matches_hit_limit(matches, limit=capped_limit, keyword_meta=keyword_meta),
                            stderr=(completed.stderr or "").strip()[:500],
                            searched_roots=searched_roots,
                        )
                        | _drop_empty(
                            {
                                "text_search_strategy": strategy,
                                "keyword_search_meta": keyword_meta,
                                "recovered_from_backend_error": "ripgrep_returncode",
                                "used_default_search_excludes": use_default_excludes,
                            }
                        ),
                    )
                matches = _parse_rg_matches(completed.stdout, limit=capped_limit)
                backend = "ripgrep"
                strategy = "literal_or_regex"
                keyword_meta: dict[str, Any] = {}
                if not matches and len(keyword_terms) >= 2:
                    matches, keyword_meta = self._keyword_search_text(
                        query=normalized_query,
                        terms=keyword_terms,
                        roots=safe_roots,
                        glob=str(glob or ""),
                        limit=capped_limit,
                        using_default_roots=use_default_excludes,
                        case_sensitive=case_sensitive,
                    )
                    backend = "python_keyword_ranked"
                    strategy = str(keyword_meta.get("strategy") or "keyword_and_bm25_lite")
                return self._result(
                    matches=matches,
                    meta=self._meta(
                        backend=backend,
                        status="ok" if matches else "no_match",
                        args=args,
                        returncode=completed.returncode,
                        limit=capped_limit,
                        matched_count=len(matches),
                        truncated=_matches_hit_limit(matches, limit=capped_limit, keyword_meta=keyword_meta),
                        stderr=(completed.stderr or "").strip()[:500],
                        searched_roots=searched_roots,
                    )
                    | _drop_empty({"text_search_strategy": strategy, "keyword_search_meta": keyword_meta, "used_default_search_excludes": use_default_excludes}),
                )
        matches = self._fallback_search_text(
            query=normalized_query,
            roots=safe_roots,
            glob=str(glob or ""),
            limit=capped_limit,
            using_default_roots=use_default_excludes,
            case_sensitive=case_sensitive,
        )
        backend = "python_fallback"
        strategy = "literal_substring"
        keyword_meta: dict[str, Any] = {}
        if not matches and len(keyword_terms) >= 2:
            matches, keyword_meta = self._keyword_search_text(
                query=normalized_query,
                terms=keyword_terms,
                roots=safe_roots,
                glob=str(glob or ""),
                limit=capped_limit,
                using_default_roots=use_default_excludes,
                case_sensitive=case_sensitive,
            )
            backend = "python_keyword_ranked"
            strategy = str(keyword_meta.get("strategy") or "keyword_and_bm25_lite")
        return self._result(
            matches=matches,
            meta=self._meta(
                backend=backend,
                status="ok" if matches else "no_match",
                limit=capped_limit,
                matched_count=len(matches),
                truncated=_matches_hit_limit(matches, limit=capped_limit, keyword_meta=keyword_meta),
                searched_roots=searched_roots,
            )
            | _drop_empty({"text_search_strategy": strategy, "keyword_search_meta": keyword_meta, "used_default_search_excludes": use_default_excludes}),
        )

    def _use_default_search_excludes(
        self,
        roots: list[str] | tuple[str, ...] | None,
        include_default_search_excludes: bool | None,
        *,
        glob: str = "",
    ) -> bool:
        if include_default_search_excludes is not None:
            return bool(include_default_search_excludes)
        explicit_roots = _nonempty(roots)
        if not explicit_roots:
            return True
        if str(glob or "").strip() and _targets_default_excluded_path(str(glob or "")):
            return False
        return not any(self._root_targets_default_excluded_path(root) for root in explicit_roots)

    def _root_targets_default_excluded_path(self, root: str) -> bool:
        raw = str(root or "").replace("\\", "/").strip().strip("/")
        if not raw:
            return False
        try:
            resolved = self.files.resolve(raw, require_path=True)
        except ValueError:
            return _targets_default_excluded_path(raw)
        relative = self.files.relative_path(resolved).replace("\\", "/").strip("/")
        return _targets_default_excluded_path(relative or raw)

    def glob_paths(
        self,
        *,
        pattern: str,
        limit: int = 80,
    ) -> dict[str, Any]:
        normalized_pattern = str(pattern or "").replace("\\", "/").strip()
        capped_limit = max(1, min(int(limit or 80), 300))
        if not normalized_pattern:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="input_validation",
                    status="error",
                    limit=capped_limit,
                    error="pattern is required",
                ),
            )
        try:
            searched_roots = self.files.glob_search_roots(normalized_pattern)
        except ValueError as exc:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="workspace_glob",
                    status="error",
                    limit=capped_limit,
                    error=str(exc) or "invalid pattern",
                ),
            )
        rg_result = self._rg_glob_paths(pattern=normalized_pattern, limit=capped_limit)
        if rg_result is not None:
            paths, rg_meta = rg_result
            return self._result(
                matches=[{"path": path} for path in paths],
                meta=self._meta(
                    backend="ripgrep_files",
                    status="ok" if paths else "no_match",
                    limit=capped_limit,
                    args=list(rg_meta.get("args") or []),
                    returncode=rg_meta.get("returncode") if isinstance(rg_meta.get("returncode"), int) else None,
                    matched_count=len(paths),
                    truncated=len(paths) >= capped_limit,
                    stderr=str(rg_meta.get("stderr") or ""),
                    searched_roots=searched_roots,
                ),
            )
        try:
            paths = self.files.glob_paths(normalized_pattern, max_results=capped_limit)
        except ValueError as exc:
            return self._result(
                matches=[],
                meta=self._meta(
                    backend="workspace_glob",
                    status="error",
                    limit=capped_limit,
                    error=str(exc) or "invalid pattern",
                ),
            )
        return self._result(
            matches=[{"path": path} for path in paths],
            meta=self._meta(
                backend="python_glob_fallback",
                status="ok" if paths else "no_match",
                limit=capped_limit,
                matched_count=len(paths),
                truncated=len(paths) >= capped_limit,
                searched_roots=searched_roots,
            ),
        )

    def _rg_glob_paths(self, *, pattern: str, limit: int) -> tuple[list[str], dict[str, Any]] | None:
        args = ["--files", "--hidden", "--no-ignore-parent"]
        _extend_rg_exclude_globs(
            args,
            include_default_search_excludes=not _targets_default_excluded_path(pattern),
        )
        args.extend(["--glob", pattern])
        try:
            completed = subprocess.run(
                ["rg", *args],
                cwd=self.files.workspace_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=8.0,
                check=False,
            )
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError):
            return None
        paths = [
            str(line or "").strip().replace("\\", "/")
            for line in str(completed.stdout or "").splitlines()
            if str(line or "").strip()
        ]
        if completed.returncode not in {0, 1} and not paths:
            return None
        return sorted(dict.fromkeys(paths))[: max(1, int(limit or 1))], {
            "args": args,
            "returncode": completed.returncode,
            "stderr": (completed.stderr or "").strip()[:500],
        }

    def _path_search_boundary(
        self,
        *,
        safe_roots: list[Path],
        using_default_roots: bool,
    ) -> dict[str, Any]:
        workspace_root = self.files.workspace_root.resolve()
        searched_roots = [self.files.relative_path(root) or "." for root in safe_roots]
        omitted_workspace_root = using_default_roots and all(root.resolve() != workspace_root for root in safe_roots)
        return {
            "searched_roots": searched_roots,
            "used_default_roots": bool(using_default_roots),
            "workspace_root": str(workspace_root),
            "omitted_workspace_root": bool(omitted_workspace_root),
        }

    def _search_path_matches(
        self,
        *,
        safe_roots: list[Path],
        query: str,
        terms: list[str],
        limit: int,
        using_default_roots: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        scanned = 0
        deadline = time.monotonic() + _PATH_SEARCH_TIME_BUDGET_SECONDS
        for root in safe_roots:
            for directory, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    dirname
                    for dirname in dirnames
                    if not self.files.is_excluded(
                        Path(directory) / dirname,
                        include_default_search_excludes=using_default_roots,
                    )
                ]
                for filename in filenames:
                    path = Path(directory) / filename
                    if not path.is_file() or self.files.is_excluded(
                        path,
                        include_default_search_excludes=using_default_roots,
                    ):
                        continue
                    scanned += 1
                    rel = self.files.relative_path(path)
                    score_payload = _path_match_score(rel, query=query, terms=terms)
                    if rel in seen or not score_payload:
                        if scanned >= _PATH_SEARCH_SCAN_LIMIT or time.monotonic() >= deadline:
                            return _rank_path_candidates(candidates, limit=limit), _path_search_meta(
                                scanned=scanned,
                                truncated=True,
                                candidate_count=len(candidates),
                            )
                        continue
                    seen.add(rel)
                    candidates.append({"path": rel, **score_payload})
                    if scanned >= _PATH_SEARCH_SCAN_LIMIT or time.monotonic() >= deadline:
                        return _rank_path_candidates(candidates, limit=limit), _path_search_meta(
                            scanned=scanned,
                            truncated=True,
                            candidate_count=len(candidates),
                        )
        return _rank_path_candidates(candidates, limit=limit), _path_search_meta(
            scanned=scanned,
            truncated=False,
            candidate_count=len(candidates),
        )

    def _rg_args(
        self,
        *,
        query: str,
        roots: list[Path],
        glob: str,
        limit: int,
        case_sensitive: bool,
        using_default_roots: bool,
    ) -> list[str]:
        args = [
            "--line-number",
            "--column",
            "--hidden",
            "--no-ignore-parent",
            "--no-heading",
            "--color",
            "never",
            "--max-count",
            str(max(1, int(limit or 1))),
        ]
        if not bool(case_sensitive):
            args.append("--ignore-case")
        _extend_rg_exclude_globs(args, include_default_search_excludes=using_default_roots)
        if str(glob or "").strip():
            args.extend(["--glob", str(glob).strip()])
        args.append(query)
        args.extend(self.files.relative_path(root) or "." for root in roots)
        return args

    def _resolve_search_paths(self, paths: list[str]) -> tuple[list[Path], str]:
        resolved: list[Path] = []
        seen: set[Path] = set()
        for item in paths:
            try:
                target = self.files.resolve(item, require_path=True)
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

    def _search_paths(
        self,
        *,
        query: str,
        paths: list[Path],
        glob: str,
        limit: int,
        case_sensitive: bool,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        pattern = str(glob or "").strip()
        query_cmp = query if case_sensitive else query.lower()
        for path in paths:
            if len(matches) >= limit:
                return matches
            rel = self.files.relative_path(path)
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
                matches.append({"path": rel, "line": line_number, "column": column, "text": line[:240]})
                if len(matches) >= limit:
                    return matches
        return matches

    def _fallback_search_text(
        self,
        *,
        query: str,
        roots: list[Path],
        glob: str,
        limit: int,
        using_default_roots: bool,
        case_sensitive: bool,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        pattern = glob.strip() or "*"
        query_cmp = query if case_sensitive else query.lower()
        for root in roots:
            for path in root.rglob(pattern):
                if len(matches) >= limit:
                    return matches
                if not path.is_file() or self.files.is_excluded(
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
                    column = line_cmp.find(query_cmp) + 1
                    if column <= 0:
                        continue
                    matches.append({"path": self.files.relative_path(path), "line": line_number, "column": column, "text": line[:240]})
                    break
        return matches

    def _keyword_search_text(
        self,
        *,
        query: str,
        terms: list[str],
        roots: list[Path],
        glob: str,
        limit: int,
        using_default_roots: bool,
        case_sensitive: bool,
        paths: list[Path] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized_terms = _cross_search_terms(query=query, terms=terms)
        if len(normalized_terms) < 2:
            return [], {"strategy": "keyword_cross_and_bm25_lite", "reason": "insufficient_keyword_terms"}
        prefilter_meta: dict[str, Any] = {}
        if paths:
            candidate_files = list(paths or [])
        else:
            candidate_files, prefilter_meta = self._keyword_prefilter_files(
                terms=normalized_terms,
                roots=roots,
                glob=glob,
                using_default_roots=using_default_roots,
                case_sensitive=case_sensitive,
            )
            if not candidate_files and not bool(prefilter_meta.get("complete_no_match")):
                candidate_files = self._iter_search_files(
                    roots=roots,
                    glob=glob,
                    using_default_roots=using_default_roots,
                )
        scanned = 0
        docs: list[dict[str, Any]] = []
        doc_freq = {term: 0 for term in normalized_terms}
        deadline = time.monotonic() + _KEYWORD_SEARCH_TIME_BUDGET_SECONDS
        for path in candidate_files:
            if time.monotonic() >= deadline:
                break
            if not path.is_file() or self.files.is_excluded(path, include_default_search_excludes=using_default_roots):
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            haystack = text if case_sensitive else text.lower()
            term_counts: dict[str, int] = {}
            for term in normalized_terms:
                needle = term if case_sensitive else term.lower()
                count = haystack.count(needle)
                if count > 0:
                    term_counts[term] = count
            if set(term_counts) != set(normalized_terms):
                continue
            for term in term_counts:
                doc_freq[term] += 1
            lines = text.splitlines()
            best_line, line_score, matched_line_terms = _best_keyword_anchor(
                lines,
                terms=normalized_terms,
                case_sensitive=case_sensitive,
            )
            docs.append(
                {
                    "path": path,
                    "relative_path": self.files.relative_path(path),
                    "line": best_line,
                    "line_score": line_score,
                    "matched_line_terms": matched_line_terms,
                    "term_counts": term_counts,
                    "doc_len": max(1, len(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text))),
                    "lines": lines,
                }
            )
        if not docs:
            return [], {
                "strategy": "keyword_cross_and_bm25_lite",
                "scanned_documents": scanned,
                "candidate_file_count": len(candidate_files),
                "keyword_terms": normalized_terms,
                "prefilter": prefilter_meta,
                "truncated": scanned < len(candidate_files) or len(candidate_files) >= _PATH_SEARCH_SCAN_LIMIT,
            }
        avg_doc_len = sum(int(doc["doc_len"]) for doc in docs) / max(1, len(docs))
        ranked: list[dict[str, Any]] = []
        for doc in docs:
            score = _bm25_lite_score(
                term_counts=dict(doc["term_counts"]),
                doc_freq=doc_freq,
                doc_count=max(scanned, len(docs)),
                doc_len=int(doc["doc_len"]),
                avg_doc_len=avg_doc_len,
            )
            rel = str(doc["relative_path"])
            path_score = _path_match_score(rel, query=query, terms=normalized_terms)
            if path_score:
                score += min(2.5, float(path_score.get("score") or 0.0) / 120.0)
            score += float(doc["line_score"]) * 0.15
            line_no = max(1, int(doc["line"] or 1))
            line_text = str(doc["lines"][line_no - 1] if line_no - 1 < len(doc["lines"]) else "")[:240]
            ranked.append(
                {
                    "path": rel,
                    "line": line_no,
                    "column": _first_keyword_column(line_text, normalized_terms, case_sensitive=case_sensitive),
                    "text": line_text,
                    "score": round(score, 4),
                    "match_reason": "keyword_cross_and_bm25_lite",
                    "matched_terms": normalized_terms,
                }
            )
        ranked.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("path") or ""), int(item.get("line") or 0)))
        return ranked[: max(1, int(limit or 1))], {
            "strategy": "keyword_cross_and_bm25_lite",
            "scanned_documents": scanned,
            "candidate_file_count": len(candidate_files),
            "candidate_documents": len(docs),
            "keyword_terms": normalized_terms,
            "prefilter": prefilter_meta,
            "doc_freq": doc_freq,
            "truncated": scanned < len(candidate_files) or len(candidate_files) >= _PATH_SEARCH_SCAN_LIMIT,
        }

    def _iter_search_files(
        self,
        *,
        roots: list[Path],
        glob: str,
        using_default_roots: bool,
    ) -> list[Path]:
        pattern = str(glob or "").strip() or "*"
        result: list[Path] = []
        for root in list(roots or []):
            for path in root.rglob(pattern):
                if not path.is_file() or self.files.is_excluded(
                    path,
                    include_default_search_excludes=using_default_roots,
                ):
                    continue
                result.append(path)
                if len(result) >= _PATH_SEARCH_SCAN_LIMIT:
                    return result
        return result

    def _keyword_prefilter_files(
        self,
        *,
        terms: list[str],
        roots: list[Path],
        glob: str,
        using_default_roots: bool,
        case_sensitive: bool,
    ) -> tuple[list[Path], dict[str, Any]]:
        if not self.files.search_root_args_are_workspace_relative(roots):
            return [], {"backend": "rg_files_with_matches", "status": "skipped_external_roots"}
        selected_terms = _keyword_prefilter_terms(terms)
        if len(selected_terms) < 2:
            return [], {"backend": "rg_files_with_matches", "status": "skipped_insufficient_terms"}
        intersection: set[str] | None = None
        term_counts: dict[str, int] = {}
        for term in selected_terms:
            paths, meta = self._rg_files_with_match(
                term=term,
                roots=roots,
                glob=glob,
                using_default_roots=using_default_roots,
                case_sensitive=case_sensitive,
            )
            status = str(meta.get("status") or "")
            if status not in {"ok", "no_match"}:
                return [], {
                    "backend": "rg_files_with_matches",
                    "status": "fallback_after_prefilter_" + status,
                    "terms": selected_terms,
                    "failed_term": term,
                    "error": meta.get("error") or meta.get("stderr") or "",
                }
            current = set(paths)
            term_counts[term] = len(current)
            intersection = current if intersection is None else intersection & current
            if not intersection:
                return [], {
                    "backend": "rg_files_with_matches",
                    "status": "no_match",
                    "complete_no_match": True,
                    "terms": selected_terms,
                    "term_file_counts": term_counts,
                    "candidate_file_count": 0,
                }
        relative_paths = sorted(intersection or set())[:_PATH_SEARCH_SCAN_LIMIT]
        candidate_files = [
            self.files.workspace_root / rel
            for rel in relative_paths
            if rel and not self.files.is_excluded(self.files.workspace_root / rel, include_default_search_excludes=using_default_roots)
        ]
        return candidate_files, {
            "backend": "rg_files_with_matches",
            "status": "ok",
            "terms": selected_terms,
            "term_file_counts": term_counts,
            "candidate_file_count": len(candidate_files),
            "truncated": len(relative_paths) >= _PATH_SEARCH_SCAN_LIMIT,
        }

    def _rg_files_with_match(
        self,
        *,
        term: str,
        roots: list[Path],
        glob: str,
        using_default_roots: bool,
        case_sensitive: bool,
    ) -> tuple[list[str], dict[str, Any]]:
        args = [
            "--files-with-matches",
            "--fixed-strings",
            "--hidden",
            "--no-ignore-parent",
            "--color",
            "never",
        ]
        if not bool(case_sensitive):
            args.append("--ignore-case")
        _extend_rg_exclude_globs(args, include_default_search_excludes=using_default_roots)
        if str(glob or "").strip():
            args.extend(["--glob", str(glob).strip()])
        args.append(str(term or ""))
        args.extend(self.files.relative_path(root) or "." for root in roots)
        try:
            completed = subprocess.run(
                ["rg", *args],
                cwd=self.files.workspace_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4.0,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return [], {"status": "timeout", "stderr": str(getattr(exc, "stderr", "") or "")[:500], "args": args}
        except FileNotFoundError:
            return [], {"status": "missing_rg", "args": args}
        except (PermissionError, OSError) as exc:
            return [], {"status": "error", "error": str(exc), "args": args}
        if completed.returncode not in {0, 1}:
            return [], {
                "status": "error",
                "returncode": completed.returncode,
                "stderr": (completed.stderr or "").strip()[:500],
                "args": args,
            }
        paths = [
            str(line or "").strip().replace("\\", "/")
            for line in str(completed.stdout or "").splitlines()
            if str(line or "").strip()
        ]
        return paths[:_PATH_SEARCH_SCAN_LIMIT], {
            "status": "ok" if paths else "no_match",
            "returncode": completed.returncode,
            "matched_count": len(paths),
            "args": args,
        }

    def _result(self, *, matches: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
        normalized_matches = [_with_recommended_read_window(dict(item)) for item in list(matches or []) if isinstance(item, dict)]
        payload: dict[str, Any] = {
            "matches": normalized_matches,
            "search_meta": dict(meta or {}),
        }
        matched_paths = _matched_paths(normalized_matches)
        if matched_paths:
            payload["matched_paths"] = matched_paths
        read_windows = _recommended_read_windows(normalized_matches)
        if read_windows:
            payload["recommended_read_windows"] = read_windows
        return payload

    def _meta(
        self,
        *,
        backend: str,
        status: str,
        limit: int,
        args: list[str] | None = None,
        returncode: int | None = None,
        matched_count: int = 0,
        truncated: bool = False,
        stderr: str = "",
        error: str = "",
        searched_roots: list[str] | None = None,
    ) -> dict[str, Any]:
        return _drop_empty(
            {
                "backend": str(backend or ""),
                "status": str(status or ""),
                "returncode": returncode,
                "matched_count": int(matched_count or 0),
                "limit": int(limit or 0),
                "truncated": bool(truncated),
                "has_more": bool(truncated),
                "searched_roots": list(searched_roots or []),
                "rg_args": list(args or [])[:80],
                "stderr": str(stderr or ""),
                "error": str(error or ""),
                "authority": "capability_system.tools.workspace_search_service",
            }
        )


def _nonempty(values: list[str] | tuple[str, ...] | str | None) -> list[str]:
    raw_values = [values] if isinstance(values, str) else list(values or [])
    return [str(item or "").strip() for item in raw_values if str(item or "").strip()]


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
        for part in _identifier_parts(term):
            if part and part not in seen:
                seen.add(part)
                deduped.append(part)
    return deduped


def _content_query_terms(query: str) -> list[str]:
    normalized = str(query or "").strip()
    raw_terms = re.findall(r"[A-Za-z0-9_.\-\u4e00-\u9fff]+", normalized)
    terms: list[str] = []
    for raw in raw_terms:
        item = raw.lower().strip("._-")
        if len(item) < 2:
            continue
        if item in {
            "and",
            "for",
            "from",
            "the",
            "with",
            "文件",
            "查找",
            "搜索",
            "帮我",
            "找到",
            "打开",
            "读取",
            "一下",
            "路径",
        }:
            continue
        terms.append(item)
        terms.extend(_identifier_parts(item))
    return _dedupe_terms(terms)


def _path_matches_query(path: str, *, query: str, terms: list[str]) -> bool:
    if _path_match_score(path, query=query, terms=terms):
        return True
    raw_query = str(query or "").strip().replace("\\", "/").lower()
    if not any(ch in raw_query for ch in "*?[]"):
        return False
    normalized_path = str(path or "").replace("\\", "/").lower()
    return fnmatch.fnmatch(normalized_path, raw_query) or fnmatch.fnmatch(Path(normalized_path).name, raw_query)


def _path_match_score(path: str, *, query: str, terms: list[str]) -> dict[str, Any]:
    normalized_path = str(path or "").replace("\\", "/").lower()
    basename = Path(normalized_path).name
    stem = Path(basename).stem
    raw_query = str(query or "").strip().replace("\\", "/").lower()
    compact_path = _compact_identifier(normalized_path)
    compact_basename = _compact_identifier(basename)
    compact_stem = _compact_identifier(stem)
    compact_query = _compact_identifier(raw_query)
    glob_query = bool(any(ch in raw_query for ch in "*?[]"))
    if glob_query and (fnmatch.fnmatch(normalized_path, raw_query) or fnmatch.fnmatch(basename, raw_query)):
        return {
            "score": 120.0,
            "match_reason": "glob_pattern_match",
            "matched_terms": [raw_query],
        }
    expanded_terms = _dedupe_terms([*list(terms or []), *_identifier_parts(raw_query)])
    important_terms = [term for term in expanded_terms if term not in _GENERIC_PATH_TERMS]
    matched_important = [term for term in important_terms if _term_matches_path(term, normalized_path, compact_path)]
    matched_generic = [term for term in expanded_terms if term in _GENERIC_PATH_TERMS and _term_matches_path(term, normalized_path, compact_path)]
    basename_hits = [term for term in matched_important if _term_matches_path(term, basename, compact_basename)]
    compact_query_match = bool(compact_query and len(compact_query) >= 4 and compact_query in compact_path)
    phrase_match = bool(raw_query and raw_query in normalized_path)
    if important_terms and not matched_important and not compact_query_match and not phrase_match:
        return {}
    if not important_terms and not matched_generic and not compact_query_match and not phrase_match:
        return {}
    if _requires_strict_identifier_path_match(raw_query, compact_query) and not compact_query_match and not phrase_match:
        required_hits = min(3, len(set(important_terms)))
        if len(set(matched_important)) < required_hits or not basename_hits:
            return {}

    score = 0.0
    reasons: list[str] = []
    if phrase_match:
        score += 100.0
        reasons.append("full_phrase_path_match")
    if compact_query_match:
        score += 92.0
        reasons.append("compact_identifier_path_match")
        if compact_query in compact_basename:
            score += 18.0
            reasons.append("compact_identifier_basename_match")
    if compact_query and compact_query == compact_stem:
        score += 110.0
        reasons.append("exact_stem_identifier_match")
    if important_terms:
        if len(matched_important) == len(set(important_terms)):
            score += 42.0
            reasons.append("all_important_terms_matched")
        score += min(36.0, 12.0 * len(matched_important))
    if basename_hits:
        score += min(36.0, 18.0 * len(basename_hits))
        reasons.append("basename_term_match")
    if matched_generic:
        score += min(6.0, 2.0 * len(matched_generic))
        reasons.append("generic_term_match")
    if normalized_path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".yaml", ".yml")):
        score += 2.0
    if any(part in normalized_path for part in ("/__pycache__/", "/node_modules/", "/.next/", "/dist/", "/build/")):
        score -= 60.0
        reasons.append("generated_path_penalty")
    if important_terms and matched_important and len(matched_important) < len(set(important_terms)):
        reasons.append("partial_important_term_match")
    return {
        "score": round(max(0.0, score), 3),
        "match_reason": "; ".join(reasons[:5]) or "path_term_match",
        "matched_terms": matched_important or matched_generic,
    } if score > 0 else {}


def _rank_path_candidates(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(item) for item in list(candidates or []) if isinstance(item, dict) and str(item.get("path") or "")),
        key=lambda item: (-float(item.get("score") or 0.0), str(item.get("path") or "")),
    )
    if ordered and float(ordered[0].get("score") or 0.0) >= 100.0:
        top_score = float(ordered[0].get("score") or 0.0)
        ordered = [
            item
            for item in ordered
            if float(item.get("score") or 0.0) >= max(50.0, top_score * 0.35)
        ]
    return ordered[: max(1, int(limit or 1))]


def _path_search_meta(*, scanned: int, truncated: bool, candidate_count: int = 0) -> dict[str, Any]:
    return {
        "scanned_paths": int(scanned),
        "candidate_count": int(candidate_count or 0),
        "truncated": bool(truncated),
        "scan_limit": _PATH_SEARCH_SCAN_LIMIT,
        "time_budget_seconds": _PATH_SEARCH_TIME_BUDGET_SECONDS,
        "scoring_policy": "phrase_identifier_basename_terms_with_generic_term_penalty",
    }


def _targets_default_excluded_path(pattern: str) -> bool:
    normalized = str(pattern or "").replace("\\", "/").strip("/").lower()
    if not normalized:
        return False
    return any(
        normalized == excluded or normalized.startswith(f"{excluded}/")
        for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS
    )


def _extend_rg_exclude_globs(args: list[str], *, include_default_search_excludes: bool) -> None:
    for excluded in DEFAULT_EXCLUDED_DIRS:
        normalized = str(excluded or "").replace("\\", "/").strip("/")
        if not normalized:
            continue
        args.extend(["--glob", f"!**/{normalized}", "--glob", f"!**/{normalized}/**"])
    for excluded in DEFAULT_RUNTIME_PRIVATE_PATHS:
        normalized = str(excluded or "").replace("\\", "/").strip("/")
        if normalized:
            args.extend(["--glob", f"!{normalized}"])
    if include_default_search_excludes:
        for excluded in DEFAULT_SEARCH_EXCLUDED_PATHS:
            normalized = str(excluded or "").replace("\\", "/").strip("/")
            if normalized:
                args.extend(["--glob", f"!{normalized}", "--glob", f"!{normalized}/**"])


def _parse_rg_match(line: str) -> dict[str, Any]:
    parts = str(line or "").replace("\\", "/").split(":", 3)
    if len(parts) < 4:
        return {}
    path, line_no, column, text = parts
    try:
        parsed_line = int(line_no)
        parsed_column = int(column)
    except ValueError:
        return {}
    return {"path": path, "line": parsed_line, "column": parsed_column, "text": text[:240]}


def _parse_rg_matches(stdout: Any, *, limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for raw in str(stdout or "").splitlines():
        item = _parse_rg_match(raw)
        if item:
            matches.append(item)
            if len(matches) >= max(1, int(limit or 1)):
                break
    return matches


def _timeout_stdout_text(exc: subprocess.TimeoutExpired) -> str:
    stdout = getattr(exc, "stdout", "") or ""
    if isinstance(stdout, bytes):
        return stdout.decode("utf-8", errors="replace")
    return str(stdout or "")


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in ("", None, [], {})}


def _matches_hit_limit(matches: list[dict[str, Any]], *, limit: int, keyword_meta: dict[str, Any] | None = None) -> bool:
    meta = dict(keyword_meta or {})
    if meta:
        candidate_documents = _safe_int(meta.get("candidate_documents"))
        return bool(meta.get("truncated")) or (candidate_documents > max(1, int(limit or 1)))
    return len(list(matches or [])) >= max(1, int(limit or 1))


def _cross_search_terms(*, query: str, terms: list[str]) -> list[str]:
    raw_query = str(query or "").strip().lower()
    compact_query = _compact_identifier(raw_query)
    if _requires_strict_identifier_path_match(raw_query, compact_query):
        return _dedupe_terms([raw_query, *_identifier_parts(raw_query)])
    filtered = _dedupe_terms([term for term in terms if term not in _LOW_VALUE_CONTENT_TERMS])
    if len(filtered) <= 6:
        return filtered
    high_value = [
        term
        for term in filtered
        if len(term) >= 5 or "_" in term or "." in term or "-" in term
    ]
    if len(high_value) >= 2:
        return _dedupe_terms(high_value[:6])
    return filtered[:6]


def _keyword_prefilter_terms(terms: list[str]) -> list[str]:
    candidates = [
        str(term or "").strip().lower()
        for term in list(terms or [])
        if str(term or "").strip().lower() not in _LOW_VALUE_CONTENT_TERMS
    ]
    candidates = _dedupe_terms(candidates)
    if len(candidates) <= 3:
        return candidates
    high_signal = [
        term
        for term in candidates
        if len(term) >= 5 or "_" in term or "." in term or "-" in term
    ]
    selected = high_signal if len(high_signal) >= 2 else candidates
    selected.sort(key=lambda item: (-len(_compact_identifier(item)), item))
    return selected[:3]


def _best_keyword_anchor(
    lines: list[str],
    *,
    terms: list[str],
    case_sensitive: bool,
) -> tuple[int, float, list[str]]:
    records: list[tuple[int, set[str]]] = []
    normalized_terms = _dedupe_terms(terms)
    for index, line in enumerate(list(lines or []), start=1):
        haystack = line if case_sensitive else line.lower()
        matched = {
            term
            for term in normalized_terms
            if (term if case_sensitive else term.lower()) in haystack
        }
        if matched:
            records.append((index, matched))
    if not records:
        return _best_keyword_line(lines, terms=normalized_terms, case_sensitive=case_sensitive)

    required = set(normalized_terms)
    best: tuple[int, int, int, int, set[str]] | None = None
    for start_index, (start_line, start_terms) in enumerate(records):
        covered = set(start_terms)
        if covered >= required:
            best = _better_keyword_span(best, start_line, start_line, start_line, covered)
            continue
        for end_line, end_terms in records[start_index + 1 :]:
            covered.update(end_terms)
            if not covered >= required:
                continue
            anchor = _keyword_anchor_line(records[start_index:], start_line=start_line, end_line=end_line)
            best = _better_keyword_span(best, start_line, end_line, anchor, covered)
            break
    if best is None:
        return _best_keyword_line(lines, terms=normalized_terms, case_sensitive=case_sensitive)

    start_line, end_line, anchor, _, covered_terms = best
    span = max(0, end_line - start_line)
    score = 36.0 + (10.0 * len(covered_terms)) - min(28.0, float(span) * 1.8)
    anchor_terms = next((terms for line, terms in records if line == anchor), covered_terms)
    return anchor, max(score, 1.0), sorted(anchor_terms)


def _better_keyword_span(
    current: tuple[int, int, int, int, set[str]] | None,
    start_line: int,
    end_line: int,
    anchor_line: int,
    covered_terms: set[str],
) -> tuple[int, int, int, int, set[str]]:
    span = max(0, int(end_line) - int(start_line))
    candidate = (int(start_line), int(end_line), int(anchor_line), span, set(covered_terms))
    if current is None:
        return candidate
    _, _, _, current_span, current_terms = current
    if span < current_span:
        return candidate
    if span == current_span and len(covered_terms) > len(current_terms):
        return candidate
    return current


def _keyword_anchor_line(records: list[tuple[int, set[str]]], *, start_line: int, end_line: int) -> int:
    candidates = [
        (line, terms)
        for line, terms in records
        if int(start_line) <= int(line) <= int(end_line)
    ]
    if not candidates:
        return int(start_line)
    line, _ = max(candidates, key=lambda item: (len(item[1]), -abs(item[0] - ((start_line + end_line) // 2)), -item[0]))
    return int(line)


def _best_keyword_line(
    lines: list[str],
    *,
    terms: list[str],
    case_sensitive: bool,
) -> tuple[int, float, list[str]]:
    best_line = 1
    best_score = 0.0
    best_terms: list[str] = []
    for index, line in enumerate(list(lines or []), start=1):
        haystack = line if case_sensitive else line.lower()
        matched = [
            term
            for term in terms
            if (term if case_sensitive else term.lower()) in haystack
        ]
        if not matched:
            continue
        score = float(len(matched) * 10)
        if len(matched) == len(set(terms)):
            score += 20.0
        stripped = line.strip()
        if re.match(r"^(class|def|async def|function|export\s+(class|function|const|interface)|interface)\b", stripped):
            score += 12.0
        if score > best_score:
            best_line = index
            best_score = score
            best_terms = matched
    return best_line, best_score, best_terms


def _bm25_lite_score(
    *,
    term_counts: dict[str, int],
    doc_freq: dict[str, int],
    doc_count: int,
    doc_len: int,
    avg_doc_len: float,
) -> float:
    k1 = 1.2
    b = 0.75
    length_norm = 1.0 - b + b * (float(doc_len or 1) / max(1.0, float(avg_doc_len or 1.0)))
    score = 0.0
    total_docs = max(1, int(doc_count or 1))
    for term, raw_tf in dict(term_counts or {}).items():
        tf = max(0.0, float(raw_tf or 0.0))
        if tf <= 0:
            continue
        df = max(0.0, float(dict(doc_freq or {}).get(term) or 0.0))
        idf = math.log(1.0 + ((total_docs - df + 0.5) / (df + 0.5)))
        score += idf * ((tf * (k1 + 1.0)) / (tf + (k1 * length_norm)))
    return score


def _first_keyword_column(line: str, terms: list[str], *, case_sensitive: bool) -> int:
    haystack = str(line or "") if case_sensitive else str(line or "").lower()
    best = 0
    for term in list(terms or []):
        needle = str(term or "") if case_sensitive else str(term or "").lower()
        if not needle:
            continue
        index = haystack.find(needle)
        if index >= 0 and (best <= 0 or index + 1 < best):
            best = index + 1
    return max(1, best)


def _identifier_parts(value: str) -> list[str]:
    normalized = str(value or "").replace("\\", "/")
    raw_parts = re.split(r"[/_.:\-\s]+", normalized)
    result: list[str] = []
    for raw in raw_parts:
        for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+|[\u4e00-\u9fff]{2,}", raw):
            lowered = part.lower().strip()
            if len(lowered) >= 2:
                result.append(lowered)
    return result


def _dedupe_terms(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value or "").strip().lower()
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _compact_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _term_matches_path(term: str, normalized_path: str, compact_path: str) -> bool:
    item = str(term or "").strip().lower()
    if not item:
        return False
    if item in normalized_path:
        return True
    compact_term = _compact_identifier(item)
    return bool(compact_term and len(compact_term) >= 3 and compact_term in compact_path)


def _requires_strict_identifier_path_match(raw_query: str, compact_query: str) -> bool:
    query = str(raw_query or "").strip()
    if not query or any(ch.isspace() for ch in query):
        return False
    compact = str(compact_query or "").strip()
    if len(compact) < 12:
        return False
    return bool(re.search(r"[_.:/\\-]", query)) or len(compact) >= 24


def _with_recommended_read_window(match: dict[str, Any]) -> dict[str, Any]:
    payload = dict(match or {})
    path = str(payload.get("path") or "").strip()
    line = _safe_int(payload.get("line"))
    if not path or line <= 0:
        return payload
    start_line = max(1, line - _DEFAULT_READ_WINDOW_CONTEXT_LINES)
    end_line = line + _DEFAULT_READ_WINDOW_CONTEXT_LINES
    payload.setdefault(
        "recommended_read_window",
        {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "line_count": end_line - start_line + 1,
            "match_line": line,
            "read_intent": "search_result_evidence",
            "authority": "capability_system.tools.workspace_search_service",
        },
    )
    return payload


def _recommended_read_windows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for match in matches:
        window = dict(match.get("recommended_read_window") or {}) if isinstance(match, dict) else {}
        if not window:
            continue
        key = (
            str(window.get("path") or ""),
            _safe_int(window.get("start_line")),
            _safe_int(window.get("line_count")),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        windows.append(window)
    return windows


def _matched_paths(matches: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for match in matches:
        path = str(dict(match or {}).get("path") or "").strip()
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
