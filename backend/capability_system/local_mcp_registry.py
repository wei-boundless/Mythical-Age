from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LOCAL_MCP_PROTOCOL_VERSION = "mcp-compatible.v1"


LOCAL_MCP_SERVER_NAME = "local-capability-units"


@dataclass(frozen=True, slots=True)
class LocalMCPUnitRecord:
    unit_id: str
    name: str
    route: str
    route_aliases: list[str]
    category: str
    summary: str
    mcp_id: str
    agent_id: str
    operation_id: str
    implementation_module: str
    worker_slot: str
    worker_execution_kind: str
    template_ids: list[str]
    answer_source: str
    followup_binding_key: str
    source_kind: str
    implementation_root: str
    a2a_name: str
    a2a_description: str
    a2a_skill_id: str
    a2a_skill_name: str
    a2a_skill_description: str
    supports_long_task: bool = False
    default_input_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    request_path_parameter: str = "path"
    request_mode_parameter: str = ""
    request_default_mode: str = ""
    server_name: str = LOCAL_MCP_SERVER_NAME
    protocol_version: str = LOCAL_MCP_PROTOCOL_VERSION
    tool_refs: list[str] = field(default_factory=list)
    mcp_refs: list[str] = field(default_factory=list)
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
            route="retrieval",
            route_aliases=["retrieval", "evidence_orchestrator"],
            category="knowledge_retrieval",
            summary="本地知识检索与 RAG 能力单元，负责集合配置、索引注册、查询改写、路由与重排。",
            mcp_id="mcp:knowledge:retrieval",
            agent_id="agent:knowledge:retrieval",
            operation_id="op.mcp_retrieval",
            implementation_module="evidence.retrieval_worker.RetrievalWorker",
            worker_slot="retrieval_worker",
            worker_execution_kind="sync",
            template_ids=["template.rag.knowledge_answer"],
            answer_source="mcp.retrieval_local",
            followup_binding_key="current_turn_context",
            source_kind="knowledge",
            implementation_root="capability_system.units.mcp.local.retrieval",
            a2a_name="检索智能体",
            a2a_description="查询本地知识证据，返回可追踪的候选证据与对象句柄。",
            a2a_skill_id="knowledge-retrieval",
            a2a_skill_name="知识检索",
            a2a_skill_description="召回本地知识，但不把原始片段直接当作主线程结论。",
            supports_long_task=True,
            mcp_refs=["retrieval"],
            skill_refs=["rag-skill"],
            resource_kinds=["knowledge_collection", "retrieval_hit", "parsed_chunk"],
            normalization_contract={
                "mcp_output": "evidence_envelope",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["rag", "retrieval", "knowledge", "local_mcp"],
        ),
        LocalMCPUnitRecord(
            unit_id="local_mcp:pdf",
            name="pdf",
            route="pdf",
            route_aliases=["pdf"],
            category="document_reading",
            summary="本地 PDF 阅读与解析能力单元，负责路径解析、页面解析、路由判定与规范化结果输出。",
            mcp_id="mcp:document:pdf",
            agent_id="agent:document:pdf",
            operation_id="op.mcp_pdf",
            implementation_module="evidence.pdf_worker.PDFWorker",
            worker_slot="pdf_worker",
            worker_execution_kind="async",
            template_ids=["template.pdf.document_analysis"],
            answer_source="mcp.pdf_local",
            followup_binding_key="active_pdf",
            source_kind="pdf",
            implementation_root="capability_system.units.mcp.local.pdf",
            a2a_name="文档智能体",
            a2a_description="读取 PDF 与文档产物，抽取页级/章节级证据，并把表格产物继续移交。",
            a2a_skill_id="pdf-analysis",
            a2a_skill_name="PDF 分析",
            a2a_skill_description="分析用户明确指定或由句柄绑定的 PDF 来源。",
            supports_long_task=True,
            default_input_modes=["text/plain", "application/pdf"],
            mcp_refs=["pdf"],
            skill_refs=["pdf-analysis"],
            resource_kinds=["pdf_document", "pdf_page", "pdf_section", "canonical_pdf_answer"],
            request_mode_parameter="mode",
            request_default_mode="document",
            normalization_contract={
                "mcp_output": "canonical_result_and_evidence",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["pdf", "document", "analysis", "local_mcp"],
        ),
        LocalMCPUnitRecord(
            unit_id="local_mcp:structured_data",
            name="structured_data",
            route="structured_data",
            route_aliases=["structured_data"],
            category="dataset_analytics",
            summary="本地结构化数据分析能力单元，负责数据目录、计划生成、执行与子集选择规范化。",
            mcp_id="mcp:data:structured",
            agent_id="agent:data:structured",
            operation_id="op.mcp_structured_data",
            implementation_module="evidence.structured_data_worker.StructuredDataWorker",
            worker_slot="structured_data_worker",
            worker_execution_kind="async",
            template_ids=["template.data.structured_analysis"],
            answer_source="mcp.structured_data_local",
            followup_binding_key="active_dataset",
            source_kind="dataset",
            implementation_root="capability_system.units.mcp.local.structured_data",
            a2a_name="结构化数据智能体",
            a2a_description="围绕表格句柄执行结构识别、聚合分析和子集延续处理。",
            a2a_skill_id="structured-data-analysis",
            a2a_skill_name="结构化数据分析",
            a2a_skill_description="分析用户明确指定或由句柄绑定的表格/数据集来源。",
            default_input_modes=["text/plain", "text/csv", "application/json"],
            mcp_refs=["structured_data"],
            skill_refs=["structured-data-analysis"],
            resource_kinds=["dataset", "dataset_analysis", "subset_selection"],
            normalization_contract={
                "mcp_output": "canonical_result_and_evidence",
                "resource_exposure_policy": "explicit_resource",
            },
            tags=["dataset", "analytics", "table", "local_mcp"],
        ),
    ]


