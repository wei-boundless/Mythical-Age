from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MCPTool:
    name: str
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = False


@dataclass(slots=True)
class MCPResource:
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    enabled: bool = False


@dataclass(slots=True)
class MCPLayer:
    enabled: bool = False
    connected: bool = False
    server_name: str = ""
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "server_name": self.server_name,
            "tool_count": len(self.tools),
            "resource_count": len(self.resources),
        }



