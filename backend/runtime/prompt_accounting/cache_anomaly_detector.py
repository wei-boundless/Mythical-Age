from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import ModelTokenUsageRecord, CachePlanRecord
from .provider_lane import normalize_provider_lane


@dataclass(frozen=True, slots=True)
class CacheAnomalyRecord:
    anomaly_id: str
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
    authority: str = "runtime.prompt_accounting.cache_anomaly"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CacheAnomalyRecord":
        return cls(
            anomaly_id=str(payload.get("anomaly_id") or ""),
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
            authority=str(payload.get("authority") or "runtime.prompt_accounting.cache_anomaly"),
        )


class CacheAnomalyDetector:
    def detect(
        self,
        *,
        cache_plan: CachePlanRecord,
        provider_usage: ModelTokenUsageRecord,
        previous_cache_plans: list[CachePlanRecord],
        created_at: float | None = None,
    ) -> CacheAnomalyRecord | None:
        if not cache_plan.cache_key or not cache_plan.prefix_hash:
            return None
        cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
        comparable_records = [
            record
            for record in previous_cache_plans
            if record.request_id != cache_plan.request_id
            and record.status in {"eligible", "hit", "miss"}
            and _record_scope_matches(record, cache_plan)
        ]
        repeated_prefix = [
            record
            for record in comparable_records
            if record.cache_key == cache_plan.cache_key
        ]
        latest_previous = _latest_record(comparable_records)
        prefix_cache_health = dict(dict(cache_plan.diagnostics or {}).get("provider_prefix_cache_health") or {})
        if str(prefix_cache_health.get("verdict") or "") == "provider_under_read" and repeated_prefix:
            return _build_anomaly_record(
                cache_plan=cache_plan,
                provider_usage=provider_usage,
                previous_repeated_records=repeated_prefix,
                latest_previous=latest_previous,
                reason="provider_prefix_cache_under_read",
                created_at=created_at,
                extra_diagnostics={
                    "provider_prefix_cache_health": prefix_cache_health,
                    "provider_under_read_tokens": int(prefix_cache_health.get("under_read_tokens") or 0),
                    "first_missing_expected_prefix_identity": dict(
                        prefix_cache_health.get("first_missing_expected_prefix_identity") or {}
                    ),
                },
            )
        uncovered_required = _uncovered_required_segments(cache_plan)
        if uncovered_required and repeated_prefix and _required_coverage_is_authoritative(cache_plan):
            return _build_anomaly_record(
                cache_plan=cache_plan,
                provider_usage=provider_usage,
                previous_repeated_records=repeated_prefix,
                latest_previous=latest_previous,
                reason="provider_cache_read_under_required_physical_cache_spine_boundary",
                created_at=created_at,
                extra_diagnostics={
                    "cached_tokens": cached_tokens,
                    "provider_cache_read_required_coverage_status": _diag_value(
                        dict(cache_plan.diagnostics or {}),
                        "provider_cache_read_required_coverage_status",
                    ),
                    "provider_cache_read_uncovered_required_segments": uncovered_required,
                    "provider_cache_read_required_segment_coverage": _diag_raw(
                        dict(cache_plan.diagnostics or {}),
                        "provider_cache_read_required_segment_coverage",
                    ),
                },
            )
        if cache_plan.status != "miss":
            return None
        if cached_tokens > 0:
            return None
        reason = "provider_reported_miss_for_repeated_provider_payload_prefix" if repeated_prefix else _changed_payload_reason(
            previous=latest_previous,
            current=cache_plan,
        )
        if not reason:
            return None
        return _build_anomaly_record(
            cache_plan=cache_plan,
            provider_usage=provider_usage,
            previous_repeated_records=repeated_prefix,
            latest_previous=latest_previous,
            reason=reason,
            created_at=created_at,
        )


