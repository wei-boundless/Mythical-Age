from __future__ import annotations

import time
from types import SimpleNamespace

from health_system.governance import HealthGovernanceBuilder
from harness.runtime.run_monitor import RuntimeMonitorProjector
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

    def list_recent_task_runs(self, limit: int = 240):
        return sorted(
            list(self.task_runs),
            key=lambda item: float(item.updated_at or item.created_at or 0.0),
            reverse=True,
        )[:limit]

    def get_task_run(self, task_run_id: str):
        task_run_id = str(task_run_id or "")
        return next((item for item in self.task_runs if item.task_run_id == task_run_id), None)

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


class RuntimeObjectsStub:
    def __init__(self, payloads: dict[str, dict] | None = None) -> None:
        self.payloads = dict(payloads or {})

    def get_object(self, ref: str):
        return dict(self.payloads.get(str(ref), {}))


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
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

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
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=ledger,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    token_usage = HealthGovernanceBuilder(runtime).build_token_usage(limit=10)
    task = token_usage["tasks"][0]

    assert task["token_total"] == 120
    assert task["token_source"] == "provider_usage"
    assert task["predicted_token_total"] == 300
    assert task["cached_tokens"] == 30
    assert token_usage["summary"]["exact_total_tokens"] == 120
    assert token_usage["summary"]["predicted_total_tokens"] == 300
    assert token_usage["summary"]["trace_estimate_total_tokens"] == 0


def test_health_token_usage_includes_turn_runs_without_task_run_id(tmp_path) -> None:
    now = time.time()
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:turn:local_prediction",
            request_id="modelreq:turn",
            run_id="turnrun:turn:session-main:3",
            session_id="session-main",
            source="local_prediction",
            prompt_tokens=300,
            total_tokens=300,
            created_at=now - 12,
        )
    )
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:turn:provider_usage",
            request_id="modelreq:turn",
            run_id="turnrun:turn:session-main:3",
            session_id="session-main",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=now - 10,
        )
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([]),
        event_log=EventLogStub({}),
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=ledger,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    token_usage = HealthGovernanceBuilder(runtime).build_token_usage(limit=10)
    record = token_usage["tasks"][0]

    assert token_usage["summary"]["provider_usage_task_count"] == 1
    assert token_usage["summary"]["exact_total_tokens"] == 120
    assert token_usage["summary"]["predicted_total_tokens"] == 300
    assert token_usage["summary"]["trace_estimate_total_tokens"] == 0
    assert record["task_run_id"] == "turnrun:turn:session-main:3"
    assert record["run_id"] == "turnrun:turn:session-main:3"
    assert record["record_kind"] == "turn_run"
    assert record["token_source"] == "provider_usage"
    assert record["token_total"] == 120


