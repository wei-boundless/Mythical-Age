from __future__ import annotations

from dataclasses import fields
from typing import Any


def clean_payload(payload: dict[str, Any], model: type[Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(model)}
    return {key: value for key, value in dict(payload or {}).items() if key in allowed}


def require(value: Any, message: str) -> None:
    if value is None:
        raise ValueError(message)
    if isinstance(value, str) and not value.strip():
        raise ValueError(message)


def require_authority(actual: str, expected: str, model_name: str) -> None:
    if actual != expected:
        raise ValueError(f"{model_name} authority must be {expected}")


def tuple_of_dicts(value: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(item) for item in list(value or []) if isinstance(item, dict))


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in list(value or []) if str(item).strip())
