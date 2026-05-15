from __future__ import annotations

from memory_system.working_memory_finalizer import WorkingMemoryFinalizer
from memory_system.working_memory_service import WorkingMemoryService
from orchestration.runtime_loop.langgraph_coordination_runtime import _working_memory_read_operation_from_context


def test_working_memory_defaults_to_node_scope_only(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    own = service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        writer_agent_id="agent:a",
        kind="note",
        summary="own memory",
        status="accepted",
        scope="node_scope",
        visibility="private_to_node",
    )
    service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_b",
        node_run_id="taskrun:test:node_b",
        writer_agent_id="agent:b",
        kind="note",
        summary="other shared memory",
        status="accepted",
        scope="graph_scope",
        visibility="shared_in_graph",
    )

    selection = service.select_for_node(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        reader_agent_id="agent:a",
        node_role="participant",
        memory_read_policy={},
    )

    required_ids = [item.work_memory_id for item in selection["required_items"]]
    assert required_ids == [own.work_memory_id]


def test_working_memory_handoff_only_requires_explicit_authorization(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    handoff = service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_b",
        node_run_id="taskrun:test:node_b",
        writer_agent_id="agent:b",
        kind="handoff_note",
        summary="edge scoped handoff",
        status="accepted",
        scope="graph_scope",
        visibility="handoff_only",
    )

    denied = service.select_for_node(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        reader_agent_id="agent:a",
        node_role="participant",
        memory_read_policy={"readable_scopes": ["graph_scope"]},
    )
    allowed = service.select_for_node(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        reader_agent_id="agent:a",
        node_role="participant",
        memory_read_policy={
            "readable_scopes": ["graph_scope"],
            "readable_visibilities": ["handoff_only"],
            "allow_handoff_visibility": True,
            "authorized_source_node_ids": ["node_b"],
        },
    )

    assert [item.work_memory_id for item in denied["required_items"]] == []
    assert [item.work_memory_id for item in allowed["required_items"]] == [handoff.work_memory_id]


def test_working_memory_finalizer_purges_low_value_terminal_items(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    finalizer = WorkingMemoryFinalizer(service)
    service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        writer_agent_id="agent:a",
        kind="draft_note",
        summary="discard me",
        status="draft",
        scope="node_scope",
        visibility="private_to_node",
    )
    accepted = service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        writer_agent_id="agent:a",
        kind="decision_record",
        summary="keep as archived",
        status="accepted",
        scope="node_scope",
        visibility="private_to_node",
    )

    result = finalizer.finalize_task_run("taskrun:test")
    remaining = service.query_items(task_run_id="taskrun:test", limit=20)

    assert result.purged_count == 1
    assert result.purged_status_counts["discarded"] == 1
    assert result.store_optimized is True
    assert [item.work_memory_id for item in remaining] == [accepted.work_memory_id]
    assert remaining[0].status == "archived"


def test_working_memory_read_operation_exposes_selected_refs_and_denials() -> None:
    operation = _working_memory_read_operation_from_context(
        context={
            "node_run_id": "taskrun:test:node_a",
            "read_log_id": "wmread:test",
            "denied_reason": "",
            "working_memory.required": {"refs": ["wm:1"]},
            "working_memory.preferred": {"refs": ["wm:2"]},
            "diagnostics": {
                "excluded_refs": ["wm:3"],
                "selected_item_previews": [
                    {
                        "work_memory_id": "wm:1",
                        "owner_node_id": "node_a",
                        "scope": "node_scope",
                        "visibility": "private_to_node",
                        "kind": "decision",
                        "summary": "selected",
                    }
                ],
            },
        },
        stage_id="world_candidate",
        node_id="world_candidate",
        agent_id="agent:writer",
    )

    assert operation["operation"] == "memory_read"
    assert operation["selected_working_memory_refs"] == ["wm:1", "wm:2"]
    assert operation["excluded_working_memory_refs"] == ["wm:3"]
    assert operation["selected_item_previews"][0]["work_memory_id"] == "wm:1"
