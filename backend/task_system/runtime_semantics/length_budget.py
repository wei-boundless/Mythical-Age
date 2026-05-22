from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SUPPORTED_LENGTH_BUDGET_SCOPES = {"graph", "group", "batch", "node"}
SUPPORTED_LENGTH_MEASUREMENT_MODES = {"tokens", "text_units", "hybrid"}
DEFAULT_REPAIR_POLICY = {
    "mode": "expand_or_split",
    "max_repair_rounds": 2,
}
DEFAULT_ACCEPTANCE_POLICY = {
    "require_continuity": True,
    "require_formal_headings": True,
}


@dataclass(frozen=True, slots=True)
class CompiledLengthBudget:
    configured: bool = False
    budget_scope: str = "graph"
    measurement_mode: str = "text_units"
    unit_kind: str = "unit"
    unit_label_zh: str = "单元"
    target_units: int = 0
    min_units: int = 0
    max_units: int = 0
    batch_unit_count: int = 0
    repair_policy: dict[str, Any] = field(default_factory=dict)
    acceptance_policy: dict[str, Any] = field(default_factory=dict)
    source_chain: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "orchestration.length_budget"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_chain"] = list(self.source_chain)
        return payload


def normalize_length_budget_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(item, dict):
            payload[normalized_key] = normalize_length_budget_payload(item)
        elif isinstance(item, list):
            payload[normalized_key] = [
                normalize_length_budget_payload(child) if isinstance(child, dict) else child
                for child in item
            ]
        else:
            payload[normalized_key] = item
    return payload


def compile_length_budget(
    *,
    explicit: Any = None,
    inherited: Any = None,
    source_chain: tuple[str, ...] = (),
    source_ref: str = "",
) -> CompiledLengthBudget:
    merged = _merge_length_budget_payloads(
        normalize_length_budget_payload(inherited),
        normalize_length_budget_payload(explicit),
    )
    chain = tuple(
        dict.fromkeys(
            [
                *[str(item).strip() for item in source_chain if str(item).strip()],
                *([str(source_ref).strip()] if str(source_ref).strip() else []),
            ]
        )
    )
    diagnostics: dict[str, Any] = {
        "source_chain": list(chain),
        "source_ref": str(source_ref or "").strip(),
        "issues": [],
    }
    issues: list[str] = diagnostics["issues"]
    budget_scope = _normalize_choice(
        _normalize_legacy_budget_scope(merged.get("budget_scope")),
        SUPPORTED_LENGTH_BUDGET_SCOPES,
        fallback="graph",
        issues=issues,
        issue_code="length_budget_scope_invalid",
    )
    measurement_mode = _normalize_choice(
        merged.get("measurement_mode"),
        SUPPORTED_LENGTH_MEASUREMENT_MODES,
        fallback="text_units",
        issues=issues,
        issue_code="length_budget_measurement_mode_invalid",
    )
    unit_kind = str(merged.get("unit_kind") or "").strip() or "unit"
    unit_label_zh = str(merged.get("unit_label_zh") or "").strip() or _default_unit_label(unit_kind)

    target_units = _optional_int(merged.get("target_units"))
    min_units = _optional_int(merged.get("min_units"))
    max_units = _optional_int(merged.get("max_units"))
    batch_unit_count = _optional_int(merged.get("batch_unit_count"))
    enabled = _optional_bool(merged.get("enabled"))
    configured = (
        enabled is True
        or any(value > 0 for value in (target_units, min_units, max_units))
    ) and enabled is not False

    if target_units <= 0:
        target_units = max(min_units, max_units, batch_unit_count, 0)
    if min_units <= 0 and target_units > 0:
        min_units = target_units
    if max_units <= 0 and target_units > 0:
        max_units = target_units
    if min_units > 0 and max_units > 0 and max_units < min_units:
        issues.append("length_budget_range_inverted")
        max_units = min_units
    if target_units > 0 and min_units > 0 and target_units < min_units:
        issues.append("length_budget_target_below_min")
        target_units = min_units
    if target_units > 0 and max_units > 0 and target_units > max_units:
        issues.append("length_budget_target_above_max")
        target_units = max_units

    repair_policy = {
        **dict(DEFAULT_REPAIR_POLICY),
        **dict(merged.get("repair_policy") or {}),
    }
    acceptance_policy = {
        **dict(DEFAULT_ACCEPTANCE_POLICY),
        **dict(merged.get("acceptance_policy") or {}),
    }

    compiled = CompiledLengthBudget(
        budget_scope=budget_scope,
        configured=configured,
        measurement_mode=measurement_mode,
        unit_kind=unit_kind,
        unit_label_zh=unit_label_zh,
        target_units=max(target_units, 0),
        min_units=max(min_units, 0),
        max_units=max(max_units, 0),
        batch_unit_count=max(batch_unit_count, 0),
        repair_policy=repair_policy,
        acceptance_policy=acceptance_policy,
        source_chain=chain,
        diagnostics={
            **diagnostics,
            "compiled_from": dict(merged),
            "summary": length_budget_preview(
                budget_scope=budget_scope,
                measurement_mode=measurement_mode,
                unit_kind=unit_kind,
                unit_label_zh=unit_label_zh,
                target_units=max(target_units, 0),
                min_units=max(min_units, 0),
                max_units=max(max_units, 0),
                batch_unit_count=max(batch_unit_count, 0),
            ),
            "configured": configured,
            "enabled": enabled,
            "repair_policy": dict(repair_policy),
            "acceptance_policy": dict(acceptance_policy),
        },
    )
    return compiled


