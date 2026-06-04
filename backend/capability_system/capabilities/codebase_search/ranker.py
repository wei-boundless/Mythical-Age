from __future__ import annotations

import re
from typing import Any

from .file_slicer import FileSlice
from .models import CodebaseEvidence, CodebaseSearchPlan
from .providers import TextHit


def rank_codebase_evidence(
    hits: list[TextHit],
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
        evidence_kind = _evidence_kind(hit.file, hit.snippet, snippet)
        score, reason = _score(hit.file, evidence_kind, hit.snippet, snippet, context=context)
        evidence.append(
            CodebaseEvidence(
                file=hit.file,
                line=hit.line,
                column=hit.column,
                start_line=file_slice.start_line if file_slice else hit.line,
                end_line=file_slice.end_line if file_slice else hit.line,
                symbol=_symbol_from_snippet(hit.snippet),
                evidence_kind=evidence_kind,
                snippet=snippet,
                score=score,
                reason=reason,
            )
        )
    evidence.sort(key=lambda item: (-item.score, -_path_priority(item.file, context=context), item.file, item.line))
    return tuple(_diversify_by_file(evidence, limit=limit))


def _evidence_kind(path: str, line: str, snippet: str) -> str:
    value = f"{line}\n{snippet}"
    if "test" in path.lower() or "regression" in path.lower():
        return "test"
    if re.search(r"\b(class|def|async def|function|interface)\s+[A-Za-z_][A-Za-z0-9_]*", value):
        return "definition"
    if re.search(r"\b(import|from|require)\b", value):
        return "call_site"
    if path.endswith((".json", ".toml", ".yaml", ".yml")):
        return "config"
    if path.endswith((".md", ".rst")):
        return "doc"
    return "text_match"


def _score(path: str, evidence_kind: str, line: str, snippet: str, *, context: dict[str, Any]) -> tuple[float, str]:
    score = {
        "definition": 0.95,
        "call_site": 0.78,
        "config": 0.68,
        "test": 0.62,
        "text_match": 0.58,
        "doc": 0.35,
    }.get(evidence_kind, 0.5)
    lowered_path = path.lower()
    haystack = f"{path}\n{line}\n{snippet}".lower()
    reasons = [f"{evidence_kind} evidence"]
    symbol_hits = _matched_terms(haystack, context["symbols"])
    required_hits = _matched_terms(haystack, context["required_terms"])
    query_hits = _matched_terms(haystack, context["query_terms"])
    path_hits = _matched_terms(lowered_path, context["path_terms"])
    if symbol_hits:
        score += min(0.28, 0.14 * len(symbol_hits))
        reasons.append(f"symbol match:{','.join(symbol_hits[:3])}")
    if required_hits:
        score += min(0.18, 0.06 * len(required_hits))
        reasons.append("required term match")
    if len(query_hits) >= 2:
        score += 0.14
        reasons.append("multi-term co-occurrence")
    if path_hits:
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
        "symbols": tuple(dict.fromkeys(symbols)),
        "query_terms": tuple(dict.fromkeys(query_terms)),
        "required_terms": tuple(dict.fromkeys(required_terms)),
        "path_terms": tuple(item for item in dict.fromkeys(path_terms) if item),
        "test_intent": bool(getattr(plan, "test_intent", False)) or _contains_test_intent(query),
        "doc_intent": bool(getattr(plan, "doc_intent", False)) or _contains_doc_intent(query),
        "rag_eval_intent": _contains_rag_eval_intent(query),
    }


def _matched_terms(haystack: str, terms: tuple[str, ...]) -> list[str]:
    lowered = str(haystack or "").lower()
    matches: list[str] = []
    for term in terms:
        item = str(term or "").strip().lower()
        if not item or len(item) < 3:
            continue
        if item in lowered:
            matches.append(item)
    return matches


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


