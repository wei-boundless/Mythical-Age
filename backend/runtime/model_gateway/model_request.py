from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.prompt_accounting.serializer import canonical_json
from prompt_composition.provider_payload_plan import build_provider_payload_plan

from .lightweight_chat_model import provider_message_payloads, provider_tool_payloads
from .provider_cache_policy import ProviderCachePolicy, ProviderCachePolicyResolver
from .provider_payload import ProviderPayloadManifest


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
    prefix_tier: str = "volatile"
    compression_role: str = "summarize"
    planned_content_hash: str = ""
    planned_model_message_hash: str = ""
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
    base_url: str = ""
    tools: tuple[dict[str, Any], ...] = ()
    segment_plan: dict[str, Any] = field(default_factory=dict)
    segment_bindings: tuple[ModelRequestSegmentBinding, ...] = ()
    canonical_hash: str = ""
    stable_prefix_hash: str = ""
    provider_global_prefix_hash: str = ""
    session_prefix_hash: str = ""
    task_prefix_hash: str = ""
    provider_payload_prefix_hash: str = ""
    provider_payload_provider_global_prefix_hash: str = ""
    provider_payload_session_prefix_hash: str = ""
    provider_payload_task_prefix_hash: str = ""
    provider_payload_message_prefix_hash: str = ""
    transport_contract_hash: str = ""
    transport_contract_ref: str = ""
    tool_catalog_hash: str = ""
    stable_tool_catalog_hash: str = ""
    tool_catalog_manifest: dict[str, Any] = field(default_factory=dict)
    cache_sensitive_params_hash: str = ""
    cache_policy: ProviderCachePolicy = field(default_factory=lambda: ProviderCachePolicy(provider=""))
    provider_payload_manifest: ProviderPayloadManifest | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.model_request_packet"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["messages"] = [dict(message) for message in self.messages]
        payload["tools"] = [dict(tool) for tool in self.tools]
        payload["segment_plan"] = dict(self.segment_plan)
        payload["tool_catalog_manifest"] = dict(self.tool_catalog_manifest)
        payload["segment_bindings"] = [binding.to_dict() for binding in self.segment_bindings]
        payload["cache_policy"] = self.cache_policy.to_dict()
        payload["provider_payload_manifest"] = (
            self.provider_payload_manifest.to_dict()
            if self.provider_payload_manifest is not None
            else {}
        )
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
        base_url: str = "",
        segment_plan: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelRequestPacket:
        raw_messages = list(messages or [])
        raw_tools = list(tools or [])
        plan = dict(segment_plan or {})
        metadata_payload = dict(metadata or {})
        cache_relevant_params = dict(metadata_payload.get("cache_relevant_params") or {})
        provider_transport_messages = tuple(provider_message_payloads(raw_messages))
        provider_transport_tools = tuple(
            provider_tool_payloads(raw_tools, strict=_transport_tool_strict(cache_relevant_params))
        )
        bindings = tuple(_bindings_from_plan(plan, provider_transport_messages))
        stable_prefix_hash = _stable_prefix_hash(bindings)
        tier_hashes = _prefix_tier_hashes(bindings)
        binding_diagnostics = _binding_diagnostics(bindings, provider_transport_messages)
        provider_transport_message_hashes = tuple(
            _stable_text_hash(canonical_json(message)) for message in provider_transport_messages
        )
        provider_transport_tools_hash = _stable_text_hash(canonical_json(list(provider_transport_tools))) if provider_transport_tools else ""
        tool_catalog_manifest_payload = _tool_catalog_manifest_from_metadata(metadata_payload)
        provider_reasoning_contract = _provider_reasoning_contract_diagnostics(
            provider=str(provider or ""),
            model=str(model or ""),
            cache_relevant_params=cache_relevant_params,
            messages=provider_transport_messages,
        )
        canonical = canonical_json(
            {
                "messages": list(provider_transport_messages),
                "tools": list(provider_transport_tools),
            }
        )
        cache_policy = self.cache_policy_resolver.resolve(provider=provider, model=model, base_url=base_url)
        provider_payload_plan = build_provider_payload_plan(
            request_id=str(request_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            messages=provider_transport_messages,
            tools=provider_transport_tools,
            segment_bindings=bindings,
            request_params=cache_relevant_params,
            tool_catalog_manifest=tool_catalog_manifest_payload,
            assembly_plan_id=str(
                dict(metadata_payload.get("prompt_manifest") or {}).get("prompt_assembly_plan_ref")
                or dict(plan.get("diagnostics") or {}).get("prompt_assembly_plan_ref")
                or plan.get("provider_policy_ref")
                or ""
            ),
        )
        provider_payload_manifest = provider_payload_plan.provider_payload_manifest
        if provider_payload_manifest is None:
            raise ValueError("provider payload plan did not produce a manifest")
        provider_payload_boundary = dict(provider_payload_manifest.cache_boundary or {})
        provider_payload_tiers = dict(provider_payload_boundary.get("tier_prefixes") or {})
        return ModelRequestPacket(
            request_id=str(request_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            base_url=str(base_url or ""),
            messages=provider_transport_messages,
            tools=provider_transport_tools,
            segment_plan=plan,
            segment_bindings=bindings,
            canonical_hash=_stable_text_hash(canonical),
            stable_prefix_hash=stable_prefix_hash,
            provider_global_prefix_hash=tier_hashes["provider_global"],
            session_prefix_hash=tier_hashes["session"],
            task_prefix_hash=tier_hashes["task"],
            provider_payload_prefix_hash=str(provider_payload_boundary.get("provider_payload_prefix_hash") or ""),
            provider_payload_provider_global_prefix_hash=str(dict(provider_payload_tiers.get("provider_global") or {}).get("provider_payload_prefix_hash") or ""),
            provider_payload_session_prefix_hash=str(dict(provider_payload_tiers.get("session") or {}).get("provider_payload_prefix_hash") or ""),
            provider_payload_task_prefix_hash=str(dict(provider_payload_tiers.get("task") or {}).get("provider_payload_prefix_hash") or ""),
            provider_payload_message_prefix_hash=str(provider_payload_boundary.get("provider_payload_message_prefix_hash") or ""),
            transport_contract_hash=str(provider_payload_boundary.get("transport_contract_hash") or ""),
            transport_contract_ref=str(provider_payload_boundary.get("transport_contract_ref") or ""),
            tool_catalog_hash=str(provider_payload_boundary.get("tool_catalog_hash") or ""),
            stable_tool_catalog_hash=str(provider_payload_boundary.get("stable_tool_catalog_hash") or ""),
            tool_catalog_manifest=tool_catalog_manifest_payload,
            cache_sensitive_params_hash=str(provider_payload_boundary.get("cache_sensitive_params_hash") or ""),
            cache_policy=cache_policy,
            provider_payload_manifest=provider_payload_manifest,
            diagnostics={
                "planned_segment_count": len(list(plan.get("segments") or [])),
                "bound_segment_count": len(bindings),
                "provider_payload_plan_ref": provider_payload_plan.plan_id,
                "provider_payload_manifest_ref": provider_payload_manifest.manifest_id,
                "provider_payload_cache_boundary": provider_payload_boundary,
                "provider_payload_plan": provider_payload_plan.to_dict(),
                "transport_contract_ref": str(provider_payload_boundary.get("transport_contract_ref") or ""),
                "transport_contract_hash": str(provider_payload_boundary.get("transport_contract_hash") or ""),
                "tool_catalog_manifest_ref": str(tool_catalog_manifest_payload.get("manifest_id") or ""),
                "tool_catalog_manifest_hash": str(tool_catalog_manifest_payload.get("tool_catalog_hash") or ""),
                "provider_transport_payload": {
                    "message_count": len(provider_transport_messages),
                    "tool_count": len(provider_transport_tools),
                    "messages_hash": _stable_text_hash(canonical_json(list(provider_transport_messages))),
                    "message_hashes": list(provider_transport_message_hashes),
                    "tools_hash": provider_transport_tools_hash,
                    "tool_schema_sorted_by_name": True,
                    "messages_include_provider_reasoning_content": any(
                        bool(dict(message).get("reasoning_content"))
                        for message in provider_transport_messages
                    ),
                },
                "provider_reasoning_contract": provider_reasoning_contract,
                "unplanned_message_count": max(0, len(provider_transport_messages) - len(bindings)),
                **binding_diagnostics,
                "prefix_tier_hashes": tier_hashes,
                **metadata_payload,
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
                prefix_tier=_prefix_tier(raw_segment.get("prefix_tier"), cache_scope=str(raw_segment.get("cache_scope") or "none"), cache_role=_cache_role(raw_segment.get("cache_role"))),
                compression_role=_compression_role(raw_segment.get("compression_role")),
                planned_content_hash=str(raw_segment.get("content_hash") or ""),
                planned_model_message_hash=str(raw_segment.get("model_message_hash") or ""),
                request_content_hash=_stable_text_hash(message_payload),
                byte_length=len(message_payload.encode("utf-8", errors="ignore")),
                metadata=dict(raw_segment.get("metadata") or {}),
            )
        )
    return result


def _provider_reasoning_contract_diagnostics(
    *,
    provider: str,
    model: str,
    cache_relevant_params: dict[str, Any],
    messages: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    thinking_mode = str(dict(cache_relevant_params or {}).get("thinking_mode") or "").strip().lower()
    deepseek_v4_thinking = (
        normalized_provider == "deepseek"
        and normalized_model in {"deepseek-v4-pro", "deepseek-v4-flash"}
        and thinking_mode == "enabled"
    )
    assistant_tool_call_indexes: list[int] = []
    missing_reasoning_indexes: list[int] = []
    reasoning_indexes: list[int] = []
    for index, message in enumerate(tuple(messages or ())):
        payload = dict(message or {})
        if str(payload.get("role") or "") != "assistant" or not payload.get("tool_calls"):
            continue
        assistant_tool_call_indexes.append(index)
        if str(payload.get("reasoning_content") or "").strip():
            reasoning_indexes.append(index)
        else:
            missing_reasoning_indexes.append(index)
    status = "not_applicable"
    if deepseek_v4_thinking:
        status = "ok" if not missing_reasoning_indexes else "missing_reasoning_content_for_tool_call_history"
    return {
        "provider": normalized_provider,
        "model": str(model or ""),
        "thinking_mode": thinking_mode,
        "deepseek_v4_thinking_contract": deepseek_v4_thinking,
        "assistant_tool_call_message_indexes": assistant_tool_call_indexes,
        "assistant_tool_call_reasoning_content_indexes": reasoning_indexes,
        "assistant_tool_call_missing_reasoning_content_indexes": missing_reasoning_indexes,
        "status": status,
        "rule": (
            "DeepSeek V4 thinking tool-call assistant history must preserve provider-visible reasoning_content "
            "together with tool_calls and subsequent tool observations"
        ),
        "authority": "runtime.model_gateway.model_request.provider_reasoning_contract",
    }


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


def _prefix_tier_hashes(bindings: tuple[ModelRequestSegmentBinding, ...]) -> dict[str, str]:
    tiers = {
        "provider_global": {"provider_global"},
        "session": {"provider_global", "session"},
        "task": {"provider_global", "session", "task"},
    }
    result: dict[str, str] = {}
    ordered = sorted(bindings, key=lambda item: item.ordinal)
    for name, allowed in tiers.items():
        parts: list[str] = []
        expected_index = 0
        for binding in ordered:
            if binding.model_message_index != expected_index:
                break
            if binding.prefix_tier in allowed:
                parts.append(binding.request_content_hash)
                expected_index += 1
                continue
            break
        result[name] = _stable_text_hash("|".join(parts)) if parts else ""
    return result


def _binding_diagnostics(
    bindings: tuple[ModelRequestSegmentBinding, ...],
    normalized_messages: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    mismatched_bindings = [
        binding.planned_segment_id
        for binding in bindings
        if binding.planned_model_message_hash and binding.planned_model_message_hash != binding.request_content_hash
    ]
    contiguous_prefix_count = 0
    for expected_index, binding in enumerate(sorted(bindings, key=lambda item: item.ordinal)):
        if binding.model_message_index != expected_index:
            break
        contiguous_prefix_count += 1
        if binding.cache_role not in {"cacheable_prefix", "session_stable"}:
            break
    return {
        "segment_binding_content_mismatch_count": len(mismatched_bindings),
        "segment_binding_content_mismatch_ids": mismatched_bindings[:10],
        "segment_bindings_match_planned_messages": not mismatched_bindings,
        "contiguous_planned_prefix_count": contiguous_prefix_count,
        "request_message_count": len(normalized_messages),
    }


def _tool_catalog_manifest_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    direct = metadata.get("tool_catalog_manifest")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    prompt_manifest = dict(metadata.get("prompt_manifest") or {}) if isinstance(metadata.get("prompt_manifest"), dict) else {}
    nested = prompt_manifest.get("tool_catalog_manifest")
    return dict(nested) if isinstance(nested, dict) else {}


def _transport_tool_strict(cache_relevant_params: dict[str, Any]) -> bool | None:
    options = cache_relevant_params.get("tool_call_options")
    if isinstance(options, dict) and "strict" in options and options.get("strict") is not None:
        return bool(options.get("strict"))
    if cache_relevant_params.get("response_format"):
        return True
    return None


def _cache_role(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized
    return "volatile"


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> str:
    normalized = str(value or "").strip()
    if normalized in {"provider_global", "session", "task", "volatile", "none"}:
        return normalized
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "task":
            return "task"
        if scope == "session":
            return "session"
        if scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "volatile":
        return "volatile"
    return "none"


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
