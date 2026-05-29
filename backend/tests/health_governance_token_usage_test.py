from __future__ import annotations

import time
from types import SimpleNamespace

from health_system.governance import HealthGovernanceBuilder
from runtime.prompt_accounting import ModelTokenUsageRecord, PromptAccountingLedger
from runtime.shared.models import TaskRun


class EventStub:
    def __init__(self, event_type: str, payload: dict):
        self.event_type = event_type
        self.payload = payload
        self.event_id = f"event:{event_type}"
        self.task_run_id = "taskrun:test"
        self.offset = 0
        self.created_at = 100.0
        self.refs = {}

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "task_run_id": self.task_run_id,
            "event_type": self.event_type,
            "offset": self.offset,
            "created_at": self.created_at,
            "payload": self.payload,
            "refs": self.refs,
        }


class EventLogStub:
    def __init__(self, events_by_task_run_id: dict[str, list[EventStub]]):
        self.events_by_task_run_id = events_by_task_run_id
        self.deleted_task_run_ids: list[str] = []

    def list_events(self, task_run_id: str):
        return list(self.events_by_task_run_id.get(task_run_id, []))

    def delete_events(self, task_run_id: str):
        self.deleted_task_run_ids.append(task_run_id)
        return bool(self.events_by_task_run_id.pop(task_run_id, []))


class StateIndexStub:
    def __init__(self, task_runs: list[TaskRun]):
        self.task_runs = task_runs
        self.deleted_task_run_ids: list[str] = []

    def list_task_runs(self):
        return list(self.task_runs)

    def list_task_agent_runs(self, _task_run_id: str):
        return []

    def list_task_worker_spawn_requests(self, _task_run_id: str):
        return []

    def list_task_worker_spawn_results(self, _task_run_id: str):
        return []

    def list_task_supervision_records(self, _task_run_id: str):
        return []

    def prune_task_runs(self, task_run_ids: set[str]):
        targets = {str(item) for item in task_run_ids}
        existing = {item.task_run_id for item in self.task_runs if item.task_run_id in targets}
        self.deleted_task_run_ids.extend(sorted(existing))
        self.task_runs = [item for item in self.task_runs if item.task_run_id not in existing]
        return {
            "authority": "orchestration.runtime_state_index.prune_task_runs",
            "requested_task_run_ids": sorted(targets),
            "deleted_task_run_ids": sorted(existing),
            "deleted_counts": {"task_runs": len(existing)} if existing else {},
        }


