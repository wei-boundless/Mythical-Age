from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from harness.runtime.control_action_schema import CONTROL_ACTION_TOOL_NAMES
from harness.runtime.tool_schema_identity import provider_input_schema_ref
from prompt_composition.context_envelope import parse_context_fragment_payload
from runtime.prompt_accounting.cache_policy import (
    is_cache_eligible_prefix,
    normalize_cache_role,
    normalize_compression_role,
    normalize_prefix_tier,
)
from runtime.prompt_accounting.serializer import canonical_json


_PREFIX_CONSUMER_CONTRACTS = (
    "runtime.prompt_accounting.serializer",
    "runtime.prompt_accounting.cache_planner",
    "runtime.prompt_accounting.cache_baseline",
    "runtime.prompt_accounting.cache_break_detector",
    "runtime.prompt_accounting.provider_cache_ledger",
)
_SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES = (
    "runtime.prompt_accounting.serializer.reclassify_prefix_family",
    "runtime.prompt_accounting.cache_planner.reclassify_prefix_family",
    "runtime.prompt_accounting.provider_cache_ledger.reclassify_prefix_family",
    "runtime.prompt_accounting.cache_break_detector.reclassify_prefix_family",
    "frontend.presentation.reclassify_prefix_family",
)
_NON_TOKEN_CONSUMER_CONTRACTS = (
    "runtime.model_gateway.provider_payload.transport_stable_contract",
    "runtime.prompt_accounting.cache_planner",
    "runtime.prompt_accounting.cache_break_detector",
)


