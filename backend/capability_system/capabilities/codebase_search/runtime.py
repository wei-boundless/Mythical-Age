from __future__ import annotations

from pathlib import Path
from typing import Any

from .file_slicer import FileSlicer
from .models import CodebaseSearchConfig, required_operations_for_codebase_search
from .providers import CodebaseSearchProviders, TextHit
from .query_planner import build_codebase_search_plan
from .ranker import rank_codebase_evidence
from .report import build_codebase_search_result


class CodebaseSearchCapability:
    """Read-only deterministic local codebase search capability."""

    def __init__(self, root_dir: Path, *, providers: CodebaseSearchProviders | None = None, slicer: FileSlicer | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.providers = providers or CodebaseSearchProviders(self.root_dir)
        self.slicer = slicer or FileSlicer(self.root_dir)

    async def run(
        self,
        *,
        request: Any,
        agent: Any,
        profile: Any,
        config: CodebaseSearchConfig,
    ) -> dict[str, Any]:
        available_ops = _available_operations(profile)
        required_ops = set(required_operations_for_codebase_search())
        missing_ops = sorted(required_ops - available_ops)
        if missing_ops:
            return _failed_result(
                summary="Codebase Search Agent 缺少本地只读搜索权限。",
                limitations=["codebase_search_required_operation_missing", *missing_ops],
                diagnostics={
                    "child_execution_mode": "profile_authorized_codebase_search_capability",
                    "capability_id": "capability.codebase_search",
                    "required_operations": sorted(required_ops),
                    "available_operations": sorted(available_ops),
                    "missing_operations": missing_ops,
                },
            )

        payload = dict(request.input_payload or {})
        query = str(payload.get("query") or payload.get("question") or request.instruction or "").strip()
        if not query:
            return _failed_result(
                summary="Codebase Search Agent 没有收到可检索的问题。",
                limitations=["codebase_search_empty_query"],
                diagnostics={"child_execution_mode": "profile_authorized_codebase_search_capability"},
            )

        plan = build_codebase_search_plan(query, max_queries=config.max_queries, include_tests=config.include_tests)
        roots = tuple(payload.get("roots") or plan.preferred_roots)
        path_results = []
        if plan.path_queries:
            path_results = await self.providers.search_paths(
                queries=plan.path_queries,
                roots=roots,
                max_results=config.max_path_results,
            )
        glob_results = await self.providers.glob_paths(patterns=plan.file_globs, max_results=config.max_path_results)
        text_hits = await self.providers.search_text(
            queries=_text_queries(plan),
            roots=roots,
            max_results=config.max_text_results,
        )
        text_hits = _boost_path_hits(text_hits, path_results=path_results)
        slices = self.slicer.slices_for_hits(
            text_hits,
            max_slices=config.max_file_slices,
            max_slice_lines=config.max_slice_lines,
        )
        findings = rank_codebase_evidence(text_hits, slices, limit=config.max_file_slices, plan=plan, query=query)
        files_read = tuple(dict.fromkeys(item.file for item in slices))
        limitations: list[str] = []
        git_history = []
        if config.include_git_history:
            git_history = await self.providers.git_log(queries=plan.git_history_queries, max_results=8)
            if not git_history and plan.git_history_queries:
                limitations.append("git_history_no_relevant_commits")

        result = build_codebase_search_result(
            query=query,
            findings=findings,
            files_read=files_read,
            limitations=tuple(limitations),
            diagnostics={
                "child_execution_mode": "profile_authorized_codebase_search_capability",
                "operation_id": "op.codebase_search",
                "specialist_route": "codebase_search",
                "capability_id": "capability.codebase_search",
                "capability_config": config.to_dict(),
                "agent_id": str(getattr(agent, "agent_id", "") or "agent:codebase_searcher"),
                "plan": plan.to_dict(),
                "path_results": path_results[:20],
                "glob_results": glob_results[:20],
                "git_history": git_history,
                "usage": {
                    "text_hits": len(text_hits),
                    "files_read": len(files_read),
                    "findings": len(findings),
                    "max_file_slices": config.max_file_slices,
                    "max_text_results": config.max_text_results,
                },
            },
        )
        payload_result = result.to_dict()
        payload_result["answer_candidate"] = _answer_candidate(payload_result["summary"], payload_result["findings"])
        payload_result["evidence_refs"] = [f"{item['file']}:{item['line']}" for item in payload_result["findings"]]
        payload_result["artifact_refs"] = []
        payload_result["confidence"] = "high" if payload_result["findings"] else "low"
        return payload_result


def _available_operations(profile: Any) -> set[str]:
    allowed = {str(item).strip() for item in tuple(getattr(profile, "allowed_operations", ()) or ()) if str(item).strip()}
    blocked = {str(item).strip() for item in tuple(getattr(profile, "blocked_operations", ()) or ()) if str(item).strip()}
    return allowed - blocked


def _text_queries(plan: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*plan.symbol_queries, *plan.text_queries]))


def _boost_path_hits(text_hits: list[TextHit], *, path_results: list[str]) -> list[TextHit]:
    known_paths = set(path_results)
    direct_hits = [
        TextHit(file=path, line=1, column=1, snippet=f"path match: {path}", query="path")
        for path in known_paths
        if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md"))
    ]
    return [*text_hits, *direct_hits]


def _answer_candidate(summary: str, findings: list[dict[str, Any]]) -> str:
    lines = [summary]
    for item in findings[:8]:
        lines.append(f"- {item['file']}:{item['line']} [{item['evidence_kind']}] {item['reason']}")
    return "\n".join(lines)


def _failed_result(*, summary: str, limitations: list[str], diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "failed",
        "summary": summary,
        "answer_candidate": summary,
        "findings": [],
        "files_read": [],
        "evidence_refs": [],
        "artifact_refs": [],
        "confidence": "low",
        "limitations": limitations,
        "diagnostics": diagnostics,
    }


