from __future__ import annotations

import asyncio
from pathlib import Path

from api import memory as memory_api
from memory_system import MemoryFacade


class _RuntimeStub:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.memory_facade = MemoryFacade(base_dir)
        self.refreshed_paths: list[str] = []

    def refresh_indexes_for_path(self, path: str) -> None:
        self.refreshed_paths.append(path)


def test_working_memory_overview_and_detail_api_expose_runtime_governance(tmp_path: Path) -> None:
    runtime = _RuntimeStub(tmp_path)
    accepted = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:api",
        task_id="task.api",
        graph_id="graph:api",
        owner_node_id="writer",
        node_run_id="writer.chapter_001",
        run_attempt_id="attempt_01",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="第一章工作草稿",
        status="accepted",
        visibility="shared_in_graph",
        promotion_state="candidate",
    )
    conflicted = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:api",
        graph_id="graph:api",
        owner_node_id="reviewer",
        node_run_id="reviewer.chapter_001",
        writer_agent_id="agent:reviewer",
        kind="continuity_conflict",
        summary="时间线冲突需要裁定",
        status="conflicted",
    )
    runtime.memory_facade.record_working_memory_read(
        task_run_id="taskrun:api",
        graph_id="graph:api",
        owner_node_id="reviewer",
        node_run_id="reviewer.chapter_001",
        reader_agent_id="agent:reviewer",
        selected_item_ids=[accepted.work_memory_id],
        excluded_item_ids=[conflicted.work_memory_id],
    )
    runtime.memory_facade.create_working_memory_temporal_edge(
        task_run_id="taskrun:api",
        graph_id="graph:api",
        source_item_id=accepted.work_memory_id,
        target_item_id=conflicted.work_memory_id,
        relation="contradicts",
        source_node_id="reviewer",
    )
    transaction = runtime.memory_facade.create_working_memory_handoff_transaction(
        task_run_id="taskrun:api",
        graph_id="graph:api",
        edge_id="writer_to_reviewer",
        handoff_id="handoff:api",
        candidate_work_memory_ids=[accepted.work_memory_id],
    )
    runtime.memory_facade.commit_working_memory_handoff_transaction(
        transaction.transaction_id,
        adopted_work_memory_ids=[accepted.work_memory_id],
    )

    original = memory_api.require_runtime
    memory_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        overview = asyncio.run(memory_api.get_working_memory_overview(task_run_id="taskrun:api"))
        detail = asyncio.run(memory_api.get_working_memory_item(accepted.work_memory_id))
    finally:
        memory_api.require_runtime = original  # type: ignore[assignment]

    assert overview["total"] == 2
    assert overview["by_status"]["accepted"] == 1
    assert overview["by_status"]["conflicted"] == 1
    assert overview["conflict_items"][0]["work_memory_id"] == conflicted.work_memory_id
    assert overview["promotion_candidates"][0]["work_memory_id"] == accepted.work_memory_id
    assert overview["read_logs"][0]["selected_item_ids"] == [accepted.work_memory_id]
    assert overview["handoff_transactions"][0]["transaction_status"] == "committed"

    assert detail["item"]["work_memory_id"] == accepted.work_memory_id
    assert detail["read_logs"][0]["reader_agent_id"] == "agent:reviewer"
    assert detail["temporal_edges"][0]["relation"] == "contradicts"
    assert detail["handoff_transactions"][0]["adopted_work_memory_ids"] == [accepted.work_memory_id]


def test_working_memory_finalize_api_returns_report_without_committing_durable_memory(tmp_path: Path) -> None:
    runtime = _RuntimeStub(tmp_path)
    item = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:api-finalize",
        graph_id="graph:api",
        owner_node_id="summarizer",
        node_run_id="summarizer.run.001",
        writer_agent_id="agent:summarizer",
        kind="promotion_candidate",
        summary="稳定设定候选",
        status="proposed",
    )

    original = memory_api.require_runtime
    memory_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            memory_api.finalize_working_memory_task_run(
                "taskrun:api-finalize",
                memory_api.WorkingMemoryFinalizeRequest(actor_id="agent:main", terminal_reason="completed"),
            )
        )
    finally:
        memory_api.require_runtime = original  # type: ignore[assignment]

    loaded = runtime.memory_facade.get_working_memory_item(item.work_memory_id)
    headers = runtime.memory_facade.scan_durable_memory_headers(limit=20)

    assert payload["ok"] is True
    assert payload["result"]["promotion_candidate_count"] == 1
    assert loaded is not None
    assert loaded.status == "archived"
    assert loaded.promotion_state == "needs_review"
    assert headers == []


