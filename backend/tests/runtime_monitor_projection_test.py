from types import SimpleNamespace

from harness.runtime.monitor_projection import TaskRunMonitorProjector


class EventLogStub:
    def __init__(self, events=None):
        self._events = events or {}

    def list_events(self, task_run_id):
        return list(self._events.get(task_run_id, []))


class EventStub:
    def __init__(self, *, event_type, created_at, payload=None, event_id="event:1", offset=0):
        self.event_type = event_type
        self.created_at = created_at
        self.payload = payload or {}
        self.event_id = event_id
        self.offset = offset

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "created_at": self.created_at,
            "offset": self.offset,
            "payload": self.payload,
        }


def task_run(**patch):
    data = {
        "task_run_id": "taskrun:turn:session-a:1:abc",
        "session_id": "session-a",
        "task_id": "task:turn:session-a:1",
        "execution_runtime_kind": "single_agent_task",
        "status": "running",
        "terminal_reason": "",
        "created_at": 100.0,
        "updated_at": 120.0,
        "diagnostics": {},
    }
    data.update(patch)
    return SimpleNamespace(**data)


def test_running_monitor_items_are_dynamic_and_tick_with_now():
    projector = TaskRunMonitorProjector(EventLogStub())

    first = projector.project_task_run(task_run(), now=130.0)
    second = projector.project_task_run(task_run(), now=150.0)

    assert first["bucket"] == "running"
    assert first["resource_class"] == "dynamic"
    assert first["ended_at"] is None
    assert first["duration_seconds"] == 30.0
    assert second["duration_seconds"] == 50.0


def test_terminal_monitor_items_are_static_and_duration_is_frozen():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(status="completed", updated_at=135.0)

    first = projector.project_task_run(run, now=150.0)
    second = projector.project_task_run(run, now=300.0)

    assert first["bucket"] == "completed"
    assert first["resource_class"] == "static"
    assert first["ended_at"] == 135.0
    assert first["duration_seconds"] == 35.0
    assert second["duration_seconds"] == 35.0


def test_stale_waiting_executor_moves_to_diagnostics_not_running():
    projector = TaskRunMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(status="waiting_executor", updated_at=120.0)

    item = projector.project_task_run(run, now=300.0)

    assert item["bucket"] == "diagnostics"
    assert item["lifecycle"] == "stale"
    assert item["resource_class"] == "static"
    assert item["stale"] is True


def test_waiting_approval_moves_to_diagnostics_and_freezes_duration():
    projector = TaskRunMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(status="waiting_approval", updated_at=120.0)

    first = projector.project_task_run(run, now=300.0)
    second = projector.project_task_run(run, now=600.0)

    assert first["bucket"] == "diagnostics"
    assert first["lifecycle"] == "action_required"
    assert first["resource_class"] == "static"
    assert first["action_required"] is True
    assert first["duration_seconds"] == 20.0
    assert second["duration_seconds"] == 20.0


def test_blocked_moves_to_diagnostics_and_freezes_duration():
    projector = TaskRunMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(status="blocked", updated_at=125.0)

    first = projector.project_task_run(run, now=300.0)
    second = projector.project_task_run(run, now=600.0)

    assert first["bucket"] == "diagnostics"
    assert first["lifecycle"] == "action_required"
    assert first["resource_class"] == "static"
    assert first["action_required"] is True
    assert first["duration_seconds"] == 25.0
    assert second["duration_seconds"] == 25.0


def test_internal_titles_are_not_exposed_and_route_is_authoritative():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(
        task_run_id="taskrun:graph",
        task_id="taskinst:internal",
        diagnostics={
            "title": "taskinst:internal",
            "project_title": "商业长篇项目",
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:main",
        },
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["title"] == "商业长篇项目"
    assert item["route"]["kind"] == "task_graph_run"
    assert item["route"]["graph_id"] == "graph:main"
    assert item["graph_run_id"] == "grun:main"
    assert item["has_graph_run"] is True
    assert item["route"]["graph_run_id"] == "grun:main"


def test_latest_step_summary_is_exposed_from_event_log():
    event = EventStub(
        event_type="step_summary_recorded",
        created_at=125.0,
        payload={"step": "tool_result", "status": "completed", "summary": "已读取文件。"},
    )
    projector = TaskRunMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}))

    item = projector.project_task_run(task_run(), now=150.0)

    assert item["latest_step_summary"] == "已读取文件。"
    assert item["latest_step_name"] == "tool_result"


def test_missing_time_fields_enter_diagnostics():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(created_at=0.0, updated_at=0.0)

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "missing_runtime_time" in item["diagnostic_reasons"]


def test_task_graph_route_without_graph_id_enters_diagnostics():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(
        task_run_id="taskrun:graph",
        diagnostics={"graph_run_id": "grun:graph", "graph_harness_config_id": "ghcfg:graph"},
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "missing_route_graph_id" in item["diagnostic_reasons"]


def test_unknown_status_enters_diagnostics():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(status="repairing")

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "unknown_task_status" in item["diagnostic_reasons"]


def test_global_monitor_filters_internal_child_runs_and_applies_per_bucket_limit():
    projector = TaskRunMonitorProjector(EventLogStub())
    runs = [
        task_run(task_run_id="taskrun:running-1", updated_at=140.0),
        task_run(task_run_id="taskrun:running-2", updated_at=130.0),
        task_run(task_run_id="taskrun:completed-1", status="completed", updated_at=145.0),
        task_run(task_run_id="taskrun:completed-2", status="completed", updated_at=135.0),
        task_run(
            task_run_id="taskrun:child",
            task_id="taskinst:turn:session-a:child",
            task_contract_ref="taskinst:turn:session-a:child",
            updated_at=150.0,
            diagnostics={
                "coordination_stage_id": "chapter_draft",
                "stage_request_id": "nodeexec:chapter_draft",
            },
        ),
    ]

    monitor = projector.build_global_monitor(runs, now=160.0, limit=1)

    assert [item["task_run_id"] for item in monitor["buckets"]["running"]] == ["taskrun:running-1"]
    assert [item["task_run_id"] for item in monitor["buckets"]["completed"]] == ["taskrun:completed-1"]
    assert "taskrun:child" not in {item["task_run_id"] for item in monitor["task_runs"]}


def test_main_chat_taskinst_task_run_remains_monitorable():
    projector = TaskRunMonitorProjector(EventLogStub())
    run = task_run(
        task_run_id="taskrun:turn:session-a:1:formal-task",
        task_id="taskinst:turn:session-a:1:formal-task",
        task_contract_ref="rtobj:task_run_contract:formal-task",
        execution_runtime_kind="single_agent_task",
        diagnostics={
            "turn_id": "turn:session-a:1",
            "contract": {
                "user_visible_goal": "生成交付文档",
                "task_run_goal": "生成交付文档",
            },
        },
    )

    monitor = projector.build_global_monitor([run], now=150.0, limit=20)

    assert [item["task_run_id"] for item in monitor["buckets"]["running"]] == [run.task_run_id]
    item = monitor["buckets"]["running"][0]
    assert item["route"]["kind"] == "chat_turn_runtime"
    assert item["session_id"] == "session-a"
