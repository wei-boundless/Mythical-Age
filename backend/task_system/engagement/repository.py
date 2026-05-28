from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .models import (
    EngagementAssignee,
    EngagementExecutionStrategy,
    EngagementRuntimeProfile,
    RegisteredEngagementPlan,
)


ENGAGEMENT_PLANS_FILENAME = "engagement_plans.json"


class EngagementPlanConfigError(ValueError):
    pass


class EngagementPlanRepository:
    def __init__(self, backend_dir: Path | str) -> None:
        self.backend_dir = Path(backend_dir)
        self.root = ProjectLayout.from_backend_dir(self.backend_dir).tasks_dir

    @property
    def path(self) -> Path:
        return self.root / ENGAGEMENT_PLANS_FILENAME

    def list(self) -> list[RegisteredEngagementPlan]:
        payload = self._read_payload()
        plans = [_plan_from_payload(item) for item in _list_payload(payload.get("engagement_plans"), path="$.engagement_plans")]
        return sorted(plans, key=lambda item: (item.plan_id, item.version))

    def get(self, plan_id: str) -> RegisteredEngagementPlan | None:
        target = str(plan_id or "").strip()
        if not target:
            return None
        return next((item for item in self.list() if item.plan_id == target), None)

    def upsert(self, plan: RegisteredEngagementPlan | dict[str, Any]) -> RegisteredEngagementPlan:
        model = plan if isinstance(plan, RegisteredEngagementPlan) else _plan_from_payload(plan)
        plans = [item for item in self.list() if item.plan_id != model.plan_id]
        plans.append(model)
        self._write_plans(plans)
        return model

    def delete(self, plan_id: str) -> RegisteredEngagementPlan:
        target = str(plan_id or "").strip()
        plans = self.list()
        existing = next((item for item in plans if item.plan_id == target), None)
        if existing is None:
            raise KeyError(f"engagement plan not found: {target}")
        self._write_plans([item for item in plans if item.plan_id != target])
        return existing

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"engagement_plans": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise EngagementPlanConfigError(f"failed to read engagement plans: {exc}") from exc
        if not isinstance(payload, dict):
            raise EngagementPlanConfigError("engagement plans root must be an object")
        payload.setdefault("engagement_plans", [])
        return payload

    def _write_plans(self, plans: list[RegisteredEngagementPlan]) -> None:
        payload = {"engagement_plans": [item.to_dict() for item in sorted(plans, key=lambda plan: plan.plan_id)]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _plan_from_payload(payload: Any) -> RegisteredEngagementPlan:
    if not isinstance(payload, dict):
        raise EngagementPlanConfigError("engagement plan item must be an object")
    data = dict(payload)
    data["assignee"] = _dataclass_from_payload(
        EngagementAssignee,
        dict(data.get("assignee") or {}),
        path="engagement_plan.assignee",
    )
    data["runtime_profile"] = _dataclass_from_payload(
        EngagementRuntimeProfile,
        dict(data.get("runtime_profile") or {}),
        path="engagement_plan.runtime_profile",
    )
    data["execution_strategy"] = _dataclass_from_payload(
        EngagementExecutionStrategy,
        dict(data.get("execution_strategy") or {}),
        path="engagement_plan.execution_strategy",
    )
    return _dataclass_from_payload(RegisteredEngagementPlan, data, path="engagement_plan")


def _dataclass_from_payload(model: type, payload: dict[str, Any], *, path: str):
    if not is_dataclass(model):
        raise EngagementPlanConfigError(f"{model!r} is not a dataclass")
    field_names = {item.name for item in fields(model)}
    unknown = sorted(set(payload) - field_names)
    if unknown:
        raise EngagementPlanConfigError(f"{path} has unknown keys: {', '.join(unknown)}")
    values: dict[str, Any] = {}
    tuple_fields = {
        item.name
        for item in fields(model)
        if getattr(item.type, "__origin__", None) is tuple or str(item.type).startswith("tuple[")
    }
    for key, value in payload.items():
        values[key] = tuple(value or ()) if key in tuple_fields else value
    return model(**values)


def _list_payload(value: Any, *, path: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EngagementPlanConfigError(f"{path} must be a list")
    return list(value)

