from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage

from evidence.agent_evidence_packet import build_agent_evidence_packet_from_mcp_payload, build_agent_evidence_packet_from_web_payload
from evidence.mcp_models import MCPRequest
from agent_system.registry.agent_registry import default_agent_descriptors
from harness.execution.agent_delegation_executor import AgentDelegationExecutor
from harness.execution.delegation_review import child_system_prompt
from harness.execution.child_agent_capability_executor import ChildAgentCapabilityExecutor, _build_mcp_request
from harness.execution.delegation_models import AgentDelegationRequest
from capability_system.agent_capabilities.deepsearch import DeepSearchCapability, normalize_runtime_config
from capability_system.agent_capabilities.deepsearch.evidence_builder import build_deepsearch_evidence_packet
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


class _FakeChildCapabilityExecutor(ChildAgentCapabilityExecutor):
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


class _FakeWebCapabilityExecutor(ChildAgentCapabilityExecutor):
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


class _FakeDeepSearchProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config) -> dict:
        self.queries.append(query)
        return {
            "ok": True,
            "query": query,
            "topic": topic,
            "time_range": time_range,
            "results": [
                {
                    "title": f"Official source for {query}",
                    "url": f"https://example.com/{len(self.queries)}",
                    "score": 0.92,
                    "published_date": "2026-05-01",
                    "content": f"Evidence collected for {query}.",
                }
            ],
        }


class _GapThenOfficialProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config) -> dict:
        self.queries.append(query)
        if "official announcement" in query:
            return {
                "ok": True,
                "query": query,
                "topic": topic,
                "time_range": time_range,
                "results": [
                    {
                        "title": "Official announcement",
                        "url": "https://example.gov/announcement",
                        "score": 0.96,
                        "published_date": "2026-05-02",
                        "content": "Official announcement confirms the evidence.",
                    }
                ],
            }
        return {
            "ok": True,
            "query": query,
            "topic": topic,
            "time_range": time_range,
            "results": [
                {
                    "title": "Community discussion",
                    "url": "https://example.com/community",
                    "score": 0.7,
                    "content": "A non-primary source discusses the topic.",
                }
            ],
        }


class _FakeFetchProvider:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch(self, *, url: str) -> dict:
        self.urls.append(url)
        return {"ok": True, "url": url, "content": f"Fetched content from {url}"}


class _HtmlFetchProvider:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch(self, *, url: str) -> dict:
        self.urls.append(url)
        return {
            "ok": True,
            "url": url,
            "content_type": "text/html",
            "content": """
            <!DOCTYPE html><html><head><title>Official announcement</title>
            <style>body{display:none}</style></head><body>
            <header>Navigation</header>
            <main><p>Official announcement confirms the policy update with primary evidence.</p></main>
            </body></html>
            """,
        }


class _LargeFetchProvider:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch(self, *, url: str) -> dict:
        self.urls.append(url)
        return {
            "ok": True,
            "url": url,
            "content_type": "text/html",
            "content": (
                "<html><body><main>"
                "<p>Official announcement confirms the policy update with primary evidence.</p>"
                + "<p>Long supporting detail about implementation, dates, scope, and provenance.</p>" * 220
                + "</main></body></html>"
            ),
        }


class _ModelDistillerRuntime:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.messages: list[list[dict[str, str]]] = []

    async def invoke_messages(self, messages, **_kwargs):
        self.messages.append(list(messages))
        if isinstance(self.content, Exception):
            raise self.content
        return AIMessage(content=self.content)


class _SequentialModelDistillerRuntime:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.messages: list[list[dict[str, str]]] = []

    async def invoke_messages(self, messages, **_kwargs):
        self.messages.append(list(messages))
        if len(self.messages) <= len(self.contents):
            return AIMessage(content=self.contents[len(self.messages) - 1])
        return AIMessage(content=self.contents[-1])


def test_child_agent_capability_attaches_shadow_evidence_packet() -> None:
    executor = _FakeChildCapabilityExecutor(root_dir=Path("."))
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


