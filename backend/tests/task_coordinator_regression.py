from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.models import QueryExecutionPlan
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


async def _run_tasks() -> tuple[list[dict[str, object]], TaskCoordinator]:
    coordinator = TaskCoordinator()
    executions = [
        QueryExecutionPlan(
            message="a",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(),
        ),
        QueryExecutionPlan(
            message="b",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "retrieval", "results": [{"query": execution.message}]}
        yield {"type": "done", "content": f"answer for {execution.message}"}

    events: list[dict[str, object]] = []
    async for event in coordinator.run_query_tasks("session-1", executions, runner):
        events.append(event)
    return events, coordinator


def test_task_coordinator_records_query_subtasks() -> None:
    events, coordinator = asyncio.run(_run_tasks())

    assert [event["type"] for event in events[:2]] == ["subtask_start", "retrieval"]
    assert events[-1]["type"] == "subtask_end"
    assert "done" not in [event["type"] for event in events]
    records = coordinator.list_tasks(session_id="session-1")
    assert len(records) == 2
    assert all(task.status == "completed" for task in records)
    assert all(task.agent_type == "explorer" for task in records)
    assert records[0].result == "answer for a"
    assert records[0].context_ref is not None
    assert records[0].context_ref.parent_query_id
    assert records[0].summary is not None
    assert records[0].summary.response == "answer for a"
    assert records[0].result_ref is not None
    assert events[0]["task_id"] == records[0].task_id
    assert isinstance(events[-1]["summary"], dict)
    assert isinstance(events[-1]["context_ref"], dict)
    assert isinstance(events[-1]["result_ref"], dict)


def test_task_coordinator_records_tool_tasks() -> None:
    coordinator = TaskCoordinator()

    async def runner() -> str:
        return "tool ok"

    result = asyncio.run(coordinator.run_tool_task("session-2", "terminal", runner))
    task = coordinator.list_tasks(session_id="session-2")[0]

    assert result == "tool ok"
    assert task.status == "completed"
    assert task.agent_type == "worker"
    assert task.metadata["tool_name"] == "terminal"
    assert task.result_ref is not None


def main() -> None:
    test_task_coordinator_records_query_subtasks()
    test_task_coordinator_records_tool_tasks()
    print("ALL PASSED (task coordinator regression)")


if __name__ == "__main__":
    main()
