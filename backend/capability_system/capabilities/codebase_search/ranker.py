from __future__ import annotations

import re
from typing import Any

from .file_slicer import FileSlice
from .models import CodebaseEvidence, CodebaseSearchPlan, SearchCandidate


def rank_codebase_evidence(
    hits: list[SearchCandidate],
    slices: list[FileSlice],
    *,
    limit: int,
    plan: CodebaseSearchPlan | None = None,
    query: str = "",
) -> tuple[CodebaseEvidence, ...]:
    slice_by_key = {(item.file, item.matched_line): item for item in slices}
    context = _ranking_context(plan=plan, query=query)
    evidence: list[CodebaseEvidence] = []
    for hit in hits:
        file_slice = slice_by_key.get((hit.file, hit.line))
        snippet = file_slice.snippet if file_slice else hit.snippet
        evidence_kind = _candidate_evidence_kind(hit, snippet=snippet)
        score, reason = _score(
            hit.file,
            evidence_kind,
            hit.snippet,
            snippet,
            context=context,
            hit_score=float(getattr(hit, "score", 0.0) or 0.0),
            hit_match_reason=str(getattr(hit, "match_reason", "") or ""),
        )
        evidence.append(
            CodebaseEvidence(
                file=hit.file,
                line=hit.line,
                column=hit.column,
                start_line=file_slice.start_line if file_slice else hit.line,
                end_line=file_slice.end_line if file_slice else hit.line,
                symbol=_symbol_from_snippet(hit.snippet),
                evidence_kind=evidence_kind,
                source_layer=str(getattr(hit, "source_layer", "") or "text"),
                search_status=str(getattr(hit, "search_status", "") or "candidate_only"),
                snippet=snippet,
                score=score,
                reason=reason,
                matched_terms=tuple(getattr(hit, "matched_terms", ()) or ()),
            )
        )
    evidence.sort(
        key=lambda item: (
            -item.score,
            -_path_query_filename_priority(item.file, context=context),
            -_evidence_kind_priority(item.evidence_kind),
            -_symbol_filename_priority(item.file, context=context),
            -_path_priority(item.file, context=context),
            item.file,
            item.line,
        )
    )
    return tuple(_diversify_by_file(evidence, limit=limit))


def _candidate_evidence_kind(hit: SearchCandidate, *, snippet: str) -> str:
    explicit = str(getattr(hit, "evidence_kind", "") or "").strip()
    if explicit in {"symbol_match", "symbol_locator", "path_match"}:
        return explicit
    return _evidence_kind(hit.file, hit.snippet, snippet)


def _evidence_kind(path: str, line: str, snippet: str) -> str:
    matched_line = str(line or "")
    if str(line or "").lower().startswith("symbol match:"):
        return "symbol_match"
    if str(line or "").lower().startswith("path match:"):
        return "path_match"
    if "test" in path.lower() or "regression" in path.lower():
        return "test"
    if re.search(r"\b(class|def|async def|function|interface)\s+[A-Za-z_][A-Za-z0-9_]*", matched_line):
        return "definition"
    if re.search(r"\b(import|from|require)\b", matched_line):
        return "call_site"
    if path.endswith((".json", ".toml", ".yaml", ".yml")):
        return "config"
    if path.endswith((".md", ".rst")):
        return "doc"
    return "text_match"


