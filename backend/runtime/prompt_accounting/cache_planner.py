from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import replace
from typing import Any

from runtime.prompt_accounting.cache_policy import is_cache_eligible_prefix, is_prefix_eligible_for_tier

from .models import ModelTokenUsageRecord, CachePlanRecord, PromptSegmentMap
from .prefix_cache_health import evaluate_prefix_cache_health
from .provider_payload_boundary import (
    provider_payload_boundary_diagnostics,
    provider_payload_cache_boundary,
    provider_payload_physical_cache_spine,
)


CACHE_READ_REQUIRED_SEGMENT_KINDS = {
    "native_tool_binding_schema",
    "global_static",
    "action_schema_static",
    "tool_index_stable",
}
APPEND_ONLY_REPLAY_SEGMENT_KINDS = {
    "read_evidence_context",
    "single_agent_turn_tool_call",
    "tool_transcript_delta",
    "task_state_replay_entry",
}


def stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def prompt_cache_key(*, scope: str, inputs: dict[str, Any]) -> str:
    payload = json.dumps(_json_stable(inputs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
    safe_scope = str(scope or "prompt").strip().replace(" ", "_")
    return f"{safe_scope}:{digest}"


class PromptCachePlanner:
    """Builds request-level cache records from provider-visible physical cache spine."""

    def plan(
        self,
        segment_map: PromptSegmentMap,
        *,
        provider: str = "",
        model: str = "",
        provider_request: Any | None = None,
        created_at: float | None = None,
    ) -> CachePlanRecord:
        combined_stable_prefix = []
        provider_global_prefix = []
        session_prefix = []
        collect_provider_global = True
        collect_session = True
        collect_stable = True
        for segment in segment_map.segments:
            if _is_provider_payload_tool_blocker_segment(segment):
                continue
            tier = str(getattr(segment, "prefix_tier", "") or "none")
            if collect_stable and is_cache_eligible_prefix(cache_role=segment.cache_role, prefix_tier=tier):
                combined_stable_prefix.append(segment)
            else:
                collect_stable = False
            if collect_provider_global and is_prefix_eligible_for_tier(
                cache_role=segment.cache_role,
                prefix_tier=tier,
                tier="provider_global",
            ):
                provider_global_prefix.append(segment)
            else:
                collect_provider_global = False
            if collect_session and is_prefix_eligible_for_tier(
                cache_role=segment.cache_role,
                prefix_tier=tier,
                tier="session",
            ):
                session_prefix.append(segment)
            else:
                collect_session = False
            if not collect_session and not is_cache_eligible_prefix(
                cache_role=segment.cache_role,
                prefix_tier=tier,
            ):
                break
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        diagnostics = {
            **_prefix_diagnostics(
                segment_map=segment_map,
                combined_stable_prefix=combined_stable_prefix,
                provider_global_prefix=provider_global_prefix,
                session_prefix=session_prefix,
            ),
            **_prompt_manifest_cache_diagnostics(segment_map),
        }
        provider_boundary = provider_payload_cache_boundary(provider_request)
        if provider_boundary:
            provider_record = _plan_from_provider_payload_boundary(
                segment_map=segment_map,
                provider=str(provider or segment_map.provider or ""),
                model=str(model or segment_map.model or ""),
                provider_request=provider_request,
                boundary=provider_boundary,
                timestamp=timestamp,
                diagnostics=diagnostics,
            )
            if provider_record is not None:
                return provider_record
        return CachePlanRecord(
            cache_plan_id=f"pcache:{segment_map.request_id}",
            request_id=segment_map.request_id,
            provider=str(provider or segment_map.provider or ""),
            model=str(model or segment_map.model or ""),
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            scope="none",
            status="bypassed",
            cache_safety_reasons=("no_provider_payload_physical_cache_spine_boundary",),
            created_at=timestamp,
            diagnostics={
                **diagnostics,
                "prefix_hash_source": "missing_provider_payload_manifest",
            },
        )

    def with_provider_usage(
        self,
        record: CachePlanRecord,
        usage: ModelTokenUsageRecord | None,
    ) -> CachePlanRecord:
        if usage is None:
            return record
        cached = max(int(usage.cached_tokens or 0), int(usage.cache_read_tokens or 0))
        creation = int(usage.cache_creation_tokens or 0)
        if record.status == "bypassed":
            status = "bypassed"
        elif cached > 0:
            status = "hit"
        else:
            status = "miss"
        base_diagnostics = dict(record.diagnostics or {})
        coverage_diagnostics = _provider_cache_read_coverage_diagnostics(
            diagnostics=base_diagnostics,
            usage=usage,
            cached_tokens=cached,
        )
        diagnostics = {
            **base_diagnostics,
            **coverage_diagnostics,
        }
        diagnostics = {
            **diagnostics,
            **_provider_actual_cache_target_diagnostics(
                diagnostics=diagnostics,
                usage=usage,
                cached_tokens=cached,
            ),
            "provider_usage_ref": usage.usage_id,
            "provider_cached_tokens": cached,
        }
        return replace(
            record,
            status=status,
            cached_tokens=cached,
            cache_read_tokens=int(usage.cache_read_tokens or 0),
            cache_creation_tokens=creation,
            cache_savings_tokens=cached,
            diagnostics=diagnostics,
        )


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _prefix_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    combined_stable_prefix: list[Any],
    provider_global_prefix: list[Any],
    session_prefix: list[Any],
) -> dict[str, Any]:
    total_tokens = _total_predicted_tokens(segment_map)
    stable_prefix_tokens = sum(int(item.predicted_tokens or 0) for item in combined_stable_prefix)
    provider_global_tokens = sum(int(item.predicted_tokens or 0) for item in provider_global_prefix)
    session_tokens = sum(int(item.predicted_tokens or 0) for item in session_prefix)
    stable_role_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.cache_role or "") in {"cacheable_prefix", "session_stable"}
    )
    volatile_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if _is_non_cache_payload_segment(segment)
    )
    non_cache_lane_tokens = _non_cache_payload_lane_tokens(segment_map)
    provider_tool_schema_blocker_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if _is_provider_payload_tool_blocker_segment(segment)
    )
    replay_stable_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") in APPEND_ONLY_REPLAY_SEGMENT_KINDS
        and str(segment.cache_role or "") in {"cacheable_prefix", "session_stable"}
        and str(segment.prefix_tier or "") == "session"
    )
    replay_volatile_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") in APPEND_ONLY_REPLAY_SEGMENT_KINDS
        and str(segment.cache_role or "") in {"volatile", "never_cache"}
    )
    read_evidence_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") in {"read_evidence_context", "read_evidence_injection"}
    )
    editor_context_index_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "editor_context_index"
    )
    attachment_context_index_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "attachment_context_index"
    )
    evidence_index_cursor_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "evidence_index_cursor"
    )
    task_mode_tail_context_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") in {"task_goal_context", "task_plan_context", "task_todo_context"}
    )
    current_editor_evidence_delta_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "current_editor_evidence_delta"
    )
    volatile_task_state_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "volatile_task_state"
    )
    runtime_memory_context_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "runtime_memory_context"
    )
    return {
        "prompt_stable_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in combined_stable_prefix)) if combined_stable_prefix else "",
        "provider_global_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in provider_global_prefix)) if provider_global_prefix else "",
        "session_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in session_prefix)) if session_prefix else "",
        "provider_global_prefix_segment_count": len(provider_global_prefix),
        "session_prefix_segment_count": len(session_prefix),
        "predicted_prompt_tokens_total": total_tokens,
        "provider_global_prefix_predicted_tokens": provider_global_tokens,
        "session_prefix_predicted_tokens": session_tokens,
        "prompt_stable_prefix_predicted_tokens": stable_prefix_tokens,
        "prompt_stable_cache_role_predicted_tokens": stable_role_tokens,
        "volatile_predicted_tokens": volatile_tokens,
        "volatile_non_cache_predicted_tokens": volatile_tokens,
        "current_turn_tail_predicted_tokens": non_cache_lane_tokens["current_turn_tail"],
        "never_replay_tail_predicted_tokens": non_cache_lane_tokens["never_replay_tail"],
        "unconfirmed_provider_replay_predicted_tokens": non_cache_lane_tokens["provider_visible_context_prefix"],
        "other_non_cache_payload_predicted_tokens": non_cache_lane_tokens["other"],
        "provider_tool_schema_blocker_predicted_tokens": provider_tool_schema_blocker_tokens,
        "body_after_prompt_stable_prefix_predicted_tokens": max(0, total_tokens - stable_prefix_tokens),
        "provider_global_prefix_token_ratio": _ratio(provider_global_tokens, total_tokens),
        "session_prefix_token_ratio": _ratio(session_tokens, total_tokens),
        "prompt_stable_prefix_token_ratio": _ratio(stable_prefix_tokens, total_tokens),
        "volatile_token_ratio": _ratio(volatile_tokens, total_tokens),
        "top_volatile_segment_families": _top_volatile_segment_families(segment_map),
        "append_only_replay_promoted_to_provider_visible_context_prefix": replay_stable_tokens > 0,
        "append_only_replay_context_prefix_predicted_tokens": replay_stable_tokens,
        "append_only_replay_volatile_predicted_tokens": replay_volatile_tokens,
        "read_evidence_exact_predicted_tokens": read_evidence_tokens,
        "attachment_context_index_predicted_tokens": attachment_context_index_tokens,
        "evidence_index_cursor_predicted_tokens": evidence_index_cursor_tokens,
        "task_mode_tail_context_predicted_tokens": task_mode_tail_context_tokens,
        "editor_context_index_predicted_tokens": editor_context_index_tokens,
        "current_editor_evidence_delta_predicted_tokens": current_editor_evidence_delta_tokens,
        "volatile_task_state_predicted_tokens": volatile_task_state_tokens,
        "runtime_memory_context_predicted_tokens": runtime_memory_context_tokens,
        **_physical_cache_spine_boundary_diagnostics(segment_map),
        **_cache_read_target_diagnostics(
            segment_map=segment_map,
            prefix_tokens=stable_prefix_tokens,
            prefix_source="segment_map_stable_prefix",
        ),
    }


