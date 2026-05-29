from __future__ import annotations

import hashlib
import sqlite3

from artifact_system import ArtifactRepositoryService
from runtime.shared.artifact_refs import ArtifactRefIndex
from tests.support.trace_stubs import StateIndexStub, TaskRunStub, TraceReaderStub


def test_artifact_repository_defaults_to_task_run_isolation(tmp_path) -> None:
    service = ArtifactRepositoryService(tmp_path)
    service.record_materialization(
        task_run_id="taskrun:one",
        repository_id="artifact.project.manuscript",
        collection_id="chapters",
        stage_id="chapter_draft",
        node_run_id="taskrun:one:chapter_draft",
        artifact_refs=["artifact:output/run-one/chapter.md"],
        created_files=["chapter.md"],
        status="accepted",
    )

    run_one = service.overview(task_run_id="taskrun:one", repository_id="artifact.project.manuscript")
    run_two = service.overview(task_run_id="taskrun:two", repository_id="artifact.project.manuscript")

    assert run_one["artifact_count"] == 1
    assert run_one["artifacts"][0]["task_run_id"] == "taskrun:one"
    assert run_two["artifact_count"] == 0


def test_artifact_repository_records_contract_and_file_hash(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    artifact = workspace / "output" / "run-one" / "chapter.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Chapter\n\nReal artifact body.\n", encoding="utf-8")
    service = ArtifactRepositoryService(tmp_path / "repo", workspace_root=workspace)

    service.record_materialization(
        task_run_id="taskrun:one",
        repository_id="artifact.project.manuscript",
        collection_id="chapters",
        graph_id="graph:novel",
        graph_run_id="grun:novel:001",
        stage_id="chapter_draft",
        node_run_id="nodeexec:chapter_draft:001",
        task_ref="task.chapter_draft",
        output_contract_id="contract.chapter.draft",
        producer_node_id="chapter_draft",
        artifact_refs=["artifact:output/run-one/chapter.md"],
        created_files=["chapter.md"],
        artifact_root="output/run-one",
        status="accepted",
    )

    overview = service.overview(output_contract_id="contract.chapter.draft", graph_run_id="grun:novel:001")
    assert overview["artifact_count"] == 1
    assert service.overview(output_contract_id="contract.chapter.draft", graph_run_id="grun:other")["artifact_count"] == 0
    record = overview["artifacts"][0]
    assert record["output_contract_id"] == "contract.chapter.draft"
    assert record["producer_node_id"] == "chapter_draft"
    assert record["graph_run_id"] == "grun:novel:001"
    assert record["content_hash"] == hashlib.sha1(artifact.read_bytes()).hexdigest()
    assert record["content_hash"] != hashlib.sha1(b"artifact:output/run-one/chapter.md").hexdigest()
    assert record["metadata"]["content_hash_source"] == "file"
    assert service.latest_refs_by_contract(output_contract_id="contract.chapter.draft") == [
        "artifact:output/run-one/chapter.md"
    ]


def test_artifact_repository_migrates_existing_sqlite_schema(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    db_path = repo_root / "artifact_repository.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE artifact_repositories (
                repository_id TEXT PRIMARY KEY,
                logical_repository_id TEXT NOT NULL DEFAULT '',
                effective_repository_id TEXT NOT NULL DEFAULT '',
                task_run_id TEXT NOT NULL DEFAULT '',
                scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                scope_id TEXT NOT NULL DEFAULT '',
                graph_id TEXT NOT NULL DEFAULT '',
                node_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                lifecycle_policy_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                authority TEXT NOT NULL DEFAULT 'artifact_repository.repository'
            );
            CREATE TABLE artifact_records (
                artifact_id TEXT PRIMARY KEY,
                artifact_ref TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '',
                repository_id TEXT NOT NULL,
                collection_id TEXT NOT NULL DEFAULT 'default',
                logical_repository_id TEXT NOT NULL DEFAULT '',
                effective_repository_id TEXT NOT NULL DEFAULT '',
                task_run_id TEXT NOT NULL DEFAULT '',
                scope_kind TEXT NOT NULL DEFAULT 'run_scoped',
                scope_id TEXT NOT NULL DEFAULT '',
                graph_id TEXT NOT NULL DEFAULT '',
                stage_id TEXT NOT NULL DEFAULT '',
                node_run_id TEXT NOT NULL DEFAULT '',
                task_ref TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'accepted',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                authority TEXT NOT NULL DEFAULT 'artifact_repository.record'
            );
            INSERT INTO artifact_records (
                artifact_id, artifact_ref, path, repository_id, collection_id,
                logical_repository_id, effective_repository_id, task_run_id, scope_kind, scope_id,
                graph_id, stage_id, node_run_id, task_ref,
                status, content_hash, metadata_json, created_at, updated_at, authority
            ) VALUES (
                'artifactrec:legacy', 'artifact:output/legacy.md', 'output/legacy.md',
                'artifact.project.manuscript', 'default', 'artifact.project.manuscript',
                'run:taskrun_legacy:artifact.project.manuscript', 'taskrun:legacy',
                'run_scoped', 'taskrun:legacy', 'graph:legacy', 'stage:legacy',
                'nodeexec:legacy', 'task.legacy',
                'accepted', 'hash', '{}', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', 'artifact_repository.record'
            );
            """
        )

    service = ArtifactRepositoryService(repo_root, workspace_root=tmp_path)
    service.record_materialization(
        task_run_id="taskrun:migrated",
        repository_id="artifact.project.manuscript",
        output_contract_id="contract.migrated",
        artifact_refs=["artifact:output/migrated.md"],
    )

    assert service.overview(output_contract_id="contract.migrated")["artifact_count"] == 1
    legacy = service.overview(output_contract_id="", task_run_id="taskrun:legacy")["artifacts"][0]
    assert legacy["graph_run_id"] == ""


def test_artifact_ref_index_uses_repository_for_contract_lookup(tmp_path) -> None:
    service = ArtifactRepositoryService(tmp_path / "repo", workspace_root=tmp_path)
    service.record_materialization(
        task_run_id="taskrun:one",
        repository_id="artifact.project.manuscript",
        output_contract_id="contract.chapter.draft",
        artifact_refs=["artifact:output/chapter.md"],
        status="accepted",
    )
    index = ArtifactRefIndex(StateIndexStub(()), TraceReaderStub({}), artifact_repository=service)

    assert index.latest_output_refs_by_contract(output_contract_id="contract.chapter.draft") == [
        "artifact:output/chapter.md"
    ]


def test_artifact_ref_index_falls_back_to_trace_contract_lookup() -> None:
    task_run = TaskRunStub(task_run_id="taskrun:trace", updated_at=20.0)
    index = ArtifactRefIndex(
        StateIndexStub((task_run,)),
        TraceReaderStub(
            {
                "taskrun:trace": {
                    "task_result": {
                        "output_contract_id": "contract.trace",
                        "output_refs": ["artifact:trace/result.md"],
                    }
                }
            }
        ),
    )

    assert index.latest_output_refs_by_contract(output_contract_id="contract.trace") == [
        "artifact:trace/result.md"
    ]


