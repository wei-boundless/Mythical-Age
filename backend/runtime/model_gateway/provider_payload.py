from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from prompt_composition.context_envelope import parse_context_fragment_payload
from runtime.prompt_accounting.cache_policy import (
    is_cache_eligible_prefix,
    is_prefix_eligible_for_tier,
    normalize_cache_role,
    normalize_compression_role,
    normalize_prefix_tier,
)
from runtime.prompt_accounting.serializer import canonical_json
from runtime.shared.tool_schema_canonical import canonical_provider_schema_ref


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
    transport_contract: dict[str, Any] = field(default_factory=dict)
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
            "transport_contract": dict(self.transport_contract),
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
    request_params: dict[str, Any] | None = None,
    tool_catalog_manifest: dict[str, Any] | None = None,
) -> ProviderPayloadManifest:
    segments: list[ProviderPayloadSegment] = []
    covered_message_indexes: set[int] = set()
    ordinal = 0
    bindings = sorted(
        [binding for binding in tuple(segment_bindings or ())],
        key=lambda item: int(getattr(item, "ordinal", 0) or 0),
    )
    for binding in bindings:
        message_index = _int(getattr(binding, "model_message_index", -1), default=-1)
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
        profile = _tool_schema_cache_profile(
            messages=messages,
            tools=tools,
            segments=tuple(segments),
            tool_catalog_manifest=dict(tool_catalog_manifest or {}),
        )
        payload = canonical_json({"tools": [dict(item) for item in tools]})
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, str(profile.get("kind") or "native_tool_binding_schema"), payload),
                kind=str(profile.get("kind") or "native_tool_binding_schema"),
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
    params = _drop_empty(dict(request_params or {}))
    tool_call_options = _dict_param(params.pop("tool_call_options", {}))
    response_format = _response_format_param(params)
    if tool_call_options:
        ordinal += 1
        payload = canonical_json({"tool_call_options": tool_call_options})
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "tool_call_options", payload),
                kind="tool_call_options",
                transport_location="tool_call_options",
                ordinal=ordinal,
                source_ref="model_request.tool_call_options",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                metadata={"key_only": True, "option_keys": sorted(str(key) for key in tool_call_options)},
            )
        )
    if response_format not in (None, "", [], {}):
        ordinal += 1
        payload = canonical_json({"response_format": response_format})
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "response_format", payload),
                kind="response_format",
                transport_location="response_format",
                ordinal=ordinal,
                source_ref="model_request.response_format",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                metadata={"key_only": True},
            )
        )
    if params:
        ordinal += 1
        payload = canonical_json({"cache_relevant_params": params})
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "provider_params", payload),
                kind="provider_params",
                transport_location="request_params",
                ordinal=ordinal,
                source_ref="model_request.cache_relevant_params",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                metadata={"key_only": True, "param_keys": sorted(str(key) for key in params)},
            )
        )
    ordered_segments = _ordered_provider_payload_segments(
        request_id=str(request_id or ""),
        segments=segments,
    )
    transport_contract = _transport_stable_contract(
        provider=str(provider or ""),
        model=str(model or ""),
        segments=ordered_segments,
    )
    seed = {
        "request_id": str(request_id or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "transport_contract_hash": str(transport_contract.get("contract_hash") or ""),
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
        transport_contract=transport_contract,
        cache_boundary=_cache_boundary(
            ordered_segments,
            transport_contract=transport_contract,
        ),
        diagnostics={
            "message_segment_count": sum(1 for segment in ordered_segments if segment.transport_location == "messages"),
            "tool_segment_count": sum(1 for segment in ordered_segments if segment.transport_location == "tools"),
            "transport_contract_ref": str(transport_contract.get("contract_id") or ""),
            "transport_contract_hash": str(transport_contract.get("contract_hash") or ""),
            "tool_catalog_manifest_ref": str(dict(tool_catalog_manifest or {}).get("manifest_id") or ""),
            "context_cache_section_counts": _context_cache_section_counts(ordered_segments),
            "cache_spine_segment_after_tail_count": _cache_spine_segment_after_tail_count(ordered_segments),
            "cache_spine_contiguous_before_tail": _cache_spine_segment_after_tail_count(ordered_segments) == 0,
            "authority": "runtime.model_gateway.provider_payload.builder",
        },
    )


def _tool_schema_cache_profile(
    *,
    messages: tuple[dict[str, Any], ...],
    tools: tuple[dict[str, Any], ...],
    segments: tuple[ProviderPayloadSegment, ...],
    tool_catalog_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_index = next((segment for segment in segments if segment.kind == "tool_index_stable"), None)
    if tool_index is None:
        return _native_tool_binding_schema_never_cache("missing_stable_tool_index")
    message_index = _int(dict(tool_index.metadata or {}).get("message_index"), default=-1)
    if message_index < 0 or message_index >= len(messages):
        return _native_tool_binding_schema_never_cache("stable_tool_index_message_missing")
    payload = _parse_context_payload(str(dict(messages[message_index]).get("content") or ""))
    manifest_payload = dict(tool_catalog_manifest or {})
    manifest_ref = str(manifest_payload.get("manifest_id") or "")
    expected = _tool_catalog_manifest_fingerprint(manifest_payload) if manifest_payload else _tool_index_fingerprint(payload)
    message_expected = _tool_index_fingerprint(payload)
    if manifest_payload and message_expected.get("tools") and message_expected != expected:
        return _native_tool_binding_schema_never_cache(
            "stable_tool_index_does_not_match_tool_catalog_manifest",
            expected_tool_names=list(expected.get("tool_names") or []),
            message_tool_names=list(message_expected.get("tool_names") or []),
            tool_catalog_manifest_ref=manifest_ref,
            stable_tool_index_segment_id=tool_index.segment_id,
        )
    actual = _provider_tool_schema_fingerprint(tools)
    subset_check = _tool_fingerprint_subset_check(expected, actual)
    if not subset_check["matched"]:
        reason = (
            "provider_tools_do_not_match_tool_catalog_manifest"
            if manifest_payload
            else "provider_tools_do_not_match_tool_index"
        )
        return _native_tool_binding_schema_never_cache(
            reason,
            expected_tool_names=list(expected.get("tool_names") or []),
            actual_tool_names=list(actual.get("tool_names") or []),
            tool_subset_mismatch=list(subset_check.get("mismatches") or []),
            tool_catalog_manifest_ref=manifest_ref,
            stable_tool_index_segment_id=tool_index.segment_id,
        )
    if tool_index.cache_role not in {"cacheable_prefix", "session_stable"}:
        return _native_tool_binding_schema_never_cache(
            "matched_tool_index_is_not_stable",
            stable_tool_index_segment_id=tool_index.segment_id,
        )
    return {
        "kind": "native_tool_binding_schema",
        "source_ref": "model_request.tools",
        "cache_scope": "none",
        "cache_role": "never_cache",
        "prefix_tier": "none",
        "metadata": {
            "native_tool_binding_decision": (
                "current_turn_tool_binding_validated_against_tool_catalog_manifest"
                if manifest_payload
                else "current_turn_tool_binding_validated_against_stable_tool_index"
            ),
            "cache_note": (
                "native_tool_binding_schema_is_current_turn_tool_binding_sidecar; it is provider transport, not message prefix cache"
                if manifest_payload
                else "native_tool_binding_schema_is_current_turn_tool_binding_sidecar"
            ),
            "stability_rule": "native tools sidecar is current-turn tool authorization and is never replayed as context memory",
            "sidecar_semantic_role": "current_turn_tool_binding_sidecar",
            "sidecar_validity_scope": "current_provider_request",
            "provider_payload_transport_location": "tools",
            "provider_payload_sidecar_component": True,
            "provider_payload_prefix_component": False,
            "transport_contract_component": False,
            "transport_contract_role": "current_turn_tool_binding_sidecar",
            "transport_sidecar_role": "current_turn_tool_binding_sidecar",
            "sidecar_drift_status": "matched",
            "native_tool_binding_scope": "current_turn_bound_subset_of_stable_tool_catalog",
            "native_tool_binding_tool_names": list(actual.get("tool_names") or []),
            "native_tool_binding_expected_catalog_tool_count": len(list(expected.get("tool_names") or [])),
            "native_tool_binding_bound_tool_count": len(list(actual.get("tool_names") or [])),
            "message_prefix_cacheable": False,
            "tool_catalog_manifest_ref": manifest_ref,
            "tool_catalog_manifest_hash": str(manifest_payload.get("tool_catalog_hash") or ""),
            "stable_tool_index_segment_id": tool_index.segment_id,
            "stable_tool_index_cache_scope": tool_index.cache_scope,
            "stable_tool_index_cache_role": tool_index.cache_role,
            "stable_tool_index_prefix_tier": tool_index.prefix_tier,
        },
    }


def _native_tool_binding_schema_never_cache(reason: str, **metadata: Any) -> dict[str, Any]:
    return {
        "kind": "native_tool_binding_schema",
        "source_ref": "model_request.tools",
        "cache_scope": "none",
        "cache_role": "never_cache",
        "prefix_tier": "none",
        "metadata": {
            "native_tool_binding_decision": "not_promoted",
            "native_tool_binding_reason": str(reason or "unknown"),
            "cache_note": "native_tool_binding_schema_is_current_turn_tool_binding_sidecar_but_not_message_prefix_cacheable",
            "sidecar_semantic_role": "current_turn_tool_binding_sidecar",
            "sidecar_validity_scope": "current_provider_request",
            "provider_payload_transport_location": "tools",
            "provider_payload_sidecar_component": True,
            "provider_payload_prefix_component": False,
            "transport_contract_component": False,
            "transport_contract_role": "current_turn_tool_binding_sidecar_unvalidated",
            "transport_sidecar_role": "current_turn_tool_binding_sidecar",
            "sidecar_drift_status": _native_tool_sidecar_drift_status(reason),
            "message_prefix_cacheable": False,
            **dict(metadata),
        },
    }


def _native_tool_sidecar_drift_status(reason: str) -> str:
    normalized = str(reason or "").strip()
    if not normalized:
        return "unknown"
    if normalized in {"missing_stable_tool_index", "stable_tool_index_message_missing"}:
        return "missing_catalog"
    if "does_not_match" in normalized or "do_not_match" in normalized:
        return "drifted"
    return "not_validated"


def _parse_context_payload(content: str) -> Any | None:
    text = str(content or "").strip()
    if not text:
        return None
    envelope_payload = parse_context_fragment_payload(text)
    if envelope_payload is not None:
        return envelope_payload
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


def _tool_catalog_manifest_fingerprint(manifest: dict[str, Any]) -> dict[str, Any]:
    available = list(dict(manifest or {}).get("model_visible_catalog") or [])
    return _tool_index_fingerprint({"available_tools": available})


def _provider_tool_schema_fingerprint(tools: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    for tool in tools:
        payload = dict(tool)
        function_payload = payload.get("function") if isinstance(payload.get("function"), dict) else {}
        name = str(payload.get("name") or function_payload.get("name") or "").strip()
        if not name:
            continue
        schema = (
            payload.get("schema")
            or payload.get("input_schema")
            or payload.get("parameters")
            or function_payload.get("parameters")
            or {}
        )
        items.append({"name": name, "input_schema_ref": canonical_provider_schema_ref(schema)})
    ordered = sorted(items, key=lambda item: item["name"])
    return {"tools": ordered, "tool_names": [item["name"] for item in ordered]}


def _tool_fingerprint_subset_check(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_refs = {
        str(item.get("name") or ""): str(item.get("input_schema_ref") or "")
        for item in list(dict(expected or {}).get("tools") or [])
        if isinstance(item, dict) and str(item.get("name") or "")
    }
    mismatches: list[dict[str, str]] = []
    for item in list(dict(actual or {}).get("tools") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        actual_ref = str(item.get("input_schema_ref") or "")
        expected_ref = expected_refs.get(name)
        if not expected_ref:
            mismatches.append({"name": name, "reason": "tool_not_in_stable_catalog", "actual_ref": actual_ref})
        elif expected_ref != actual_ref:
            mismatches.append(
                {
                    "name": name,
                    "reason": "schema_ref_mismatch",
                    "expected_ref": expected_ref,
                    "actual_ref": actual_ref,
                }
            )
    return {"matched": not mismatches, "mismatches": mismatches}


def _cache_boundary(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    transport_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transport = dict(transport_contract or {})
    transport_contract_hash = str(transport.get("contract_hash") or "")
    stable_message_prefix = _contiguous_stable_message_prefix(segments)
    stable_tool_capability_segments = [
        segment
        for segment in segments
        if segment.kind == "tool_index_stable"
        and is_cache_eligible_prefix(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier)
    ]
    tier_prefixes = {
        tier: _tier_prefix_diagnostics(
            segments,
            tier=tier,
            transport_contract_hash=transport_contract_hash,
        )
        for tier in ("provider_global", "session", "task")
    }
    selected_tier, selected_prefix = _selected_tier_prefix(tier_prefixes)
    tool_segments = [segment for segment in segments if segment.transport_location == "tools"]
    request_param_segments = [segment for segment in segments if segment.transport_location == "request_params"]
    tool_option_segments = [segment for segment in segments if segment.transport_location == "tool_call_options"]
    response_format_segments = [segment for segment in segments if segment.transport_location == "response_format"]
    cache_sensitive_segments = [
        *request_param_segments,
        *tool_option_segments,
        *response_format_segments,
    ]
    stable_prefix_segments = _provider_prefix_segments_for_tier(segments, tier=selected_tier)
    cache_spine = _cache_spine_diagnostics(
        segments,
        transport_contract_hash=transport_contract_hash,
    )
    return {
        "selected_prefix_key_tier": selected_tier,
        "provider_payload_prefix_hash": str(selected_prefix.get("provider_payload_prefix_hash") or ""),
        "provider_payload_message_prefix_hash": str(selected_prefix.get("message_prefix_hash") or ""),
        "transport_contract_ref": str(transport.get("contract_id") or ""),
        "transport_contract_hash": transport_contract_hash,
        "stable_transport_contract_hash": transport_contract_hash,
        "transport_contract_component_count": int(transport.get("component_count") or 0),
        "transport_contract_components": list(transport.get("components") or []),
        "selected_boundary_segment_id": str(selected_prefix.get("boundary_segment_id") or ""),
        "stable_segment_count": len(stable_prefix_segments),
        "stable_segment_hash": str(selected_prefix.get("provider_payload_prefix_hash") or ""),
        "stable_message_prefix_hash": _segments_hash(stable_message_prefix),
        "stable_message_prefix_physical_hash": _physical_prefix_hash(
            transport_contract_hash=transport_contract_hash,
            message_prefix_hash=_segments_hash(stable_message_prefix),
        ),
        "stable_message_prefix_segment_count": len(stable_message_prefix),
        "tool_catalog_hash": _segments_hash(tool_segments),
        "stable_tool_catalog_hash": _segments_hash(stable_tool_capability_segments),
        "cache_sensitive_params_hash": _segments_hash(cache_sensitive_segments),
        "provider_params_hash": _segments_hash(request_param_segments),
        "tool_call_options_hash": _segments_hash(tool_option_segments),
        "response_format_hash": _segments_hash(response_format_segments),
        "cache_sensitive_param_segment_count": len(cache_sensitive_segments),
        "tier_prefixes": tier_prefixes,
        "tool_schema_segment_count": sum(1 for segment in segments if segment.transport_location == "tools"),
        "tool_schema_cache_roles": [
            segment.cache_role for segment in segments if segment.transport_location == "tools"
        ],
        "tool_call_options_segment_count": len(tool_option_segments),
        "response_format_segment_count": len(response_format_segments),
        "provider_params_segment_count": len(request_param_segments),
        "cache_spine_hash": str(cache_spine.get("cache_spine_hash") or ""),
        "cache_spine_generation": str(cache_spine.get("cache_spine_generation") or ""),
        "cache_spine_segment_count": int(cache_spine.get("cache_spine_segment_count") or 0),
        "cache_spine_lane_counts": dict(cache_spine.get("cache_spine_lane_counts") or {}),
        "cache_spine_lane_order": list(cache_spine.get("cache_spine_lane_order") or []),
        "stable_after_tail_violations": list(cache_spine.get("stable_after_tail_violations") or []),
        "stable_after_tail_violation_count": int(cache_spine.get("stable_after_tail_violation_count") or 0),
        "authority": "runtime.model_gateway.provider_payload.cache_boundary",
    }


def _contiguous_stable_message_prefix(segments: tuple[ProviderPayloadSegment, ...]) -> list[ProviderPayloadSegment]:
    return _provider_visible_structural_prefix_segments(segments)


def _cache_spine_diagnostics(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    transport_contract_hash: str,
) -> dict[str, Any]:
    spine_lanes = {
        "global_static_prefix",
        "provider_visible_context_prefix",
    }
    tail_lanes = {"current_turn_tail", "never_replay_tail"}
    message_segments = [
        segment
        for segment in sorted(tuple(segments or ()), key=lambda item: int(item.ordinal or 0))
        if segment.transport_location == "messages"
    ]
    spine_segments: list[ProviderPayloadSegment] = []
    lane_counts: dict[str, int] = {}
    lane_order: list[str] = []
    violations: list[dict[str, Any]] = []
    tail_seen = False
    generation = ""
    for segment in message_segments:
        metadata = dict(segment.metadata or {})
        lane = str(metadata.get("physical_prefix_lane") or "").strip()
        if not lane:
            violations.append(
                {
                    "segment_id": segment.segment_id,
                    "kind": segment.kind,
                    "source_ref": segment.source_ref,
                    "ordinal": int(segment.ordinal or 0),
                    "reason": "missing_physical_prefix_lane",
                }
            )
            lane = "current_turn_tail"
        if not generation:
            generation = str(metadata.get("cache_spine_generation") or metadata.get("compaction_generation") or "")
        if lane:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
            if lane not in lane_order:
                lane_order.append(lane)
        if lane in tail_lanes:
            tail_seen = True
            continue
        if lane in spine_lanes:
            if tail_seen:
                violations.append(
                    {
                        "segment_id": segment.segment_id,
                        "kind": segment.kind,
                        "source_ref": segment.source_ref,
                        "lane": lane,
                        "ordinal": int(segment.ordinal or 0),
                        "reason": "cache_spine_segment_after_current_turn_tail",
                    }
                )
            spine_segments.append(segment)
    spine_hash = _physical_prefix_hash(
        transport_contract_hash=transport_contract_hash,
        message_prefix_hash=_segments_hash(spine_segments),
    ) if spine_segments or transport_contract_hash else ""
    return {
        "cache_spine_hash": spine_hash,
        "cache_spine_generation": generation or "0",
        "cache_spine_segment_count": len(spine_segments),
        "cache_spine_lane_counts": lane_counts,
        "cache_spine_lane_order": lane_order,
        "stable_after_tail_violations": violations,
        "stable_after_tail_violation_count": len(violations),
    }


def _contiguous_message_prefix_for_tier(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    tier: str,
) -> list[ProviderPayloadSegment]:
    result: list[ProviderPayloadSegment] = []
    for segment in [item for item in segments if item.transport_location == "messages"]:
        if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier, tier=tier):
            result.append(segment)
            continue
        break
    return result


def _tool_prefix_for_tier(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    tier: str,
) -> list[ProviderPayloadSegment]:
    return [
        segment
        for segment in segments
        if segment.transport_location == "tools"
        and is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier, tier=tier)
    ]


def _provider_prefix_segments_for_tier(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    tier: str,
) -> list[ProviderPayloadSegment]:
    if not tier or tier == "none":
        return []
    if str(tier or "").strip() == "task":
        return _provider_visible_structural_prefix_segments(segments)
    result: list[ProviderPayloadSegment] = []
    for segment in sorted(segments, key=lambda item: item.ordinal):
        if segment.transport_location != "messages":
            if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier, tier=tier):
                result.append(segment)
            continue
        if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier, tier=tier):
            result.append(segment)
            continue
        break
    return result


def _provider_visible_structural_prefix_segments(
    segments: tuple[ProviderPayloadSegment, ...],
) -> list[ProviderPayloadSegment]:
    result: list[ProviderPayloadSegment] = []
    for segment in sorted(tuple(segments or ()), key=lambda item: item.ordinal):
        if segment.transport_location != "messages":
            continue
        if _is_provider_visible_structural_prefix_segment(segment):
            result.append(segment)
            continue
        break
    return result


def _is_provider_visible_structural_prefix_segment(segment: ProviderPayloadSegment) -> bool:
    metadata = dict(segment.metadata or {})
    lane = str(metadata.get("physical_prefix_lane") or "").strip()
    if not lane:
        return False
    return lane in {
        "global_static_prefix",
        "provider_visible_context_prefix",
    }


def _tier_prefix_diagnostics(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    tier: str,
    transport_contract_hash: str = "",
) -> dict[str, Any]:
    prefix_segments = _provider_prefix_segments_for_tier(segments, tier=tier)
    message_segments = [segment for segment in prefix_segments if segment.transport_location == "messages"]
    tool_segments = [segment for segment in prefix_segments if segment.transport_location == "tools"]
    boundary = prefix_segments[-1] if prefix_segments else None
    message_prefix_hash = _segments_hash(prefix_segments)
    return {
        "provider_payload_prefix_hash": _physical_prefix_hash(
            transport_contract_hash=transport_contract_hash,
            message_prefix_hash=message_prefix_hash,
        ),
        "provider_payload_message_prefix_hash": message_prefix_hash,
        "transport_contract_hash": str(transport_contract_hash or ""),
        "message_prefix_hash": _segments_hash(message_segments),
        "tool_prefix_hash": _segments_hash(tool_segments),
        "segment_count": len(prefix_segments),
        "message_segment_count": len(message_segments),
        "tool_segment_count": len(tool_segments),
        "segment_ids": [segment.segment_id for segment in prefix_segments],
        "kinds": [segment.kind for segment in prefix_segments],
        "boundary_segment_id": boundary.segment_id if boundary is not None else "",
        "boundary_kind": boundary.kind if boundary is not None else "",
        "boundary_ordinal": boundary.ordinal if boundary is not None else 0,
        "boundary_content_hash": boundary.content_hash if boundary is not None else "",
        "provider_visible_boundary_source": "context_structure" if str(tier or "").strip() == "task" else "prefix_tier",
        "provider_visible_boundaries": [
            str(dict(segment.metadata or {}).get("context_provider_visible_boundary") or "")
            for segment in message_segments
        ],
    }


def _selected_tier_prefix(tier_prefixes: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    for tier in ("task", "session", "provider_global"):
        payload = dict(tier_prefixes.get(tier) or {})
        if payload.get("provider_payload_prefix_hash"):
            return tier, payload
    return "none", {}


def _ordered_provider_payload_segments(
    *,
    request_id: str,
    segments: list[ProviderPayloadSegment],
) -> tuple[ProviderPayloadSegment, ...]:
    ordered = sorted(list(segments or []), key=_provider_payload_physical_sort_key)
    return tuple(
        _with_provider_payload_ordinal(
            request_id=request_id,
            segment=segment,
            ordinal=index + 1,
        )
        for index, segment in enumerate(ordered)
    )


def _provider_payload_physical_sort_key(segment: ProviderPayloadSegment) -> tuple[int, int]:
    location = str(segment.transport_location or "")
    if location in {"tools", "tool_call_options", "response_format", "request_params"}:
        return (0, int(segment.ordinal or 0))
    if location == "messages":
        return (1, int(segment.ordinal or 0))
    return (2, int(segment.ordinal or 0))


def _with_provider_payload_ordinal(
    *,
    request_id: str,
    segment: ProviderPayloadSegment,
    ordinal: int,
) -> ProviderPayloadSegment:
    if int(segment.ordinal or 0) == int(ordinal or 0):
        return segment
    digest = str(segment.content_hash or "").split(":", 1)[-1][:12]
    return replace(
        segment,
        ordinal=int(ordinal or 0),
        segment_id=f"ppseg:{request_id}:{int(ordinal or 0)}:{segment.kind}:{digest}",
    )


def _segments_hash(segments: list[ProviderPayloadSegment]) -> str:
    if not segments:
        return ""
    return _stable_text_hash("|".join(segment.content_hash for segment in segments))


def _context_cache_section_counts(segments: tuple[ProviderPayloadSegment, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for segment in tuple(segments or ()):
        if segment.transport_location != "messages":
            continue
        metadata = dict(segment.metadata or {})
        section = str(metadata.get("context_cache_section") or "unknown")
        counts[section] = counts.get(section, 0) + 1
    return counts


def _cache_spine_segment_after_tail_count(segments: tuple[ProviderPayloadSegment, ...]) -> int:
    tail_seen = False
    count = 0
    for segment in [item for item in tuple(segments or ()) if item.transport_location == "messages"]:
        metadata = dict(segment.metadata or {})
        lane = str(metadata.get("physical_prefix_lane") or "").strip()
        if lane in {"current_turn_tail", "never_replay_tail"}:
            tail_seen = True
            continue
        if tail_seen and lane in {"global_static_prefix", "provider_visible_context_prefix"}:
            count += 1
    return count


def _transport_stable_contract(
    *,
    provider: str,
    model: str,
    segments: tuple[ProviderPayloadSegment, ...],
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for segment in sorted(tuple(segments or ()), key=lambda item: item.ordinal):
        if segment.transport_location == "messages":
            continue
        metadata = dict(segment.metadata or {})
        if metadata.get("transport_contract_component") is False:
            continue
        components.append(
            {
                "kind": segment.kind,
                "transport_location": segment.transport_location,
                "source_ref": segment.source_ref,
                "content_hash": segment.content_hash,
                "byte_length": int(segment.byte_length or 0),
                "cache_role": segment.cache_role,
                "prefix_tier": segment.prefix_tier,
                "transport_contract_component": bool(
                    metadata.get("transport_contract_component") is not False
                ),
                "transport_contract_role": str(
                    metadata.get("transport_contract_role")
                    or _transport_contract_role(segment)
                ),
                "sidecar_drift_status": str(metadata.get("sidecar_drift_status") or ""),
            }
        )
    seed = {
        "provider": str(provider or ""),
        "model": str(model or ""),
        "components": components,
    }
    contract_hash = _stable_text_hash(canonical_json(seed))
    return {
        "contract_id": "transportcontract:" + contract_hash.removeprefix("sha256:")[:16],
        "contract_hash": contract_hash,
        "provider": str(provider or ""),
        "model": str(model or ""),
        "component_count": len(components),
        "components": components,
        "tool_schema_hash": _segments_hash([segment for segment in segments if segment.transport_location == "tools"]),
        "cache_sensitive_params_hash": _segments_hash(
            [
                segment
                for segment in segments
                if segment.transport_location in {"request_params", "tool_call_options", "response_format"}
            ]
        ),
        "authority": "runtime.model_gateway.provider_payload.transport_stable_contract",
    }


def _transport_contract_role(segment: ProviderPayloadSegment) -> str:
    location = str(segment.transport_location or "")
    if location == "tools":
        return "stable_provider_tool_schema"
    if location == "tool_call_options":
        return "stable_tool_binding_options"
    if location == "response_format":
        return "stable_response_format"
    if location == "request_params":
        return "stable_provider_params"
    return "stable_transport_component"


def _physical_prefix_hash(*, transport_contract_hash: str, message_prefix_hash: str) -> str:
    message_hash = str(message_prefix_hash or "")
    if not message_hash:
        return ""
    return _stable_text_hash(
        canonical_json(
            {
                "transport_contract_hash": str(transport_contract_hash or ""),
                "message_prefix_hash": message_hash,
            }
        )
    )


def _segment_id(request_id: str, ordinal: int, kind: Any, payload: str) -> str:
    return f"ppseg:{request_id}:{ordinal}:{str(kind or 'segment')}:{_stable_text_hash(payload).split(':', 1)[-1][:12]}"


def _stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in ("", None, [], {})}


def _dict_param(value: Any) -> dict[str, Any]:
    return _drop_empty(dict(value or {})) if isinstance(value, dict) else {}


def _response_format_param(params: dict[str, Any]) -> Any:
    if "response_format" in params:
        return params.pop("response_format")
    if "structured_output_schema" in params:
        return params.pop("structured_output_schema")
    if "output_schema" in params:
        return params.pop("output_schema")
    return None

