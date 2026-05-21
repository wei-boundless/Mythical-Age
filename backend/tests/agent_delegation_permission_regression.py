from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from orchestration.delegation_catalog import DelegationCatalogBuilder
from runtime.execution.agent_delegation_executor import AgentDelegationExecutor
from runtime.execution.delegation_models import AgentDelegationRequest
from runtime.shared.models import AgentRun


def test_delegation_catalog_filters_by_parent_agent_permission(tmp_path) -> None:
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    runtime_registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        allowed_runtime_lanes=("full_interactive",),
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        can_delegate_to_agents=False,
    )

    catalog = DelegationCatalogBuilder(tmp_path).build(parent_agent_id="agent:0")

    assert catalog["delegate_cards"] == []
    assert set(catalog["summary"]["blocked_reasons"]) == {"parent_delegation_not_authorized"}


def test_delegation_executor_blocks_when_parent_cannot_delegate(tmp_path) -> None:
    runtime_registry = AgentRuntimeRegistry(tmp_path)
    runtime_registry.upsert_profile(
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        allowed_runtime_lanes=("full_interactive",),
        allowed_operations=("op.model_response",),
        blocked_operations=(),
        can_delegate_to_agents=False,
    )
    executor = AgentDelegationExecutor(tmp_path)
    request = AgentDelegationRequest(
        request_id="delegation:req:test",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:taskrun:test:main",
        source_agent_id="agent:0",
        target_agent_id="agent:rag_analyst",
        delegation_kind="evidence_lookup",
        instruction="请检索证据并返回摘要。",
        input_payload={"question": "test"},
    )
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    result = executor.validate_request(request, parent_agent_run=parent_run)

    assert "parent_delegation_not_authorized" in result["blocked_reasons"]


def test_delegation_executor_blocks_target_disabled_by_search_policy(tmp_path) -> None:
    executor = AgentDelegationExecutor(tmp_path)
    request = AgentDelegationRequest(
        request_id="delegation:req:search-policy",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:taskrun:test:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="请联网核验最新资料。",
        input_payload={"question": "test"},
        diagnostics={"allowed_search_sources": ["rag", "local_files"]},
    )
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    result = executor.validate_request(request, parent_agent_run=parent_run)

    assert "target_agent_blocked_by_search_policy" in result["blocked_reasons"]


def test_delegation_executor_treats_empty_search_policy_as_no_sources(tmp_path) -> None:
    executor = AgentDelegationExecutor(tmp_path)
    request = AgentDelegationRequest(
        request_id="delegation:req:empty-search-policy",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:taskrun:test:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="请联网核验最新资料。",
        input_payload={"question": "test"},
        diagnostics={"allowed_search_sources": []},
    )
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    result = executor.validate_request(request, parent_agent_run=parent_run)

    assert "target_agent_blocked_by_search_policy" in result["blocked_reasons"]


def test_delegation_executor_blocks_nested_delegation(tmp_path) -> None:
    executor = AgentDelegationExecutor(tmp_path)
    request = AgentDelegationRequest(
        request_id="delegation:req:nested",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:taskrun:test:delegated",
        source_agent_id="agent:rag_analyst",
        target_agent_id="agent:pdf_reader",
        delegation_kind="pdf_reading",
        instruction="请阅读 PDF。",
        input_payload={"question": "test"},
    )
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:delegated",
        task_run_id="taskrun:test",
        agent_id="agent:rag_analyst",
        agent_profile_id="rag_analysis_agent",
        spawn_mode="delegation",
        status="running",
    )

    result = executor.validate_request(request, parent_agent_run=parent_run)

    assert "nested_delegation_denied" in result["blocked_reasons"]


def test_delegation_executor_resolves_builtin_alias_and_kind_to_registered_worker(tmp_path) -> None:
    executor = AgentDelegationExecutor(tmp_path)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )

    by_kind = AgentDelegationRequest(
        request_id="delegation:req:kind",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="",
        delegation_kind="pdf_reading",
        instruction="请阅读 PDF。",
        input_payload={"file_path": "knowledge/demo.pdf"},
    )
    normalized_by_kind = executor._normalize_request_target(by_kind, parent_agent_run=parent_run)

    assert normalized_by_kind.target_agent_id == "agent:pdf_reader"
    assert normalized_by_kind.diagnostics["resolved_target_agent_id"] == "agent:pdf_reader"

    by_alias = AgentDelegationRequest(
        request_id="delegation:req:alias",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="builtin-table-analyzer",
        delegation_kind="",
        instruction="请分析表格。",
        input_payload={"file_path": "knowledge/demo.xlsx"},
    )
    normalized_by_alias = executor._normalize_request_target(by_alias, parent_agent_run=parent_run)

    assert normalized_by_alias.target_agent_id == "agent:table_analyst"
    assert normalized_by_alias.diagnostics["resolved_target_agent_id"] == "agent:table_analyst"

    by_web_kind = AgentDelegationRequest(
        request_id="delegation:req:web-kind",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="",
        delegation_kind="web_research",
        instruction="请检索公开网页来源。",
        input_payload={"query": "official release notes"},
    )
    normalized_by_web_kind = executor._normalize_request_target(by_web_kind, parent_agent_run=parent_run)

    assert normalized_by_web_kind.target_agent_id == "agent:web_researcher"
    assert normalized_by_web_kind.diagnostics["resolved_target_agent_id"] == "agent:web_researcher"

    by_web_alias = AgentDelegationRequest(
        request_id="delegation:req:web-alias",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="builtin-web-researcher",
        delegation_kind="",
        instruction="请检索公开网页来源。",
        input_payload={"query": "official release notes"},
    )
    normalized_by_web_alias = executor._normalize_request_target(by_web_alias, parent_agent_run=parent_run)

    assert normalized_by_web_alias.target_agent_id == "agent:web_researcher"


