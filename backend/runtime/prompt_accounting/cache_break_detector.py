from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import ModelTokenUsageRecord, PromptCacheRecord


@dataclass(frozen=True, slots=True)
class PromptCacheBreakRecord:
    break_id: str
    request_id: str
    provider: str = ""
    model: str = ""
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    cache_key: str = ""
    prefix_hash: str = ""
    reason: str = ""
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prompt_cache_break"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptCacheBreakRecord":
        return cls(
            break_id=str(payload.get("break_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            cache_key=str(payload.get("cache_key") or ""),
            prefix_hash=str(payload.get("prefix_hash") or ""),
            reason=str(payload.get("reason") or ""),
            created_at=float(payload.get("created_at") or 0.0),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_cache_break"),
        )


class PromptCacheBreakDetector:
    def detect(
        self,
        *,
        cache_record: PromptCacheRecord,
        provider_usage: ModelTokenUsageRecord,
        previous_cache_records: list[PromptCacheRecord],
        created_at: float | None = None,
    ) -> PromptCacheBreakRecord | None:
        if not cache_record.cache_key or not cache_record.prefix_hash:
            return None
        cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
        comparable_records = [
            record
            for record in previous_cache_records
            if record.request_id != cache_record.request_id
            and record.status in {"eligible", "hit", "miss"}
            and _record_scope_matches(record, cache_record)
        ]
        repeated_prefix = [
            record
            for record in comparable_records
            if record.cache_key == cache_record.cache_key
        ]
        latest_previous = _latest_record(comparable_records)
        uncovered_required = _uncovered_required_segments(cache_record)
        if uncovered_required and repeated_prefix and _required_coverage_is_authoritative(cache_record):
            return _build_break_record(
                cache_record=cache_record,
                provider_usage=provider_usage,
                previous_repeated_records=repeated_prefix,
                latest_previous=latest_previous,
                reason="provider_cache_read_under_required_stable_boundary",
                created_at=created_at,
                extra_diagnostics={
                    "cached_tokens": cached_tokens,
                    "provider_cache_read_required_coverage_status": _diag_value(
                        dict(cache_record.diagnostics or {}),
                        "provider_cache_read_required_coverage_status",
                    ),
                    "provider_cache_read_uncovered_required_segments": uncovered_required,
                    "provider_cache_read_required_segment_coverage": _diag_raw(
                        dict(cache_record.diagnostics or {}),
                        "provider_cache_read_required_segment_coverage",
                    ),
                },
            )
        if cache_record.status != "miss":
            return None
        if cached_tokens > 0:
            return None
        reason = "provider_reported_miss_for_repeated_provider_payload_prefix" if repeated_prefix else _changed_payload_reason(
            previous=latest_previous,
            current=cache_record,
        )
        if not reason:
            return None
        return _build_break_record(
            cache_record=cache_record,
            provider_usage=provider_usage,
            previous_repeated_records=repeated_prefix,
            latest_previous=latest_previous,
            reason=reason,
            created_at=created_at,
        )


def _build_break_record(
    *,
    cache_record: PromptCacheRecord,
    provider_usage: ModelTokenUsageRecord,
    previous_repeated_records: list[PromptCacheRecord],
    latest_previous: PromptCacheRecord | None,
    reason: str,
    created_at: float | None,
    extra_diagnostics: dict[str, Any] | None = None,
) -> PromptCacheBreakRecord:
    timestamp = time.time() if created_at is None else float(created_at or 0.0)
    return PromptCacheBreakRecord(
        break_id=f"pcachebreak:{cache_record.request_id}",
        request_id=cache_record.request_id,
        provider=cache_record.provider,
        model=cache_record.model,
        run_id=cache_record.run_id,
        task_run_id=cache_record.task_run_id,
        session_id=cache_record.session_id,
        cache_key=cache_record.cache_key,
        prefix_hash=cache_record.prefix_hash,
        reason=reason,
        created_at=timestamp,
        diagnostics={
            "provider_usage_ref": provider_usage.usage_id,
            "previous_request_ids": [record.request_id for record in previous_repeated_records[-5:]],
            "previous_comparable_request_id": latest_previous.request_id if latest_previous is not None else "",
            "boundary_segment_id": cache_record.boundary_segment_id,
            "provider_payload": _provider_payload_diagnostics(
                previous=latest_previous,
                current=cache_record,
            ),
            "prompt_assembly": _prompt_assembly_diagnostics(
                previous=latest_previous,
                current=cache_record,
            ),
            **dict(extra_diagnostics or {}),
        },
    )


def _record_scope_matches(previous: PromptCacheRecord, current: PromptCacheRecord) -> bool:
    if previous.provider and current.provider and previous.provider != current.provider:
        return False
    if previous.model and current.model and previous.model != current.model:
        return False
    if current.task_run_id:
        return previous.task_run_id == current.task_run_id
    if current.run_id:
        return previous.run_id == current.run_id
    if current.session_id:
        return previous.session_id == current.session_id
    return True


def _latest_record(records: list[PromptCacheRecord]) -> PromptCacheRecord | None:
    if not records:
        return None
    return sorted(records, key=lambda item: float(item.created_at or 0.0))[-1]


def _uncovered_required_segments(record: PromptCacheRecord) -> list[str]:
    diagnostics = dict(record.diagnostics or {})
    value = diagnostics.get("provider_cache_read_uncovered_required_segments")
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "")]
    return []


