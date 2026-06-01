from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from typing import Any

from .models import ModelTokenUsageRecord, PromptCacheRecord, PromptSegmentMap


def stable_text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def prompt_cache_key(*, scope: str, inputs: dict[str, Any]) -> str:
    payload = json.dumps(_json_stable(inputs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
    safe_scope = str(scope or "prompt").strip().replace(" ", "_")
    return f"{safe_scope}:{digest}"


class PromptCachePlanner:
    """Builds request-level cache records from stable prefix segments."""

    def plan(
        self,
        segment_map: PromptSegmentMap,
        *,
        provider: str = "",
        model: str = "",
        ttl_seconds: int = 300,
        created_at: float | None = None,
    ) -> PromptCacheRecord:
        stable_prefix = []
        for segment in segment_map.segments:
            if segment.cache_role in {"cacheable_prefix", "session_stable"}:
                stable_prefix.append(segment)
                continue
            break
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        if not stable_prefix:
            return PromptCacheRecord(
                cache_record_id=f"pcache:{segment_map.request_id}",
                request_id=segment_map.request_id,
                provider=str(provider or segment_map.provider or ""),
                model=str(model or segment_map.model or ""),
                run_id=segment_map.run_id,
                task_run_id=segment_map.task_run_id,
                session_id=segment_map.session_id,
                scope="none",
                status="bypassed",
                cache_safety_reasons=("no_stable_prefix_boundary",),
                created_at=timestamp,
            )
        boundary = stable_prefix[-1]
        prefix_hash = stable_text_hash("|".join(segment.content_hash for segment in stable_prefix))
        key = prompt_cache_key(
            scope="model_request_prefix",
            inputs={
                "provider": str(provider or segment_map.provider or ""),
                "model": str(model or segment_map.model or ""),
                "prefix_hash": prefix_hash,
                "boundary_kind": boundary.kind,
                "boundary_ordinal": boundary.ordinal,
                "boundary_content_hash": boundary.content_hash,
            },
        )
        return PromptCacheRecord(
            cache_record_id=f"pcache:{segment_map.request_id}",
            request_id=segment_map.request_id,
            provider=str(provider or segment_map.provider or ""),
            model=str(model or segment_map.model or ""),
            run_id=segment_map.run_id,
            task_run_id=segment_map.task_run_id,
            session_id=segment_map.session_id,
            cache_key=key,
            prefix_hash=prefix_hash,
            boundary_segment_id=boundary.segment_id,
            scope="session" if segment_map.session_id else "global",
            ttl_seconds=max(0, int(ttl_seconds or 0)),
            status="eligible",
            cache_safety_reasons=(),
            created_at=timestamp,
            diagnostics={
                "stable_prefix_segment_count": len(stable_prefix),
                "stable_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in stable_prefix),
            },
        )

    def with_provider_usage(
        self,
        record: PromptCacheRecord,
        usage: ModelTokenUsageRecord | None,
    ) -> PromptCacheRecord:
        if usage is None:
            return record
        cached = max(int(usage.cached_tokens or 0), int(usage.cache_read_tokens or 0))
        creation = int(usage.cache_creation_tokens or 0)
        if record.status == "bypassed":
            status = "bypassed"
        elif cached > 0:
            status = "hit"
        else:
            status = "miss"
        return replace(
            record,
            status=status,
            cached_tokens=cached,
            cache_read_tokens=int(usage.cache_read_tokens or 0),
            cache_creation_tokens=creation,
            cache_savings_tokens=cached,
            diagnostics={
                **dict(record.diagnostics or {}),
                "provider_usage_ref": usage.usage_id,
                "provider_cached_tokens": cached,
            },
        )


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