def _build_anomaly_record(
    *,
    cache_plan: CachePlanRecord,
    provider_usage: ModelTokenUsageRecord,
    previous_repeated_records: list[CachePlanRecord],
    latest_previous: CachePlanRecord | None,
    reason: str,
    created_at: float | None,
    extra_diagnostics: dict[str, Any] | None = None,
) -> CacheAnomalyRecord:
    timestamp = time.time() if created_at is None else float(created_at or 0.0)
    return CacheAnomalyRecord(
        anomaly_id=f"cacheanomaly:{cache_plan.request_id}",
        request_id=cache_plan.request_id,
        provider=cache_plan.provider,
        model=cache_plan.model,
        run_id=cache_plan.run_id,
        task_run_id=cache_plan.task_run_id,
        session_id=cache_plan.session_id,
        cache_key=cache_plan.cache_key,
        prefix_hash=cache_plan.prefix_hash,
        reason=reason,
        created_at=timestamp,
        diagnostics={
            "provider_usage_ref": provider_usage.usage_id,
            "provider_lane": _record_provider_lane(cache_plan),
            "physical_payload_family_hash": _record_physical_payload_family_hash(cache_plan),
            "physical_payload_family": dict(dict(cache_plan.diagnostics or {}).get("physical_payload_family") or {}),
            "previous_request_ids": [record.request_id for record in previous_repeated_records[-5:]],
            "previous_comparable_request_id": latest_previous.request_id if latest_previous is not None else "",
            "boundary_segment_id": cache_plan.boundary_segment_id,
            "provider_payload": _provider_payload_diagnostics(
                previous=latest_previous,
                current=cache_plan,
            ),
            "prompt_assembly": _prompt_assembly_diagnostics(
                previous=latest_previous,
                current=cache_plan,
            ),
            **dict(extra_diagnostics or {}),
        },
    )


def _record_scope_matches(previous: CachePlanRecord, current: CachePlanRecord) -> bool:
    if previous.provider and current.provider and previous.provider != current.provider:
        return False
    if previous.model and current.model and previous.model != current.model:
        return False
    previous_lane = _record_provider_lane(previous)
    current_lane = _record_provider_lane(current)
    if previous_lane != current_lane:
        return False
    previous_family = _record_physical_payload_family_hash(previous)
    current_family = _record_physical_payload_family_hash(current)
    if (previous_family or current_family) and previous_family != current_family:
        return False
    previous_cache_scope = _record_cache_scope(previous)
    current_cache_scope = _record_cache_scope(current)
    if previous_cache_scope and current_cache_scope:
        return previous_cache_scope == current_cache_scope
    if previous.session_id and current.session_id:
        return previous.session_id == current.session_id
    if current.session_id:
        return previous.session_id == current.session_id
    if current.task_run_id:
        return previous.task_run_id == current.task_run_id
    if current.run_id:
        return previous.run_id == current.run_id
    return True


def _record_provider_lane(record: CachePlanRecord) -> str:
    diagnostics = dict(record.diagnostics or {})
    return normalize_provider_lane(diagnostics.get("provider_lane"))


def _record_physical_payload_family_hash(record: CachePlanRecord) -> str:
    diagnostics = dict(record.diagnostics or {})
    return str(diagnostics.get("physical_payload_family_hash") or "")


def _record_cache_scope(record: CachePlanRecord) -> str:
    diagnostics = dict(record.diagnostics or {})
    return str(
        diagnostics.get("provider_cache_scope_id")
        or diagnostics.get("cache_scope_id")
        or diagnostics.get("session_cache_scope_id")
        or ""
    ).strip()


def _latest_record(records: list[CachePlanRecord]) -> CachePlanRecord | None:
    if not records:
        return None
    return sorted(records, key=lambda item: float(item.created_at or 0.0))[-1]


def _uncovered_required_segments(record: CachePlanRecord) -> list[str]:
    diagnostics = dict(record.diagnostics or {})
    value = diagnostics.get("provider_cache_read_uncovered_required_segments")
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "")]
    return []


def _required_coverage_is_authoritative(record: CachePlanRecord) -> bool:
    diagnostics = dict(record.diagnostics or {})
    evidence = str(diagnostics.get("provider_cache_read_required_coverage_evidence") or "").strip()
    return bool(evidence and evidence not in {"estimated_from_local_token_scale", "unmeasured"})


