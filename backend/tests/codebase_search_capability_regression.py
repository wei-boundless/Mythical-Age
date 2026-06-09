from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from capability_system.capabilities.codebase_search import (
    CODEBASE_SEARCH_TEMPLATE_ID,
    CodebaseSearchCapability,
    normalize_codebase_search_config,
    required_operations_for_codebase_search,
)
from capability_system.capabilities.codebase_search.file_slicer import FileSlicer
from capability_system.capabilities.codebase_search.query_planner import build_codebase_search_plan
from capability_system.capabilities.codebase_search.ranker import rank_codebase_evidence
from capability_system.capabilities.codebase_search.providers import TextHit


def _request(query: str = "CodebaseSearchCapability") -> SimpleNamespace:
    return SimpleNamespace(
        request_id="subagent:req:codebase-search",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:codebase_searcher",
        subagent_task_kind="codebase_search",
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
                    "execution_strategy": "readonly_recon",
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


def test_codebase_search_capability_runs_local_readonly_search() -> None:
    payload = asyncio.run(
        CodebaseSearchCapability(Path(".")).run(
            request=_request("CodebaseSearchCapability"),
            agent=_agent(),
            profile=_profile(),
            config=normalize_codebase_search_config({}),
        )
    )

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "profile_authorized_codebase_search_capability"
    assert payload["diagnostics"]["capability_id"] == "capability.codebase_search"
    assert payload["diagnostics"]["specialist_route"] == "codebase_search"
    assert payload["findings"]
    assert all(str(item["file"]).startswith("backend/") for item in payload["findings"][:3])
    structure = payload["code_structure"]
    assert structure["authority"] == "capability.codebase_search.code_structure_map"
    assert structure["candidate_only"] is True
    assert structure["source_authority"] == "locator_only"
    assert structure["files"]
    first_file = structure["files"][0]
    assert first_file["candidate_only"] is True
    assert first_file["must_read_source_before_edit"] is True
    assert first_file["evidence_refs"]
    assert first_file["slices"][0]["start_line"] <= first_file["slices"][0]["matched_line"] <= first_file["slices"][0]["end_line"]
    assert first_file["slices"][0]["read_request"]["tool_name"] == "read_file"
    assert "snippet" not in first_file["slices"][0]


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

    payload = asyncio.run(CodebaseSearchCapability(Path(".")).run(request=_request(), agent=_agent(), profile=profile, config=normalize_codebase_search_config({})))

    assert payload["status"] == "failed"
    assert "codebase_search_required_operation_missing" in payload["limitations"]
    assert "op.search_text" in payload["limitations"]
    assert payload["diagnostics"]["capability_id"] == "capability.codebase_search"


def test_query_planner_splits_symbols_roots_and_history_terms() -> None:
    plan = build_codebase_search_plan(
        "检查 backend/harness 的 AgentHarness loop control",
        max_queries=10,
        include_tests=True,
    )

    assert "backend" in plan.preferred_roots
    assert "backend/harness" in plan.path_queries
    assert "AgentHarness" in plan.symbol_queries
    assert {"loop", "control"} <= set(plan.text_queries)
    assert "AgentHarness" in plan.git_history_queries
    assert plan.git_history_queries
    assert not {"fallback", "legacy", "compat", "intent", "classifier"} & set(plan.text_queries)


def test_query_planner_extracts_symbols_from_natural_language_without_command_noise() -> None:
    plan = build_codebase_search_plan(
        "Find where SpecialistRuntimeRouter routes to CodebaseSearchCapability and where execute_task_run records the result.",
        max_queries=12,
        include_tests=True,
    )

    assert {"SpecialistRuntimeRouter", "CodebaseSearchCapability", "execute_task_run"} <= set(plan.symbol_queries)
    assert not {"Find", "where", "routes", "records", "result"} & set(plan.text_queries)
    assert "SpecialistRuntimeRouter" in plan.required_terms


def test_query_planner_treats_rag_test_data_as_local_evidence_discovery() -> None:
    plan = build_codebase_search_plan(
        "你能查到我项目里面的 RAG 测试数据和实验结果吗",
        max_queries=12,
        include_tests=True,
    )

    assert "scifact" in plan.preferred_roots
    assert "backend/tests/_artifacts" in plan.preferred_roots
    assert "output/benchmark_runtime" in plan.preferred_roots
    assert "scifact" in plan.path_queries
    assert "qrels" in plan.path_queries
    assert "_artifacts" in plan.path_queries
    assert "recall_at_10" in plan.text_queries
    assert "mrr_at_10" in plan.text_queries
    assert "scifact/**/*.jsonl" in plan.file_globs
    assert "backend/tests/_artifacts/scifact_v2*.json" in plan.file_globs
    assert "output/benchmark_runtime/**/*.json" in plan.file_globs


def test_codebase_search_natural_language_query_prioritizes_relevant_runtime_files() -> None:
    query = "Find where SpecialistRuntimeRouter routes to CodebaseSearchCapability and where execute_task_run records the result."

    payload = asyncio.run(
        CodebaseSearchCapability(Path(".")).run(
            request=_request(query),
            agent=_agent(),
            profile=_profile(include_git_history=False),
            config=normalize_codebase_search_config({"max_queries": 10, "max_text_results": 60, "max_file_slices": 8, "include_git_history": False}),
        )
    )

    top_files = [item["file"] for item in payload["findings"][:8]]
    assert "backend/harness/loop/specialist_runtime_router.py" in top_files
    assert "backend/harness/loop/task_executor.py" in top_files


def test_codebase_search_finds_rag_dataset_and_historical_eval_artifacts() -> None:
    query = "你能查到我项目里面的 RAG 测试数据和实验结果吗"

    payload = asyncio.run(
        CodebaseSearchCapability(Path(".")).run(
            request=_request(query),
            agent=_agent(),
            profile=_profile(include_git_history=False),
            config=normalize_codebase_search_config(
                {
                    "max_queries": 12,
                    "max_text_results": 120,
                    "max_path_results": 100,
                    "max_file_slices": 24,
                    "include_git_history": False,
                }
            ),
        )
    )

    files = {item["file"] for item in payload["findings"]}

    assert payload["status"] == "completed"
    assert "scifact/_beir_extract/scifact/qrels/test.tsv" in files
    assert any(path.startswith("backend/tests/_artifacts/scifact_v2") and path.endswith(".json") for path in files)
    assert {"scifact", "qrels", "_artifacts"} <= set(payload["diagnostics"]["plan"]["path_queries"])


def test_file_slicer_reads_bounded_context() -> None:
    slicer = FileSlicer(Path("."))

    result = slicer.slice_file(
        "backend/capability_system/capabilities/codebase_search/runtime.py",
        matched_line=15,
        max_slice_lines=30,
    )

    assert result is not None
    assert result.file == "backend/capability_system/capabilities/codebase_search/runtime.py"
    assert result.end_line - result.start_line + 1 <= 30
    assert "CodebaseSearchCapability" in result.snippet


def test_ranker_prioritizes_definitions_over_docs() -> None:
    hits = [
        TextHit(file="docs/implementation_plans/example.md", line=1, column=1, snippet="CodebaseSearchCapability design", query="CodebaseSearchCapability"),
        TextHit(file="backend/capability_system/agent_capabilities/codebase_search/runtime.py", line=14, column=1, snippet="class CodebaseSearchCapability:", query="CodebaseSearchCapability"),
    ]

    ranked = rank_codebase_evidence(hits, [], limit=2)

    assert ranked[0].file.endswith("runtime.py")
    assert ranked[0].evidence_kind == "definition"
    assert ranked[0].start_line == ranked[0].line
    assert ranked[0].end_line == ranked[0].line
    assert ranked[0].score > ranked[1].score


def test_missing_matches_returns_limitation_not_fake_evidence() -> None:
    missing_query = "definitely_missing_" + "code_symbol_zzzz_" + "20260525"
    payload = asyncio.run(
        CodebaseSearchCapability(Path(".")).run(
            request=_request(missing_query),
            agent=_agent(),
            profile=_profile(include_git_history=False),
            config=normalize_codebase_search_config({"max_queries": 2, "max_text_results": 4, "max_file_slices": 2, "include_git_history": False}),
        )
    )

    assert payload["status"] == "failed"
    assert payload["findings"] == []
    assert "codebase_search_no_evidence" in payload["limitations"]


