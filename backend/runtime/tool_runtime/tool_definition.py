from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from runtime.tool_runtime.tool_result_envelope import ToolResultEnvelope
from runtime.tool_runtime.tool_use_context import ToolUseContext


@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    allowed: bool
    reason: str = ""
    repair_instruction: str = ""
    normalized_args: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolPermissionResult:
    allowed: bool
    decision: str
    reason: str = ""
    requires_approval: bool = False
    approval_fingerprint: str = ""
    repair_instruction: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class RuntimeToolDefinition(Protocol):
    name: str
    operation_id: str
    input_schema: Any
    output_schema: Any

    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        ...

    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        ...

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        ...