@dataclass(frozen=True, slots=True)
class ProviderPayloadSegment:
    segment_id: str
    kind: str
    transport_location: str
    ordinal: int
    role: str = ""
    source_ref: str = ""
    content_hash: str = ""
    byte_length: int = 0
    cache_scope: str = "none"
    cache_role: str = "volatile"
    prefix_tier: str = "volatile"
    compression_role: str = "summarize"
    prefix_family: str = ""
    semantic_source: str = ""
    logical_segment_ref: str = ""
    semantic_slot: str = ""
    physical_prefix_lane: str = ""
    boundary_participation: str = "excluded"
    exclusion_reason: str = ""
    consumer_contracts: tuple[str, ...] = ()
    forbidden_authorities: tuple[str, ...] = ()
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
        payload_hash = _stable_text_hash(payload)
        metadata = {**dict(getattr(binding, "metadata", {}) or {}), "message_index": message_index}
        source_ref = str(getattr(binding, "source_ref", "") or "model_request.message")
        identity = _message_structural_identity(
            kind=str(getattr(binding, "kind", "") or "message"),
            metadata=metadata,
            content_hash=payload_hash,
        )
        segments.append(
            ProviderPayloadSegment(
                segment_id=str(getattr(binding, "planned_segment_id", "") or _segment_id(request_id, ordinal, getattr(binding, "kind", "message"), payload)),
                kind=str(getattr(binding, "kind", "") or "message"),
                transport_location="messages",
                ordinal=ordinal,
                role=str(getattr(binding, "model_message_role", "") or message.get("role") or ""),
                source_ref=source_ref,
                content_hash=payload_hash,
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope=str(getattr(binding, "cache_scope", "") or "none"),
                cache_role=normalize_cache_role(getattr(binding, "cache_role", "")),
                prefix_tier=normalize_prefix_tier(
                    getattr(binding, "prefix_tier", ""),
                    cache_scope=str(getattr(binding, "cache_scope", "") or "none"),
                    cache_role=normalize_cache_role(getattr(binding, "cache_role", "")),
                ),
                compression_role=normalize_compression_role(getattr(binding, "compression_role", "")),
                prefix_family=str(identity.get("prefix_family") or ""),
                semantic_source=str(identity.get("semantic_source") or ""),
                logical_segment_ref=str(identity.get("logical_segment_ref") or ""),
                semantic_slot=str(identity.get("semantic_slot") or ""),
                physical_prefix_lane=str(identity.get("physical_prefix_lane") or ""),
                boundary_participation=str(identity.get("boundary_participation") or "excluded"),
                exclusion_reason=str(identity.get("exclusion_reason") or ""),
                consumer_contracts=_tuple_text(identity.get("consumer_contracts")),
                forbidden_authorities=_tuple_text(identity.get("forbidden_authorities")),
                metadata=metadata,
            )
        )
    for message_index, message in enumerate(messages):
        if message_index in covered_message_indexes:
            continue
        ordinal += 1
        payload = canonical_json(dict(message))
        payload_hash = _stable_text_hash(payload)
        metadata = {"message_index": message_index, "planned": False}
        identity = _message_structural_identity(
            kind="unplanned_message",
            metadata=metadata,
            content_hash=payload_hash,
        )
        segments.append(
            ProviderPayloadSegment(
                segment_id=_segment_id(request_id, ordinal, "unplanned_message", payload),
                kind="unplanned_message",
                transport_location="messages",
                ordinal=ordinal,
                role=str(dict(message).get("role") or ""),
                source_ref="model_request.unplanned_message",
                content_hash=payload_hash,
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="summarize",
                prefix_family=str(identity.get("prefix_family") or ""),
                semantic_source=str(identity.get("semantic_source") or ""),
                logical_segment_ref=str(identity.get("logical_segment_ref") or ""),
                semantic_slot=str(identity.get("semantic_slot") or ""),
                physical_prefix_lane=str(identity.get("physical_prefix_lane") or ""),
                boundary_participation=str(identity.get("boundary_participation") or "excluded"),
                exclusion_reason=str(identity.get("exclusion_reason") or ""),
                consumer_contracts=_tuple_text(identity.get("consumer_contracts")),
                forbidden_authorities=_tuple_text(identity.get("forbidden_authorities")),
                metadata=metadata,
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
                role="tool_schema",
                source_ref=str(profile.get("source_ref") or "model_request.tools"),
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope=str(profile.get("cache_scope") or "none"),
                cache_role=str(profile.get("cache_role") or "never_cache"),
                prefix_tier=str(profile.get("prefix_tier") or "none"),
                compression_role="preserve",
                prefix_family=str(profile.get("prefix_family") or ""),
                semantic_source=str(profile.get("semantic_source") or ""),
                logical_segment_ref=str(profile.get("logical_segment_ref") or ""),
                semantic_slot=str(profile.get("semantic_slot") or ""),
                physical_prefix_lane=str(profile.get("physical_prefix_lane") or ""),
                boundary_participation=str(profile.get("boundary_participation") or "excluded"),
                exclusion_reason=str(profile.get("exclusion_reason") or ""),
                consumer_contracts=_tuple_text(profile.get("consumer_contracts")),
                forbidden_authorities=_tuple_text(profile.get("forbidden_authorities")),
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
                role="transport_contract",
                source_ref="model_request.tool_call_options",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                prefix_family="transport_contract_family_selector",
                semantic_source="model_request.tool_call_options",
                logical_segment_ref="tool_call_options",
                semantic_slot="tool_call_options",
                physical_prefix_lane="",
                boundary_participation="non_token_family_selector",
                exclusion_reason="non_token_transport_contract",
                consumer_contracts=_NON_TOKEN_CONSUMER_CONTRACTS,
                forbidden_authorities=_SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
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
                role="transport_contract",
                source_ref="model_request.response_format",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                prefix_family="transport_contract_family_selector",
                semantic_source="model_request.response_format",
                logical_segment_ref="response_format",
                semantic_slot="response_format",
                physical_prefix_lane="",
                boundary_participation="non_token_family_selector",
                exclusion_reason="non_token_transport_contract",
                consumer_contracts=_NON_TOKEN_CONSUMER_CONTRACTS,
                forbidden_authorities=_SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
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
                role="transport_contract",
                source_ref="model_request.cache_relevant_params",
                content_hash=_stable_text_hash(payload),
                byte_length=len(payload.encode("utf-8", errors="ignore")),
                cache_scope="none",
                cache_role="never_cache",
                prefix_tier="none",
                compression_role="preserve",
                prefix_family="transport_contract_family_selector",
                semantic_source="model_request.cache_relevant_params",
                logical_segment_ref="provider_params",
                semantic_slot="provider_params",
                physical_prefix_lane="",
                boundary_participation="non_token_family_selector",
                exclusion_reason="non_token_transport_contract",
                consumer_contracts=_NON_TOKEN_CONSUMER_CONTRACTS,
                forbidden_authorities=_SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
                metadata={"key_only": True, "param_keys": sorted(str(key) for key in params)},
            )
        )
    ordered_segments = _ordered_provider_payload_segments(
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
                "transport_location": segment.transport_location,
                "role": segment.role,
                "content_hash": segment.content_hash,
                "physical_prefix_lane": segment.physical_prefix_lane,
                "boundary_participation": segment.boundary_participation,
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
            "physical_cache_spine_segment_after_tail_count": _physical_cache_spine_segment_after_tail_count(ordered_segments),
            "physical_cache_spine_contiguous_before_tail": _physical_cache_spine_segment_after_tail_count(ordered_segments) == 0,
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
    stable_tool_index_ref = _tool_schema_logical_segment_ref(
        manifest_payload=manifest_payload,
        expected=expected,
    )
    if manifest_payload and message_expected.get("tools") and message_expected != expected:
        return _native_tool_binding_schema_never_cache(
            "stable_tool_index_does_not_match_tool_catalog_manifest",
            expected_tool_names=list(expected.get("tool_names") or []),
            message_tool_names=list(message_expected.get("tool_names") or []),
            tool_catalog_manifest_ref=manifest_ref,
            stable_tool_index_segment_id=tool_index.segment_id,
            stable_tool_index_ref=stable_tool_index_ref,
        )
    actual = _provider_tool_schema_fingerprint(tools)
    stable_validation = _provider_tool_schema_matches_stable_catalog(
        expected=expected,
        actual=actual,
    )
    if not stable_validation.get("matched"):
        reason = (
            "provider_tools_do_not_match_tool_catalog_manifest"
            if manifest_payload
            else "provider_tools_do_not_match_tool_index"
        )
        return _native_tool_binding_schema_never_cache(
            reason,
            expected_tool_names=list(expected.get("tool_names") or []),
            actual_tool_names=list(actual.get("tool_names") or []),
            schema_mismatch_tool_names=list(stable_validation.get("schema_mismatch_tool_names") or []),
            unexpected_provider_tool_names=list(stable_validation.get("unexpected_provider_tool_names") or []),
            tool_catalog_manifest_ref=manifest_ref,
            stable_tool_index_segment_id=tool_index.segment_id,
            stable_tool_index_ref=stable_tool_index_ref,
        )
    if not is_cache_eligible_prefix(cache_role=tool_index.cache_role, prefix_tier=tool_index.prefix_tier):
        return _native_tool_binding_schema_never_cache(
            "matched_tool_index_is_not_prefix_eligible",
            stable_tool_index_segment_id=tool_index.segment_id,
            stable_tool_index_ref=stable_tool_index_ref,
        )
    decision = "validated_against_tool_catalog_manifest" if manifest_payload else "validated_against_stable_tool_index"
    cache_note = (
        "native_tool_binding_schema_is_provider_physical_prefix_cacheable_after_tool_catalog_manifest_validation"
        if manifest_payload
        else "native_tool_binding_schema_is_provider_physical_prefix_cacheable_after_stable_tool_index_validation"
    )
    metadata: dict[str, Any] = {
        "native_tool_binding_decision": decision,
        "cache_note": cache_note,
        "stability_rule": "native tools payload is a provider physical prefix only while its schema fingerprint matches the stable tool catalog",
        "provider_payload_transport_location": "tools",
        "provider_payload_sidecar_component": False,
        "provider_payload_prefix_component": True,
        "transport_contract_component": False,
        "transport_contract_role": "stable_provider_tool_schema",
        "transport_sidecar_role": "native_tool_binding_schema",
        "tool_schema_blocker_drift_status": "matched",
        "sidecar_drift_status": "matched",
        "physical_prefix_blocker": False,
        "schema_ref_validation": "provider_tool_schema_refs_match_stable_catalog_for_bound_tools",
        "stable_tool_names_bound": list(stable_validation.get("stable_tool_names_bound") or []),
        "provider_control_tool_names": list(stable_validation.get("provider_control_tool_names") or []),
        "message_prefix_cacheable": False,
        "tool_catalog_manifest_ref": manifest_ref,
        "tool_catalog_manifest_hash": str(manifest_payload.get("tool_catalog_hash") or ""),
        "stable_tool_index_segment_id": tool_index.segment_id,
        "stable_tool_index_ref": stable_tool_index_ref,
        "stable_tool_index_cache_scope": tool_index.cache_scope,
        "stable_tool_index_cache_role": tool_index.cache_role,
        "stable_tool_index_prefix_tier": tool_index.prefix_tier,
        "physical_prefix_lane": "provider_tool_schema_prefix",
        "physical_prefix_cacheable": True,
    }
    return {
        "kind": "native_tool_binding_schema",
        "source_ref": "model_request.tools",
        "cache_scope": str(tool_index.cache_scope or "session"),
        "cache_role": str(tool_index.cache_role or "session_stable"),
        "prefix_tier": str(tool_index.prefix_tier or "session"),
        "prefix_family": "provider_physical_tool_schema_prefix",
        "semantic_source": "runtime.tool_catalog_manifest" if manifest_payload else "runtime.stable_tool_index",
        "logical_segment_ref": stable_tool_index_ref,
        "semantic_slot": "tool_index",
        "physical_prefix_lane": "provider_tool_schema_prefix",
        "boundary_participation": "included",
        "exclusion_reason": "",
        "consumer_contracts": _PREFIX_CONSUMER_CONTRACTS,
        "forbidden_authorities": _SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
        "metadata": metadata,
    }

def _native_tool_binding_schema_never_cache(reason: str, **metadata: Any) -> dict[str, Any]:
    normalized_reason = str(reason or "unknown")
    return {
        "kind": "native_tool_binding_schema",
        "source_ref": "model_request.tools",
        "cache_scope": "none",
        "cache_role": "never_cache",
        "prefix_tier": "none",
        "prefix_family": "provider_tool_schema_blocker",
        "semantic_source": str(metadata.get("tool_catalog_manifest_ref") or "runtime.provider_tool_schema_validation"),
        "logical_segment_ref": str(metadata.get("stable_tool_index_ref") or ""),
        "semantic_slot": "tool_index",
        "physical_prefix_lane": "provider_tool_schema_blocker",
        "boundary_participation": "blocker",
        "exclusion_reason": normalized_reason,
        "consumer_contracts": _PREFIX_CONSUMER_CONTRACTS,
        "forbidden_authorities": _SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
        "metadata": {
            "native_tool_binding_decision": "not_promoted",
            "native_tool_binding_reason": normalized_reason,
            "cache_note": "native_tool_binding_schema_blocks_provider_physical_prefix_until_it_matches_the_stable_tool_catalog",
            "provider_payload_transport_location": "tools",
            "provider_payload_sidecar_component": False,
            "provider_payload_prefix_component": False,
            "transport_contract_component": False,
            "transport_contract_role": "stable_provider_tool_schema_unvalidated",
            "transport_sidecar_role": "native_tool_binding_schema",
            "tool_schema_blocker_drift_status": _native_tool_blocker_drift_status(reason),
            "sidecar_drift_status": _native_tool_blocker_drift_status(reason),
            "message_prefix_cacheable": False,
            "physical_prefix_blocker": True,
            "physical_prefix_lane": "provider_tool_schema_blocker",
            **dict(metadata),
        },
    }


def _native_tool_blocker_drift_status(reason: str) -> str:
    normalized = str(reason or "").strip()
    if not normalized:
        return "unknown"
    if normalized in {"missing_stable_tool_index", "stable_tool_index_message_missing"}:
        return "missing_catalog"
    if "does_not_match" in normalized or "do_not_match" in normalized:
        return "drifted"
    return "not_validated"


def _message_structural_identity(
    *,
    kind: str,
    metadata: dict[str, Any],
    content_hash: str = "",
) -> dict[str, Any]:
    payload = dict(metadata or {})
    lane = str(payload.get("physical_prefix_lane") or "").strip()
    included = lane in {"global_static_prefix", "provider_visible_context_prefix"}
    semantic_source = _first_text(
        payload.get("context_semantic_source"),
        payload.get("semantic_source"),
        payload.get("source_kind"),
        payload.get("context_source_kind"),
        payload.get("content_source"),
        payload.get("runtime_fragment_role"),
        kind,
    )
    semantic_slot = _first_text(
        payload.get("context_semantic_slot"),
        payload.get("semantic_slot"),
        payload.get("slot"),
        kind,
    )
    return {
        "prefix_family": _message_prefix_family(lane),
        "semantic_source": semantic_source,
        "logical_segment_ref": _stable_logical_segment_ref(
            kind=kind,
            semantic_source=semantic_source,
            semantic_slot=semantic_slot,
            content_hash=content_hash,
        ),
        "semantic_slot": semantic_slot,
        "physical_prefix_lane": lane,
        "boundary_participation": "included" if included else "excluded",
        "exclusion_reason": "" if included else _message_exclusion_reason(lane),
        "consumer_contracts": _PREFIX_CONSUMER_CONTRACTS,
        "forbidden_authorities": _SEGMENT_IDENTITY_FORBIDDEN_AUTHORITIES,
    }


def _message_prefix_family(lane: str) -> str:
    if lane == "global_static_prefix":
        return "provider_global_static_prefix"
    if lane == "provider_visible_context_prefix":
        return "provider_visible_context_prefix"
    return "dynamic_tail"


def _message_exclusion_reason(lane: str) -> str:
    normalized = str(lane or "").strip()
    if normalized in {"current_turn_tail", "never_replay_tail"}:
        return normalized
    if normalized:
        return f"non_cache_spine_lane:{normalized}"
    return "no_physical_prefix_lane"


def _tuple_text(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in list(value or []) if str(item or ""))


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_logical_segment_ref(
    *,
    kind: str,
    semantic_source: str,
    semantic_slot: str,
    content_hash: str,
) -> str:
    seed = {
        "kind": str(kind or ""),
        "semantic_source": str(semantic_source or ""),
        "semantic_slot": str(semantic_slot or ""),
        "content_hash": str(content_hash or ""),
    }
    digest = _stable_text_hash(canonical_json(seed)).removeprefix("sha256:")[:16]
    return f"logical:{str(kind or 'segment')}:{digest}"


def _tool_schema_logical_segment_ref(
    *,
    manifest_payload: dict[str, Any],
    expected: dict[str, Any],
) -> str:
    stable_catalog_hash = _first_text(
        dict(manifest_payload or {}).get("stable_tool_catalog_hash"),
        dict(manifest_payload or {}).get("tool_catalog_hash"),
    )
    if stable_catalog_hash:
        return "tool_catalog:" + str(stable_catalog_hash).removeprefix("sha256:")[:16]
    expected_hash = _stable_text_hash(canonical_json(dict(expected or {}))).removeprefix("sha256:")[:16]
    return f"tool_index:{expected_hash}"


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
        items.append({"name": name, "input_schema_ref": provider_input_schema_ref(schema)})
    ordered = sorted(items, key=lambda item: item["name"])
    return {"tools": ordered, "tool_names": [item["name"] for item in ordered]}


_PROVIDER_CONTROL_TOOL_NAMES = frozenset(str(item) for item in CONTROL_ACTION_TOOL_NAMES)


def _provider_tool_schema_matches_stable_catalog(
    *,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    expected_by_name = _tool_refs_by_name(expected)
    actual_by_name = _tool_refs_by_name(actual)
    expected_names = set(expected_by_name)
    actual_names = set(actual_by_name)
    stable_bound_names = sorted(actual_names.intersection(expected_names))
    schema_mismatches = sorted(
        name
        for name in stable_bound_names
        if str(actual_by_name.get(name) or "") != str(expected_by_name.get(name) or "")
    )
    provider_control_names = sorted(actual_names.intersection(_PROVIDER_CONTROL_TOOL_NAMES))
    unexpected_names = sorted(actual_names - expected_names - _PROVIDER_CONTROL_TOOL_NAMES)
    return {
        "matched": not schema_mismatches and not unexpected_names,
        "stable_tool_names_bound": stable_bound_names,
        "provider_control_tool_names": provider_control_names,
        "schema_mismatch_tool_names": schema_mismatches,
        "unexpected_provider_tool_names": unexpected_names,
    }


def _tool_refs_by_name(fingerprint: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in list(dict(fingerprint or {}).get("tools") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result[name] = str(item.get("input_schema_ref") or "").strip()
    return result


def _cache_boundary(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    transport_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transport = dict(transport_contract or {})
    transport_contract_hash = str(transport.get("contract_hash") or "")
    physical_cache_spine = _physical_cache_spine_prefix_diagnostics(
        segments,
        transport_contract_hash=transport_contract_hash,
    )
    physical_prefix_hash = str(physical_cache_spine.get("provider_payload_prefix_hash") or "")
    physical_message_hash = str(physical_cache_spine.get("physical_cache_spine_message_subtotal_hash") or "")
    stable_tool_capability_segments = [
        segment
        for segment in segments
        if segment.kind == "tool_index_stable"
        and is_cache_eligible_prefix(cache_role=segment.cache_role, prefix_tier=segment.prefix_tier)
    ]
    selected_tier = "physical_cache_spine" if physical_prefix_hash else "none"
    tool_segments = [segment for segment in segments if segment.transport_location == "tools"]
    request_param_segments = [segment for segment in segments if segment.transport_location == "request_params"]
    tool_option_segments = [segment for segment in segments if segment.transport_location == "tool_call_options"]
    response_format_segments = [segment for segment in segments if segment.transport_location == "response_format"]
    cache_sensitive_segments = [
        *request_param_segments,
        *tool_option_segments,
        *response_format_segments,
    ]
    return {
        "selected_prefix_key_tier": selected_tier,
        "provider_payload_prefix_hash": physical_prefix_hash,
        "physical_cache_spine_message_subtotal_hash": physical_message_hash,
        "transport_contract_ref": str(transport.get("contract_id") or ""),
        "transport_contract_hash": transport_contract_hash,
        "transport_contract_component_count": int(transport.get("component_count") or 0),
        "transport_contract_components": list(transport.get("components") or []),
        "selected_boundary_segment_id": str(physical_cache_spine.get("boundary_segment_id") or ""),
        "physical_cache_spine": physical_cache_spine,
        "physical_cache_spine_hash": physical_prefix_hash,
        "physical_cache_spine_segment_count": int(physical_cache_spine.get("segment_count") or 0),
        "physical_cache_spine_message_segment_count": int(physical_cache_spine.get("message_segment_count") or 0),
        "physical_cache_spine_tool_segment_count": int(physical_cache_spine.get("tool_segment_count") or 0),
        "physical_cache_spine_segment_ids": list(physical_cache_spine.get("segment_ids") or []),
        "physical_cache_spine_segments": list(physical_cache_spine.get("segments") or []),
        "physical_cache_spine_prefix_families": list(physical_cache_spine.get("prefix_families") or []),
        "physical_cache_spine_boundary_participations": list(physical_cache_spine.get("boundary_participations") or []),
        "physical_cache_spine_blockers": list(physical_cache_spine.get("blockers") or []),
        "physical_cache_spine_first_blocker": dict(physical_cache_spine.get("first_blocker") or {}),
        "physical_cache_spine_boundary_segment_id": str(physical_cache_spine.get("boundary_segment_id") or ""),
        "physical_cache_spine_boundary_kind": str(physical_cache_spine.get("boundary_kind") or ""),
        "physical_cache_spine_boundary_ordinal": int(physical_cache_spine.get("boundary_ordinal") or 0),
        "physical_cache_spine_boundary_content_hash": str(physical_cache_spine.get("boundary_content_hash") or ""),
        "physical_cache_spine_lane_counts": dict(physical_cache_spine.get("lane_counts") or {}),
        "physical_cache_spine_lane_order": list(physical_cache_spine.get("lane_order") or []),
        "physical_cache_spine_tool_protocol_round_count": int(physical_cache_spine.get("provider_tool_protocol_round_count") or 0),
        "physical_cache_spine_tool_protocol_rounds": list(physical_cache_spine.get("provider_tool_protocol_rounds") or []),
        "physical_cache_spine_tool_protocol_round_ids": [
            str(item.get("round_id") or "")
            for item in list(physical_cache_spine.get("provider_tool_protocol_rounds") or [])
            if isinstance(item, dict) and str(item.get("round_id") or "")
        ],
        "physical_cache_spine_authority": str(physical_cache_spine.get("authority") or ""),
        "tool_catalog_hash": _segments_hash(tool_segments),
        "stable_tool_catalog_hash": _segments_hash(stable_tool_capability_segments),
        "cache_sensitive_params_hash": _segments_hash(cache_sensitive_segments),
        "provider_params_hash": _segments_hash(request_param_segments),
        "tool_call_options_hash": _segments_hash(tool_option_segments),
        "response_format_hash": _segments_hash(response_format_segments),
        "cache_sensitive_param_segment_count": len(cache_sensitive_segments),
        "tool_schema_segment_count": sum(1 for segment in segments if segment.transport_location == "tools"),
        "tool_schema_cache_roles": [
            segment.cache_role for segment in segments if segment.transport_location == "tools"
        ],
        "tool_call_options_segment_count": len(tool_option_segments),
        "response_format_segment_count": len(response_format_segments),
        "provider_params_segment_count": len(request_param_segments),
        "authority": "runtime.model_gateway.provider_payload.cache_boundary",
    }


def _physical_cache_spine_segments(
    segments: tuple[ProviderPayloadSegment, ...],
) -> list[ProviderPayloadSegment]:
    result: list[ProviderPayloadSegment] = []
    for segment in sorted(tuple(segments or ()), key=lambda item: item.ordinal):
        participation = str(segment.boundary_participation or "").strip()
        if participation == "non_token_family_selector":
            continue
        if participation == "blocker":
            break
        if participation == "included":
            result.append(segment)
            continue
        if str(segment.transport_location or "") in {"tools", "messages"}:
            break
        break
    return result


def _is_cache_family_selector_segment(segment: ProviderPayloadSegment) -> bool:
    return str(segment.boundary_participation or "") == "non_token_family_selector"


def _is_provider_tool_schema_prefix_segment(segment: ProviderPayloadSegment) -> bool:
    return (
        str(segment.transport_location or "") == "tools"
        and str(segment.prefix_family or "") == "provider_physical_tool_schema_prefix"
        and str(segment.boundary_participation or "") == "included"
        and str(segment.physical_prefix_lane or "") == "provider_tool_schema_prefix"
    )


def _is_physical_cache_spine_message_segment(segment: ProviderPayloadSegment) -> bool:
    return (
        str(segment.transport_location or "") == "messages"
        and str(segment.boundary_participation or "") == "included"
        and str(segment.physical_prefix_lane or "") in {
            "global_static_prefix",
            "provider_visible_context_prefix",
        }
    )


def _physical_cache_spine_prefix_diagnostics(
    segments: tuple[ProviderPayloadSegment, ...],
    *,
    transport_contract_hash: str,
) -> dict[str, Any]:
    prefix_segments = _physical_cache_spine_segments(segments)
    boundary = prefix_segments[-1] if prefix_segments else None
    message_segments = [segment for segment in prefix_segments if segment.transport_location == "messages"]
    tool_segments = [segment for segment in prefix_segments if segment.transport_location == "tools"]
    spine_content_hash = _segments_hash(prefix_segments)
    message_subtotal_hash = _segments_hash(message_segments)
    tool_prefix_hash = _segments_hash(tool_segments)
    lane_counts: dict[str, int] = {}
    lane_order: list[str] = []
    segment_payloads: list[dict[str, Any]] = []
    for segment in prefix_segments:
        metadata = dict(segment.metadata or {})
        lane = str(segment.physical_prefix_lane or "").strip()
        if lane:
            lane_counts[lane] = lane_counts.get(lane, 0) + 1
            if lane not in lane_order:
                lane_order.append(lane)
        segment_payloads.append(
            {
                "segment_id": segment.segment_id,
                "kind": segment.kind,
                "transport_location": segment.transport_location,
                "ordinal": int(segment.ordinal or 0),
                "role": segment.role,
                "source_ref": segment.source_ref,
                "content_hash": segment.content_hash,
                "byte_length": int(segment.byte_length or 0),
                "prefix_family": segment.prefix_family,
                "semantic_source": segment.semantic_source,
                "logical_segment_ref": segment.logical_segment_ref,
                "semantic_slot": segment.semantic_slot,
                "physical_prefix_lane": lane,
                "boundary_participation": segment.boundary_participation,
                "exclusion_reason": segment.exclusion_reason,
                "consumer_contracts": list(segment.consumer_contracts),
                "forbidden_authorities": list(segment.forbidden_authorities),
                "cache_role": segment.cache_role,
                "prefix_tier": segment.prefix_tier,
                "cache_spine_generation": str(metadata.get("cache_spine_generation") or ""),
                "provider_visible_boundary": str(metadata.get("context_provider_visible_boundary") or ""),
                "provider_tool_protocol": dict(metadata.get("provider_tool_protocol") or {}),
            }
        )
    blocker_payloads = [
        _segment_projection(segment)
        for segment in sorted(tuple(segments or ()), key=lambda item: item.ordinal)
        if str(segment.boundary_participation or "") == "blocker"
    ]
    tool_protocol_rounds = _physical_cache_spine_tool_protocol_rounds(prefix_segments)
    return {
        "provider_payload_prefix_hash": _physical_prefix_hash(
            transport_contract_hash=transport_contract_hash,
            spine_content_hash=spine_content_hash,
        )
        if prefix_segments or transport_contract_hash
        else "",
        "physical_cache_spine_message_subtotal_hash": message_subtotal_hash,
        "tool_prefix_hash": tool_prefix_hash,
        "physical_spine_content_hash": spine_content_hash,
        "transport_contract_hash": str(transport_contract_hash or ""),
        "segment_count": len(prefix_segments),
        "message_segment_count": len(message_segments),
        "tool_segment_count": len(tool_segments),
        "segment_ids": [segment.segment_id for segment in prefix_segments],
        "kinds": [segment.kind for segment in prefix_segments],
        "transport_locations": [segment.transport_location for segment in prefix_segments],
        "roles": [segment.role for segment in prefix_segments],
        "prefix_families": [segment.prefix_family for segment in prefix_segments],
        "boundary_participations": [segment.boundary_participation for segment in prefix_segments],
        "segments": segment_payloads,
        "provider_tool_protocol_rounds": tool_protocol_rounds,
        "provider_tool_protocol_round_count": len(tool_protocol_rounds),
        "blockers": blocker_payloads,
        "first_blocker": blocker_payloads[0] if blocker_payloads else {},
        "boundary_segment_id": boundary.segment_id if boundary is not None else "",
        "boundary_kind": boundary.kind if boundary is not None else "",
        "boundary_ordinal": int(boundary.ordinal or 0) if boundary is not None else 0,
        "boundary_content_hash": boundary.content_hash if boundary is not None else "",
        "provider_visible_boundary_source": "physical_cache_spine",
        "provider_visible_boundaries": [
            str(dict(segment.metadata or {}).get("context_provider_visible_boundary") or "")
            for segment in prefix_segments
        ],
        "lane_counts": lane_counts,
        "lane_order": lane_order,
        "authority": "runtime.model_gateway.provider_payload.physical_cache_spine",
    }


def _segment_projection(segment: ProviderPayloadSegment) -> dict[str, Any]:
    return {
        "segment_id": segment.segment_id,
        "kind": segment.kind,
        "transport_location": segment.transport_location,
        "ordinal": int(segment.ordinal or 0),
        "role": segment.role,
        "source_ref": segment.source_ref,
        "content_hash": segment.content_hash,
        "byte_length": int(segment.byte_length or 0),
        "prefix_family": segment.prefix_family,
        "semantic_source": segment.semantic_source,
        "logical_segment_ref": segment.logical_segment_ref,
        "semantic_slot": segment.semantic_slot,
        "physical_prefix_lane": segment.physical_prefix_lane,
        "boundary_participation": segment.boundary_participation,
        "exclusion_reason": segment.exclusion_reason,
        "consumer_contracts": list(segment.consumer_contracts),
        "forbidden_authorities": list(segment.forbidden_authorities),
        "cache_role": segment.cache_role,
        "prefix_tier": segment.prefix_tier,
    }


def _physical_cache_spine_tool_protocol_rounds(segments: tuple[ProviderPayloadSegment, ...] | list[ProviderPayloadSegment]) -> list[dict[str, Any]]:
    rounds: dict[str, dict[str, Any]] = {}
    for segment in sorted(tuple(segments or ()), key=lambda item: item.ordinal):
        metadata = dict(segment.metadata or {})
        protocol = dict(metadata.get("provider_tool_protocol") or {})
        if str(protocol.get("unit") or "").strip() != "provider_native_tool_round":
            continue
        round_id = str(protocol.get("round_id") or "").strip()
        if not round_id:
            continue
        payload = rounds.setdefault(
            round_id,
            {
                "round_id": round_id,
                "segment_ids": [],
                "roles": [],
                "tool_call_ids": [str(item) for item in list(protocol.get("tool_call_ids") or []) if str(item or "")],
                "round_member_roles": [],
                "closed": False,
                "authority": "runtime.model_gateway.provider_payload.physical_cache_spine.tool_protocol_rounds",
            },
        )
        payload["segment_ids"].append(segment.segment_id)
        payload["roles"].append(segment.role)
        payload["round_member_roles"].append(str(protocol.get("round_member_role") or ""))
    result: list[dict[str, Any]] = []
    for payload in rounds.values():
        round_member_roles = [str(item) for item in list(payload.get("round_member_roles") or []) if str(item)]
        tool_call_ids = [str(item) for item in list(payload.get("tool_call_ids") or []) if str(item)]
        tool_count = sum(1 for item in round_member_roles if item == "tool")
        payload["closed"] = bool("assistant" in round_member_roles and tool_call_ids and tool_count >= len(set(tool_call_ids)))
        result.append(payload)
    return sorted(result, key=lambda item: str(item.get("round_id") or ""))


def _ordered_provider_payload_segments(
    *,
    segments: list[ProviderPayloadSegment],
) -> tuple[ProviderPayloadSegment, ...]:
    ordered = sorted(list(segments or []), key=_provider_payload_physical_sort_key)
    return tuple(
        _with_provider_payload_ordinal(
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
    segment: ProviderPayloadSegment,
    ordinal: int,
) -> ProviderPayloadSegment:
    stable_segment_id = _provider_payload_segment_id(segment=segment, ordinal=ordinal)
    if int(segment.ordinal or 0) == int(ordinal or 0) and str(segment.segment_id or "") == stable_segment_id:
        return segment
    return replace(
        segment,
        ordinal=int(ordinal or 0),
        segment_id=stable_segment_id,
    )


def _provider_payload_segment_id(*, segment: ProviderPayloadSegment, ordinal: int) -> str:
    digest = _stable_text_hash(
        canonical_json(
            {
                "provider_payload_segment": "physical_segment_identity.v1",
                "ordinal": int(ordinal or 0),
                "transport_location": str(segment.transport_location or ""),
                "role": str(segment.role or ""),
                "content_hash": str(segment.content_hash or ""),
                "physical_prefix_lane": str(segment.physical_prefix_lane or ""),
                "boundary_participation": str(segment.boundary_participation or ""),
            }
        )
    ).removeprefix("sha256:")[:16]
    transport_location = str(segment.transport_location or "segment").replace(":", "_")
    return f"ppseg:{int(ordinal or 0)}:{transport_location}:{digest}"


def _segments_hash(segments: list[ProviderPayloadSegment]) -> str:
    if not segments:
        return ""
    return _stable_text_hash(
        canonical_json(
            [
                {
                    "transport_location": segment.transport_location,
                    "role": segment.role,
                    "content_hash": segment.content_hash,
                    "physical_prefix_lane": segment.physical_prefix_lane,
                    "boundary_participation": segment.boundary_participation,
                }
                for segment in segments
            ]
        )
    )


def _context_cache_section_counts(segments: tuple[ProviderPayloadSegment, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for segment in tuple(segments or ()):
        if segment.transport_location != "messages":
            continue
        metadata = dict(segment.metadata or {})
        section = str(metadata.get("context_cache_section") or "unknown")
        counts[section] = counts.get(section, 0) + 1
    return counts


def _physical_cache_spine_segment_after_tail_count(segments: tuple[ProviderPayloadSegment, ...]) -> int:
    tail_seen = False
    count = 0
    for segment in [item for item in tuple(segments or ()) if item.transport_location == "messages"]:
        lane = str(segment.physical_prefix_lane or "").strip()
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
        if _is_provider_tool_schema_blocker(segment, metadata=metadata):
            continue
        if str(segment.boundary_participation or "") != "non_token_family_selector":
            continue
        components.append(
            {
                "kind": segment.kind,
                "transport_location": segment.transport_location,
                "role": segment.role,
                "source_ref": segment.source_ref,
                "content_hash": segment.content_hash,
                "byte_length": int(segment.byte_length or 0),
                "prefix_family": segment.prefix_family,
                "semantic_source": segment.semantic_source,
                "logical_segment_ref": segment.logical_segment_ref,
                "semantic_slot": segment.semantic_slot,
                "boundary_participation": segment.boundary_participation,
                "cache_role": segment.cache_role,
                "prefix_tier": segment.prefix_tier,
                "transport_contract_component": True,
                "transport_contract_role": str(
                    metadata.get("transport_contract_role")
                    or _transport_contract_role(segment)
                ),
                "tool_schema_blocker_drift_status": str(metadata.get("tool_schema_blocker_drift_status") or ""),
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


def _is_provider_tool_schema_blocker(
    segment: ProviderPayloadSegment,
    *,
    metadata: dict[str, Any] | None = None,
) -> bool:
    if str(segment.transport_location or "") != "tools":
        return False
    return (
        str(segment.boundary_participation or "") == "blocker"
        or str(segment.prefix_family or "") == "provider_tool_schema_blocker"
    )


def _physical_prefix_hash(
    *,
    transport_contract_hash: str,
    spine_content_hash: str = "",
) -> str:
    content_hash = str(spine_content_hash or "")
    if not content_hash:
        return ""
    return _stable_text_hash(
        canonical_json(
            {
                "cache_spine": "provider_payload_physical_cache_spine",
                "transport_contract_hash": str(transport_contract_hash or ""),
                "spine_content_hash": content_hash,
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
