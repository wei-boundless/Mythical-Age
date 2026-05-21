from __future__ import annotations

from memory_system.working_memory_finalizer import WorkingMemoryFinalizer
from memory_system.working_memory_service import WorkingMemoryService
from runtime.coordination_runtime.context_packet_resolver import resolve_memory_snapshot
from runtime.coordination_runtime.memory_helpers import _working_memory_read_operation_from_context


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


def test_working_memory_repository_read_edges_filter_formal_records(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    selected = service.create_item(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="baseline_memory_seed",
        node_run_id="taskrun:test:baseline_memory_seed",
        writer_agent_id="agent:memory",
        kind="baseline_world_spine",
        summary="committed world spine",
        status="accepted",
        scope="graph_scope",
        visibility="shared_in_graph",
        metadata={
            "formal_memory": {
                "repository_id": "memory.writing.baseline",
                "collection_id": "world",
                "record_kind": "baseline_world_spine",
                "commit_state": "committed",
                "source_edge_id": "edge.memory_commit.baseline.world",
                "version_selector": "latest_committed_before_clock",
            }
        },
    )
    service.create_item(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="world_design",
        node_run_id="taskrun:test:world_design",
        writer_agent_id="agent:writer",
        kind="world_candidate",
        summary="candidate should not be selected",
        status="accepted",
        scope="graph_scope",
        visibility="shared_in_graph",
        metadata={
            "formal_memory": {
                "repository_id": "memory.writing.artifact_index",
                "collection_id": "candidates",
                "record_kind": "world_candidate",
                "commit_state": "candidate",
            }
        },
    )

    selection = service.select_for_node(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="chapter_draft",
        node_run_id="taskrun:test:chapter_draft",
        reader_agent_id="agent:writer",
        node_role="writer",
        memory_read_policy={"readable_scopes": ["graph_scope"], "readable_visibilities": ["shared_in_graph"]},
        request={
            "repository_read_edges": [
                {
                    "edge_id": "edge.memory_read.chapter_draft.baseline.world",
                    "repository": "memory.writing.baseline",
                    "collection": "world",
                    "record_keys": ["baseline_world_spine"],
                    "selector": {"status_filter": ["committed"]},
                    "version_selector": "latest_committed_before_clock",
                }
            ]
        },
    )

    assert [item.work_memory_id for item in selection["required_items"]] == [selected.work_memory_id]
    selected_records = selection["diagnostics"]["selected_repository_records"]
    assert selected_records[0]["repository_id"] == "memory.writing.baseline"
    assert selected_records[0]["collection_id"] == "world"

    missing = service.select_for_node(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="chapter_draft",
        node_run_id="taskrun:test:chapter_draft:missing",
        reader_agent_id="agent:writer",
        node_role="writer",
        memory_read_policy={"readable_scopes": ["graph_scope"], "readable_visibilities": ["shared_in_graph"]},
        request={
            "repository_read_edges": [
                {
                    "edge_id": "edge.memory_read.chapter_draft.baseline.characters",
                    "repository": "memory.writing.baseline",
                    "collection": "characters",
                    "record_keys": ["frozen_character_fact"],
                    "selector": {"status_filter": ["committed"]},
                    "on_missing": "block",
                }
            ]
        },
    )
    assert missing["required_items"] == ()
    assert missing["diagnostics"]["missing_repository_read_edges"][0]["edge_id"] == "edge.memory_read.chapter_draft.baseline.characters"


def test_memory_snapshot_resolves_nested_working_memory_records() -> None:
    snapshot = resolve_memory_snapshot(
        working_memory_context={
            "working_memory.required": {
                "refs": ["wm:1"],
                "items": [
                    {
                        "work_memory_id": "wm:1",
                        "kind": "baseline_world_spine",
                        "metadata": {
                            "formal_memory": {
                                "repository_id": "memory.writing.baseline",
                                "collection_id": "world",
                                "record_kind": "baseline_world_spine",
                                "version_selector": "latest_committed_before_clock",
                            }
                        },
                    }
                ],
            },
            "repository_read_edges": [
                {
                    "edge_id": "edge.memory_read.chapter_draft.baseline.world",
                    "repository": "memory.writing.baseline",
                    "collection": "world",
                }
            ],
            "read_log_id": "wmread:1",
        },
        dispatch_context={"dispatch_event_id": "evt:1", "clock_seq": 12, "scope_path": ["run", "phase.chapter_loop"]},
        state={"diagnostics": {"coordination_graph_spec": {"edges": []}}},
        stage_id="chapter_draft",
        node_id="chapter_draft",
    )

    assert snapshot["resolved_record_refs"] == ["wm:1"]
    assert snapshot["resolved_records"][0]["work_memory_id"] == "wm:1"
    assert snapshot["resolved_versions"][0]["version_selector"] == "latest_committed_before_clock"
    assert snapshot["repository_read_edges"][0]["edge_id"] == "edge.memory_read.chapter_draft.baseline.world"


def test_working_memory_finalizer_preserves_terminal_items_for_audit(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    finalizer = WorkingMemoryFinalizer(service)
    service.create_item(
        task_run_id="taskrun:test",
        owner_node_id="node_a",
        node_run_id="taskrun:test:node_a",
        writer_agent_id="agent:a",
        kind="scratch_note",
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

    remaining_by_id = {item.work_memory_id: item for item in remaining}
    assert len(remaining_by_id) == 2
    assert remaining_by_id[accepted.work_memory_id].status == "archived"
    discarded_items = [item for item in remaining if item.status == "discarded"]
    assert len(discarded_items) == 1


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


def test_working_memory_read_logging_is_idempotent_for_replayed_stage(tmp_path) -> None:
    service = WorkingMemoryService(tmp_path)
    first = service.record_read(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="chapter_progress_router",
        node_run_id="taskrun:test:chapter_progress_router",
        run_attempt_id="0",
        reader_agent_id="agent:reviewer",
        selected_item_ids=(),
        excluded_item_ids=(),
        request={"max_items": 5},
    )
    second = service.record_read(
        task_run_id="taskrun:test",
        graph_id="graph:test",
        owner_node_id="chapter_progress_router",
        node_run_id="taskrun:test:chapter_progress_router",
        run_attempt_id="0",
        reader_agent_id="agent:reviewer",
        selected_item_ids=(),
        excluded_item_ids=(),
        request={"max_items": 5},
    )

    assert second.read_log_id == first.read_log_id
    assert len(service.list_read_logs("taskrun:test", limit=20)) == 1
