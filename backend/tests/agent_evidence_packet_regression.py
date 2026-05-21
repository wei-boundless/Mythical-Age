from __future__ import annotations

import asyncio
from pathlib import Path

from evidence.agent_evidence_packet import build_agent_evidence_packet_from_mcp_payload, build_agent_evidence_packet_from_web_payload
from evidence.mcp_models import MCPRequest
from orchestration.agent_registry import default_agent_descriptors
from runtime.execution.agent_delegation_executor import AgentDelegationExecutor
from runtime.execution.agent_delegation_executor import _child_system_prompt
from runtime.execution.child_agent_runtime_executor import ChildAgentRuntimeExecutor, _build_mcp_request
from runtime.execution.delegation_models import AgentDelegationRequest
from runtime.shared.models import AgentRun


def _request(*, route: str, query: str = "find evidence") -> MCPRequest:
    return MCPRequest(
        request_id=f"mcpreq:test:{route}",
        session_id="session-1",
        query=query,
        mcp_route=route,  # type: ignore[arg-type]
        owner_task_id="taskrun-1",
        agent_id=f"agent:{route}",
    )


def test_rag_payload_maps_evidence_to_facts_and_answer_to_hint() -> None:
    packet = build_agent_evidence_packet_from_mcp_payload(
        mcp_result_payload={
            "mcp_name": "retrieval",
            "status": "ok",
            "evidence_envelope": {
                "query": "AI risk",
                "source_mcp": "retrieval",
                "evidence_items": [
                    {
                        "kind": "document_chunk",
                        "source": "knowledge/report.md",
                        "text": "AI governance risk taxonomy lists safety, privacy, and accountability.",
                        "score": 0.92,
                        "metadata": {"artifact_id": "artifact:chunk:1", "path": "knowledge/report.md"},
                        "visibility": "model_visible",
                    }
                ],
            },
            "canonical_result": {
                "result_kind": "retrieval_answer",
                "ok": True,
                "answer": "The material appears to support three governance risk categories.",
            },
        },
        mcp_request=_request(route="retrieval", query="AI risk categories"),
        source_agent_id="agent:rag_reader",
        target_task_id="taskrun-1",
        task_goal="Use the knowledge base to collect evidence about AI risk categories.",
        domain="retrieval",
    )

    assert packet.domain == "rag"
    assert packet.facts
    assert "knowledge/report.md" in packet.facts[0].claim
    assert packet.hints
    assert packet.hints[0].basis_fact_ids == ("fact:1",)
    assert "support" in packet.hints[0].suggestion


def test_pdf_payload_keeps_page_state_as_evidence_boundary_not_final_answer() -> None:
    packet = build_agent_evidence_packet_from_mcp_payload(
        mcp_result_payload={
            "mcp_name": "pdf",
            "status": "degraded",
            "evidence_envelope": {
                "query": "read page 3",
                "source_mcp": "pdf",
                "evidence_items": [
                    {
                        "kind": "pdf_page_snapshot",
                        "source": "knowledge/report.pdf",
                        "text": "Page 3 contains only a title-like transition heading.",
                        "score": 0.81,
                        "metadata": {
                            "artifact_id": "artifact:pdf:page3",
                            "page_number": 3,
                            "target_page_state": "transition_title_only",
                        },
                        "visibility": "model_visible",
                    }
                ],
            },
            "canonical_result": {
                "result_kind": "pdf_answer",
                "ok": False,
                "answer": "Page 3 may be a transition page.",
                "degraded_reason_typed": "target_page_transition_title_only",
            },
        },
        mcp_request=_request(route="pdf", query="read page 3"),
        source_agent_id="agent:pdf_reader",
        target_task_id="taskrun-1",
        task_goal="Judge the role of page 3 in the PDF.",
        domain="pdf",
    )

    assert packet.domain == "pdf"
    assert packet.facts[0].source_refs == ("artifact:pdf:page3",)
    assert packet.hints[0].hint_id == "hint:canonical_answer"
    assert packet.unknowns
    assert packet.unknowns[0].description == "target_page_transition_title_only"
    assert packet.limits


