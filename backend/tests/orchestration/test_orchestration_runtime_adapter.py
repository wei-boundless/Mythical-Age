from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.runtime_adapter import build_runtime_control


class LegacyPlan:
    execution_mode = "explicit_fanout"


class LegacyExecution:
    def __init__(self, subtask_id: str = "", bundle_item_id: str = "") -> None:
        self.subtask_id = subtask_id
        self.bundle_item_id = bundle_item_id


def test_runtime_control_shadow_keeps_legacy_execution_order() -> None:
    executions = [LegacyExecution("b"), LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={"mode": "shadow", "plan_id": "orch:test"},
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "orchestration_shadow"
    assert control.primary_active is False
    assert control.executions == executions
    assert control.execution_mode == "explicit_fanout"


def test_runtime_control_primary_uses_orchestration_execution_order() -> None:
    first = LegacyExecution("a")
    second = LegacyExecution("b")

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "b"}, {"execution_id": "a"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=[first, second],
    )

    assert control.source == "orchestration_plan"
    assert control.primary_active is True
    assert control.executions == [second, first]
    assert control.execution_mode == "explicit_fanout"
    assert control.warnings == []


def test_runtime_control_primary_falls_back_when_plan_cannot_match_legacy_execution() -> None:
    executions = [LegacyExecution("a")]

    control = build_runtime_control(
        orchestration_plan={
            "mode": "primary",
            "plan_id": "orch:test",
            "topology": {"mode": "explicit_fanout"},
            "executions": [{"execution_id": "missing"}],
        },
        legacy_plan=LegacyPlan(),
        legacy_executions=executions,
    )

    assert control.source == "legacy_fallback"
    assert control.primary_active is False
    assert control.executions == executions
    assert "primary_fallback_legacy_execution_mismatch" in control.warnings
