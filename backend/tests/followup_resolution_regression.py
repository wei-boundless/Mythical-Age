from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from query.followup_resolver import QueryFollowupResolver
from query.models import QueryExecutionPlan
from tasks import TaskCoordinator
from understanding import MemoryIntent, QueryUnderstanding


async def _seed_tasks() -> TaskCoordinator:
    coordinator = TaskCoordinator()
    executions = [
        QueryExecutionPlan(
            message="总结 PDF 第三页",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="pdf_analysis", task_kind="pdf_followup_query"),
        ),
        QueryExecutionPlan(
            message="给我 inventory.xlsx 最缺货的前三个仓库",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
        ),
        QueryExecutionPlan(
            message="补一句北京天气",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="get_weather", task_kind="weather_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async for _event in coordinator.run_query_tasks("session-1", executions, runner):
        pass
    return coordinator


def test_followup_resolver_prefers_task_ref_for_ordinal_request() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="只展开第二个子任务，给我仓库和缺货量。",
    )

    assert resolution.mode == "task_ref"
    assert resolution.task_id.endswith("-subtask-2")
    assert resolution.task_ids == [resolution.task_id]
    assert resolution.source_query == "给我 inventory.xlsx 最缺货的前三个仓库"


def test_followup_resolver_can_bind_back_to_recent_pdf_task() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="把这份 PDF 的核心结论压成三条行动建议。",
    )

    assert resolution.mode == "binding_ref"
    assert resolution.binding_key == "active_pdf"
    assert resolution.binding_owner_task_id == resolution.task_id
    assert resolution.source_query == "总结 PDF 第三页"


def test_followup_resolver_can_select_multiple_tasks_for_subset_request() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="把第一个和第三个子任务各压成一句话，不要重复第二个。",
    )

    assert resolution.mode == "compound_subset"
    assert resolution.task_ids == ["session-1-subtask-1", "session-1-subtask-3"]
    assert resolution.task_id == "session-1-subtask-1"


def main() -> None:
    test_followup_resolver_prefers_task_ref_for_ordinal_request()
    test_followup_resolver_can_bind_back_to_recent_pdf_task()
    test_followup_resolver_can_select_multiple_tasks_for_subset_request()
    print("ALL PASSED (followup resolution regression)")


if __name__ == "__main__":
    main()
