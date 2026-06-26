from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .context_segment_policy import (
    CONTEXT_APPEND,
    CONTEXT_MEMORY_PREFIX,
    DYNAMIC_TAIL,
    STATIC_PREFIX,
    ContextSegmentPolicy,
    context_segment_policy_for_spec,
    context_segment_policy_is_provider_visible_sealable,
)


TRANSPORT_CONTRACT = "transport_contract"
GLOBAL_STATIC_PREFIX = "global_static_prefix"
PROVIDER_VISIBLE_CONTEXT_PREFIX = "provider_visible_context_prefix"
CURRENT_TURN_TAIL = "current_turn_tail"
NEVER_REPLAY_TAIL = "never_replay_tail"

CACHE_SPINE_LANES = {
    GLOBAL_STATIC_PREFIX,
    PROVIDER_VISIBLE_CONTEXT_PREFIX,
}
TAIL_LANES = {CURRENT_TURN_TAIL, NEVER_REPLAY_TAIL}
PHYSICAL_CONTEXT_LANE_ORDER = (
    GLOBAL_STATIC_PREFIX,
    PROVIDER_VISIBLE_CONTEXT_PREFIX,
    CURRENT_TURN_TAIL,
    NEVER_REPLAY_TAIL,
)
PHYSICAL_CONTEXT_LANE_RANK = {lane: index * 10 for index, lane in enumerate(PHYSICAL_CONTEXT_LANE_ORDER, start=1)}


@dataclass(frozen=True, slots=True)
class PhysicalContextPlanSegment:
    index: int
    kind: str
    source_ref: str
    lane: str
    section: str
    cache_scope: str
    cache_role: str
    prefix_tier: str
    semantic_visibility: str
    replay_policy: str
    validity_scope: str
    content_hash: str
    cache_spine_participation: bool
    cache_spine_break_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PhysicalContextPlan:
    plan_id: str
    cache_spine_hash: str
    cache_spine_generation: str
    cache_spine_segment_count: int
    lane_counts: dict[str, int]
    lane_order: tuple[str, ...]
    segments: tuple[PhysicalContextPlanSegment, ...]
    stable_after_tail_violations: tuple[dict[str, Any], ...]
    blocked_segments: tuple[dict[str, Any], ...] = ()
    authority: str = "runtime.context_management.physical_context_plan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "cache_spine_hash": self.cache_spine_hash,
            "cache_spine_generation": self.cache_spine_generation,
            "cache_spine_segment_count": self.cache_spine_segment_count,
            "lane_counts": dict(self.lane_counts),
            "lane_order": list(self.lane_order),
            "segments": [segment.to_dict() for segment in self.segments],
            "stable_after_tail_violations": [dict(item) for item in self.stable_after_tail_violations],
            "blocked_segments": [dict(item) for item in self.blocked_segments],
            "authority": self.authority,
        }


