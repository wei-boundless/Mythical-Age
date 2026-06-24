from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from typing import Any

from runtime.prompt_accounting.cache_policy import is_cache_eligible_prefix, is_prefix_eligible_for_tier

from .models import ModelTokenUsageRecord, PromptSegment, PromptSegmentMap
from .provider_payload_boundary import (
    provider_payload_boundary_diagnostics,
    provider_payload_cache_boundary,
    provider_payload_manifest_dict,
    provider_payload_selected_tier,
    provider_payload_tier_prefix,
)
from .stability_models import PromptStabilityReport, PromptStabilitySection


class PromptStabilityReporter:
    def build(
        self,
        *,
        segment_map: PromptSegmentMap,
        previous_report: PromptStabilityReport | None = None,
        model_request: Any | None = None,
        cache_record: Any | None = None,
        created_at: float | None = None,
    ) -> PromptStabilityReport:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        provider_sections = _provider_payload_sections(model_request=model_request, segment_map=segment_map)
        if provider_sections is not None:
            stable_sections, volatile_sections = provider_sections
        else:
            stable_segments, volatile_segments = _split_segments(segment_map.segments)
            stable_sections = tuple(_section_from_segment(segment) for segment in stable_segments)
            volatile_sections = tuple(_section_from_segment(segment) for segment in volatile_segments)
        tier_prefixes = _tier_prefixes(segment_map.segments)
        dynamic_summary = _dynamic_param_summary(model_request=model_request, segment_map=segment_map)
        dynamic_hash = _stable_hash(dynamic_summary)
        context_window = _context_window_summary(model_request=model_request, segment_map=segment_map)
        changed_sections, first_changed = _diff_stable_sections(previous_report, stable_sections)
        dynamic_param_diff = _dynamic_param_diff(previous_report, dynamic_summary)
        dynamic_params_changed = bool(dynamic_param_diff)
        stable_prefix_hash = str(
            getattr(model_request, "provider_payload_prefix_hash", "")
            or getattr(model_request, "stable_prefix_hash", "")
            or getattr(cache_record, "prefix_hash", "")
            or _stable_hash([section.content_hash for section in stable_sections])
        )
        provider_global_prefix_hash = str(
            getattr(model_request, "provider_payload_provider_global_prefix_hash", "")
            or getattr(model_request, "provider_global_prefix_hash", "")
            or dict(getattr(cache_record, "diagnostics", {}) or {}).get("provider_global_prefix_hash")
            or _prefix_hash(tier_prefixes["provider_global"])
        )
        session_prefix_hash = str(
            getattr(model_request, "provider_payload_session_prefix_hash", "")
            or getattr(model_request, "session_prefix_hash", "")
            or dict(getattr(cache_record, "diagnostics", {}) or {}).get("session_prefix_hash")
            or _prefix_hash(tier_prefixes["session"])
        )
        task_prefix_hash = str(
            getattr(model_request, "provider_payload_task_prefix_hash", "")
            or getattr(model_request, "task_prefix_hash", "")
            or dict(getattr(cache_record, "diagnostics", {}) or {}).get("task_prefix_hash")
            or _prefix_hash(tier_prefixes["task"])
        )
        diagnostics = _diagnostics(
            stable_sections=stable_sections,
            previous_report=previous_report,
            first_changed=first_changed,
            dynamic_param_diff=dynamic_param_diff,
            dynamic_params_changed=dynamic_params_changed,
            model_request=model_request,
        )
        return PromptStabilityReport(
            report_id=f"pstability:{segment_map.request_id}",
            request_id=segment_map.request_id,
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            packet_id=str(dict(segment_map.metadata or {}).get("packet_ref") or ""),
            invocation_kind=str(dict(segment_map.metadata or {}).get("source") or dict(segment_map.metadata or {}).get("call_kind") or ""),
            provider=segment_map.provider,
            model=segment_map.model,
            session_cache_key=_session_cache_key(segment_map),
            context_window_generation=1 if context_window.get("active_history_message_count") else 0,
            compaction_generation=1 if context_window.get("context_recovery_package_hash") else 0,
            stable_prefix_hash=stable_prefix_hash,
            provider_global_prefix_hash=provider_global_prefix_hash,
            session_prefix_hash=session_prefix_hash,
            task_prefix_hash=task_prefix_hash,
            stable_prefix_tokens=sum(int(section.predicted_tokens or 0) for section in stable_sections),
            provider_global_prefix_tokens=sum(int(segment.predicted_tokens or 0) for segment in tier_prefixes["provider_global"]),
            session_prefix_tokens=sum(int(segment.predicted_tokens or 0) for segment in tier_prefixes["session"]),
            task_prefix_tokens=sum(int(segment.predicted_tokens or 0) for segment in tier_prefixes["task"]),
            stable_section_count=len(stable_sections),
            volatile_token_count=sum(int(section.predicted_tokens or 0) for section in volatile_sections),
            stable_sections=stable_sections,
            volatile_sections=volatile_sections,
            dynamic_param_hash=dynamic_hash,
            dynamic_param_summary=dynamic_summary,
            previous_report_ref=previous_report.report_id if previous_report is not None else "",
            first_changed_section=first_changed,
            changed_sections=tuple(changed_sections),
            diagnostics={**diagnostics, "context_window": context_window},
            created_at=timestamp,
        )

    def with_provider_usage(
        self,
        report: PromptStabilityReport,
        usage: ModelTokenUsageRecord | None,
    ) -> PromptStabilityReport:
        if usage is None:
            return report
        cached_tokens = max(int(usage.cached_tokens or 0), int(usage.cache_read_tokens or 0))
        cache_miss_tokens = int(usage.cache_miss_tokens or 0)
        prompt_tokens = int(usage.prompt_tokens or 0)
        provider_returned_hit_miss_available = (
            str(dict(usage.diagnostics or {}).get("provider_cache_hit_rate_source") or "")
            == "provider_hit_miss_tokens"
        )
        provider_usage = {
            "usage_id": usage.usage_id,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "cache_read_tokens": int(usage.cache_read_tokens or 0),
            "cache_creation_tokens": int(usage.cache_creation_tokens or 0),
            "cache_miss_tokens": cache_miss_tokens,
            "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0,
            "provider_returned_cache_hit_rate": round(cached_tokens / (cached_tokens + cache_miss_tokens), 4)
            if provider_returned_hit_miss_available and (cached_tokens + cache_miss_tokens) > 0
            else None,
        }
        likely_break_reason = _likely_break_reason_with_provider_usage(
            diagnostics=dict(report.diagnostics or {}),
            cached_tokens=cached_tokens,
            prompt_tokens=prompt_tokens,
        )
        return replace(
            report,
            provider_usage=provider_usage,
            diagnostics={
                **dict(report.diagnostics or {}),
                "provider_usage_ref": usage.usage_id,
                "likely_break_reason": likely_break_reason,
            },
        )


