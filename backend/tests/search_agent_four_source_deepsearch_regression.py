from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from agent_system.registry.agent_registry import default_agent_descriptors
from runtime.execution.child_agent_runtime_executor import ChildAgentRuntimeExecutor
from runtime.execution.delegation_models import AgentDelegationRequest
from runtime.search_agent_runtime import SearchAgentRuntime, normalize_runtime_config, required_operations_for_search_config
from soul.projection_store import get_projection_card


class _StaticProvider:
    def __init__(self, source: str) -> None:
        self.source = source
        self.queries: list[str] = []

    async def search(self, *, query: str, topic: str, time_range: str, max_results: int, config) -> dict:
        self.queries.append(query)
        return {
            "ok": True,
            "query": query,
            "topic": topic,
            "time_range": time_range,
            "source": self.source,
            "results": [
                {
                    "title": f"{self.source} evidence",
                    "url": f"{self.source}://source-1",
                    "source": f"{self.source}:source-1",
                    "content": f"{self.source} source contains evidence for {query}.",
                    "score": 0.91,
                    "_source_type": self.source,
                    "search_source": self.source,
                    "artifact_ref": f"artifact:{self.source}:1",
                }
            ],
        }


def test_search_agent_default_profile_is_registered_four_source_deepsearch() -> None:
    agents = {agent.agent_id: agent for agent in default_agent_descriptors(now=1.0)}
    profiles = {profile.agent_id: profile for profile in default_agent_runtime_profiles()}

    agent = agents["agent:web_researcher"]
    profile = profiles["agent:web_researcher"]
    runtime_config = normalize_runtime_config(profile.metadata["runtime_config"])

    assert agent.agent_name == "搜索证据研究Agent"
    assert agent.metadata["worker_kind"] == "search_research"
    assert runtime_config.template_id == "runtime.template.deepsearch"
    assert runtime_config.search is not None
    assert set(runtime_config.search.search_sources) == {"web", "local_files", "rag", "memory"}
    assert {
        "op.web_search",
        "op.fetch_url",
        "op.search_files",
        "op.search_text",
        "op.read_file",
        "op.mcp_retrieval",
        "op.memory_read",
    } <= set(profile.allowed_operations)


def test_search_agent_projection_prompt_is_multi_source_not_web_only() -> None:
    card = get_projection_card(Path("backend"), "projection.worker.web_evidence_researcher")

    assert card is not None
    text = f"{card.get('identity_anchor', '')}\n{card.get('projection_prompt', '')}"
    assert "搜索证据研究员" in text
    assert "本地文件" in text
    assert "知识库" in text
    assert "正式记忆" in text
    assert "不能使用未被编排配置启用的搜索源" in text


def test_four_source_config_requires_four_source_operations() -> None:
    config = normalize_runtime_config(
        {
            "template_id": "runtime.template.deepsearch",
            "search": {
                "search_sources": ["web", "local_files", "rag", "memory"],
                "allow_fetch_url": True,
                "allow_local_files": True,
                "allow_memory_read": True,
                "max_fetches": 1,
            },
        }
    ).search

    assert config is not None
    assert set(required_operations_for_search_config(config)) == {
        "op.model_response",
        "op.web_search",
        "op.fetch_url",
        "op.search_files",
        "op.search_text",
        "op.read_file",
        "op.mcp_retrieval",
        "op.memory_read",
    }


def test_search_runtime_executes_configured_local_rag_memory_sources_without_web() -> None:
    local_provider = _StaticProvider("local_files")
    rag_provider = _StaticProvider("rag")
    memory_provider = _StaticProvider("memory")
    runtime = SearchAgentRuntime(
        Path("."),
        local_files_provider=local_provider,
        rag_provider=rag_provider,
        memory_provider=memory_provider,
    )
    config = normalize_runtime_config(
        {
            "template_id": "runtime.template.deepsearch",
            "search": {
                "search_sources": ["local_files", "rag", "memory"],
                "allow_fetch_url": False,
                "max_queries": 1,
                "max_fetches": 0,
                "max_sources": 6,
                "prefer_primary_sources": False,
            },
        }
    ).search
    request = AgentDelegationRequest(
        request_id="delegation:req:multi-source",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind="evidence_lookup",
        instruction="Find local, rag and memory evidence.",
        input_payload={"query": "runtime configuration"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": ("op.model_response", "op.search_files", "op.search_text", "op.read_file", "op.mcp_retrieval", "op.memory_read"),
            "blocked_operations": (),
            "metadata": {},
        },
    )()

    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=config))

    packet = dict(payload["diagnostics"]["agent_evidence_packet"])
    sources = {item["locator"]["source_type"] for item in packet["evidence"]}
    assert payload["status"] == "completed"
    assert local_provider.queries == ["runtime configuration"]
    assert rag_provider.queries == ["runtime configuration"]
    assert memory_provider.queries == ["runtime configuration"]
    assert {"local_files", "rag", "memory"} <= sources
    assert "web" not in set(payload["diagnostics"]["web_payload"]["usage"]["search_sources"])