def _score(
    path: str,
    evidence_kind: str,
    line: str,
    snippet: str,
    *,
    context: dict[str, Any],
    hit_score: float = 0.0,
    hit_match_reason: str = "",
) -> tuple[float, str]:
    score = {
        "symbol_match": 0.98,
        "symbol_locator": 0.62,
        "path_match": 0.72,
        "definition": 0.95,
        "call_site": 0.78,
        "config": 0.68,
        "test": 0.62,
        "text_match": 0.58,
        "doc": 0.35,
    }.get(evidence_kind, 0.5)
    lowered_path = path.lower()
    basename = lowered_path.rsplit("/", 1)[-1]
    haystack = f"{path}\n{line}\n{snippet}".lower()
    reasons = [f"{evidence_kind} evidence"]
    symbol_hits = _matched_terms(haystack, context["symbols"])
    required_hits = _matched_terms(haystack, context["required_terms"])
    query_hits = _matched_terms(haystack, context["query_terms"])
    path_hits = _matched_terms(lowered_path, context["path_terms"])
    basename_symbol_hits = _matched_terms(basename, context["symbols"])
    locator_only = evidence_kind == "path_match"
    if hit_score > 0:
        score += min(0.22, hit_score / 40.0)
        reasons.append(str(hit_match_reason or "ranked retrieval score"))
    if evidence_kind == "symbol_match":
        score += 0.18
        reasons.append("direct symbol index hit")
    if evidence_kind == "symbol_locator":
        reasons.append("symbol locator for mixed query")
    if evidence_kind == "path_match":
        score += 0.08
        reasons.append("direct path search hit")
    if symbol_hits and not locator_only:
        score += min(0.28, 0.14 * len(symbol_hits))
        reasons.append(f"symbol match:{','.join(symbol_hits[:3])}")
    if basename_symbol_hits and not locator_only:
        score += min(0.24, 0.12 * len(basename_symbol_hits))
        reasons.append("symbol filename match")
    if required_hits and not locator_only:
        score += min(0.18, 0.06 * len(required_hits))
        reasons.append("required term match")
    if len(query_hits) >= 2 and not locator_only:
        score += 0.14
        reasons.append("multi-term co-occurrence")
    if path_hits and not locator_only:
        score += min(0.16, 0.08 * len(path_hits))
        reasons.append("path affinity")
    if any(part in lowered_path for part in ("node_modules", ".next", "dist/", "build/", "cache/")):
        score -= 0.5
        reasons.append("generated path penalty")
    if lowered_path.startswith("storage/") and lowered_path.endswith(".json"):
        score -= 0.18
        reasons.append("storage json penalty")
    if evidence_kind == "test":
        if context["test_intent"]:
            score += 0.08
            reasons.append("test intent")
        else:
            score -= 0.22
            reasons.append("test not requested")
    if evidence_kind == "doc":
        if context["doc_intent"]:
            score += 0.12
            reasons.append("doc intent")
        else:
            score -= 0.08
            reasons.append("doc not requested")
    if lowered_path.startswith(("backend/", "frontend/")) and evidence_kind not in {"doc", "test"}:
        score += 0.04
        reasons.append("source path")
    if score >= 0.85:
        reasons[0] = f"high-priority {reasons[0]}"
    return max(0.0, min(1.0, score)), "; ".join(reasons[:4])


def _symbol_from_snippet(value: str) -> str:
    symbol_match = re.search(r"\bsymbol match:\s+\w+\s+([A-Za-z_][A-Za-z0-9_.]*)", value)
    if symbol_match:
        return symbol_match.group(1)
    match = re.search(r"\b(?:class|def|async def|function|interface)\s+([A-Za-z_][A-Za-z0-9_]*)", value)
    return match.group(1) if match else ""


def _diversify_by_file(evidence: list[CodebaseEvidence], *, limit: int) -> list[CodebaseEvidence]:
    selected: list[CodebaseEvidence] = []
    selected_keys: set[tuple[str, int]] = set()
    seen_files: set[str] = set()
    for item in evidence:
        if item.file in seen_files:
            continue
        selected.append(item)
        selected_keys.add((item.file, item.line))
        seen_files.add(item.file)
        if len(selected) >= limit:
            return selected
    for item in evidence:
        key = (item.file, item.line)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return selected


def _ranking_context(*, plan: CodebaseSearchPlan | None, query: str) -> dict[str, Any]:
    symbols = tuple(str(item or "").strip().lower() for item in tuple(getattr(plan, "symbol_queries", ()) or ()) if str(item or "").strip())
    query_terms = tuple(str(item or "").strip().lower() for item in tuple(getattr(plan, "query_terms", ()) or ()) if str(item or "").strip())
    required_terms = tuple(str(item or "").strip().lower() for item in tuple(getattr(plan, "required_terms", ()) or ()) if str(item or "").strip())
    path_terms = tuple(
        _path_basename_term(str(item or "").strip().lower())
        for item in tuple(getattr(plan, "path_queries", ()) or ())
        if str(item or "").strip()
    )
    return {
        "symbols": tuple(dict.fromkeys([*symbols, *_identifier_variants(symbols)])),
        "query_terms": tuple(dict.fromkeys(query_terms)),
        "required_terms": tuple(dict.fromkeys(required_terms)),
        "path_terms": tuple(item for item in dict.fromkeys([*path_terms, *_identifier_variants(path_terms)]) if item),
        "test_intent": bool(getattr(plan, "test_intent", False)) or _contains_test_intent(query),
        "doc_intent": bool(getattr(plan, "doc_intent", False)) or _contains_doc_intent(query),
        "rag_eval_intent": _contains_rag_eval_intent(query),
    }