def _split_segments(segments: tuple[PromptSegment, ...]) -> tuple[list[PromptSegment], list[PromptSegment]]:
    stable: list[PromptSegment] = []
    volatile: list[PromptSegment] = []
    in_prefix = True
    for segment in segments:
        if in_prefix and is_cache_eligible_prefix(
            cache_role=segment.cache_role,
            prefix_tier=getattr(segment, "prefix_tier", ""),
        ):
            stable.append(segment)
            continue
        in_prefix = False
        volatile.append(segment)
    return stable, volatile


def _section_from_segment(segment: PromptSegment) -> PromptStabilitySection:
    metadata = dict(segment.metadata or {})
    return PromptStabilitySection(
        section_id=segment.segment_id,
        kind=segment.kind,
        ordinal=segment.ordinal,
        source_ref=segment.source,
        cache_role=segment.cache_role,
        prefix_tier=str(getattr(segment, "prefix_tier", "") or "volatile"),
        content_hash=segment.content_hash,
        predicted_tokens=int(segment.predicted_tokens or 0),
        volatility_reason=str(metadata.get("volatility_reason") or metadata.get("cache_impact") or ""),
    )


def _provider_payload_sections(
    *,
    model_request: Any | None,
    segment_map: PromptSegmentMap,
) -> tuple[tuple[PromptStabilitySection, ...], tuple[PromptStabilitySection, ...]] | None:
    manifest = provider_payload_manifest_dict(model_request)
    if not manifest:
        return None
    segments = [dict(item) for item in list(manifest.get("segments") or []) if isinstance(item, dict)]
    if not segments:
        return None
    by_id = {str(item.get("segment_id") or ""): item for item in segments}
    boundary = provider_payload_cache_boundary(model_request)
    tier = provider_payload_selected_tier(boundary)
    selected_prefix = provider_payload_tier_prefix(boundary, tier)
    stable_ids = [str(item) for item in list(selected_prefix.get("segment_ids") or []) if str(item or "")]
    stable_set = set(stable_ids)
    token_lookup = _provider_payload_token_lookup(segment_map)
    stable_sections = tuple(
        _section_from_provider_payload_segment(
            by_id[segment_id],
            ordinal=index + 1,
            token_lookup=token_lookup,
        )
        for index, segment_id in enumerate(stable_ids)
        if segment_id in by_id
    )
    volatile_sections = tuple(
        _section_from_provider_payload_segment(
            item,
            ordinal=_int(item.get("ordinal")),
            token_lookup=token_lookup,
        )
        for item in sorted(segments, key=lambda payload: int(payload.get("ordinal") or 0))
        if str(item.get("segment_id") or "") not in stable_set
    )
    return stable_sections, volatile_sections


