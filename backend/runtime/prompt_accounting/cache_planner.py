from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from typing import Any

from prompt_cache_policy import is_cache_eligible_prefix, is_prefix_eligible_for_tier

from .models import ModelTokenUsageRecord, PromptCacheRecord, PromptSegmentMap
from .provider_payload_boundary import (
    provider_payload_boundary_diagnostics,
    provider_payload_cache_boundary,
    provider_payload_selected_tier,
    provider_payload_tier_prefix,
)


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
        return replace(
            record,
            status=status,
            cached_tokens=cached,
            cache_read_tokens=int(usage.cache_read_tokens or 0),
            cache_creation_tokens=creation,
            cache_savings_tokens=cached,
            diagnostics={
                **dict(record.diagnostics or {}),
                "provider_usage_ref": usage.usage_id,
                "provider_cached_tokens": cached,
            },
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
        if str(segment.cache_role or "") in {"volatile", "never_cache"}
        or str(segment.prefix_tier or "") in {"volatile", "none"}
    )
    replay_stable_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "task_state_replay_entry"
        and str(segment.cache_role or "") in {"cacheable_prefix", "session_stable"}
        and str(segment.prefix_tier or "") == "task"
    )
    replay_volatile_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "task_state_replay_entry"
        and str(segment.cache_role or "") in {"volatile", "never_cache"}
    )
    read_evidence_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "read_evidence_injection"
    )
    volatile_task_state_tokens = sum(
        int(segment.predicted_tokens or 0)
        for segment in segment_map.segments
        if str(segment.kind or "") == "volatile_task_state"
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
        "volatile_task_state_predicted_tokens": volatile_task_state_tokens,
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


def _cache_read_target_diagnostics(
    *,
    segment_map: PromptSegmentMap,
    prefix_tokens: int,
    prefix_source: str,
) -> dict[str, Any]:
    total_tokens = _total_predicted_tokens(segment_map)
    estimate = _ratio(int(prefix_tokens or 0), total_tokens)
    goal = 0.9
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
    )
    target_diagnostics = _cache_read_target_diagnostics(
        segment_map=segment_map,
        prefix_tokens=int(token_diagnostics.get("provider_payload_prefix_predicted_tokens") or 0),
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
) -> dict[str, int]:
    message_tokens = _prefix_predicted_tokens_for_tier(diagnostics, tier=tier)
    tool_tokens = _provider_payload_tool_prefix_predicted_tokens(segment_map, tier=tier)
    return {
        "provider_payload_message_prefix_predicted_tokens": message_tokens,
        "provider_payload_tool_prefix_predicted_tokens": tool_tokens,
        "provider_payload_prefix_predicted_tokens": message_tokens + tool_tokens,
    }


def _provider_payload_tool_prefix_predicted_tokens(segment_map: PromptSegmentMap, *, tier: str) -> int:
    total = 0
    for segment in segment_map.segments:
        if str(segment.kind or "") != "tool_schema_catalog":
            continue
        if is_prefix_eligible_for_tier(
            cache_role=segment.cache_role,
            prefix_tier=segment.prefix_tier,
            tier=tier,
        ):
            total += int(segment.predicted_tokens or 0)
    return total


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value not in ("", None, [], {})}
