from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import replace
from typing import Any

from runtime.prompt_accounting.cache_policy import is_cache_eligible_prefix, is_prefix_eligible_for_tier

from .models import ModelTokenUsageRecord, PromptCacheRecord, PromptSegmentMap
from .provider_payload_boundary import (
    provider_payload_boundary_diagnostics,
    provider_payload_cache_boundary,
    provider_payload_selected_tier,
    provider_payload_tier_prefix,
)


CACHE_READ_REQUIRED_SEGMENT_KINDS = {
    "global_static",
    "action_schema_static",
    "tool_schema_catalog",
    "tool_index_stable",
    "task_run_contract_stable",
}
APPEND_ONLY_REPLAY_SEGMENT_KINDS = {
    "read_evidence_context",
    "single_agent_turn_tool_call",
    "single_agent_turn_tool_observation",
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
    """Builds request-level cache records from stable prefix segments."""

    def plan(
        self,
        segment_map: PromptSegmentMap,
        *,
        provider: str = "",
        model: str = "",
        model_request: Any | None = None,
        created_at: float | None = None,
    ) -> PromptCacheRecord:
        combined_stable_prefix = []
        provider_global_prefix = []
        session_prefix = []
        task_prefix = []
        collect_provider_global = True
        collect_session = True
        collect_task = True
        collect_stable = True
        for segment in segment_map.segments:
            if _is_provider_payload_tool_sidecar_segment(segment):
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
            if collect_task and is_prefix_eligible_for_tier(
                cache_role=segment.cache_role,
                prefix_tier=tier,
                tier="task",
            ):
                task_prefix.append(segment)
            else:
                collect_task = False
            if not collect_task and not is_cache_eligible_prefix(
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
                task_prefix=task_prefix,
            ),
            **_prompt_manifest_cache_diagnostics(segment_map),
        }
        provider_boundary = provider_payload_cache_boundary(model_request)
        if provider_boundary:
            provider_record = _plan_from_provider_payload_boundary(
                segment_map=segment_map,
                provider=str(provider or segment_map.provider or ""),
                model=str(model or segment_map.model or ""),
                model_request=model_request,
                boundary=provider_boundary,
                timestamp=timestamp,
                diagnostics=diagnostics,
            )
            if provider_record is not None:
                return provider_record
        key_tier, key_prefix = _primary_cache_key_prefix(
            provider_global_prefix=provider_global_prefix,
            session_prefix=session_prefix,
            task_prefix=task_prefix,
        )
        if not key_prefix:
            return PromptCacheRecord(
                cache_record_id=f"pcache:{segment_map.request_id}",
                request_id=segment_map.request_id,
                provider=str(provider or segment_map.provider or ""),
                model=str(model or segment_map.model or ""),
                run_id=segment_map.run_id,
                task_run_id=segment_map.task_run_id,
                session_id=segment_map.session_id,
                scope="none",
                status="bypassed",
                cache_safety_reasons=("no_stable_prefix_boundary",),
                created_at=timestamp,
                diagnostics=diagnostics,
            )
        boundary = key_prefix[-1]
        prefix_hash = stable_text_hash("|".join(segment.content_hash for segment in key_prefix))
        key = prompt_cache_key(
            scope="model_request_prefix",
            inputs={
                "provider": str(provider or segment_map.provider or ""),
                "model": str(model or segment_map.model or ""),
                "prefix_key_tier": key_tier,
                "prefix_hash": prefix_hash,
                "boundary_kind": boundary.kind,
                "boundary_ordinal": boundary.ordinal,
                "boundary_content_hash": boundary.content_hash,
            },
        )
        return PromptCacheRecord(
            cache_record_id=f"pcache:{segment_map.request_id}",
            request_id=segment_map.request_id,
            provider=str(provider or segment_map.provider or ""),
            model=str(model or segment_map.model or ""),
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            cache_key=key,
            prefix_hash=prefix_hash,
            boundary_segment_id=boundary.segment_id,
            scope="session" if segment_map.session_id else "global",
            status="eligible",
            cache_safety_reasons=(),
            created_at=timestamp,
            diagnostics={
                **diagnostics,
                **_cache_read_target_diagnostics(
                    segment_map=segment_map,
                    prefix_tokens=sum(int(item.predicted_tokens or 0) for item in key_prefix),
                    prefix_source=f"segment_map_{key_tier}_prefix",
                ),
                "prefix_key_tier": key_tier,
                "stable_prefix_segment_count": len(combined_stable_prefix),
                "stable_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in combined_stable_prefix),
            },
        )

    def with_provider_usage(
        self,
        record: PromptCacheRecord,
        usage: ModelTokenUsageRecord | None,
    ) -> PromptCacheRecord:
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
    task_prefix: list[Any],
) -> dict[str, Any]:
    total_tokens = _total_predicted_tokens(segment_map)
    stable_prefix_tokens = sum(int(item.predicted_tokens or 0) for item in combined_stable_prefix)
    provider_global_tokens = sum(int(item.predicted_tokens or 0) for item in provider_global_prefix)
    session_tokens = sum(int(item.predicted_tokens or 0) for item in session_prefix)
    task_tokens = sum(int(item.predicted_tokens or 0) for item in task_prefix)
    stable_role_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.cache_role or "") in {"cacheable_prefix", "session_stable"}
    )
    volatile_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if (
            str(segment.cache_role or "") in {"volatile", "never_cache"}
            or str(segment.prefix_tier or "") in {"volatile", "none"}
        )
        and not _is_provider_payload_tool_sidecar_segment(segment)
    )
    provider_sidecar_tool_schema_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if _is_provider_payload_tool_sidecar_segment(segment)
    )
    stable_transport_contract_tokens = provider_sidecar_tool_schema_tokens
    replay_stable_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") in APPEND_ONLY_REPLAY_SEGMENT_KINDS
        and str(segment.cache_role or "") in {"cacheable_prefix", "session_stable"}
        and str(segment.prefix_tier or "") == "task"
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
        "combined_stable_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in combined_stable_prefix)) if combined_stable_prefix else "",
        "provider_global_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in provider_global_prefix)) if provider_global_prefix else "",
        "session_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in session_prefix)) if session_prefix else "",
        "task_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in task_prefix)) if task_prefix else "",
        "provider_global_prefix_segment_count": len(provider_global_prefix),
        "session_prefix_segment_count": len(session_prefix),
        "task_prefix_segment_count": len(task_prefix),
        "predicted_prompt_tokens_total": total_tokens,
        "provider_global_prefix_predicted_tokens": provider_global_tokens,
        "session_prefix_predicted_tokens": session_tokens,
        "task_prefix_predicted_tokens": task_tokens,
        "combined_stable_prefix_predicted_tokens": stable_prefix_tokens,
        "stable_cache_role_predicted_tokens": stable_role_tokens,
        "volatile_predicted_tokens": volatile_tokens,
        "provider_sidecar_tool_schema_predicted_tokens": provider_sidecar_tool_schema_tokens,
        "stable_transport_contract_predicted_tokens": stable_transport_contract_tokens,
        "body_after_stable_prefix_predicted_tokens": max(0, total_tokens - stable_prefix_tokens),
        "body_after_task_prefix_predicted_tokens": max(0, total_tokens - task_tokens),
        "provider_global_prefix_token_ratio": _ratio(provider_global_tokens, total_tokens),
        "session_prefix_token_ratio": _ratio(session_tokens, total_tokens),
        "task_prefix_token_ratio": _ratio(task_tokens, total_tokens),
        "combined_stable_prefix_token_ratio": _ratio(stable_prefix_tokens, total_tokens),
        "volatile_token_ratio": _ratio(volatile_tokens, total_tokens),
        "top_volatile_segment_families": _top_volatile_segment_families(segment_map),
        "append_only_replay_promoted_to_task_prefix": replay_stable_tokens > 0,
        "append_only_replay_task_prefix_predicted_tokens": replay_stable_tokens,
        "append_only_replay_volatile_predicted_tokens": replay_volatile_tokens,
        "read_evidence_exact_predicted_tokens": read_evidence_tokens,
        "attachment_context_index_predicted_tokens": attachment_context_index_tokens,
        "evidence_index_cursor_predicted_tokens": evidence_index_cursor_tokens,
        "task_mode_tail_context_predicted_tokens": task_mode_tail_context_tokens,
        "editor_context_index_predicted_tokens": editor_context_index_tokens,
        "current_editor_evidence_delta_predicted_tokens": current_editor_evidence_delta_tokens,
        "volatile_task_state_predicted_tokens": volatile_task_state_tokens,
        "runtime_memory_context_predicted_tokens": runtime_memory_context_tokens,
        **_stable_segment_boundary_diagnostics(segment_map),
        **_cache_read_target_diagnostics(
            segment_map=segment_map,
            prefix_tokens=task_tokens,
            prefix_source="segment_map_task_prefix",
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
        if _is_provider_payload_tool_sidecar_segment(segment):
            continue
        cache_role = str(segment.cache_role or "")
        prefix_tier = str(segment.prefix_tier or "")
        if cache_role not in {"volatile", "never_cache"} and prefix_tier not in {"volatile", "none"}:
            continue
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


def _stable_segment_boundary_diagnostics(segment_map: PromptSegmentMap) -> dict[str, Any]:
    boundaries: list[dict[str, Any]] = []
    required: list[dict[str, Any]] = []
    cumulative = 0
    for segment in segment_map.segments:
        if _is_provider_payload_tool_sidecar_segment(segment):
            continue
        tokens = int(segment.predicted_tokens or 0)
        cumulative += tokens
        tier = str(segment.prefix_tier or "")
        if not is_cache_eligible_prefix(cache_role=segment.cache_role, prefix_tier=tier):
            break
        metadata = dict(segment.metadata or {})
        item = {
            "kind": str(segment.kind or ""),
            "ordinal": int(segment.ordinal or 0),
            "cache_role": str(segment.cache_role or ""),
            "prefix_tier": tier,
            "predicted_tokens": tokens,
            "cumulative_predicted_tokens": cumulative,
            "authority_class": str(metadata.get("authority_class") or segment.authority_class or ""),
            "source": str(segment.source or ""),
        }
        boundaries.append(item)
        if _requires_provider_cache_read_coverage(segment_kind=str(segment.kind or ""), metadata=metadata):
            required.append(item)
    return {
        "provider_cache_read_stable_segment_boundaries": boundaries,
        "provider_cache_read_required_segment_boundaries": required,
        "provider_cache_read_required_segment_kinds": [item["kind"] for item in required],
    }


def _requires_provider_cache_read_coverage(*, segment_kind: str, metadata: dict[str, Any]) -> bool:
    if segment_kind in CACHE_READ_REQUIRED_SEGMENT_KINDS:
        return True
    return str(metadata.get("authority_class") or "") == "provider_tool_schema_catalog"


def _provider_cache_read_coverage_diagnostics(
    *,
    diagnostics: dict[str, Any],
    usage: ModelTokenUsageRecord,
    cached_tokens: int,
) -> dict[str, Any]:
    raw_boundaries = [
        dict(item)
        for item in list(diagnostics.get("provider_cache_read_required_segment_boundaries") or [])
        if isinstance(item, dict)
    ]
    all_boundaries = [
        dict(item)
        for item in list(diagnostics.get("provider_cache_read_stable_segment_boundaries") or [])
        if isinstance(item, dict)
    ]
    predicted_total = int(
        diagnostics.get("target_warm_cache_read_rate_total_tokens")
        or diagnostics.get("predicted_prompt_tokens_total")
        or 0
    )
    provider_prompt_tokens = int(usage.prompt_tokens or 0)
    token_scale = (
        round(provider_prompt_tokens / predicted_total, 6)
        if predicted_total > 0 and provider_prompt_tokens > 0
        else 0.0
    )
    expected_prefix_predicted_tokens = int(diagnostics.get("expected_cache_read_prefix_predicted_tokens") or 0)
    context_append_predicted_tokens = int(diagnostics.get("context_append_prefix_predicted_tokens") or 0)
    has_expected_cache_read_prefix = expected_prefix_predicted_tokens > 0
    expected_cache_read_boundaries = [
        item
        for item in all_boundaries
        if not has_expected_cache_read_prefix
        or int(item.get("cumulative_predicted_tokens") or 0) <= expected_prefix_predicted_tokens
    ]
    expected_required_boundaries = [
        item
        for item in raw_boundaries
        if not has_expected_cache_read_prefix
        or int(item.get("cumulative_predicted_tokens") or 0) <= expected_prefix_predicted_tokens
    ]
    current_append_boundaries = [
        item
        for item in all_boundaries
        if has_expected_cache_read_prefix
        and int(item.get("cumulative_predicted_tokens") or 0) > expected_prefix_predicted_tokens
    ]
    required_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=provider_prompt_tokens,
        )
        for item in expected_required_boundaries
    ]
    stable_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=provider_prompt_tokens,
        )
        for item in expected_cache_read_boundaries
    ]
    current_append_coverage = [
        _coverage_item(
            item,
            cached_tokens=cached_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=provider_prompt_tokens,
        )
        for item in current_append_boundaries
    ]
    uncovered_required = [
        item
        for item in required_coverage
        if item.get("covered_by_provider_scaled_boundary") is False
    ]
    uncovered_stable = [
        item
        for item in stable_coverage
        if item.get("covered_by_provider_scaled_boundary") is False
    ]
    stable_prefix_estimated_tokens = 0
    stable_prefix_estimated_source = "unmeasured"
    if has_expected_cache_read_prefix:
        stable_prefix_estimated_tokens = _scaled_boundary_tokens(
            expected_prefix_predicted_tokens,
            predicted_total=predicted_total,
            provider_prompt_tokens=provider_prompt_tokens,
        )
        stable_prefix_estimated_source = "expected_cache_read_prefix_excluding_current_context_append"
    elif stable_coverage:
        stable_prefix_estimated_tokens = int(stable_coverage[-1].get("provider_scaled_cumulative_tokens") or 0)
        stable_prefix_estimated_source = "last_stable_segment_boundary"
    current_context_append_estimated_tokens = _scaled_boundary_tokens(
        context_append_predicted_tokens,
        predicted_total=predicted_total,
        provider_prompt_tokens=provider_prompt_tokens,
    )
    status = "unmeasured"
    if required_coverage:
        status = "estimated_covered" if not uncovered_required else "estimated_partial"
    stable_prefix_estimated_covered = (
        bool(stable_prefix_estimated_tokens)
        and int(cached_tokens or 0) >= stable_prefix_estimated_tokens
    )
    return {
        "provider_cache_read_token_scale": token_scale,
        "provider_cache_read_token_scale_source": "local_prediction_to_provider_prompt_token_scale_estimate",
        "provider_cache_read_prompt_tokens": provider_prompt_tokens,
        "provider_cache_read_cached_tokens": int(cached_tokens or 0),
        "provider_cache_read_coverage_scope": (
            "expected_cache_read_prefix_excludes_current_context_append"
            if has_expected_cache_read_prefix
            else "stable_prefix_boundary"
        ),
        "provider_cache_read_expected_prefix_predicted_tokens": expected_prefix_predicted_tokens,
        "provider_cache_read_expected_prefix_provider_scaled_tokens": stable_prefix_estimated_tokens
        if has_expected_cache_read_prefix
        else 0,
        "provider_cache_read_current_context_append_predicted_tokens": context_append_predicted_tokens,
        "provider_cache_read_current_context_append_provider_scaled_tokens": current_context_append_estimated_tokens,
        "provider_cache_read_current_context_append_promoted_to_next_turn": context_append_predicted_tokens > 0,
        "provider_cache_read_non_expected_prompt_predicted_tokens": max(
            0,
            int(predicted_total or 0) - int(expected_prefix_predicted_tokens or 0),
        )
        if has_expected_cache_read_prefix
        else 0,
        "provider_cache_read_required_coverage_status": status,
        "provider_cache_read_required_coverage_evidence": "estimated_from_local_token_scale" if required_coverage else "unmeasured",
        "provider_cache_read_required_segment_coverage": required_coverage,
        "provider_cache_read_uncovered_required_segments": [
            str(item.get("kind") or "") for item in uncovered_required
        ],
        "provider_cache_read_uncovered_required_count": len(uncovered_required),
        "provider_cache_read_stable_segment_coverage": stable_coverage,
        "provider_cache_read_first_uncovered_stable_segment": dict(uncovered_stable[0]) if uncovered_stable else {},
        "provider_cache_read_uncovered_stable_count": len(uncovered_stable),
        "provider_cache_read_current_context_append_segment_coverage": current_append_coverage,
        "provider_cache_read_first_current_context_append_segment": dict(current_append_coverage[0]) if current_append_coverage else {},
        "provider_cache_read_current_context_append_segment_count": len(current_append_coverage),
        "provider_cache_read_stable_prefix_estimated_tokens": stable_prefix_estimated_tokens,
        "provider_cache_read_stable_prefix_estimated_source": stable_prefix_estimated_source,
        "provider_cache_read_stable_prefix_estimated_covered": stable_prefix_estimated_covered,
        "provider_cache_read_stable_prefix_covered": None,
        "provider_cache_read_stable_prefix_coverage_evidence": (
            "estimated_from_local_token_scale"
            if stable_coverage and stable_prefix_estimated_covered
            else ("unmeasured_by_provider_usage" if stable_coverage else "unmeasured")
        ),
    }


