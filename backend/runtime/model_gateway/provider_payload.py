from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_cache_policy import normalize_cache_role, normalize_compression_role, normalize_prefix_tier
from runtime.prompt_accounting.serializer import canonical_json


@dataclass(frozen=True, slots=True)
class ProviderPayloadSegment:
    segment_id: str
    kind: str
    transport_location: str
    ordinal: int
    source_ref: str = ""
    content_hash: str = ""
    byte_length: int = 0
    cache_scope: str = "none"
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    compression_role: str = "summarize"
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.provider_payload.segment"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ProviderPayloadManifest:
    manifest_id: str
    request_id: str
    provider: str
    model: str
    segments: tuple[ProviderPayloadSegment, ...] = ()
    cache_boundary: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.provider_payload.manifest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "request_id": self.request_id,
            "provider": self.provider,
            "model": self.model,
            "segments": [segment.to_dict() for segment in self.segments],
            "cache_boundary": dict(self.cache_boundary),
            "diagnostics": dict(self.diagnostics),
            "authority": self.authority,
        }


def build_provider_payload_manifest(
    *,
    request_id: str,
    provider: str,
    model: str,
    messages: tuple[dict[str, Any], ...],
    tools: tuple[dict[str, Any], ...],
    segment_bindings: tuple[Any, ...],
) -> ProviderPayloadManifest:
    segments: list[ProviderPayloadSegment] = []
    covered_message_indexes: set[int] = set()
    ordinal = 0
    bindings = sorted(
        [binding for binding in tuple(segment_bindings or ())],
        key=lambda item: int(getattr(item, "ordinal", 0) or 0),
    )
    for binding in bindings:
        message_index = int(getattr(binding, "model_message_index", -1) or -1)
        if message_index < 0 or message_index >= len(messages):
            continue
        ordinal += 1
        covered_message_indexes.add(message_index)
        message = dict(messages[message_index])
        payload = canonical_json(message)
        segments.append(
            ProviderPayloadSegment(
                segment_id=str(getattr(binding, "planned_segment_id", "") or _segment_id(request_id, ordinal, getattr(binding, "kind", "message"), payload)),
                kind=str(getattr(binding, "kind", "") or "message"),
                transport_location="messages",
                ordinal=ordinal,
                source_ref=str(getattr(binding, "source_ref", "") or "model_request.message"),
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope=str(getattr(binding, "cache_scope", "") or "none"),
                cache_role=normalize_cache_role(getattr(binding, "cache_role", "")),
                prefix_tier=normalize_prefix_tier(
                    getattr(binding, "prefix_tier", ""),
                    cache_scope=str(getattr(binding, "cache_scope", "") or "none"),
                    cache_role=normalize_cache_role(getattr(binding, "cache_role", "")),
                ),
                compression_role=normalize_compression_role(getattr(binding, "compression_role", "")),
                metadata={**dict(getattr(binding, "metadata", {}) or {}), "message_index": message_index},
            )
        )
    for message_index, message in enumerate(messages):
        if message_index in covered_message_indexes:
            continue
        ordinal += 1
        payload = canonical_json(dict(message))
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "unplanned_message", payload),
                kind="unplanned_message",
                transport_location="messages",
                ordinal=ordinal,
                source_ref="model_request.unplanned_message",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="summarize",
                metadata={"message_index": message_index, "planned": False},
            )
        )
    if tools:
        ordinal += 1
        profile = _tool_schema_cache_profile(messages=messages, tools=tools, segments=tuple(segments))
        payload = canonical_json({"tools": [dict(item) for item in tools]})
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "tool_schema_catalog", payload),
                kind="tool_schema_catalog",
                transport_location="tools",
                ordinal=ordinal,
                source_ref=str(profile.get("source_ref") or "model_request.tools"),
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope=str(profile.get("cache_scope") or "none"),
                cache_role=str(profile.get("cache_role") or "never_cache"),
                prefix_tier=str(profile.get("prefix_tier") or "none"),
                compression_role="preserve",
                metadata={**dict(profile.get("metadata") or {}), "tool_count": len(tools)},
            )
        )
    ordered_segments = tuple(sorted(segments, key=lambda item: item.ordinal))
    seed = {
        "request_id": str(request_id or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "segments": [
            {
                "kind": segment.kind,
                "transport_location": segment.transport_location,
                "source_ref": segment.source_ref,
                "content_hash": segment.content_hash,
                "cache_role": segment.cache_role,
                "prefix_tier": segment.prefix_tier,
            }
            for segment in ordered_segments
        ],
    }
    return ProviderPayloadManifest(
        manifest_id="ppmanifest:" + _digest(seed)[:16],
        request_id=str(request_id or ""),
        provider=str(provider or ""),
        model=str(model or ""),
        segments=ordered_segments,
        cache_boundary=_cache_boundary(ordered_segments),
        diagnostics={
            "message_segment_count": sum(1 for segment in ordered_segments if segment.transport_location == "messages"),
            "tool_segment_count": sum(1 for segment in ordered_segments if segment.transport_location == "tools"),
            "authority": "runtime.model_gateway.provider_payload.builder",
        },
    )


def _tool_schema_cache_profile(
    *,
    messages: tuple[dict[str, Any], ...],
    tools: tuple[dict[str, Any], ...],
    segments: tuple[ProviderPayloadSegment, ...],
) -> dict[str, Any]:
    tool_index = next((segment for segment in segments if segment.kind == "tool_index_stable"), None)
    if tool_index is None:
        return _tool_schema_never_cache("missing_stable_tool_index")
    message_index = int(dict(tool_index.metadata or {}).get("message_index") or -1)
    if message_index < 0 or message_index >= len(messages):
        return _tool_schema_never_cache("stable_tool_index_message_missing")
    payload = _parse_titled_json_payload(str(dict(messages[message_index]).get("content") or ""))
    expected = _tool_index_fingerprint(payload)
    actual = _provider_tool_schema_fingerprint(tools)
    if expected != actual:
        return _tool_schema_never_cache(
            "provider_tools_do_not_match_tool_index",
            expected_tool_names=list(expected.get("tool_names") or []),
            actual_tool_names=list(actual.get("tool_names") or []),
            stable_tool_index_segment_id=tool_index.segment_id,
        )
    if tool_index.cache_role not in {"cacheable_prefix", "session_stable"}:
        return _tool_schema_never_cache(
            "matched_tool_index_is_not_stable",
            stable_tool_index_segment_id=tool_index.segment_id,
        )
    return {
        "source_ref": tool_index.source_ref or "model_request.tools",
        "cache_scope": tool_index.cache_scope,
        "cache_role": tool_index.cache_role,
        "prefix_tier": tool_index.prefix_tier,
        "metadata": {
            "tool_schema_cache_decision": "derived_from_stable_tool_index",
            "cache_note": "tool_schema_cache_role_derived_from_matching_stable_tool_index",
            "stable_tool_index_segment_id": tool_index.segment_id,
            "stable_tool_index_cache_scope": tool_index.cache_scope,
            "stable_tool_index_cache_role": tool_index.cache_role,
            "stable_tool_index_prefix_tier": tool_index.prefix_tier,
        },
    }


def _tool_schema_never_cache(reason: str, **metadata: Any) -> dict[str, Any]:
    return {
        "source_ref": "model_request.tools",
        "cache_scope": "none",
        "cache_role": "never_cache",
        "prefix_tier": "none",
        "metadata": {
            "tool_schema_cache_decision": "not_promoted",
            "tool_schema_cache_reason": str(reason or "unknown"),
            "cache_note": "tool_schema_is_recorded_but_not_promoted_without_matching_stable_tool_index",
            **dict(metadata),
        },
    }


def _parse_titled_json_payload(content: str) -> Any | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "\n" in text:
        candidates.append(text.split("\n", 1)[1].strip())
    for candidate in candidates:
        if not candidate or candidate[0] not in "{[":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _tool_index_fingerprint(payload: Any) -> dict[str, Any]:
    available = list(dict(payload or {}).get("available_tools") or []) if isinstance(payload, dict) else []
    tools: list[dict[str, str]] = []
    for item in available:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or item.get("name") or "").strip()
        if not name:
            continue
        tools.append({"name": name, "input_schema_ref": str(item.get("input_schema_ref") or "").strip()})
    ordered = sorted(tools, key=lambda item: item["name"])
    return {"tools": ordered, "tool_names": [item["name"] for item in ordered]}


