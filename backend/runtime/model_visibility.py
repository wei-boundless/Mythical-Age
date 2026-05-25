from __future__ import annotations

from typing import Any


TASK_DOMAIN_AUTHORITY_KEYS = frozenset(
    {
        "domain",
        "task_domain",
        "task_domain_binding",
        "active_domain_binding",
        "domain_binding",
        "domain_playbook",
        "requested_domain",
        "bound_domain_id",
        "semantic_domain",
    }
)


def model_visible_semantic_contract(semantic_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = strip_task_domain_authority(dict(semantic_contract or {}))
    diagnostics = contract.get("diagnostics")
    if isinstance(diagnostics, dict) and not diagnostics:
        contract.pop("diagnostics", None)
    return contract


def strip_task_domain_authority(value: Any) -> Any:
    if isinstance(value, dict):
        stripped: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key in TASK_DOMAIN_AUTHORITY_KEYS:
                continue
            stripped[key] = strip_task_domain_authority(raw_value)
        return stripped
    if isinstance(value, list):
        return [strip_task_domain_authority(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_task_domain_authority(item) for item in value)
    return value