def test_child_agent_capability_does_not_substitute_specialist_for_unknown_delegation_kind() -> None:
    executor = _FakeChildCapabilityExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:unknown-kind",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:pdf_reader",
        delegation_kind="bounded_analysis",
        instruction="Analyze the supplied material.",
        input_payload={"path": "knowledge/demo.pdf"},
    )
    agent = type("Agent", (), {"agent_id": "agent:pdf_reader"})()
    profile = type("Profile", (), {"allowed_operations": ("op.mcp_pdf",), "blocked_operations": ()})()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    assert payload["status"] == "failed"
    assert payload["limitations"] == ["child_operation_not_authorized"]
    assert payload["diagnostics"]["child_execution_mode"] == "profile_authorized_specialist"


def test_child_agent_capability_keeps_orchestrator_evidence_envelope() -> None:
    executor = ChildAgentCapabilityExecutor(root_dir=Path("."), evidence_orchestrator=_FakeEvidenceOrchestrator())
    request = AgentDelegationRequest(
        request_id="delegation:req:orchestrator",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:knowledge_searcher",
        delegation_kind="retrieval",
        instruction="Collect evidence from the knowledge base.",
        input_payload={"query": "policy"},
    )
    agent = type("Agent", (), {"agent_id": "agent:knowledge_searcher"})()
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


def test_web_payload_cleans_html_before_fact_extraction() -> None:
    packet = build_agent_evidence_packet_from_web_payload(
        web_payload={
            "ok": True,
            "query": "OpenAI web search docs",
            "topic": "general",
            "results": [
                {
                    "title": "Web search | OpenAI API",
                    "url": "https://developers.openai.com/api/docs/guides/tools-web-search",
                    "score": 0.95,
                    "raw_content": """
                    <!DOCTYPE html><html><head><title>Web search | OpenAI API</title>
                    <meta name="description" content="Search the web using OpenAI API tools.">
                    <script>window.__noise = true;</script></head>
                    <body><nav>Docs nav</nav><main>
                    <h1>Web search</h1>
                    <p>Allow models to search the web for up-to-date information before generating a response.</p>
                    <p>&lt;meta name="escaped-noise" content="should not survive"&gt;</p>
                    <p>The web search tool is available through the Responses API.</p>
                    </main></body></html>
                    """,
                }
            ],
        },
        source_agent_id="agent:web_researcher",
        target_task_id="taskrun-1",
        task_goal="Find official web search documentation.",
    )

    fact = packet.facts[0].claim
    assert "Responses API" in fact
    assert "<!DOCTYPE" not in fact
    assert "<meta" not in fact
    assert "escaped-noise" not in fact
    assert "window.__noise" not in fact


def test_deepsearch_evidence_builder_ranks_official_sources_and_extracts_short_facts() -> None:
    packet = build_deepsearch_evidence_packet(
        web_payload={
            "ok": True,
            "query": "OpenAI Responses API web search tool official documentation",
            "topic": "general",
            "usage": {"queries_executed": 2, "fetches_executed": 1},
            "results": [
                {
                    "title": "Blog tutorial",
                    "url": "https://medium.com/example/openai-responses-api",
                    "score": 0.98,
                    "clean_text": "A blog explains the Responses API and mentions web search examples.",
                },
                {
                    "title": "Web search | OpenAI API",
                    "url": "https://developers.openai.com/api/docs/guides/tools-web-search",
                    "score": 0.82,
                    "clean_text": "Allow models to search the web for the latest information before generating a response. The web search tool is available through the Responses API.",
                },
            ],
            "deepsearch": {"stop_reason": "enough_evidence"},
        },
        source_agent_id="agent:web_researcher",
        target_task_id="taskrun-1",
        task_goal="Find official web search documentation.",
    )

    ranking = packet.domain_payload["source_ranking"]
    assert ranking[0]["host"] == "developers.openai.com"
    assert ranking[0]["source_type"] == "official"
    assert packet.facts[0].scope == "deepsearch.official"
    assert packet.facts[0].source_refs == ("web:evidence:1",)
    assert "Responses API" in packet.facts[0].claim
    assert len(packet.facts[0].claim) < 430
    assert packet.confidence == "high"


