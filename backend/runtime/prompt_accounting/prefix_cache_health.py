from __future__ import annotations

import math
from typing import Any


PREFIX_CACHE_HEALTH_AUTHORITY = "runtime.prompt_accounting.prefix_cache_health"


def evaluate_prefix_cache_health(
    *,
    diagnostics: dict[str, Any],
    usage: Any | None = None,
    cached_tokens: int | None = None,
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    prompt_tokens = _int(
        getattr(usage, "prompt_tokens", 0)
        or payload.get("provider_prompt_tokens")
        or payload.get("prompt_tokens")
    )
    cached = _int(
        cached_tokens
        if cached_tokens is not None
        else max(
            _int(getattr(usage, "cached_tokens", 0)),
            _int(getattr(usage, "cache_read_tokens", 0)),
        )
    )
    predicted_total = _int(
        payload.get("target_warm_cache_read_rate_total_tokens")
        or payload.get("predicted_prompt_tokens_total")
    )
    token_scale = (
        round(prompt_tokens / predicted_total, 6)
        if predicted_total > 0 and prompt_tokens > 0
        else 0.0
    )
    expected_predicted_tokens = _int(
        payload.get("physical_cache_spine_expected_read_predicted_tokens")
        or payload.get("physical_cache_spine_predicted_tokens")
    )
    append_predicted_tokens = _int(payload.get("context_append_prefix_predicted_tokens"))
    raw_boundaries = [
        dict(item)
        for item in list(
            payload.get("provider_cache_read_physical_spine_segment_boundaries")
            or payload.get("provider_cache_read_stable_segment_boundaries")
            or []
        )
        if isinstance(item, dict)
    ]
    all_boundaries = _provider_read_boundaries(raw_boundaries)
    required_keys = {
        _boundary_key(item)
        for item in list(payload.get("provider_cache_read_required_segment_boundaries") or [])
        if isinstance(item, dict)
    }
    required_boundaries = [
        dict(item)
        for item in all_boundaries
        if _boundary_key(item) in required_keys
    ]
    has_expected_spine = expected_predicted_tokens > 0
    expected_boundaries = _boundaries_within_expected_prefix(
        all_boundaries,
        expected_predicted_tokens=expected_predicted_tokens,
    )
    required_expected_boundaries = _boundaries_within_expected_prefix(
        required_boundaries,
        expected_predicted_tokens=expected_predicted_tokens,
    )
    expected_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached,
            predicted_total=predicted_total,
            provider_prompt_tokens=prompt_tokens,
        )
        for item in expected_boundaries
    ]
    required_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached,
            predicted_total=predicted_total,
            provider_prompt_tokens=prompt_tokens,
        )
        for item in required_expected_boundaries
    ]
    current_append_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached,
            predicted_total=predicted_total,
            provider_prompt_tokens=prompt_tokens,
        )
        for item in all_boundaries
        if has_expected_spine
        and _boundary_cumulative_tokens(item) > expected_predicted_tokens
    ]
    expected_scaled_tokens = _expected_scaled_tokens(
        expected_predicted_tokens=expected_predicted_tokens,
        expected_coverage=expected_coverage,
        predicted_total=predicted_total,
        prompt_tokens=prompt_tokens,
    )
    covered = bool(expected_scaled_tokens) and cached >= expected_scaled_tokens
    uncovered_expected = [
        item
        for item in expected_coverage
        if item.get("covered_by_provider_scaled_boundary") is False
    ]
    uncovered_required = [
        item
        for item in required_coverage
        if item.get("covered_by_provider_scaled_boundary") is False
    ]
    under_read_tokens = max(0, expected_scaled_tokens - cached)
    if not expected_scaled_tokens:
        status = "unmeasured"
        verdict = "unmeasured"
    elif covered:
        status = "physical_spine_estimated_covered"
        verdict = "covered"
    else:
        status = "physical_spine_estimated_partial"
        verdict = "provider_under_read"
    first_uncovered = dict(uncovered_expected[0]) if uncovered_expected else {}
    health = {
        "verdict": verdict,
        "status": status,
        "expected_prefix_tokens": expected_scaled_tokens,
        "cached_tokens": cached,
        "under_read_tokens": under_read_tokens,
        "first_missing_expected_prefix_identity": _identity_projection(first_uncovered),
        "hit_rate": _ratio(cached, prompt_tokens),
        "authority": PREFIX_CACHE_HEALTH_AUTHORITY,
    }
    return {
        "provider_prefix_cache_health": health,
        "provider_cache_read_token_scale": token_scale,
        "provider_cache_read_token_scale_source": "local_prediction_to_provider_prompt_token_scale_estimate",
        "provider_cache_read_prompt_tokens": prompt_tokens,
        "provider_cache_read_cached_tokens": cached,
        "provider_cache_read_coverage_scope": (
            "physical_cache_spine" if has_expected_spine else "physical_cache_spine_boundary"
        ),
        "provider_cache_read_physical_spine_predicted_tokens": expected_predicted_tokens,
        "provider_cache_read_physical_spine_provider_scaled_tokens": expected_scaled_tokens if has_expected_spine else 0,
        "provider_cache_read_current_context_append_predicted_tokens": append_predicted_tokens,
        "provider_cache_read_current_context_append_provider_scaled_tokens": _scaled_tokens(
            append_predicted_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=prompt_tokens,
        ),
        "provider_cache_read_current_context_append_promoted_to_next_turn": append_predicted_tokens > 0,
        "provider_cache_read_non_expected_prompt_predicted_tokens": max(
            0,
            _int(predicted_total) - _int(expected_predicted_tokens),
        )
        if has_expected_spine
        else 0,
        "provider_cache_read_required_coverage_status": status,
        "provider_cache_read_required_coverage_evidence": (
            "physical_spine_identity_boundary_estimate"
            if expected_coverage
            else ("physical_spine_total_estimate" if has_expected_spine else "unmeasured")
        ),
        "provider_cache_read_required_segment_coverage": required_coverage,
        "provider_cache_read_uncovered_required_segments": [
            str(item.get("kind") or "") for item in uncovered_required
        ],
        "provider_cache_read_uncovered_required_count": len(uncovered_required),
        "provider_cache_read_physical_spine_segment_coverage": expected_coverage,
        "provider_cache_read_physical_spine_internal_boundary_coverage": expected_coverage,
        "provider_cache_read_physical_spine_uncovered_boundary_precision": (
            "physical_spine_identity_boundary_estimate"
            if expected_coverage
            else "physical_spine_total_only"
        ),
        "provider_cache_read_first_uncovered_physical_spine_segment": first_uncovered,
        "provider_cache_read_first_missing_expected_prefix_identity": dict(
            health["first_missing_expected_prefix_identity"]
        ),
        "provider_cache_read_uncovered_physical_spine_count": len(uncovered_expected),
        "provider_cache_read_current_context_append_segment_coverage": current_append_coverage,
        "provider_cache_read_first_current_context_append_segment": dict(current_append_coverage[0]) if current_append_coverage else {},
        "provider_cache_read_current_context_append_segment_count": len(current_append_coverage),
        "provider_cache_read_physical_spine_estimated_tokens": expected_scaled_tokens,
        "provider_cache_read_physical_spine_estimated_source": (
            "physical_cache_spine" if has_expected_spine else "last_physical_spine_segment_boundary"
        )
        if expected_scaled_tokens
        else "unmeasured",
        "provider_cache_read_physical_spine_estimated_covered": covered if expected_scaled_tokens else None,
        "provider_cache_read_physical_spine_under_read_tokens": under_read_tokens,
        "provider_cache_read_physical_spine_covered": covered if expected_scaled_tokens else None,
        "provider_cache_read_physical_spine_coverage_evidence": (
            "physical_spine_identity_boundary_estimate"
            if expected_coverage
            else ("physical_spine_total_estimate" if has_expected_spine else "unmeasured")
        ),
    }