def _total_predicted_tokens(segment_map: PromptSegmentMap) -> int:
    total = int(getattr(segment_map, "predicted_prompt_tokens", 0) or 0)
    if total > 0:
        return total
    return sum(int(segment.predicted_tokens or 0) for segment in segment_map.segments)


def _ratio(numerator: int, denominator: int) -> float:
    if int(denominator or 0) <= 0:
        return 0.0
    return round(max(0, int(numerator or 0)) / max(1, int(denominator or 0)), 4)


def _top_volatile_segment_families(segment_map: PromptSegmentMap, *, limit: int = 8) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for segment in segment_map.segments:
        if not _is_non_cache_payload_segment(segment):
            continue
        cache_role = str(segment.cache_role or "")
        prefix_tier = str(segment.prefix_tier or "")
        kind = str(segment.kind or "unknown")
        payload = totals.setdefault(
            kind,
            {
                "kind": kind,
                "predicted_tokens": 0,
                "segment_count": 0,
                "cache_roles": set(),
                "prefix_tiers": set(),
            },
        )
        payload["predicted_tokens"] += int(segment.predicted_tokens or 0)
        payload["segment_count"] += 1
        payload["cache_roles"].add(cache_role)
        payload["prefix_tiers"].add(prefix_tier)
    ordered = sorted(totals.values(), key=lambda item: int(item["predicted_tokens"]), reverse=True)[: max(1, int(limit or 8))]
    return [
        {
            "kind": str(item["kind"]),
            "predicted_tokens": int(item["predicted_tokens"]),
            "segment_count": int(item["segment_count"]),
            "cache_roles": sorted(str(role) for role in item["cache_roles"] if str(role)),
            "prefix_tiers": sorted(str(tier) for tier in item["prefix_tiers"] if str(tier)),
        }
        for item in ordered
        if int(item["predicted_tokens"]) > 0
    ]


