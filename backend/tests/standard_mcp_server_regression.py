from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration import ResourcePolicy
from mcp_server.local_capability_server import LocalCapabilityMCPExecutor, LocalMCPToolRequest
from mcp_server.server import build_server
from mcp_server.tool_pool import build_mcp_tool_pool


class _OrchestratorStub:
    async def stream_execution(self, *, session_id, execution, mcp_plan, main_context, trace):
        route = mcp_plan.mcp_route
        yield {
            "type": "done",
            "status": "ok",
            "mcp_result": SimpleNamespace(
                to_dict=lambda: {
                    "status": "ok",
                    "canonical_result": {
                        "ok": True,
                        "answer": f"{route} answer",
                    },
                    "evidence_envelope": {
                        "query": mcp_plan.request.query,
                        "source_mcp": route,
                    },
                    "diagnostics": {"route": route},
                }
            ).to_dict(),
            "main_context": {"answer_source": route},
            "task_summary_refs": [],
        }


def test_standard_mcp_server_lists_tools() -> None:
    server = build_server(
        backend_dir=BACKEND_DIR,
        executor=LocalCapabilityMCPExecutor(
            backend_dir=BACKEND_DIR,
            orchestrator=_OrchestratorStub(),
        ),
    )

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}

    assert {
        "langchain_agent_list_capabilities",
        "langchain_agent_search_knowledge",
        "langchain_agent_analyze_pdf",
        "langchain_agent_analyze_structured_data",
    }.issubset(tool_names)


def test_standard_mcp_executor_routes_registered_units() -> None:
    executor = LocalCapabilityMCPExecutor(
        backend_dir=BACKEND_DIR,
        orchestrator=_OrchestratorStub(),
    )

    result = executor.execute_sync(
        LocalMCPToolRequest(
            route="pdf",
            query="总结",
            path="docs/example.pdf",
            mode="document",
        )
    )

    assert result["status"] == "ok"
    assert result["route"] == "pdf"
    assert result["operation_id"] == "op.mcp_pdf"
    assert result["answer"] == "pdf answer"


def test_standard_mcp_tool_call_executes_registered_unit() -> None:
    server = build_server(
        backend_dir=BACKEND_DIR,
        executor=LocalCapabilityMCPExecutor(
            backend_dir=BACKEND_DIR,
            orchestrator=_OrchestratorStub(),
        ),
    )

    result = asyncio.run(
        server._tool_manager.call_tool(
            "langchain_agent_analyze_structured_data",
            {
                "params": {
                    "query": "统计缺货",
                    "path": "storage/example.csv",
                    "session_id": "test-session",
                }
            },
            convert_result=False,
        )
    )

    assert result["status"] == "ok"
    assert result["route"] == "structured_data"
    assert result["operation_id"] == "op.mcp_structured_data"


def test_standard_mcp_server_exposes_resources_and_prompts() -> None:
    server = build_server(
        backend_dir=BACKEND_DIR,
        executor=LocalCapabilityMCPExecutor(
            backend_dir=BACKEND_DIR,
            orchestrator=_OrchestratorStub(),
        ),
    )

    resources = {str(resource.uri) for resource in server._resource_manager.list_resources()}
    templates = {str(template.uri_template) for template in server._resource_manager.list_templates()}
    prompts = {prompt.name for prompt in server._prompt_manager.list_prompts()}

    assert "local-mcp://catalog" in resources
    assert "local-mcp://tool-pool" in resources
    assert "skill://catalog" in resources
    assert "skill://{name}" in templates
    assert "local-mcp://capability/{route}" in templates
    assert "langchain_agent_capability_prompt" in prompts
    assert "langchain_agent_skill_prompt" in prompts


def test_standard_mcp_executor_uses_operation_gate_fail_closed() -> None:
    executor = LocalCapabilityMCPExecutor(
        backend_dir=BACKEND_DIR,
        orchestrator=_OrchestratorStub(),
        resource_policy=ResourcePolicy(
            policy_id="respol:test:deny",
            task_id="test",
            denied_operations=("op.mcp_pdf",),
            runtime_view_only=False,
            adopted=True,
            runtime_executable=True,
        ),
    )

    result = executor.execute_sync(
        LocalMCPToolRequest(route="pdf", query="总结", path="docs/example.pdf")
    )

    assert result["status"] == "error"
    assert result["error"] == "operation_gate_denied"
    assert result["authorization"]["pipeline_stage"] == "deny_rule"


def test_mcp_tool_pool_merges_builtin_and_mcp_tools_stably() -> None:
    pool = build_mcp_tool_pool(backend_dir=BACKEND_DIR)
    entries = list(pool["entries"])
    names = [entry["name"] for entry in entries]
    entry_ids = [entry["entry_id"] for entry in entries]

    assert names == sorted(names[: len([entry for entry in entries if entry["source"] == "builtin_tool"])]) + sorted(
        names[len([entry for entry in entries if entry["source"] == "builtin_tool"]):]
    )
    assert entry_ids == sorted(entry_ids, key=lambda entry_id: next(item["discovery_priority"] for item in entries if item["entry_id"] == entry_id))
    assert "read_file" in names
    assert "mcp__langchain_agent__pdf" in names
    assert pool["merge_policy"] == "stable_priority_then_kind_then_name"
    assert pool["dedupe_key"] == "entry_id"
    pdf_entry = next(entry for entry in entries if entry["name"] == "mcp__langchain_agent__pdf")
    assert pdf_entry["entry_kind"] == "local_mcp"
    assert pdf_entry["model_visibility"] == "runtime_delegate_only"
    assert pdf_entry["runtime_exposure"] == "local_mcp_delegate"
