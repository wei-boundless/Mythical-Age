from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from agent_system.registry.agent_registry import default_agent_descriptors
from capability_system.agent_capabilities.deepsearch import DeepSearchCapability, normalize_runtime_config, required_operations_for_search_config


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


def test_search_specialists_are_registered_with_separate_authority() -> None:
    agents = {agent.agent_id: agent for agent in default_agent_descriptors(now=1.0)}
    profiles = {profile.agent_id: profile for profile in default_agent_runtime_profiles()}

    assert {"agent:web_researcher", "agent:codebase_searcher", "agent:knowledge_searcher", "agent:memory_searcher"} <= set(agents)
    assert profiles["agent:0"].subagent_policy.allowed_subagent_ids == (
        "agent:knowledge_searcher",
        "agent:codebase_searcher",
        "agent:memory_searcher",
        "agent:pdf_reader",
        "agent:table_analyst",
        "agent:web_researcher",
        "agent:verifier",
    )

    web = profiles["agent:web_researcher"]
    assert web.allowed_operations == ("op.model_response", "op.search_agent", "op.web_search", "op.fetch_url")
    assert set(web.metadata["runtime_config"]["search"]["search_sources"]) == {"web"}
    assert web.metadata["runtime_config"]["search"]["allow_local_files"] is False
    assert web.metadata["runtime_config"]["search"]["allow_memory_read"] is False

    code = profiles["agent:codebase_searcher"]
    assert {"op.search_files", "op.search_text", "op.read_file", "op.git_log", "op.git_show"} <= set(code.allowed_operations)
    assert "op.web_search" in code.blocked_operations
    assert "op.memory_read" in code.blocked_operations

    knowledge = profiles["agent:knowledge_searcher"]
    assert knowledge.allowed_operations == ("op.model_response", "op.mcp_retrieval")
    assert "op.memory_read" in knowledge.blocked_operations
    assert knowledge.metadata["runtime_template_id"] == "runtime.template.knowledge_search"

    memory = profiles["agent:memory_searcher"]
    assert memory.allowed_operations == ("op.model_response", "op.memory_read")
    assert "op.mcp_retrieval" in memory.blocked_operations


def test_web_search_config_requires_only_web_operations() -> None:
    profile = {profile.agent_id: profile for profile in default_agent_runtime_profiles()}["agent:web_researcher"]
    config = normalize_runtime_config(profile.metadata["runtime_config"]).search

    assert config is not None
    assert tuple(config.search_sources) == ("web",)
    assert set(required_operations_for_search_config(config)) == {
        "op.model_response",
        "op.search_agent",
        "op.web_search",
        "op.fetch_url",
    }


def test_deepsearch_capability_runs_web_only_sources() -> None:
    web_provider = _StaticProvider("web")
    local_provider = _StaticProvider("local_files")
    rag_provider = _StaticProvider("rag")
    memory_provider = _StaticProvider("memory")

    capability = DeepSearchCapability(
        Path("."),
        search_provider=web_provider,
        local_files_provider=local_provider,
        rag_provider=rag_provider,
        memory_provider=memory_provider,
    )
    request = SimpleNamespace(
        request_id="subagent:req:web-only",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        subagent_task_kind="web_research",
        instruction="Find official web evidence.",
        input_payload={"query": "official release notes"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type(
        "Profile",
        (),
        {
            "allowed_operations": ("op.model_response", "op.search_agent", "op.web_search", "op.fetch_url"),
            "blocked_operations": (),
            "metadata": {
                "runtime_config": {
                    "template_id": "runtime.template.deepsearch",
                    "search": {
                        "search_sources": ["web"],
                        "allow_fetch_url": False,
                        "allow_local_files": False,
                        "allow_memory_read": False,
                        "max_queries": 1,
                        "max_fetches": 0,
                        "prefer_primary_sources": False,
                    },
                }
            },
        },
    )()
    config = normalize_runtime_config(profile.metadata["runtime_config"]).search

    payload = asyncio.run(capability.run(request=request, agent=agent, profile=profile, config=config))

    assert payload["status"] == "completed"
    assert payload["diagnostics"]["child_execution_mode"] == "profile_authorized_deepsearch_capability"
    assert payload["diagnostics"]["capability_id"] == "capability.deepsearch"
    assert payload["diagnostics"]["web_payload"]["usage"]["search_sources"] == ["web"]
    assert web_provider.queries == ["official release notes"]
    assert local_provider.queries == []
    assert rag_provider.queries == []
    assert memory_provider.queries == []


def test_web_research_agent_blocks_non_web_source_by_permission() -> None:
    runtime = DeepSearchCapability(Path("."), local_files_provider=_StaticProvider("local_files"))
    config = normalize_runtime_config(
        {
            "template_id": "runtime.template.deepsearch",
            "search": {
                "search_sources": ["local_files"],
                "allow_local_files": True,
                "allow_fetch_url": False,
                "max_queries": 1,
                "max_fetches": 0,
            },
        }
    ).search
    request = SimpleNamespace(
        request_id="subagent:req:web-local-denied",
        task_run_id="taskrun:test",
        session_id="session:test",
        parent_agent_run_ref="agrun:main",
        source_agent_id="agent:0",
        target_agent_id="agent:web_researcher",
        subagent_task_kind="web_research",
        instruction="Wrongly search local files.",
        input_payload={"query": "runtime"},
    )
    agent = type("Agent", (), {"agent_id": "agent:web_researcher"})()
    profile = type("Profile", (), {"allowed_operations": ("op.model_response", "op.web_search"), "blocked_operations": (), "metadata": {}})()

    payload = asyncio.run(runtime.run(request=request, agent=agent, profile=profile, config=config))

    assert payload["status"] == "failed"
    assert "deepsearch_required_operation_missing" in payload["limitations"]
    assert "op.search_files" in payload["limitations"]