def _is_non_cache_payload_segment(segment: Any) -> bool:
    if _is_provider_payload_tool_blocker_segment(segment):
        return False
    cache_role = str(getattr(segment, "cache_role", "") or "")
    prefix_tier = str(getattr(segment, "prefix_tier", "") or "")
    return cache_role in {"volatile", "never_cache"} or prefix_tier in {"volatile", "none"}


def _non_cache_payload_lane_tokens(segment_map: PromptSegmentMap) -> dict[str, int]:
    lane_tokens = {
        "current_turn_tail": 0,
        "never_replay_tail": 0,
        "provider_visible_context_prefix": 0,
        "other": 0,
    }
    for segment in segment_map.segments:
        if not _is_non_cache_payload_segment(segment):
            continue
        tokens = int(segment.predicted_tokens or 0)
        lane = str(getattr(segment, "physical_prefix_lane", "") or "").strip()
        if lane in lane_tokens and lane != "other":
            lane_tokens[lane] += tokens
        else:
            lane_tokens["other"] += tokens
    return lane_tokens


def _physical_cache_spine_boundary_diagnostics(segment_map: PromptSegmentMap) -> dict[str, Any]:
    boundaries: list[dict[str, Any]] = []
    required: list[dict[str, Any]] = []
    cumulative = 0
    for segment in segment_map.segments:
        if _is_provider_payload_tool_blocker_segment(segment):
            continue
        tokens = int(segment.predicted_tokens or 0)
        cumulative += tokens
        physical_lane = str(getattr(segment, "physical_prefix_lane", "") or "").strip()
        if str(getattr(segment, "boundary_participation", "") or "") != "included":
            break
        item = {
            "kind": str(segment.kind or ""),
            "ordinal": int(segment.ordinal or 0),
            "segment_id": str(segment.segment_id or ""),
            "content_hash": str(segment.content_hash or ""),
            "transport_location": str(getattr(segment, "transport_location", "") or ""),
            "role": str(getattr(segment, "role", "") or ""),
            "prefix_family": str(getattr(segment, "prefix_family", "") or ""),
            "logical_segment_ref": str(getattr(segment, "logical_segment_ref", "") or ""),
            "prefix_segment_ref": str(getattr(segment, "prefix_segment_ref", "") or ""),
            "semantic_slot": str(getattr(segment, "semantic_slot", "") or ""),
            "physical_prefix_lane": physical_lane,
            "prefix_identity": dict(getattr(segment, "prefix_identity", {}) or {}),
            "boundary_participation": str(getattr(segment, "boundary_participation", "") or ""),
            "exclusion_reason": str(getattr(segment, "exclusion_reason", "") or ""),
            "cache_role": str(segment.cache_role or ""),
            "prefix_tier": str(segment.prefix_tier or ""),
            "predicted_tokens": tokens,
            "cumulative_predicted_tokens": cumulative,
            "source": str(segment.source or ""),
            **_segment_contract_projection(dict(segment.metadata or {})),
        }
        boundaries.append(item)
        if _requires_provider_cache_read_coverage(segment_kind=str(segment.kind or ""), metadata=dict(segment.metadata or {})):
            required.append(item)
    return {
        "provider_cache_read_physical_spine_segment_boundaries": boundaries,
        "provider_cache_read_required_segment_boundaries": required,
        "provider_cache_read_required_segment_kinds": [item["kind"] for item in required],
    }


def _requires_provider_cache_read_coverage(*, segment_kind: str, metadata: dict[str, Any]) -> bool:
    if segment_kind in CACHE_READ_REQUIRED_SEGMENT_KINDS:
        return True
    return False


def _provider_cache_read_coverage_diagnostics(
    *,
    diagnostics: dict[str, Any],
    usage: ModelTokenUsageRecord,
    cached_tokens: int,
) -> dict[str, Any]:
    return evaluate_prefix_cache_health(
        diagnostics=diagnostics,
        usage=usage,
        cached_tokens=cached_tokens,
    )


def _cache_read_target_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    prefix_tokens: int,
    prefix_source: str,
) -> dict[str, Any]:
    total_tokens = _total_predicted_tokens(segment_map)
    estimate = _ratio(int(prefix_tokens or 0), total_tokens)
    goal = 0.95
    blockers: list[dict[str, Any]] = []
    if estimate < goal:
        blockers = _top_volatile_segment_families(segment_map, limit=5)
    return {
        "target_warm_cache_read_rate_goal": goal,
        "target_warm_cache_read_rate_estimate": estimate,
        "target_warm_cache_read_rate_gap": round(max(0.0, goal - estimate), 4),
        "target_warm_cache_read_rate_status": "ok" if estimate >= goal else "below_target",
        "target_warm_cache_read_rate_prefix_source": str(prefix_source or ""),
        "target_warm_cache_read_rate_prefix_tokens": max(0, int(prefix_tokens or 0)),
        "target_warm_cache_read_rate_total_tokens": total_tokens,
        "target_warm_cache_read_rate_blockers": blockers,
    }


