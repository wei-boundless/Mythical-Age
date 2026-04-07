from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MCPTool:
    """Placeholder definition for a future MCP-exposed tool."""

    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MCPResource:
    """Placeholder definition for a future MCP-exposed resource."""

    name: str
    uri: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MCPLayer:
    """Non-invasive MCP extension layer.

    This layer is only a registry placeholder right now:
    - it does not connect to any MCP server
    - it does not change the current agent routing
    - it exists so MCP can be added later as an extension layer
    """

    enabled: bool = False
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "tool_count": len(self.tools),
            "resource_count": len(self.resources),
        }
