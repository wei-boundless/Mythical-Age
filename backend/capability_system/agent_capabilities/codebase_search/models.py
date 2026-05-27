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
    git_history_queries: tuple[str, ...] = ()
    preferred_roots: tuple[str, ...] = ()
    file_globs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_queries": list(self.path_queries),
            "text_queries": list(self.text_queries),
            "symbol_queries": list(self.symbol_queries),
            "git_history_queries": list(self.git_history_queries),
            "preferred_roots": list(self.preferred_roots),
            "file_globs": list(self.file_globs),
        }


@dataclass(frozen=True, slots=True)
class CodebaseEvidence:
    file: str
    line: int = 1
    column: int = 1
    symbol: str = ""
    evidence_kind: str = "text_match"
    snippet: str = ""
    score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "symbol": self.symbol,
            "evidence_kind": self.evidence_kind,
            "snippet": self.snippet,
            "score": round(float(self.score), 3),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CodebaseSearchResult:
    status: str
    summary: str
    findings: tuple[CodebaseEvidence, ...] = ()
    files_read: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "files_read": list(self.files_read),
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


