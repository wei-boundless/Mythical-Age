from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ASSISTANT_STREAM_FRAME_SCHEMA_VERSION": (
        "runtime.model_gateway.assistant_stream_frame",
        "ASSISTANT_STREAM_FRAME_SCHEMA_VERSION",
    ),
    "ASSISTANT_STREAM_REPAIR_EVENT": ("runtime.model_gateway.assistant_stream_frame", "ASSISTANT_STREAM_REPAIR_EVENT"),
    "ASSISTANT_TEXT_DELTA_EVENT": ("runtime.model_gateway.assistant_stream_frame", "ASSISTANT_TEXT_DELTA_EVENT"),
    "ASSISTANT_TEXT_FINAL_EVENT": ("runtime.model_gateway.assistant_stream_frame", "ASSISTANT_TEXT_FINAL_EVENT"),
    "AssistantStreamFrame": ("runtime.model_gateway.assistant_stream_frame", "AssistantStreamFrame"),
    "AssistantStreamNormalizer": ("runtime.model_gateway.assistant_stream_normalizer", "AssistantStreamNormalizer"),
    "ModelRequestBuilder": ("runtime.model_gateway.model_request", "ModelRequestBuilder"),
    "ModelRequestPacket": ("runtime.model_gateway.model_request", "ModelRequestPacket"),
    "ModelRequestSegmentBinding": ("runtime.model_gateway.model_request", "ModelRequestSegmentBinding"),
    "ModelResponseProtocolResult": ("runtime.model_gateway.model_response_protocol", "ModelResponseProtocolResult"),
    "ModelResponseRuntimeExecutor": ("runtime.model_gateway.model_response", "ModelResponseRuntimeExecutor"),
    "ModelRuntime": ("runtime.model_gateway.model_runtime", "ModelRuntime"),
    "ModelRuntimeError": ("runtime.model_gateway.model_runtime", "ModelRuntimeError"),
    "ModelSpec": ("runtime.model_gateway.model_runtime", "ModelSpec"),
    "ProviderCachePolicy": ("runtime.model_gateway.provider_cache_policy", "ProviderCachePolicy"),
    "ProviderCachePolicyResolver": ("runtime.model_gateway.provider_cache_policy", "ProviderCachePolicyResolver"),
    "RuntimeConversationAgent": ("runtime.model_gateway.model_runtime", "RuntimeConversationAgent"),
    "model_response_protocol_from_response": (
        "runtime.model_gateway.model_response_protocol",
        "model_response_protocol_from_response",
    ),
    "stringify_content": ("runtime.model_gateway.model_runtime", "stringify_content"),
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
