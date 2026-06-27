from __future__ import annotations

from typing import Any


def request_signal_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(getattr(value, "__dict__", {}) or {})


def turn_signals(value: Any) -> dict[str, Any]:
    mapping = request_signal_mapping(value)
    return dict(mapping.get("structural_signals") or mapping.get("turn_signals") or {})


def capability_intent(value: Any) -> dict[str, Any]:
    mapping = request_signal_mapping(value)
    capability = dict(mapping.get("capability_intent") or {})
    if capability:
        capability.pop("route_hint", None)
        return capability
    return {"capability_needs": list(mapping.get("capability_needs") or []), "tool_selection_allowed": False}


def context_binding(value: Any) -> dict[str, Any]:
    return dict(request_signal_mapping(value).get("context_binding") or {})


def capability_needs(value: Any) -> set[str]:
    mapping = request_signal_mapping(value)
    signals = turn_signals(value)
    needs = [
        *list(mapping.get("capability_needs") or []),
        *list(capability_intent(value).get("capability_needs") or []),
        *list(signals.get("weak_capability_needs") or []),
    ]
    return {str(item).strip() for item in needs if str(item).strip()}


def material_kinds(value: Any) -> set[str]:
    suffixes = [
        *list(turn_signals(value).get("material_suffixes") or []),
    ]
    kinds: set[str] = set()
    for suffix in suffixes:
        item = str(suffix or "").strip().lower()
        if item == ".pdf":
            kinds.add("pdf")
        elif item in {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}:
            kinds.add("dataset")
        elif item in {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html"}:
            kinds.add("code")
        elif item:
            kinds.add("workspace")
    return kinds


def target_domain_hints(value: Any) -> set[str]:
    mapping = request_signal_mapping(value)
    return {
        str(item).strip()
        for item in list(mapping.get("target_domain_hints") or [])
        if str(item).strip()
    }


def explicit_paths(value: Any) -> list[str]:
    signals = turn_signals(value)
    return _dedupe(
        [
            *[str(item).strip() for item in list(signals.get("explicit_paths") or [])],
        ]
    )


def explicit_task_selected(value: Any) -> bool:
    binding = context_binding(value)
    signals = turn_signals(value)
    return (
        str(binding.get("kind") or "") == "explicit_task_contract"
        or bool(signals.get("explicit_task_contract"))
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


