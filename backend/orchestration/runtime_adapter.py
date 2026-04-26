from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeControl:
    execution_mode: str
    executions: list[Any]
    source: str = "legacy"
    primary_active: bool = False
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "orchestration_runtime_control",
            "execution_mode": self.execution_mode,
            "source": self.source,
            "primary_active": self.primary_active,
            "execution_count": len(self.executions),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
        }


def build_runtime_control(
    *,
    orchestration_plan: dict[str, Any] | None,
    legacy_plan: Any,
    legacy_executions: list[Any],
) -> RuntimeControl:
    legacy_mode = str(getattr(legacy_plan, "execution_mode", "") or "single_execution")
    legacy_control = RuntimeControl(
        execution_mode=legacy_mode,
        executions=list(legacy_executions),
        diagnostics={"legacy_execution_count": len(legacy_executions)},
    )
    if not isinstance(orchestration_plan, dict) or not orchestration_plan:
        return legacy_control
    mode = str(orchestration_plan.get("mode") or "shadow")
    if mode != "primary":
        legacy_control.source = "orchestration_shadow"
        legacy_control.diagnostics["plan_id"] = str(orchestration_plan.get("plan_id") or "")
        return legacy_control

    planned_executions = [
        dict(item)
        for item in list(orchestration_plan.get("executions") or [])
        if isinstance(item, dict)
    ]
    topology = dict(orchestration_plan.get("topology") or {})
    planned_mode = str(topology.get("mode") or legacy_mode)
    legacy_by_id = {
        _legacy_execution_id(execution, index=index): execution
        for index, execution in enumerate(legacy_executions, start=1)
    }
    ordered: list[Any] = []
    missing: list[str] = []
    for index, planned in enumerate(planned_executions, start=1):
        execution_id = str(planned.get("execution_id") or f"main-{index}")
        execution = legacy_by_id.get(execution_id)
        if execution is None:
            missing.append(execution_id)
            continue
        ordered.append(execution)

    warnings: list[str] = []
    if missing or len(ordered) != len(legacy_executions):
        warnings.append("primary_fallback_legacy_execution_mismatch")
        return RuntimeControl(
            execution_mode=legacy_mode,
            executions=list(legacy_executions),
            source="legacy_fallback",
            primary_active=False,
            warnings=warnings,
            diagnostics={
                "plan_id": str(orchestration_plan.get("plan_id") or ""),
                "planned_execution_count": len(planned_executions),
                "legacy_execution_count": len(legacy_executions),
                "missing_execution_ids": missing,
            },
        )

    return RuntimeControl(
        execution_mode=planned_mode,
        executions=ordered,
        source="orchestration_plan",
        primary_active=True,
        diagnostics={
            "plan_id": str(orchestration_plan.get("plan_id") or ""),
            "planned_execution_count": len(planned_executions),
            "legacy_execution_count": len(legacy_executions),
            "execution_ids": [str(item.get("execution_id") or "") for item in planned_executions],
        },
    )


def _legacy_execution_id(execution: Any, *, index: int) -> str:
    return str(
        getattr(execution, "subtask_id", "")
        or getattr(execution, "bundle_item_id", "")
        or "main"
    )
