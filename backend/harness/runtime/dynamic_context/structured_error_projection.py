from __future__ import annotations

from typing import Any

from .models import compact_text, drop_empty


def structured_error_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return drop_empty(
        {
            "code": compact_text(value.get("code") or value.get("error_code") or "", limit=120),
            "message": compact_text(value.get("message") or value.get("detail") or "", limit=500),
            "retryable": value.get("retryable") if isinstance(value.get("retryable"), bool) else None,
            "provider_retryable": value.get("provider_retryable") if isinstance(value.get("provider_retryable"), bool) else None,
            "agent_auto_retry_allowed": value.get("agent_auto_retry_allowed") if isinstance(value.get("agent_auto_retry_allowed"), bool) else None,
            "agent_retry_policy": compact_text(value.get("agent_retry_policy") or "", limit=120),
            "max_agent_retry_attempts": value.get("max_agent_retry_attempts") if isinstance(value.get("max_agent_retry_attempts"), int) else None,
            "suggested_retry_delay_seconds": (
                value.get("suggested_retry_delay_seconds") if isinstance(value.get("suggested_retry_delay_seconds"), (int, float)) else None
            ),
            "origin": compact_text(value.get("origin") or "", limit=120),
            "attempts": _attempts_projection(value.get("attempts")),
        }
    )


def _attempts_projection(value: Any) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for item in list(value or [])[-3:]:
        if not isinstance(item, dict):
            continue
        attempts.append(
            drop_empty(
                {
                    "model": compact_text(item.get("model") or "", limit=120),
                    "attempt_index": item.get("attempt_index") if isinstance(item.get("attempt_index"), int) else None,
                    "http_status": item.get("http_status") if isinstance(item.get("http_status"), int) else None,
                    "code": compact_text(item.get("code") or item.get("error_code") or "", limit=120),
                    "retryable": item.get("retryable") if isinstance(item.get("retryable"), bool) else None,
                }
            )
        )
    return attempts