def length_budget_preview(
    *,
    budget_scope: str,
    measurement_mode: str,
    unit_kind: str,
    unit_label_zh: str,
    target_units: int,
    min_units: int,
    max_units: int,
    batch_unit_count: int,
) -> dict[str, Any]:
    return {
        "label": f"{unit_label_zh or unit_kind} · {budget_scope} · {measurement_mode}",
        "budget_scope": budget_scope,
        "measurement_mode": measurement_mode,
        "unit_kind": unit_kind,
        "unit_label_zh": unit_label_zh,
        "target_units": target_units,
        "min_units": min_units,
        "max_units": max_units,
        "batch_unit_count": batch_unit_count,
    }


def compiled_length_budget_preview(compiled: CompiledLengthBudget | dict[str, Any]) -> dict[str, Any]:
    if isinstance(compiled, CompiledLengthBudget):
        return length_budget_preview(
            # preview remains stable even when the budget is not configured;
            # callers can consult `configured` separately.
            budget_scope=compiled.budget_scope,
            measurement_mode=compiled.measurement_mode,
            unit_kind=compiled.unit_kind,
            unit_label_zh=compiled.unit_label_zh,
            target_units=compiled.target_units,
            min_units=compiled.min_units,
            max_units=compiled.max_units,
            batch_unit_count=compiled.batch_unit_count,
        )
    payload = dict(compiled or {})
    return length_budget_preview(
        budget_scope=str(payload.get("budget_scope") or "graph"),
        measurement_mode=str(payload.get("measurement_mode") or "text_units"),
        unit_kind=str(payload.get("unit_kind") or "unit"),
        unit_label_zh=str(payload.get("unit_label_zh") or ""),
        target_units=_optional_int(payload.get("target_units")),
        min_units=_optional_int(payload.get("min_units")),
        max_units=_optional_int(payload.get("max_units")),
        batch_unit_count=_optional_int(payload.get("batch_unit_count")),
    )


def _merge_length_budget_payloads(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    if not base and not override:
        return {}
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict):
            merged[key] = {
                **dict(merged.get(key) or {}),
                **dict(value),
            }
        else:
            merged[key] = value
    return merged


def _normalize_choice(
    value: Any,
    allowed: set[str],
    *,
    fallback: str,
    issues: list[str],
    issue_code: str,
) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if raw in allowed:
        return raw
    issues.append(issue_code)
    return fallback


def _default_unit_label(unit_kind: str) -> str:
    mapping = {
        "unit": "单元",
        "item": "条目",
        "record": "记录",
        "group": "组",
        "batch": "批次",
        "node": "节点",
    }
    return mapping.get(str(unit_kind or "").strip(), "单元")


def _normalize_legacy_budget_scope(value: Any) -> Any:
    raw = str(value or "").strip()
    if raw == "volume":
        return "group"
    return value


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "1", "yes", "y", "enabled", "on"}:
        return True
    if raw in {"false", "0", "no", "n", "disabled", "off"}:
        return False
    return None