def _provider_tool_schema_fingerprint(tools: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    for tool in tools:
        name = str(dict(tool).get("name") or "").strip()
        if not name:
            continue
        items.append({"name": name, "input_schema_ref": _short_schema_ref(dict(tool).get("schema") or {})})
    ordered = sorted(items, key=lambda item: item["name"])
    return {"tools": ordered, "tool_names": [item["name"] for item in ordered]}


def _short_schema_ref(schema: Any) -> str:
    digest = _stable_text_hash(canonical_json(schema or {}))
    return "sha256:" + digest.removeprefix("sha256:")[:10]


def _cache_boundary(segments: tuple[ProviderPayloadSegment, ...]) -> dict[str, Any]:
    stable = [segment for segment in segments if segment.cache_role in {"cacheable_prefix", "session_stable"}]
    return {
        "stable_segment_count": len(stable),
        "stable_segment_hash": _stable_text_hash("|".join(segment.content_hash for segment in stable)) if stable else "",
        "tool_schema_segment_count": sum(1 for segment in segments if segment.transport_location == "tools"),
        "tool_schema_cache_roles": [
            segment.cache_role for segment in segments if segment.transport_location == "tools"
        ],
        "authority": "runtime.model_gateway.provider_payload.cache_boundary",
    }


def _segment_id(request_id: str, ordinal: int, kind: Any, payload: str) -> str:
    return f"ppseg:{request_id}:{ordinal}:{str(kind or 'segment')}:{_stable_text_hash(payload).split(':', 1)[-1][:12]}"


def _stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
