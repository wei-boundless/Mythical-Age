from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.local_mcp_registry import build_local_mcp_agent_map, default_local_mcp_units
from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION


A2A_COMPATIBLE_PROTOCOL_VERSION = "a2a-compatible.v1"
AGENT_ID_BY_MCP_ROUTE: dict[str, str] = build_local_mcp_agent_map()


@dataclass(frozen=True, slots=True)
class A2AAgentSkill:
    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class A2AAgentCard:
    agent_id: str
    name: str
    description: str
    protocol_version: str = A2A_COMPATIBLE_PROTOCOL_VERSION
    supports_streaming: bool = True
    supports_long_task: bool = False
    default_input_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    skills: list[A2AAgentSkill] = field(default_factory=list)
    mcp_profile: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skills"] = [skill.to_dict() for skill in self.skills]
        return payload


def build_default_agent_cards() -> dict[str, A2AAgentCard]:
    cards: dict[str, A2AAgentCard] = {}
    for unit in default_local_mcp_units():
        cards[unit.agent_id] = A2AAgentCard(
            agent_id=unit.agent_id,
            name=unit.a2a_name,
            description=unit.a2a_description,
            supports_long_task=unit.supports_long_task,
            default_input_modes=list(unit.default_input_modes),
            default_output_modes=list(unit.default_output_modes),
            skills=[
                A2AAgentSkill(
                    id=unit.a2a_skill_id,
                    name=unit.a2a_skill_name,
                    description=unit.a2a_skill_description,
                    tags=list(unit.tags),
                    input_modes=list(unit.default_input_modes),
                    output_modes=list(unit.default_output_modes),
                )
            ],
            mcp_profile={
                "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
                "tools": [],
            },
            extensions={
                "x-langchain-agent.mcp_route": unit.route,
                "x-langchain-agent.local_mcp_unit": unit.unit_id,
            },
        )
    return cards


def get_agent_card(agent_id: str | None) -> A2AAgentCard | None:
    return build_default_agent_cards().get(str(agent_id or "").strip())
