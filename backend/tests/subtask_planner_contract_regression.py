from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from query.planner import QueryPlanner
from query.subtask_planner import InvalidSubtaskPlan
from understanding import MemoryIntent, QueryUnderstanding
from query.models import QueryExecutionPlan, QueryPlan, SubtaskPlan
from tests.query_runtime_route_guard_regression import _build_runtime


def _planner() -> QueryPlanner:
    return QueryPlanner(base_dir=ROOT, skill_registry=None, tool_runtime=SimpleNamespace(registry=None))


def test_explicit_structured_subtasks_are_the_only_fanout_source() -> None:
    planner = _planner()
    explicit_subtasks = [
        {
            "id": "pdf-page",
            "goal": "总结 PDF 第三页",
            "title": "PDF 第三页",
            "execution_message": "总结 PDF 第三页",
            "refs": {"kind": "pdf"},
        },
        {
            "id": "weather",
            "goal": "查询北京天气",
            "title": "北京天气",
            "execution_message": "查北京天气",
            "depends_on": ["pdf-page"],
            "refs": {"kind": "weather"},
        },
    ]

    plan = planner.build_plan(
        session_id="explicit-subtasks",
        message="按显式计划执行。",
        history=[],
        explicit_subtasks=explicit_subtasks,
    )

    assert plan.query_understanding.route == "explicit_fanout"
    assert plan.query_understanding.direct_route_reason == "explicit_structured_plan"
    assert plan.subqueries == ["总结 PDF 第三页", "查北京天气"]
    assert [subtask.subtask_id for subtask in plan.subtasks] == ["pdf-page", "weather"]
    assert plan.subtasks[1].depends_on == ["pdf-page"]
    assert plan.iter_executions()[0].subtask_id == "pdf-page"
    assert plan.iter_executions()[1].subtask_origin == "explicit_structured_input"


def test_invalid_explicit_subtasks_fail_closed() -> None:
    planner = _planner()
    try:
        planner.build_plan(
            session_id="explicit-subtasks",
            message="按显式计划执行。",
            history=[],
            explicit_subtasks=[{"id": "a", "execution_message": "A"}, {"id": "b", "execution_message": "B", "depends_on": ["missing"]}],
        )
    except InvalidSubtaskPlan as exc:
        assert "unknown explicit subtask dependencies" in str(exc)
    else:
        raise AssertionError("invalid explicit subtasks must fail closed")


def test_runtime_executes_explicit_subtasks_with_metadata() -> None:
    execution_a = QueryExecutionPlan(
        message="a",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(intent="session_summary_query", route="memory", modality="memory", should_skip_rag=True),
        subtask_id="alpha",
    )
    execution_b = QueryExecutionPlan(
        message="b",
        history=[],
        memory_intent=MemoryIntent(intent="session_continuity_query", memory_read_mode="session_state", should_skip_rag=True),
        query_understanding=QueryUnderstanding(intent="session_summary_query", route="memory", modality="memory", should_skip_rag=True),
        subtask_id="beta",
    )
    plan = QueryPlan(
        session_id="explicit-runtime",
        message="explicit",
        history=[],
        subqueries=["a", "b"],
        memory_intent=MemoryIntent(),
        query_understanding=QueryUnderstanding(intent="explicit_fanout_query", route="explicit_fanout", modality="multi"),
        execution_mode="explicit_fanout",
        executions=[execution_a, execution_b],
        subtasks=[
            SubtaskPlan(subtask_id="alpha", goal="A", user_visible_title="A", execution_message="a", origin="explicit_structured_input"),
            SubtaskPlan(
                subtask_id="beta",
                goal="B",
                user_visible_title="B",
                execution_message="b",
                depends_on=["alpha"],
                origin="explicit_structured_input",
            ),
        ],
    )
    runtime, _retrieval, _model_runtime, _memory_facade = _build_runtime(rag_mode=False)
    runtime.planner.build_plan = lambda **_kwargs: plan  # type: ignore[method-assign]

    async def _run() -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        async for event in runtime._execution_events(plan.session_id, plan.message, plan.history):
            events.append(event)
        return events

    events = asyncio.run(_run())
    starts = [event for event in events if event.get("type") == "subtask_start"]
    assert [event["subtask_plan"]["subtask_plan_id"] for event in starts] == ["alpha", "beta"]
    assert starts[1]["subtask_plan"]["depends_on"] == ["alpha"]
    assert events[-1]["main_context"]["followup_target_task_ids"]


def main() -> None:
    test_explicit_structured_subtasks_are_the_only_fanout_source()
    test_invalid_explicit_subtasks_fail_closed()
    test_runtime_executes_explicit_subtasks_with_metadata()
    print("ALL PASSED (subtask planner contract regression)")


if __name__ == "__main__":
    main()
