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
        created_at: float | None = None,
    ) -> PromptCacheRecord:
        combined_stable_prefix = []
        provider_global_prefix = []
        session_prefix = []
        task_prefix = []
        collect_provider_global = True
        collect_session = True
        collect_task = True
        for segment in segment_map.segments:
            if segment.cache_role in {"cacheable_prefix", "session_stable"}:
                combined_stable_prefix.append(segment)
            tier = str(getattr(segment, "prefix_tier", "") or "none")
            if collect_provider_global and tier == "provider_global":
                provider_global_prefix.append(segment)
            else:
                collect_provider_global = False
            if collect_session and tier in {"provider_global", "session"}:
                session_prefix.append(segment)
            else:
                collect_session = False
            if collect_task and tier in {"provider_global", "session", "task"}:
                task_prefix.append(segment)
            else:
                collect_task = False
            if not collect_task and not (segment.cache_role in {"cacheable_prefix", "session_stable"}):
                break
        timestamp = time.time() if created_at is None else float(created_at or 0.0)
        key_tier, key_prefix = _primary_cache_key_prefix(
            provider_global_prefix=provider_global_prefix,
            session_prefix=session_prefix,
            task_prefix=task_prefix,
        )
        if not key_prefix:
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
                diagnostics=_prefix_diagnostics(
                    combined_stable_prefix=combined_stable_prefix,
                    provider_global_prefix=provider_global_prefix,
                    session_prefix=session_prefix,
                    task_prefix=task_prefix,
                ),
            )
        boundary = key_prefix[-1]
        prefix_hash = stable_text_hash("|".join(segment.content_hash for segment in key_prefix))
        key = prompt_cache_key(
            scope="model_request_prefix",
            inputs={
                "provider": str(provider or segment_map.provider or ""),
                "model": str(model or segment_map.model or ""),
                "prefix_key_tier": key_tier,
                "prefix_hash": prefix_hash,
                "boundary_kind": boundary.kind,
                "boundary_ordinal": boundary.ordinal,
                "boundary_content_hash": boundary.content_hash,
            },
        )
        diagnostics = _prefix_diagnostics(
            combined_stable_prefix=combined_stable_prefix,
            provider_global_prefix=provider_global_prefix,
            session_prefix=session_prefix,
            task_prefix=task_prefix,
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
            status="eligible",
            cache_safety_reasons=(),
            created_at=timestamp,
            diagnostics={
                **diagnostics,
                "prefix_key_tier": key_tier,
                "stable_prefix_segment_count": len(combined_stable_prefix),
                "stable_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in combined_stable_prefix),
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


def _prefix_diagnostics(
    *,
    combined_stable_prefix: list[Any],
    provider_global_prefix: list[Any],
    session_prefix: list[Any],
    task_prefix: list[Any],
) -> dict[str, Any]:
    return {
        "combined_stable_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in combined_stable_prefix)) if combined_stable_prefix else "",
        "provider_global_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in provider_global_prefix)) if provider_global_prefix else "",
        "session_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in session_prefix)) if session_prefix else "",
        "task_prefix_hash": stable_text_hash("|".join(segment.content_hash for segment in task_prefix)) if task_prefix else "",
        "provider_global_prefix_segment_count": len(provider_global_prefix),
        "session_prefix_segment_count": len(session_prefix),
        "task_prefix_segment_count": len(task_prefix),
        "provider_global_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in provider_global_prefix),
        "session_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in session_prefix),
        "task_prefix_predicted_tokens": sum(int(item.predicted_tokens or 0) for item in task_prefix),
    }


def _primary_cache_key_prefix(
    *,
    provider_global_prefix: list[Any],
    session_prefix: list[Any],
    task_prefix: list[Any],
) -> tuple[str, list[Any]]:
    if task_prefix:
        return "task", task_prefix
    if session_prefix:
        return "session", session_prefix
    if provider_global_prefix:
        return "provider_global", provider_global_prefix
    return "none", []