def build_local_mcp_catalog() -> list[dict[str, Any]]:
    return [record.to_dict() for record in default_local_mcp_units()]


def build_local_mcp_route_map() -> dict[str, LocalMCPUnitRecord]:
    route_map: dict[str, LocalMCPUnitRecord] = {}
    for record in default_local_mcp_units():
        for route in [record.route, *list(record.route_aliases)]:
            key = str(route or "").strip()
            if key:
                route_map[key] = record
    return route_map


def build_local_mcp_template_map() -> dict[str, LocalMCPUnitRecord]:
    template_map: dict[str, LocalMCPUnitRecord] = {}
    for record in default_local_mcp_units():
        for template_id in list(record.template_ids):
            key = str(template_id or "").strip()
            if key:
                template_map[key] = record
    return template_map


def build_local_mcp_source_kind_map() -> dict[str, LocalMCPUnitRecord]:
    source_kind_map: dict[str, LocalMCPUnitRecord] = {}
    for record in default_local_mcp_units():
        key = str(record.source_kind or "").strip()
        if key:
            source_kind_map[key] = record
    return source_kind_map


def build_local_mcp_agent_map() -> dict[str, str]:
    return {
        route: record.agent_id
        for route, record in build_local_mcp_route_map().items()
        if str(record.agent_id or "").strip()
    }


def get_local_mcp_unit(route_or_alias: str | None) -> LocalMCPUnitRecord | None:
    return build_local_mcp_route_map().get(str(route_or_alias or "").strip())


def get_local_mcp_unit_for_template(template_id: str | None) -> LocalMCPUnitRecord | None:
    return build_local_mcp_template_map().get(str(template_id or "").strip())


def get_local_mcp_unit_for_source_kind(source_kind: str | None) -> LocalMCPUnitRecord | None:
    return build_local_mcp_source_kind_map().get(str(source_kind or "").strip())


def get_local_mcp_primary_template(route_or_alias: str | None) -> str:
    unit = get_local_mcp_unit(route_or_alias)
    if unit is None:
        return ""
    return str(unit.template_ids[0] if unit.template_ids else "").strip()
