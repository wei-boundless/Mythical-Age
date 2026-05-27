from __future__ import annotations

from memory_system import MemoryFacade
from memory_system.contracts import MemoryContextCandidate


def test_task_durable_memory_creates_and_queries_isolated_namespaces(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    first = facade.task_durable_memory.create_item(
        task_id="novel.alpha",
        graph_id="graph:alpha",
        kind="character_state",
        memory_semantics="working_fact",
        title="主角仍在主城",
        canonical_statement="第二章结束前，主角仍在主城。",
        summary="主角不能提前离开主城。",
        retrieval_hints=["主角", "主城"],
    )
    second = facade.task_durable_memory.create_item(
        task_id="novel.beta",
        graph_id="graph:beta",
        kind="character_state",
        memory_semantics="working_fact",
        title="另一项目设定",
        canonical_statement="Beta 项目使用独立世界观。",
        summary="不应污染 Alpha。",
    )

    alpha_items = facade.task_durable_memory.query_items(namespace_id=first.namespace_id)
    beta_items = facade.task_durable_memory.query_items(namespace_id=second.namespace_id)
    namespaces = facade.task_durable_memory.list_namespaces()

    assert first.namespace_id != second.namespace_id
    assert [item.task_memory_id for item in alpha_items] == [first.task_memory_id]
    assert [item.task_memory_id for item in beta_items] == [second.task_memory_id]
    assert {namespace.namespace_id for namespace in namespaces} == {first.namespace_id, second.namespace_id}


def test_working_memory_promotes_to_task_durable_without_global_pollution(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    work_item = facade.working_memory.create_item(
        task_run_id="taskrun:chapter",
        task_id="novel.longform",
        graph_id="graph:longform",
        owner_node_id="continuity_keeper",
        node_run_id="continuity_keeper.chapter_03",
        writer_agent_id="agent:continuity",
        kind="promotion_candidate",
        memory_semantics="decision",
        title="第三章天气",
        summary="第三章全程下雨，不能突然晴天。",
        status="archived",
        promotion_state="approved",
    )

    result = facade.promote_working_memory_item_to_task_durable(
        work_item.work_memory_id,
        actor_id="human:editor",
        reason="accepted continuity fact",
    )
    updated_work_item = facade.working_memory.get_item(work_item.work_memory_id)
    task_memory = result["task_memory"]

    assert updated_work_item is not None
    assert updated_work_item.status == "promoted"
    assert updated_work_item.promotion_state == "promoted_to_task_durable"
    assert task_memory.task_id == "novel.longform"
    assert task_memory.graph_id == "graph:longform"
    assert task_memory.source_work_memory_ids == (work_item.work_memory_id,)
    assert facade.governance_service.scan_durable_memory_headers(limit=20) == []


def test_task_durable_context_candidates_are_namespace_scoped(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    item = facade.task_durable_memory.create_item(
        task_id="novel.longform",
        graph_id="graph:longform",
        kind="timeline_fact",
        memory_semantics="temporal_event",
        title="入城时间",
        canonical_statement="主角在第四章才抵达都城。",
        summary="第四章抵达都城。",
    )
    facade.task_durable_memory.create_item(
        task_id="other.task",
        graph_id="graph:other",
        kind="timeline_fact",
        memory_semantics="temporal_event",
        title="其他任务",
        canonical_statement="不应被当前任务读取。",
    )

    candidates = facade.task_durable_memory.context_candidates(
        task_id="novel.longform",
        graph_id="graph:longform",
        requested_kinds=["timeline_fact"],
    )

    assert len(candidates) == 1
    assert all(isinstance(candidate, MemoryContextCandidate) for candidate in candidates)
    assert candidates[0].memory_layer == "task_durable"
    assert candidates[0].content_ref == item.task_memory_id
    assert candidates[0].metadata["task_id"] == "novel.longform"


def test_task_durable_global_promotion_requires_candidate_and_allowed_kind(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    item = facade.task_durable_memory.create_item(
        task_id="novel.longform",
        graph_id="graph:longform",
        kind="character_state",
        title="项目局部设定",
        canonical_statement="这只是长篇项目局部设定。",
    )

    try:
        facade.promote_task_durable_item_to_global_durable(
            item.task_memory_id,
            global_kind="cross_task_policy",
        )
    except ValueError as exc:
        first_error = str(exc)
    else:
        first_error = ""

    marked = facade.mark_task_durable_item_global_candidate(item.task_memory_id, reason="review")
    try:
        facade.promote_task_durable_item_to_global_durable(
            item.task_memory_id,
            global_kind="character_state",
        )
    except ValueError as exc:
        second_error = str(exc)
    else:
        second_error = ""

    assert "candidate" in first_error
    assert marked["task_memory"].global_promotion_state == "candidate"
    assert "allowed global promotion kind" in second_error
    assert facade.governance_service.scan_durable_memory_headers(limit=20) == []


def test_task_durable_global_promotion_writes_global_only_after_second_governance(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)
    item = facade.task_durable_memory.create_item(
        task_id="task.system",
        graph_id="graph:system",
        kind="cross_task_policy",
        title="跨任务规则",
        canonical_statement="跨任务编排时，必须先确认任务长期记忆命名空间。",
        summary="任务长期记忆必须按命名空间读取。",
    )

    facade.mark_task_durable_item_global_candidate(item.task_memory_id, reason="cross task rule")
    promoted = facade.promote_task_durable_item_to_global_durable(
        item.task_memory_id,
        global_kind="cross_task_policy",
        reason="approved",
    )
    headers = facade.governance_service.scan_durable_memory_headers(limit=20)
    updated = facade.task_durable_memory.get_item(item.task_memory_id)

    assert promoted["filename"]
    assert updated is not None
    assert updated.global_promotion_state == "promoted_to_global"
    assert updated.metadata["promoted_global_durable_filename"] == promoted["filename"]
    assert len(headers) == 1
    assert headers[0].title == "跨任务规则"