def _coverage_item(
    boundary: dict[str, Any],
    *,
    cached_tokens: int,
    predicted_total: int,
    provider_prompt_tokens: int,
) -> dict[str, Any]:
    raw_boundary = int(boundary.get("cumulative_predicted_tokens") or 0)
    scaled_boundary = _scaled_boundary_tokens(
        raw_boundary,
        predicted_total=predicted_total,
        provider_prompt_tokens=provider_prompt_tokens,
    )
    covered_scaled = bool(scaled_boundary) and int(cached_tokens or 0) >= scaled_boundary
    return {
        **boundary,
        "raw_cumulative_predicted_tokens": raw_boundary,
        "provider_scaled_cumulative_tokens": scaled_boundary,
        "covered_by_raw_predicted_boundary": bool(raw_boundary) and int(cached_tokens or 0) >= raw_boundary,
        "covered_by_provider_scaled_boundary": covered_scaled,
        "covered_by_provider_scaled_boundary_estimate": covered_scaled,
        "coverage_evidence": "estimated_from_local_token_scale" if scaled_boundary else "unmeasured",
        "provider_scaled_under_read_tokens": max(0, scaled_boundary - int(cached_tokens or 0)) if scaled_boundary else 0,
    }


def _scaled_boundary_tokens(
    raw_boundary: int,
    *,
    predicted_total: int,
    provider_prompt_tokens: int,
) -> int:
    if int(raw_boundary or 0) <= 0:
        return 0
    if int(predicted_total or 0) <= 0 or int(provider_prompt_tokens or 0) <= 0:
        return int(raw_boundary or 0)
    return max(1, int(math.ceil(int(raw_boundary or 0) * int(provider_prompt_tokens or 0) / int(predicted_total or 1))))


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
    stable_prefix_estimated_covered = diagnostics.get("provider_cache_read_stable_prefix_estimated_covered")
    provider_below_target = provider_prompt_tokens > 0 and actual < goal
    stable_prefix_under_read = stable_prefix_estimated_covered is False
    blockers = list(diagnostics.get("target_warm_cache_read_rate_blockers") or [])
    if provider_below_target or stable_prefix_under_read:
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
    elif stable_prefix_under_read:
        status = "provider_stable_prefix_under_read"
    else:
        status = "ok"
    anchor_status = _provider_cache_anchor_status(
        actual=actual,
        goal=goal,
        provider_prompt_tokens=provider_prompt_tokens,
        stable_prefix_under_read=stable_prefix_under_read,
        stable_prefix_estimated_covered=stable_prefix_estimated_covered,
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
    stable_prefix_under_read: bool,
    stable_prefix_estimated_covered: Any,
    plan_estimate: Any,
) -> str:
    if int(provider_prompt_tokens or 0) <= 0:
        return "unmeasured"
    if actual >= goal:
        return "anchored_to_target"
    if stable_prefix_under_read:
        return "provider_stable_prefix_under_read"
    try:
        planned = float(plan_estimate)
    except (TypeError, ValueError):
        planned = 0.0
    if stable_prefix_estimated_covered is True and planned < goal:
        return "dynamic_tail_or_current_append_over_budget"
    if stable_prefix_estimated_covered is True:
        return "provider_under_target_after_stable_prefix"
    return "provider_prefix_anchor_unverified"


