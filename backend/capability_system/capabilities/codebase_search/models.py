from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CODEBASE_SEARCH_TEMPLATE_ID = "runtime.template.codebase_search"


@dataclass(frozen=True, slots=True)
class CodebaseSearchConfig:
    max_queries: int = 12
    max_path_results: int = 40
    max_text_results: int = 80
    max_file_slices: int = 16
    max_slice_lines: int = 120
    include_git_history: bool = True
    include_tests: bool = True
    stop_policy: str = "enough_code_evidence_or_budget_exhausted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_queries": self.max_queries,
            "max_path_results": self.max_path_results,
            "max_text_results": self.max_text_results,
            "max_file_slices": self.max_file_slices,
            "max_slice_lines": self.max_slice_lines,
            "include_git_history": self.include_git_history,
            "include_tests": self.include_tests,
            "stop_policy": self.stop_policy,
        }


@dataclass(frozen=True, slots=True)
class CodebaseSearchPlan:
    path_queries: tuple[str, ...] = ()
    text_queries: tuple[str, ...] = ()
    symbol_queries: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    git_history_queries: tuple[str, ...] = ()
    preferred_roots: tuple[str, ...] = ()
    file_globs: tuple[str, ...] = ()
    test_intent: bool = False
    doc_intent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_queries": list(self.path_queries),
            "text_queries": list(self.text_queries),
            "symbol_queries": list(self.symbol_queries),
            "query_terms": list(self.query_terms),
            "required_terms": list(self.required_terms),
            "git_history_queries": list(self.git_history_queries),
            "preferred_roots": list(self.preferred_roots),
            "file_globs": list(self.file_globs),
            "test_intent": self.test_intent,
            "doc_intent": self.doc_intent,
        }


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    file: str
    line: int = 1
    column: int = 1
    snippet: str = ""
    query: str = ""
    source_layer: str = "text"
    evidence_kind: str = "text_match"
    score: float = 0.0
    match_reason: str = ""
    matched_terms: tuple[str, ...] = ()
    search_status: str = "candidate_only"
    recommended_read_window: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "file": self.file,
            "line": max(1, int(self.line or 1)),
            "column": max(1, int(self.column or 1)),
            "snippet": self.snippet,
            "query": self.query,
            "source_layer": self.source_layer,
            "evidence_kind": self.evidence_kind,
            "score": round(float(self.score), 3),
            "match_reason": self.match_reason,
            "matched_terms": list(self.matched_terms),
            "search_status": self.search_status,
            "recommended_read_window": self.read_window(),
        }
        return {key: value for key, value in payload.items() if value not in ("", [], {})}

    def read_window(self) -> dict[str, Any]:
        if self.recommended_read_window:
            return dict(self.recommended_read_window)
        line = max(1, int(self.line or 1))
        start_line = max(1, line - 12)
        end_line = line + 12
        return {
            "path": self.file,
            "start_line": start_line,
            "end_line": end_line,
            "line_count": end_line - start_line + 1,
            "match_line": line,
            "read_intent": "codebase_search_candidate",
            "authority": "capability_system.capabilities.codebase_search",
        }


@dataclass(frozen=True, slots=True)
class SearchFeedback:
    feedback_kind: str
    action: str
    message: str = ""
    source_layer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "feedback_kind": self.feedback_kind,
                "action": self.action,
                "message": self.message,
                "source_layer": self.source_layer,
            }.items()
            if value
        }


@dataclass(frozen=True, slots=True)
class SearchLifecycleRecord:
    lifecycle_state: str
    candidate_count: int = 0
    consumed_candidate_refs: tuple[str, ...] = ()
    superseded_candidate_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifecycle_state": self.lifecycle_state,
            "candidate_count": max(0, int(self.candidate_count or 0)),
            "consumed_candidate_refs": list(self.consumed_candidate_refs),
            "superseded_candidate_refs": list(self.superseded_candidate_refs),
        }


@dataclass(frozen=True, slots=True)
class SearchResultEnvelope:
    query: str
    status: str
    candidates: tuple[SearchCandidate, ...] = ()
    layer_meta: tuple[dict[str, Any], ...] = ()
    feedback: tuple[SearchFeedback, ...] = ()
    lifecycle: SearchLifecycleRecord = field(default_factory=lambda: SearchLifecycleRecord(lifecycle_state="discovered"))
    authority: str = "capability_system.capabilities.codebase_search.search_result_envelope"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "query": self.query,
            "status": self.status,
            "candidates": [item.to_dict() for item in self.candidates],
            "layer_meta": [dict(item) for item in self.layer_meta],
            "feedback": [item.to_dict() for item in self.feedback],
            "lifecycle": self.lifecycle.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CodebaseEvidence:
    file: str
    line: int = 1
    column: int = 1
    start_line: int = 1
    end_line: int = 1
    symbol: str = ""
    evidence_kind: str = "text_match"
    source_layer: str = "text"
    search_status: str = "candidate_only"
    snippet: str = ""
    score: float = 0.0
    reason: str = ""
    matched_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        start_line = max(1, int(self.start_line or self.line or 1))
        end_line = max(start_line, int(self.end_line or self.line or start_line))
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "start_line": start_line,
            "end_line": end_line,
            "symbol": self.symbol,
            "evidence_kind": self.evidence_kind,
            "source_layer": self.source_layer,
            "search_status": self.search_status,
            "snippet": self.snippet,
            "score": round(float(self.score), 3),
            "reason": self.reason,
            "matched_terms": list(self.matched_terms),
            "recommended_read_window": {
                "path": self.file,
                "start_line": start_line,
                "end_line": end_line,
                "line_count": max(1, min(end_line - start_line + 1, 240)),
                "match_line": max(1, int(self.line or start_line)),
                "read_intent": "codebase_search_evidence",
                "authority": "capability_system.capabilities.codebase_search",
            },
        }


@dataclass(frozen=True, slots=True)
class CodebaseSearchResult:
    status: str
    summary: str
    findings: tuple[CodebaseEvidence, ...] = ()
    files_read: tuple[str, ...] = ()
    code_structure: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "files_read": list(self.files_read),
            "code_structure": dict(self.code_structure),
            "limitations": list(self.limitations),
            "diagnostics": dict(self.diagnostics),
        }


def normalize_codebase_search_config(value: Any) -> CodebaseSearchConfig:
    raw = _as_record(value)
    nested = raw.get("codebase_search")
    if isinstance(nested, dict):
        raw = {**raw, **nested}
    return CodebaseSearchConfig(
        max_queries=_clamp_int(raw.get("max_queries"), 1, 30, 12),
        max_path_results=_clamp_int(raw.get("max_path_results"), 1, 100, 40),
        max_text_results=_clamp_int(raw.get("max_text_results"), 1, 200, 80),
        max_file_slices=_clamp_int(raw.get("max_file_slices"), 1, 60, 16),
        max_slice_lines=_clamp_int(raw.get("max_slice_lines"), 20, 240, 120),
        include_git_history=bool(raw.get("include_git_history", True)),
        include_tests=bool(raw.get("include_tests", True)),
        stop_policy=str(raw.get("stop_policy") or "enough_code_evidence_or_budget_exhausted"),
    )


def required_operations_for_codebase_search() -> tuple[str, ...]:
    return (
        "op.model_response",
        "op.codebase_search",
        "op.search_files",
        "op.search_text",
        "op.python_symbol_search",
        "op.read_file",
        "op.glob_paths",
    )


def _as_record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(fallback)
    return max(minimum, min(maximum, parsed))


