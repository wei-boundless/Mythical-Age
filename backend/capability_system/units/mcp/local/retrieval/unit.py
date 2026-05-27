from __future__ import annotations

from capability_system.local_mcp_registry import get_local_mcp_unit


RETRIEVAL_LOCAL_MCP_UNIT = get_local_mcp_unit("retrieval")
assert RETRIEVAL_LOCAL_MCP_UNIT is not None


