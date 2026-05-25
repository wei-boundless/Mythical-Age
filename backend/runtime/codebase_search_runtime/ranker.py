from __future__ import annotations

import re

from .file_slicer import FileSlice
from .models import CodebaseEvidence
from .providers import TextHit


def rank_codebase_evidence(hits: list[TextHit], slices: list[FileSlice], *, limit: int) -> tuple[CodebaseEvidence, ...]:
    slice_by_key = {(item.file, item.matched_line): item for item in slices}
    evidence: list[CodebaseEvidence] = []
    for hit in hits:
        file_slice = slice_by_key.get((hit.file, hit.line))
        snippet = file_slice.snippet if file_slice else hit.snippet
        evidence_kind = _evidence_kind(hit.file, hit.snippet, snippet)
        score, reason = _score(hit.file, evidence_kind, hit.snippet, snippet)
        evidence.append(
            CodebaseEvidence(
                file=hit.file,
                line=hit.line,
                column=hit.column,
                symbol=_symbol_from_snippet(hit.snippet),
                evidence_kind=evidence_kind,
                snippet=snippet,
                score=score,
                reason=reason,
            )
        )
    evidence.sort(key=lambda item: (-item.score, item.file, item.line))
    return tuple(evidence[:limit])


def _evidence_kind(path: str, line: str, snippet: str) -> str:
    value = f"{line}\n{snippet}"
    if re.search(r"\b(class|def|async def|function|interface)\s+[A-Za-z_][A-Za-z0-9_]*", value):
        return "definition"
    if re.search(r"\b(import|from|require)\b", value):
        return "call_site"
    if "test" in path.lower() or "regression" in path.lower():
        return "test"
    if path.endswith((".json", ".toml", ".yaml", ".yml")):
        return "config"
    if path.endswith((".md", ".rst")):
        return "doc"
    return "text_match"


def _score(path: str, evidence_kind: str, line: str, snippet: str) -> tuple[float, str]:
    score = {
        "definition": 0.95,
        "call_site": 0.78,
        "config": 0.68,
        "test": 0.62,
        "text_match": 0.58,
        "doc": 0.35,
    }.get(evidence_kind, 0.5)
    lowered_path = path.lower()
    lowered_text = f"{line}\n{snippet}".lower()
    if any(part in lowered_path for part in ("runtime", "executor", "assembly", "registry", "policy")):
        score += 0.12
    if any(term in lowered_text for term in ("fallback", "legacy", "compat", "intent", "classifier", "recover")):
        score += 0.08
    if any(part in lowered_path for part in ("node_modules", ".next", "dist/", "build/", "cache/")):
        score -= 0.5
    if lowered_path.startswith("storage/") and lowered_path.endswith(".json"):
        score -= 0.18
    reason = f"{evidence_kind} evidence"
    if score >= 0.85:
        reason = f"high-priority {reason}"
    return max(0.0, min(1.0, score)), reason


def _symbol_from_snippet(value: str) -> str:
    match = re.search(r"\b(?:class|def|async def|function|interface)\s+([A-Za-z_][A-Za-z0-9_]*)", value)
    return match.group(1) if match else ""