def _provider_cache_under_read_blockers(
    *,
    diagnostics: dict[str, Any],
    cached_tokens: int,
    provider_prompt_tokens: int,
    actual: float,
    goal: float,
) -> list[dict[str, Any]]:
    first_uncovered = dict(diagnostics.get("provider_cache_read_first_uncovered_stable_segment") or {})
    stable_prefix_estimated_tokens = int(diagnostics.get("provider_cache_read_stable_prefix_estimated_tokens") or 0)
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
        "stable_prefix_estimated_tokens": stable_prefix_estimated_tokens,
        "stable_prefix_estimated_source": str(diagnostics.get("provider_cache_read_stable_prefix_estimated_source") or ""),
        "stable_prefix_estimated_covered": diagnostics.get("provider_cache_read_stable_prefix_estimated_covered"),
        "under_read_tokens": max(0, stable_prefix_estimated_tokens - int(cached_tokens or 0)),
        "current_context_append_predicted_tokens": current_context_append_tokens,
        "current_context_append_provider_scaled_tokens": current_context_append_scaled_tokens,
        "current_context_append_promoted_to_next_turn": bool(
            diagnostics.get("provider_cache_read_current_context_append_promoted_to_next_turn")
        ),
        "non_expected_prompt_predicted_tokens": int(diagnostics.get("provider_cache_read_non_expected_prompt_predicted_tokens") or 0),
    }
    if first_uncovered:
        blocker["first_uncovered_stable_segment"] = {
            "kind": str(first_uncovered.get("kind") or ""),
            "ordinal": int(first_uncovered.get("ordinal") or 0),
            "prefix_tier": str(first_uncovered.get("prefix_tier") or ""),
            "cache_role": str(first_uncovered.get("cache_role") or ""),
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


def _primary_cache_key_prefix(
    *,
    provider_global_prefix: list[Any],
    session_prefix: list[Any],
    task_prefix: list[Any],
) -> tuple[str, list[Any]]:
    if task_prefix:
        return "task", task_prefix
    if session_prefix:
        return "session", session_prefix
    if provider_global_prefix:
        return "provider_global", provider_global_prefix
    return "none", []


def _plan_from_provider_payload_boundary(
    *,
    segment_map: PromptSegmentMap,
    provider: str,
    model: str,
    model_request: Any | None,
    boundary: dict[str, Any],
    timestamp: float,
    diagnostics: dict[str, Any],
) -> PromptCacheRecord | None:
    key_tier = provider_payload_selected_tier(boundary)
    selected_prefix = provider_payload_tier_prefix(boundary, key_tier)
    prefix_hash = str(
        selected_prefix.get("provider_payload_prefix_hash")
        or boundary.get("provider_payload_prefix_hash")
        or ""
    )
    boundary_segment_id = str(
        selected_prefix.get("boundary_segment_id")
        or boundary.get("selected_boundary_segment_id")
        or ""
    )
    provider_diagnostics = provider_payload_boundary_diagnostics(
        model_request=model_request,
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
            token_diagnostics.get("expected_cache_read_prefix_predicted_tokens")
            or token_diagnostics.get("provider_payload_prefix_predicted_tokens")
            or 0
        ),
        prefix_source=f"provider_payload_{key_tier}_prefix",
    )
    if not prefix_hash:
        return PromptCacheRecord(
            cache_record_id=f"pcache:{segment_map.request_id}",
            request_id=segment_map.request_id,
            provider=provider,
            model=model,
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            scope="none",
            status="bypassed",
            cache_safety_reasons=("no_provider_payload_stable_prefix_boundary",),
            created_at=timestamp,
            diagnostics={
                **diagnostics,
                **provider_diagnostics,
                **token_diagnostics,
                **target_diagnostics,
                "prefix_hash_source": "provider_payload_manifest",
            },
        )
    key = prompt_cache_key(
        scope="provider_payload_prefix",
        inputs={
            "provider": provider,
            "model": model,
            "prefix_key_tier": key_tier,
            "provider_payload_prefix_hash": prefix_hash,
            "boundary_kind": str(selected_prefix.get("boundary_kind") or ""),
            "boundary_ordinal": int(selected_prefix.get("boundary_ordinal") or 0),
            "boundary_content_hash": str(selected_prefix.get("boundary_content_hash") or ""),
            "transport_contract_hash": str(boundary.get("transport_contract_hash") or ""),
            "stable_transport_contract_hash": str(boundary.get("stable_transport_contract_hash") or ""),
            "tool_catalog_hash": str(boundary.get("tool_catalog_hash") or ""),
            "stable_tool_catalog_hash": str(boundary.get("stable_tool_catalog_hash") or ""),
            "cache_sensitive_params_hash": str(boundary.get("cache_sensitive_params_hash") or ""),
        },
    )
    return PromptCacheRecord(
        cache_record_id=f"pcache:{segment_map.request_id}",
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
            "prefix_key_tier": key_tier,
            "prefix_hash_source": "provider_payload_manifest",
            "provider_payload_stable_segment_count": int(selected_prefix.get("segment_count") or 0),
            "provider_payload_message_prefix_segment_count": int(selected_prefix.get("message_segment_count") or 0),
            "provider_payload_tool_prefix_segment_count": int(selected_prefix.get("tool_segment_count") or 0),
            "stable_prefix_segment_count": int(selected_prefix.get("segment_count") or 0),
            "stable_message_prefix_segment_count": int(selected_prefix.get("message_segment_count") or 0),
            "stable_prefix_predicted_tokens": int(token_diagnostics.get("provider_payload_prefix_predicted_tokens") or 0),
            "expected_cache_read_prefix_predicted_tokens": int(token_diagnostics.get("expected_cache_read_prefix_predicted_tokens") or 0),
            "context_append_promoted_to_next_context_memory_prefix": int(
                token_diagnostics.get("context_append_prefix_predicted_tokens") or 0
            )
            > 0,
        },
    )


