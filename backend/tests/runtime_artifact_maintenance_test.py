from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from runtime.cache_manager import safe_cache_namespace
from runtime.memory.state_index import RuntimeStateIndex
from runtime.prompt_accounting import ModelTokenUsageRecord, PromptAccountingLedger
from runtime.storage_policy import DEFAULT_RUNTIME_STORAGE_POLICY, RuntimeStoragePolicy
from runtime.shared.models import TaskRun
from scripts.maintain_runtime_artifacts import RuntimeArtifactMaintenance


def test_runtime_storage_policy_declares_cache_tiers_and_ttls() -> None:
    policy = DEFAULT_RUNTIME_STORAGE_POLICY
    rules = policy.to_dict()["rules"]

    assert rules["runtime_active_detail"]["ttl_seconds"] == 24 * 60 * 60
    assert rules["terminal_hot_runtime_fact"]["ttl_seconds"] == 7 * 24 * 60 * 60
    assert rules["terminal_run_summary"]["ttl_seconds"] == 180 * 24 * 60 * 60
    assert rules["event_summary"]["ttl_seconds"] == 30 * 24 * 60 * 60
    assert rules["cold_runtime_archive"]["ttl_seconds"] == 90 * 24 * 60 * 60
    assert rules["manual_hold_archive_review"]["ttl_seconds"] == 365 * 24 * 60 * 60
    assert rules["sandbox_cache"]["ttl_seconds"] == 24 * 60 * 60
    assert rules["diagnostic_trace"]["ttl_seconds"] == 7 * 24 * 60 * 60
    assert rules["temporary_output"]["ttl_seconds"] == 3 * 24 * 60 * 60
    assert rules["prompt_map_hot_detail"]["ttl_seconds"] == 24 * 60 * 60
    assert rules["prompt_usage_hot_detail"]["ttl_seconds"] == 7 * 24 * 60 * 60
    assert rules["event_payload_hot_detail"]["ttl_seconds"] == 24 * 60 * 60
    assert policy.to_dict()["time_bucket_controls"]["prompt_map_keep_latest_per_scope"] == 20
    assert policy.to_dict()["time_bucket_controls"]["event_payload_keep_latest_per_run"] == 50
    assert policy.protected_durability_classes() == {"project_artifact", "user_asset"}


def test_runtime_artifact_maintenance_plans_expired_runtime_cache_without_active_task_cache(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    sandbox_root = project / "storage" / "runtime_cache" / "sandboxes"
    old = sandbox_root / "old"
    fresh = sandbox_root / "fresh"
    active_task_run_id = "taskrun:active"
    active = sandbox_root / safe_cache_namespace(active_task_run_id)
    for path in (old, fresh, active):
        path.mkdir(parents=True)
        (path / "scratch.txt").write_text("cache", encoding="utf-8")
    os.utime(old, (100.0, 100.0))
    os.utime(active, (100.0, 100.0))

    RuntimeStateIndex(project / "storage" / "runtime_state").upsert_task_run(
        TaskRun(
            task_run_id=active_task_run_id,
            session_id="session:active",
            task_id="task:active",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=100.0,
        )
    )

    result = RuntimeArtifactMaintenance(project, runtime_cache_ttl_seconds=1).plan()
    cache_deletes = [
        item
        for item in result["actions"]
        if item["reason"] == "runtime_cache_ttl_expired"
    ]

    assert [item["source"] for item in cache_deletes] == ["storage/runtime_cache/sandboxes/old"]
    assert result["mode"] == "dry_run"
    assert old.exists()
    assert active.exists()


def test_runtime_artifact_maintenance_default_sandbox_cache_ttl_is_24_hours(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    old = project / "storage" / "runtime_cache" / "sandboxes" / "old"
    old.mkdir(parents=True)
    (old / "scratch.txt").write_text("cache", encoding="utf-8")
    old_timestamp = time.time() - (2 * 24 * 60 * 60)
    os.utime(old, (old_timestamp, old_timestamp))

    result = RuntimeArtifactMaintenance(project).plan()

    assert result["storage_policy"]["rules"]["sandbox_cache"]["ttl_seconds"] == 24 * 60 * 60
    assert [
        item["source"]
        for item in result["actions"]
        if item["reason"] == "runtime_cache_ttl_expired"
    ] == ["storage/runtime_cache/sandboxes/old"]
    assert old.exists()


def test_runtime_artifact_maintenance_compacts_prompt_accounting_old_details(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    ledger = PromptAccountingLedger(project / "storage" / "runtime_state")
    old = time.time() - (8 * 24 * 60 * 60)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:old:provider_usage",
            request_id="modelreq:old",
            task_run_id="taskrun:old",
            session_id="session:old",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=old,
        )
    )

    plan = RuntimeArtifactMaintenance(project).plan()
    prompt_actions = [
        item
        for item in plan["actions"]
        if item["action"] == "compact_prompt_accounting"
    ]

    assert len(prompt_actions) == 1
    assert prompt_actions[0]["metadata"]["summary"]["compactable_detail_rows"] == 1
    assert ledger.list_token_usage(task_run_id="taskrun:old")

    result = RuntimeArtifactMaintenance(project).execute()

    assert result["mode"] == "execute"
    assert result["actions"][0]["action"] == "compact_prompt_accounting"
    assert result["actions"][0]["metadata"]["retention_receipt"]["status"] == "completed"
    assert ledger.list_token_usage(task_run_id="taskrun:old") == []
    assert ledger.summarize_task("taskrun:old")["total_tokens"] == 120


def test_runtime_artifact_maintenance_keeps_active_prompt_accounting_details(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    active_task_run_id = "taskrun:active"
    RuntimeStateIndex(project / "storage" / "runtime_state").upsert_task_run(
        TaskRun(
            task_run_id=active_task_run_id,
            session_id="session:active",
            task_id="task:active",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=100.0,
        )
    )
    ledger = PromptAccountingLedger(project / "storage" / "runtime_state")
    old = time.time() - (8 * 24 * 60 * 60)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:active:provider_usage",
            request_id="modelreq:active",
            task_run_id=active_task_run_id,
            session_id="session:active",
            source="provider_usage",
            prompt_tokens=100,
            total_tokens=100,
            created_at=old,
        )
    )

    plan = RuntimeArtifactMaintenance(project).plan()

    assert [
        item for item in plan["actions"] if item["action"] == "compact_prompt_accounting"
    ] == []
    assert ledger.list_token_usage(task_run_id=active_task_run_id)[0].total_tokens == 100


