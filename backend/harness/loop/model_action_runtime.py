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


async def await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def model_action_timeout_seconds(
    model_runtime: Any,
    *,
    model_selection: dict[str, Any],
) -> float:
    for key in ("model_response_timeout_seconds", "model_timeout_seconds", "request_timeout_seconds", "timeout_seconds"):
        if key not in model_selection:
            continue
        try:
            value = float(model_selection.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    for attr_name in ("model_call_timeout_seconds", "request_timeout_seconds", "long_output_timeout_seconds"):
        try:
            value = float(getattr(model_runtime, attr_name) or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 180.0


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
