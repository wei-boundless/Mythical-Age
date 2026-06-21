from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "RuntimeToolControlPlane": ("runtime.tool_runtime.tool_control_plane", "RuntimeToolControlPlane"),
    "RuntimeToolDefinition": ("runtime.tool_runtime.tool_definition", "RuntimeToolDefinition"),
    "ToolCallBindingOptions": ("runtime.tool_runtime.tool_call_policy", "ToolCallBindingOptions"),
    "ToolCallIntent": ("runtime.tool_runtime.tool_call_intent", "ToolCallIntent"),
    "ToolInvocationAlreadyStartedError": (
        "runtime.tool_runtime.tool_invocation_control",
        "ToolInvocationAlreadyStartedError",
    ),
    "ToolInvocationContext": ("runtime.tool_runtime.tool_invocation_control", "ToolInvocationContext"),
    "ToolInvocationControlRegistry": (
        "runtime.tool_runtime.tool_invocation_control",
        "ToolInvocationControlRegistry",
    ),
    "ToolInvocationRecord": ("runtime.tool_runtime.tool_invocation_control", "ToolInvocationRecord"),
    "ToolInvocationRequest": ("runtime.tool_runtime.tool_invocation_request", "ToolInvocationRequest"),
    "ToolObservation": ("runtime.tool_runtime.tool_observation", "ToolObservation"),
    "ToolPermissionResult": ("runtime.tool_runtime.tool_definition", "ToolPermissionResult"),
    "ToolResultEnvelope": ("runtime.tool_runtime.tool_result_envelope", "ToolResultEnvelope"),
    "ToolRuntimeExecutor": ("runtime.tool_runtime.tool_executor", "ToolRuntimeExecutor"),
    "ToolUseContext": ("runtime.tool_runtime.tool_use_context", "ToolUseContext"),
    "ToolValidationResult": ("runtime.tool_runtime.tool_definition", "ToolValidationResult"),
    "build_round_tool_call_options": ("runtime.tool_runtime.tool_call_policy", "build_round_tool_call_options"),
    "build_tool_invocation_id": ("runtime.tool_runtime.tool_invocation_control", "build_tool_invocation_id"),
    "build_tool_invocation_idempotency_key": (
        "runtime.tool_runtime.tool_invocation_control",
        "build_tool_invocation_idempotency_key",
    ),
    "build_tool_result_envelope": ("runtime.tool_runtime.tool_result_envelope", "build_tool_result_envelope"),
    "build_tool_result_envelope_id": (
        "runtime.tool_runtime.tool_result_envelope",
        "build_tool_result_envelope_id",
    ),
    "build_tool_result_idempotency_key": (
        "runtime.tool_runtime.tool_result_envelope",
        "build_tool_result_idempotency_key",
    ),
    "extract_tool_call_intents": ("runtime.tool_runtime.provider_tool_call_adapter", "extract_tool_call_intents"),
    "normalize_tool_call_dicts": ("runtime.tool_runtime.provider_tool_call_adapter", "normalize_tool_call_dicts"),
    "registry_for": ("runtime.tool_runtime.tool_invocation_control", "registry_for"),
    "tool_calls_for_langchain_messages": (
        "runtime.tool_runtime.provider_tool_call_adapter",
        "tool_calls_for_langchain_messages",
    ),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
