from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from orchestration.adapters import build_shadow_orchestration_plan
from orchestration.behavior_trace import build_behavior_snapshot
from query.models import QueryExecutionPlan, QueryPlan
from understanding import MemoryIntent, QueryUnderstanding


def test_behavior_snapshot_prefers_orchestration_plan_decisions() -> None:
    understanding = QueryUnderstanding(
        route="rag",
        execution_posture="direct_rag",
        task_kind="knowledge_lookup",
        reasons=["selected_rag"],
    )
    memory_intent = MemoryIntent(intent="general")
    execution = QueryExecutionPlan(
        message="查一下项目资料",
        history=[],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_kind="agent",
    )
    query_plan = QueryPlan(
        session_id="session-a",
        message="查一下项目资料",
        history=[],
        subqueries=["查一下项目资料"],
        memory_intent=memory_intent,
        query_understanding=understanding,
        execution_mode="single_execution",
        execution_kind="agent",
        executions=[execution],
    )
    orchestration_plan = build_shadow_orchestration_plan(
        session_id="session-a",
        message="查一下项目资料",
        query_plan=query_plan,
        source="unit-test",
    ).to_dict()

    snapshot = build_behavior_snapshot(
        source="unit-test",
        session_id="session-a",
        message="查一下项目资料",
        plan=query_plan,
        execution=execution,
        orchestration_plan=orchestration_plan,
    )

    by_id = {node["id"]: node for node in snapshot["nodes"]}
    assert snapshot["artifacts"]["orchestration_plan_id"] == orchestration_plan["plan_id"]
    assert snapshot["orchestration_plan"]["plan_id"] == orchestration_plan["plan_id"]
    assert by_id["execution-mode"]["refs"]["orchestration_decision_id"] == "execution-topology"
    assert by_id["task-understanding"]["refs"]["orchestration_plan_id"] == orchestration_plan["plan_id"]
    assert "branches=1" in by_id["execution-mode"]["summary"]
