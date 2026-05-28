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

    def list_events(self, task_run_id: str):
        return list(self.events_by_task_run_id.get(task_run_id, []))


class StateIndexStub:
    def __init__(self, task_runs: list[TaskRun]):
        self.task_runs = task_runs

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
