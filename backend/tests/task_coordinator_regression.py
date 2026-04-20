from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tasks import TaskCoordinator


async def _run_tasks() -> tuple[list[dict[str, object]], TaskCoordinator]:
    coordinator = TaskCoordinator()

    async def runner(subquery: str):
        yield {"type": "retrieval", "results": [{"query": subquery}]}
        yield {"type": "done", "content": f"answer for {subquery}"}

    events: list[dict[str, object]] = []
    async for event in coordinator.run_query_tasks("session-1", ["a", "b"], runner):
        events.append(event)
    return events, coordinator


def test_task_coordinator_records_query_subtasks() -> None:
    events, coordinator = asyncio.run(_run_tasks())

    assert [event["type"] for event in events[:2]] == ["subtask_start", "retrieval"]
    records = coordinator.list_tasks(session_id="session-1")
    assert len(records) == 2
    assert all(task.status == "completed" for task in records)
    assert all(task.agent_type == "explorer" for task in records)
    assert records[0].result == "answer for a"


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
