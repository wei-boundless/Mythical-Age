from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from context_system.segments.metadata import provider_message_byte_preservation_required
from context_system.segments.policy import context_segment_policy_for_spec


TRANSPORT_CONTRACT = "transport_contract"
GLOBAL_STATIC_PREFIX = "global_static_prefix"
PROVIDER_VISIBLE_CONTEXT_PREFIX = "provider_visible_context_prefix"
CURRENT_TURN_TAIL = "current_turn_tail"
NEVER_REPLAY_TAIL = "never_replay_tail"
MISSING_PHYSICAL_ASSEMBLY = "missing_physical_assembly"

CACHE_SPINE_LANES = {
    GLOBAL_STATIC_PREFIX,
    PROVIDER_VISIBLE_CONTEXT_PREFIX,
}
TAIL_LANES = {CURRENT_TURN_TAIL, NEVER_REPLAY_TAIL}


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
    """Describe an already-assembled physical context order.

    The physical assembler owns splice order. This plan only adds lane metadata,
    cache-spine identity, and diagnostics for the order it receives.
    """

    raw_segments: list[PhysicalContextPlanSegment] = []
    lane_counts: dict[str, int] = {}
    lane_order: list[str] = []
    blocked_segments: list[dict[str, Any]] = []

    for index, raw_spec in enumerate(list(specs or ()), start=1):
        if not isinstance(raw_spec, dict):
            continue
        spec = dict(raw_spec)
        metadata = dict(spec.get("metadata") or {})
        policy = context_segment_policy_for_spec(spec)
        lane, lane_issue = _assembler_lane_for_spec(spec, metadata=metadata)
        assembly_index = _physical_assembly_index(spec, metadata=metadata)
        if lane_issue:
            blocked_segments.append(
                {
                    "index": index,
                    "kind": str(spec.get("kind") or metadata.get("kind") or ""),
                    "source_ref": str(spec.get("source_ref") or metadata.get("source_ref") or ""),
                    "reason": lane_issue,
                    "authority": "runtime.context_management.physical_context_plan",
                }
            )
        if assembly_index <= 0:
            blocked_segments.append(
                {
                    "index": index,
                    "kind": str(spec.get("kind") or metadata.get("kind") or ""),
                    "source_ref": str(spec.get("source_ref") or metadata.get("source_ref") or ""),
                    "reason": "missing_context_physical_assembly_index",
                    "authority": "runtime.context_management.physical_context_plan",
                }
            )
        elif assembly_index != index:
            blocked_segments.append(
                {
                    "index": index,
                    "context_physical_assembly_index": assembly_index,
                    "kind": str(spec.get("kind") or metadata.get("kind") or ""),
                    "source_ref": str(spec.get("source_ref") or metadata.get("source_ref") or ""),
                    "reason": "context_physical_assembly_index_mismatch",
                    "authority": "runtime.context_management.physical_context_plan",
                }
            )
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

    segments = tuple(raw_segments)
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
                    "lane": lane,
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
        segments=segments,
        stable_after_tail_violations=tuple(stable_after_tail_violations),
        blocked_segments=tuple(blocked_segments),
    )


def _assembler_lane_for_spec(spec: dict[str, Any], *, metadata: dict[str, Any]) -> tuple[str, str]:
    lane = _first_text(metadata.get("physical_prefix_lane"), spec.get("physical_prefix_lane"))
    if lane:
        return lane, ""
    return MISSING_PHYSICAL_ASSEMBLY, "missing_physical_prefix_lane"


def _historical_only_metadata(metadata: dict[str, Any]) -> bool:
    return (
        metadata.get("provider_visible_replay_only") is True
        or metadata.get("context_memory_visible") is False
        or _historical_only_on_replay(metadata)
    )


def _historical_only_on_replay(metadata: dict[str, Any]) -> bool:
    value = metadata.get("historical_only_on_replay", metadata.get("provider_visible_historical_only_on_replay"))
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true", "1", "yes", "historical_only_provider_visible_replay"}


def _semantic_visibility(*, metadata: dict[str, Any], lane: str) -> str:
    explicit = str(metadata.get("semantic_visibility") or "").strip()
    if explicit:
        return explicit
    if lane == MISSING_PHYSICAL_ASSEMBLY:
        return "missing_physical_assembly"
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
    if lane == MISSING_PHYSICAL_ASSEMBLY:
        return "missing_physical_assembly"
    return ""


def _physical_assembly_index(spec: dict[str, Any], *, metadata: dict[str, Any]) -> int:
    for value in (
        metadata.get("context_physical_assembly_index"),
        spec.get("context_physical_assembly_index"),
    ):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
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
    if _must_preserve_model_message_hash(spec):
        return _stable_json_hash({"model_message": dict(message or {})})
    seed = {
        "role": str(dict(message).get("role") or spec.get("role") or ""),
        "content": str(dict(message).get("content") if dict(message).get("content") is not None else spec.get("content") or ""),
        "name": str(dict(message).get("name") or ""),
        "tool_call_id": str(dict(message).get("tool_call_id") or ""),
        "tool_calls": dict(message).get("tool_calls") or [],
        "reasoning_content": str(dict(message).get("reasoning_content") or ""),
        "kind": str(spec.get("kind") or ""),
        "source_ref": str(spec.get("source_ref") or ""),
    }
    return _stable_json_hash(seed)


def _must_preserve_model_message_hash(spec: dict[str, Any]) -> bool:
    return provider_message_byte_preservation_required(spec)


def _stable_json_hash(value: Any) -> str:
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