def _matched_terms(haystack: str, terms: tuple[str, ...]) -> list[str]:
    lowered = str(haystack or "").lower()
    compact_haystack = _compact_identifier(lowered)
    matches: list[str] = []
    for term in terms:
        item = str(term or "").strip().lower()
        if not item or len(item) < 3:
            continue
        compact_item = _compact_identifier(item)
        if item in lowered or (compact_item and len(compact_item) >= 3 and compact_item in compact_haystack):
            matches.append(item)
    return matches


def _identifier_variants(terms: tuple[str, ...]) -> tuple[str, ...]:
    variants: list[str] = []
    for term in tuple(terms or ()):
        item = str(term or "").strip()
        if not item:
            continue
        snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", item)
        snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", snake)
        snake = re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").lower()
        compact = _compact_identifier(item)
        if snake:
            variants.append(snake)
        if compact:
            variants.append(compact)
    return tuple(dict.fromkeys(variants))


def _compact_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _path_basename_term(value: str) -> str:
    item = str(value or "").replace("\\", "/").strip("/")
    if not item:
        return ""
    tail = item.rsplit("/", 1)[-1]
    return tail or item


def _contains_test_intent(value: str) -> bool:
    lowered = str(value or "").lower()
    return "测试" in lowered or bool(re.search(r"\b(pytest|tests?|regression|spec|fixture)\b", lowered))


def _contains_doc_intent(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(token in lowered for token in ("文档", "计划书", "设计书", "方案")) or bool(re.search(r"\b(docs?|readme)\b", lowered))


def _contains_rag_eval_intent(value: str) -> bool:
    lowered = str(value or "").lower()
    return any(
        token in lowered
        for token in (
            "rag",
            "retrieval",
            "scifact",
            "qrels",
            "benchmark",
            "eval",
            "evaluation",
            "测试数据",
            "评测",
            "检索质量",
            "召回率",
            "准确率",
        )
    )


def _path_priority(path: str, *, context: dict[str, Any]) -> int:
    if not context.get("rag_eval_intent"):
        return 0
    normalized = str(path or "").replace("\\", "/").lower()
    if normalized.startswith("scifact/") and "/qrels/" in normalized:
        return 90
    if normalized.startswith("scifact/") and normalized.endswith((".jsonl", ".tsv", ".parquet")):
        return 80
    if normalized.startswith("backend/tests/_artifacts/") and normalized.endswith(".json"):
        return 75
    if normalized.startswith("output/benchmark_runtime/"):
        return 60
    return 0


def _evidence_kind_priority(evidence_kind: str) -> int:
    return {
        "symbol_match": 110,
        "path_match": 100,
        "definition": 80,
        "call_site": 55,
        "symbol_locator": 50,
        "config": 45,
        "text_match": 35,
        "test": 30,
        "doc": 20,
    }.get(str(evidence_kind or ""), 0)


def _symbol_filename_priority(path: str, *, context: dict[str, Any]) -> int:
    basename = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    compact_basename = _compact_identifier(basename)
    for symbol in tuple(context.get("symbols") or ()):
        compact_symbol = _compact_identifier(str(symbol or ""))
        if compact_symbol and compact_symbol in compact_basename:
            return 100
    return 0


def _path_query_filename_priority(path: str, *, context: dict[str, Any]) -> int:
    basename = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    compact_basename = _compact_identifier(basename)
    for term in tuple(context.get("path_terms") or ()):
        compact_term = _compact_identifier(str(term or ""))
        if compact_term and len(compact_term) >= 8 and compact_term in compact_basename:
            return 100
    return 0