def test_table_payload_preserves_method_and_data_fact() -> None:
    packet = build_agent_evidence_packet_from_mcp_payload(
        mcp_result_payload={
            "mcp_name": "structured_data",
            "status": "ok",
            "evidence_envelope": {
                "query": "top warehouse by shortage",
                "source_mcp": "structured_data",
                "evidence_items": [
                    {
                        "kind": "dataset_analysis",
                        "source": "data/inventory.csv",
                        "text": "Filtered rows where shortage > 0; sorted by shortage descending; WH-03 ranked first.",
                        "score": 1.0,
                        "metadata": {"artifact_id": "artifact:dataset:analysis", "path": "data/inventory.csv"},
                        "visibility": "model_visible",
                    }
                ],
                "diagnostics": {"dataset_path": "data/inventory.csv", "analysis_ok": True},
            },
            "canonical_result": {
                "result_kind": "structured_answer",
                "ok": True,
                "answer": "WH-03 has the largest shortage.",
                "diagnostics": {"mcp": "structured_data", "answer_source": "structured_data_worker"},
            },
            "diagnostics": {"tool_input": {"query": "top warehouse by shortage", "path": "data/inventory.csv"}},
        },
        mcp_request=_request(route="structured_data", query="top warehouse by shortage"),
        source_agent_id="agent:table_analyst",
        target_task_id="taskrun-1",
        task_goal="Analyze shortage ranking from the inventory table.",
        domain="structured_data",
    )

    assert packet.domain == "table"
    assert packet.confidence == "high"
    assert packet.method["mcp_route"] == "structured_data"
    assert packet.domain_payload["envelope_diagnostics"]["dataset_path"] == "data/inventory.csv"
    assert "WH-03" in packet.facts[0].claim


class _FakeChildRuntimeExecutor(ChildAgentRuntimeExecutor):
    async def _run_mcp(self, *, mcp_route: str, mcp_request: MCPRequest) -> dict[str, object]:
        return {
            "mcp_name": mcp_route,
            "status": "ok",
            "evidence_envelope": {
                "query": mcp_request.query,
                "source_mcp": mcp_route,
                "evidence_items": [
                    {
                        "kind": "dataset_analysis",
                        "source": "data/demo.csv",
                        "text": "The table contains 10 rows and the target metric is revenue.",
                        "score": 1.0,
                        "metadata": {"artifact_id": "artifact:demo"},
                        "visibility": "model_visible",
                    }
                ],
            },
            "canonical_result": {
                "result_kind": "structured_answer",
                "ok": True,
                "answer": "Revenue evidence was collected.",
                "evidence_refs": ["artifact:demo"],
                "artifact_refs": ["artifact:demo"],
            },
        }


class _FakeEvidenceOrchestrator:
    async def stream_execution(self, **_kwargs):
        yield {
            "type": "mcp_evidence",
            "evidence": {
                "query": "policy",
                "source_mcp": "retrieval",
                "evidence_items": [
                    {
                        "kind": "document_chunk",
                        "source": "knowledge/policy.md",
                        "text": "The policy requires evidence before synthesis.",
                        "score": 0.9,
                        "metadata": {"artifact_id": "artifact:policy"},
                        "visibility": "model_visible",
                    }
                ],
            },
        }
        yield {
            "type": "mcp_end",
            "task_status": "completed",
            "stream_event_type": "task.completed",
            "result": {
                "result_kind": "rag_answer",
                "ok": True,
                "answer": "Evidence collected.",
                "evidence_refs": ["artifact:policy"],
            },
        }
        yield {"type": "done", "result": {"ok": True, "answer": "Evidence collected."}}