def _section_from_provider_payload_segment(
    payload: dict[str, Any],
    *,
    ordinal: int,
    token_lookup: dict[tuple[str, str], int],
) -> PromptStabilitySection:
    metadata = dict(payload.get("metadata") or {})
    kind = str(payload.get("kind") or "")
    content_hash = str(payload.get("content_hash") or "")
    return PromptStabilitySection(
        section_id=str(payload.get("segment_id") or ""),
        kind=kind,
        ordinal=max(0, int(ordinal or 0)),
        source_ref=str(payload.get("source_ref") or ""),
        cache_role=str(payload.get("cache_role") or "volatile"),
        prefix_tier=str(payload.get("prefix_tier") or "volatile"),
        content_hash=content_hash,
        predicted_tokens=int(token_lookup.get((kind, content_hash)) or token_lookup.get(("", content_hash)) or 0),
        volatility_reason=str(metadata.get("volatility_reason") or metadata.get("cache_impact") or ""),
    )


def _provider_payload_token_lookup(segment_map: PromptSegmentMap) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for segment in list(segment_map.segments or []):
        content_hash = str(segment.content_hash or "")
        if not content_hash:
            continue
        result[(str(segment.kind or ""), content_hash)] = int(segment.predicted_tokens or 0)
        result.setdefault(("", content_hash), int(segment.predicted_tokens or 0))
    return result


def _dynamic_param_summary(*, model_request: Any | None, segment_map: PromptSegmentMap) -> dict[str, Any]:
    tools = list(getattr(model_request, "tools", ()) or [])
    cache_policy = getattr(model_request, "cache_policy", None)
    diagnostics = dict(getattr(model_request, "diagnostics", {}) or {})
    cache_relevant_params = dict(diagnostics.get("cache_relevant_params") or {})
    provider_boundary = provider_payload_cache_boundary(model_request)
    return _drop_empty(
        {
            "provider": segment_map.provider,
            "model": segment_map.model,
            "request_params": cache_relevant_params,
            "tool_count": len(tools),
            "tools_hash": _stable_hash(tools) if tools else "",
            "tool_catalog_hash": str(provider_boundary.get("tool_catalog_hash") or ""),
            "cache_sensitive_params_hash": str(provider_boundary.get("cache_sensitive_params_hash") or ""),
            "cache_policy": cache_policy.to_dict() if hasattr(cache_policy, "to_dict") else {},
        }
    )


def _context_window_summary(*, model_request: Any | None, segment_map: PromptSegmentMap) -> dict[str, Any]:
    diagnostics = dict(getattr(model_request, "diagnostics", {}) or {})
    if not diagnostics:
        diagnostics = dict(segment_map.metadata or {})
    prompt_manifest = dict(diagnostics.get("prompt_manifest") or {})
    context_window = dict(prompt_manifest.get("context_window") or {})
    return _drop_empty(
        {
            "context_recovery_package_hash": str(context_window.get("context_recovery_package_hash") or ""),
            "context_recovery_package_present": bool(context_window.get("context_recovery_package_present") or False),
            "context_recovery_package_source": str(context_window.get("context_recovery_package_source") or ""),
            "context_recovery_package_covered_message_count": _int(context_window.get("context_recovery_package_covered_message_count")),
            "context_recovery_package_covered_event_offset_end": _int(context_window.get("context_recovery_package_covered_event_offset_end")),
            "raw_history_message_count": _int(context_window.get("raw_history_message_count")),
            "active_history_message_count": _int(context_window.get("active_history_message_count")),
            "budget_report": dict(context_window.get("budget_report") or {}),
            "dynamic_context_diagnostics": dict(context_window.get("dynamic_context_diagnostics") or {}),
        }
    )


def _diff_stable_sections(
    previous_report: PromptStabilityReport | None,
    current_sections: tuple[PromptStabilitySection, ...],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if previous_report is None:
        return [], {}
    previous_sections = list(previous_report.stable_sections)
    changed: list[dict[str, Any]] = []
    max_len = max(len(previous_sections), len(current_sections))
    for index in range(max_len):
        previous = previous_sections[index] if index < len(previous_sections) else None
        current = current_sections[index] if index < len(current_sections) else None
        if previous is None or current is None:
            item = {
                "ordinal": index + 1,
                "change_type": "section_added" if current is not None else "section_removed",
                "previous_section_id": previous.section_id if previous is not None else "",
                "current_section_id": current.section_id if current is not None else "",
                "previous_kind": previous.kind if previous is not None else "",
                "current_kind": current.kind if current is not None else "",
            }
            changed.append(item)
            continue
        if (
            previous.cache_role,
            previous.content_hash,
        ) != (
            current.cache_role,
            current.content_hash,
        ):
            changed.append(
                {
                    "ordinal": current.ordinal,
                    "change_type": "section_changed",
                    "previous_section_id": previous.section_id,
                    "current_section_id": current.section_id,
                    "previous_kind": previous.kind,
                    "current_kind": current.kind,
                    "previous_source_ref": previous.source_ref,
                    "current_source_ref": current.source_ref,
                    "previous_content_hash": previous.content_hash,
                    "current_content_hash": current.content_hash,
                }
            )
    return changed, changed[0] if changed else {}


def _diagnostics(
    *,
    stable_sections: tuple[PromptStabilitySection, ...],
    previous_report: PromptStabilityReport | None,
    first_changed: dict[str, Any],
    dynamic_param_diff: dict[str, Any],
    dynamic_params_changed: bool,
    model_request: Any | None,
) -> dict[str, Any]:
    stable_prefix_changed = bool(first_changed)
    return _drop_empty(
        {
            "has_previous_report": previous_report is not None,
            "stable_prefix_changed": stable_prefix_changed,
            "dynamic_params_changed": dynamic_params_changed,
            "dynamic_param_diff": dynamic_param_diff,
            "likely_break_reason": _likely_break_reason(
                stable_prefix_changed=stable_prefix_changed,
                dynamic_params_changed=dynamic_params_changed,
            ),
            "provider_payload": provider_payload_boundary_diagnostics(
                model_request=model_request,
                boundary=provider_payload_cache_boundary(model_request),
            ),
        }
    )


def _dynamic_param_diff(
    previous_report: PromptStabilityReport | None,
    current_summary: dict[str, Any],
) -> dict[str, Any]:
    if previous_report is None:
        return {}
    return _top_level_diff(dict(previous_report.dynamic_param_summary or {}), dict(current_summary or {}))


def _top_level_diff(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key in sorted(set(previous) | set(current)):
        previous_value = previous.get(key)
        current_value = current.get(key)
        if _json_stable(previous_value) == _json_stable(current_value):
            continue
        diff[str(key)] = {
            "previous": previous_value,
            "current": current_value,
        }
    return diff


def _likely_break_reason(*, stable_prefix_changed: bool, dynamic_params_changed: bool) -> str:
    if dynamic_params_changed:
        return "dynamic_request_params_changed"
    if stable_prefix_changed:
        return "stable_prefix_changed"
    return "stable_prefix_unchanged"


def _likely_break_reason_with_provider_usage(
    *,
    diagnostics: dict[str, Any],
    cached_tokens: int,
    prompt_tokens: int,
) -> str:
    if int(cached_tokens or 0) > 0:
        return "provider_cache_hit"
    existing = str(diagnostics.get("likely_break_reason") or "")
    if existing and existing != "stable_prefix_unchanged":
        return existing
    if int(prompt_tokens or 0) > 0:
        return "provider_cache_cold_or_expired"
    return existing or "stable_prefix_unchanged"


def _tier_prefixes(segments: tuple[PromptSegment, ...]) -> dict[str, list[PromptSegment]]:
    result: dict[str, list[PromptSegment]] = {}
    for tier in ("provider_global", "session", "task"):
        items: list[PromptSegment] = []
        for segment in segments:
            if is_prefix_eligible_for_tier(
                cache_role=segment.cache_role,
                prefix_tier=getattr(segment, "prefix_tier", ""),
                tier=tier,
            ):
                items.append(segment)
                continue
            break
        result[tier] = items
    return result


def _session_cache_key(segment_map: PromptSegmentMap) -> str:
    if segment_map.session_id:
        return f"session:{segment_map.session_id}"
    if segment_map.task_run_id:
        return f"task:{segment_map.task_run_id}"
    return f"request:{segment_map.request_id}"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _prefix_hash(segments: list[PromptSegment]) -> str:
    if not segments:
        return ""
    return _stable_hash([segment.content_hash for segment in segments])


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}