def _prefix_predicted_tokens_for_tier(diagnostics: dict[str, Any], *, tier: str) -> int:
    normalized = str(tier or "").strip()
    if normalized == "task":
        return int(diagnostics.get("task_prefix_predicted_tokens") or 0)
    if normalized == "session":
        return int(diagnostics.get("session_prefix_predicted_tokens") or 0)
    if normalized == "provider_global":
        return int(diagnostics.get("provider_global_prefix_predicted_tokens") or 0)
    return 0


def _provider_payload_prefix_token_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    diagnostics: dict[str, Any],
    tier: str,
    selected_prefix: dict[str, Any] | None = None,
) -> dict[str, int]:
    message_tokens = _prefix_predicted_tokens_for_tier(diagnostics, tier=tier)
    context_append_tokens = _context_append_prefix_predicted_tokens(segment_map, tier=tier)
    expected_cache_read_tokens = max(0, message_tokens - context_append_tokens)
    selected = dict(selected_prefix or {})
    tool_prefix_selected = int(selected.get("tool_segment_count") or 0) > 0
    tool_tokens = (
        _provider_payload_tool_prefix_predicted_tokens(segment_map, tier=tier)
        if tool_prefix_selected
        else 0
    )
    sidecar_tool_schema_tokens = _provider_sidecar_tool_schema_predicted_tokens(segment_map)
    stable_transport_contract_tokens = sidecar_tool_schema_tokens
    return {
        "provider_payload_message_prefix_predicted_tokens": message_tokens,
        "provider_payload_tool_prefix_predicted_tokens": tool_tokens,
        "provider_sidecar_tool_schema_predicted_tokens": sidecar_tool_schema_tokens,
        "stable_transport_contract_predicted_tokens": stable_transport_contract_tokens,
        "context_append_prefix_predicted_tokens": context_append_tokens,
        "expected_cache_read_prefix_predicted_tokens": expected_cache_read_tokens,
        "provider_payload_tool_prefix_transport_selected": int(tool_prefix_selected),
        "provider_payload_prefix_predicted_tokens": message_tokens + tool_tokens,
        "provider_payload_physical_contract_predicted_tokens": message_tokens + tool_tokens + stable_transport_contract_tokens,
    }