class _FakeWebRuntimeExecutor(ChildAgentRuntimeExecutor):
    async def _run_web_search(self, *, query: str, topic: str, time_range: str, max_results: int) -> dict:
        return {
            "ok": True,
            "query": query,
            "topic": topic,
            "time_range": time_range,
            "results": [
                {
                    "title": "Official model release notes",
                    "url": "https://example.com/release",
                    "score": 0.91,
                    "published_date": "2026-05-01",
                    "content": "The official release notes describe the current model update.",
                }
            ],
        }


def test_child_agent_runtime_attaches_shadow_evidence_packet() -> None:
    executor = _FakeChildRuntimeExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:1",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:table_analyst",
        delegation_kind="structured_data",
        instruction="Analyze revenue evidence from the active table.",
        input_payload={"path": "data/demo.csv"},
    )
    agent = type("Agent", (), {"agent_id": "agent:table_analyst"})()
    profile = type("Profile", (), {"allowed_operations": ("op.mcp_structured_data",), "blocked_operations": ()})()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    diagnostics = dict(payload["diagnostics"])
    packet = dict(diagnostics["agent_evidence_packet"])
    assert payload["summary"] == "Revenue evidence was collected."
    assert packet["domain"] == "table"
    assert packet["facts"]
    assert "visible_packet_summary" in diagnostics
    assert "Revenue evidence" in diagnostics["visible_packet_summary"]


def test_child_agent_runtime_keeps_orchestrator_evidence_envelope() -> None:
    executor = ChildAgentRuntimeExecutor(root_dir=Path("."), evidence_orchestrator=_FakeEvidenceOrchestrator())
    request = AgentDelegationRequest(
        request_id="delegation:req:orchestrator",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:rag_analyst",
        delegation_kind="retrieval",
        instruction="Collect evidence from the knowledge base.",
        input_payload={"query": "policy"},
    )
    agent = type("Agent", (), {"agent_id": "agent:rag_analyst"})()
    profile = type("Profile", (), {"allowed_operations": ("op.mcp_retrieval",), "blocked_operations": ()})()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    packet = dict(dict(payload["diagnostics"])["agent_evidence_packet"])
    assert packet["domain"] == "rag"
    assert len(packet["facts"]) == 1
    assert len(packet["evidence"]) == 1
    assert packet["facts"][0]["source_refs"] == ["artifact:policy"]


def test_web_payload_maps_search_results_to_web_evidence_packet() -> None:
    packet = build_agent_evidence_packet_from_web_payload(
        web_payload={
            "ok": True,
            "query": "official model release notes",
            "topic": "general",
            "results": [
                {
                    "title": "Official model release notes",
                    "url": "https://example.com/release",
                    "score": 0.91,
                    "published_date": "2026-05-01",
                    "content": "The official release notes describe the current model update.",
                }
            ],
        },
        source_agent_id="agent:web_researcher",
        target_task_id="taskrun-1",
        task_goal="Find official release evidence.",
    )

    assert packet.domain == "web"
    assert packet.facts
    assert packet.evidence[0].locator["host"] == "example.com"
    assert packet.evidence[0].visibility == "model_visible"
    assert packet.confidence in {"high", "medium"}