def test_working_memory_promotion_api_commits_candidate_to_task_durable_memory(tmp_path: Path) -> None:
    runtime = _RuntimeStub(tmp_path)
    item = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:promote",
        task_id="novel.longform",
        graph_id="graph:novel",
        owner_node_id="continuity_keeper",
        node_run_id="continuity_keeper.chapter_02",
        writer_agent_id="agent:continuity",
        kind="promotion_candidate",
        memory_semantics="decision",
        title="主角不能在第二章离开主城",
        summary="稳定设定：主角在第二章结尾前仍留在主城，不能提前出城。",
        status="archived",
        visibility="shared_in_graph",
        promotion_state="needs_review",
        source_event_refs=["event:chapter_02_review"],
        source_message_refs=["message:reviewer:02"],
        artifact_refs=["artifact:chapter_02_outline"],
        tags=["longform", "continuity"],
    )

    original = memory_api.require_runtime
    memory_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(
            memory_api.promote_working_memory_item_to_task_durable(
                item.work_memory_id,
                memory_api.WorkingMemoryPromoteTaskDurableRequest(
                    actor_id="human:editor",
                    reason="continuity fact accepted",
                ),
            )
        )
    finally:
        memory_api.require_runtime = original  # type: ignore[assignment]

    loaded = runtime.memory_facade.get_working_memory_item(item.work_memory_id)
    task_memory = runtime.memory_facade.get_task_durable_memory_item(payload["task_memory"]["task_memory_id"])
    headers = runtime.memory_facade.scan_durable_memory_headers(limit=20)

    assert payload["ok"] is True
    assert payload["action"] == "promote_to_task_durable"
    assert payload["item"]["promotion_state"] == "promoted_to_task_durable"
    assert loaded is not None
    assert loaded.status == "promoted"
    assert loaded.promotion_state == "promoted_to_task_durable"
    assert loaded.metadata["promoted_task_memory_id"] == payload["task_memory"]["task_memory_id"]
    assert task_memory is not None
    assert task_memory.task_id == "novel.longform"
    assert task_memory.graph_id == "graph:novel"
    assert task_memory.source_work_memory_ids == (item.work_memory_id,)
    assert task_memory.payload["source_refs"]["owner_node_id"] == "continuity_keeper"
    assert headers == []
    assert runtime.refreshed_paths == []


def test_working_memory_governance_api_accepts_discards_and_marks_conflict(tmp_path: Path) -> None:
    runtime = _RuntimeStub(tmp_path)
    first = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:govern",
        owner_node_id="planner",
        writer_agent_id="agent:planner",
        kind="plan_fragment",
        summary="待采纳计划",
        status="proposed",
    )
    second = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:govern",
        owner_node_id="writer",
        writer_agent_id="agent:writer",
        kind="chapter_draft",
        summary="需要废弃的草稿",
        status="draft",
    )
    third = runtime.memory_facade.create_working_memory_item(
        task_run_id="taskrun:govern",
        owner_node_id="reviewer",
        writer_agent_id="agent:reviewer",
        kind="continuity_conflict",
        summary="冲突候选",
        status="proposed",
    )

    original = memory_api.require_runtime
    memory_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        accepted = asyncio.run(
            memory_api.accept_working_memory_item(
                first.work_memory_id,
                memory_api.WorkingMemoryGovernRequest(actor_id="human:editor", reason="plan ok"),
            )
        )
        discarded = asyncio.run(
            memory_api.discard_working_memory_item(
                second.work_memory_id,
                memory_api.WorkingMemoryGovernRequest(actor_id="human:editor", reason="draft obsolete"),
            )
        )
        conflicted = asyncio.run(
            memory_api.mark_working_memory_item_conflict(
                third.work_memory_id,
                memory_api.WorkingMemoryGovernRequest(actor_id="human:editor", reason="continuity mismatch"),
            )
        )
    finally:
        memory_api.require_runtime = original  # type: ignore[assignment]

    assert accepted["item"]["status"] == "accepted"
    assert accepted["item"]["authority"] == "coordinator_adopted"
    assert accepted["item"]["metadata"]["governance_reason"] == "plan ok"
    assert discarded["item"]["status"] == "discarded"
    assert conflicted["item"]["status"] == "conflicted"
