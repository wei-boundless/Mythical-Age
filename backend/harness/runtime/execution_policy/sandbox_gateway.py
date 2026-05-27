from __future__ import annotations

from typing import Any


def sandbox_policy_from_permit(permit: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(permit, "diagnostics", {}) or {})
    return dict(diagnostics.get("sandbox_policy") or {})


