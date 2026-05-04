from __future__ import annotations

from capability_system.local_mcp_registry import LocalMCPUnitRecord


PDF_LOCAL_MCP_UNIT = LocalMCPUnitRecord(
    unit_id="local_mcp:pdf",
    name="pdf",
    category="document_reading",
    summary="本地 PDF 阅读与解析能力单元。",
    implementation_root="capability_system.units.mcp.local.pdf",
    tool_refs=["pdf_analysis"],
    mcp_refs=["pdf"],
    skill_refs=["pdf-analysis"],
    resource_kinds=["pdf_document", "pdf_page", "pdf_section", "canonical_pdf_answer"],
    normalization_contract={
        "tool_output": "finalize_then_display",
        "mcp_output": "canonical_result_and_evidence",
    },
    tags=["pdf", "document", "analysis", "local_mcp"],
)