def test_child_agent_capability_runs_web_research_specialist_path() -> None:
    executor = _FakeWebCapabilityExecutor(root_dir=Path("."))
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


def test_child_agent_capability_uses_deepsearch_runtime_config_without_fetch_permission() -> None:
    search_provider = _FakeDeepSearchProvider()
    fetch_provider = _FakeFetchProvider()

    def capability_factory(root_dir: Path) -> DeepSearchCapability:
        return DeepSearchCapability(root_dir, search_provider=search_provider, fetch_provider=fetch_provider)

    executor = ChildAgentCapabilityExecutor(root_dir=Path("."), search_capability_factory=capability_factory)
    request = AgentDelegationRequest(
        request_id="delegation:req:deepsearch",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find current official release evidence.",
        input_payload={"query": "official model release notes", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {
                "runtime_template_id": "builtin.specialist.web_researcher",
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "runtime_kind": "search_agent",
                    "runtime_mode": "deepsearch",
                    "search": {
                        "runtime_mode": "deepsearch",
                        "allow_fetch_url": False,
                        "max_queries": 2,
                        "max_fetches": 0,
                        "max_sources": 4,
                    },
                },
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    diagnostics = dict(payload["diagnostics"])
    packet = dict(diagnostics["agent_evidence_packet"])
    assert payload["status"] == "completed"
    assert diagnostics["child_execution_mode"] == "profile_authorized_deepsearch_capability"
    assert diagnostics["capability_id"] == "capability.deepsearch"
    assert len(search_provider.queries) == 2
    assert fetch_provider.urls == []
    assert packet["domain"] == "web"
    assert packet["facts"]


def test_child_agent_capability_requires_fetch_permission_only_when_fetch_enabled() -> None:
    executor = ChildAgentCapabilityExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:deepsearch-fetch",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find current official release evidence.",
        input_payload={"query": "official model release notes"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {"allow_fetch_url": True, "max_fetches": 1},
                },
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    assert payload["status"] == "failed"
    assert "deepsearch_required_operation_missing" in payload["limitations"]
    assert "op.fetch_url" in payload["limitations"]


def test_deepsearch_strategy_adds_next_query_from_evidence_gap() -> None:
    search_provider = _GapThenOfficialProvider()
    fetch_provider = _FakeFetchProvider()

    def capability_factory(root_dir: Path) -> DeepSearchCapability:
        return DeepSearchCapability(root_dir, search_provider=search_provider, fetch_provider=fetch_provider)

    executor = ChildAgentCapabilityExecutor(root_dir=Path("."), search_capability_factory=capability_factory)
    request = AgentDelegationRequest(
        request_id="delegation:req:strategy-gap",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find primary evidence for a policy update.",
        input_payload={"query": "policy update", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "runtime_mode": "deepsearch",
                        "allow_fetch_url": False,
                        "max_queries": 3,
                        "max_fetches": 0,
                        "max_sources": 5,
                        "prefer_primary_sources": True,
                    },
                },
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    state = dict(payload["diagnostics"]["research_state"])
    deepsearch = dict(payload["diagnostics"]["web_payload"]["deepsearch"])
    assert payload["status"] == "completed"
    assert any("official announcement" in query for query in search_provider.queries)
    assert any("primary_source_missing" in review["gaps"] for review in deepsearch["reviews"])
    assert deepsearch["final_synthesis"]["covered_questions"]
    assert state["final_synthesis"]["stop_reason"] in {"enough_evidence", "query_budget_exhausted", "enough_sources"}


def test_deepsearch_fetch_cleans_html_before_evidence_packet() -> None:
    search_provider = _GapThenOfficialProvider()
    fetch_provider = _HtmlFetchProvider()

    def capability_factory(root_dir: Path) -> DeepSearchCapability:
        return DeepSearchCapability(root_dir, search_provider=search_provider, fetch_provider=fetch_provider)

    executor = ChildAgentCapabilityExecutor(root_dir=Path("."), search_capability_factory=capability_factory)
    request = AgentDelegationRequest(
        request_id="delegation:req:clean-html",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find primary evidence for a policy update.",
        input_payload={"query": "policy update", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search", "op.fetch_url"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "runtime_mode": "deepsearch",
                        "allow_fetch_url": True,
                        "max_queries": 3,
                        "max_fetches": 1,
                        "max_sources": 5,
                        "prefer_primary_sources": True,
                    },
                },
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    facts = list(dict(payload["diagnostics"]["agent_evidence_packet"])["facts"])
    ranking = list(dict(payload["diagnostics"]["agent_evidence_packet"])["domain_payload"]["source_ranking"])
    claims = "\n".join(str(item["claim"]) for item in facts)
    assert payload["status"] == "completed"
    assert ranking
    assert ranking[0]["source_type"] in {"official", "primary"}
    assert "Official announcement confirms the policy update" in claims
    assert "<!DOCTYPE" not in claims
    assert "<style" not in claims
    assert "Navigation" not in claims


def test_deepsearch_persists_large_tool_results_and_keeps_distilled_evidence(tmp_path: Path) -> None:
    search_provider = _GapThenOfficialProvider()
    fetch_provider = _LargeFetchProvider()

    def capability_factory(root_dir: Path) -> DeepSearchCapability:
        return DeepSearchCapability(root_dir, search_provider=search_provider, fetch_provider=fetch_provider)

    executor = ChildAgentCapabilityExecutor(root_dir=tmp_path, search_capability_factory=capability_factory)
    request = AgentDelegationRequest(
        request_id="delegation:req:large-result",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find primary evidence for a policy update.",
        input_payload={"query": "policy update", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search", "op.fetch_url"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "runtime_mode": "deepsearch",
                        "allow_fetch_url": True,
                        "max_queries": 2,
                        "max_fetches": 1,
                        "max_sources": 4,
                        "prefer_primary_sources": True,
                        "tool_result_field_limit_bytes": 1200,
                        "tool_result_preview_bytes": 300,
                        "tool_result_payload_budget_bytes": 3000,
                    },
                },
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    diagnostics = dict(payload["diagnostics"])
    replacements = list(diagnostics["content_replacements"])
    packet = dict(diagnostics["agent_evidence_packet"])
    facts = "\n".join(str(item["claim"]) for item in packet["facts"])
    assert payload["status"] == "completed"
    assert replacements
    assert Path(str(replacements[0]["path"])).exists()
    assert "<persisted-output>" in str(diagnostics["web_payload"])
    assert "Long supporting detail" not in facts
    assert "Official announcement confirms the policy update" in facts
    assert payload["artifact_refs"]
    assert packet["domain_payload"]["distilled_claim_count"] >= 1
    assert packet["evidence"][0]["locator"]["artifact_ref"]


def test_deepsearch_uses_model_backed_distiller_when_model_runtime_available() -> None:
    search_provider = _FakeDeepSearchProvider()
    model_runtime = _ModelDistillerRuntime(
        """
        {
          "claims": [
            {
              "claim": "The model distiller selected the strongest official source.",
              "source_url": "https://example.com/1",
              "source_title": "Official source for official model release notes",
              "source_type": "official",
              "confidence": "high",
              "excerpt": "Evidence collected for official model release notes."
            }
          ],
          "unknowns": [],
          "conflicts": []
        }
        """
    )
    executor = ChildAgentCapabilityExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:model-distiller",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find current official release evidence.",
        input_payload={"query": "official model release notes", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {"allow_fetch_url": False, "max_queries": 1, "max_fetches": 0, "max_sources": 3},
                },
            },
        },
    )()
    runtime = DeepSearchCapability(Path("."), search_provider=search_provider, model_runtime=model_runtime)

    runtime_config = normalize_runtime_config(profile.metadata["runtime_config"])
    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=runtime_config.search))

    packet = dict(payload["diagnostics"]["agent_evidence_packet"])
    assert payload["status"] == "completed"
    assert payload["diagnostics"]["distillation"]["method"] == "model_distiller"
    assert "model distiller selected" in packet["facts"][0]["claim"]
    assert model_runtime.messages