def _context_append_prefix_predicted_tokens(segment_map: PromptSegmentMap, *, tier: str) -> int:
    total = 0
    for segment in tuple(segment_map.segments or ()):
        metadata = dict(getattr(segment, "metadata", None) or {})
        if str(metadata.get("context_cache_section") or metadata.get("context_assembly_section") or "") != "context_append":
            continue
        if not is_prefix_eligible_for_tier(
            cache_role=getattr(segment, "cache_role", ""),
            prefix_tier=getattr(segment, "prefix_tier", ""),
            tier=tier,
        ):
            continue
        total += int(getattr(segment, "predicted_tokens", 0) or 0)
    return total


def _provider_payload_tool_prefix_predicted_tokens(segment_map: PromptSegmentMap, *, tier: str) -> int:
    total = 0
    for segment in tuple(segment_map.segments or ()):
        metadata = dict(getattr(segment, "metadata", None) or {})
        if not _is_provider_payload_tool_prefix_segment(segment, metadata=metadata):
            continue
        if not is_prefix_eligible_for_tier(
            cache_role=getattr(segment, "cache_role", ""),
            prefix_tier=getattr(segment, "prefix_tier", ""),
            tier=tier,
        ):
            continue
        total += int(getattr(segment, "predicted_tokens", 0) or 0)
    return total