def test_health_token_usage_summary_counts_records_without_session_id(tmp_path) -> None:
    now = time.time()
    ledger = PromptAccountingLedger(tmp_path)
    ledger.record_token_usage(
        ModelTokenUsageRecord(
            usage_id="tokuse:modelreq:unscoped:provider_usage",
            request_id="modelreq:unscoped",
            run_id="modelreq:unscoped",
            source="provider_usage",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            created_at=now - 10,
        )
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([]),
        event_log=EventLogStub({}),
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=ledger,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    token_usage = HealthGovernanceBuilder(runtime).build_token_usage(limit=10)

    assert token_usage["summary"]["total_tokens"] == 120
    assert token_usage["summary"]["overall_total_tokens"] == 120
    assert token_usage["summary"]["exact_total_tokens"] == 120
    assert token_usage["summary"]["week_total_tokens"] >= 120
    assert token_usage["summary"]["session_count"] == 0
    assert token_usage["sessions"] == []
    assert token_usage["tasks"][0]["token_total"] == 120


def test_health_task_list_hides_graph_node_child_task_runs() -> None:
    now = time.time()
    root = TaskRun(
        task_run_id="taskrun:graph-root",
        session_id="session:graph",
        task_id="task.writing.modular_novel.master",
        status="waiting_executor",
        created_at=now - 100,
        updated_at=now - 10,
        diagnostics={"graph_run_id": "grun:graph-root", "graph_id": "graph.writing.modular_novel.master"},
    )
    child = TaskRun(
        task_run_id="gtask:child-node",
        session_id="session:graph",
        task_id="task.writing.modular_novel.node.project_brief@graph_module.design_init",
        status="completed",
        created_at=now - 90,
        updated_at=now - 5,
        diagnostics={
            "origin_kind": "graph_node_assigned",
            "graph_run_id": "grun:graph-root",
            "graph_node_id": "graph_module.design_init::project_brief",
            "graph_work_order_id": "gwork:project_brief",
        },
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([root, child]),
        event_log=EventLogStub({}),
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    result = HealthGovernanceBuilder(runtime).build_tasks(limit=10)

    assert [item["task_run_id"] for item in result["tasks"]] == ["taskrun:graph-root"]
    assert result["summary"]["hidden_child_task_count"] == 1


def test_health_task_list_excludes_historical_unscoped_runs_when_operational_scope_exists() -> None:
    now = time.time()
    active_graph = TaskRun(
        task_run_id="taskrun:graph-active",
        session_id="session:graph",
        task_id="task.writing.modular_novel.master",
        status="waiting_executor",
        created_at=now - 100,
        updated_at=now - 10,
        diagnostics={
            "graph_run_id": "grun:graph-active",
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "project.creation.writing.honghuang",
        },
    )
    failed_same_scope = TaskRun(
        task_run_id="taskrun:graph-failed",
        session_id="session:graph-old",
        task_id="task.writing.modular_novel.master",
        status="failed",
        terminal_reason="node_failed",
        created_at=now - 200,
        updated_at=now - 150,
        diagnostics={
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "project.creation.writing.honghuang",
        },
    )
    old_prompt_cache = TaskRun(
        task_run_id="taskrun:old-prompt-cache",
        session_id="session:old",
        task_id="prompt-cache-live-five-floor-dungeon:old",
        status="aborted",
        terminal_reason="user_aborted",
        created_at=now - 300,
        updated_at=now - 250,
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([active_graph, failed_same_scope, old_prompt_cache]),
        event_log=EventLogStub({}),
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {"summary": {}, "task_runs": []},
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    result = HealthGovernanceBuilder(runtime).build_tasks(limit=10)

    assert [item["task_run_id"] for item in result["tasks"]] == ["taskrun:graph-active", "taskrun:graph-failed"]
    assert result["summary"]["hidden_history_task_count"] == 1


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
        runtime_objects=RuntimeObjectsStub(),
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
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

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
        runtime_objects=RuntimeObjectsStub(),
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
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

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


def test_health_governance_reports_resumable_rollout_risks_without_terminal_recovery_branch_risks() -> None:
    now = time.time()
    stopped_terminal = TaskRun(
        task_run_id="taskrun:stopped-terminal",
        session_id="session:health-rollout",
        task_id="task.stopped-terminal",
        execution_runtime_kind="single_agent_task",
        status="aborted",
        terminal_reason="user_aborted",
        created_at=now - 2000,
        updated_at=now - 1900,
    )
    missing_rollout = TaskRun(
        task_run_id="taskrun:missing-rollout",
        session_id="session:health-rollout",
        task_id="task.missing-rollout",
        execution_runtime_kind="single_agent_task",
        status="waiting_executor",
        terminal_reason="waiting_executor",
        created_at=now - 2000,
        updated_at=now - 1900,
    )
    failed_terminal = TaskRun(
        task_run_id="taskrun:failed-terminal",
        session_id="session:health-rollout",
        task_id="task.failed-terminal",
        execution_runtime_kind="single_agent_task",
        status="failed",
        terminal_reason="model_call_recovery_required",
        created_at=now - 1700,
        updated_at=now - 1600,
        diagnostics={
            "recoverable_error": {"retryable": True},
            "recovery_action": "rerun_task_executor",
        },
    )
    state_index = StateIndexStub([stopped_terminal, missing_rollout, failed_terminal])
    event_log = EventLogStub({
        "taskrun:stopped-terminal": [EventStub("task_run_finished", {"terminal_reason": "user_aborted"})],
        "taskrun:missing-rollout": [EventStub("step_summary_recorded", {"summary": "waiting"})],
        "taskrun:failed-terminal": [EventStub("loop_error", {"error": "failed"})],
    })
    monitor_projector = RuntimeMonitorProjector(event_log)
    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=event_log,
        monitor_projector=monitor_projector,
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: monitor_projector.build_global_monitor(state_index.list_task_runs(), now=now, limit=limit),
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    risks = HealthGovernanceBuilder(runtime).build_risks(limit=10)["risks"]
    risk_codes = {str(item.get("risk_code") or "") for item in risks}

    assert "missing_rollout_for_resumable_task" in risk_codes
    assert "stale_waiting_executor" in risk_codes
    assert "interrupted_without_recovery_branch" not in risk_codes
    assert "repeated_terminal_recovery_branch_failure" not in risk_codes


def test_health_task_record_maintenance_protects_explicit_parent_lineage_records() -> None:
    now = time.time()
    source = TaskRun(
        task_run_id="taskrun:lineage-source",
        session_id="session:maintenance-lineage",
        task_id="task.lineage.source",
        status="completed",
        created_at=now - 200000,
        updated_at=now - 190000,
    )
    child = TaskRun(
        task_run_id="taskrun:lineage-child",
        session_id="session:maintenance-lineage",
        task_id="task.lineage.child",
        status="completed",
        created_at=now - 200000,
        updated_at=now - 190000,
        diagnostics={
            "root_task_run_id": "taskrun:lineage-source",
            "parent_task_run_id": "taskrun:lineage-source",
            "lineage": {
                "root_task_run_id": "taskrun:lineage-source",
                "parent_task_run_id": "taskrun:lineage-source",
            },
        },
    )
    state_index = StateIndexStub([source, child])
    event_log = EventLogStub({
        "taskrun:lineage-source": [EventStub("step_summary_recorded", {"summary": "done"})],
        "taskrun:lineage-child": [EventStub("step_summary_recorded", {"summary": "done"})],
    })
    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=event_log,
        runtime_objects=RuntimeObjectsStub(),
        prompt_accounting_ledger=None,
        list_global_live_monitor=lambda limit: {
            "summary": {"completed": 2},
            "task_runs": [
                {
                    "task_run_id": "taskrun:lineage-source",
                    "status": "completed",
                    "bucket": "completed",
                    "resource_class": "static",
                },
                {
                    "task_run_id": "taskrun:lineage-child",
                    "status": "completed",
                    "bucket": "completed",
                    "resource_class": "static",
                },
            ],
        },
    )
    runtime = SimpleNamespace(harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host))

    result = HealthGovernanceBuilder(runtime).prune_task_records(
        task_run_ids=["taskrun:lineage-source", "taskrun:lineage-child"],
        dry_run=True,
        min_age_seconds=0,
    )
    skipped = {item["task_run_id"]: item["protection_reasons"] for item in result["skipped"]}

    assert result["eligible_task_run_ids"] == []
    assert set(result["protected_task_run_ids"]) == {"taskrun:lineage-source", "taskrun:lineage-child"}
    assert "task_lineage_parent" in skipped["taskrun:lineage-source"]
    assert "task_lineage_record" in skipped["taskrun:lineage-child"]