def test_runtime_artifact_maintenance_pressure_mode_reports_time_buckets(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    ledger = PromptAccountingLedger(project / "storage" / "runtime_state")
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:bucketed:provider_usage",
            request_id="modelreq:bucketed",
            task_run_id="taskrun:bucketed",
            session_id="session:bucketed",
            source="provider_usage",
            prompt_tokens=100,
            total_tokens=100,
            created_at=2_000_000.0,
        )
    )

    plan = RuntimeArtifactMaintenance(project, pressure_mode=True, prompt_hot_budget_mb=1).plan()

    pressure = plan["hot_cache_pressure"]
    assert pressure["enabled"] is True
    assert pressure["prompt_accounting"]["summary"]["bucket_count"] == 1
    assert pressure["prompt_accounting"]["files"]["token_usage.jsonl"]["shard_count"] == 1
    assert pressure["pressure"]["prompt_over_budget"] is False


def test_runtime_artifact_maintenance_archives_old_runtime_facts_to_l2(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    runtime_root = project / "storage" / "runtime_state"
    old_time = time.time() - 100
    event_file = runtime_root / "events" / "taskrun_old.jsonl"
    event_file.parent.mkdir(parents=True)
    event_file.write_text("{}\n", encoding="utf-8")
    payload_file = runtime_root / "event_payloads" / "aa" / "payload.json"
    payload_file.parent.mkdir(parents=True)
    payload_file.write_text('{"run_id":"taskrun:old","safe_run_id":"taskrun_old","payload":{}}', encoding="utf-8")
    runtime_object = runtime_root / "runtime_objects" / "observation" / "old.json"
    runtime_object.parent.mkdir(parents=True)
    runtime_object.write_text('{"payload":{"task_run_id":"taskrun:old"}}', encoding="utf-8")
    checkpoint_db = runtime_root / "graph_checkpoints.sqlite"
    _write_checkpoint_rows(checkpoint_db)
    for path in (event_file, payload_file, runtime_object, checkpoint_db):
        os.utime(path, (old_time, old_time))
    policy = RuntimeStoragePolicy(terminal_hot_seconds=1, temporary_output_ttl_seconds=1)

    plan = RuntimeArtifactMaintenance(project, storage_policy=policy).plan()
    archive_actions = [item for item in plan["actions"] if item["action"] == "archive_runtime_facts"]

    assert len(archive_actions) == 1
    assert len(archive_actions[0]["metadata"]["actions"]) == 4

    result = RuntimeArtifactMaintenance(project, storage_policy=policy).execute()

    assert result["actions"][0]["action"] == "archive_runtime_facts"
    assert not event_file.exists()
    assert not payload_file.exists()
    assert not runtime_object.exists()
    assert (runtime_root / "cold_archive" / "events").exists()
    assert (runtime_root / "cold_archive" / "checkpoints").exists()
    with sqlite3.connect(checkpoint_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = 'grun:old'").fetchone()[0] == 1
        assert conn.execute("SELECT checkpoint_id FROM checkpoints WHERE thread_id = 'grun:old'").fetchone()[0] == "gchk:old:0002"


def test_runtime_artifact_maintenance_keeps_active_runtime_event_hot(tmp_path: Path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    active_task_run_id = "taskrun:active"
    RuntimeStateIndex(project / "storage" / "runtime_state").upsert_task_run(
        TaskRun(
            task_run_id=active_task_run_id,
            session_id="session:active",
            task_id="task:active",
            execution_runtime_kind="single_agent_task",
            status="running",
            created_at=100.0,
            updated_at=100.0,
        )
    )
    event_file = project / "storage" / "runtime_state" / "events" / f"{safe_cache_namespace(active_task_run_id)}.jsonl"
    event_file.parent.mkdir(parents=True)
    event_file.write_text("{}\n", encoding="utf-8")
    old_time = time.time() - 100
    os.utime(event_file, (old_time, old_time))

    plan = RuntimeArtifactMaintenance(project, storage_policy=RuntimeStoragePolicy(terminal_hot_seconds=1)).plan()

    assert [item for item in plan["actions"] if item["action"] == "archive_runtime_facts"] == []
    assert event_file.exists()


def _write_checkpoint_rows(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            );
            INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)
                VALUES ('grun:old', 'graph_loop', 'gchk:old:0001', x'00', x'00');
            INSERT INTO checkpoints(thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)
                VALUES ('grun:old', 'graph_loop', 'gchk:old:0002', x'00', x'00');
            INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value)
                VALUES ('grun:old', 'graph_loop', 'gchk:old:0001', 'task', 1, 'channel', x'00');
            INSERT INTO writes(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value)
                VALUES ('grun:old', 'graph_loop', 'gchk:old:0002', 'task', 1, 'channel', x'00');
            """
        )