def _expected_miss_budget_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    diagnostics: dict[str, Any],
    token_diagnostics: dict[str, Any],
    target_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    total_tokens = int(
        target_diagnostics.get("target_warm_cache_read_rate_total_tokens")
        or _total_predicted_tokens(segment_map)
        or 0
    )
    expected_prefix_tokens = int(target_diagnostics.get("target_warm_cache_read_rate_prefix_tokens") or 0)
    current_append_tokens = int(token_diagnostics.get("context_append_prefix_predicted_tokens") or 0)
    volatile_tokens = int(diagnostics.get("volatile_predicted_tokens") or 0)
    current_turn_tail_tokens = int(diagnostics.get("current_turn_tail_predicted_tokens") or 0)
    current_turn_tail_residual_tokens = max(0, current_turn_tail_tokens - current_append_tokens)
    never_replay_tail_tokens = int(diagnostics.get("never_replay_tail_predicted_tokens") or 0)
    unconfirmed_replay_tokens = int(diagnostics.get("unconfirmed_provider_replay_predicted_tokens") or 0)
    other_non_cache_tokens = int(diagnostics.get("other_non_cache_payload_predicted_tokens") or 0)
    blocker_tokens = int(token_diagnostics.get("provider_tool_schema_blocker_predicted_tokens") or 0)
    expected_miss_tokens = max(0, total_tokens - expected_prefix_tokens)
    volatile_control_tokens = max(0, volatile_tokens - current_append_tokens)
    categorized_tokens = current_append_tokens + volatile_control_tokens + blocker_tokens
    uncategorized_tokens = max(0, expected_miss_tokens - categorized_tokens)
    goal = float(target_diagnostics.get("target_warm_cache_read_rate_goal") or 0.95)
    allowed_miss_tokens = max(0, int(math.floor((1.0 - goal) * total_tokens)))
    families: list[dict[str, Any]] = []
    for kind, tokens, reason in (
        ("current_context_append", current_append_tokens, "current append is provider-visible now but becomes cache-readable only after provider success seals it into the next physical prefix frame"),
        ("current_turn_tail_residual", current_turn_tail_residual_tokens, "current-turn non-cache lane content outside declared current append should be inspected if large"),
        ("degraded_provider_protocol_replay", unconfirmed_replay_tokens, "provider protocol replay is degraded diagnostic input and is not confirmed old context"),
        ("never_replay_tail", never_replay_tail_tokens, "dynamic runtime tail is invocation-local and must remain outside the cache spine"),
        ("other_non_cache_payload", other_non_cache_tokens, "non-cache payload is outside the physical cache spine and should be inspected if large"),
        ("provider_tool_schema_sidecar", blocker_tokens, "provider tool schema travels as sidecar transport and is accounted separately from message-prefix cache reads"),
        ("uncategorized_non_prefix_payload", uncategorized_tokens, "remaining non-prefix payload should be inspected for cache pollution"),
    ):
        if tokens <= 0:
            continue
        families.append(
            {
                "kind": kind,
                "predicted_tokens": tokens,
                "predicted_token_ratio": _ratio(tokens, total_tokens),
                "reason": reason,
            }
        )
    over_budget = max(0, expected_miss_tokens - allowed_miss_tokens)
    return {
        "target_warm_cache_read_rate_expected_miss_tokens": expected_miss_tokens,
        "target_warm_cache_read_rate_allowed_miss_tokens": allowed_miss_tokens,
        "target_warm_cache_read_rate_expected_miss_over_budget_tokens": over_budget,
        "target_warm_cache_read_rate_expected_miss_ratio": _ratio(expected_miss_tokens, total_tokens),
        "target_warm_cache_read_rate_expected_miss_budget_status": "ok" if over_budget <= 0 else "over_budget",
        "target_warm_cache_read_rate_expected_miss_families": families,
        "target_warm_cache_read_rate_uncategorized_miss_tokens": uncategorized_tokens,
    }


def _provider_actual_cache_target_diagnostics(
    *,
    diagnostics: dict[str, Any],
    usage: ModelTokenUsageRecord,
    cached_tokens: int,
) -> dict[str, Any]:
    provider_prompt_tokens = int(usage.prompt_tokens or 0)
    actual = _ratio(int(cached_tokens or 0), provider_prompt_tokens)
    goal = float(diagnostics.get("target_warm_cache_read_rate_goal") or 0.95)
    plan_estimate = diagnostics.get("target_warm_cache_read_rate_estimate")
    plan_status = str(diagnostics.get("target_warm_cache_read_rate_status") or "")
    physical_spine_estimated_covered = diagnostics.get(
        "provider_cache_read_physical_spine_estimated_covered"
    )
    provider_below_target = provider_prompt_tokens > 0 and actual < goal
    physical_spine_under_read = physical_spine_estimated_covered is False
    blockers = list(diagnostics.get("target_warm_cache_read_rate_blockers") or [])
    if provider_below_target or physical_spine_under_read:
        blockers = [
            *_provider_cache_under_read_blockers(
                diagnostics=diagnostics,
                cached_tokens=int(cached_tokens or 0),
                provider_prompt_tokens=provider_prompt_tokens,
                actual=actual,
                goal=goal,
            ),
            *blockers,
        ]
    if provider_below_target:
        status = "provider_below_target"
    elif physical_spine_under_read:
        status = "provider_physical_cache_spine_under_read"
    else:
        status = "ok"
    anchor_status = _provider_cache_anchor_status(
        actual=actual,
        goal=goal,
        provider_prompt_tokens=provider_prompt_tokens,
        physical_spine_under_read=physical_spine_under_read,
        physical_spine_estimated_covered=physical_spine_estimated_covered,
        plan_estimate=plan_estimate,
    )
    return {
        "target_warm_cache_read_rate_plan_estimate": plan_estimate,
        "target_warm_cache_read_rate_plan_status": plan_status,
        "target_warm_cache_read_rate_actual": actual,
        "target_warm_cache_read_rate_actual_source": "provider_usage_cached_tokens_over_prompt_tokens"
        if provider_prompt_tokens > 0
        else "unmeasured",
        "target_warm_cache_read_rate_gap": round(max(0.0, goal - actual), 4)
        if provider_prompt_tokens > 0
        else diagnostics.get("target_warm_cache_read_rate_gap"),
        "target_warm_cache_read_rate_status": status,
        "target_warm_cache_read_rate_blockers": blockers,
        "provider_cache_anchor_status": anchor_status,
    }


