from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from context_system.segments.declarations import (
    CONTEXT_MEMORY,
    context_segment_kind_capability,
)

from .models import CachePlanRecord, PromptSegmentMap
from .provider_lane import normalize_provider_lane
from .provider_payload_boundary import (
    provider_payload_boundary_diagnostics,
    provider_payload_cache_boundary,
    provider_payload_physical_cache_spine,
)
from .prefix_state_diff_models import PrefixStateDiffReport, PrefixStateDiffSection


PrefixStateStatus = Literal["active", "invalidated"]

MEMORY_SEGMENT_KINDS = frozenset(
    {
        "runtime_memory_context",
        "session_emphasis",
        "session_pinned_facts_context",
    }
)
MEMORY_SEGMENT_SLOTS = frozenset(
    {
        "runtime_memory_context",
    }
)
SELECTED_MEMORY_AND_TASK_STATE_SLOT = "selected_memory_and_task_state_facts"
MEMORY_SEGMENT_COMMIT_CLASSES = frozenset({"selected_memory_context"})
@dataclass(frozen=True, slots=True)
class PrefixStateRecord:
    state_id: str
    request_id: str = ""
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    packet_id: str = ""
    provider: str = ""
    model: str = ""
    invocation_kind: str = ""
    provider_lane: str = "unscoped"
    physical_payload_family_hash: str = ""
    status: PrefixStateStatus = "active"
    previous_state_ref: str = ""
    generation: int = 0
    provider_payload_prefix_hash: str = ""
    global_static_prefix_hash: str = ""
    provider_visible_context_prefix_hash: str = ""
    current_turn_tail_hash: str = ""
    never_replay_tail_hash: str = ""
    stable_prefix_hash: str = ""
    provider_global_prefix_hash: str = ""
    session_prefix_hash: str = ""
    memory_segment_hash: str = ""
    tool_catalog_hash: str = ""
    stable_tool_catalog_hash: str = ""
    cache_sensitive_params_hash: str = ""
    changed_tiers: tuple[str, ...] = ()
    changed_sections: tuple[dict[str, Any], ...] = ()
    first_changed_section: dict[str, Any] = field(default_factory=dict)
    stable_token_count: int = 0
    volatile_token_count: int = 0
    provider_cache_read_expectation_summary: dict[str, Any] = field(default_factory=dict)
    stable_section_refs: tuple[dict[str, Any], ...] = ()
    dynamic_param_hash: str = ""
    dynamic_param_summary: dict[str, Any] = field(default_factory=dict)
    reset_reason: str = ""
    reset_ref: str = ""
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prefix_state"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_tiers"] = list(self.changed_tiers)
        payload["changed_sections"] = [dict(item) for item in self.changed_sections]
        payload["first_changed_section"] = dict(self.first_changed_section)
        payload["provider_cache_read_expectation_summary"] = dict(self.provider_cache_read_expectation_summary)
        payload["stable_section_refs"] = [dict(item) for item in self.stable_section_refs]
        payload["dynamic_param_summary"] = dict(self.dynamic_param_summary)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PrefixStateRecord":
        diagnostics = dict(payload.get("diagnostics") or {})
        return cls(
            state_id=str(payload.get("state_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            packet_id=str(payload.get("packet_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            invocation_kind=str(payload.get("invocation_kind") or ""),
            provider_lane=normalize_provider_lane(payload.get("provider_lane") or diagnostics.get("provider_lane")),
            physical_payload_family_hash=str(payload.get("physical_payload_family_hash") or diagnostics.get("physical_payload_family_hash") or ""),
            status=_status(payload.get("status")),
            previous_state_ref=str(payload.get("previous_state_ref") or ""),
            generation=_int(payload.get("generation")),
            provider_payload_prefix_hash=str(payload.get("provider_payload_prefix_hash") or ""),
            global_static_prefix_hash=str(payload.get("global_static_prefix_hash") or ""),
            provider_visible_context_prefix_hash=str(payload.get("provider_visible_context_prefix_hash") or ""),
            current_turn_tail_hash=str(payload.get("current_turn_tail_hash") or ""),
            never_replay_tail_hash=str(payload.get("never_replay_tail_hash") or ""),
            stable_prefix_hash=str(payload.get("stable_prefix_hash") or ""),
            provider_global_prefix_hash=str(payload.get("provider_global_prefix_hash") or ""),
            session_prefix_hash=str(payload.get("session_prefix_hash") or ""),
            memory_segment_hash=str(payload.get("memory_segment_hash") or ""),
            tool_catalog_hash=str(payload.get("tool_catalog_hash") or ""),
            stable_tool_catalog_hash=str(payload.get("stable_tool_catalog_hash") or ""),
            cache_sensitive_params_hash=str(payload.get("cache_sensitive_params_hash") or ""),
            changed_tiers=tuple(str(item) for item in list(payload.get("changed_tiers") or []) if str(item or "")),
            changed_sections=tuple(dict(item) for item in list(payload.get("changed_sections") or []) if isinstance(item, dict)),
            first_changed_section=dict(payload.get("first_changed_section") or {}),
            stable_token_count=_int(payload.get("stable_token_count")),
            volatile_token_count=_int(payload.get("volatile_token_count")),
            provider_cache_read_expectation_summary=dict(payload.get("provider_cache_read_expectation_summary") or {}),
            stable_section_refs=tuple(dict(item) for item in list(payload.get("stable_section_refs") or []) if isinstance(item, dict)),
            dynamic_param_hash=str(payload.get("dynamic_param_hash") or ""),
            dynamic_param_summary=dict(payload.get("dynamic_param_summary") or {}),
            reset_reason=str(payload.get("reset_reason") or ""),
            reset_ref=str(payload.get("reset_ref") or ""),
            created_at=float(payload.get("created_at") or 0.0),
            diagnostics=diagnostics,
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prefix_state"),
        )


class PrefixStateReporter:
    def build(
        self,
        *,
        segment_map: PromptSegmentMap,
        diff_report: PrefixStateDiffReport,
        cache_plan: CachePlanRecord | None = None,
        provider_request: Any | None = None,
        previous_state: PrefixStateRecord | None = None,
        previous_generation: int = 0,
        created_at: float | None = None,
    ) -> PrefixStateRecord:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        boundary = provider_payload_cache_boundary(provider_request)
        physical_spine = provider_payload_physical_cache_spine(boundary)
        lane_hashes = _physical_lane_hashes(provider_request)
        invocation_kind = _invocation_kind(segment_map, diff_report=diff_report)
        provider_lane = _provider_lane(segment_map)
        physical_payload_family_hash = _physical_payload_family_hash(segment_map)
        prefix_hashes = _prefix_hashes(
            segment_map=segment_map,
            diff_report=diff_report,
            provider_request=provider_request,
            provider_payload_prefix_hash=str(physical_spine.get("provider_payload_prefix_hash") or ""),
        )
        generation = max(int(previous_generation or 0), int(getattr(previous_state, "generation", 0) or 0))
        changed_tiers = _changed_tiers(previous_state, prefix_hashes)
        cache_summary = _cache_expectation_summary(cache_plan)
        provider_prefix_seal = _provider_prefix_seal(physical_spine)
        provider_prefix_continuity = _provider_prefix_continuity(
            previous=previous_state,
            current_seal=provider_prefix_seal,
        )
        diagnostics = {
            "source_components": {
                "prefix_state_diff_report_id": str(getattr(diff_report, "report_id", "") or ""),
                "cache_plan_id": str(getattr(cache_plan, "cache_plan_id", "") or ""),
            },
            "diff": dict(getattr(diff_report, "diagnostics", {}) or {}),
            "provider_payload": provider_payload_boundary_diagnostics(
                provider_request=provider_request,
                boundary=boundary,
            ),
            "provider_prefix_seal": provider_prefix_seal,
            "provider_prefix_continuity": provider_prefix_continuity,
            "provider_lane": provider_lane,
            "physical_payload_family_hash": physical_payload_family_hash,
            "physical_payload_family": dict(dict(segment_map.metadata or {}).get("physical_payload_family") or {}),
            "reset_seen": previous_state is None and generation > 0,
            "has_previous_active_state": previous_state is not None,
            "previous_generation": generation,
            "transport_contract_hash": str(getattr(provider_request, "transport_contract_hash", "") or ""),
            "physical_cache_spine_message_subtotal_hash": str(getattr(provider_request, "physical_cache_spine_message_subtotal_hash", "") or ""),
        }
        state = PrefixStateRecord(
            state_id=_state_id(
                request_id=segment_map.request_id,
                generation=generation,
                created_at=timestamp,
            ),
            request_id=segment_map.request_id,
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            packet_id=str(getattr(diff_report, "packet_id", "") or ""),
            provider=segment_map.provider,
            model=segment_map.model,
            invocation_kind=invocation_kind,
            provider_lane=provider_lane,
            physical_payload_family_hash=physical_payload_family_hash,
            status="active",
            previous_state_ref=(
                str(getattr(previous_state, "state_id", "") or "")
                or str(getattr(diff_report, "previous_report_ref", "") or "")
            ),
            generation=generation,
            provider_payload_prefix_hash=prefix_hashes["provider_payload"],
            global_static_prefix_hash=str(lane_hashes.get("global_static_prefix") or ""),
            provider_visible_context_prefix_hash=str(lane_hashes.get("provider_visible_context_prefix") or ""),
            current_turn_tail_hash=str(lane_hashes.get("current_turn_tail") or ""),
            never_replay_tail_hash=str(lane_hashes.get("never_replay_tail") or ""),
            stable_prefix_hash=prefix_hashes["stable"],
            provider_global_prefix_hash=prefix_hashes["provider_global"],
            session_prefix_hash=prefix_hashes["session"],
            memory_segment_hash=prefix_hashes["memory"],
            tool_catalog_hash=prefix_hashes["tool_catalog"],
            stable_tool_catalog_hash=prefix_hashes["stable_tool_catalog"],
            cache_sensitive_params_hash=prefix_hashes["cache_sensitive_params"],
            changed_tiers=changed_tiers,
            changed_sections=tuple(dict(item) for item in tuple(getattr(diff_report, "changed_sections", ()) or ())),
            first_changed_section=dict(getattr(diff_report, "first_changed_section", {}) or {}),
            stable_token_count=int(getattr(diff_report, "stable_prefix_tokens", 0) or 0),
            volatile_token_count=int(getattr(diff_report, "volatile_token_count", 0) or 0),
            provider_cache_read_expectation_summary=cache_summary,
            stable_section_refs=tuple(_section_ref(section) for section in tuple(getattr(diff_report, "stable_sections", ()) or ())),
            dynamic_param_hash=str(getattr(diff_report, "dynamic_param_hash", "") or ""),
            dynamic_param_summary=dict(getattr(diff_report, "dynamic_param_summary", {}) or {}),
            created_at=timestamp,
            diagnostics=diagnostics,
        )
        return state

    def build_invalidation_record(
        self,
        *,
        previous_records: list[PrefixStateRecord] | tuple[PrefixStateRecord, ...] = (),
        request_id: str = "",
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        invocation_kind: str = "",
        provider_lane: str = "",
        physical_payload_family_hash: str = "",
        provider: str = "",
        model: str = "",
        reason: str,
        reset_ref: str = "",
        diagnostics: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> PrefixStateRecord:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        previous = _latest_matching_state(
            previous_records,
            invocation_kind=invocation_kind,
            provider_lane=provider_lane,
            physical_payload_family_hash=physical_payload_family_hash,
            provider=provider,
            model=model,
        )
        latest_generation = max([int(getattr(item, "generation", 0) or 0) for item in previous_records], default=0)
        generation = max(latest_generation, int(getattr(previous, "generation", 0) or 0)) + 1
        resolved_request_id = str(request_id or f"prefix-state-reset:{hashlib.sha256(str(timestamp).encode('utf-8')).hexdigest()[:12]}")
        return PrefixStateRecord(
            state_id=_state_id(request_id=resolved_request_id, generation=generation, created_at=timestamp),
            request_id=resolved_request_id,
            run_id=str(run_id or ""),
            task_run_id=str(task_run_id or ""),
            session_id=str(session_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            invocation_kind=str(invocation_kind or ""),
            provider_lane=normalize_provider_lane(provider_lane),
            physical_payload_family_hash=str(physical_payload_family_hash or ""),
            status="invalidated",
            previous_state_ref=str(getattr(previous, "state_id", "") or ""),
            generation=generation,
            reset_reason=str(reason or "prefix_state_reset"),
            reset_ref=str(reset_ref or ""),
            created_at=timestamp,
            diagnostics=dict(diagnostics or {}),
        )


def prefix_state_to_diff_report(record: PrefixStateRecord) -> PrefixStateDiffReport:
    diagnostics = dict(record.diagnostics or {})
    diff_diagnostics = dict(diagnostics.get("diff") or {})
    stable_sections = tuple(
        PrefixStateDiffSection.from_dict(dict(item))
        for item in tuple(record.stable_section_refs or ())
    )
    return PrefixStateDiffReport(
        report_id=str(record.state_id or ""),
        request_id=str(record.request_id or ""),
        run_id=str(record.run_id or record.task_run_id or ""),
        task_run_id=str(record.task_run_id or ""),
        session_id=str(record.session_id or ""),
        packet_id=str(record.packet_id or ""),
        invocation_kind=str(record.invocation_kind or ""),
        provider=str(record.provider or ""),
        model=str(record.model or ""),
        stable_prefix_hash=str(record.stable_prefix_hash or ""),
        provider_global_prefix_hash=str(record.provider_global_prefix_hash or ""),
        session_prefix_hash=str(record.session_prefix_hash or ""),
        stable_prefix_tokens=int(record.stable_token_count or 0),
        stable_section_count=len(stable_sections),
        volatile_token_count=int(record.volatile_token_count or 0),
        stable_sections=stable_sections,
        dynamic_param_hash=str(record.dynamic_param_hash or ""),
        dynamic_param_summary=dict(record.dynamic_param_summary or {}),
        previous_report_ref=str(record.previous_state_ref or ""),
        first_changed_section=dict(record.first_changed_section or {}),
        changed_sections=tuple(dict(item) for item in tuple(record.changed_sections or ())),
        diagnostics=diff_diagnostics,
        created_at=float(record.created_at or 0.0),
    )


def latest_matching_prefix_state(
    records: list[PrefixStateRecord] | tuple[PrefixStateRecord, ...],
    *,
    invocation_kind: str,
    provider: str,
    model: str,
    provider_lane: str = "",
    physical_payload_family_hash: str = "",
) -> PrefixStateRecord | None:
    previous, _generation = resolve_previous_prefix_state(
        records,
        invocation_kind=invocation_kind,
        provider=provider,
        model=model,
        provider_lane=provider_lane,
        physical_payload_family_hash=physical_payload_family_hash,
    )
    return previous


def resolve_previous_prefix_state(
    records: list[PrefixStateRecord] | tuple[PrefixStateRecord, ...],
    *,
    invocation_kind: str,
    provider: str,
    model: str,
    provider_lane: str = "",
    physical_payload_family_hash: str = "",
) -> tuple[PrefixStateRecord | None, int]:
    relevant = [
        record
        for record in tuple(records or ())
        if _record_matches(
            record,
            invocation_kind=invocation_kind,
            provider_lane=provider_lane,
            physical_payload_family_hash=physical_payload_family_hash,
            provider=provider,
            model=model,
        )
    ]
    if not relevant:
        return None, 0
    latest = sorted(relevant, key=lambda item: float(item.created_at or 0.0))[-1]
    generation = int(getattr(latest, "generation", 0) or 0)
    if latest.status == "invalidated":
        return None, generation
    return latest, generation


def _latest_matching_state(
    records: list[PrefixStateRecord] | tuple[PrefixStateRecord, ...],
    *,
    invocation_kind: str,
    provider_lane: str = "",
    physical_payload_family_hash: str = "",
    provider: str = "",
    model: str = "",
) -> PrefixStateRecord | None:
    for record in reversed(sorted(tuple(records or ()), key=lambda item: float(item.created_at or 0.0))):
        if _record_matches(
            record,
            invocation_kind=invocation_kind,
            provider_lane=provider_lane,
            physical_payload_family_hash=physical_payload_family_hash,
            provider=provider,
            model=model,
        ):
            return record
    return None


def _record_matches(
    record: PrefixStateRecord,
    *,
    invocation_kind: str,
    provider_lane: str = "",
    physical_payload_family_hash: str = "",
    provider: str = "",
    model: str = "",
) -> bool:
    return (
        _matches_or_wildcard(record.invocation_kind, invocation_kind)
        and _matches_or_wildcard(_normalized_lane_or_blank(record.provider_lane), _normalized_lane_or_blank(provider_lane))
        and _matches_or_wildcard(record.physical_payload_family_hash, physical_payload_family_hash)
        and _matches_or_wildcard(record.provider, provider)
        and _matches_or_wildcard(record.model, model)
    )


def _matches_or_wildcard(record_value: str, current_value: str) -> bool:
    normalized = str(record_value or "")
    current = str(current_value or "")
    return not normalized or not current or normalized == current


def _normalized_lane_or_blank(value: Any) -> str:
    return normalize_provider_lane(value) if str(value or "").strip() else ""


def _cache_expectation_summary(cache_plan: CachePlanRecord | None) -> dict[str, Any]:
    if cache_plan is None:
        return {}
    diagnostics = dict(getattr(cache_plan, "diagnostics", {}) or {})
    return {
        "cache_plan_id": str(getattr(cache_plan, "cache_plan_id", "") or ""),
        "status": str(getattr(cache_plan, "status", "") or ""),
        "scope": str(getattr(cache_plan, "scope", "") or ""),
        "prefix_key_tier": str(diagnostics.get("prefix_key_tier") or diagnostics.get("provider_request_prefix_key_tier") or ""),
        "selected_prefix_hash": str(getattr(cache_plan, "prefix_hash", "") or ""),
        "expected_prefix_hash": str(diagnostics.get("provider_request_selected_prefix_hash") or ""),
        "prefix_hash_matches_provider_request": bool(diagnostics.get("prefix_hash_matches_provider_request") is True),
        "boundary_segment_id": str(getattr(cache_plan, "boundary_segment_id", "") or ""),
        "physical_cache_spine_predicted_tokens": _int(diagnostics.get("physical_cache_spine_predicted_tokens")),
    }


def _physical_lane_hashes(provider_request: Any | None) -> dict[str, str]:
    manifest = getattr(provider_request, "provider_payload_manifest", None)
    segments = []
    if manifest is not None and hasattr(manifest, "to_dict"):
        segments = list(dict(manifest.to_dict() or {}).get("segments") or [])
    if not segments:
        boundary = provider_payload_cache_boundary(provider_request)
        spine = dict(boundary.get("physical_cache_spine") or {})
        segments = list(spine.get("segments") or [])
    lanes = {
        "global_static_prefix": [],
        "provider_visible_context_prefix": [],
        "current_turn_tail": [],
        "never_replay_tail": [],
    }
    for item in segments:
        if not isinstance(item, dict):
            continue
        lane = str(item.get("physical_prefix_lane") or dict(item.get("prefix_identity") or {}).get("physical_prefix_lane") or "")
        if lane not in lanes:
            continue
        lanes[lane].append(
            {
                "ordinal": _int(item.get("ordinal")),
                "segment_id": str(item.get("segment_id") or ""),
                "content_hash": str(item.get("content_hash") or ""),
                "provider_serialized_hash": str(item.get("provider_serialized_hash") or item.get("content_hash") or ""),
            }
        )
    return {lane: _hash_json(sorted(items, key=lambda row: int(row.get("ordinal") or 0))) for lane, items in lanes.items()}


def _prefix_hashes(
    *,
    segment_map: PromptSegmentMap,
    diff_report: PrefixStateDiffReport,
    provider_request: Any | None,
    provider_payload_prefix_hash: str,
) -> dict[str, str]:
    boundary = provider_payload_cache_boundary(provider_request)
    resolved_provider_payload_prefix_hash = str(
        provider_payload_prefix_hash
        or getattr(provider_request, "provider_payload_prefix_hash", "")
        or ""
    )
    return {
        "stable": str(getattr(diff_report, "stable_prefix_hash", "") or resolved_provider_payload_prefix_hash),
        "provider_global": str(
            getattr(diff_report, "provider_global_prefix_hash", "")
            or boundary.get("provider_global_prefix_hash")
            or resolved_provider_payload_prefix_hash
        ),
        "session": str(getattr(diff_report, "session_prefix_hash", "") or boundary.get("session_prefix_hash") or ""),
        "memory": _memory_segment_hash(segment_map),
        "provider_payload": resolved_provider_payload_prefix_hash,
        "tool_catalog": str(getattr(provider_request, "tool_catalog_hash", "") or boundary.get("tool_catalog_hash") or ""),
        "stable_tool_catalog": str(getattr(provider_request, "stable_tool_catalog_hash", "") or boundary.get("stable_tool_catalog_hash") or ""),
        "cache_sensitive_params": str(getattr(provider_request, "cache_sensitive_params_hash", "") or boundary.get("cache_sensitive_params_hash") or ""),
    }


def _changed_tiers(previous: PrefixStateRecord | None, hashes: dict[str, str]) -> tuple[str, ...]:
    if previous is None:
        return ()
    checks = {
        "stable": previous.stable_prefix_hash,
        "provider_global": previous.provider_global_prefix_hash,
        "session": previous.session_prefix_hash,
        "memory": previous.memory_segment_hash,
        "provider_payload": previous.provider_payload_prefix_hash,
        "tool_catalog": previous.tool_catalog_hash,
        "stable_tool_catalog": previous.stable_tool_catalog_hash,
        "cache_sensitive_params": previous.cache_sensitive_params_hash,
    }
    return tuple(
        tier
        for tier, previous_hash in checks.items()
        if str(previous_hash or "") != str(hashes.get(tier) or "")
    )


def _memory_segment_hash(segment_map: PromptSegmentMap) -> str:
    memory_segments = [segment for segment in tuple(segment_map.segments or ()) if _is_memory_segment(segment)]
    if not memory_segments:
        return ""
    return _hash_json([str(segment.content_hash or "") for segment in memory_segments])


def _is_memory_segment(segment: Any) -> bool:
    metadata = dict(getattr(segment, "metadata", {}) or {})
    policy = dict(metadata.get("context_segment_policy") or {})
    kind = _first_text(getattr(segment, "kind", ""), metadata.get("kind"), metadata.get("canonical_kind"))
    if kind in MEMORY_SEGMENT_KINDS:
        return True
    capability = context_segment_kind_capability(kind)
    if capability and str(capability[0] or "") == CONTEXT_MEMORY:
        return True
    semantic_slot = _first_text(
        getattr(segment, "semantic_slot", ""),
        metadata.get("context_semantic_slot"),
        metadata.get("semantic_slot"),
        policy.get("semantic_slot"),
    )
    if semantic_slot in MEMORY_SEGMENT_SLOTS:
        return True
    agent_domain = _first_text(
        metadata.get("agent_domain"),
        metadata.get("context_agent_domain"),
        getattr(segment, "agent_domain", ""),
    )
    if semantic_slot == SELECTED_MEMORY_AND_TASK_STATE_SLOT and agent_domain == "ContextMemoryDomain":
        return True
    semantic_commit_class = _first_text(
        metadata.get("semantic_commit_class"),
        metadata.get("context_semantic_commit_class"),
        policy.get("semantic_commit_class"),
    )
    if semantic_commit_class in MEMORY_SEGMENT_COMMIT_CLASSES:
        return True
    return False


def _provider_prefix_seal(physical_spine: dict[str, Any]) -> dict[str, Any]:
    prefix_segments = [
        dict(item)
        for item in list(dict(physical_spine or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    if not prefix_segments:
        return {
            "status": "empty",
            "selected_boundary": "physical_cache_spine",
            "segment_count": 0,
            "segments": [],
        }
    prefix_segments = sorted(prefix_segments, key=lambda item: _int(item.get("ordinal")))
    return {
        "status": "sealed",
        "selected_boundary": "physical_cache_spine",
        "segment_count": len(prefix_segments),
        "byte_length": sum(_int(item.get("byte_length")) for item in prefix_segments),
        "content_hash": _hash_json([str(item.get("content_hash") or "") for item in prefix_segments]),
        "physical_cache_spine_hash": str(physical_spine.get("provider_payload_prefix_hash") or ""),
        "physical_cache_spine_message_subtotal_hash": str(physical_spine.get("physical_cache_spine_message_subtotal_hash") or ""),
        "segments": prefix_segments,
    }


def _provider_prefix_continuity(
    *,
    previous: PrefixStateRecord | None,
    current_seal: dict[str, Any],
) -> dict[str, Any]:
    current_segments = [
        dict(item)
        for item in list(dict(current_seal or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    previous_seal = _previous_provider_prefix_seal(previous)
    previous_segments = [
        dict(item)
        for item in list(previous_seal.get("segments") or [])
        if isinstance(item, dict)
    ]
    common = 0
    for left, right in zip(previous_segments, current_segments):
        if _provider_prefix_segment_identity(left) != _provider_prefix_segment_identity(right):
            break
        common += 1
    first_mismatch: dict[str, Any] = {}
    if common < min(len(previous_segments), len(current_segments)):
        first_mismatch = {
            "index": common + 1,
            "previous": _provider_prefix_segment_summary(previous_segments[common]),
            "current": _provider_prefix_segment_summary(current_segments[common]),
        }
    elif len(previous_segments) > len(current_segments):
        first_mismatch = {
            "index": common + 1,
            "previous": _provider_prefix_segment_summary(previous_segments[common]),
            "current": {},
        }
    return {
        "status": (
            "no_previous"
            if previous is None
            else "previous_prefix_preserved"
            if common == len(previous_segments)
            else "previous_prefix_broken"
        ),
        "previous_state_ref": str(getattr(previous, "state_id", "") or ""),
        "previous_segment_count": len(previous_segments),
        "current_segment_count": len(current_segments),
        "common_segment_count": common,
        "previous_prefix_preserved": bool(previous is not None and common == len(previous_segments)),
        "first_mismatch": first_mismatch,
    }


def _previous_provider_prefix_seal(previous: PrefixStateRecord | None) -> dict[str, Any]:
    if previous is None:
        return {}
    diagnostics = dict(getattr(previous, "diagnostics", {}) or {})
    return dict(diagnostics.get("provider_prefix_seal") or {})


def _provider_prefix_segment_identity(segment: dict[str, Any]) -> tuple[str, str]:
    return (
        str(segment.get("transport_location") or ""),
        str(segment.get("content_hash") or ""),
    )


def _provider_prefix_segment_summary(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "ordinal": _int(segment.get("ordinal")),
        "kind": str(segment.get("kind") or ""),
        "transport_location": str(segment.get("transport_location") or ""),
        "content_hash": str(segment.get("content_hash") or ""),
        "cache_role": str(segment.get("cache_role") or ""),
        "prefix_tier": str(segment.get("prefix_tier") or ""),
    }


def _invocation_kind(segment_map: PromptSegmentMap, *, diff_report: PrefixStateDiffReport | None = None) -> str:
    metadata = dict(segment_map.metadata or {})
    return str(
        getattr(diff_report, "invocation_kind", "")
        or metadata.get("source")
        or metadata.get("call_kind")
        or ""
    )


def _provider_lane(segment_map: PromptSegmentMap) -> str:
    metadata = dict(segment_map.metadata or {})
    return normalize_provider_lane(metadata.get("provider_lane"))


def _physical_payload_family_hash(segment_map: PromptSegmentMap) -> str:
    metadata = dict(segment_map.metadata or {})
    return str(metadata.get("physical_payload_family_hash") or "")


def _section_ref(section: PrefixStateDiffSection) -> dict[str, Any]:
    return section.to_dict() if hasattr(section, "to_dict") else dict(section or {})


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _state_id(*, request_id: str, generation: int, created_at: float) -> str:
    return "pstate:" + hashlib.sha256(
        json.dumps(
            {
                "request_id": str(request_id or ""),
                "generation": int(generation or 0),
                "created_at": float(created_at or 0.0),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]


def _hash_json(payload: Any) -> str:
    if not payload:
        return ""
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _status(value: Any) -> PrefixStateStatus:
    status = str(value or "").strip()
    if status in {"active", "invalidated"}:
        return status  # type: ignore[return-value]
    return "active"


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
