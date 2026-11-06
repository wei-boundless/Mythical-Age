from __future__ import annotations

from dataclasses import replace
import re
from pathlib import Path
from typing import Any

from .file_slicer import FileSlicer
from .models import CodebaseSearchConfig, SearchCandidate, required_operations_for_codebase_search
from .providers import CodebaseSearchProviders
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
        user_roots = tuple(payload.get("roots") or ())
        roots = tuple(user_roots or plan.preferred_roots)
        using_plan_roots = not bool([str(item or "").strip() for item in user_roots])
        skipped_layers: list[str] = []
        path_queries = _path_queries_for_fast_pass(plan, query=query)
        path_results = []
        if path_queries:
            path_results = await self.providers.search_paths(
                queries=path_queries,
                roots=roots,
                max_results=config.max_path_results,
                include_default_search_excludes=using_plan_roots,
            )
        else:
            skipped_layers.append("path:no_high_signal_path_query")

        glob_results = []
        run_glob = _should_run_glob(plan, query=query)
        if run_glob:
            glob_results = await self.providers.glob_paths(patterns=plan.file_globs, max_results=config.max_path_results)
        else:
            skipped_layers.append("glob:no_explicit_glob_intent")

        symbol_queries = _symbol_queries_for_fast_pass(plan, query=query)
        symbol_hits = []
        if symbol_queries:
            symbol_hits = await self.providers.search_symbols(
                queries=symbol_queries,
                roots=roots,
                max_results=max(1, min(config.max_text_results, max(10, config.max_file_slices * 2))),
            )
        else:
            skipped_layers.append("symbol:no_high_signal_symbol_query")
        exact_symbol_lookup = _is_exact_symbol_lookup(symbol_hits, query=query)
        if not exact_symbol_lookup:
            symbol_hits = _soften_symbol_hits_for_mixed_query(symbol_hits)
        text_hits = []
        if exact_symbol_lookup and _enough_symbol_candidates(symbol_hits, query=query):
            skipped_layers.append("text:symbol_candidates_sufficient")
        else:
            text_queries = _text_queries(plan)
            if text_queries:
                text_hits = await self.providers.search_text(
                    queries=text_queries,
                    roots=roots,
                    max_results=config.max_text_results,
                    include_default_search_excludes=using_plan_roots,
                )
            else:
                skipped_layers.append("text:no_high_signal_text_query")

        text_hits = _dedupe_hits([*symbol_hits, *text_hits])
        text_hits = _boost_path_hits(text_hits, path_results=path_results, source_layer="path")
        if run_glob:
            text_hits = _boost_path_hits(text_hits, path_results=glob_results, source_layer="glob")
        slices = self.slicer.slices_for_hits(
            text_hits,
            max_slices=config.max_file_slices,
            max_slice_lines=config.max_slice_lines,
        )
        findings = rank_codebase_evidence(text_hits, slices, limit=config.max_file_slices, plan=plan, query=query)
        files_read = tuple(dict.fromkeys(item.file for item in slices))
        limitations: list[str] = []
        git_history = []
        if config.include_git_history and _should_run_git_history(query=query, plan=plan):
            git_history = await self.providers.git_log(queries=plan.git_history_queries, max_results=8)
            if not git_history and plan.git_history_queries:
                limitations.append("git_history_no_relevant_commits")
        else:
            skipped_layers.append("git_history:no_history_intent")

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
                "adaptive_search": {
                    "path_queries_used": list(path_queries),
                    "symbol_queries_used": list(symbol_queries),
                    "text_queries_used": list(_text_queries(plan)),
                    "glob_ran": bool(run_glob),
                    "skipped_layers": skipped_layers,
                    "strategy": "intent_gated_adaptive_cascade",
                },
                "path_results": path_results[:20],
                "path_search_meta": list(getattr(self.providers, "last_path_search_meta", []) or []),
                "symbol_search_meta": list(getattr(self.providers, "last_symbol_search_meta", []) or []),
                "glob_results": glob_results[:20],
                "glob_search_meta": list(getattr(self.providers, "last_glob_search_meta", []) or []),
                "text_search_meta": list(getattr(self.providers, "last_text_search_meta", []) or []),
                "git_history": git_history,
                "usage": {
                    "symbol_hits": len(symbol_hits),
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
    queries: list[str] = []
    raw_text_queries = tuple(getattr(plan, "text_queries", ()) or ())
    symbol_queries = tuple(getattr(plan, "symbol_queries", ()) or ())
    has_phrase_query = any(" " in str(item or "").strip() for item in raw_text_queries)
    symbol_query_set = {str(item or "").strip() for item in symbol_queries if str(item or "").strip()}
    for query in [*symbol_queries, *raw_text_queries]:
        item = str(query or "").strip()
        if not item:
            continue
        if " " in item or item in symbol_query_set or _is_identifier_query(item) or (not has_phrase_query and _is_high_signal_query(item)):
            queries.append(item)
    return tuple(dict.fromkeys(queries))


def _symbol_queries_for_fast_pass(plan: Any, *, query: str) -> tuple[str, ...]:
    queries = [str(item or "").strip() for item in tuple(getattr(plan, "symbol_queries", ()) or ()) if str(item or "").strip()]
    if not queries:
        return ()
    query_has_extra_terms = " " in str(query or "").strip()
    if not query_has_extra_terms:
        high_signal = [item for item in queries if _has_camel_or_qualified_symbol_signal(item)]
        return tuple(dict.fromkeys(high_signal[:4]))
    high_signal = [item for item in queries if _has_camel_or_qualified_symbol_signal(item)]
    return tuple(dict.fromkeys(high_signal[:4]))


def _boost_path_hits(text_hits: list[SearchCandidate], *, path_results: list[str], source_layer: str) -> list[SearchCandidate]:
    existing_hit_files = {str(hit.file or "") for hit in list(text_hits or [])}
    known_paths = set(path_results)
    direct_hits = [
        SearchCandidate(
            file=path,
            line=1,
            column=1,
            snippet=f"{source_layer} match: {path}",
            query=source_layer,
            source_layer=source_layer,
            evidence_kind="path_match",
            match_reason=f"{source_layer}_locator_candidate",
        )
        for path in known_paths
        if path not in existing_hit_files
        if path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".jsonl", ".tsv", ".csv", ".parquet", ".ipynb", ".md"))
    ]
    return [*text_hits, *direct_hits]


