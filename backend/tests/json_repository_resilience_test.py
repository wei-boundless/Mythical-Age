from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import pytest

import core.json_file_store as json_file_store_module
from runtime.shared.action_request import RuntimeActionRequest
from runtime.shared.execution_record import (
    RuntimeExecutionStore,
    build_idempotency_token,
    build_request_fingerprint,
)
from task_system.engagement.models import EngagementEvent
from task_system.engagement.repository import EngagementPlanConfigError, EngagementPlanRepository
from task_system.engagement.run_repository import EngagementRunRepository
from task_system.environments.repository import TaskEnvironmentConfigError, TaskEnvironmentRepository
from task_system.storage import TaskSystemStorage, TaskSystemStoragePayloadCorrupt


def test_task_environment_repository_atomic_write_preserves_existing_payload_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_dir = tmp_path / "backend"
    repository = TaskEnvironmentRepository(backend_dir)
    repository.upsert_group({"group_id": "group.one", "title": "One"})
    path = repository.config_path
    original = json.loads(path.read_text(encoding="utf-8"))

    def fail_replace(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(json_file_store_module.os, "replace", fail_replace)

    with pytest.raises(TaskEnvironmentConfigError):
        repository.upsert_group({"group_id": "group.two", "title": "Two"})

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_engagement_run_repository_serializes_concurrent_event_appends(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    repository = EngagementRunRepository(backend_dir)

    def append_event(index: int) -> None:
        repository.append_event(
            EngagementEvent(
                engagement_run_id="erun:1",
                event_type="progress",
                summary=f"event-{index}",
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(append_event, range(40)))

    assert {item["summary"] for item in repository.list_events()} == {f"event-{index}" for index in range(40)}


def test_engagement_plan_repository_reports_corrupt_payload(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    repository = EngagementPlanRepository(backend_dir)
    repository.path.parent.mkdir(parents=True, exist_ok=True)
    repository.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(EngagementPlanConfigError):
        repository.list()


def test_task_system_storage_raises_on_corrupt_payload(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    storage = TaskSystemStorage(backend_dir)
    path = storage.path("task_graphs.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad-json", encoding="utf-8")

    with pytest.raises(TaskSystemStoragePayloadCorrupt):
        storage.read_object("task_graphs.json", {"task_graphs": []})

    assert storage.read_object("missing.json", {"ok": True}) == {"ok": True}


def test_runtime_execution_store_preserves_existing_payload_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    store = RuntimeExecutionStore(root)
    task_run_id = "taskrun:test"
    action_request = RuntimeActionRequest(
        request_id="rtact:test",
        task_run_id=task_run_id,
        request_type="tool_call",
        step_id="step:1",
        directive_ref="directive:test",
        operation_id="op.test",
        payload={"tool_name": "shell"},
    )
    fingerprint = build_request_fingerprint(step_id="step:1", operation_id="op.test", payload=action_request.payload)
    record = store.create_record(
        task_run_id=task_run_id,
        step_id="step:1",
        action_request=action_request,
        directive_ref="directive:test",
        operation_id="op.test",
        executor_type="tool",
        replay_policy="deny_auto_replay",
        request_fingerprint=fingerprint,
        idempotency_token=build_idempotency_token(
            task_run_id=task_run_id,
            step_id="step:1",
            operation_id="op.test",
            request_fingerprint=fingerprint,
        ),
    )
    path = store._payload_path(task_run_id)
    original = json.loads(path.read_text(encoding="utf-8"))

    def fail_replace(_src: object, _dst: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(json_file_store_module.os, "replace", fail_replace)
    monkeypatch.setattr(json_file_store_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError):
        store.mark_dispatched(record)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []

