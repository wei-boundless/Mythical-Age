from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from typing import Any

from .models import ModelTokenUsageRecord, PromptSegment, PromptSegmentMap
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
        stable_segments, volatile_segments = _split_segments(segment_map.segments)
        stable_sections = tuple(_section_from_segment(segment) for segment in stable_segments)
        volatile_sections = tuple(_section_from_segment(segment) for segment in volatile_segments)
        dynamic_summary = _dynamic_param_summary(model_request=model_request, segment_map=segment_map)
        dynamic_hash = _stable_hash(dynamic_summary)
        dynamic_param_diff = _diff_dynamic_params(previous_report, dynamic_summary)
        context_window = _context_window_summary(model_request=model_request, segment_map=segment_map)
        changed_sections, first_changed = _diff_stable_sections(previous_report, stable_sections)
        stable_prefix_hash = str(
            getattr(model_request, "stable_prefix_hash", "")
            or getattr(cache_record, "prefix_hash", "")
            or _stable_hash([section.content_hash for section in stable_sections])
        )
        diagnostics = _diagnostics(
            stable_sections=stable_sections,
            previous_report=previous_report,
            first_changed=first_changed,
            dynamic_param_hash=dynamic_hash,
            dynamic_param_diff=dynamic_param_diff,
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
            context_window_generation=1 if context_window.get("replacement_history_ref") else 0,
            compaction_generation=1 if context_window.get("compressed_summary_hash") else 0,
            stable_prefix_hash=stable_prefix_hash,
            stable_prefix_tokens=sum(int(section.predicted_tokens or 0) for section in stable_sections),
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
        prompt_tokens = int(usage.prompt_tokens or 0)
        provider_usage = {
            "usage_id": usage.usage_id,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "cache_read_tokens": int(usage.cache_read_tokens or 0),
            "cache_creation_tokens": int(usage.cache_creation_tokens or 0),
            "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0,
        }
        reason = _likely_reason(report=report, provider_usage=provider_usage)
        return replace(
            report,
            provider_usage=provider_usage,
            diagnostics={
                **dict(report.diagnostics or {}),
                "provider_usage_ref": usage.usage_id,
                "likely_break_reason": reason,
            },
        )


def _split_segments(segments: tuple[PromptSegment, ...]) -> tuple[list[PromptSegment], list[PromptSegment]]:
    stable: list[PromptSegment] = []
    volatile: list[PromptSegment] = []
    in_prefix = True
    for segment in segments:
        if in_prefix and segment.cache_role in {"cacheable_prefix", "session_stable"}:
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
        content_hash=segment.content_hash,
        predicted_tokens=int(segment.predicted_tokens or 0),
        volatility_reason=str(metadata.get("volatility_reason") or metadata.get("cache_impact") or ""),
    )


def _dynamic_param_summary(*, model_request: Any | None, segment_map: PromptSegmentMap) -> dict[str, Any]:
    tools = list(getattr(model_request, "tools", ()) or [])
    cache_policy = getattr(model_request, "cache_policy", None)
    diagnostics = dict(getattr(model_request, "diagnostics", {}) or {})
    cache_relevant_params = dict(diagnostics.get("cache_relevant_params") or {})
    return _drop_empty(
        {
            "provider": segment_map.provider,
            "model": segment_map.model,
            "request_params": cache_relevant_params,
            "tool_count": len(tools),
            "tools_hash": _stable_hash(tools) if tools else "",
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
            "compressed_summary_hash": str(context_window.get("compressed_summary_hash") or ""),
            "compressed_summary_present": bool(context_window.get("compressed_summary_present") or False),
            "replacement_history_ref": str(context_window.get("replacement_history_ref") or ""),
            "replacement_history_present": bool(context_window.get("replacement_history_present") or False),
            "raw_history_message_count": _int(context_window.get("raw_history_message_count")),
            "recent_history_message_count": _int(context_window.get("recent_history_message_count")),
            "omitted_history_message_count": _int(context_window.get("omitted_history_message_count")),
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
            previous.kind,
            previous.source_ref,
            previous.cache_role,
            previous.content_hash,
        ) != (
            current.kind,
            current.source_ref,
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
    dynamic_param_hash: str,
    dynamic_param_diff: dict[str, Any],
) -> dict[str, Any]:
    reason = ""
    if not stable_sections:
        reason = "no_stable_prefix_boundary"
    elif first_changed:
        ordinal = int(first_changed.get("ordinal") or 0)
        reason = "global_static_changed" if ordinal <= 1 else "stable_section_changed"
    elif previous_report is not None and previous_report.dynamic_param_hash and previous_report.dynamic_param_hash != dynamic_param_hash:
        reason = "dynamic_request_params_changed"
    elif previous_report is None:
        reason = "no_previous_report"
    return _drop_empty(
        {
            "likely_break_reason": reason,
            "has_previous_report": previous_report is not None,
            "stable_prefix_changed": bool(first_changed),
            "dynamic_params_changed": bool(
                previous_report is not None
                and previous_report.dynamic_param_hash
                and previous_report.dynamic_param_hash != dynamic_param_hash
            ),
            "dynamic_param_diff": dynamic_param_diff,
        }
    )


def _diff_dynamic_params(
    previous_report: PromptStabilityReport | None,
    current_summary: dict[str, Any],
) -> dict[str, Any]:
    if previous_report is None:
        return {}
    previous_summary = dict(previous_report.dynamic_param_summary or {})
    changes: dict[str, Any] = {}
    for key in sorted(set(previous_summary) | set(current_summary)):
        previous_value = previous_summary.get(key)
        current_value = current_summary.get(key)
        if _json_stable(previous_value) != _json_stable(current_value):
            changes[key] = {
                "previous": previous_value,
                "current": current_value,
            }
    return changes


def _likely_reason(*, report: PromptStabilityReport, provider_usage: dict[str, Any]) -> str:
    cached = int(provider_usage.get("cached_tokens") or 0)
    if cached > 0:
        return "provider_cache_hit"
    existing = str(dict(report.diagnostics or {}).get("likely_break_reason") or "")
    if existing and existing != "no_previous_report":
        return existing
    if not provider_usage:
        return "provider_usage_missing"
    return "provider_cache_cold_or_expired"


def _session_cache_key(segment_map: PromptSegmentMap) -> str:
    if segment_map.session_id:
        return f"session:{segment_map.session_id}"
    if segment_map.task_run_id:
        return f"task:{segment_map.task_run_id}"
    return f"request:{segment_map.request_id}"


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


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
