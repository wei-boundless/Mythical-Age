from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ExternalMCPTool:
    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExternalMCPResource:
    uri: str
    name: str = ""
    title: str = ""
    description: str = ""
    mime_type: str = ""
    size: int | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExternalMCPPrompt:
    name: str
    title: str = ""
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExternalMCPServerConfig:
    server_id: str
    title: str
    description: str = ""
    transport: str = "stdio"
    enabled: bool = True
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    url: str = ""
    scope: str = "project"
    tags: tuple[str, ...] = ()
    allowed_operations: tuple[str, ...] = ()
    requires_approval_operations: tuple[str, ...] = ()
    denied_operations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["args"] = list(self.args)
        payload["tags"] = list(self.tags)
        payload["allowed_operations"] = list(self.allowed_operations)
        payload["requires_approval_operations"] = list(self.requires_approval_operations)
        payload["denied_operations"] = list(self.denied_operations)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExternalMCPServerConfig":
        return cls(
            server_id=str(payload.get("server_id") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            transport=str(payload.get("transport") or "stdio").strip() or "stdio",
            enabled=bool(payload.get("enabled", True)),
            command=str(payload.get("command") or "").strip(),
            args=tuple(str(item) for item in list(payload.get("args") or [])),
            env={str(key): str(value) for key, value in dict(payload.get("env") or {}).items()},
            cwd=str(payload.get("cwd") or "").strip(),
            url=str(payload.get("url") or "").strip(),
            scope=str(payload.get("scope") or "project").strip() or "project",
            tags=tuple(str(item) for item in list(payload.get("tags") or [])),
            allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or [])),
            requires_approval_operations=tuple(
                str(item) for item in list(payload.get("requires_approval_operations") or [])
            ),
            denied_operations=tuple(str(item) for item in list(payload.get("denied_operations") or [])),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class ExternalMCPSnapshot:
    server_id: str
    title: str
    transport: str
    enabled: bool
    scope: str
    status: str
    status_reason: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    tools: list[ExternalMCPTool] = field(default_factory=list)
    resources: list[ExternalMCPResource] = field(default_factory=list)
    prompts: list[ExternalMCPPrompt] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "title": self.title,
            "transport": self.transport,
            "enabled": self.enabled,
            "scope": self.scope,
            "status": self.status,
            "status_reason": self.status_reason,
            "capabilities": dict(self.capabilities),
            "tools": [tool.to_dict() for tool in self.tools],
            "resources": [resource.to_dict() for resource in self.resources],
            "prompts": [prompt.to_dict() for prompt in self.prompts],
            "diagnostics": dict(self.diagnostics),
        }
