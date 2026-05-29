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
        if cache_record.status != "miss":
            return None
        if not cache_record.cache_key or not cache_record.prefix_hash:
            return None
        cached_tokens = max(int(provider_usage.cached_tokens or 0), int(provider_usage.cache_read_tokens or 0))
        if cached_tokens > 0:
            return None
        repeated_prefix = [
            record
            for record in previous_cache_records
            if record.cache_key == cache_record.cache_key
            and record.request_id != cache_record.request_id
            and record.status in {"eligible", "hit", "miss"}
        ]
        if not repeated_prefix:
            return None
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        return PromptCacheBreakRecord(
            break_id=f"pcachebreak:{cache_record.request_id}",
            request_id=cache_record.request_id,
            provider=cache_record.provider,
            model=cache_record.model,
            task_run_id=cache_record.task_run_id,
            session_id=cache_record.session_id,
            cache_key=cache_record.cache_key,
            prefix_hash=cache_record.prefix_hash,
            reason="provider_reported_miss_for_repeated_stable_prefix",
            created_at=timestamp,
            diagnostics={
                "provider_usage_ref": provider_usage.usage_id,
                "previous_request_ids": [record.request_id for record in repeated_prefix[-5:]],
                "boundary_segment_id": cache_record.boundary_segment_id,
            },
        )