def _required_coverage_is_authoritative(record: PromptCacheRecord) -> bool:
    diagnostics = dict(record.diagnostics or {})
    evidence = str(diagnostics.get("provider_cache_read_required_coverage_evidence") or "").strip()
    return bool(evidence and evidence not in {"estimated_from_local_token_scale", "unmeasured"})


def _changed_payload_reason(
    *,
    previous: PromptCacheRecord | None,
    current: PromptCacheRecord,
) -> str:
    if previous is None:
        return ""
    previous_diag = dict(previous.diagnostics or {})
    current_diag = dict(current.diagnostics or {})
    if _diag_present_on_both(previous_diag, current_diag, "assembly_request_fingerprint") and (
        _diag_value(previous_diag, "assembly_request_fingerprint")
        != _diag_value(current_diag, "assembly_request_fingerprint")
    ):
        return "prompt_assembly_request_changed"
    if _diag_present_on_both(previous_diag, current_diag, "section_fingerprint") and (
        _diag_value(previous_diag, "section_fingerprint") != _diag_value(current_diag, "section_fingerprint")
    ):
        return "prompt_section_fingerprint_changed"
    if _diag_value(previous_diag, "stable_message_prefix_hash") != _diag_value(current_diag, "stable_message_prefix_hash"):
        return "stable_message_prefix_changed"
    if _diag_value(previous_diag, "tool_catalog_hash") != _diag_value(current_diag, "tool_catalog_hash"):
        previous_tool_count = _diag_int(previous_diag, "provider_payload_tool_prefix_segment_count")
        current_tool_count = _diag_int(current_diag, "provider_payload_tool_prefix_segment_count")
        if previous_tool_count != current_tool_count:
            return "tool_count_changed"
        return "tool_schema_hash_changed"
    if _diag_value(previous_diag, "cache_sensitive_params_hash") != _diag_value(current_diag, "cache_sensitive_params_hash"):
        if _diag_value(previous_diag, "tool_call_options_hash") != _diag_value(current_diag, "tool_call_options_hash"):
            return "tool_binding_options_changed"
        if _diag_value(previous_diag, "response_format_hash") != _diag_value(current_diag, "response_format_hash"):
            return "response_format_changed"
        if _diag_value(previous_diag, "provider_params_hash") != _diag_value(current_diag, "provider_params_hash"):
            return "provider_params_changed"
        return "cache_sensitive_params_changed"
    if _diag_value(previous_diag, "provider_payload_prefix_hash") != _diag_value(current_diag, "provider_payload_prefix_hash"):
        return "provider_payload_prefix_changed"
    return ""


def _provider_payload_diagnostics(
    *,
    previous: PromptCacheRecord | None,
    current: PromptCacheRecord,
) -> dict[str, Any]:
    previous_diag = dict(getattr(previous, "diagnostics", {}) or {}) if previous is not None else {}
    current_diag = dict(current.diagnostics or {})
    keys = (
        "provider_payload_prefix_hash",
        "provider_payload_prefix_key_tier",
        "stable_message_prefix_hash",
        "tool_catalog_hash",
        "stable_tool_catalog_hash",
        "cache_sensitive_params_hash",
        "provider_params_hash",
        "tool_call_options_hash",
        "response_format_hash",
        "provider_payload_tool_prefix_segment_count",
        "provider_payload_message_prefix_segment_count",
    )
    return {
        key: {
            "previous": _diag_value(previous_diag, key),
            "current": _diag_value(current_diag, key),
        }
        for key in keys
        if _diag_value(previous_diag, key) or _diag_value(current_diag, key)
    }


def _prompt_assembly_diagnostics(
    *,
    previous: PromptCacheRecord | None,
    current: PromptCacheRecord,
) -> dict[str, Any]:
    previous_diag = dict(getattr(previous, "diagnostics", {}) or {}) if previous is not None else {}
    current_diag = dict(current.diagnostics or {})
    keys = (
        "prompt_manifest_ref",
        "assembly_request_fingerprint",
        "section_fingerprint",
        "prompt_composition_manifest_ref",
        "prompt_composition_cache_boundary_status",
        "prompt_composition_prefix_tier_sequence",
        "prompt_composition_layer_violation_count",
        "prompt_composition_segment_violation_count",
    )
    return {
        key: {
            "previous": _diag_raw(previous_diag, key),
            "current": _diag_raw(current_diag, key),
        }
        for key in keys
        if _diag_raw(previous_diag, key) not in (None, "", [], {})
        or _diag_raw(current_diag, key) not in (None, "", [], {})
    }


def _diag_present_on_both(previous: dict[str, Any], current: dict[str, Any], key: str) -> bool:
    return bool(_diag_value(previous, key)) and bool(_diag_value(current, key))


def _diag_raw(diagnostics: dict[str, Any], key: str) -> Any:
    value = diagnostics.get(key)
    if value in (None, ""):
        provider_payload = dict(diagnostics.get("provider_payload") or {})
        value = provider_payload.get(key)
    if value in (None, ""):
        prompt_assembly = dict(diagnostics.get("prompt_assembly") or {})
        value = prompt_assembly.get(key)
    return value


def _diag_value(diagnostics: dict[str, Any], key: str) -> str:
    value = _diag_raw(diagnostics, key)
    return str(value or "")


def _diag_int(diagnostics: dict[str, Any], key: str) -> int:
    try:
        return int(_diag_value(diagnostics, key) or 0)
    except (TypeError, ValueError):
        return 0