def test_deepsearch_model_distiller_falls_back_when_model_fails() -> None:
    search_provider = _FakeDeepSearchProvider()
    model_runtime = _ModelDistillerRuntime(RuntimeError("boom"))
    runtime = DeepSearchCapability(Path("."), search_provider=search_provider, model_runtime=model_runtime)
    request = AgentDelegationRequest(
        request_id="delegation:req:model-distiller-fallback",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find current official release evidence.",
        input_payload={"query": "official model release notes", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {},
        },
    )()
    config = normalize_runtime_config({"template_id": "runtime.template.deepsearch", "search": {"allow_fetch_url": False, "max_queries": 1, "max_fetches": 0}}).search
    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=config))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["distillation"]["method"] == "deterministic_distiller_fallback"
    assert any("model_distiller_failed" in item for item in payload["limitations"])


def test_deepsearch_adds_followup_queries_from_distilled_unknowns() -> None:
    search_provider = _FakeDeepSearchProvider()
    model_runtime = _SequentialModelDistillerRuntime(
        [
            """
            {
              "claims": [
                {
                  "claim": "Initial source says the feature exists.",
                  "source_url": "https://example.com/1",
                  "source_title": "Official source for official model release notes",
                  "source_type": "official",
                  "confidence": "medium",
                  "excerpt": "Evidence collected for official model release notes."
                }
              ],
              "unknowns": ["Supported models and response structure are still unclear."],
              "conflicts": []
            }
            """,
            """
            {
              "claims": [
                {
                  "claim": "Follow-up evidence clarifies supported models and response structure.",
                  "source_url": "https://example.com/2",
                  "source_title": "Official source for official model release notes supported models",
                  "source_type": "official",
                  "confidence": "high",
                  "excerpt": "Evidence collected for official model release notes supported models."
                }
              ],
              "unknowns": [],
              "conflicts": []
            }
            """,
        ]
    )
    runtime = DeepSearchCapability(Path("."), search_provider=search_provider, model_runtime=model_runtime)
    request = AgentDelegationRequest(
        request_id="delegation:req:followup-unknowns",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find current official release evidence.",
        input_payload={"query": "official model release notes", "topic": "general"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search"),
            "blocked_operations": (),
            "metadata": {},
        },
    )()
    config = normalize_runtime_config(
        {
            "template_id": "runtime.template.deepsearch",
            "search": {"allow_fetch_url": False, "max_queries": 4, "max_fetches": 0, "max_sources": 6},
        }
    ).search
    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=config))

    executed = list(payload["diagnostics"]["web_payload"]["deepsearch"]["executed_queries"])
    reviews = list(payload["diagnostics"]["web_payload"]["deepsearch"]["reviews"])
    assert payload["status"] == "completed"
    assert len(model_runtime.messages) >= 2
    assert any("supported models" in query for query in executed)
    assert any(review["stop_reason"] == "distilled_evidence_gap" for review in reviews)
    assert "Follow-up evidence clarifies" in payload["diagnostics"]["agent_evidence_packet"]["facts"][0]["claim"]


