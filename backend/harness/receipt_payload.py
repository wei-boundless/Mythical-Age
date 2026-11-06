from __future__ import annotations

from typing import Any


def receipt_payload(receipt: dict[str, Any] | Any | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    if isinstance(receipt, dict):
        return dict(receipt)
    to_dict = getattr(receipt, "to_dict", None)
    if not callable(to_dict):
        return {}
    payload = to_dict()
    return dict(payload) if isinstance(payload, dict) else {}
