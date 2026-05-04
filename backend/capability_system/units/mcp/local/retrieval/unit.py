from __future__ import annotations

from capability_system.local_mcp_registry import LocalMCPUnitRecord


RETRIEVAL_LOCAL_MCP_UNIT = LocalMCPUnitRecord(
    unit_id="local_mcp:retrieval",
    name="retrieval",
    category="knowledge_retrieval",
    summary="本地知识检索与 RAG 能力单元。",
    implementation_root="capability_system.units.mcp.local.retrieval",
    tool_refs=["search_knowledge"],
    worker_refs=["retrieval"],
    skill_refs=["rag-skill"],
    resource_kinds=["knowledge_collection", "retrieval_hit", "parsed_chunk"],
    normalization_contract={
        "tool_output": "summary_text",
        "worker_output": "evidence_envelope",
    },
    tags=["rag", "retrieval", "knowledge", "local_mcp"],
)
