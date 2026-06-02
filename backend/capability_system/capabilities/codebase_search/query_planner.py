from __future__ import annotations

import re
from typing import Iterable

from .models import CodebaseSearchPlan


STOP_TERMS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "please",
    "check",
    "find",
    "where",
    "show",
    "locate",
    "trace",
    "route",
    "routes",
    "record",
    "records",
    "result",
    "results",
    "use",
    "uses",
    "used",
    "using",
    "what",
    "which",
    "that",
    "this",
    "there",
    "wherever",
    "please",
    "tell",
    "about",
    "into",
    "onto",
    "then",
    "than",
    "search",
    "query",
    "file",
    "files",
    "code",
    "source",
    "implementation",
    "帮我",
    "查找",
    "搜索",
    "检查",
    "一下",
    "哪里",
    "在哪",
    "在哪里",
    "定位",
    "追踪",
    "记录",
    "结果",
    "调用",
    "路由",
    "实现",
    "文件",
    "代码",
}


def build_codebase_search_plan(query: str, *, max_queries: int = 12, include_tests: bool = True) -> CodebaseSearchPlan:
    normalized = str(query or "").strip()
    tokens = _tokens(normalized)
    symbols = _symbols(normalized, tokens)
    test_intent = _has_test_intent(normalized)
    doc_intent = _has_doc_intent(normalized)
    roots = _preferred_roots(normalized, include_tests=include_tests)
    path_queries = _dedupe([item for item in tokens if _is_path_query(item)])
    search_terms = [item for item in tokens if _is_search_term(item)]
    high_value_terms = [item for item in search_terms if _is_high_value_term(item)]
    text_queries = _dedupe([*symbols, *high_value_terms, *search_terms])
    if not text_queries and normalized:
        text_queries = (normalized,)
    text_queries = text_queries[:max_queries]
    symbol_queries = _dedupe(symbols)[:max_queries]
    query_terms = _dedupe([*symbol_queries, *path_queries, *search_terms])[:max_queries]
    required_terms = _dedupe([*symbol_queries, *path_queries, *high_value_terms])[:max_queries]
    git_history_queries = _dedupe([*symbol_queries, *path_queries, *[item for item in text_queries if _is_history_query(item)]])[: max(1, max_queries // 2)]
    file_globs = _file_globs(normalized, include_tests=include_tests)
    return CodebaseSearchPlan(
        path_queries=tuple(path_queries[:max_queries]),
        text_queries=tuple(text_queries),
        symbol_queries=tuple(symbol_queries),
        query_terms=tuple(query_terms),
        required_terms=tuple(required_terms),
        git_history_queries=tuple(git_history_queries),
        preferred_roots=tuple(roots),
        file_globs=tuple(file_globs),
        test_intent=test_intent,
        doc_intent=doc_intent,
    )


def _tokens(value: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_./\\:-]+|[\u4e00-\u9fff]{2,}", value)
    return [item for item in (_clean_token(token) for token in raw) if item]


def _symbols(value: str, tokens: Iterable[str]) -> list[str]:
    symbols: list[str] = []
    for token in tokens:
        item = _clean_token(token)
        if not item:
            continue
        if item.lower() in STOP_TERMS:
            continue
        if re.match(r"^[A-Z][A-Za-z0-9]+(?:[A-Z][A-Za-z0-9]+)*$", item):
            symbols.append(item)
        elif re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{2,}$", item) and _looks_like_identifier(item):
            symbols.append(item)
        elif re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", item):
            symbols.append(item)
    dotted = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\b", value)
    symbols.extend(dotted)
    return symbols


def _clean_token(value: str) -> str:
    item = str(value or "").strip().strip("`'\".,，。:：;；()[]{}<>")
    if item.endswith(".") and item.count(".") == 1:
        item = item[:-1]
    return item.strip()


def _looks_like_identifier(value: str) -> bool:
    return "_" in value or "." in value or bool(re.search(r"[A-Z]", value[1:])) or value.isupper()


def _is_path_query(value: str) -> bool:
    item = str(value or "").strip()
    if "/" in item or "\\" in item:
        return True
    if re.search(r"\.(py|ts|tsx|js|jsx|json|md|toml|yaml|yml|sql)$", item, re.IGNORECASE):
        return True
    return False


def _is_search_term(value: str) -> bool:
    item = str(value or "").strip()
    if not item:
        return False
    lowered = item.lower()
    if lowered in STOP_TERMS:
        return False
    if "/" in item or "\\" in item:
        return True
    if re.match(r"^[\u4e00-\u9fff]{2,}$", item):
        return True
    return len(item) >= 4


def _is_high_value_term(value: str) -> bool:
    item = str(value or "").strip()
    if not _is_search_term(item):
        return False
    if _is_path_query(item) or _looks_like_identifier(item):
        return True
    if re.match(r"^[A-Z][A-Za-z0-9]+$", item):
        return True
    if item.lower() in {"router", "runtime", "executor", "profile", "capability", "subagent", "specialist", "harness", "deepsearch", "codebase"}:
        return True
    if re.match(r"^[\u4e00-\u9fff]{2,}$", item):
        return True
    return len(item) >= 8


def _is_history_query(value: str) -> bool:
    item = str(value or "").strip()
    if not item or len(item) > 80:
        return False
    if "/" in item or "\\" in item:
        return True
    return _looks_like_identifier(item) or len(item) >= 6


def _preferred_roots(value: str, *, include_tests: bool) -> list[str]:
    roots: list[str] = []
    lowered = value.lower().replace("\\", "/")
    if any(token in lowered for token in ("harness", "router", "runtime", "executor", "task_run", "subagent", "agentrun", "agent_run")):
        roots.append("backend/harness")
    if any(token in lowered for token in ("capability", "codebase", "deepsearch", "search_agent", "pdf_reader")):
        roots.append("backend/capability_system")
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
    if _has_test_intent(lowered):
        return ["backend/tests/**/*.py", *globs] if include_tests else globs
    return globs


def _has_test_intent(value: str) -> bool:
    lowered = str(value or "").lower()
    return "测试" in lowered or bool(re.search(r"\b(pytest|tests?|regression|spec|fixture)\b", lowered))


def _has_doc_intent(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(token in lowered for token in ("文档", "计划书", "设计书", "方案")) or bool(re.search(r"\b(docs?|readme)\b", lowered))


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


