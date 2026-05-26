from __future__ import annotations

from memory_system.formal_memory_content import materialize_formal_memory_candidate
from memory_system.formal_memory_service import FormalMemoryService


def test_formal_memory_candidate_commit_and_directed_read(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    service.sync_graph_spec(
        graph_id="graph:writing",
        task_run_id="taskrun:writing",
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
            "commit_visibility_policy": {"visible_after": "next_clock"},
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


def test_formal_memory_syncs_repository_from_resource_nodes(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    result = service.sync_graph_spec(
        graph_id="graph:resource-layer",
        task_run_id="taskrun:resource-layer",
        graph_spec={
            "nodes": [],
            "resource_nodes": [
                {
                    "node_id": "memory.resource.world",
                    "resource_type": "memory_repository",
                    "title": "Resource Layer World Memory",
                    "repository_id": "memory.resource.world",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.resource.world",
                            "collections": [
                                {
                                    "collection_id": "world",
                                    "record_kinds": ["world_bible"],
                                }
                            ],
                        }
                    },
                }
            ],
        },
    )

    assert result["repository_count"] == 1
    assert result["collection_count"] == 1
    assert result["repositories"][0]["logical_repository_id"] == "memory.resource.world"
    assert result["collections"][0]["collection_id"] == "world"


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


def test_required_formal_memory_rejects_refs_only_shell_records(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    service.sync_graph_spec(
        graph_id="graph:memory-content",
        task_run_id="taskrun:memory-content",
        graph_spec={
            "nodes": [
                {
                    "node_id": "memory.project",
                    "node_type": "memory_repository",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.project",
                            "collections": [
                                {
                                    "collection_id": "canon",
                                    "content_requirement": {
                                        "canonical_text_required": True,
                                        "artifact_ref_only_allowed": False,
                                    },
                                }
                            ],
                        }
                    },
                }
            ]
        },
    )
    version, _ = service.store.write_candidate(
        repository_id="run:taskrun_memory-content:memory.project",
        collection_id="canon",
        record_key="canon.current",
        logical_repository_id="memory.project",
        task_run_id="taskrun:memory-content",
        scope_kind="run_scoped",
        scope_id="taskrun:memory-content",
        record_kind="canon",
        payload={},
        canonical_text="",
        summary="shell",
        artifact_refs=["artifact:canon.md"],
        source_node_id="writer",
        source_edge_id="edge.writer.canon",
        source_node_run_id="taskrun:memory-content:writer",
        source_clock_seq=1,
    )
    service.store.commit_version(
        candidate_version_id=version.version_id,
        edge_id="edge.commit.canon",
        node_run_id="taskrun:memory-content:commit",
        source_clock_seq=1,
    )

    selected = service.select_for_node(
        read_edges=[
            {
                "edge_id": "edge.reader.canon",
                "repository": "memory.project",
                "collection": "canon",
                "selector": {"record_key": "canon.current", "status_filter": ["committed"]},
                "content_requirement": {
                    "canonical_text_required": True,
                    "artifact_ref_only_allowed": False,
                },
                "on_missing": "block",
            }
        ],
        task_run_id="taskrun:memory-content",
        node_run_id="taskrun:memory-content:reader",
        clock_seq=2,
    )

    assert selected["required_records"] == []
    assert selected["missing_required_records"][0]["reason"] == "content_requirement_not_satisfied"
    assert selected["missing_required_records"][0]["rejected_versions"][0]["content_state"] == "refs_only"


def test_collection_content_requirement_cannot_be_loosened_by_candidate_or_edge(tmp_path) -> None:
    service = FormalMemoryService(tmp_path)
    service.sync_graph_spec(
        graph_id="graph:memory-content-hard-boundary",
        task_run_id="taskrun:memory-content-hard-boundary",
        graph_spec={
            "nodes": [
                {
                    "node_id": "memory.project",
                    "node_type": "memory_repository",
                    "metadata": {
                        "memory_repository": {
                            "repository_id": "memory.project",
                            "collections": [
                                {
                                    "collection_id": "canon",
                                    "content_requirement": {
                                        "canonical_text_required": True,
                                        "artifact_ref_only_allowed": False,
                                    },
                                }
                            ],
                        }
                    },
                }
            ]
        },
    )

    try:
        service.write_candidate_from_edge(
            edge={
                "edge_id": "edge.writer.canon",
                "repository": "memory.project",
                "collection": "canon",
                "record_key": "canon.current",
                "record_kind": "canon",
                "content_requirement": {
                    "canonical_text_required": False,
                    "artifact_ref_only_allowed": True,
                },
            },
            candidate={
                "kind": "canon",
                "summary": "shell",
                "artifact_refs": ["artifact:canon.md"],
                "content_requirement": {
                    "canonical_text_required": False,
                    "artifact_ref_only_allowed": True,
                },
            },
            task_run_id="taskrun:memory-content-hard-boundary",
            node_run_id="taskrun:memory-content-hard-boundary:writer",
        )
    except ValueError as exc:
        assert "content requirement" in str(exc)
    else:
        raise AssertionError("candidate loosened the collection content requirement")


def test_formal_memory_candidate_materialization_reads_artifact_text(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "memory_candidate.md"
    artifact.write_text("# Canon\n\n正式记忆正文。", encoding="utf-8")
    candidate, errors = materialize_formal_memory_candidate(
        candidate={"summary": "artifact_refs", "artifact_refs": [f"artifact:{artifact.name}"]},
        edge={
            "edge_id": "edge.write.canon",
            "memory_edge_type": "commit",
            "repository": "memory.project",
            "collection": "canon",
            "record_key": "canon.current",
            "record_kinds": ["canon"],
            "source_output_key": "artifact_refs",
            "content_requirement": {
                "canonical_text_required": True,
                "artifact_ref_only_allowed": False,
            },
            "materialization_policy": {
                "enabled": True,
                "source": "artifact_refs",
                "canonical_text_mode": "full_text",
                "summary_mode": "first_heading_or_excerpt",
            },
        },
        fallback_write_policy={"writable_kinds": ["canon"], "writable_scopes": ["test"]},
        output_bundle={
            "artifact_refs": [f"artifact:{artifact.name}"],
            "workspace_root": str(tmp_path),
        },
    )

    assert errors == []
    assert candidate["canonical_text"] == "# Canon\n\n正式记忆正文。"
    assert candidate["summary"] == "Canon"
    assert candidate["content_requirement"]["canonical_text_required"] is True