def build_physical_context_plan(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    transport_contract_hash: str = "",
    compaction_generation: str = "",
) -> PhysicalContextPlan:
    raw_segments: list[PhysicalContextPlanSegment] = []
    lane_counts: dict[str, int] = {}
    lane_order: list[str] = []

    for index, raw_spec in enumerate(list(specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = dict(spec.get("metadata") or {})
        policy = context_segment_policy_for_spec(spec)
        lane = physical_lane_for_spec(spec, policy=policy)
        cache_spine_participation = lane in CACHE_SPINE_LANES
        content_hash = _spec_content_hash(spec)
        segment = PhysicalContextPlanSegment(
            index=index,
            kind=str(spec.get("kind") or metadata.get("kind") or ""),
            source_ref=str(spec.get("source_ref") or metadata.get("source_ref") or ""),
            lane=lane,
            section=policy.section,
            cache_scope=str(policy.prefix_cache_scope or "none"),
            cache_role=str(policy.prefix_cache_role or "volatile"),
            prefix_tier=str(policy.prefix_tier or "volatile"),
            semantic_visibility=_semantic_visibility(metadata=metadata, lane=lane),
            replay_policy=str(metadata.get("context_replay_policy") or ""),
            validity_scope=_validity_scope(metadata),
            content_hash=content_hash,
            cache_spine_participation=cache_spine_participation,
            cache_spine_break_reason="" if cache_spine_participation else _tail_break_reason(lane),
            metadata=metadata,
        )
        raw_segments.append(segment)

    segments = sorted(raw_segments, key=_physical_context_order_key)
    spine_seed: list[dict[str, Any]] = []
    tail_seen = False
    stable_after_tail_violations: list[dict[str, Any]] = []
    for physical_index, segment in enumerate(segments, start=1):
        lane = segment.lane
        if lane not in lane_counts:
            lane_order.append(lane)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
        cache_spine_participation = lane in CACHE_SPINE_LANES
        if lane in TAIL_LANES:
            tail_seen = True
        elif tail_seen and cache_spine_participation:
            stable_after_tail_violations.append(
                {
                    "index": segment.index,
                    "physical_index": physical_index,
                    "kind": segment.kind,
                    "source_ref": segment.source_ref,
                    "lane": lane,
                    "section": segment.section,
                    "content_hash": segment.content_hash,
                    "reason": "cache_spine_segment_after_current_turn_tail",
                }
            )
        if cache_spine_participation:
            spine_seed.append(
                {
                    "physical_index": physical_index,
                    "original_index": segment.index,
                    "lane": lane,
                    "kind": segment.kind,
                    "source_ref": segment.source_ref,
                    "content_hash": segment.content_hash,
                }
            )

    generation = str(compaction_generation or _first_generation(segments) or "0")
    cache_spine_hash = _stable_json_hash(
        {
            "transport_contract_hash": str(transport_contract_hash or ""),
            "cache_spine_generation": generation,
            "segments": spine_seed,
        }
    ) if spine_seed or transport_contract_hash else ""
    plan_id = "physctx:" + _stable_json_hash(
        {
            "cache_spine_hash": cache_spine_hash,
            "segment_count": len(segments),
            "lane_counts": lane_counts,
            "violations": stable_after_tail_violations,
        }
    ).removeprefix("sha256:")[:16]
    return PhysicalContextPlan(
        plan_id=plan_id,
        cache_spine_hash=cache_spine_hash,
        cache_spine_generation=generation,
        cache_spine_segment_count=len(spine_seed),
        lane_counts=lane_counts,
        lane_order=tuple(lane_order),
        segments=tuple(segments),
        stable_after_tail_violations=tuple(stable_after_tail_violations),
    )


def annotate_specs_with_physical_context_plan(
    specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    transport_contract_hash: str = "",
    compaction_generation: str = "",
) -> tuple[list[dict[str, Any]], PhysicalContextPlan]:
    plan = build_physical_context_plan(
        specs,
        transport_contract_hash=transport_contract_hash,
        compaction_generation=compaction_generation,
    )
    specs_by_index = {
        index: dict(raw_spec)
        for index, raw_spec in enumerate(list(specs or ()), start=1)
        if isinstance(raw_spec, dict)
    }
    annotated: list[dict[str, Any]] = []
    for physical_index, segment in enumerate(plan.segments, start=1):
        spec = dict(specs_by_index.get(segment.index) or {})
        if not spec:
            continue
        metadata = {
            **dict(spec.get("metadata") or {}),
            "context_physical_assembly_index": physical_index,
            "context_physical_original_order": segment.index,
            "physical_prefix_lane": segment.lane,
            "physical_context_plan_ref": plan.plan_id,
            "cache_spine_hash": plan.cache_spine_hash,
            "cache_spine_generation": plan.cache_spine_generation,
            "cache_spine_participation": segment.cache_spine_participation,
            "cache_spine_break_reason": segment.cache_spine_break_reason,
            "semantic_visibility": segment.semantic_visibility,
            "validity_scope": segment.validity_scope,
            "physical_context_plan_authority": plan.authority,
        }
        spec["metadata"] = metadata
        annotated.append(spec)
    return annotated, plan


def physical_lane_for_spec(spec: dict[str, Any] | None, *, policy: ContextSegmentPolicy | None = None) -> str:
    payload = dict(spec or {})
    policy = policy or context_segment_policy_for_spec(payload)
    section = str(policy.section or "")
    if section == STATIC_PREFIX:
        return GLOBAL_STATIC_PREFIX
    if section == CONTEXT_MEMORY_PREFIX:
        if not _stable_prefix_binding(policy):
            return CURRENT_TURN_TAIL
        return PROVIDER_VISIBLE_CONTEXT_PREFIX
    if section == CONTEXT_APPEND:
        return CURRENT_TURN_TAIL
    if section == DYNAMIC_TAIL:
        return NEVER_REPLAY_TAIL
    return CURRENT_TURN_TAIL


def _historical_only_metadata(metadata: dict[str, Any]) -> bool:
    semantic_class = str(metadata.get("semantic_commit_class") or "").strip()
    return (
        metadata.get("provider_visible_replay_only") is True
        or metadata.get("semantic_memory_visible") is False
        or semantic_class.startswith("provider_visible_replay_only")
        or _historical_only_on_replay(metadata)
    )


def _stable_prefix_binding(policy: ContextSegmentPolicy) -> bool:
    return context_segment_policy_is_provider_visible_sealable(policy) or str(policy.section or "") == STATIC_PREFIX


def _historical_only_on_replay(metadata: dict[str, Any]) -> bool:
    value = metadata.get("historical_only_on_replay", metadata.get("provider_visible_historical_only_on_replay"))
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true", "1", "yes", "historical_only_provider_visible_replay"}


def _semantic_visibility(*, metadata: dict[str, Any], lane: str) -> str:
    explicit = str(metadata.get("semantic_visibility") or "").strip()
    if explicit:
        return explicit
    if _historical_only_metadata(metadata):
        return "historical_only"
    if lane in TAIL_LANES:
        return "current_turn_only"
    return "active"


def _validity_scope(metadata: dict[str, Any]) -> str:
    for key in (
        "validity_scope",
        "context_validity_scope",
        "provider_visible_replay_validity_scope",
        "valid_until_turn_id",
        "valid_as_active_instruction_until",
        "turn_id",
        "task_run_id",
        "compaction_generation",
    ):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _tail_break_reason(lane: str) -> str:
    if lane == CURRENT_TURN_TAIL:
        return "current_turn_tail_after_cache_boundary"
    if lane == NEVER_REPLAY_TAIL:
        return "never_replay_tail_after_cache_boundary"
    return ""


def _first_generation(segments: tuple[PhysicalContextPlanSegment, ...]) -> str:
    for segment in segments:
        value = str(
            segment.metadata.get("compaction_generation")
            or segment.metadata.get("context_compaction_generation")
            or ""
        ).strip()
        if value:
            return value
    return ""


def _spec_content_hash(spec: dict[str, Any]) -> str:
    message = spec.get("model_message") if isinstance(spec.get("model_message"), dict) else {}
    seed = {
        "role": str(dict(message).get("role") or spec.get("role") or ""),
        "content": str(dict(message).get("content") if dict(message).get("content") is not None else spec.get("content") or ""),
        "kind": str(spec.get("kind") or ""),
        "source_ref": str(spec.get("source_ref") or ""),
    }
    return _stable_json_hash(seed)


def _physical_context_order_key(segment: PhysicalContextPlanSegment) -> tuple[int, int, int, str]:
    ledger_entry_index = _safe_int(segment.metadata.get("provider_visible_context_ledger_entry_index"))
    if ledger_entry_index > 0 and segment.lane == PROVIDER_VISIBLE_CONTEXT_PREFIX:
        return (
            PHYSICAL_CONTEXT_LANE_RANK[PROVIDER_VISIBLE_CONTEXT_PREFIX],
            ledger_entry_index,
            int(segment.index or 0),
            str(segment.source_ref or ""),
        )
    return (
        PHYSICAL_CONTEXT_LANE_RANK.get(segment.lane, 999),
        int(segment.index or 0),
        0,
        str(segment.source_ref or ""),
    )


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