def _provider_cache_anchor_status(
    *,
    actual: float,
    goal: float,
    provider_prompt_tokens: int,
    physical_spine_under_read: bool,
    physical_spine_estimated_covered: Any,
    plan_estimate: Any,
) -> str:
    if int(provider_prompt_tokens or 0) <= 0:
        return "unmeasured"
    if actual >= goal:
        return "anchored_to_target"
    if physical_spine_under_read:
        return "provider_physical_cache_spine_under_read"
    try:
        planned = float(plan_estimate)
    except (TypeError, ValueError):
        planned = 0.0
    if physical_spine_estimated_covered is True and planned < goal:
        return "dynamic_tail_or_current_append_over_budget"
    if physical_spine_estimated_covered is True:
        return "provider_under_target_after_physical_cache_spine"
    return "provider_physical_cache_spine_anchor_unverified"


def _provider_cache_under_read_blockers(
    *,
    diagnostics: dict[str, Any],
    cached_tokens: int,
    provider_prompt_tokens: int,
    actual: float,
    goal: float,
) -> list[dict[str, Any]]:
    first_uncovered = dict(diagnostics.get("provider_cache_read_first_uncovered_physical_spine_segment") or {})
    first_missing_identity = dict(
        dict(diagnostics.get("provider_prefix_cache_health") or {}).get("first_missing_expected_prefix_identity")
        or diagnostics.get("provider_cache_read_first_missing_expected_prefix_identity")
        or {}
    )
    physical_spine_estimated_tokens = int(diagnostics.get("provider_cache_read_physical_spine_estimated_tokens") or 0)
    current_context_append_tokens = int(diagnostics.get("provider_cache_read_current_context_append_predicted_tokens") or 0)
    current_context_append_scaled_tokens = int(diagnostics.get("provider_cache_read_current_context_append_provider_scaled_tokens") or 0)
    target_cached_tokens = int(math.ceil(float(goal or 0.0) * int(provider_prompt_tokens or 0)))
    blocker = {
        "kind": "provider_cache_read_under_target",
        "cache_roles": ["provider_usage"],
        "prefix_tiers": ["provider_payload"],
        "segment_count": 1,
        "provider_cached_tokens": int(cached_tokens or 0),
        "provider_prompt_tokens": int(provider_prompt_tokens or 0),
        "provider_cache_hit_rate": actual,
        "target_cache_hit_rate_goal": goal,
        "target_cached_tokens": target_cached_tokens,
        "target_cached_token_gap": max(0, target_cached_tokens - int(cached_tokens or 0)),
        "physical_cache_spine_estimated_tokens": physical_spine_estimated_tokens,
        "physical_cache_spine_estimated_source": str(diagnostics.get("provider_cache_read_physical_spine_estimated_source") or ""),
        "physical_cache_spine_estimated_covered": diagnostics.get("provider_cache_read_physical_spine_estimated_covered"),
        "under_read_tokens": max(0, physical_spine_estimated_tokens - int(cached_tokens or 0)),
        "current_context_append_predicted_tokens": current_context_append_tokens,
        "current_context_append_provider_scaled_tokens": current_context_append_scaled_tokens,
        "current_context_append_promoted_to_next_turn": bool(
            diagnostics.get("provider_cache_read_current_context_append_promoted_to_next_turn")
        ),
        "non_expected_prompt_predicted_tokens": int(diagnostics.get("provider_cache_read_non_expected_prompt_predicted_tokens") or 0),
    }
    if first_missing_identity:
        blocker["first_missing_expected_prefix_identity"] = first_missing_identity
    if first_uncovered:
        blocker["first_uncovered_physical_spine_segment"] = {
            "kind": str(first_uncovered.get("kind") or ""),
            "ordinal": int(first_uncovered.get("ordinal") or 0),
            "transport_location": str(first_uncovered.get("transport_location") or ""),
            "role": str(first_uncovered.get("role") or ""),
            "prefix_family": str(first_uncovered.get("prefix_family") or ""),
            "physical_prefix_lane": str(first_uncovered.get("physical_prefix_lane") or ""),
            "boundary_participation": str(first_uncovered.get("boundary_participation") or ""),
            "prefix_tier": str(first_uncovered.get("prefix_tier") or ""),
            "cache_role": str(first_uncovered.get("cache_role") or ""),
            "context_contract_node_ref": str(first_uncovered.get("context_contract_node_ref") or ""),
            "context_contract_edge_refs": _string_list(first_uncovered.get("context_contract_edge_refs")),
            "connection_contract_ref": str(first_uncovered.get("connection_contract_ref") or ""),
            "agent_domain": str(first_uncovered.get("agent_domain") or ""),
            "control_signal": str(first_uncovered.get("control_signal") or ""),
            "cache_expectation": str(first_uncovered.get("cache_expectation") or ""),
            "provider_scaled_cumulative_tokens": int(first_uncovered.get("provider_scaled_cumulative_tokens") or 0),
            "provider_scaled_under_read_tokens": int(first_uncovered.get("provider_scaled_under_read_tokens") or 0),
        }
    return [blocker]


