from __future__ import annotations

from typing import Any


def provider_payload_manifest_dict(model_request: Any | None) -> dict[str, Any]:
    if model_request is None:
        return {}
    value = getattr(model_request, "provider_payload_manifest", None)
    if value is None and isinstance(model_request, dict):
        value = model_request.get("provider_payload_manifest")
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {}) if isinstance(value, dict) else {}


def provider_payload_cache_boundary(model_request: Any | None) -> dict[str, Any]:
    manifest = provider_payload_manifest_dict(model_request)
    return dict(manifest.get("cache_boundary") or {})


def provider_payload_segments(model_request: Any | None) -> list[dict[str, Any]]:
    manifest = provider_payload_manifest_dict(model_request)
    return [dict(item) for item in list(manifest.get("segments") or []) if isinstance(item, dict)]


def provider_payload_manifest_id(model_request: Any | None) -> str:
    manifest = provider_payload_manifest_dict(model_request)
    return str(manifest.get("manifest_id") or "")


def provider_payload_selected_tier(boundary: dict[str, Any]) -> str:
    tier = str(dict(boundary or {}).get("selected_prefix_key_tier") or "")
    return tier if tier in {"provider_global", "session", "task"} else "none"


def provider_payload_tier_prefix(boundary: dict[str, Any], tier: str) -> dict[str, Any]:
    tiers = dict(dict(boundary or {}).get("tier_prefixes") or {})
    return dict(tiers.get(str(tier or "")) or {})


def provider_payload_prefix_hash_for_tier(model_request: Any | None, tier: str) -> str:
    normalized = str(tier or "").strip()
    if normalized == "task":
        return str(getattr(model_request, "provider_payload_task_prefix_hash", "") or "")
    if normalized == "session":
        return str(getattr(model_request, "provider_payload_session_prefix_hash", "") or "")
    if normalized == "provider_global":
        return str(getattr(model_request, "provider_payload_provider_global_prefix_hash", "") or "")
    if normalized in {"stable", "provider_payload"}:
        return str(getattr(model_request, "provider_payload_prefix_hash", "") or "")
    return ""


def provider_payload_boundary_diagnostics(
    *,
    model_request: Any | None,
    boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = dict(boundary or provider_payload_cache_boundary(model_request))
    selected_tier = provider_payload_selected_tier(resolved)
    selected_prefix = provider_payload_tier_prefix(resolved, selected_tier)
    return {
        "provider_payload_manifest_ref": provider_payload_manifest_id(model_request),
        "provider_payload_prefix_hash": str(resolved.get("provider_payload_prefix_hash") or ""),
        "provider_payload_prefix_key_tier": selected_tier,
        "provider_payload_boundary_segment_id": str(resolved.get("selected_boundary_segment_id") or ""),
        "tool_catalog_hash": str(resolved.get("tool_catalog_hash") or ""),
        "stable_tool_catalog_hash": str(resolved.get("stable_tool_catalog_hash") or ""),
        "cache_sensitive_params_hash": str(resolved.get("cache_sensitive_params_hash") or ""),
        "stable_message_prefix_hash": str(resolved.get("stable_message_prefix_hash") or ""),
        "selected_provider_payload_prefix": selected_prefix,
    }