def _changed_payload_reason(
    *,
    previous: CachePlanRecord | None,
    current: CachePlanRecord,
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
    if _diag_value(previous_diag, "transport_contract_hash") != _diag_value(current_diag, "transport_contract_hash"):
        return "transport_contract_changed"
    if _diag_value(previous_diag, "physical_cache_spine_hash") != _diag_value(current_diag, "physical_cache_spine_hash"):
        return "physical_cache_spine_changed"
    if _diag_list(previous_diag, "physical_cache_spine_segment_ids") != _diag_list(current_diag, "physical_cache_spine_segment_ids"):
        return "physical_cache_spine_segments_changed"
    if _diag_list(previous_diag, "physical_cache_spine_transport_locations") != _diag_list(current_diag, "physical_cache_spine_transport_locations"):
        return "physical_cache_spine_transport_locations_changed"
    if _diag_list(previous_diag, "physical_cache_spine_roles") != _diag_list(current_diag, "physical_cache_spine_roles"):
        return "physical_cache_spine_roles_changed"
    if _diag_list(previous_diag, "physical_cache_spine_prefix_families") != _diag_list(current_diag, "physical_cache_spine_prefix_families"):
        return "physical_cache_spine_prefix_families_changed"
    if _diag_list(previous_diag, "physical_cache_spine_tool_protocol_round_ids") != _diag_list(current_diag, "physical_cache_spine_tool_protocol_round_ids"):
        return "physical_cache_spine_tool_protocol_rounds_changed"
    if _diag_list(previous_diag, "physical_cache_spine_boundary_participations") != _diag_list(current_diag, "physical_cache_spine_boundary_participations"):
        return "physical_cache_spine_boundary_participations_changed"
    if _diag_value(previous_diag, "physical_cache_spine_message_subtotal_hash") != _diag_value(current_diag, "physical_cache_spine_message_subtotal_hash"):
        return "physical_cache_spine_message_changed"
    if _diag_value(previous_diag, "tool_catalog_hash") != _diag_value(current_diag, "tool_catalog_hash"):
        previous_tool_count = _diag_int(previous_diag, "physical_cache_spine_tool_segment_count")
        current_tool_count = _diag_int(current_diag, "physical_cache_spine_tool_segment_count")
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
    previous: CachePlanRecord | None,
    current: CachePlanRecord,
) -> dict[str, Any]:
    previous_diag = dict(getattr(previous, "diagnostics", {}) or {}) if previous is not None else {}
    current_diag = dict(current.diagnostics or {})
    keys = (
        "provider_payload_prefix_hash",
        "provider_payload_prefix_key_tier",
        "transport_contract_hash",
        "physical_cache_spine_hash",
        "physical_cache_spine_message_subtotal_hash",
        "transport_contract_ref",
        "tool_catalog_hash",
        "stable_tool_catalog_hash",
        "cache_sensitive_params_hash",
        "provider_params_hash",
        "tool_call_options_hash",
        "response_format_hash",
        "physical_cache_spine_tool_segment_count",
        "physical_cache_spine_message_segment_count",
        "physical_cache_spine_transport_locations",
        "physical_cache_spine_roles",
        "physical_cache_spine_tool_protocol_round_ids",
        "physical_cache_spine_tool_protocol_rounds",
        "physical_cache_spine_prefix_families",
        "physical_cache_spine_boundary_participations",
        "physical_cache_spine_first_blocker",
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
    previous: CachePlanRecord | None,
    current: CachePlanRecord,
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


def _diag_list(diagnostics: dict[str, Any], key: str) -> list[str]:
    value = _diag_raw(diagnostics, key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _diag_value(diagnostics: dict[str, Any], key: str) -> str:
    value = _diag_raw(diagnostics, key)
    return str(value or "")


def _diag_int(diagnostics: dict[str, Any], key: str) -> int:
    try:
        return int(_diag_value(diagnostics, key) or 0)
    except (TypeError, ValueError):
        return 0
