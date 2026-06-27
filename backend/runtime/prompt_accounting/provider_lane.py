from __future__ import annotations

import hashlib
import json
from typing import Any


PROVIDER_LANE_AGENT_TOOL_LOOP = "agent_tool_loop"
PROVIDER_LANE_AGENT_CONTROL_NO_TOOL = "agent_control_no_tool"
PROVIDER_LANE_COMPACTION = "compaction"
PROVIDER_LANE_UTILITY = "utility"
PROVIDER_LANE_LEGACY_UNSCOPED = "legacy_unscoped"

KNOWN_PROVIDER_LANES = frozenset(
    {
        PROVIDER_LANE_AGENT_TOOL_LOOP,
        PROVIDER_LANE_AGENT_CONTROL_NO_TOOL,
        PROVIDER_LANE_COMPACTION,
        PROVIDER_LANE_UTILITY,
        PROVIDER_LANE_LEGACY_UNSCOPED,
    }
)


def normalize_provider_lane(value: Any) -> str:
    lane = str(value or "").strip()
    if lane in KNOWN_PROVIDER_LANES:
        return lane
    return PROVIDER_LANE_LEGACY_UNSCOPED


def provider_lane_from_accounting_context(
    context: dict[str, Any] | None,
    *,
    call_kind: str = "",
) -> str:
    payload = dict(context or {})
    explicit = normalize_provider_lane(payload.get("provider_lane"))
    if explicit != PROVIDER_LANE_LEGACY_UNSCOPED:
        return explicit
    prompt_manifest = dict(payload.get("prompt_manifest") or {})
    manifest_lane = normalize_provider_lane(prompt_manifest.get("provider_lane"))
    if manifest_lane != PROVIDER_LANE_LEGACY_UNSCOPED:
        return manifest_lane
    source = str(payload.get("source") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    invocation_kind = str(prompt_manifest.get("invocation_kind") or "").strip()
    call_purpose = str(payload.get("call_purpose") or "").strip()
    haystack = " ".join([source, request_id, invocation_kind, call_kind, call_purpose]).lower()
    if "partial-stream" in haystack or "partial_stream" in haystack:
        return PROVIDER_LANE_AGENT_CONTROL_NO_TOOL
    if "runtime-control-recovery" in haystack or "runtime_control_signal_recovery" in haystack:
        return PROVIDER_LANE_AGENT_CONTROL_NO_TOOL
    if "contract-observation" in haystack or "contract_observation" in haystack:
        return PROVIDER_LANE_AGENT_CONTROL_NO_TOOL
    if "admission-repair" in haystack or "admission_repair" in haystack:
        return PROVIDER_LANE_AGENT_CONTROL_NO_TOOL
    if "agent-closeout" in haystack or "agent_authored_closeout" in haystack:
        return PROVIDER_LANE_AGENT_TOOL_LOOP
    if "tool-followup" in haystack or "tool_followup" in haystack:
        return PROVIDER_LANE_AGENT_TOOL_LOOP
    if "active-turn-steer" in haystack or "active_turn_steer" in haystack:
        return PROVIDER_LANE_AGENT_TOOL_LOOP
    if source.startswith("harness.single_agent_turn") or source.startswith("harness.loop.single_agent_turn"):
        return PROVIDER_LANE_AGENT_TOOL_LOOP
    if "compaction" in haystack:
        return PROVIDER_LANE_COMPACTION
    if "utility" in haystack:
        return PROVIDER_LANE_UTILITY
    return PROVIDER_LANE_LEGACY_UNSCOPED


def physical_payload_family_components(
    *,
    provider: str,
    model: str,
    provider_lane: str,
    model_request: Any | None,
) -> dict[str, Any]:
    diagnostics = dict(getattr(model_request, "diagnostics", {}) or {}) if model_request is not None else {}
    boundary = dict(diagnostics.get("provider_payload_cache_boundary") or {})
    transport_payload = dict(diagnostics.get("provider_transport_payload") or {})
    return {
        "provider": str(provider or getattr(model_request, "provider", "") or ""),
        "model": str(model or getattr(model_request, "model", "") or ""),
        "provider_lane": normalize_provider_lane(provider_lane),
        "transport_contract_hash": str(
            getattr(model_request, "transport_contract_hash", "")
            or boundary.get("transport_contract_hash")
            or ""
        ),
        "stable_tool_catalog_hash": str(
            getattr(model_request, "stable_tool_catalog_hash", "")
            or boundary.get("stable_tool_catalog_hash")
            or ""
        ),
        "tool_catalog_hash": str(
            getattr(model_request, "tool_catalog_hash", "")
            or boundary.get("tool_catalog_hash")
            or ""
        ),
        "cache_sensitive_params_hash": str(
            getattr(model_request, "cache_sensitive_params_hash", "")
            or boundary.get("cache_sensitive_params_hash")
            or ""
        ),
        "tool_count": int(transport_payload.get("tool_count") or 0),
    }


def physical_payload_family_hash_for_model_request(
    *,
    provider: str,
    model: str,
    provider_lane: str,
    model_request: Any | None,
) -> str:
    components = physical_payload_family_components(
        provider=provider,
        model=model,
        provider_lane=provider_lane,
        model_request=model_request,
    )
    return "sha256:" + hashlib.sha256(
        json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
