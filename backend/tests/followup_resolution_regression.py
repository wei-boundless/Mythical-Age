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
            message="总结 knowledge/reports/AI治理报告.pdf 第三页",
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
    assert resolution.resolved_task_id == resolution.task_id
    assert resolution.resolved_task_ids == resolution.task_ids
    assert resolution.resolved_target_kind == "task"
    assert resolution.resolved_task_kind == "structured_data"
    assert resolution.source_query == "给我 inventory.xlsx 最缺货的前三个仓库"


def test_followup_resolver_can_bind_back_to_recent_pdf_task() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="把这份 PDF 的核心结论压成三条行动建议。",
    )

    assert resolution.mode == "binding_ref"
    assert resolution.target_kind == "binding"
    assert resolution.binding_key == "active_pdf"
    assert resolution.binding_kind == "active_pdf"
    assert resolution.binding_identity.endswith("knowledge/reports/ai治理报告.pdf")
    assert resolution.resolved_binding_kind == "active_pdf"
    assert resolution.resolved_binding_identity == resolution.binding_identity
    assert resolution.resolved_binding_ref == resolution.binding_identity
    assert resolution.resolved_binding_owner_task_id == resolution.binding_owner_task_id
    assert resolution.resolved_task_kind == "pdf"
    assert resolution.binding_owner_task_id == resolution.task_id
    assert resolution.resolution_source == "task_registry_binding"
    assert resolution.source_query == "总结 knowledge/reports/AI治理报告.pdf 第三页"


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
    assert resolution.resolved_task_ids == resolution.task_ids
    assert resolution.resolved_target_kind == "task_subset"


def test_followup_resolver_refuses_ambiguous_dataset_binding() -> None:
    coordinator = asyncio.run(_seed_tasks())
    executions = [
        QueryExecutionPlan(
            message="给我 employees.xlsx 的薪资前五",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async def seed_more() -> None:
        async for _event in coordinator.run_query_tasks("session-1", executions, runner):
            pass

    asyncio.run(seed_more())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="把那个表按仓库展开一下。",
    )

    assert resolution.mode == "clarify"
    assert resolution.requires_clarification is True
    assert resolution.reason == "ambiguous_binding_reference"
    assert resolution.resolution_source == "task_registry_binding"
    assert resolution.resolved_task_ids == resolution.task_ids
    assert resolution.resolved_target_kind == "binding"
    assert "请直接说文件名" in resolution.clarification_prompt


def test_followup_resolver_prefers_latest_dataset_owner_for_operation_hint() -> None:
    coordinator = asyncio.run(_seed_tasks())
    executions = [
        QueryExecutionPlan(
            message="给我 employees.xlsx 的薪资前五",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async def seed_more() -> None:
        async for _event in coordinator.run_query_tasks("session-1", executions, runner):
            pass

    asyncio.run(seed_more())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="按部门汇总这些高薪员工。",
    )

    assert resolution.mode == "binding_ref"
    assert resolution.binding_key == "active_dataset"
    assert resolution.source_query == "给我 employees.xlsx 的薪资前五"
    assert resolution.binding_identity.endswith("employees.xlsx")


def test_followup_resolver_generic_realtime_query_does_not_get_stolen_by_binding_clarify() -> None:
    coordinator = asyncio.run(_seed_tasks())
    executions = [
        QueryExecutionPlan(
            message="给我 employees.xlsx 的薪资前五",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="structured_data_analysis", task_kind="structured_followup_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async def seed_more() -> None:
        async for _event in coordinator.run_query_tasks("session-1", executions, runner):
            pass

    asyncio.run(seed_more())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="再看一下北京今天天气。",
    )

    assert resolution.mode == "none"
    assert resolution.requires_clarification is False


def test_followup_resolver_can_continue_unique_dataset_owner_with_operation_hint() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="再按仓库展开一下。",
    )

    assert resolution.mode == "binding_ref"
    assert resolution.binding_key == "active_dataset"
    assert resolution.binding_identity.endswith("inventory.xlsx")
    assert resolution.resolved_binding_identity == resolution.binding_identity
    assert resolution.resolved_binding_owner_task_id == resolution.binding_owner_task_id
    assert resolution.resolved_task_kind == "structured_data"
    assert resolution.binding_owner_task_id == resolution.task_id
    assert resolution.source_query == "给我 inventory.xlsx 最缺货的前三个仓库"


def test_followup_resolver_does_not_treat_generic_pdf_mention_as_committed_owner() -> None:
    coordinator = TaskCoordinator()
    executions = [
        QueryExecutionPlan(
            message="总结 PDF 第三页",
            history=[],
            memory_intent=MemoryIntent(),
            query_understanding=QueryUnderstanding(route="tool", tool_name="pdf_analysis", task_kind="pdf_followup_query"),
        ),
    ]

    async def runner(execution: QueryExecutionPlan):
        yield {"type": "done", "content": f"answer for {execution.message}"}

    async def seed() -> None:
        async for _event in coordinator.run_query_tasks("session-generic-pdf", executions, runner):
            pass

    asyncio.run(seed())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-generic-pdf",
        message="把这份 PDF 的核心结论压成三条行动建议。",
    )

    assert resolution.mode == "none"
    assert resolution.binding_owner_task_id == ""


def test_followup_resolver_keeps_global_synthesis_request_out_of_single_binding() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="最后给我一个总总结，按 PDF、数据、实时、长期记忆四段组织，而且先给结论。",
    )

    assert resolution.mode == "none"
    assert resolution.binding_owner_task_id == ""
    assert resolution.resolved_task_id == ""


def test_followup_resolver_keeps_ops_summary_request_out_of_single_binding() -> None:
    coordinator = asyncio.run(_seed_tasks())
    resolver = QueryFollowupResolver(coordinator)

    resolution = resolver.resolve(
        session_id="session-1",
        message="把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。",
    )

    assert resolution.mode == "none"
    assert resolution.binding_owner_task_id == ""
    assert resolution.resolved_task_id == ""


def main() -> None:
    test_followup_resolver_prefers_task_ref_for_ordinal_request()
    test_followup_resolver_can_bind_back_to_recent_pdf_task()
    test_followup_resolver_can_select_multiple_tasks_for_subset_request()
    test_followup_resolver_refuses_ambiguous_dataset_binding()
    test_followup_resolver_prefers_latest_dataset_owner_for_operation_hint()
    test_followup_resolver_generic_realtime_query_does_not_get_stolen_by_binding_clarify()
    test_followup_resolver_can_continue_unique_dataset_owner_with_operation_hint()
    test_followup_resolver_does_not_treat_generic_pdf_mention_as_committed_owner()
    test_followup_resolver_keeps_global_synthesis_request_out_of_single_binding()
    test_followup_resolver_keeps_ops_summary_request_out_of_single_binding()
    print("ALL PASSED (followup resolution regression)")


if __name__ == "__main__":
    main()