def _boundaries_within_expected_prefix(
    boundaries: list[dict[str, Any]],
    *,
    expected_predicted_tokens: int,
) -> list[dict[str, Any]]:
    if expected_predicted_tokens <= 0:
        return list(boundaries)
    return [
        item
        for item in list(boundaries or [])
        if _boundary_cumulative_tokens(item) <= expected_predicted_tokens
    ]


def _coverage_item(
    boundary: dict[str, Any],
    *,
    cached_tokens: int,
    predicted_total: int,
    provider_prompt_tokens: int,
) -> dict[str, Any]:
    raw_boundary = _boundary_cumulative_tokens(boundary)
    scaled_boundary = _scaled_tokens(
        raw_boundary,
        predicted_total=predicted_total,
        provider_prompt_tokens=provider_prompt_tokens,
    )
    covered_scaled = bool(scaled_boundary) and cached_tokens >= scaled_boundary
    return {
        **dict(boundary or {}),
        "raw_cumulative_predicted_tokens": raw_boundary,
        "provider_scaled_cumulative_tokens": scaled_boundary,
        "covered_by_raw_predicted_boundary": bool(raw_boundary) and cached_tokens >= raw_boundary,
        "covered_by_provider_scaled_boundary": covered_scaled,
        "covered_by_provider_scaled_boundary_estimate": covered_scaled,
        "coverage_evidence": "estimated_from_local_token_scale" if scaled_boundary else "unmeasured",
        "provider_scaled_under_read_tokens": max(0, scaled_boundary - cached_tokens) if scaled_boundary else 0,
    }


