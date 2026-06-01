from __future__ import annotations

import inspect
import json
from typing import Any


async def call_model_invoker(
    invoker: Any,
    messages: list[Any],
    *,
    model_selection: dict[str, Any],
    accounting_context: dict[str, Any] | None = None,
) -> Any:
    model_selection = normalize_model_selection_for_invocation(model_selection)
    if model_selection:
        try:
            return await await_if_needed(
                invoker(messages, model_spec=model_selection, accounting_context=accounting_context)
            )
        except TypeError as exc:
            if "model_spec" not in str(exc) and "accounting_context" not in str(exc):
                raise
        try:
            return await await_if_needed(invoker(messages, model_spec=model_selection))
        except TypeError as exc:
            if "model_spec" not in str(exc):
                raise
            return await await_if_needed(invoker(messages))
    if accounting_context:
        try:
            return await await_if_needed(invoker(messages, accounting_context=accounting_context))
        except TypeError as exc:
            if "accounting_context" not in str(exc):
                raise
    return await await_if_needed(invoker(messages))


_MODEL_SELECTION_INVOCATION_FIELDS = frozenset(
    {
        "provider",
        "model",
        "base_url",
        "credential_ref",
        "api_key",
        "max_output_tokens",
        "timeout_seconds",
        "request_timeout_seconds",
        "long_output_timeout_seconds",
        "max_retries",
        "temperature",
        "thinking_mode",
        "reasoning_effort",
        "context_budget_preset",
        "context_window_preset",
        "stream_policy",
        "model_response_timeout_seconds",
        "model_timeout_seconds",
    }
)


def normalize_model_selection_for_invocation(model_selection: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(model_selection, dict):
        return {}
    payload = {
        str(key): value
        for key, value in dict(model_selection).items()
        if value not in ("", None, {}, [])
    }
    if not any(key in payload for key in _MODEL_SELECTION_INVOCATION_FIELDS):
        return {}
    return payload


async def await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def model_action_timeout_seconds(
    model_runtime: Any,
    *,
    model_selection: dict[str, Any],
) -> float:
    for key in ("model_response_timeout_seconds", "model_timeout_seconds"):
        if key not in model_selection:
            continue
        try:
            value = float(model_selection.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    timeout_seconds = _positive_float(model_selection.get("timeout_seconds") or model_selection.get("request_timeout_seconds"))
    long_timeout_seconds = _positive_float(model_selection.get("long_output_timeout_seconds"))
    max_output_tokens = _positive_int(model_selection.get("max_output_tokens"))
    if max_output_tokens >= 16384 and long_timeout_seconds > 0:
        return max(timeout_seconds, long_timeout_seconds)
    if timeout_seconds > 0:
        return timeout_seconds
    for attr_name in ("model_call_timeout_seconds", "request_timeout_seconds", "long_output_timeout_seconds"):
        try:
            value = float(getattr(model_runtime, attr_name) or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 180.0


def _positive_float(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def parse_json_object(content: Any) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def compact_text(value: Any, *, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"
