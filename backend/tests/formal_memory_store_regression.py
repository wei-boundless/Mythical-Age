from __future__ import annotations

from memory_system.formal_memory_service import FormalMemoryService


def test_formal_memory_candidate_commit_and_directed_read(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    service.sync_graph_spec(
        graph_id="graph:writing",
        graph_spec={
            "nodes": [
                {
                    "node_id": "memory.writing.baseline",
                    "node_type": "memory_repository",
                    "title": "Baseline Memory",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.writing.baseline",
                            "schema_id": "schema.writing.memory_record",
                            "collections": [
                                {
                                    "collection_id": "world",
                                    "title": "World Bible",
                                    "schema_id": "schema.writing.world_bible",
                                    "record_kinds": ["world_bible"],
                                }
                            ],
                        }
                    },
                }
            ]
        },
    )

    version, write_txn = service.write_candidate_from_edge(
        edge={
            "edge_id": "edge.world_author.baseline.world",
            "repository": "memory.writing.baseline",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
        },
        candidate={
            "kind": "world_bible",
            "summary": "洪荒世界观定稿候选",
            "payload": {"canonical_text": "天地初辟，万族争道。"},
        },
        task_run_id="taskrun:writing",
        node_run_id="taskrun:writing:world_author",
        source_node_id="world_author",
        source_clock="clock:4",
        source_clock_seq=4,
        artifact_refs=["artifact:world_candidate_v004.md"],
    )

    assert version.status == "candidate"
    assert write_txn.receipt["record_key"] == "world_bible.current"

    committed, commit_txn = service.commit_from_edge(
        edge={
            "edge_id": "edge.world_review.baseline.world",
            "repository": "memory.writing.baseline",
            "collection": "world",
            "record_key": "world_bible.current",
            "record_kind": "world_bible",
            "receipt_policy": {"visible_after": "next_clock"},
        },
        candidate_version_id=version.version_id,
        node_run_id="taskrun:writing:world_review",
        source_clock="clock:5",
        source_clock_seq=5,
    )

    assert committed.status == "committed"
    assert commit_txn.receipt["visible_after_clock_seq"] == 6

    before_visible = service.select_for_node(
        read_edges=[
            {
                "edge_id": "edge.baseline.chapter_writer.world",
                "repository": "memory.writing.baseline",
                "collection": "world",
                "selector": {
                    "collection": "world",
                    "record_key": "world_bible.current",
                    "record_kind": "world_bible",
                    "status_filter": ["committed"],
                },
                "version_selector": {"mode": "latest_committed_before_clock"},
                "on_missing": "block",
            }
        ],
        node_run_id="taskrun:writing:chapter_writer",
        clock="clock:5",
        clock_seq=5,
    )
    assert before_visible["required_records"] == []
    assert before_visible["missing_required_records"][0]["edge_id"] == "edge.baseline.chapter_writer.world"

    after_visible = service.select_for_node(
        read_edges=[
            {
                "edge_id": "edge.baseline.chapter_writer.world",
                "repository": "memory.writing.baseline",
                "collection": "world",
                "selector": {
                    "collection": "world",
                    "record_key": "world_bible.current",
                    "record_kind": "world_bible",
                    "status_filter": ["committed"],
                },
                "version_selector": {"mode": "latest_committed_before_clock"},
                "model_visible_label": "世界观定稿",
                "usage_instruction": "必须遵守世界观定稿。",
                "on_missing": "block",
            }
        ],
        node_run_id="taskrun:writing:chapter_writer",
        clock="clock:6",
        clock_seq=6,
    )

    records = after_visible["required_records"]
    assert len(records) == 1
    assert records[0]["record_key"] == "world_bible.current"
    assert records[0]["version_id"] == version.version_id
    assert records[0]["model_visible_label"] == "世界观定稿"
    assert after_visible["read_log_ids"]


def test_formal_memory_write_is_idempotent_by_node_edge_and_content(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    edge = {
        "edge_id": "edge.writer.memory",
        "repository": "memory.project",
        "collection": "facts",
        "record_key": "fact.current",
        "record_kind": "fact",
    }
    candidate = {
        "kind": "fact",
        "summary": "same fact",
        "payload": {"content": "same fact"},
        "idempotency_key": "idem:writer:fact",
    }

    first_version, first_txn = service.write_candidate_from_edge(
        edge=edge,
        candidate=candidate,
        task_run_id="taskrun:test",
        node_run_id="taskrun:test:writer",
        source_node_id="writer",
        source_clock_seq=1,
    )
    second_version, second_txn = service.write_candidate_from_edge(
        edge=edge,
        candidate=candidate,
        task_run_id="taskrun:test",
        node_run_id="taskrun:test:writer",
        source_node_id="writer",
        source_clock_seq=1,
    )

    assert second_version.version_id == first_version.version_id
    assert second_txn.transaction_id == first_txn.transaction_id
