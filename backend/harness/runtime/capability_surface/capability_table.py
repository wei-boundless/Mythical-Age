from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolCapabilitySourceTrace:
    source: str
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolCapabilityFilterIssue:
    operation_id: str
    tool_name: str = ""
    reason: str = ""
    source: str = ""
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolCapability:
    operation_id: str
    tool_name: str
    visible: bool
    dispatchable: bool
    requires_approval: bool = False
    file_repository_grants: tuple[str, ...] = ()
    source_trace: tuple[ToolCapabilitySourceTrace, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["file_repository_grants"] = list(self.file_repository_grants)
        payload["source_trace"] = [item.to_dict() for item in self.source_trace]
        return payload


@dataclass(frozen=True, slots=True)
class ToolCapabilityTable:
    table_id: str
    environment_id: str
    capabilities: tuple[ToolCapability, ...] = ()
    filtered: tuple[ToolCapabilityFilterIssue, ...] = ()
    source_trace: tuple[ToolCapabilitySourceTrace, ...] = ()
    authority: str = "harness.runtime.capability_surface.tool_capability_table"

    @property
    def visible_tools(self) -> tuple[str, ...]:
        return tuple(item.tool_name for item in self.capabilities if item.visible)

    @property
    def dispatchable_tools(self) -> tuple[str, ...]:
        return tuple(item.tool_name for item in self.capabilities if item.dispatchable)

    @property
    def visible_operations(self) -> tuple[str, ...]:
        return tuple(item.operation_id for item in self.capabilities if item.visible)

    @property
    def dispatchable_operations(self) -> tuple[str, ...]:
        return tuple(item.operation_id for item in self.capabilities if item.dispatchable)

    def capability_for_operation(self, operation_id: str) -> ToolCapability | None:
        target = str(operation_id or "").strip()
        return next((item for item in self.capabilities if item.operation_id == target), None)

    def capability_for_tool(self, *, operation_id: str, tool_name: str) -> ToolCapability | None:
        target_operation = str(operation_id or "").strip()
        target_tool = str(tool_name or "").strip()
        return next(
            (
                item
                for item in self.capabilities
                if item.operation_id == target_operation and item.tool_name == target_tool
            ),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "environment_id": self.environment_id,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "filtered": [item.to_dict() for item in self.filtered],
            "source_trace": [item.to_dict() for item in self.source_trace],
            "authority": self.authority,
        }