def _provider_sidecar_tool_schema_predicted_tokens(segment_map: PromptSegmentMap) -> int:
    total = 0
    for segment in tuple(segment_map.segments or ()):
        if not _is_provider_payload_tool_sidecar_segment(segment):
            continue
        total += int(getattr(segment, "predicted_tokens", 0) or 0)
    return total


def _is_provider_payload_tool_prefix_segment(segment: Any, *, metadata: dict[str, Any]) -> bool:
    if str(getattr(segment, "kind", "") or "") != "native_tool_binding_schema":
        return False
    if metadata.get("provider_payload_prefix_component") is False:
        return False
    if str(metadata.get("provider_payload_transport_location") or "") == "tools":
        return True
    if str(getattr(segment, "role", "") or "") == "tool_schema":
        return True
    return str(getattr(segment, "source", "") or "") == "model_request.tools"


def _is_provider_payload_tool_sidecar_segment(segment: Any, *, metadata: dict[str, Any] | None = None) -> bool:
    if str(getattr(segment, "kind", "") or "") != "native_tool_binding_schema":
        return False
    payload = dict(metadata if metadata is not None else getattr(segment, "metadata", None) or {})
    if str(payload.get("provider_payload_transport_location") or "") != "tools" and str(getattr(segment, "source", "") or "") != "model_request.tools":
        return False
    if payload.get("provider_payload_prefix_component") is True:
        return False
    if str(payload.get("transport_sidecar_role") or "") == "native_tool_binding_schema":
        return True
    return payload.get("provider_payload_sidecar_component") is True


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in ("", None, [], {})}

