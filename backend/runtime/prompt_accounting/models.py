from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


TokenUsageSource = Literal["provider_usage", "local_prediction", "trace_estimate"]
PromptCacheStatus = Literal["eligible", "hit", "miss", "bypassed", "invalidated"]
PromptCacheScope = Literal["global", "org", "session", "task", "none"]
PromptCacheRole = Literal["cacheable_prefix", "session_stable", "volatile", "never_cache"]
CompressionRole = Literal["preserve", "summarize", "drop_if_cold", "ref_only"]


@dataclass(frozen=True, slots=True)
class PromptSegment:
    segment_id: str
    request_id: str
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    kind: str = "unknown_unplanned"
    ordinal: int = 0
    role: str = ""
    content_hash: str = ""
    byte_length: int = 0
    predicted_tokens: int = 0
    cache_role: PromptCacheRole = "volatile"
    compression_role: CompressionRole = "summarize"
    source: str = ""
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prompt_segment"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromptSegmentMap:
    request_id: str
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    provider: str = ""
    model: str = ""
    segments: tuple[PromptSegment, ...] = ()
    canonical_hash: str = ""
    byte_length: int = 0
    predicted_prompt_tokens: int = 0
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prompt_segment_map"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["segments"] = [segment.to_dict() for segment in self.segments]
        return payload


@dataclass(frozen=True, slots=True)
class ModelTokenUsageRecord:
    usage_id: str
    request_id: str
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    provider: str = ""
    model: str = ""
    source: TokenUsageSource = "local_prediction"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.model_token_usage"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ModelTokenUsageRecord":
        return cls(
            usage_id=str(payload.get("usage_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            source=_usage_source(payload.get("source")),
            prompt_tokens=_int(payload.get("prompt_tokens")),
            completion_tokens=_int(payload.get("completion_tokens")),
            reasoning_tokens=_int(payload.get("reasoning_tokens")),
            cached_tokens=_int(payload.get("cached_tokens")),
            cache_creation_tokens=_int(payload.get("cache_creation_tokens")),
            cache_read_tokens=_int(payload.get("cache_read_tokens")),
            total_tokens=_int(payload.get("total_tokens")),
            created_at=float(payload.get("created_at") or 0.0),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.model_token_usage"),
        )


@dataclass(frozen=True, slots=True)
class PromptCacheRecord:
    cache_record_id: str
    request_id: str
    provider: str = ""
    model: str = ""
    run_id: str = ""
    task_run_id: str = ""
    session_id: str = ""
    cache_key: str = ""
    prefix_hash: str = ""
    boundary_segment_id: str = ""
    scope: PromptCacheScope = "none"
    ttl_seconds: int = 0
    status: PromptCacheStatus = "bypassed"
    cached_tokens: int = 0
    cache_savings_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cache_safety_reasons: tuple[str, ...] = ()
    created_at: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.prompt_accounting.prompt_cache_record"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cache_safety_reasons"] = list(self.cache_safety_reasons)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PromptCacheRecord":
        return cls(
            cache_record_id=str(payload.get("cache_record_id") or ""),
            request_id=str(payload.get("request_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            run_id=str(payload.get("run_id") or payload.get("task_run_id") or ""),
            task_run_id=str(payload.get("task_run_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            cache_key=str(payload.get("cache_key") or ""),
            prefix_hash=str(payload.get("prefix_hash") or ""),
            boundary_segment_id=str(payload.get("boundary_segment_id") or ""),
            scope=_cache_scope(payload.get("scope")),
            ttl_seconds=_int(payload.get("ttl_seconds")),
            status=_cache_status(payload.get("status")),
            cached_tokens=_int(payload.get("cached_tokens")),
            cache_savings_tokens=_int(payload.get("cache_savings_tokens")),
            cache_creation_tokens=_int(payload.get("cache_creation_tokens")),
            cache_read_tokens=_int(payload.get("cache_read_tokens")),
            cache_safety_reasons=tuple(str(item) for item in list(payload.get("cache_safety_reasons") or [])),
            created_at=float(payload.get("created_at") or 0.0),
            diagnostics=dict(payload.get("diagnostics") or {}),
            authority=str(payload.get("authority") or "runtime.prompt_accounting.prompt_cache_record"),
        )


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_source(value: Any) -> TokenUsageSource:
    source = str(value or "").strip()
    if source in {"provider_usage", "local_prediction", "trace_estimate"}:
        return source  # type: ignore[return-value]
    return "local_prediction"


def _cache_status(value: Any) -> PromptCacheStatus:
    status = str(value or "").strip()
    if status in {"eligible", "hit", "miss", "bypassed", "invalidated"}:
        return status  # type: ignore[return-value]
    return "bypassed"


def _cache_scope(value: Any) -> PromptCacheScope:
    scope = str(value or "").strip()
    if scope in {"global", "org", "session", "task", "none"}:
        return scope  # type: ignore[return-value]
    return "none"
