from __future__ import annotations

from memory_system import MemoryFacade
from memory_system.task_durable_memory import TaskDurableMemoryService


def test_task_durable_memory_service_can_be_used_standalone(tmp_path) -> None:
    service = TaskDurableMemoryService(tmp_path / "standalone_task_durable")

    first = service.create_item(
        task_id="novel.alpha",
        graph_id="graph:alpha",
        kind="character_state",
        memory_semantics="working_fact",
        title="主角仍在主城",
        canonical_statement="第二章结束前，主角仍在主城。",
        summary="主角不能提前离开主城。",
        retrieval_hints=["主角", "主城"],
    )
    second = service.create_item(
        task_id="novel.beta",
        graph_id="graph:beta",
        kind="character_state",
        memory_semantics="working_fact",
        title="另一项目设定",
        canonical_statement="Beta 项目使用独立世界观。",
        summary="不应污染 Alpha。",
    )

    alpha_items = service.query_items(namespace_id=first.namespace_id)
    beta_items = service.query_items(namespace_id=second.namespace_id)
    namespaces = service.list_namespaces()

    assert first.namespace_id != second.namespace_id
    assert [item.task_memory_id for item in alpha_items] == [first.task_memory_id]
    assert [item.task_memory_id for item in beta_items] == [second.task_memory_id]
    assert {namespace.namespace_id for namespace in namespaces} == {first.namespace_id, second.namespace_id}


def test_task_durable_records_remain_standalone_namespace_scoped_without_runtime_candidates(tmp_path) -> None:
    service = TaskDurableMemoryService(tmp_path / "standalone_task_durable")
    item = service.create_item(
        task_id="novel.longform",
        graph_id="graph:longform",
        kind="timeline_fact",
        memory_semantics="temporal_event",
        title="入城时间",
        canonical_statement="主角在第四章才抵达都城。",
        summary="第四章抵达都城。",
    )
    service.create_item(
        task_id="other.task",
        graph_id="graph:other",
        kind="timeline_fact",
        memory_semantics="temporal_event",
        title="其他任务",
        canonical_statement="不应被当前任务读取。",
    )

    items = service.query_items(
        task_id="novel.longform",
        graph_id="graph:longform",
        kind="timeline_fact",
    )

    assert not hasattr(service, "context_candidates")
    assert [record.task_memory_id for record in items] == [item.task_memory_id]
    assert items[0].task_id == "novel.longform"


def test_task_durable_memory_is_not_wired_into_memory_facade(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    assert not hasattr(facade, "task_durable_memory")
    assert not hasattr(facade.runtime_services, "task_durable_memory")
    assert not hasattr(facade.bundle_service, "task_durable_memory")
    assert not hasattr(facade.bundle_service, "build_task_durable_memory_context_candidates")
    assert not hasattr(facade, "promote_working_memory_item_to_task_durable")
    assert not hasattr(facade, "mark_task_durable_item_global_candidate")
    assert not hasattr(facade, "promote_task_durable_item_to_global_durable")


def test_task_durable_memory_layer_is_rejected_by_runtime_read_plan(tmp_path) -> None:
    facade = MemoryFacade(tmp_path)

    for layer in ("task_durable", "task_durable_memory"):
        try:
            facade.bundle_service.build_memory_runtime_view(
                session_id="session-task-durable-disconnected",
                memory_request_profile={"requested_memory_layers": [layer]},
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

        assert "disconnected from runtime" in error
