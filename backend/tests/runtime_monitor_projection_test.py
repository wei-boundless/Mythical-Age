import time
from pathlib import Path
from types import SimpleNamespace

from harness.runtime.run_monitor import RuntimeMonitorActionService, RuntimeMonitorProjector, RuntimeMonitorService
from harness.runtime.run_monitor.signals import build_runtime_monitor_envelope


class EventLogStub:
    def __init__(self, events=None):
        self._events = events or {}
        self.list_recent_event_calls = []
        self.event_count_calls = []

    def list_events(self, task_run_id):
        return list(self._events.get(task_run_id, []))

    def list_recent_events(self, task_run_id, *, limit=240):
        self.list_recent_event_calls.append((task_run_id, limit))
        return list(self._events.get(task_run_id, []))[-max(1, int(limit or 240)) :]

    def event_count(self, task_run_id):
        self.event_count_calls.append(task_run_id)
        return len(self._events.get(task_run_id, []))


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


class StateIndexStub:
    def __init__(self, task_runs=None, turn_runs=None):
        self._task_runs = list(task_runs or [])
        self._turn_runs = {getattr(item, "turn_run_id", ""): item for item in list(turn_runs or [])}

    def list_recent_task_runs(self, *, limit=80):
        return list(self._task_runs)[: max(1, int(limit or 80))]

    def list_session_task_runs(self, session_id):
        return [item for item in self._task_runs if getattr(item, "session_id", "") == session_id]

    def get_task_run(self, task_run_id):
        for item in self._task_runs:
            if getattr(item, "task_run_id", "") == task_run_id:
                return item
        return None

    def get_turn_run(self, turn_run_id):
        return self._turn_runs.get(turn_run_id)


class ActiveTurnRecordStub:
    def __init__(self, **payload):
        self.payload = dict(payload)

    def __getattr__(self, name):
        if name in self.payload:
            return self.payload[name]
        raise AttributeError(name)

    def to_dict(self):
        return dict(self.payload)


class ActiveTurnRegistryStub:
    def __init__(self, record=None):
        self.record = record

    def resolve_current(self, session_id):
        if self.record is None or self.record.payload.get("session_id") != session_id:
            return None
        return self.record


class RunRegistryStub:
    def __init__(self, runs=None):
        self._runs = list(runs or [])

    def list_runs(self):
        return list(self._runs)

    def latest_session_run(self, session_id):
        for run in self._runs:
            if getattr(run, "session_id", "") == session_id:
                return run
        return None


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


def turn_run(**patch):
    data = {
        "turn_run_id": "turnrun:session-a:1",
        "session_id": "session-a",
        "turn_id": "turn:session-a:1",
        "execution_runtime_kind": "single_agent_turn",
        "status": "running",
        "created_at": 100.0,
        "updated_at": 125.0,
        "latest_event_offset": 0,
        "terminal_reason": "",
        "diagnostics": {},
    }
    data.update(patch)
    return SimpleNamespace(**data)


def runtime_run(**patch):
    data = {
        "stream_run_id": "strun:test",
        "session_id": "session-a",
        "status": "running",
        "created_at": 95.0,
        "updated_at": 126.0,
    }
    data.update(patch)
    return SimpleNamespace(**data)