def test_delegation_executor_runs_child_agent_through_profile_authorized_specialist_path(tmp_path) -> None:
    executor = AgentDelegationExecutor(tmp_path)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    request = AgentDelegationRequest(
        request_id="delegation:req:execute",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:pdf_reader",
        delegation_kind="pdf_reading",
        instruction="请阅读 PDF 并返回摘要。",
        input_payload={"file_path": "knowledge/demo.pdf"},
    )

    outcome = asyncio.run(
        executor.execute(
            request=request,
            parent_agent_run=parent_run,
            model_response_executor=None,
        )
    )
    result = outcome["result"]

    assert result.status == "failed"
    assert result.target_agent_id == "agent:pdf_reader"
    assert "model_runtime_unavailable" not in result.limitations
    assert result.diagnostics["child_execution_mode"] == "profile_authorized_specialist"


def test_delegation_executor_rejects_plan_text_as_invalid_output(tmp_path) -> None:
    async def _child_runner(_context):
        return {
            "status": "completed",
            "summary": "我将读取 PDF 文件并调用 op.mcp_pdf。",
            "answer_candidate": "我将读取 PDF 文件并调用 op.mcp_pdf。",
        }

    executor = AgentDelegationExecutor(tmp_path, child_runner=_child_runner)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    request = AgentDelegationRequest(
        request_id="delegation:req:invalid",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:pdf_reader",
        delegation_kind="pdf_reading",
        instruction="请阅读 PDF 并返回摘要。",
        input_payload={"file_path": "knowledge/demo.pdf"},
    )

    outcome = asyncio.run(executor.execute(request=request, parent_agent_run=parent_run))
    result = outcome["result"]

    assert result.status == "invalid_output"
    assert "pseudo_tool_text_without_execution_refs" in result.limitations
    assert result.diagnostics["quality_gate"]["status"] == "invalid"


def test_direct_delegation_does_not_create_coordination_run(tmp_path) -> None:
    async def _child_runner(_context):
        return {
            "status": "completed",
            "summary": "已完成证据摘要。",
            "answer_candidate": "已完成证据摘要。",
            "evidence_refs": ["ref:test"],
        }

    executor = AgentDelegationExecutor(tmp_path, child_runner=_child_runner)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    request = AgentDelegationRequest(
        request_id="delegation:req:direct",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:rag_analyst",
        delegation_kind="evidence_lookup",
        instruction="请检索证据。",
        input_payload={"query": "test"},
    )

    outcome = asyncio.run(executor.execute(request=request, parent_agent_run=parent_run))
    event_types = [event.event_type for event in outcome["events"]]
    child_runs = executor.state_index.list_task_agent_runs("taskrun:test")

    assert outcome["result"].status == "completed"
    assert outcome["observation"]["type"] == "agent_delegation_result"
    assert executor.state_index.list_task_coordination_runs("taskrun:test") == []
    assert all(run.coordination_run_ref == "" for run in child_runs)
    assert "coordination_run_created" not in event_types
    assert "coordination_node_run_created" not in event_types
    assert "handoff_envelope_created" not in event_types
    assert "agent_delegation_parent_observation_created" in event_types


def test_delegation_executor_fails_closed_on_child_timeout(tmp_path) -> None:
    async def _slow_child_runner(_context):
        await asyncio.sleep(1.0)
        return {
            "status": "completed",
            "summary": "迟到的结果不应进入本轮。",
        }

    executor = AgentDelegationExecutor(tmp_path, child_runner=_slow_child_runner)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    request = AgentDelegationRequest(
        request_id="delegation:req:timeout",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:rag_analyst",
        delegation_kind="evidence_lookup",
        instruction="请检索证据。",
        input_payload={"query": "test"},
        timeout_policy={"timeout_seconds": 0.01},
    )

    outcome = asyncio.run(executor.execute(request=request, parent_agent_run=parent_run))
    result = outcome["result"]

    assert result.status == "failed"
    assert "delegation_timeout" in result.limitations
    assert result.diagnostics["timeout_seconds"] == 1.0


def test_delegation_executor_enforces_max_delegate_calls_per_turn(tmp_path) -> None:
    async def _child_runner(_context):
        return {
            "status": "completed",
            "summary": "已完成证据摘要。",
            "answer_candidate": "已完成证据摘要。",
            "evidence_refs": ["ref:test"],
        }

    executor = AgentDelegationExecutor(tmp_path, child_runner=_child_runner)
    parent_run = AgentRun(
        agent_run_id="agrun:taskrun:test:main",
        task_run_id="taskrun:test",
        agent_id="agent:0",
        agent_profile_id="main_interactive_agent",
        status="running",
    )
    first = AgentDelegationRequest(
        request_id="delegation:req:first",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:rag_analyst",
        delegation_kind="evidence_lookup",
        instruction="请检索证据。",
        input_payload={"query": "test"},
    )
    second = AgentDelegationRequest(
        request_id="delegation:req:second",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref=parent_run.agent_run_id,
        source_agent_id="agent:0",
        target_agent_id="agent:rag_analyst",
        delegation_kind="evidence_lookup",
        instruction="请再次检索证据。",
        input_payload={"query": "test"},
    )

    asyncio.run(executor.execute(request=first, parent_agent_run=parent_run))
    outcome = asyncio.run(executor.execute(request=second, parent_agent_run=parent_run))

    assert outcome["result"].status == "blocked"
    assert "max_delegate_calls_per_turn_exceeded" in outcome["result"].limitations