def test_health_token_usage_is_task_trace_scoped_not_session_duplicated() -> None:
    now = time.time()
    task_runs = [
        TaskRun(task_run_id="taskrun:a", session_id="session:same", task_id="task.a", created_at=now - 20, updated_at=now - 10),
        TaskRun(task_run_id="taskrun:b", session_id="session:same", task_id="task.b", created_at=now - 15, updated_at=now - 5),
    ]
    events = {
        "taskrun:a": [EventStub("step_summary_recorded", {"summary": "short task trace"})],
        "taskrun:b": [EventStub("step_summary_recorded", {"summary": "another short trace"})],
    }
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(task_runs),
        event_log=EventLogStub(events),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(query_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    token_usage = HealthGovernanceBuilder(runtime).build_token_usage(limit=10)
    task_tokens = [int(item["token_total"]) for item in token_usage["tasks"]]
    session = token_usage["sessions"][0]

    assert len(task_tokens) == 2
    assert all(0 < value < 100 for value in task_tokens)
    assert session["total_tokens"] == sum(task_tokens)
    assert token_usage["summary"]["total_tokens"] == sum(task_tokens)
    assert token_usage["summary"]["trace_estimate_task_count"] == 2


def test_health_token_usage_prefers_prompt_accounting_provider_usage(tmp_path) -> None:
    now = time.time()
    task_run = TaskRun(
        task_run_id="taskrun:accounted",
        session_id="session:accounted",
        task_id="task.accounted",
        created_at=now - 20,
        updated_at=now - 10,
    )
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:accounted:local_prediction",
            request_id="modelreq:accounted",
            task_run_id="taskrun:accounted",
            session_id="session:accounted",
            source="local_prediction",
            prompt_tokens=300,
            total_tokens=300,
            created_at=now - 15,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:accounted:provider_usage",
            request_id="modelreq:accounted",
            task_run_id="taskrun:accounted",
            session_id="session:accounted",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            cached_tokens=30,
            cache_read_tokens=30,
            total_tokens=120,
            created_at=now - 14,
        )
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([task_run]),
        event_log=EventLogStub({"taskrun:accounted": [EventStub("step_summary_recorded", {"summary": "large trace should not win"})]}),
        prompt_accounting_ledger=ledger,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(query_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    token_usage = HealthGovernanceBuilder(runtime).build_token_usage(limit=10)
    task = token_usage["tasks"][0]

    assert task["token_total"] == 120
    assert task["token_source"] == "provider_usage"
    assert task["predicted_token_total"] == 300
    assert task["cached_tokens"] == 30
    assert token_usage["summary"]["exact_total_tokens"] == 120
    assert token_usage["summary"]["predicted_total_tokens"] == 300
    assert token_usage["summary"]["trace_estimate_total_tokens"] == 0


def test_health_task_record_maintenance_dry_run_does_not_delete_records() -> None:
    now = time.time()
    old_completed = TaskRun(
        task_run_id="taskrun:old-completed",
        session_id="session:maintenance",
        task_id="task.old",
        status="completed",
        created_at=now - 200000,
        updated_at=now - 190000,
    )
    running = TaskRun(
        task_run_id="taskrun:running",
        session_id="session:maintenance",
        task_id="task.running",
        status="running",
        created_at=now - 200000,
        updated_at=now - 190000,
    )
    state_index = StateIndexStub([old_completed, running])
    event_log = EventLogStub(
        {
            "taskrun:old-completed": [EventStub("step_summary_recorded", {"summary": "done"})],
            "taskrun:running": [EventStub("step_summary_recorded", {"summary": "active"})],
        }
    )
    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=event_log,
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {
            "summary": {"completed": 1, "running": 1},
            "task_runs": [
                {
                    "task_run_id": "taskrun:old-completed",
                    "status": "completed",
                    "bucket": "completed",
                    "resource_class": "static",
                },
                {
                    "task_run_id": "taskrun:running",
                    "status": "running",
                    "bucket": "running",
                    "resource_class": "dynamic",
                },
            ],
        },
    )
    runtime = SimpleNamespace(query_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    result = HealthGovernanceBuilder(runtime).prune_task_records(
        task_run_ids=["taskrun:old-completed", "taskrun:running"],
        dry_run=True,
        min_age_seconds=0,
    )

    assert result["mode"] == "dry_run"
    assert result["eligible_task_run_ids"] == ["taskrun:old-completed"]
    assert result["protected_task_run_ids"] == ["taskrun:running"]
    assert result["deleted_task_run_ids"] == []
    assert state_index.deleted_task_run_ids == []
    assert event_log.deleted_task_run_ids == []


def test_health_task_record_maintenance_protects_failed_without_report_and_deletes_old_completed() -> None:
    now = time.time()
    old_completed = TaskRun(
        task_run_id="taskrun:old-completed",
        session_id="session:maintenance",
        task_id="task.old",
        status="completed",
        created_at=now - 200000,
        updated_at=now - 190000,
    )
    failed_without_report = TaskRun(
        task_run_id="taskrun:failed",
        session_id="session:maintenance",
        task_id="task.failed",
        status="failed",
        created_at=now - 200000,
        updated_at=now - 190000,
    )
    state_index = StateIndexStub([old_completed, failed_without_report])
    event_log = EventLogStub(
        {
            "taskrun:old-completed": [EventStub("step_summary_recorded", {"summary": "done"})],
            "taskrun:failed": [EventStub("loop_error", {"error": "failed"})],
        }
    )
    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=event_log,
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {
            "summary": {"completed": 1, "failed": 1},
            "task_runs": [
                {
                    "task_run_id": "taskrun:old-completed",
                    "status": "completed",
                    "bucket": "completed",
                    "resource_class": "static",
                },
                {
                    "task_run_id": "taskrun:failed",
                    "status": "failed",
                    "bucket": "failed",
                    "resource_class": "static",
                },
            ],
        },
    )
    runtime = SimpleNamespace(query_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    result = HealthGovernanceBuilder(runtime).prune_task_records(
        task_run_ids=["taskrun:old-completed", "taskrun:failed"],
        min_age_seconds=0,
    )

    assert result["mode"] == "execute"
    assert result["deleted_task_run_ids"] == ["taskrun:old-completed"]
    assert result["protected_task_run_ids"] == ["taskrun:failed"]
    assert result["maintenance_receipt"]["status"] == "completed"
    assert state_index.deleted_task_run_ids == ["taskrun:old-completed"]
    assert event_log.deleted_task_run_ids == ["taskrun:old-completed"]
