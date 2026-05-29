from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.prompt_accounting.serializer import canonical_json, normalize_messages, normalize_tools

from .provider_cache_policy import ProviderCachePolicy, ProviderCachePolicyResolver


@dataclass(frozen=True, slots=True)
class ModelRequestSegmentBinding:
    planned_segment_id: str
    kind: str
    ordinal: int
    model_message_index: int
    model_message_role: str
    source_ref: str = ""
    cache_scope: str = "none"
    cache_role: str = "volatile"
    compression_role: str = "summarize"
    planned_content_hash: str = ""
    request_content_hash: str = ""
    byte_length: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.model_request_segment_binding"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ModelRequestPacket:
    request_id: str
    provider: str
    model: str
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    segment_plan: dict[str, Any] = field(default_factory=dict)
    segment_bindings: tuple[ModelRequestSegmentBinding, ...] = ()
    canonical_hash: str = ""
    stable_prefix_hash: str = ""
    cache_policy: ProviderCachePolicy = field(default_factory=lambda: ProviderCachePolicy(provider=""))
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.model_request_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["messages"] = [dict(message) for message in self.messages]
        payload["tools"] = [dict(tool) for tool in self.tools]
        payload["segment_plan"] = dict(self.segment_plan)
        payload["segment_bindings"] = [binding.to_dict() for binding in self.segment_bindings]
        payload["cache_policy"] = self.cache_policy.to_dict()
        payload["diagnostics"] = dict(self.diagnostics)
        return payload


class ModelRequestBuilder:
    def __init__(self, *, cache_policy_resolver: ProviderCachePolicyResolver | None = None) -> None:
        self.cache_policy_resolver = cache_policy_resolver or ProviderCachePolicyResolver()

    def build(
        self,
        *,
        request_id: str,
        messages: list[Any],
        tools: list[Any] | None = None,
        provider: str = "",
        model: str = "",
        segment_plan: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelRequestPacket:
        normalized_messages = tuple(normalize_messages(list(messages or [])))
        normalized_tools = tuple(normalize_tools(list(tools or [])))
        plan = dict(segment_plan or {})
        bindings = tuple(_bindings_from_plan(plan, normalized_messages))
        stable_prefix_hash = _stable_prefix_hash(bindings)
        canonical = canonical_json(
            {
                "messages": list(normalized_messages),
                "tools": list(normalized_tools),
                "metadata": dict(metadata or {}),
            }
        )
        cache_policy = self.cache_policy_resolver.resolve(provider=provider, model=model)
        return ModelRequestPacket(
            request_id=str(request_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            messages=normalized_messages,
            tools=normalized_tools,
            segment_plan=plan,
            segment_bindings=bindings,
            canonical_hash=_stable_text_hash(canonical),
            stable_prefix_hash=stable_prefix_hash,
            cache_policy=cache_policy,
            diagnostics={
                "planned_segment_count": len(list(plan.get("segments") or [])),
                "bound_segment_count": len(bindings),
                "unplanned_message_count": max(0, len(normalized_messages) - len(bindings)),
                **dict(metadata or {}),
            },
        )


def _bindings_from_plan(
    segment_plan: dict[str, Any],
    normalized_messages: tuple[dict[str, Any], ...],
) -> list[ModelRequestSegmentBinding]:
    result: list[ModelRequestSegmentBinding] = []
    for raw_segment in list(segment_plan.get("segments") or []):
        if not isinstance(raw_segment, dict):
            continue
        message_index = _int(raw_segment.get("model_message_index"), default=-1)
        if message_index < 0 or message_index >= len(normalized_messages):
            continue
        message = normalized_messages[message_index]
        message_payload = canonical_json(message)
        result.append(
            ModelRequestSegmentBinding(
                planned_segment_id=str(raw_segment.get("segment_id") or ""),
                kind=str(raw_segment.get("kind") or "unknown_unplanned"),
                ordinal=_int(raw_segment.get("ordinal"), default=len(result) + 1),
                model_message_index=message_index,
                model_message_role=str(raw_segment.get("model_message_role") or message.get("role") or ""),
                source_ref=str(raw_segment.get("source_ref") or ""),
                cache_scope=str(raw_segment.get("cache_scope") or "none"),
                cache_role=_cache_role(raw_segment.get("cache_role")),
                compression_role=_compression_role(raw_segment.get("compression_role")),
                planned_content_hash=str(raw_segment.get("content_hash") or ""),
                request_content_hash=_stable_text_hash(message_payload),
                byte_length=len(message_payload.encode("utf-8", errors="ignore")),
                metadata=dict(raw_segment.get("metadata") or {}),
            )
        )
    return result


def _stable_prefix_hash(bindings: tuple[ModelRequestSegmentBinding, ...]) -> str:
    parts: list[str] = []
    expected_index = 0
    for binding in sorted(bindings, key=lambda item: item.ordinal):
        if binding.model_message_index != expected_index:
            break
        if binding.cache_role in {"cacheable_prefix", "session_stable"}:
            parts.append(binding.request_content_hash)
            expected_index += 1
            continue
        break
    if not parts:
        return ""
    return _stable_text_hash("|".join(parts))


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _compression_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized
    return "summarize"


def _stable_text_hash(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