def _prompt_manifest_cache_diagnostics(segment_map: PromptSegmentMap) -> dict[str, Any]:
    metadata = dict(getattr(segment_map, "metadata", {}) or {})
    manifest = dict(metadata.get("prompt_manifest") or {})
    cache_boundary = dict(manifest.get("cache_boundary") or {})
    manifest_diagnostics = dict(manifest.get("diagnostics") or {})
    composition = dict(manifest.get("prompt_composition") or {})
    composition_diagnostics = dict(composition.get("diagnostics") or {})
    composition_cache_boundary = dict(composition_diagnostics.get("cache_boundary") or {})
    assembly_request_fingerprint = str(
        cache_boundary.get("assembly_request_fingerprint")
        or manifest_diagnostics.get("assembly_request_fingerprint")
        or ""
    )
    section_fingerprint = str(
        cache_boundary.get("section_fingerprint")
        or manifest_diagnostics.get("section_fingerprint")
        or ""
    )
    return _drop_empty(
        {
            "prompt_manifest_ref": str(manifest.get("manifest_id") or ""),
            "assembly_request_fingerprint": assembly_request_fingerprint,
            "section_fingerprint": section_fingerprint,
            "prompt_composition_manifest_ref": str(composition.get("manifest_id") or ""),
            "prompt_composition_cache_boundary_status": str(composition_cache_boundary.get("status") or ""),
            "prompt_composition_prefix_tier_sequence": list(composition_cache_boundary.get("prefix_tier_sequence") or []),
            "prompt_composition_layer_violation_count": len(
                list(composition_cache_boundary.get("layer_cache_policy_violations") or [])
            ),
            "prompt_composition_segment_violation_count": len(
                list(composition_cache_boundary.get("segment_prefix_violations") or [])
            ),
        }
    )


def _plan_from_provider_payload_boundary(
    *,
    segment_map: PromptSegmentMap,
    provider: str,
    model: str,
    provider_request: Any | None,
    boundary: dict[str, Any],
    timestamp: float,
    diagnostics: dict[str, Any],
) -> CachePlanRecord | None:
    key_tier = "physical_cache_spine"
    selected_prefix = provider_payload_physical_cache_spine(boundary)
    prefix_hash = str(
        selected_prefix.get("provider_payload_prefix_hash")
        or ""
    )
    boundary_segment_id = str(
        selected_prefix.get("boundary_segment_id")
        or ""
    )
    provider_diagnostics = provider_payload_boundary_diagnostics(
        provider_request=provider_request,
        boundary=boundary,
    )
    token_diagnostics = _provider_payload_prefix_token_diagnostics(
        segment_map=segment_map,
        diagnostics=diagnostics,
        tier=key_tier,
        selected_prefix=selected_prefix,
    )
    target_diagnostics = _cache_read_target_diagnostics(
        segment_map=segment_map,
        prefix_tokens=int(
            token_diagnostics.get("physical_cache_spine_expected_read_predicted_tokens")
            or token_diagnostics.get("physical_cache_spine_predicted_tokens")
            or 0
        ),
        prefix_source="provider_payload_physical_cache_spine",
    )
    expected_miss_budget = _expected_miss_budget_diagnostics(
        segment_map=segment_map,
        diagnostics=diagnostics,
        token_diagnostics=token_diagnostics,
        target_diagnostics=target_diagnostics,
    )
    if not prefix_hash:
        return CachePlanRecord(
            cache_plan_id=f"pcache:{segment_map.request_id}",
            request_id=segment_map.request_id,
            provider=provider,
            model=model,
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            scope="none",
            status="bypassed",
            cache_safety_reasons=("no_provider_payload_physical_cache_spine_boundary",),
            created_at=timestamp,
            diagnostics={
                **diagnostics,
                **provider_diagnostics,
                **token_diagnostics,
                **target_diagnostics,
                **expected_miss_budget,
                "prefix_hash_source": "provider_payload_manifest",
                "cache_boundary_authority": "provider_payload_manifest.physical_cache_spine",
            },
        )
    key = prompt_cache_key(
        scope="provider_payload_physical_cache_spine",
        inputs={
            "provider": provider,
            "model": model,
            "cache_boundary": key_tier,
            "physical_cache_spine_hash": prefix_hash,
            "boundary_kind": str(selected_prefix.get("boundary_kind") or ""),
            "boundary_content_hash": str(selected_prefix.get("boundary_content_hash") or ""),
        },
    )
    return CachePlanRecord(
        cache_plan_id=f"pcache:{segment_map.request_id}",
        request_id=segment_map.request_id,
        provider=provider,
        model=model,
        run_id=segment_map.run_id,
        task_run_id=segment_map.task_run_id,
        session_id=segment_map.session_id,
        cache_key=key,
        prefix_hash=prefix_hash,
        boundary_segment_id=boundary_segment_id,
        scope="session" if segment_map.session_id else "global",
        status="eligible",
        cache_safety_reasons=(),
        created_at=timestamp,
        diagnostics={
            **diagnostics,
            **provider_diagnostics,
            **token_diagnostics,
            **target_diagnostics,
            **expected_miss_budget,
            "prefix_key_tier": key_tier,
            "prefix_hash_source": "provider_payload_manifest",
            "cache_boundary_authority": "provider_payload_manifest.physical_cache_spine",
            "physical_cache_spine_hash": prefix_hash,
            "physical_cache_spine_message_subtotal_hash": str(selected_prefix.get("physical_cache_spine_message_subtotal_hash") or ""),
            "physical_cache_spine_segment_count": int(selected_prefix.get("segment_count") or 0),
            "physical_cache_spine_message_segment_count": int(selected_prefix.get("message_segment_count") or 0),
            "physical_cache_spine_tool_segment_count": int(selected_prefix.get("tool_segment_count") or 0),
            "physical_cache_spine_boundary_segment_id": boundary_segment_id,
            "physical_cache_spine_segment_ids": list(selected_prefix.get("segment_ids") or []),
            "physical_cache_spine_transport_locations": [
                str(item.get("transport_location") or "")
                for item in _provider_payload_selected_prefix_segments(selected_prefix)
            ],
            "physical_cache_spine_roles": [
                str(item.get("role") or "")
                for item in _provider_payload_selected_prefix_segments(selected_prefix)
            ],
            "physical_cache_spine_prefix_families": [
                str(item.get("prefix_family") or "")
                for item in _provider_payload_selected_prefix_segments(selected_prefix)
            ],
            "physical_cache_spine_boundary_participations": [
                str(item.get("boundary_participation") or "")
                for item in _provider_payload_selected_prefix_segments(selected_prefix)
            ],
            "physical_cache_spine_first_blocker": dict(selected_prefix.get("first_blocker") or {}),
            "physical_cache_spine_blockers": list(selected_prefix.get("blockers") or []),
            "physical_cache_spine_tool_protocol_round_count": int(selected_prefix.get("provider_tool_protocol_round_count") or 0),
            "physical_cache_spine_tool_protocol_rounds": list(selected_prefix.get("provider_tool_protocol_rounds") or []),
            "physical_cache_spine_tool_protocol_round_ids": [
                str(item.get("round_id") or "")
                for item in list(selected_prefix.get("provider_tool_protocol_rounds") or [])
                if isinstance(item, dict) and str(item.get("round_id") or "")
            ],
            "physical_cache_spine_predicted_tokens": int(token_diagnostics.get("physical_cache_spine_predicted_tokens") or 0),
            "physical_cache_spine_expected_read_predicted_tokens": int(
                token_diagnostics.get("physical_cache_spine_expected_read_predicted_tokens") or 0
            ),
            "context_append_promoted_to_next_context_memory_prefix": int(
                token_diagnostics.get("context_append_prefix_predicted_tokens") or 0
            )
            > 0,
        },
    )


