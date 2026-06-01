from __future__ import annotations

import re
from typing import Iterable

from .models import CodebaseSearchPlan


NOISE_TERMS = {
    "fallback",
    "legacy",
    "compat",
    "compatibility",
    "recover",
    "recovery",
    "intent",
    "classifier",
    "runtime",
    "executor",
    "policy",
    "registry",
}


def build_codebase_search_plan(query: str, *, max_queries: int = 12, include_tests: bool = True) -> CodebaseSearchPlan:
    normalized = str(query or "").strip()
    tokens = _tokens(normalized)
    symbols = _symbols(normalized, tokens)
    roots = _preferred_roots(normalized, include_tests=include_tests)
    path_queries = _dedupe([item for item in tokens if "/" in item or "\\" in item or "." in item])
    text_queries = _dedupe([normalized, *symbols, *[item for item in tokens if item.lower() in NOISE_TERMS or len(item) >= 4]])
    if not text_queries and normalized:
        text_queries = (normalized,)
    text_queries = text_queries[:max_queries]
    symbol_queries = _dedupe(symbols)[:max_queries]
    git_history_queries = tuple(item for item in text_queries if item.lower() in NOISE_TERMS or item in symbol_queries)[: max(1, max_queries // 2)]
    file_globs = _file_globs(normalized, include_tests=include_tests)
    return CodebaseSearchPlan(
        path_queries=tuple(path_queries[:max_queries]),
        text_queries=tuple(text_queries),
        symbol_queries=tuple(symbol_queries),
        git_history_queries=tuple(git_history_queries),
        preferred_roots=tuple(roots),
        file_globs=tuple(file_globs),
    )


def _tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_./\\:-]+|[\u4e00-\u9fff]{2,}", value)


def _symbols(value: str, tokens: Iterable[str]) -> list[str]:
    symbols: list[str] = []
    for token in tokens:
        item = token.strip("`'\".,，。:：;；()[]{}")
        if not item:
            continue
        if re.match(r"^[A-Z][A-Za-z0-9]+(?:[A-Z][A-Za-z0-9]+)*$", item):
            symbols.append(item)
        elif re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{2,}$", item) and ("_" in item or item.lower() in NOISE_TERMS):
            symbols.append(item)
        elif re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", item):
            symbols.append(item)
    dotted = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\b", value)
    symbols.extend(dotted)
    return symbols


def _preferred_roots(value: str, *, include_tests: bool) -> list[str]:
    roots: list[str] = []
    lowered = value.lower().replace("\\", "/")
    for root in ("backend", "frontend", "docs", "storage", "tests"):
        if root in lowered:
            roots.append("backend/tests" if root == "tests" else root)
    if not roots:
        roots.extend(["backend", "frontend", "docs"])
        if include_tests:
            roots.append("backend/tests")
    return _dedupe(roots)


def _file_globs(value: str, *, include_tests: bool) -> list[str]:
    lowered = value.lower()
    globs = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.json", "**/*.md"]
    if "pytest" in lowered or "test" in lowered or "测试" in lowered or "regression" in lowered:
        return ["backend/tests/**/*.py", *globs] if include_tests else globs
    return globs


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


