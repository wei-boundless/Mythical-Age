from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SegmentCacheRole = Literal["cacheable_prefix", "session_stable", "volatile", "never_cache"]
SegmentCompressionRole = Literal["preserve", "summarize", "drop_if_cold", "ref_only"]


@dataclass(frozen=True, slots=True)
class PromptSegmentPlanSegment:
    segment_id: str
    kind: str
    ordinal: int
    model_message_index: int
    model_message_role: str
    source_ref: str = ""
    cache_scope: str = "none"
    cache_role: SegmentCacheRole = "volatile"
    compression_role: SegmentCompressionRole = "summarize"
    content_hash: str = ""
    model_message_hash: str = ""
    byte_length: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_segment_plan.segment"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class PromptSegmentPlan:
    segment_plan_id: str
    packet_id: str
    invocation_kind: str
    segments: tuple[PromptSegmentPlanSegment, ...] = ()
    provider_policy_ref: str = ""
    stable_prefix_hash: str = ""
    authority: str = "runtime.prompt_segment_plan"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["segments"] = [segment.to_dict() for segment in self.segments]
        return payload


def build_prompt_segment_plan(
    *,
    packet_id: str,
    invocation_kind: str,
    message_specs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    enforce_dynamic_context_reports: bool = False,
) -> PromptSegmentPlan:
    segments: list[PromptSegmentPlanSegment] = []
    stable_hash_parts: list[str] = []
    collect_stable_prefix = True
    for index, spec in enumerate(list(message_specs or [])):
        content = str(spec.get("content") or "")
        role = str(spec.get("role") or "user")
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        cache_role = _cache_role(spec.get("cache_role"))
        if enforce_dynamic_context_reports and _requires_dynamic_context_report(kind=kind, cache_role=cache_role):
            metadata = dict(spec.get("metadata") or {})
            if not (metadata.get("dynamic_context_report_ref") or metadata.get("volatility_reason")):
                raise ValueError(f"dynamic/volatile segment requires dynamic context metadata: {kind}")
        content_hash = stable_text_hash(content)
        model_message_hash = stable_text_hash(_canonical_json({"role": role, "content": content}))
        segment = PromptSegmentPlanSegment(
            segment_id=_segment_id(packet_id=packet_id, ordinal=index + 1, kind=kind, content_hash=content_hash),
            kind=kind,
            ordinal=index + 1,
            model_message_index=index,
            model_message_role=role,
            source_ref=str(spec.get("source_ref") or ""),
            cache_scope=str(spec.get("cache_scope") or "none"),
            cache_role=cache_role,
            compression_role=_compression_role(spec.get("compression_role")),
            content_hash=content_hash,
            model_message_hash=model_message_hash,
            byte_length=len(content.encode("utf-8", errors="ignore")),
            metadata=dict(spec.get("metadata") or {}),
        )
        segments.append(segment)
        if collect_stable_prefix and cache_role in {"cacheable_prefix", "session_stable"}:
            stable_hash_parts.append(model_message_hash)
            continue
        collect_stable_prefix = False
    seed = {
        "packet_id": packet_id,
        "invocation_kind": invocation_kind,
        "segments": [
            {
                "kind": item.kind,
                "ordinal": item.ordinal,
                "role": item.model_message_role,
                "source_ref": item.source_ref,
                "cache_role": item.cache_role,
                "content_hash": item.content_hash,
                "model_message_hash": item.model_message_hash,
            }
            for item in segments
        ],
    }
    return PromptSegmentPlan(
        segment_plan_id="segplan:" + _digest(json.dumps(seed, ensure_ascii=False, sort_keys=True)),
        packet_id=str(packet_id or ""),
        invocation_kind=str(invocation_kind or ""),
        segments=tuple(segments),
        stable_prefix_hash=stable_text_hash("|".join(stable_hash_parts)) if stable_hash_parts else "",
    )


def stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def _segment_id(*, packet_id: str, ordinal: int, kind: str, content_hash: str) -> str:
    digest = str(content_hash or "").split(":", 1)[-1][:12]
    return f"segplan:{packet_id}:{ordinal}:{kind}:{digest}"


def _digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _canonical_json(value: Any) -> str:
    return json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _cache_role(value: Any) -> SegmentCacheRole:
    normalized = str(value or "").strip()
    if normalized in {"cacheable_prefix", "session_stable", "volatile", "never_cache"}:
        return normalized  # type: ignore[return-value]
    return "volatile"


def _compression_role(value: Any) -> SegmentCompressionRole:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized  # type: ignore[return-value]
    return "summarize"


def _requires_dynamic_context_report(*, kind: str, cache_role: str) -> bool:
    if str(cache_role or "") == "volatile":
        return True
    return str(kind or "").startswith("dynamic")