def _provider_payload_prefix_token_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    diagnostics: dict[str, Any],
    tier: str,
    selected_prefix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = dict(selected_prefix or {})
    message_tokens = _provider_payload_selected_message_prefix_predicted_tokens(
        segment_map=segment_map,
        selected_prefix=selected,
    )
    tool_tokens = _provider_payload_selected_tool_prefix_predicted_tokens(
        segment_map=segment_map,
        selected_prefix=selected,
    )
    prefix_tokens = _provider_payload_selected_prefix_predicted_tokens(
        segment_map=segment_map,
        selected_prefix=selected,
    )
    context_append_tokens = _context_append_prefix_predicted_tokens(segment_map, tier=tier)
    # Provider cache usage is reported against the chat-message prefix. Native
    # tool schemas travel as provider sidecar transport and are tracked as
    # physical-family inputs, not as required message-prefix cache reads.
    expected_cache_read_tokens = message_tokens
    tool_prefix_selected = int(selected.get("tool_segment_count") or 0) > 0
    blocker_tool_schema_tokens = _provider_tool_schema_blocker_predicted_tokens(segment_map)
    return {
        "physical_cache_spine_message_predicted_tokens": message_tokens,
        "physical_cache_spine_tool_predicted_tokens": tool_tokens,
        "physical_cache_spine_sidecar_predicted_tokens": tool_tokens,
        "provider_tool_schema_blocker_predicted_tokens": blocker_tool_schema_tokens,
        "context_append_prefix_predicted_tokens": context_append_tokens,
        "physical_cache_spine_expected_read_predicted_tokens": expected_cache_read_tokens,
        "physical_cache_spine_expected_read_scope": "provider_message_prefix",
        "physical_cache_spine_sidecar_transport_predicted_tokens": tool_tokens,
        "physical_cache_spine_tool_transport_selected": int(tool_prefix_selected),
        "physical_cache_spine_predicted_tokens": prefix_tokens,
        "physical_cache_spine_contract_predicted_tokens": prefix_tokens,
        **_provider_payload_selected_prefix_boundaries(
            segment_map=segment_map,
            selected_prefix=selected,
        ),
    }


def _provider_payload_selected_message_prefix_predicted_tokens(
    *,
    segment_map: PromptSegmentMap,
    selected_prefix: dict[str, Any],
) -> int:
    total = 0
    for item in _provider_payload_selected_prefix_segments(selected_prefix):
        if str(item.get("transport_location") or "messages") != "messages":
            continue
        total += _provider_payload_selected_segment_predicted_tokens(segment_map, item)
    return total


def _provider_payload_selected_tool_prefix_predicted_tokens(
    *,
    segment_map: PromptSegmentMap,
    selected_prefix: dict[str, Any],
) -> int:
    total = 0
    for item in _provider_payload_selected_prefix_segments(selected_prefix):
        if str(item.get("transport_location") or "") != "tools":
            continue
        total += _provider_payload_selected_segment_predicted_tokens(segment_map, item)
    return total


def _provider_payload_selected_prefix_predicted_tokens(
    *,
    segment_map: PromptSegmentMap,
    selected_prefix: dict[str, Any],
) -> int:
    total = 0
    for item in _provider_payload_selected_prefix_segments(selected_prefix):
        total += _provider_payload_selected_segment_predicted_tokens(segment_map, item)
    return total


