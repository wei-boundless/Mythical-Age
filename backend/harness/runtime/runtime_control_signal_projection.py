from __future__ import annotations

from typing import Any


def canonical_runtime_control_signal_projection(value: Any) -> list[dict[str, Any]]:
    """Project Gateway runtime-control signals into model-visible canonical shape."""

    signals: list[dict[str, Any]] = []
    for item in _dict_items(value):
        signal_ref = _text(item.get("runtime_control_signal_ref"))
        if not signal_ref:
            continue
        projected: dict[str, Any] = {
            "observation_ref": _text(item.get("observation_ref")),
            "runtime_control_signal_ref": signal_ref,
            "signal_kind": _text(item.get("signal_kind")),
            "runtime_control_state": _text(item.get("runtime_control_state")),
            "requested_by": _text(item.get("requested_by")),
            "reason": _compact_text(item.get("reason"), limit=300),
            "steer_ref": _text(item.get("steer_ref")),
            "boundary": _text(item.get("boundary")),
            "agent_closeout_required": bool(item.get("agent_closeout_required") is True),
            "tool_calls_allowed_after_signal": bool(item.get("tool_calls_allowed_after_signal") is True),
            "repair_instruction": _compact_text(item.get("repair_instruction"), limit=1200),
            "authority": "harness.runtime.runtime_control_signal_projection",
        }
        requested_at = _float_or_none(item.get("requested_at"))
        if requested_at is not None:
            projected["requested_at"] = requested_at
        signals.append(_drop_empty(projected))
    return signals


def _dict_items(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _compact_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _float_or_none(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}