def test_session_task_summary_uses_top_level_session_task_not_child_runs():
    now = time.time()
    top_level = task_run(
        task_run_id="taskrun:turn:session-dev:1:root",
        session_id="session-dev",
        task_id="task:turn:session-dev:1",
        status="running",
        updated_at=now,
        diagnostics={"title": "开发计算器"},
    )
    child_run = task_run(
        task_run_id="taskrun:child:newer",
        session_id="session-dev",
        task_id="task.graph.node",
        status="running",
        updated_at=now + 10,
        diagnostics={"graph_node_id": "node.compile"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([child_run, top_level]),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    summary = service.get_session_task_summary("session-dev")

    assert summary["available"] is True
    assert summary["task_run_id"] == "taskrun:turn:session-dev:1:root"
    assert summary["title"] == "开发计算器"
    assert summary["task_run_count"] == 1


def test_session_live_monitor_exposes_active_turn_snapshot():
    task = task_run(
        task_run_id="taskrun:turn:session-dev:1:root",
        session_id="session-dev",
        task_id="task:turn:session-dev:1",
        status="running",
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([task]),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:1",
                bound_task_run_id="taskrun:turn:session-dev:1:root",
                state="running_task",
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.get_session_live_monitor("session-dev")

    assert monitor["active_task_run_id"] == "taskrun:turn:session-dev:1:root"
    assert monitor["active_turn_snapshot"] == {
        "session_id": "session-dev",
        "turn_id": "turn:session-dev:1",
        "bound_task_run_id": "taskrun:turn:session-dev:1:root",
        "state": "running_task",
    }


def test_global_monitor_includes_active_turn_when_task_run_not_started_yet():
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(
            task_runs=[],
            turn_runs=[turn_run(turn_run_id="turnrun:session-dev:1", session_id="session-dev", turn_id="turn:session-dev:1")],
        ),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        run_registry=RunRegistryStub([runtime_run(session_id="session-dev")]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:1",
                turn_run_id="turnrun:session-dev:1",
                bound_task_run_id="",
                stream_run_id="strun:test",
                state="model_turn",
                started_at=100.0,
                updated_at=126.0,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.list_global_live_monitor(limit=20)

    assert monitor["summary"]["running"] == 1
    assert monitor["buckets"]["running"][0]["task_run_id"] == "turnrun:session-dev:1"
    assert monitor["buckets"]["running"][0]["execution_runtime_kind"] == "single_agent_turn"
    assert monitor["buckets"]["running"][0]["summary"] == "正在分析请求并准备执行。"


def test_run_monitor_projects_active_turn_as_primary_signal():
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(
            task_runs=[],
            turn_runs=[turn_run(turn_run_id="turnrun:session-dev:1", session_id="session-dev", turn_id="turn:session-dev:1")],
        ),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        run_registry=RunRegistryStub([runtime_run(session_id="session-dev")]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:1",
                turn_run_id="turnrun:session-dev:1",
                bound_task_run_id="",
                stream_run_id="strun:test",
                state="model_turn",
                started_at=100.0,
                updated_at=126.0,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["authority"] == "runtime_monitor"
    assert monitor["summary"]["active"] == 1
    assert monitor["primary"][0]["signal_id"] == "turnrun:session-dev:1"
    assert monitor["primary"][0]["source_kind"] == "turn_run"
    assert monitor["primary"][0]["state"] == "active"
    assert monitor["management"]["lanes"]["current"][0]["signal_id"] == "turnrun:session-dev:1"
    clear_action = next(item for item in monitor["primary"][0]["actions"] if item["action"] == "clear_from_monitor")
    delete_action = next(item for item in monitor["primary"][0]["actions"] if item["action"] == "delete_record")
    assert clear_action["enabled"] is False
    assert delete_action["enabled"] is False


def test_runtime_monitor_management_includes_recent_terminal_records(tmp_path):
    completed = task_run(
        task_run_id="taskrun:completed",
        status="completed",
        terminal_reason="completed",
        updated_at=140.0,
        diagnostics={"title": "已完成任务"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([completed]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    live_monitor = service.list_global_live_monitor(limit=20)
    monitor = service.collect_global_runtime_monitor(limit=20)

    assert live_monitor["task_runs"] == []
    assert monitor["summary"]["recent"] == 1
    assert monitor["management"]["lanes"]["recent"][0]["signal_id"] == "taskrun:completed"
    clear_action = next(item for item in monitor["management"]["lanes"]["recent"][0]["actions"] if item["action"] == "clear_from_monitor")
    delete_action = next(item for item in monitor["management"]["lanes"]["recent"][0]["actions"] if item["action"] == "delete_record")
    assert clear_action["enabled"] is True
    assert delete_action["enabled"] is True


def test_runtime_monitor_clear_action_hides_signal_without_deleting_record(tmp_path):
    completed = task_run(
        task_run_id="taskrun:completed",
        status="completed",
        terminal_reason="completed",
        updated_at=140.0,
        diagnostics={"title": "已完成任务"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([completed]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)
    runtime = SimpleNamespace(
        base_dir=tmp_path / "backend",
        harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host),
    )
    action_service = RuntimeMonitorActionService(runtime=runtime, monitor_service=service)

    import asyncio

    result = asyncio.run(action_service.execute({"action": "clear_from_monitor", "signal_id": "taskrun:completed"}))

    assert result["accepted"] is True
    assert runtime_host.state_index.get_task_run("taskrun:completed") is completed
    hidden = result["monitor"]["management"]["lanes"]["hidden"]
    assert [item["signal_id"] for item in hidden] == ["taskrun:completed"]
    assert result["monitor"]["management"]["lanes"]["recent"] == []


def test_run_monitor_orders_same_priority_by_last_activity():
    monitor = build_runtime_monitor_envelope(
        items=[
            {
                "task_run_id": "taskrun:old",
                "bucket": "waiting",
                "title": "old waiting task",
                "updated_at": 120.0,
                "last_activity_at": 120.0,
                "started_at": 100.0,
            },
            {
                "task_run_id": "taskrun:new",
                "bucket": "waiting",
                "title": "new waiting task",
                "updated_at": 150.0,
                "last_activity_at": 150.0,
                "started_at": 100.0,
            },
        ],
        now=180.0,
        limit=10,
    )

    assert [item["signal_id"] for item in monitor["signals"]] == ["taskrun:new", "taskrun:old"]


def test_run_monitor_keeps_bound_active_turn_when_task_run_is_not_visible():
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(
            task_runs=[],
            turn_runs=[turn_run(turn_run_id="turnrun:session-dev:1", session_id="session-dev", turn_id="turn:session-dev:1")],
        ),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        run_registry=RunRegistryStub([runtime_run(session_id="session-dev")]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:1",
                turn_run_id="turnrun:session-dev:1",
                bound_task_run_id="taskrun:turn:session-dev:1:bound",
                stream_run_id="strun:test",
                state="tool_execution",
                started_at=100.0,
                updated_at=126.0,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["summary"]["active"] == 1
    assert monitor["primary"][0]["signal_id"] == "turnrun:session-dev:1"
    assert monitor["primary"][0]["task_run_id"] == "taskrun:turn:session-dev:1:bound"
    assert monitor["primary"][0]["navigation_target"]["task_run_id"] == "taskrun:turn:session-dev:1:bound"


def test_turn_run_monitor_detail_is_available_for_active_turn_placeholder():
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(
            task_runs=[],
            turn_runs=[turn_run(turn_run_id="turnrun:session-dev:1", session_id="session-dev", turn_id="turn:session-dev:1")],
        ),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        run_registry=RunRegistryStub([runtime_run(session_id="session-dev")]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:1",
                turn_run_id="turnrun:session-dev:1",
                bound_task_run_id="",
                stream_run_id="strun:test",
                state="model_turn",
                started_at=100.0,
                updated_at=126.0,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    detail = service.get_task_run_live_monitor("turnrun:session-dev:1")

    assert detail is not None
    assert detail["task_run_id"] == "turnrun:session-dev:1"
    assert detail["scope"] == "task_run"
    assert detail["status"] == "running"


def test_global_monitor_excludes_terminal_history_from_live_items():
    projector = RuntimeMonitorProjector(EventLogStub())
    monitor = projector.build_global_monitor(
        [
            task_run(
                task_run_id="taskrun:completed",
                status="completed",
                terminal_reason="completed",
                updated_at=140.0,
            ),
            task_run(
                task_run_id="taskrun:failed",
                status="failed",
                terminal_reason="executor_failed",
                updated_at=150.0,
            ),
        ],
        now=160.0,
        limit=20,
    )

    assert monitor["task_runs"] == []
    assert monitor["buckets"]["completed"] == []
    assert monitor["buckets"]["failed"] == []
    assert monitor["summary"]["total"] == 0


def test_running_monitor_items_are_dynamic_and_tick_with_now():
    projector = RuntimeMonitorProjector(EventLogStub())

    first = projector.project_task_run(task_run(), now=130.0)
    second = projector.project_task_run(task_run(), now=150.0)

    assert first["bucket"] == "running"
    assert first["resource_class"] == "dynamic"
    assert first["ended_at"] is None
    assert first["duration_seconds"] == 30.0
    assert second["duration_seconds"] == 50.0


def test_terminal_monitor_items_are_static_and_duration_is_frozen():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(status="completed", updated_at=135.0)

    first = projector.project_task_run(run, now=150.0)
    second = projector.project_task_run(run, now=300.0)

    assert first["bucket"] == "completed"
    assert first["resource_class"] == "static"
    assert first["ended_at"] == 135.0
    assert first["duration_seconds"] == 35.0
    assert second["duration_seconds"] == 35.0


def test_stale_waiting_executor_moves_to_diagnostics_not_running():
    projector = RuntimeMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(status="waiting_executor", updated_at=120.0)

    item = projector.project_task_run(run, now=300.0)

    assert item["bucket"] == "diagnostics"
    assert item["lifecycle"] == "stale"
    assert item["resource_class"] == "static"
    assert item["stale"] is True


def test_fresh_waiting_executor_uses_waiting_bucket_not_running():
    projector = RuntimeMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(status="waiting_executor", updated_at=120.0)

    item = projector.project_task_run(run, now=140.0)
    monitor = projector.build_global_monitor([run], now=140.0, limit=20)

    assert item["bucket"] == "waiting"
    assert item["lifecycle"] == "waiting"
    assert item["resource_class"] == "static"
    assert monitor["summary"]["running"] == 0
    assert monitor["summary"]["waiting"] == 1


def test_user_paused_waiting_executor_is_actionable_not_stale():
    projector = RuntimeMonitorProjector(EventLogStub(), freshness_seconds=60.0)
    run = task_run(
        status="waiting_executor",
        updated_at=120.0,
        diagnostics={
            "runtime_control": {
                "state": "paused",
                "requested_by": "user",
                "requested_at": 121.0,
                "reason": "用户暂停",
            }
        },
    )

    item = projector.project_task_run(run, now=300.0)

    assert item["bucket"] == "diagnostics"
    assert item["lifecycle"] == "paused"
    assert item["resource_class"] == "static"
    assert item["stale"] is False
    assert item["action_required"] is True
    assert item["runtime_control"]["state"] == "paused"


def test_waiting_approval_moves_to_diagnostics_and_freezes_duration():
    projector = RuntimeMonitorProjector(EventLogStub(), freshness_seconds=60.0)
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
    projector = RuntimeMonitorProjector(EventLogStub(), freshness_seconds=60.0)
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
    projector = RuntimeMonitorProjector(EventLogStub())
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
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}))

    item = projector.project_task_run(task_run(), now=150.0)

    assert item["latest_step_summary"] == "已读取文件。"
    assert item["latest_step_name"] == "tool_result"


def test_latest_public_action_state_is_exposed_and_kept_separate_from_wait_heartbeat():
    events = [
        EventStub(
            event_type="step_summary_recorded",
            created_at=125.0,
            offset=1,
            payload={
                "step": "model_action_received:3",
                "status": "running",
                "summary": "我已确认产物存在，下一步做最终验收。",
                "public_progress_note": "已确认产物存在，下一步做最终验收。",
                "observation": "HTML 产物文件存在。",
                "public_action_state": {
                    "current_judgment": "主要交付物已满足合同。",
                    "next_action": "执行最终验收并给出 artifact 路径。",
                    "completion_status": "verifying",
                },
            },
        ),
        EventStub(
            event_type="task_model_action_wait_heartbeat",
            created_at=140.0,
            offset=2,
            payload={"step": "task_model_action_waiting:4", "status": "running", "wait_round": 1},
        ),
    ]
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": events}))

    item = projector.project_task_run(task_run(updated_at=140.0), now=150.0)

    assert item["latest_step_summary"] == "已确认产物存在，下一步做最终验收。"
    assert item["latest_progress"]["observation"] == "HTML 产物文件存在。"
    assert item["latest_progress"]["current_judgment"] == "主要交付物已满足合同。"
    assert item["latest_progress"]["next_action"] == "执行最终验收并给出 artifact 路径。"
    assert item["latest_progress"]["completion_status"] == "verifying"


def test_stale_model_wait_reports_diagnostic_cause_not_generic_waiting():
    event = EventStub(
        event_type="step_summary_recorded",
        created_at=125.0,
        payload={"step": "model_action_waiting:1", "status": "running", "summary": "正在思考。"},
    )
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}), freshness_seconds=60.0)

    item = projector.project_task_run(task_run(updated_at=125.0), now=300.0)

    assert item["bucket"] == "diagnostics"
    assert "stale_runtime_activity" in item["diagnostic_reasons"]
    assert "模型响应已超过" in item["latest_step_summary"]
    assert "诊断状态" in item["latest_public_progress_note"]
    assert item["latest_progress"]["current_judgment"] == ""


def test_active_task_steer_and_executor_sequence_diagnostics_are_exposed():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(
        diagnostics={
            "pending_user_steer_count": 2,
            "latest_user_steer_ref": "steer:taskrun:latest",
            "active_contract_revision_count": 1,
            "latest_contract_revision_ref": "taskrev:taskrun:latest",
            "executor_epoch": 3,
            "next_invocation_index": 9,
        }
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["pending_user_steer_count"] == 2
    assert item["latest_user_steer_ref"] == "steer:taskrun:latest"
    assert item["active_contract_revision_count"] == 1
    assert item["latest_contract_revision_ref"] == "taskrev:taskrun:latest"
    assert item["executor_epoch"] == 3
    assert item["next_invocation_index"] == 9


def test_missing_time_fields_enter_diagnostics():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(created_at=0.0, updated_at=0.0)

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "missing_runtime_time" in item["diagnostic_reasons"]


def test_task_graph_route_without_graph_id_enters_diagnostics():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(
        task_run_id="taskrun:graph",
        diagnostics={"graph_run_id": "grun:graph", "graph_harness_config_id": "ghcfg:graph"},
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "missing_route_graph_id" in item["diagnostic_reasons"]


def test_unknown_status_enters_diagnostics():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(status="repairing")

    item = projector.project_task_run(run, now=150.0)

    assert item["bucket"] == "diagnostics"
    assert "unknown_task_status" in item["diagnostic_reasons"]


def test_global_monitor_filters_child_runs_and_applies_per_bucket_limit():
    projector = RuntimeMonitorProjector(EventLogStub())
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
    assert "taskrun:child" not in {item["task_run_id"] for item in monitor["task_runs"]}
    assert "taskrun:completed-1" not in {item["task_run_id"] for item in monitor["task_runs"]}
    assert "taskrun:completed-2" not in {item["task_run_id"] for item in monitor["task_runs"]}


def test_global_monitor_keeps_one_current_task_per_session():
    projector = RuntimeMonitorProjector(EventLogStub())
    stale_blocked = task_run(
        task_run_id="taskrun:turn:session-a:1:old",
        session_id="session-a",
        status="blocked",
        updated_at=220.0,
        diagnostics={"latest_step_summary": "旧任务阻塞记录。"},
    )
    current_running = task_run(
        task_run_id="taskrun:turn:session-a:2:current",
        session_id="session-a",
        status="running",
        updated_at=210.0,
        diagnostics={"latest_step_summary": "当前续跑任务。"},
    )
    other_session = task_run(
        task_run_id="taskrun:turn:session-b:1:current",
        session_id="session-b",
        status="waiting_executor",
        updated_at=205.0,
    )

    monitor = projector.build_global_monitor([stale_blocked, current_running, other_session], now=230.0, limit=20)
    visible_ids = {item["task_run_id"] for item in monitor["task_runs"]}

    assert "taskrun:turn:session-a:2:current" in visible_ids
    assert "taskrun:turn:session-a:1:old" not in visible_ids
    assert "taskrun:turn:session-b:1:current" in visible_ids


def test_global_monitor_keeps_one_current_graph_task_per_project_scope():
    projector = RuntimeMonitorProjector(EventLogStub())
    stale_graph_run = task_run(
        task_run_id="taskrun:graph:old",
        session_id="session-old",
        task_id="task.writing.modular_novel.master",
        execution_runtime_kind="",
        status="running",
        created_at=100.0,
        updated_at=120.0,
        diagnostics={
            "graph_id": "graph.writing.modular_novel.master",
            "graph_run_id": "grun:old",
            "graph_harness_config_id": "ghcfg:old",
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "project.creation.writing.honghuang",
            "session_scope": {
                "workspace_view": "task_environment",
                "task_environment_id": "env.creation.writing",
                "project_id": "project.creation.writing.honghuang",
            },
        },
    )
    current_graph_run = task_run(
        task_run_id="taskrun:graph:current",
        session_id="session-new",
        task_id="contract.writing.modular_novel.graph",
        execution_runtime_kind="",
        status="running",
        created_at=180.0,
        updated_at=220.0,
        diagnostics={
            "graph_id": "graph.writing.modular_novel.master",
            "graph_run_id": "grun:current",
            "graph_harness_config_id": "ghcfg:current",
            "workspace_view": "task_environment",
            "task_environment_id": "env.creation.writing",
            "project_id": "project.creation.writing.honghuang",
            "session_scope": {
                "workspace_view": "task_environment",
                "task_environment_id": "env.creation.writing",
                "project_id": "project.creation.writing.honghuang",
            },
        },
    )

    monitor = projector.build_global_monitor([stale_graph_run, current_graph_run], now=230.0, limit=20)
    visible_ids = {item["task_run_id"] for item in monitor["task_runs"]}

    assert "taskrun:graph:current" in visible_ids
    assert "taskrun:graph:old" not in visible_ids


def test_main_chat_taskinst_task_run_remains_monitorable():
    projector = RuntimeMonitorProjector(EventLogStub())
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
    assert item["route"]["kind"] == "agent_runtime_run"
    assert item["session_id"] == "session-a"
    assert item["navigation_target"] == {
        "target_kind": "session",
        "workspace_view": "chat",
        "session_id": "session-a",
        "task_instance_id": run.task_run_id,
        "task_run_id": run.task_run_id,
        "graph_run_id": "",
        "graph_id": "",
        "mode": "conversation",
        "focus_node_id": "",
    }


def test_monitor_navigation_uses_owning_task_environment_session_scope():
    projector = RuntimeMonitorProjector(
        EventLogStub(),
        session_scope_resolver=lambda session_id: {
            "workspace_view": "task_environment",
            "task_environment_id": "env.development.sandbox",
            "project_id": "",
        } if session_id == "session-dev" else None,
    )
    run = task_run(
        task_run_id="taskrun:turn:session-dev:1:abc",
        session_id="session-dev",
        task_id="task.dev.calculator",
        execution_runtime_kind="single_agent_task",
        diagnostics={},
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["title"] == "task.dev.calculator"
    assert item["session_scope"] == {
        "workspace_view": "task_environment",
        "task_environment_id": "env.development.sandbox",
        "project_id": "",
    }
    assert item["navigation_target"] == {
        "target_kind": "session",
        "workspace_view": "task_environment",
        "task_environment_id": "env.development.sandbox",
        "session_id": "session-dev",
        "task_instance_id": run.task_run_id,
        "task_run_id": run.task_run_id,
        "graph_run_id": "",
        "graph_id": "",
        "mode": "conversation",
        "focus_node_id": "",
    }


class ResourceResolverStub:
    def __init__(self, graph_monitor=None):
        self.graph_monitor_payload = graph_monitor
        self.graph_monitor_calls = []

    def task_run_ref(self, task_run_id, *, label="任务运行"):
        return {"ref": f"task_run:{task_run_id}", "kind": "task_run", "id": task_run_id, "label": label, "availability": {"state": "available"}}

    def session_ref(self, session_id, *, label="会话"):
        return {"ref": f"session:{session_id}", "kind": "session", "id": session_id, "label": label, "availability": {"state": "available"}}

    def graph_run_ref(self, graph_run_id, *, label="任务图运行"):
        return {"ref": f"graph_run:{graph_run_id}", "kind": "graph_run", "id": graph_run_id, "label": label, "availability": {"state": "available"}}

    def graph_config_ref(self, graph_harness_config_id, *, label="任务图配置"):
        state = "available" if graph_harness_config_id == "ghcfg:existing" else "missing"
        return {"ref": f"graph_harness_config:{graph_harness_config_id}", "kind": "graph_harness_config", "id": graph_harness_config_id, "label": label, "availability": {"state": state}}

    def artifact_refs(self, refs):
        return []

    def graph_monitor(self, graph_run_id, graph_harness_config_id="", *, event_limit=80):
        self.graph_monitor_calls.append((graph_run_id, graph_harness_config_id, event_limit))
        return self.graph_monitor_payload


def test_global_monitor_uses_summary_projection_without_event_or_child_detail_fetch():
    event_log = EventLogStub({
        "taskrun:graph-root": [
            EventStub(
                event_type="step_summary_recorded",
                created_at=125.0,
                payload={"step": "tool_result", "status": "completed", "summary": "事件日志摘要不应被全局列表读取。"},
            )
        ]
    })
    resolver = ResourceResolverStub({
        "graph_loop_state": {"status": "running", "ready_node_ids": [], "node_states": {"draft": {"status": "running"}}},
        "node_runtime_views": [{"node_id": "draft", "status": "running", "node_executor_task_run_id": "gtask:draft"}],
    })
    projector = RuntimeMonitorProjector(event_log, resource_resolver=resolver)
    run = task_run(
        task_run_id="taskrun:graph-root",
        diagnostics={
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:existing",
            "latest_step_summary": "静态任务摘要",
        },
    )

    monitor = projector.build_global_monitor([run], now=150.0, limit=20)
    item = monitor["task_runs"][0]

    assert item["latest_step_summary"] == "静态任务摘要"
    assert item["child_runtime_refs"] == []
    assert item["graph_status"]["active_node_id"] == ""
    assert event_log.list_recent_event_calls == []
    assert event_log.event_count_calls == []
    assert resolver.graph_monitor_calls == []


def test_global_graph_monitor_uses_active_graph_loop_to_avoid_false_stale_diagnostic():
    graph_monitor = {
        "graph_loop_state": {"status": "running", "ready_node_ids": [], "node_states": {"world_design": {"status": "running"}}},
        "active_node_work_orders": [{"node_id": "world_design"}],
        "node_runtime_views": [{"node_id": "world_design", "status": "running"}],
    }
    projector = RuntimeMonitorProjector(EventLogStub(), resource_resolver=ResourceResolverStub(graph_monitor), freshness_seconds=60.0)
    run = task_run(
        task_run_id="taskrun:graph-root",
        execution_runtime_kind="",
        status="running",
        updated_at=100.0,
        diagnostics={
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:existing",
        },
    )

    monitor = projector.build_global_monitor([run], now=300.0, limit=20)
    item = monitor["task_runs"][0]

    assert item["bucket"] == "running"
    assert item["lifecycle"] == "running"
    assert item["stale"] is False
    assert item["graph_status"]["active_node_id"] == ""
    assert projector.resource_resolver.graph_monitor_calls == []


def test_task_graph_monitor_item_uses_graph_run_as_task_instance_and_navigation_target():
    graph_monitor = {
        "graph_harness_config": {
            "graph_id": "graph:main",
            "graph_title": "主图任务",
            "nodes": [{"node_id": "draft", "title": "草稿"}],
        },
        "graph_loop_state": {"status": "running", "ready_node_ids": [], "node_states": {"draft": {"status": "running"}}},
        "node_runtime_views": [
            {
                "node_id": "draft",
                "status": "running",
                "node_executor_task_run_id": "gtask:draft",
                "node_executor_task_run_monitor": {"lifecycle": "running", "latest_progress": {"summary": "正在写草稿"}},
            }
        ],
    }
    projector = RuntimeMonitorProjector(EventLogStub(), resource_resolver=ResourceResolverStub(graph_monitor))
    run = task_run(
        task_run_id="taskrun:graph-root",
        diagnostics={
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:existing",
        },
    )

    item = projector.project_task_run(run, now=150.0)

    assert item["kind"] == "task_graph"
    assert item["task_instance_id"] == "grun:main"
    assert item["root_task_run_id"] == "taskrun:graph-root"
    assert item["navigation_target"]["target_kind"] == "graph_task"
    assert item["navigation_target"]["task_instance_id"] == "grun:main"
    assert item["graph_status"]["active_node_id"] == "draft"
    assert item["child_runtime_refs"] == [
        {
            "task_run_id": "gtask:draft",
            "node_id": "draft",
            "node_label": "draft",
            "runtime_kind": "agent_runtime",
            "lifecycle": "running",
            "latest_progress": {"summary": "正在写草稿"},
            "artifact_refs": [],
        }
    ]


def test_missing_graph_config_is_resource_availability_not_frontend_404_control_flow():
    projector = RuntimeMonitorProjector(EventLogStub(), resource_resolver=ResourceResolverStub())
    run = task_run(
        task_run_id="taskrun:graph-root",
        diagnostics={
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:missing",
        },
    )

    item = projector.project_task_run(run, now=150.0)

    graph_config_ref = next(ref for ref in item["resource_refs"] if ref["kind"] == "graph_harness_config")
    assert graph_config_ref["availability"]["state"] == "missing"