def _dedupe_hits(hits: list[SearchCandidate]) -> list[SearchCandidate]:
    seen: set[tuple[str, int]] = set()
    result: list[SearchCandidate] = []
    for hit in list(hits or []):
        key = (str(hit.file or ""), int(hit.line or 0))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(hit)
    return result


def _answer_candidate(summary: str, findings: list[dict[str, Any]]) -> str:
    lines = [summary]
    for item in findings[:8]:
        lines.append(f"- {item['file']}:{item['line']} [{item['evidence_kind']}] {item['reason']}")
    return "\n".join(lines)


def _path_queries_for_fast_pass(plan: Any, *, query: str) -> tuple[str, ...]:
    queries = [str(item or "").strip() for item in tuple(getattr(plan, "path_queries", ()) or ()) if str(item or "").strip()]
    if not queries:
        return ()
    if _has_explicit_path_intent(query):
        return tuple(dict.fromkeys(queries[:6]))
    if " " in str(query or "").strip() and not _has_identifier_signal(query):
        return ()
    high_signal = [item for item in queries if _is_high_signal_path_query(item)]
    return tuple(dict.fromkeys(high_signal[:1]))


def _should_run_glob(plan: Any, *, query: str) -> bool:
    if any(ch in str(query or "") for ch in "*?["):
        return True
    patterns = tuple(str(item or "") for item in tuple(getattr(plan, "file_globs", ()) or ()))
    return any(pattern.startswith(("scifact/", "backend/tests/_artifacts", "output/benchmark_runtime")) for pattern in patterns)


def _should_run_git_history(*, query: str, plan: Any) -> bool:
    if not tuple(getattr(plan, "git_history_queries", ()) or ()):
        return False
    lowered = str(query or "").lower()
    return any(token in lowered for token in ("git", "commit", "history", "历史", "提交", "变更记录", "上次", "previous change"))


def _enough_symbol_candidates(hits: list[SearchCandidate], *, query: str) -> bool:
    symbol_hits = [hit for hit in list(hits or []) if str(getattr(hit, "source_layer", "") or "") == "symbol"]
    if not symbol_hits:
        return False
    return any(_compact_identifier(hit.query) and _compact_identifier(hit.query) in _compact_identifier(query) for hit in symbol_hits)


def _is_exact_symbol_lookup(hits: list[SearchCandidate], *, query: str) -> bool:
    compact_query = _compact_identifier(query)
    if not compact_query:
        return False
    for hit in list(hits or []):
        compact_hit_query = _compact_identifier(str(getattr(hit, "query", "") or ""))
        if compact_hit_query and compact_query == compact_hit_query:
            return True
    return False


def _soften_symbol_hits_for_mixed_query(hits: list[SearchCandidate]) -> list[SearchCandidate]:
    return [
        replace(
            hit,
            evidence_kind="symbol_locator",
            score=min(float(getattr(hit, "score", 0.0) or 0.0), 8.0),
            match_reason=(str(getattr(hit, "match_reason", "") or "python_ast_symbol_search") + "; mixed_query_symbol_locator"),
        )
        for hit in list(hits or [])
    ]


def _has_explicit_path_intent(value: str) -> bool:
    item = str(value or "")
    return "/" in item or "\\" in item or bool(re.search(r"\.(py|ts|tsx|js|jsx|json|md|toml|yaml|yml|sql)\b", item, re.IGNORECASE))


def _is_high_signal_path_query(value: str) -> bool:
    item = str(value or "").strip()
    if not item:
        return False
    return "/" in item or "\\" in item or "." in item or "_" in item or "-" in item or len(_compact_identifier(item)) >= 14


def _is_high_signal_query(value: str) -> bool:
    item = str(value or "").strip()
    if not item:
        return False
    compact = _compact_identifier(item)
    return "_" in item or "." in item or "-" in item or len(compact) >= 8 or any(ch.isupper() for ch in item[1:])


def _is_identifier_query(value: str) -> bool:
    item = str(value or "").strip()
    if not item:
        return False
    return "_" in item or "." in item or "-" in item or any(ch.isupper() for ch in item[1:])


def _has_identifier_signal(value: str) -> bool:
    item = str(value or "")
    return "_" in item or "." in item or "-" in item or any(ch.isupper() for ch in item[1:])


def _has_camel_or_qualified_symbol_signal(value: str) -> bool:
    item = str(value or "").strip()
    if not item:
        return False
    return "." in item or any(ch.isupper() for ch in item[1:])


def _compact_identifier(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


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


