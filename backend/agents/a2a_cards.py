from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tools.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION, get_mcp_tool_view


A2A_COMPATIBLE_PROTOCOL_VERSION = "a2a-compatible.v1"
AGENT_ID_BY_WORKER_ROUTE: dict[str, str] = {
    "retrieval": "agent:knowledge:retrieval",
    "evidence_orchestrator": "agent:knowledge:retrieval",
    "pdf": "agent:document:pdf",
    "structured_data": "agent:data:structured",
}


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
    return {
        AGENT_ID_BY_WORKER_ROUTE["retrieval"]: A2AAgentCard(
            agent_id=AGENT_ID_BY_WORKER_ROUTE["retrieval"],
            name="Retrieval Agent",
            description="Queries local knowledge evidence and emits typed candidates/handles.",
            supports_long_task=True,
            skills=[
                A2AAgentSkill(
                    id="knowledge-retrieval",
                    name="Knowledge Retrieval",
                    description="Retrieve local knowledge without exposing raw chunks as main-thread truth.",
                    tags=["rag", "retrieval", "knowledge"],
                    input_modes=["text/plain"],
                    output_modes=["application/json"],
                )
            ],
            mcp_profile=_mcp_profile(["search_knowledge"]),
            extensions={"x-langchain-agent.worker_route": "retrieval"},
        ),
        AGENT_ID_BY_WORKER_ROUTE["pdf"]: A2AAgentCard(
            agent_id=AGENT_ID_BY_WORKER_ROUTE["pdf"],
            name="PDF Agent",
            description="Reads PDF artifacts, extracts page/section evidence, and hands table artifacts onward.",
            supports_long_task=True,
            skills=[
                A2AAgentSkill(
                    id="pdf-analysis",
                    name="PDF Analysis",
                    description="Analyze explicit or handle-bound PDF sources.",
                    tags=["pdf", "document", "page"],
                    input_modes=["text/plain", "application/pdf"],
                    output_modes=["application/json", "text/plain"],
                )
            ],
            mcp_profile=_mcp_profile(["pdf_analysis", "analyze_multimodal_file"]),
            extensions={"x-langchain-agent.worker_route": "pdf"},
        ),
        AGENT_ID_BY_WORKER_ROUTE["structured_data"]: A2AAgentCard(
            agent_id=AGENT_ID_BY_WORKER_ROUTE["structured_data"],
            name="Structured Data Agent",
            description="Executes schema inspection, aggregation, and subset continuation over tabular handles.",
            supports_long_task=False,
            skills=[
                A2AAgentSkill(
                    id="structured-data-analysis",
                    name="Structured Data Analysis",
                    description="Analyze explicit or handle-bound table/dataset sources.",
                    tags=["table", "dataset", "analytics"],
                    input_modes=["text/plain", "text/csv", "application/json"],
                    output_modes=["application/json", "text/plain"],
                )
            ],
            mcp_profile=_mcp_profile(["structured_data_analysis"]),
            extensions={"x-langchain-agent.worker_route": "structured_data"},
        ),
    }


def get_agent_card(agent_id: str | None) -> A2AAgentCard | None:
    return build_default_agent_cards().get(str(agent_id or "").strip())


def _mcp_profile(tool_names: list[str]) -> dict[str, Any]:
    tools = []
    for tool_name in tool_names:
        view = get_mcp_tool_view(tool_name)
        if view is not None:
            tools.append(view.to_event_metadata())
    return {
        "protocol_version": MCP_COMPATIBLE_PROTOCOL_VERSION,
        "tools": tools,
    }
