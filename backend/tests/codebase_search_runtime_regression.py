from __future__ import annotations

import asyncio
from pathlib import Path

from runtime.codebase_search_runtime import (
    CODEBASE_SEARCH_TEMPLATE_ID,
    CodebaseSearchRuntime,
    normalize_codebase_search_config,
    required_operations_for_codebase_search,
)
from runtime.codebase_search_runtime.file_slicer import FileSlicer
from runtime.codebase_search_runtime.query_planner import build_codebase_search_plan
from runtime.codebase_search_runtime.ranker import rank_codebase_evidence
from runtime.execution.child_agent_runtime_executor import ChildAgentRuntimeExecutor
from runtime.execution.delegation_models import AgentDelegationRequest
from runtime.codebase_search_runtime.providers import TextHit


def _request(query: str = "CodebaseSearchRuntime") -> AgentDelegationRequest:
    return AgentDelegationRequest(
        request_id="delegation:req:codebase-search",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:codebase_searcher",
        delegation_kind="codebase_search",
        instruction=query,
        input_payload={"query": query},
    )


def _agent():
    return type("Agent", (), {"agent_id": "agent:codebase_searcher"})()


def _profile(**metadata):
    return type(
        "Profile",
        (),
        {
            "allowed_operations": required_operations_for_codebase_search() + ("op.git_log", "op.git_show"),
            "blocked_operations": ("op.web_search", "op.fetch_url", "op.memory_read", "op.mcp_retrieval"),
            "metadata": {
                "runtime_config": {
                    "template_id": CODEBASE_SEARCH_TEMPLATE_ID,
                    "runtime_kind": "codebase_search_agent",
                    "runtime_mode": "readonly_recon",
                    "codebase_search": {
                        "max_queries": 8,
                        "max_text_results": 20,
                        "max_file_slices": 6,
                        "max_slice_lines": 80,
                        **metadata,
                    },
                }
            },
        },
    )()


def test_codebase_search_template_routes_to_local_runtime() -> None:
    executor = ChildAgentRuntimeExecutor(Path("."))

    payload = asyncio.run(executor.run(request=_request("CodebaseSearchRuntime"), agent=_agent(), profile=_profile()))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "runtime_configured_codebase_search_agent"
    assert payload["diagnostics"]["runtime_template_id"] == CODEBASE_SEARCH_TEMPLATE_ID
    assert payload["diagnostics"]["specialist_route"] == "codebase_search"
    assert payload["findings"]
    assert all(str(item["file"]).startswith("backend/") for item in payload["findings"][:3])


def test_codebase_search_permissions_do_not_accept_web_or_memory_substitute() -> None:
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": ("op.model_response", "op.web_search", "op.memory_read"),
            "blocked_operations": (),
            "metadata": {"runtime_config": {"template_id": CODEBASE_SEARCH_TEMPLATE_ID}},
        },
    )()

    payload = asyncio.run(CodebaseSearchRuntime(Path(".")).run(request=_request(), agent=_agent(), profile=profile, config=normalize_codebase_search_config({})))

    assert payload["status"] == "failed"
    assert "codebase_search_required_operation_missing" in payload["limitations"]
    assert "op.search_text" in payload["limitations"]
    assert payload["diagnostics"]["runtime_template_id"] == CODEBASE_SEARCH_TEMPLATE_ID


def test_query_planner_splits_symbols_roots_and_noise_terms() -> None:
    plan = build_codebase_search_plan(
        "检查 backend/runtime 的 ChildAgentRuntimeExecutor legacy fallback intent classifier",
        max_queries=10,
        include_tests=True,
    )

    assert "backend" in plan.preferred_roots
    assert "ChildAgentRuntimeExecutor" in plan.symbol_queries
    assert {"legacy", "fallback", "intent", "classifier"} <= set(plan.text_queries)
    assert plan.git_history_queries


def test_file_slicer_reads_bounded_context() -> None:
    slicer = FileSlicer(Path("."))

    result = slicer.slice_file(
        "backend/runtime/codebase_search_runtime/runtime.py",
        matched_line=15,
        max_slice_lines=30,
    )

    assert result is not None
    assert result.file == "backend/runtime/codebase_search_runtime/runtime.py"
    assert result.end_line - result.start_line + 1 <= 30
    assert "CodebaseSearchRuntime" in result.snippet


def test_ranker_prioritizes_definitions_over_docs() -> None:
    hits = [
        TextHit(file="docs/implementation_plans/example.md", line=1, column=1, snippet="CodebaseSearchRuntime design", query="CodebaseSearchRuntime"),
        TextHit(file="backend/runtime/codebase_search_runtime/runtime.py", line=14, column=1, snippet="class CodebaseSearchRuntime:", query="CodebaseSearchRuntime"),
    ]

    ranked = rank_codebase_evidence(hits, [], limit=2)

    assert ranked[0].file.endswith("runtime.py")
    assert ranked[0].evidence_kind == "definition"
    assert ranked[0].score > ranked[1].score


def test_missing_matches_returns_limitation_not_fake_evidence() -> None:
    missing_query = "definitely_missing_" + "code_symbol_zzzz_" + "20260525"
    payload = asyncio.run(
        CodebaseSearchRuntime(Path(".")).run(
            request=_request(missing_query),
            agent=_agent(),
            profile=_profile(include_git_history=False),
            config=normalize_codebase_search_config({"max_queries": 2, "max_text_results": 4, "max_file_slices": 2, "include_git_history": False}),
        )
    )

    assert payload["status"] == "failed"
    assert payload["findings"] == []
    assert "codebase_search_no_evidence" in payload["limitations"]
