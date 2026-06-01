from __future__ import annotations

import time
from typing import Any

from .models import ModelTokenUsageRecord


def extract_provider_usage(
    response: Any,
    *,
    request_id: str,
    provider: str = "",
    model: str = "",
    run_id: str = "",
    task_run_id: str = "",
    session_id: str = "",
    created_at: float | None = None,
) -> ModelTokenUsageRecord | None:
    usage = _extract_usage_payload(response)
    if not usage:
        return None
    prompt_tokens = _first_int(
        usage,
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "input_token_count",
    )
    deepseek_cache_hit_tokens = _first_int(usage, "prompt_cache_hit_tokens")
    deepseek_cache_miss_tokens = _first_int(usage, "prompt_cache_miss_tokens")
    if prompt_tokens <= 0 and (deepseek_cache_hit_tokens > 0 or deepseek_cache_miss_tokens > 0):
        prompt_tokens = deepseek_cache_hit_tokens + deepseek_cache_miss_tokens
    completion_tokens = _first_int(
        usage,
        "completion_tokens",
        "output_tokens",
        "completion_token_count",
        "output_token_count",
    )
    reasoning_tokens = _nested_first_int(
        usage,
        ("completion_tokens_details", "reasoning_tokens"),
        ("output_token_details", "reasoning_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
        ("completion_token_details", "reasoning_tokens"),
        ("reasoning", "tokens"),
    )
    cached_tokens = _nested_first_int(
        usage,
        ("prompt_tokens_details", "cached_tokens"),
        ("input_token_details", "cache_read"),
        ("input_token_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
        ("cache", "read_tokens"),
    )
    cached_tokens = max(cached_tokens, deepseek_cache_hit_tokens)
    cache_creation_tokens = _nested_first_int(
        usage,
        ("input_token_details", "cache_creation"),
        ("input_tokens_details", "cache_creation"),
        ("cache", "creation_tokens"),
    )
    cache_creation_tokens = max(
        cache_creation_tokens,
        _first_int(usage, "cache_creation_input_tokens", "cache_creation_tokens"),
    )
    cache_read_tokens = _first_int(usage, "cache_read_input_tokens", "cache_read_tokens")
    cache_read_tokens = max(cache_read_tokens, cached_tokens)
    total_tokens = _first_int(usage, "total_tokens", "total_token_count")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens + reasoning_tokens
    if prompt_tokens <= 0 and completion_tokens <= 0 and total_tokens <= 0 and cached_tokens <= 0:
        return None
    timestamp = time.time() if created_at is None else float(created_at or 0.0)
    return ModelTokenUsageRecord(
        usage_id=f"tokuse:{request_id}:provider_usage",
        request_id=request_id,
        run_id=str(run_id or task_run_id or ""),
        task_run_id=str(task_run_id or ""),
        session_id=str(session_id or ""),
        provider=str(provider or _response_provider(response) or ""),
        model=str(model or _response_model(response) or ""),
        source="provider_usage",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        created_at=timestamp,
        diagnostics={"raw_usage_keys": sorted(str(key) for key in usage.keys())},
    )


def _extract_usage_payload(response: Any) -> dict[str, Any]:
    candidates: list[Any] = []
    if isinstance(response, dict):
        candidates.extend([response.get("usage"), response.get("usage_metadata"), response.get("token_usage"), response])
    for attr_name in ("usage_metadata", "usage", "token_usage"):
        candidates.append(getattr(response, attr_name, None))
    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        candidates.extend([response_metadata.get("token_usage"), response_metadata.get("usage"), response_metadata])
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        candidates.extend([additional_kwargs.get("usage"), additional_kwargs.get("token_usage"), additional_kwargs])
    for candidate in candidates:
        if isinstance(candidate, dict):
            payload = _flatten_usage_payload(candidate)
            if _looks_like_usage(payload):
                return payload
    return {}


def _flatten_usage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    usage = dict(payload)
    for key in ("usage", "usage_metadata", "token_usage"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            usage.update(nested)
    return usage


def _looks_like_usage(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    return bool(
        keys.intersection(
            {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "input_tokens",
                "output_tokens",
                "prompt_token_count",
                "completion_token_count",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            }
        )
    )


def _first_int(payload: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in payload:
            continue
        value = _int(payload.get(key))
        if value > 0:
            return value
    return 0


def _nested_first_int(payload: dict[str, Any], *paths: tuple[str, str]) -> int:
    for first, second in paths:
        value = payload.get(first)
        if isinstance(value, dict):
            parsed = _int(value.get(second))
            if parsed > 0:
                return parsed
    return 0


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _response_provider(response: Any) -> str:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        return str(additional_kwargs.get("provider") or "")
    return str(getattr(response, "provider", "") or "")


def _response_model(response: Any) -> str:
    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        return str(response_metadata.get("model_name") or response_metadata.get("model") or "")
    return str(getattr(response, "model", "") or "")
