from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION, get_mcp_tool_view


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
            name="检索智能体",
            description="查询本地知识证据，返回可追踪的候选证据与对象句柄。",
            supports_long_task=True,
            skills=[
                A2AAgentSkill(
                    id="knowledge-retrieval",
                    name="知识检索",
                    description="召回本地知识，但不把原始片段直接当作主线程结论。",
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
            name="文档智能体",
            description="读取 PDF 与文档产物，抽取页级/章节级证据，并把表格产物继续移交。",
            supports_long_task=True,
            skills=[
                A2AAgentSkill(
                    id="pdf-analysis",
                    name="PDF 分析",
                    description="分析用户明确指定或由句柄绑定的 PDF 来源。",
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
            name="结构化数据智能体",
            description="围绕表格句柄执行结构识别、聚合分析和子集延续处理。",
            supports_long_task=False,
            skills=[
                A2AAgentSkill(
                    id="structured-data-analysis",
                    name="结构化数据分析",
                    description="分析用户明确指定或由句柄绑定的表格/数据集来源。",
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