def test_deepsearch_template_routes_non_web_delegation_to_search_runtime() -> None:
    provider = _StaticProvider("rag")

    def runtime_factory(root_dir: Path) -> SearchAgentRuntime:
        return SearchAgentRuntime(root_dir, rag_provider=provider)

    executor = ChildAgentRuntimeExecutor(Path("."), search_runtime_factory=runtime_factory)
    request = AgentDelegationRequest(
        request_id="delegation:req:route-rag",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind="evidence_lookup",
        instruction="Find knowledge evidence.",
        input_payload={"query": "knowledge evidence"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": ("op.model_response", "op.mcp_retrieval"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "search_sources": ["rag"],
                        "allow_fetch_url": False,
                        "max_queries": 1,
                        "max_fetches": 0,
                        "prefer_primary_sources": False,
                    },
                }
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "runtime_configured_search_agent"
    assert payload["diagnostics"]["specialist_route"] == "deepsearch"
    assert provider.queries == ["knowledge evidence"]


def test_search_runtime_blocks_configured_source_when_search_policy_disallows_operation() -> None:
    provider = _StaticProvider("web")
    runtime = SearchAgentRuntime(Path("."), search_provider=provider)
    config = normalize_runtime_config(
        {
            "template_id": "runtime.template.deepsearch",
            "search": {
                "search_sources": ["web"],
                "allow_fetch_url": False,
                "max_queries": 1,
                "max_fetches": 0,
            },
        }
    ).search
    request = AgentDelegationRequest(
        request_id="delegation:req:policy-block-web",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind="web_research",
        instruction="Find web evidence.",
        input_payload={"query": "web evidence"},
        diagnostics={"allowed_search_sources": ["rag", "local_files"]},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type("Profile", (), {"allowed_operations": ("op.model_response", "op.web_search"), "blocked_operations": (), "metadata": {}})()

    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=config))

    assert payload["status"] == "failed"
    assert "deepsearch_search_policy_blocked" in payload["limitations"]
    assert "op.web_search" in payload["limitations"]
    assert provider.queries == []


@pytest.mark.parametrize(
    ("delegation_kind", "source", "allowed_operations"),
    [
        ("web_research", "web", ("op.model_response", "op.web_search")),
        ("evidence_lookup", "rag", ("op.model_response", "op.mcp_retrieval")),
        ("local_search", "local_files", ("op.model_response", "op.search_files", "op.search_text", "op.read_file")),
        ("memory_lookup", "memory", ("op.model_response", "op.memory_read")),
    ],
)
def test_deepsearch_source_routing_does_not_mix_between_configured_sources(
    delegation_kind: str,
    source: str,
    allowed_operations: tuple[str, ...],
) -> None:
    providers = {
        "web": _StaticProvider("web"),
        "local_files": _StaticProvider("local_files"),
        "rag": _StaticProvider("rag"),
        "memory": _StaticProvider("memory"),
    }

    def runtime_factory(root_dir: Path) -> SearchAgentRuntime:
        return SearchAgentRuntime(
            root_dir,
            search_provider=providers["web"],
            local_files_provider=providers["local_files"],
            rag_provider=providers["rag"],
            memory_provider=providers["memory"],
        )

    executor = ChildAgentRuntimeExecutor(Path("."), search_runtime_factory=runtime_factory)
    request = AgentDelegationRequest(
        request_id=f"delegation:req:route:{source}",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        delegation_kind=delegation_kind,
        instruction=f"Find {source} evidence.",
        input_payload={"query": f"{source} routing evidence"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": allowed_operations,
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "search_sources": [source],
                        "allow_fetch_url": False,
                        "allow_local_files": source == "local_files",
                        "allow_memory_read": source == "memory",
                        "max_queries": 1,
                        "max_fetches": 0,
                        "prefer_primary_sources": False,
                    },
                }
            },
        },
    )()

    payload = asyncio.run(executor.run(request=request, agent=agent, profile=profile))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "runtime_configured_search_agent"
    assert payload["diagnostics"]["web_payload"]["usage"]["search_sources"] == [source]
    assert providers[source].queries == [f"{source} routing evidence"]
    for other_source, provider in providers.items():
        if other_source != source:
            assert provider.queries == []