def test_child_agent_capability_ignores_legacy_runtime_template_id_for_deepsearch() -> None:
    executor = _FakeWebCapabilityExecutor(root_dir=Path("."))
    request = AgentDelegationRequest(
        request_id="delegation:req:legacy-template",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find official release evidence.",
        input_payload={"query": "official model release notes"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "agent_id": "agent:web_researcher",
            "allowed_operations": ("op.web_search",),
            "blocked_operations": (),
            "metadata": {"runtime_template_id": "runtime.template.deepsearch"},
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "profile_authorized_specialist"
    assert payload["diagnostics"]["specialist_route"] == "web_research"


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
        target_agent_id="agent:knowledge_searcher",
        delegation_kind="retrieval",
        instruction="Collect evidence from the knowledge base.",
        input_payload={},
    )
    child_run = AgentRun(
        agent_run_id="agrun:child",
        task_run_id="taskrun-1",
        agent_id="agent:knowledge_searcher",
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
        source_agent_id="agent:knowledge_searcher",
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


def test_parent_observation_microcompacts_large_child_answer_with_evidence_summary(tmp_path: Path) -> None:
    executor = AgentDelegationExecutor(root_dir=tmp_path)
    request = AgentDelegationRequest(
        request_id="delegation:req:compact-child",
        task_run_id="taskrun-1",
        session_id="session-1",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:main",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Collect evidence.",
        input_payload={},
    )
    child_run = AgentRun(
        agent_run_id="agrun:child",
        task_run_id="taskrun-1",
        agent_id="agent:web_researcher",
        agent_profile_id="profile:web",
    )
    packet = build_deepsearch_evidence_packet(
        web_payload={
            "ok": True,
            "query": "official docs",
            "topic": "general",
            "results": [
                {
                    "title": "Official docs",
                    "url": "https://developers.example.com/docs",
                    "score": 0.95,
                    "clean_text": "Official documentation confirms the evidence.",
                }
            ],
        },
        source_agent_id="agent:web_researcher",
        target_task_id="taskrun-1",
        task_goal="Collect evidence.",
    )
    result = executor.normalize_child_output(
        request=request,
        child_agent_run=child_run,
        child_payload={
            "status": "completed",
            "summary": "Evidence collected.",
            "answer_candidate": "LONG-ANSWER " * 2000,
            "evidence_refs": ["web:evidence:1"],
            "artifact_refs": ["artifact:web:1"],
            "diagnostics": {
                "agent_evidence_packet": packet.to_dict(),
                "visible_packet_summary": packet.visible_summary(),
            },
        },
        status="completed",
    )

    observation = executor.build_parent_observation(result)

    assert observation["summary"] == "Evidence collected."
    assert "Official documentation confirms" in observation["answer_candidate"]
    assert "LONG-ANSWER " not in observation["answer_candidate"]
    assert observation["evidence_refs"] == ["web:evidence:1"]
    assert observation["artifact_refs"] == ["artifact:web:1"]
    assert observation["context_compaction"]["applied"] is True
    assert observation["context_compaction"]["model_visible_evidence_summary_used"] is True


def test_builtin_specialist_agents_use_descriptive_professional_roles() -> None:
    agents = {item.agent_id: item for item in default_agent_descriptors(now=1.0)}

    assert "你是一名知识库检索员" in agents["agent:knowledge_searcher"].description
    assert "你是一名 PDF 阅读分析员" in agents["agent:pdf_reader"].description
    assert "你是一名表格与结构化数据分析员" in agents["agent:table_analyst"].description
    assert "你是一名网页研究员" in agents["agent:web_researcher"].description
    assert agents["agent:knowledge_searcher"].default_soul_id == "hebo"
    assert agents["agent:pdf_reader"].default_soul_id == "hebo"
    assert agents["agent:table_analyst"].default_soul_id == "hebo"
    assert agents["agent:web_researcher"].default_soul_id == "hebo"


def test_child_fallback_prompt_uses_runtime_profile_professional_role() -> None:
    agent = type(
        "Agent",
        (),
        {
            "description": "old description",
        },
    )()
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": ("op.model_response", "op.mcp_pdf"),
            "metadata": {
                "role_prompt": "你是一名 PDF 阅读与证据整理员。你负责阅读指定 PDF，并区分正文页、目录页、过渡页、相关页、结论页。"
            },
        },
    )()

    prompt = child_system_prompt(agent, profile)

    assert "PDF 阅读与证据整理员" in prompt
    assert "目录页、过渡页" in prompt
    assert "主 Agent" in prompt
    assert "old description" not in prompt



