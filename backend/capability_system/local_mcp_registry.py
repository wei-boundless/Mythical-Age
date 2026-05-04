from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from capability_system.mcp_adapter import MCP_COMPATIBLE_PROTOCOL_VERSION


LOCAL_MCP_SERVER_NAME = "local-capability-units"


@dataclass(frozen=True, slots=True)
class LocalMCPUnitRecord:
    unit_id: str
    name: str
    category: str
    summary: str
    implementation_root: str
    server_name: str = LOCAL_MCP_SERVER_NAME
    protocol_version: str = MCP_COMPATIBLE_PROTOCOL_VERSION
    tool_refs: list[str] = field(default_factory=list)
    worker_refs: list[str] = field(default_factory=list)
    skill_refs: list[str] = field(default_factory=list)
    resource_kinds: list[str] = field(default_factory=list)
    normalization_contract: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_local_mcp_units() -> list[LocalMCPUnitRecord]:
    return [
        LocalMCPUnitRecord(
            unit_id="local_mcp:retrieval",
            name="retrieval",
            category="knowledge_retrieval",
            summary="本地知识检索与 RAG 能力单元，负责集合配置、索引注册、查询改写、路由与重排。",
            implementation_root="capability_system.units.mcp.local.retrieval",
            tool_refs=["search_knowledge"],
            worker_refs=["retrieval"],
            skill_refs=["rag-skill"],
            resource_kinds=["knowledge_collection", "retrieval_hit", "parsed_chunk"],
            normalization_contract={
                "tool_output": "summary_text",
                "worker_output": "evidence_envelope",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["rag", "retrieval", "knowledge", "local_mcp"],
        ),
        LocalMCPUnitRecord(
            unit_id="local_mcp:pdf",
            name="pdf",
            category="document_reading",
            summary="本地 PDF 阅读与解析能力单元，负责路径解析、页面解析、路由判定与规范化结果输出。",
            implementation_root="capability_system.units.mcp.local.pdf",
            tool_refs=["pdf_analysis"],
            worker_refs=["pdf"],
            skill_refs=["pdf-analysis"],
            resource_kinds=["pdf_document", "pdf_page", "pdf_section", "canonical_pdf_answer"],
            normalization_contract={
                "tool_output": "finalize_then_display",
                "worker_output": "canonical_result_and_evidence",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["pdf", "document", "analysis", "local_mcp"],
        ),
        LocalMCPUnitRecord(
            unit_id="local_mcp:structured_data",
            name="structured_data",
            category="dataset_analytics",
            summary="本地结构化数据分析能力单元，负责数据目录、计划生成、执行与子集选择规范化。",
            implementation_root="capability_system.units.mcp.local.structured_data",
            tool_refs=["structured_data_analysis"],
            worker_refs=["structured_data"],
            skill_refs=["structured-data-analysis"],
            resource_kinds=["dataset", "dataset_analysis", "subset_selection"],
            normalization_contract={
                "tool_output": "canonical_structured",
                "worker_output": "canonical_result_and_evidence",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["dataset", "analytics", "table", "local_mcp"],
        ),
    ]


def build_local_mcp_catalog() -> list[dict[str, Any]]:
    return [record.to_dict() for record in default_local_mcp_units()]
