from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SegmentCacheRole = Literal["cacheable_prefix", "session_stable", "volatile", "never_cache"]
SegmentPrefixTier = Literal["provider_global", "session", "task", "volatile", "none"]
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
    prefix_tier: SegmentPrefixTier = "volatile"
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
    provider_global_prefix_hash: str = ""
    session_prefix_hash: str = ""
    task_prefix_hash: str = ""
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
    provider_global_hash_parts: list[str] = []
    session_hash_parts: list[str] = []
    task_hash_parts: list[str] = []
    collect_stable_prefix = True
    collect_provider_global_prefix = True
    collect_session_prefix = True
    collect_task_prefix = True
    for index, spec in enumerate(list(message_specs or [])):
        content = str(spec.get("content") or "")
        role = str(spec.get("role") or "user")
        kind = str(spec.get("kind") or "unknown_unplanned").strip() or "unknown_unplanned"
        cache_role = _cache_role(spec.get("cache_role"))
        cache_scope = str(spec.get("cache_scope") or "none")
        prefix_tier = _prefix_tier(spec.get("prefix_tier"), cache_scope=cache_scope, cache_role=cache_role)
        _validate_prefix_tier_content(kind=kind, prefix_tier=prefix_tier, content=content)
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
            cache_scope=cache_scope,
            cache_role=cache_role,
            prefix_tier=prefix_tier,
            compression_role=_compression_role(spec.get("compression_role")),
            content_hash=content_hash,
            model_message_hash=model_message_hash,
            byte_length=len(content.encode("utf-8", errors="ignore")),
            metadata=dict(spec.get("metadata") or {}),
        )
        segments.append(segment)
        if collect_stable_prefix and cache_role in {"cacheable_prefix", "session_stable"}:
            stable_hash_parts.append(model_message_hash)
        else:
            collect_stable_prefix = False
        if collect_provider_global_prefix and prefix_tier == "provider_global":
            provider_global_hash_parts.append(model_message_hash)
        else:
            collect_provider_global_prefix = False
        if collect_session_prefix and prefix_tier in {"provider_global", "session"}:
            session_hash_parts.append(model_message_hash)
        else:
            collect_session_prefix = False
        if collect_task_prefix and prefix_tier in {"provider_global", "session", "task"}:
            task_hash_parts.append(model_message_hash)
        else:
            collect_task_prefix = False
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
                "prefix_tier": item.prefix_tier,
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
        provider_global_prefix_hash=stable_text_hash("|".join(provider_global_hash_parts)) if provider_global_hash_parts else "",
        session_prefix_hash=stable_text_hash("|".join(session_hash_parts)) if session_hash_parts else "",
        task_prefix_hash=stable_text_hash("|".join(task_hash_parts)) if task_hash_parts else "",
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


def _prefix_tier(value: Any, *, cache_scope: str, cache_role: str) -> SegmentPrefixTier:
    normalized = str(value or "").strip()
    if normalized in {"provider_global", "session", "task", "volatile", "none"}:
        return normalized  # type: ignore[return-value]
    if cache_role == "cacheable_prefix":
        return "provider_global"
    if cache_role == "session_stable":
        scope = str(cache_scope or "").strip()
        if scope == "task":
            return "task"
        if scope == "session":
            return "session"
        if scope == "global":
            return "provider_global"
        return "session"
    if cache_role == "volatile":
        return "volatile"
    return "none"


def _compression_role(value: Any) -> SegmentCompressionRole:
    normalized = str(value or "").strip()
    if normalized in {"preserve", "summarize", "drop_if_cold", "ref_only"}:
        return normalized  # type: ignore[return-value]
    return "summarize"


def _requires_dynamic_context_report(*, kind: str, cache_role: str) -> bool:
    if str(cache_role or "") == "volatile":
        return True
    return str(kind or "").startswith("dynamic")


RUNTIME_INSTANCE_FIELDS = {
    "task_run_id",
    "graph_run_id",
    "graph_work_order_id",
    "work_order_id",
    "turn_id",
    "agent_invocation_id",
    "runtime_assembly_id",
    "attempt",
    "executor_status",
    "runtime_controls",
    "state_refs",
    "observations",
    "current_facts",
    "pending_user_steers",
    "active_contract_revisions",
}

TASK_SEMANTIC_FIELDS = {
    "task_id",
    "contract_id",
    "node_id",
    "task_contract_ref",
    "owner_agent_seat_id",
}


def _validate_prefix_tier_content(*, kind: str, prefix_tier: SegmentPrefixTier, content: str) -> None:
    if prefix_tier in {"volatile", "none"}:
        return
    payload = _parse_segment_payload(content)
    if payload is None:
        return
    keys = _nested_keys(payload)
    runtime_fields = sorted(_runtime_instance_value_fields(payload))
    if runtime_fields:
        raise ValueError(
            "stable prefix segment contains runtime instance fields: "
            f"kind={kind} prefix_tier={prefix_tier} fields={','.join(runtime_fields)}"
        )
    if prefix_tier in {"provider_global", "session"}:
        semantic_fields = sorted(keys & TASK_SEMANTIC_FIELDS)
        if semantic_fields:
            raise ValueError(
                "provider/session prefix segment contains task semantic fields: "
                f"kind={kind} prefix_tier={prefix_tier} fields={','.join(semantic_fields)}"
            )


def _parse_segment_payload(content: str) -> Any | None:
    text = str(content or "").strip()
    if not text:
        return None
    candidates = [text]
    if "\n" in text:
        candidates.append(text.split("\n", 1)[1].strip())
    for candidate in candidates:
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _nested_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            result.add(str(key))
            result.update(_nested_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_nested_keys(item))
    return result


def _runtime_instance_value_fields(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        if _looks_like_json_schema_object(value):
            return result
        for key, item in value.items():
            text_key = str(key)
            if text_key in {"schema", "input_schema", "input_schema_summary", "properties"}:
                continue
            if text_key in RUNTIME_INSTANCE_FIELDS and not _looks_like_schema_field_definition(item):
                result.add(text_key)
            result.update(_runtime_instance_value_fields(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_runtime_instance_value_fields(item))
    return result


def _looks_like_json_schema_object(value: dict[str, Any]) -> bool:
    return (
        str(value.get("type") or "") == "object"
        and isinstance(value.get("properties"), dict)
        and any(key in value for key in ("required", "additionalProperties", "$schema"))
    )


def _looks_like_schema_field_definition(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    schema_keys = {"type", "description", "enum", "items", "properties", "required", "default", "additionalProperties"}
    return bool(set(str(key) for key in value.keys()) & schema_keys)
