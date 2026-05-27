from __future__ import annotations

from .models import CodebaseEvidence, CodebaseSearchResult


def build_codebase_search_result(
    *,
    query: str,
    findings: tuple[CodebaseEvidence, ...],
    files_read: tuple[str, ...],
    limitations: tuple[str, ...],
    diagnostics: dict,
) -> CodebaseSearchResult:
    if findings:
        summary = f"本地代码搜索完成：为“{query}”找到 {len(findings)} 条带文件行号的证据。"
        status = "completed"
    else:
        summary = f"本地代码搜索完成，但没有找到“{query}”的代码证据。"
        status = "failed"
        limitations = tuple(dict.fromkeys([*limitations, "codebase_search_no_evidence"]))
    return CodebaseSearchResult(
        status=status,
        summary=summary,
        findings=findings,
        files_read=files_read,
        limitations=limitations,
        diagnostics=diagnostics,
    )