def _provider_payload_selected_prefix_boundaries(
    *,
    segment_map: PromptSegmentMap,
    selected_prefix: dict[str, Any],
) -> dict[str, Any]:
    boundaries: list[dict[str, Any]] = []
    required: list[dict[str, Any]] = []
    cumulative = 0
    for item in _provider_payload_selected_prefix_segments(selected_prefix):
        content_hash = str(item.get("content_hash") or "")
        kind = str(item.get("kind") or "")
        tokens = _provider_payload_selected_segment_predicted_tokens(segment_map, item)
        cumulative += tokens
        boundary = {
            "kind": kind,
            "ordinal": int(item.get("ordinal") or 0),
            "segment_id": str(item.get("segment_id") or ""),
            "content_hash": content_hash,
            "transport_location": str(item.get("transport_location") or ""),
            "role": str(item.get("role") or ""),
            "prefix_family": str(item.get("prefix_family") or ""),
            "logical_segment_ref": str(item.get("logical_segment_ref") or ""),
            "prefix_segment_ref": str(item.get("prefix_segment_ref") or ""),
            "semantic_slot": str(item.get("semantic_slot") or ""),
            "physical_prefix_lane": str(item.get("physical_prefix_lane") or ""),
            "prefix_identity": dict(item.get("prefix_identity") or {}),
            "boundary_participation": str(item.get("boundary_participation") or ""),
            "exclusion_reason": str(item.get("exclusion_reason") or ""),
            "cache_role": str(item.get("cache_role") or ""),
            "prefix_tier": str(item.get("prefix_tier") or ""),
            "predicted_tokens": tokens,
            "cumulative_predicted_tokens": cumulative,
            "source": str(item.get("source_ref") or ""),
            **_segment_contract_projection(item),
        }
        boundaries.append(boundary)
        if _requires_provider_cache_read_coverage(segment_kind=kind, metadata={}):
            required.append(boundary)
    return {
        "provider_cache_read_physical_spine_segment_boundaries": boundaries,
        "provider_cache_read_required_segment_boundaries": required,
        "provider_cache_read_required_segment_kinds": [item["kind"] for item in required],
    }


def _provider_payload_selected_prefix_segments(selected_prefix: dict[str, Any]) -> list[dict[str, Any]]:
    segments = [
        dict(item)
        for item in list(dict(selected_prefix or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    if segments:
        return sorted(segments, key=lambda item: int(item.get("ordinal") or 0))
    segment_ids = [str(item) for item in list(dict(selected_prefix or {}).get("segment_ids") or []) if str(item or "")]
    kinds = [str(item) for item in list(dict(selected_prefix or {}).get("kinds") or [])]
    tool_segment_count = int(dict(selected_prefix or {}).get("tool_segment_count") or 0)
    return [
        {
            "segment_id": segment_id,
            "kind": kinds[index] if index < len(kinds) else "",
            "ordinal": index + 1,
            "transport_location": (
                "tools"
                if (index < tool_segment_count or (index < len(kinds) and kinds[index] == "native_tool_binding_schema"))
                else "messages"
            ),
        }
        for index, segment_id in enumerate(segment_ids)
    ]


def _segment_contract_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_contract_node_ref": str(payload.get("context_contract_node_ref") or ""),
        "context_contract_edge_refs": _string_list(payload.get("context_contract_edge_refs")),
        "connection_contract_ref": str(payload.get("connection_contract_ref") or payload.get("context_connection_contract_ref") or ""),
        "agent_domain": str(payload.get("agent_domain") or payload.get("context_agent_domain") or ""),
        "control_signal": str(payload.get("control_signal") or payload.get("context_control_signal") or ""),
        "cache_expectation": str(payload.get("cache_expectation") or ""),
    }


def _provider_payload_token_lookup(segment_map: PromptSegmentMap) -> dict[tuple[str, str, str, str], int]:
    result: dict[tuple[str, str, str, str], int] = {}
    for segment in tuple(segment_map.segments or ()):
        content_hash = str(getattr(segment, "content_hash", "") or "")
        if not content_hash:
            continue
        tokens = int(getattr(segment, "predicted_tokens", 0) or 0)
        transport_location = str(getattr(segment, "transport_location", "") or "")
        role = str(getattr(segment, "role", "") or "")
        kind = str(getattr(segment, "kind", "") or "")
        result[(transport_location, role, kind, content_hash)] = tokens
        result.setdefault((transport_location, "", kind, content_hash), tokens)
        result.setdefault(("", "", kind, content_hash), tokens)
        result.setdefault(("", "", "", content_hash), tokens)
    return result


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


def _provider_payload_selected_segment_predicted_tokens(
    segment_map: PromptSegmentMap,
    item: dict[str, Any],
) -> int:
    segment_id = str(item.get("segment_id") or "")
    if segment_id:
        for segment in tuple(segment_map.segments or ()):
            if str(getattr(segment, "segment_id", "") or "") == segment_id:
                return int(getattr(segment, "predicted_tokens", 0) or 0)
    content_hash = str(item.get("content_hash") or "")
    if not content_hash:
        return 0
    kind = str(item.get("kind") or "")
    transport_location = str(item.get("transport_location") or "")
    role = str(item.get("role") or "")
    token_lookup = _provider_payload_token_lookup(segment_map)
    return int(
        token_lookup.get((transport_location, role, kind, content_hash))
        or token_lookup.get((transport_location, "", kind, content_hash))
        or token_lookup.get(("", "", kind, content_hash))
        or token_lookup.get(("", "", "", content_hash))
        or 0
    )


def _context_append_prefix_predicted_tokens(segment_map: PromptSegmentMap, *, tier: str) -> int:
    del tier
    total = 0
    for segment in tuple(segment_map.segments or ()):
        metadata = dict(getattr(segment, "metadata", None) or {})
        if str(metadata.get("context_cache_section") or "") != "context_append":
            continue
        total += int(getattr(segment, "predicted_tokens", 0) or 0)
    return total


def _provider_tool_schema_blocker_predicted_tokens(segment_map: PromptSegmentMap) -> int:
    total = 0
    for segment in tuple(segment_map.segments or ()):
        if not _is_provider_payload_tool_blocker_segment(segment):
            continue
        total += int(getattr(segment, "predicted_tokens", 0) or 0)
    return total


def _is_provider_payload_tool_blocker_segment(segment: Any, *, metadata: dict[str, Any] | None = None) -> bool:
    if str(getattr(segment, "kind", "") or "") != "native_tool_binding_schema":
        return False
    if str(getattr(segment, "transport_location", "") or "") != "tools":
        return False
    return (
        str(getattr(segment, "boundary_participation", "") or "") == "blocker"
        or str(getattr(segment, "prefix_family", "") or "") == "provider_tool_schema_blocker"
    )


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in ("", None, [], {})}
