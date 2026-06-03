from __future__ import annotations

from typing import Any

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
        code_structure=_code_structure_map(query=query, findings=findings),
        limitations=limitations,
        diagnostics=diagnostics,
    )


def _code_structure_map(*, query: str, findings: tuple[CodebaseEvidence, ...]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    index_by_file: dict[str, int] = {}
    for item in findings:
        path = str(item.file or "").strip().replace("\\", "/")
        if not path:
            continue
        if path not in index_by_file:
            index_by_file[path] = len(files)
            files.append(
                {
                    "path": path,
                    "candidate_only": True,
                    "must_read_source_before_edit": True,
                    "evidence_refs": [],
                    "slices": [],
                }
            )
        entry = files[index_by_file[path]]
        evidence_ref = f"{path}:{int(item.line or 1)}"
        entry["evidence_refs"].append(evidence_ref)
        start_line = max(1, int(item.start_line or item.line or 1))
        end_line = max(start_line, int(item.end_line or item.line or start_line))
        entry["slices"].append(
            _drop_empty(
                {
                    "evidence_ref": evidence_ref,
                    "matched_line": int(item.line or start_line),
                    "start_line": start_line,
                    "end_line": end_line,
                    "symbol": str(item.symbol or ""),
                    "evidence_kind": str(item.evidence_kind or ""),
                    "score": round(float(item.score), 3),
                    "reason": str(item.reason or ""),
                    "read_request": {
                        "tool_name": "read_file",
                        "args": {
                            "path": path,
                            "start_line": start_line,
                            "line_count": max(1, min(end_line - start_line + 1, 240)),
                        },
                    },
                }
            )
        )
    for entry in files:
        entry["evidence_refs"] = list(dict.fromkeys(entry["evidence_refs"]))
        entry["slices"] = entry["slices"][:8]
    return {
        "authority": "capability.codebase_search.code_structure_map",
        "source_kind": "codebase_search",
        "query": str(query or ""),
        "candidate_only": True,
        "source_authority": "locator_only",
        "instruction": "Use these paths and line ranges to choose the next read_file call; do not treat snippets as complete source.",
        "files": files[:16],
        "limitations": ["not_full_source", "read_file_required_before_edit_or_review"],
    }


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