def _provider_read_boundaries(boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    read_cumulative = 0
    for item in list(boundaries or []):
        transport_location = str(item.get("transport_location") or "").strip()
        if transport_location and transport_location != "messages":
            continue
        tokens = _int(item.get("predicted_tokens"))
        read_cumulative += tokens
        normalized = dict(item)
        normalized["physical_cumulative_predicted_tokens"] = _int(item.get("cumulative_predicted_tokens"))
        normalized["provider_read_cumulative_predicted_tokens"] = read_cumulative
        normalized["cumulative_predicted_tokens"] = read_cumulative
        result.append(normalized)
    return result


def _boundary_key(boundary: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(boundary.get("segment_id") or ""),
        str(boundary.get("content_hash") or ""),
        _int(boundary.get("ordinal")),
        str(boundary.get("kind") or ""),
    )


def _boundary_cumulative_tokens(boundary: dict[str, Any]) -> int:
    return _int(
        boundary.get("provider_read_cumulative_predicted_tokens")
        or boundary.get("cumulative_predicted_tokens")
    )


def _expected_scaled_tokens(
    *,
    expected_predicted_tokens: int,
    expected_coverage: list[dict[str, Any]],
    predicted_total: int,
    prompt_tokens: int,
) -> int:
    if expected_predicted_tokens > 0:
        return _scaled_tokens(
            expected_predicted_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=prompt_tokens,
        )
    if expected_coverage:
        return _int(expected_coverage[-1].get("provider_scaled_cumulative_tokens"))
    return 0


def _scaled_tokens(raw_tokens: int, *, predicted_total: int, provider_prompt_tokens: int) -> int:
    if raw_tokens <= 0:
        return 0
    if predicted_total <= 0 or provider_prompt_tokens <= 0:
        return raw_tokens
    return max(1, int(math.ceil(raw_tokens * provider_prompt_tokens / max(1, predicted_total))))


def _identity_projection(boundary: dict[str, Any]) -> dict[str, Any]:
    if not boundary:
        return {}
    identity = dict(boundary.get("prefix_identity") or {})
    return {
        "segment_id": str(boundary.get("segment_id") or ""),
        "ordinal": _int(boundary.get("ordinal")),
        "kind": str(boundary.get("kind") or ""),
        "transport_location": str(boundary.get("transport_location") or ""),
        "role": str(boundary.get("role") or ""),
        "physical_prefix_lane": str(boundary.get("physical_prefix_lane") or identity.get("physical_lane") or ""),
        "semantic_slot": str(boundary.get("semantic_slot") or identity.get("semantic_slot") or ""),
        "logical_segment_ref": str(boundary.get("logical_segment_ref") or identity.get("logical_segment_ref") or ""),
        "context_contract_node_ref": str(boundary.get("context_contract_node_ref") or ""),
        "context_contract_edge_refs": _string_list(boundary.get("context_contract_edge_refs")),
        "connection_contract_ref": str(boundary.get("connection_contract_ref") or ""),
        "agent_domain": str(boundary.get("agent_domain") or ""),
        "control_signal": str(boundary.get("control_signal") or ""),
        "cache_expectation": str(boundary.get("cache_expectation") or ""),
        "origin_authority": str(identity.get("origin_authority") or ""),
        "origin_ref": str(identity.get("origin_ref") or ""),
        "lifecycle_state": str(identity.get("lifecycle_state") or ""),
        "cache_read_expectation": str(identity.get("cache_read_expectation") or ""),
        "provider_scaled_under_read_tokens": _int(boundary.get("provider_scaled_under_read_tokens")),
        "provider_scaled_cumulative_tokens": _int(boundary.get("provider_scaled_cumulative_tokens")),
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0, numerator) / max(1, denominator), 4)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    return []
