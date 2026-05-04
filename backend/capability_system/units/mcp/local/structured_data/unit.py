from __future__ import annotations

from capability_system.local_mcp_registry import LocalMCPUnitRecord


STRUCTURED_DATA_LOCAL_MCP_UNIT = LocalMCPUnitRecord(
    unit_id="local_mcp:structured_data",
    name="structured_data",
    category="dataset_analytics",
    summary="本地结构化数据分析能力单元。",
    implementation_root="capability_system.units.mcp.local.structured_data",
    tool_refs=["structured_data_analysis"],
    mcp_refs=["structured_data"],
    skill_refs=["structured-data-analysis"],
    resource_kinds=["dataset", "dataset_analysis", "subset_selection"],
    normalization_contract={
        "tool_output": "canonical_structured",
        "mcp_output": "canonical_result_and_evidence",
    },
    tags=["dataset", "analytics", "table", "local_mcp"],
)