def test_child_agent_runtime_runs_web_research_specialist_path() -> None:
    executor = _FakeWebRuntimeExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:web",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find official release evidence.",
        input_payload={"query": "official model release notes", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type("Profile", (), {"allowed_operations": ("op.web_search",), "blocked_operations": ()})()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    packet = dict(dict(payload["diagnostics"])["agent_evidence_packet"])
    assert payload["status"] == "completed"
    assert payload["diagnostics"]["specialist_route"] == "web_research"
    assert packet["domain"] == "web"
    assert packet["facts"]


def test_child_agent_mcp_request_uses_first_file_paths_entry_for_pdf() -> None:
    request = AgentDelegationRequest(
        request_id="delegation:req:file-paths",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:pdf_reader",
        delegation_kind="pdf_reading",
        instruction="Read the supplied PDFs.",
        input_payload={"file_paths": ["knowledge/a.pdf", "knowledge/b.pdf"]},
    )

    mcp_request = _build_mcp_request(request, mcp_route="pdf", agent_id="agent:pdf_reader")

    assert mcp_request.bindings["active_pdf"] == "knowledge/a.pdf"
    assert mcp_request.constraints["path"] == "knowledge/a.pdf"


def test_delegation_result_records_shadow_readiness_without_changing_summary() -> None:
    executor = AgentDelegationExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:2",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:rag_analyst",
        delegation_kind="retrieval",
        instruction="Collect evidence from the knowledge base.",
        input_payload={},
    )
    child_run = AgentRun(
        agent_run_id="agrun:child",
        task_run_id="taskrun-1",
        agent_id="agent:rag_analyst",
        agent_profile_id="profile:rag",
    )
    packet = build_agent_evidence_packet_from_mcp_payload(
        mcp_result_payload={
            "mcp_name": "retrieval",
            "status": "ok",
            "evidence_envelope": {
                "query": "policy",
                "source_mcp": "retrieval",
                "evidence_items": [
                    {
                        "kind": "document_chunk",
                        "source": "knowledge/policy.md",
                        "text": "The policy requires evidence before synthesis.",
                        "score": 0.9,
                        "metadata": {"artifact_id": "artifact:policy"},
                    }
                ],
            },
            "canonical_result": {"result_kind": "retrieval_answer", "ok": True, "answer": "Evidence collected."},
        },
        mcp_request=_request(route="retrieval", query="policy"),
        source_agent_id="agent:rag_analyst",
        target_task_id="taskrun-1",
        task_goal="Collect evidence from the knowledge base.",
        domain="retrieval",
    )

    result = executor.normalize_child_output(
        request=request,
        child_agent_run=child_run,
        child_payload={
            "status": "completed",
            "summary": "Evidence collected.",
            "answer_candidate": "Evidence collected.",
            "diagnostics": {"agent_evidence_packet": packet.to_dict()},
        },
        status="completed",
    )

    shadow = dict(result.diagnostics["agent_evidence_shadow_readiness"])
    assert result.summary == "Evidence collected."
    assert shadow["mode"] == "shadow_only"
    assert shadow["evidence_sufficient"] is True
    assert shadow["summary_is_primary_path"] is True


def test_builtin_specialist_agents_have_default_professional_projections() -> None:
    agents = {item.agent_id: item for item in default_agent_descriptors(now=1.0)}

    assert agents["agent:rag_analyst"].default_projection_id == "projection.worker.rag_evidence_analyst"
    assert agents["agent:pdf_reader"].default_projection_id == "projection.worker.pdf_evidence_reader"
    assert agents["agent:table_analyst"].default_projection_id == "projection.worker.table_evidence_analyst"
    assert agents["agent:web_researcher"].default_projection_id == "projection.worker.web_evidence_researcher"
    assert agents["agent:rag_analyst"].default_soul_id == "hebo"
    assert agents["agent:pdf_reader"].default_soul_id == "hebo"
    assert agents["agent:table_analyst"].default_soul_id == "hebo"
    assert agents["agent:web_researcher"].default_soul_id == "hebo"


def test_child_fallback_prompt_uses_projection_identity_and_work_style() -> None:
    agent = type(
        "Agent",
        (),
        {
            "description": "old description",
            "default_projection_id": "projection.worker.pdf_evidence_reader",
        },
    )()
    profile = type("Profile", (), {"allowed_operations": ("op.model_response", "op.mcp_pdf")})()
    projection_card = {
        "identity_anchor": "你是一名 PDF 阅读与证据整理员。你负责阅读指定 PDF。",
        "projection_prompt": "## 工作职责\n\n你要区分正文页、目录页、过渡页、相关页、结论页。",
    }

    prompt = _child_system_prompt(agent, profile, projection_card=projection_card)

    assert "PDF 阅读与证据整理员" in prompt
    assert "目录页、过渡页" in prompt
    assert "主 Agent" in prompt
    assert "old description" not in prompt
