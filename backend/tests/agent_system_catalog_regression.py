from __future__ import annotations

from api.agents import _default_control_agents, _default_protocol_links


def test_agent_system_catalog_exposes_core_child_agents() -> None:
    agents = {agent["agent_id"]: agent for agent in _default_control_agents()}

    assert "agent:local:worker" in agents
    assert "agent:knowledge:retrieval" in agents
    assert "agent:document:pdf" in agents
    assert "agent:data:structured" in agents
    assert agents["agent:knowledge:retrieval"]["worker_route"] == "retrieval"
    assert agents["agent:document:pdf"]["protocol_version"] == "a2a-compatible.v1"


def test_agent_system_protocol_links_capture_io_contracts() -> None:
    links = {link["link_id"]: link for link in _default_protocol_links()}

    assert "main-to-retrieval" in links
    assert "pdf-to-structured" in links
    assert links["main-to-retrieval"]["from_agent"] == "agent:main:conversation"
    assert links["main-to-retrieval"]["to_agent"] == "agent:knowledge:retrieval"
    assert links["pdf-to-structured"]["input_contract"]
    assert links["pdf-to-structured"]["output_contract"]
    assert links["pdf-to-structured"]["handoff_policy"]


def test_agent_system_protocol_links_have_valid_topology() -> None:
    known_agent_ids = {"agent:main:conversation", *{agent["agent_id"] for agent in _default_control_agents()}}

    for link in _default_protocol_links():
        assert link["from_agent"] in known_agent_ids
        assert link["to_agent"] in known_agent_ids
        assert link["from_agent"] != link["to_agent"]

    route_pairs = {(link["from_agent"], link["to_agent"]) for link in _default_protocol_links()}
    assert ("agent:main:conversation", "agent:local:worker") in route_pairs
    assert ("agent:main:conversation", "agent:knowledge:retrieval") in route_pairs
    assert ("agent:main:conversation", "agent:document:pdf") in route_pairs
    assert ("agent:document:pdf", "agent:data:structured") in route_pairs
    assert ("agent:knowledge:retrieval", "agent:document:pdf") in route_pairs
