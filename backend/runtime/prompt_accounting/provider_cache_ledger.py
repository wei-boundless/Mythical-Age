from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .models import ModelTokenUsageRecord, PromptCacheRecord


ProviderCacheLedgerStatus = Literal[
    "cold_start",
    "hit",
    "provider_under_read",
    "local_physical_break",
    "miss",
    "bypassed",
]
ProviderCacheBreakStatus = Literal[
    "no_local_physical_break",
    "local_physical_break",
    "unmeasured",
]


@dataclass(frozen=True, slots=True)
class ProviderCacheLedgerRecord:
    ledger_id: str
    request_id: str
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    provider: str = ""
    model: str = ""
    provider_lane: str = ""
    physical_prefix_frame_id: str = ""
    physical_prefix_previous_frame_id: str = ""
    physical_prefix_frame_source_request_id: str = ""
    physical_prefix_frame_turn_id: str = ""
    physical_payload_family_hash: str = ""
    physical_payload_family: dict[str, Any] = field(default_factory=dict)
    physical_cache_spine_hash: str = ""
    physical_cache_spine_message_subtotal_hash: str = ""
    physical_cache_spine_segment_ids: tuple[str, ...] = ()
    physical_cache_spine_segment_kinds: tuple[str, ...] = ()
    physical_cache_spine_transport_locations: tuple[str, ...] = ()
    physical_cache_spine_roles: tuple[str, ...] = ()
    physical_cache_spine_prefix_families: tuple[str, ...] = ()
    physical_cache_spine_boundary_participations: tuple[str, ...] = ()
    physical_cache_spine_predicted_tokens: int = 0
    physical_cache_spine_provider_scaled_tokens: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    miss_tokens: int = 0
    hit_rate: float = 0.0
    expected_cacheable_tokens: int = 0
    current_context_append_tokens: int = 0
    dynamic_tail_tokens: int = 0
    tool_schema_blocker_tokens: int = 0
    provider_under_read_tokens: int = 0
    non_spine_prompt_tokens: int = 0
    cache_status: ProviderCacheLedgerStatus = "bypassed"
    break_status: ProviderCacheBreakStatus = "unmeasured"
    first_break_segment: dict[str, Any] = field(default_factory=dict)
    provider_usage_source: str = ""
    provider_payload_manifest_ref: str = ""
    token_usage_ref: str = ""
    prompt_cache_record_ref: str = ""
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.provider_cache_bus"
    ledger_version: str = "provider_cache_bus.v1"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["physical_cache_spine_segment_ids"] = list(self.physical_cache_spine_segment_ids)
        payload["physical_cache_spine_segment_kinds"] = list(self.physical_cache_spine_segment_kinds)
        payload["physical_cache_spine_transport_locations"] = list(self.physical_cache_spine_transport_locations)
        payload["physical_cache_spine_roles"] = list(self.physical_cache_spine_roles)
        payload["physical_cache_spine_prefix_families"] = list(self.physical_cache_spine_prefix_families)
        payload["physical_cache_spine_boundary_participations"] = list(self.physical_cache_spine_boundary_participations)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderCacheLedgerRecord":
        return cls(
            ledger_id=str(payload.get("ledger_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            provider_lane=str(payload.get("provider_lane") or ""),
            physical_prefix_frame_id=str(payload.get("physical_prefix_frame_id") or ""),
            physical_prefix_previous_frame_id=str(payload.get("physical_prefix_previous_frame_id") or ""),
            physical_prefix_frame_source_request_id=str(payload.get("physical_prefix_frame_source_request_id") or ""),
            physical_prefix_frame_turn_id=str(payload.get("physical_prefix_frame_turn_id") or ""),
            physical_payload_family_hash=str(payload.get("physical_payload_family_hash") or ""),
            physical_payload_family=dict(payload.get("physical_payload_family") or {}),
            physical_cache_spine_hash=str(payload.get("physical_cache_spine_hash") or ""),
            physical_cache_spine_message_subtotal_hash=str(payload.get("physical_cache_spine_message_subtotal_hash") or ""),
            physical_cache_spine_segment_ids=tuple(str(item) for item in list(payload.get("physical_cache_spine_segment_ids") or [])),
            physical_cache_spine_segment_kinds=tuple(str(item) for item in list(payload.get("physical_cache_spine_segment_kinds") or [])),
            physical_cache_spine_transport_locations=tuple(str(item) for item in list(payload.get("physical_cache_spine_transport_locations") or [])),
            physical_cache_spine_roles=tuple(str(item) for item in list(payload.get("physical_cache_spine_roles") or [])),
            physical_cache_spine_prefix_families=tuple(str(item) for item in list(payload.get("physical_cache_spine_prefix_families") or [])),
            physical_cache_spine_boundary_participations=tuple(str(item) for item in list(payload.get("physical_cache_spine_boundary_participations") or [])),
            physical_cache_spine_predicted_tokens=_int(payload.get("physical_cache_spine_predicted_tokens")),
            physical_cache_spine_provider_scaled_tokens=_int(payload.get("physical_cache_spine_provider_scaled_tokens")),
            prompt_tokens=_int(payload.get("prompt_tokens")),
            cached_tokens=_int(payload.get("cached_tokens")),
            miss_tokens=_int(payload.get("miss_tokens")),
            hit_rate=_float(payload.get("hit_rate")),
            expected_cacheable_tokens=_int(payload.get("expected_cacheable_tokens")),
            current_context_append_tokens=_int(payload.get("current_context_append_tokens")),
            dynamic_tail_tokens=_int(payload.get("dynamic_tail_tokens")),
            tool_schema_blocker_tokens=_int(payload.get("tool_schema_blocker_tokens")),
            provider_under_read_tokens=_int(payload.get("provider_under_read_tokens")),
            non_spine_prompt_tokens=_int(payload.get("non_spine_prompt_tokens")),
            cache_status=_cache_status(payload.get("cache_status")),
            break_status=_break_status(payload.get("break_status")),
            first_break_segment=dict(payload.get("first_break_segment") or {}),
            provider_usage_source=str(payload.get("provider_usage_source") or ""),
            provider_payload_manifest_ref=str(payload.get("provider_payload_manifest_ref") or ""),
            token_usage_ref=str(payload.get("token_usage_ref") or ""),
            prompt_cache_record_ref=str(payload.get("prompt_cache_record_ref") or ""),
            created_at=_float(payload.get("created_at")),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.provider_cache_bus"),
            ledger_version=str(payload.get("ledger_version") or "provider_cache_bus.v1"),
        )


def build_provider_cache_ledger_record(
    *,
    cache_record: PromptCacheRecord,
    provider_usage: ModelTokenUsageRecord,
    previous_cache_records: list[PromptCacheRecord] | tuple[PromptCacheRecord, ...] = (),
    created_at: float | None = None,
) -> ProviderCacheLedgerRecord:
    diagnostics = dict(cache_record.diagnostics or {})
    usage_diagnostics = dict(provider_usage.diagnostics or {})
    selected_prefix = dict(diagnostics.get("selected_provider_payload_prefix") or {})
    prefix_segments = _prefix_segments(selected_prefix, diagnostics)
    prompt_tokens = int(provider_usage.prompt_tokens or diagnostics.get("provider_prompt_tokens") or 0)
    cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
    miss_tokens = int(provider_usage.cache_miss_tokens or diagnostics.get("provider_cache_miss_tokens") or 0)
    family_hash = str(
        diagnostics.get("physical_payload_family_hash")
        or usage_diagnostics.get("physical_payload_family_hash")
        or ""
    )
    spine_hash = str(
        diagnostics.get("physical_cache_spine_hash")
        or diagnostics.get("provider_payload_prefix_hash")
        or cache_record.prefix_hash
        or ""
    )
    prefix_cache_health = dict(diagnostics.get("provider_prefix_cache_health") or {})
    break_status, first_break_segment = _break_status_from_diagnostics(diagnostics)
    prior_same_family = _has_previous_same_family(
        previous_cache_records,
        current_request_id=str(provider_usage.request_id or cache_record.request_id or ""),
        physical_payload_family_hash=family_hash,
        physical_cache_spine_hash=spine_hash,
    )
    provider_under_read_tokens = int(
        prefix_cache_health.get("under_read_tokens")
        or diagnostics.get("provider_cache_read_physical_spine_under_read_tokens")
        or 0
    )
    cache_status = _ledger_cache_status(
        cache_record=cache_record,
        cached_tokens=cached_tokens,
        prompt_tokens=prompt_tokens,
        break_status=break_status,
        provider_under_read_tokens=provider_under_read_tokens,
        prior_same_family=prior_same_family,
        physical_cache_spine_hash=spine_hash,
        prefix_cache_health=prefix_cache_health,
    )
    ledger_id = f"pcledger:{provider_usage.request_id or cache_record.request_id}"
    return ProviderCacheLedgerRecord(
        ledger_id=ledger_id,
        request_id=str(provider_usage.request_id or cache_record.request_id or ""),
        run_id=str(provider_usage.run_id or cache_record.run_id or provider_usage.task_run_id or cache_record.task_run_id or ""),
        task_run_id=str(provider_usage.task_run_id or cache_record.task_run_id or ""),
        session_id=str(provider_usage.session_id or cache_record.session_id or ""),
        provider=str(provider_usage.provider or cache_record.provider or ""),
        model=str(provider_usage.model or cache_record.model or ""),
        provider_lane=str(diagnostics.get("provider_lane") or usage_diagnostics.get("provider_lane") or ""),
        physical_prefix_frame_id=str(diagnostics.get("physical_prefix_frame_id") or usage_diagnostics.get("physical_prefix_frame_id") or ""),
        physical_prefix_previous_frame_id=str(
            diagnostics.get("physical_prefix_previous_frame_id")
            or usage_diagnostics.get("physical_prefix_previous_frame_id")
            or ""
        ),
        physical_prefix_frame_source_request_id=str(
            diagnostics.get("physical_prefix_frame_source_request_id")
            or usage_diagnostics.get("physical_prefix_frame_source_request_id")
            or ""
        ),
        physical_prefix_frame_turn_id=str(
            diagnostics.get("physical_prefix_frame_turn_id")
            or usage_diagnostics.get("physical_prefix_frame_turn_id")
            or ""
        ),
        physical_payload_family_hash=family_hash,
        physical_payload_family=dict(diagnostics.get("physical_payload_family") or usage_diagnostics.get("physical_payload_family") or {}),
        physical_cache_spine_hash=spine_hash,
        physical_cache_spine_message_subtotal_hash=str(diagnostics.get("physical_cache_spine_message_subtotal_hash") or ""),
        physical_cache_spine_segment_ids=tuple(str(item.get("segment_id") or "") for item in prefix_segments if str(item.get("segment_id") or "")),
        physical_cache_spine_segment_kinds=tuple(str(item.get("kind") or "") for item in prefix_segments if str(item.get("kind") or "")),
        physical_cache_spine_transport_locations=tuple(str(item.get("transport_location") or "messages") for item in prefix_segments),
        physical_cache_spine_roles=tuple(str(item.get("role") or "") for item in prefix_segments),
        physical_cache_spine_prefix_families=tuple(str(item.get("prefix_family") or "") for item in prefix_segments),
        physical_cache_spine_boundary_participations=tuple(str(item.get("boundary_participation") or "") for item in prefix_segments),
        physical_cache_spine_predicted_tokens=int(diagnostics.get("physical_cache_spine_predicted_tokens") or 0),
        physical_cache_spine_provider_scaled_tokens=int(diagnostics.get("provider_cache_read_physical_spine_provider_scaled_tokens") or 0),
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        miss_tokens=miss_tokens,
        hit_rate=_ratio(cached_tokens, cached_tokens + miss_tokens if cached_tokens + miss_tokens > 0 else prompt_tokens),
        expected_cacheable_tokens=int(diagnostics.get("physical_cache_spine_expected_read_predicted_tokens") or diagnostics.get("physical_cache_spine_predicted_tokens") or 0),
        current_context_append_tokens=int(diagnostics.get("provider_cache_read_current_context_append_predicted_tokens") or diagnostics.get("context_append_prefix_predicted_tokens") or 0),
        dynamic_tail_tokens=int(diagnostics.get("volatile_predicted_tokens") or 0),
        tool_schema_blocker_tokens=int(diagnostics.get("provider_tool_schema_blocker_predicted_tokens") or 0),
        provider_under_read_tokens=provider_under_read_tokens,
        non_spine_prompt_tokens=int(diagnostics.get("provider_cache_read_non_expected_prompt_predicted_tokens") or 0),
        cache_status=cache_status,
        break_status=break_status,
        first_break_segment=first_break_segment,
        provider_usage_source=str(usage_diagnostics.get("provider_cache_hit_rate_source") or ""),
        provider_payload_manifest_ref=str(diagnostics.get("provider_payload_manifest_ref") or ""),
        token_usage_ref=str(provider_usage.usage_id or ""),
        prompt_cache_record_ref=str(cache_record.cache_record_id or ""),
        created_at=float(created_at if created_at is not None else provider_usage.created_at or cache_record.created_at or 0.0),
        diagnostics={
            "cache_record_status": str(cache_record.status or ""),
            "provider_cache_anchor_status": str(diagnostics.get("provider_cache_anchor_status") or ""),
            "provider_cache_read_required_coverage_status": str(diagnostics.get("provider_cache_read_required_coverage_status") or ""),
            "provider_cache_read_coverage_evidence": str(diagnostics.get("provider_cache_read_required_coverage_evidence") or ""),
            "transport_contract_hash": str(diagnostics.get("transport_contract_hash") or ""),
            "transport_contract_component_count": int(diagnostics.get("transport_contract_component_count") or 0),
            "physical_prefix_frame_status": str(diagnostics.get("physical_prefix_frame_status") or usage_diagnostics.get("physical_prefix_frame_status") or ""),
            "physical_prefix_frame_turn_id": str(diagnostics.get("physical_prefix_frame_turn_id") or usage_diagnostics.get("physical_prefix_frame_turn_id") or ""),
            "physical_prefix_frame_segment_count": int(diagnostics.get("physical_prefix_frame_segment_count") or usage_diagnostics.get("physical_prefix_frame_segment_count") or 0),
            "physical_cache_spine_expected_read_scope": str(
                diagnostics.get("physical_cache_spine_expected_read_scope")
                or "provider_message_prefix"
            ),
            "physical_cache_spine_message_predicted_tokens": int(diagnostics.get("physical_cache_spine_message_predicted_tokens") or 0),
            "physical_cache_spine_sidecar_predicted_tokens": int(diagnostics.get("physical_cache_spine_sidecar_predicted_tokens") or 0),
            "physical_cache_spine_sidecar_transport_predicted_tokens": int(
                diagnostics.get("physical_cache_spine_sidecar_transport_predicted_tokens")
                or diagnostics.get("physical_cache_spine_tool_predicted_tokens")
                or 0
            ),
            "physical_cache_spine_tool_transport_selected": int(diagnostics.get("physical_cache_spine_tool_transport_selected") or 0),
            "physical_cache_spine_first_blocker": dict(diagnostics.get("physical_cache_spine_first_blocker") or {}),
            "physical_cache_spine_blockers": list(diagnostics.get("physical_cache_spine_blockers") or []),
            "provider_prefix_cache_health": prefix_cache_health,
        },
    )


def _prefix_segments(selected_prefix: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    segments = [
        dict(item)
        for item in list(dict(selected_prefix or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    if segments:
        return sorted(segments, key=lambda item: int(item.get("ordinal") or 0))
    ids = list(diagnostics.get("physical_cache_spine_segment_ids") or [])
    return [{"segment_id": str(segment_id), "kind": "", "transport_location": ""} for segment_id in ids]


def _break_status_from_diagnostics(diagnostics: dict[str, Any]) -> tuple[ProviderCacheBreakStatus, dict[str, Any]]:
    first_missing_identity = dict(
        dict(diagnostics.get("provider_prefix_cache_health") or {}).get("first_missing_expected_prefix_identity")
        or diagnostics.get("provider_cache_read_first_missing_expected_prefix_identity")
        or {}
    )
    if first_missing_identity:
        return "local_physical_break", first_missing_identity
    first_uncovered = dict(diagnostics.get("provider_cache_read_first_uncovered_physical_spine_segment") or {})
    uncovered_count = int(diagnostics.get("provider_cache_read_uncovered_physical_spine_count") or 0)
    if first_uncovered or uncovered_count > 0:
        return "local_physical_break", first_uncovered
    if diagnostics.get("physical_cache_spine_hash") or diagnostics.get("provider_payload_prefix_hash"):
        return "no_local_physical_break", {}
    return "unmeasured", {}


def _has_previous_same_family(
    previous_cache_records: list[PromptCacheRecord] | tuple[PromptCacheRecord, ...],
    *,
    current_request_id: str,
    physical_payload_family_hash: str,
    physical_cache_spine_hash: str,
) -> bool:
    for record in tuple(previous_cache_records or ()):
        if str(getattr(record, "request_id", "") or "") == str(current_request_id or ""):
            continue
        diagnostics = dict(record.diagnostics or {})
        if physical_payload_family_hash and str(diagnostics.get("physical_payload_family_hash") or "") == physical_payload_family_hash:
            return True
        if physical_cache_spine_hash and str(diagnostics.get("physical_cache_spine_hash") or diagnostics.get("provider_payload_prefix_hash") or record.prefix_hash or "") == physical_cache_spine_hash:
            return True
    return False


def _ledger_cache_status(
    *,
    cache_record: PromptCacheRecord,
    cached_tokens: int,
    prompt_tokens: int,
    break_status: ProviderCacheBreakStatus,
    provider_under_read_tokens: int,
    prior_same_family: bool,
    physical_cache_spine_hash: str,
    prefix_cache_health: dict[str, Any],
) -> ProviderCacheLedgerStatus:
    if str(cache_record.status or "") == "bypassed" or not physical_cache_spine_hash:
        return "bypassed"
    health_verdict = str(dict(prefix_cache_health or {}).get("verdict") or "")
    if int(cached_tokens or 0) <= 0:
        return "miss" if prior_same_family else "cold_start"
    if health_verdict == "covered":
        return "hit"
    if health_verdict == "provider_under_read":
        return "provider_under_read"
    if break_status == "local_physical_break":
        return "local_physical_break"
    if int(provider_under_read_tokens or 0) > 0:
        return "provider_under_read"
    if int(prompt_tokens or 0) > 0:
        return "hit"
    return "miss"


def _ratio(numerator: int, denominator: int) -> float:
    if int(denominator or 0) <= 0:
        return 0.0
    return round(max(0, int(numerator or 0)) / max(1, int(denominator or 0)), 4)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cache_status(value: Any) -> ProviderCacheLedgerStatus:
    text = str(value or "").strip()
    if text in {"cold_start", "hit", "provider_under_read", "local_physical_break", "miss", "bypassed"}:
        return text  # type: ignore[return-value]
    return "bypassed"


def _break_status(value: Any) -> ProviderCacheBreakStatus:
    text = str(value or "").strip()
    if text in {"no_local_physical_break", "local_physical_break", "unmeasured"}:
        return text  # type: ignore[return-value]
    return "unmeasured"
