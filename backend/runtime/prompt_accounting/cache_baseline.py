from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from prompt_cache_policy import is_cache_eligible_prefix, is_prefix_eligible_for_tier

from .cache_planner import stable_text_hash
from .models import PromptSegment, PromptSegmentMap


PromptCacheBaselineStatus = Literal["active", "invalidated"]


@dataclass(frozen=True, slots=True)
class PromptCacheBaselineRecord:
    baseline_id: str
    request_id: str = ""
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    provider: str = ""
    model: str = ""
    invocation_kind: str = ""
    status: PromptCacheBaselineStatus = "active"
    generation: int = 0
    stable_prefix_hash: str = ""
    provider_global_prefix_hash: str = ""
    session_prefix_hash: str = ""
    task_prefix_hash: str = ""
    memory_segment_hash: str = ""
    previous_baseline_ref: str = ""
    changed_tiers: tuple[str, ...] = ()
    reset_reason: str = ""
    reset_ref: str = ""
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prompt_cache_baseline"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_tiers"] = list(self.changed_tiers)
        payload["diagnostics"] = dict(self.diagnostics)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptCacheBaselineRecord":
        return cls(
            baseline_id=str(payload.get("baseline_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            invocation_kind=str(payload.get("invocation_kind") or ""),
            status=_baseline_status(payload.get("status")),
            generation=_int(payload.get("generation")),
            stable_prefix_hash=str(payload.get("stable_prefix_hash") or ""),
            provider_global_prefix_hash=str(payload.get("provider_global_prefix_hash") or ""),
            session_prefix_hash=str(payload.get("session_prefix_hash") or ""),
            task_prefix_hash=str(payload.get("task_prefix_hash") or ""),
            memory_segment_hash=str(payload.get("memory_segment_hash") or ""),
            previous_baseline_ref=str(payload.get("previous_baseline_ref") or ""),
            changed_tiers=tuple(str(item) for item in list(payload.get("changed_tiers") or []) if str(item or "")),
            reset_reason=str(payload.get("reset_reason") or ""),
            reset_ref=str(payload.get("reset_ref") or ""),
            created_at=float(payload.get("created_at") or 0.0),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_cache_baseline"),
        )


class PromptCacheBaselineTracker:
    """Tracks cross-turn prompt-cache baselines without owning prompt assembly."""

    def build_active_record(
        self,
        *,
        segment_map: PromptSegmentMap,
        model_request: Any | None = None,
        previous_records: list[PromptCacheBaselineRecord] | tuple[PromptCacheBaselineRecord, ...] = (),
        created_at: float | None = None,
    ) -> PromptCacheBaselineRecord:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        invocation_kind = _invocation_kind(segment_map)
        provider = str(segment_map.provider or "")
        model = str(segment_map.model or "")
        previous, generation = self.resolve_previous_active(
            previous_records,
            invocation_kind=invocation_kind,
            provider=provider,
            model=model,
        )
        hashes = _baseline_hashes(segment_map=segment_map, model_request=model_request)
        changed_tiers = _changed_tiers(previous, hashes)
        baseline_id = _baseline_id(
            request_id=segment_map.request_id,
            status="active",
            generation=generation,
            created_at=timestamp,
        )
        return PromptCacheBaselineRecord(
            baseline_id=baseline_id,
            request_id=segment_map.request_id,
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            provider=provider,
            model=model,
            invocation_kind=invocation_kind,
            status="active",
            generation=generation,
            stable_prefix_hash=hashes["stable"],
            provider_global_prefix_hash=hashes["provider_global"],
            session_prefix_hash=hashes["session"],
            task_prefix_hash=hashes["task"],
            memory_segment_hash=hashes["memory"],
            previous_baseline_ref=previous.baseline_id if previous is not None else "",
            changed_tiers=changed_tiers,
            created_at=timestamp,
            diagnostics={
                "baseline_segments": _baseline_segment_diagnostics(segment_map),
                "reset_seen": previous is None and generation > 0,
                "has_previous_active_baseline": previous is not None,
            },
        )

    def build_invalidation_record(
        self,
        *,
        previous_records: list[PromptCacheBaselineRecord] | tuple[PromptCacheBaselineRecord, ...] = (),
        request_id: str = "",
        run_id: str = "",
        task_run_id: str = "",
        session_id: str = "",
        invocation_kind: str = "",
        provider: str = "",
        model: str = "",
        reason: str,
        reset_ref: str = "",
        diagnostics: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> PromptCacheBaselineRecord:
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        previous, previous_generation = self.resolve_previous_active(
            previous_records,
            invocation_kind=invocation_kind,
            provider=provider,
            model=model,
        )
        latest_generation = max(
            [previous_generation, *[int(record.generation or 0) for record in previous_records]],
            default=0,
        )
        generation = latest_generation + 1
        resolved_request_id = str(request_id or f"baseline-reset:{uuid.uuid4().hex[:12]}")
        return PromptCacheBaselineRecord(
            baseline_id=_baseline_id(
                request_id=resolved_request_id,
                status="invalidated",
                generation=generation,
                created_at=timestamp,
            ),
            request_id=resolved_request_id,
            run_id=str(run_id or ""),
            task_run_id=str(task_run_id or ""),
            session_id=str(session_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            invocation_kind=str(invocation_kind or ""),
            status="invalidated",
            generation=generation,
            previous_baseline_ref=previous.baseline_id if previous is not None else "",
            reset_reason=str(reason or "baseline_reset"),
            reset_ref=str(reset_ref or ""),
            created_at=timestamp,
            diagnostics=dict(diagnostics or {}),
        )

    def resolve_previous_active(
        self,
        records: list[PromptCacheBaselineRecord] | tuple[PromptCacheBaselineRecord, ...],
        *,
        invocation_kind: str,
        provider: str,
        model: str,
    ) -> tuple[PromptCacheBaselineRecord | None, int]:
        relevant = [
            record
            for record in list(records or [])
            if _record_matches(record, invocation_kind=invocation_kind, provider=provider, model=model)
        ]
        if not relevant:
            return None, 0
        latest = sorted(relevant, key=lambda item: float(item.created_at or 0.0))[-1]
        if latest.status == "invalidated":
            return None, int(latest.generation or 0)
        return latest, int(latest.generation or 0)


def _baseline_hashes(*, segment_map: PromptSegmentMap, model_request: Any | None) -> dict[str, str]:
    tier_hashes = _tier_prefix_hashes(segment_map.segments)
    return {
        "stable": str(getattr(model_request, "stable_prefix_hash", "") or dict(segment_map.metadata or {}).get("stable_prefix_hash") or tier_hashes["stable"]),
        "provider_global": str(
            getattr(model_request, "provider_global_prefix_hash", "")
            or dict(segment_map.metadata or {}).get("provider_global_prefix_hash")
            or tier_hashes["provider_global"]
        ),
        "session": str(getattr(model_request, "session_prefix_hash", "") or dict(segment_map.metadata or {}).get("session_prefix_hash") or tier_hashes["session"]),
        "task": str(getattr(model_request, "task_prefix_hash", "") or dict(segment_map.metadata or {}).get("task_prefix_hash") or tier_hashes["task"]),
        "memory": _memory_segment_hash(segment_map.segments),
    }


def _tier_prefix_hashes(segments: tuple[PromptSegment, ...]) -> dict[str, str]:
    provider_global: list[PromptSegment] = []
    session: list[PromptSegment] = []
    task: list[PromptSegment] = []
    stable: list[PromptSegment] = []
    for segment in segments:
        if not is_cache_eligible_prefix(
            cache_role=segment.cache_role,
            prefix_tier=getattr(segment, "prefix_tier", ""),
        ):
            break
        stable.append(segment)
        tier = str(getattr(segment, "prefix_tier", "") or "none")
        if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=tier, tier="provider_global") and len(provider_global) == len(stable) - 1:
            provider_global.append(segment)
        if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=tier, tier="session") and len(session) == len(stable) - 1:
            session.append(segment)
        if is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=tier, tier="task") and len(task) == len(stable) - 1:
            task.append(segment)
    return {
        "stable": _segments_hash(stable),
        "provider_global": _segments_hash(provider_global),
        "session": _segments_hash(session),
        "task": _segments_hash(task),
    }


def _baseline_segment_diagnostics(segment_map: PromptSegmentMap) -> dict[str, Any]:
    segments = list(segment_map.segments or [])
    stable = _stable_prefix_segments(segments)
    provider_global = _prefix_tier_segments(stable, {"provider_global"})
    session = _prefix_tier_segments(stable, {"provider_global", "session"})
    task = _prefix_tier_segments(stable, {"provider_global", "session", "task"})
    memory = [segment for segment in segments if _is_memory_segment(segment)]
    return {
        "stable": _segment_group_diagnostics(stable),
        "provider_global": _segment_group_diagnostics(provider_global),
        "session": _segment_group_diagnostics(session),
        "task": _segment_group_diagnostics(task),
        "memory": _segment_group_diagnostics(memory),
    }


def _stable_prefix_segments(segments: list[PromptSegment]) -> list[PromptSegment]:
    result: list[PromptSegment] = []
    for segment in segments:
        if not is_cache_eligible_prefix(
            cache_role=segment.cache_role,
            prefix_tier=getattr(segment, "prefix_tier", ""),
        ):
            break
        result.append(segment)
    return result


def _prefix_tier_segments(segments: list[PromptSegment], allowed_tiers: set[str]) -> list[PromptSegment]:
    result: list[PromptSegment] = []
    for segment in segments:
        tier = str(getattr(segment, "prefix_tier", "") or "none")
        target = (
            "provider_global"
            if allowed_tiers == {"provider_global"}
            else "session"
            if allowed_tiers == {"provider_global", "session"}
            else "task"
        )
        if not is_prefix_eligible_for_tier(cache_role=segment.cache_role, prefix_tier=tier, tier=target):
            break
        result.append(segment)
    return result


def _segment_group_diagnostics(segments: list[PromptSegment]) -> dict[str, Any]:
    return {
        "segment_count": len(segments),
        "predicted_tokens": sum(int(segment.predicted_tokens or 0) for segment in segments),
        "content_hash": _segments_hash(segments),
        "segment_ids": [segment.segment_id for segment in segments],
        "kinds": [segment.kind for segment in segments],
    }


def _memory_segment_hash(segments: tuple[PromptSegment, ...]) -> str:
    memory_segments = [segment for segment in list(segments or []) if _is_memory_segment(segment)]
    return _segments_hash(memory_segments)


def _is_memory_segment(segment: PromptSegment) -> bool:
    metadata = dict(segment.metadata or {})
    haystack = " ".join(
        [
            str(segment.kind or ""),
            str(segment.source or ""),
            str(metadata.get("planned_segment_id") or ""),
            str(metadata.get("planned_content_hash") or ""),
            str(metadata.get("source_ref") or ""),
            str(metadata.get("authority") or ""),
        ]
    ).lower()
    return "memory" in haystack or "session_emphasis" in haystack or "durable" in haystack


def _segments_hash(segments: list[PromptSegment]) -> str:
    if not segments:
        return ""
    return stable_text_hash("|".join(segment.content_hash for segment in segments))


def _changed_tiers(previous: PromptCacheBaselineRecord | None, hashes: dict[str, str]) -> tuple[str, ...]:
    if previous is None:
        return ()
    checks = {
        "stable": previous.stable_prefix_hash,
        "provider_global": previous.provider_global_prefix_hash,
        "session": previous.session_prefix_hash,
        "task": previous.task_prefix_hash,
        "memory": previous.memory_segment_hash,
    }
    return tuple(tier for tier, previous_hash in checks.items() if str(previous_hash or "") != str(hashes.get(tier) or ""))


def _record_matches(
    record: PromptCacheBaselineRecord,
    *,
    invocation_kind: str,
    provider: str,
    model: str,
) -> bool:
    return (
        _matches_or_wildcard(record.invocation_kind, invocation_kind)
        and _matches_or_wildcard(record.provider, provider)
        and _matches_or_wildcard(record.model, model)
    )


def _matches_or_wildcard(record_value: str, current_value: str) -> bool:
    normalized = str(record_value or "")
    current = str(current_value or "")
    return not normalized or not current or normalized == current


def _invocation_kind(segment_map: PromptSegmentMap) -> str:
    metadata = dict(segment_map.metadata or {})
    return str(metadata.get("source") or metadata.get("call_kind") or "")


def _baseline_id(*, request_id: str, status: str, generation: int, created_at: float) -> str:
    seed = json.dumps(
        {
            "request_id": request_id,
            "status": status,
            "generation": generation,
            "created_at": created_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"pcachebaseline:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _baseline_status(value: Any) -> PromptCacheBaselineStatus:
    status = str(value or "").strip()
    if status in {"active", "invalidated"}:
        return status  # type: ignore[return-value]
    return "active"


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
