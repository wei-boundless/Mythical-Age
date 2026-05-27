from __future__ import annotations

from capability_system.local_mcp_registry import get_local_mcp_unit


STRUCTURED_DATA_LOCAL_MCP_UNIT = get_local_mcp_unit("structured_data")
assert STRUCTURED_DATA_LOCAL_MCP_UNIT is not None


