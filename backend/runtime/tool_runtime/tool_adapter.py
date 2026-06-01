from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runtime.tool_runtime.tool_definition import ToolPermissionResult, ToolValidationResult
from runtime.tool_runtime.tool_result_envelope import ToolResultEnvelope, build_tool_result_envelope
from runtime.tool_runtime.tool_use_context import ToolUseContext

if TYPE_CHECKING:
    from capability_system.tool_definitions import ToolDefinition as CapabilityToolDefinition


@dataclass(slots=True)
class RuntimeToolAdapter:
    capability_definition: CapabilityToolDefinition
    tool_instance: Any
    input_schema: Any = None
    output_schema: Any = None

    @property
    def name(self) -> str:
        return self.capability_definition.name

    @property
    def operation_id(self) -> str:
        return self.capability_definition.operation_id

    @classmethod
    def from_capability_definition(
        cls,
        *,
        capability_definition: CapabilityToolDefinition,
        tool_instance: Any,
    ) -> "RuntimeToolAdapter":
        return cls(
            capability_definition=capability_definition,
            tool_instance=tool_instance,
            input_schema=getattr(tool_instance, "args_schema", None),
            output_schema=None,
        )

    def validate_input(self, args: dict[str, Any], context: ToolUseContext) -> ToolValidationResult:
        required = [
            str(item).strip()
            for item in list(self.capability_definition.contract.required_inputs or [])
            if str(item).strip()
        ]
        missing = [name for name in required if name not in dict(args or {})]
        if missing:
            return ToolValidationResult(
                allowed=False,
                reason="missing_required_tool_inputs",
                repair_instruction="Retry the tool call with required argument(s): " + ", ".join(missing) + ".",
                normalized_args=dict(args or {}),
                diagnostics={"missing_inputs": missing},
            )
        schema = getattr(self.tool_instance, "args_schema", None)
        if schema is not None and hasattr(schema, "model_validate"):
            try:
                validated = schema.model_validate(dict(args or {}))
                normalized = validated.model_dump()
            except Exception as exc:
                return ToolValidationResult(
                    allowed=False,
                    reason="tool_input_schema_validation_failed",
                    repair_instruction=str(exc),
                    normalized_args=dict(args or {}),
                )
            return ToolValidationResult(allowed=True, normalized_args=normalized)
        return ToolValidationResult(allowed=True, normalized_args=dict(args or {}))

    def check_permissions(self, args: dict[str, Any], context: ToolUseContext) -> ToolPermissionResult:
        validator = getattr(self.tool_instance, "validate_permission", None)
        if callable(validator):
            outcome = validator(args)
            if outcome not in {None, True}:
                return ToolPermissionResult(allowed=False, decision="deny", reason=str(outcome or "tool_permission_denied"))
        return ToolPermissionResult(allowed=True, decision="allow")

    async def call(self, args: dict[str, Any], context: ToolUseContext) -> ToolResultEnvelope:
        tool = self.tool_instance
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(
                dict(args or {}),
                config={
                    "metadata": {
                        "tool_invocation_id": context.tool_invocation_id,
                        "idempotency_key": context.idempotency_key,
                    }
                },
            )
        else:
            result = await asyncio.to_thread(tool.invoke, dict(args or {}))
        return build_tool_result_envelope(
            tool_name=self.name,
            tool_args=dict(args or {}),
            result=result,
            execution_receipt=dict(context.execution_receipt or {}),
        )


