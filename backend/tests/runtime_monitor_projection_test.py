import asyncio
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
        self.deleted_task_run_ids = []
        self.session_summary_limits = []

    def list_recent_task_runs(self, *, limit=80):
        return list(self._task_runs)[: max(1, int(limit or 80))]

    def list_recent_task_run_summaries(self, *, limit=80):
        return list(self._task_runs)[: max(1, int(limit or 80))]

    def list_session_task_runs(self, session_id):
        return [item for item in self._task_runs if getattr(item, "session_id", "") == session_id]

    def list_session_task_run_summaries(self, session_id, *, limit=None):
        self.session_summary_limits.append(limit)
        items = [item for item in self._task_runs if getattr(item, "session_id", "") == session_id]
        if limit is None:
            return items
        return sorted(
            items,
            key=lambda item: float(getattr(item, "updated_at", 0.0) or getattr(item, "created_at", 0.0) or 0.0),
            reverse=True,
        )[: max(1, int(limit or 1))]

    def get_task_run(self, task_run_id):
        for item in self._task_runs:
            if getattr(item, "task_run_id", "") == task_run_id:
                return item
        return None

    def get_turn_run(self, turn_run_id):
        return self._turn_runs.get(turn_run_id)

    def mark_task_run_deleted(self, task_run_id):
        normalized = str(task_run_id or "").strip()
        if normalized:
            self.deleted_task_run_ids.append(normalized)
        return {
            "authority": "orchestration.runtime_state_index.task_run_deletion_tombstone",
            "task_run_id": normalized,
            "recorded": bool(normalized),
        }


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


class GraphHarnessStub:
    def __init__(self):
        self.monitor_calls = []

    def get_graph_run_monitor(self, graph_run_id, **kwargs):
        self.monitor_calls.append((graph_run_id, dict(kwargs)))
        return {
            "graph_loop_state": {
                "status": "running",
                "node_states": {"draft": {"status": "running"}},
            },
            "active_node_work_orders": [{"node_id": "draft"}],
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


def test_session_task_summary_does_not_fetch_graph_runtime_detail():
    graph_run = task_run(
        task_run_id="taskrun:graph-root",
        session_id="session-graph",
        task_id="task.graph.root",
        status="running",
        diagnostics={
            "graph_id": "graph:main",
            "graph_run_id": "grun:main",
            "graph_harness_config_id": "ghcfg:existing",
            "title": "长篇小说图任务",
        },
    )
    graph_harness = GraphHarnessStub()
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([graph_run]),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
    )
    service = RuntimeMonitorService(
        runtime_host=runtime_host,
        graph_harness=graph_harness,
        freshness_seconds=300.0,
    )

    summary = service.get_session_task_summary("session-graph")

    assert summary["available"] is True
    assert summary["kind"] == "task_graph"
    assert summary["task_run_id"] == "taskrun:graph-root"
    assert summary["graph_run_id"] == "grun:main"
    assert summary["title"] == "长篇小说图任务"
    assert graph_harness.monitor_calls == []


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


def test_session_live_monitor_reads_bounded_recent_task_summaries():
    tasks = [
        task_run(
            task_run_id=f"taskrun:turn:session-heavy:{index}:root",
            session_id="session-heavy",
            task_id=f"task:turn:session-heavy:{index}",
            status="completed" if index < 119 else "running",
            updated_at=100.0 + index,
        )
        for index in range(120)
    ]
    state_index = StateIndexStub(tasks)
    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
        active_turn_registry=ActiveTurnRegistryStub(None),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.get_session_live_monitor("session-heavy", limit=10)

    assert state_index.session_summary_limits == [40]
    assert monitor["latest_task_run_id"] == "taskrun:turn:session-heavy:119:root"
    assert monitor["task_run_count"] == 40


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


def test_run_monitor_active_turn_replaces_stale_task_from_same_session(tmp_path):
    now = time.time()
    stale_task = task_run(
        task_run_id="taskrun:turn:session-dev:1:old",
        session_id="session-dev",
        task_id="task:turn:session-dev:1",
        status="running",
        created_at=now - 600,
        updated_at=now - 600,
        diagnostics={"latest_step_summary": "旧任务停滞记录。"},
    )
    current_turn = turn_run(
        turn_run_id="turnrun:session-dev:2",
        session_id="session-dev",
        turn_id="turn:session-dev:2",
        created_at=now - 2,
        updated_at=now - 1,
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub(
            task_runs=[stale_task],
            turn_runs=[current_turn],
        ),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
        run_registry=RunRegistryStub([
            runtime_run(
                session_id="session-dev",
                status="running",
                created_at=now - 2,
                updated_at=now - 1,
            )
        ]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-dev",
                turn_id="turn:session-dev:2",
                turn_run_id="turnrun:session-dev:2",
                bound_task_run_id="",
                stream_run_id="strun:session-dev:2",
                state="model_turn",
                started_at=now - 2,
                updated_at=now - 1,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=60.0)

    monitor = service.collect_global_runtime_monitor(limit=20)
    signal_ids = {item["signal_id"] for item in monitor["signals"]}
    lane_ids = {
        item["signal_id"]
        for lane in dict(monitor["management"]["lanes"]).values()
        for item in lane
    }

    assert "turnrun:session-dev:2" in signal_ids
    assert "taskrun:turn:session-dev:1:old" not in signal_ids
    assert "taskrun:turn:session-dev:1:old" not in lane_ids
    assert monitor["summary"]["active"] == 1
    assert monitor["summary"]["attention"] == 0
    assert monitor["management"]["lanes"]["current"][0]["signal_id"] == "turnrun:session-dev:2"


def test_run_monitor_global_collection_uses_state_index_summaries():
    now = time.time()

    class SummaryOnlyStateIndex:
        def list_recent_task_run_summaries(self, *, limit=80):
            return [
                task_run(
                    task_run_id="taskrun:summary",
                    session_id="session-summary",
                    task_id="task.summary",
                    status="running",
                    created_at=now - 5,
                    updated_at=now,
                    diagnostics={"latest_step_summary": "轻量摘要"},
                )
            ][:limit]

        def list_recent_task_runs(self, *, limit=80):
            raise AssertionError("global monitor must read task run summaries, not full task runs")

    runtime_host = SimpleNamespace(
        state_index=SummaryOnlyStateIndex(),
        event_log=EventLogStub(),
        backend_dir=Path.cwd(),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["signals"][0]["signal_id"] == "taskrun:summary"
    assert monitor["signals"][0]["line"] == "运行中"


def test_run_monitor_waiting_state_wins_over_running_bucket_residue():
    monitor = build_runtime_monitor_envelope(
        items=[
            {
                "task_run_id": "taskrun:waiting",
                "status": "waiting_executor",
                "lifecycle": "paused",
                "bucket": "running",
                "action_required": True,
                "is_live": True,
                "title": "等待中的任务",
                "updated_at": 150.0,
                "last_activity_at": 150.0,
                "started_at": 100.0,
            },
        ],
        now=180.0,
        limit=10,
    )

    assert monitor["summary"]["active"] == 0
    assert monitor["summary"]["waiting"] == 1
    assert monitor["primary"] == []
    assert monitor["attention"][0]["state"] == "waiting"
    assert monitor["attention"][0]["activity_state"] in {"waiting", "paused"}
    assert monitor["attention"][0]["is_resumable"] is False


def test_user_aborted_projects_as_stopped_not_failed():
    monitor = build_runtime_monitor_envelope(
        items=[
            {
                "task_run_id": "taskrun:stopped",
                "status": "aborted",
                "terminal_reason": "user_aborted",
                "lifecycle": "failed",
                "bucket": "running",
                "is_live": True,
                "title": "用户停止的任务",
                "updated_at": 150.0,
                "last_activity_at": 150.0,
                "started_at": 100.0,
            },
        ],
        now=180.0,
        limit=10,
    )

    assert monitor["summary"]["active"] == 0
    assert monitor["summary"]["failed"] == 0
    assert monitor["summary"]["recent"] == 1
    assert monitor["recent"][0]["activity_state"] == "stopped"
    assert monitor["recent"][0]["terminal_reason"] == "user_aborted"
    assert monitor["recent"][0]["tone"] == "neutral"


def test_runtime_monitor_actions_use_activity_control_capability(tmp_path):
    now = time.time()
    waiting = task_run(
        task_run_id="taskrun:waiting",
        session_id="session-waiting",
        status="waiting_executor",
        created_at=now - 5,
        updated_at=now - 1,
    )
    paused = task_run(
        task_run_id="taskrun:paused",
        session_id="session-paused",
        status="running",
        created_at=now - 5,
        updated_at=now - 1,
        diagnostics={"runtime_control": {"state": "paused"}},
    )
    running = task_run(
        task_run_id="taskrun:running",
        session_id="session-running",
        status="running",
        created_at=now - 5,
        updated_at=now - 1,
        diagnostics={"executor_status": "running"},
    )
    stopped = task_run(
        task_run_id="taskrun:stopped",
        session_id="session-stopped",
        status="aborted",
        terminal_reason="user_aborted",
        created_at=now - 5,
        updated_at=now - 1,
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([waiting, paused, running, stopped]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)
    signals = {item["signal_id"]: item for item in monitor["signals"]}

    waiting_signal = signals["taskrun:waiting"]
    waiting_actions = {item["action"]: item for item in waiting_signal["actions"]}
    assert waiting_signal["activity_state"] == "waiting"
    assert waiting_signal["is_resumable"] is False
    assert "resume_task" not in waiting_actions
    assert waiting_actions["pause_task"]["enabled"] is False
    assert waiting_actions["stop_task"]["enabled"] is True
    assert waiting_actions["close_runtime"]["enabled"] is False

    paused_signal = signals["taskrun:paused"]
    paused_actions = {item["action"]: item for item in paused_signal["actions"]}
    assert paused_signal["activity_state"] == "paused"
    assert paused_signal["is_resumable"] is True
    assert "resume_task" not in paused_actions
    assert paused_actions["pause_task"]["enabled"] is False
    assert paused_actions["stop_task"]["enabled"] is True
    assert paused_actions["close_runtime"]["enabled"] is False

    running_signal = signals["taskrun:running"]
    running_actions = {item["action"]: item for item in running_signal["actions"]}
    assert running_signal["is_running"] is True
    assert running_actions["pause_task"]["enabled"] is True
    assert running_actions["stop_task"]["enabled"] is True
    assert "resume_task" not in running_actions
    assert running_actions["close_runtime"]["enabled"] is False

    stopped_signal = signals["taskrun:stopped"]
    stopped_actions = {item["action"]: item for item in stopped_signal["actions"]}
    assert stopped_signal["activity_state"] == "stopped"
    assert "resume_task" not in stopped_actions
    assert stopped_actions["stop_task"]["enabled"] is False


def test_runtime_monitor_summary_counts_only_running_graph_tasks(tmp_path):
    now = time.time()
    running_graph = task_run(
        task_run_id="taskrun:graph-running",
        session_id="session-graph-running",
        status="running",
        created_at=now - 10,
        updated_at=now - 1,
        diagnostics={
            "graph_id": "graph.demo",
            "graph_run_id": "grun:running",
            "graph_harness_config_id": "ghcfg:running",
            "workspace_view": "task_environment",
            "task_environment_id": "env.demo",
            "project_id": "project.demo.running",
        },
    )
    waiting_graph = task_run(
        task_run_id="taskrun:graph-waiting",
        session_id="session-graph-waiting",
        status="waiting_executor",
        created_at=now - 10,
        updated_at=now - 1,
        diagnostics={
            "graph_id": "graph.demo",
            "graph_run_id": "grun:waiting",
            "graph_harness_config_id": "ghcfg:waiting",
            "workspace_view": "task_environment",
            "task_environment_id": "env.demo",
            "project_id": "project.demo.waiting",
        },
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([running_graph, waiting_graph]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert [item["signal_id"] for item in monitor["projects"]] == ["grun:running"]
    assert [item["visibility"]["lane"] for item in monitor["projects"]] == ["projects"]
    assert monitor["summary"]["projects"] == 1
    assert monitor["summary"]["active"] == 1
    assert monitor["summary"]["waiting"] == 0


def test_run_monitor_projects_waiting_active_turn_as_waiting_signal():
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
                state="waiting_executor",
                started_at=100.0,
                updated_at=126.0,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["summary"]["active"] == 0
    assert monitor["summary"]["waiting"] == 1
    assert monitor["primary"] == []
    assert monitor["management"]["lanes"]["attention"][0]["signal_id"] == "turnrun:session-dev:1"
    assert monitor["management"]["lanes"]["attention"][0]["state"] == "waiting"


def test_runtime_monitor_dedupes_waiting_bound_active_turn_against_task_run(tmp_path):
    now = time.time()
    bound_task = task_run(
        task_run_id="taskrun:bound-wait",
        session_id="session-wait",
        status="waiting_executor",
        created_at=now - 10,
        updated_at=now - 1,
    )
    bound_turn = turn_run(
        turn_run_id="turnrun:wait:1",
        session_id="session-wait",
        turn_id="turn:wait:1",
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([bound_task], [bound_turn]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
        run_registry=RunRegistryStub([runtime_run(session_id="session-wait", status="running")]),
        active_turn_registry=ActiveTurnRegistryStub(
            ActiveTurnRecordStub(
                session_id="session-wait",
                turn_id="turn:wait:1",
                turn_run_id="turnrun:wait:1",
                bound_task_run_id="taskrun:bound-wait",
                stream_run_id="strun:wait",
                state="waiting_executor",
                started_at=now - 10,
                updated_at=now - 1,
            )
        ),
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["summary"]["total"] == 1
    assert monitor["summary"]["waiting"] == 1
    assert monitor["signals"][0]["signal_id"] == "taskrun:bound-wait"
    assert monitor["signals"][0]["activity_state"] == "waiting"


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


def test_runtime_monitor_management_omits_terminal_graph_records(tmp_path):
    completed_graph = task_run(
        task_run_id="taskrun:graph-completed",
        task_id="task.graph.done",
        execution_runtime_kind="",
        status="completed",
        terminal_reason="completed",
        updated_at=140.0,
        diagnostics={
            "graph_id": "graph.done",
            "graph_run_id": "grun:completed",
            "graph_harness_config_id": "ghcfg:completed",
            "workspace_view": "task_environment",
            "task_environment_id": "env.demo",
            "project_id": "project.demo",
        },
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([completed_graph]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    live_monitor = service.list_global_live_monitor(limit=20)
    monitor = service.collect_global_runtime_monitor(limit=20)

    assert live_monitor["task_runs"] == []
    assert monitor["signals"] == []
    assert monitor["summary"]["projects"] == 0
    assert monitor["summary"]["recent"] == 0
    assert monitor["management"]["lanes"]["projects"] == []
    assert monitor["management"]["lanes"]["recent"] == []


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


def test_runtime_monitor_action_uses_current_signal_authority_with_stale_source_revision(tmp_path):
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

    result = asyncio.run(
        action_service.execute(
            {
                "action": "clear_from_monitor",
                "signal_id": "taskrun:completed",
                "source_revision": "rtmon:1:stale",
            }
        )
    )

    assert result["accepted"] is True
    assert result["effects"]["hidden"]["signal_id"] == "taskrun:completed"
    assert result["monitor"]["management"]["lanes"]["hidden"][0]["signal_id"] == "taskrun:completed"
    assert runtime_host.state_index.get_task_run("taskrun:completed") is completed


def test_runtime_monitor_management_projects_stale_waiting_executor_as_closeable(tmp_path):
    now = time.time()
    stale_waiting = task_run(
        task_run_id="taskrun:stale-waiting",
        session_id="session-stale-waiting",
        status="waiting_executor",
        created_at=now - 900,
        updated_at=now - 700,
        diagnostics={"title": "停滞等待任务"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([stale_waiting]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=60.0)

    monitor = service.collect_global_runtime_monitor(limit=20)
    signal = monitor["signals"][0]
    actions = {item["action"]: item for item in signal["actions"]}

    assert signal["state"] == "stale"
    assert signal["activity_state"] == "stale"
    assert signal["activity_label"] == "等待检查"
    assert monitor["summary"]["waiting"] == 0
    assert actions["clear_from_monitor"]["enabled"] is True
    assert actions["pause_task"]["enabled"] is False
    assert "resume_task" not in actions
    assert actions["close_runtime"]["enabled"] is True
    assert actions["stop_task"]["enabled"] is False


def test_runtime_monitor_management_projects_stale_running_as_closeable_not_pausable(tmp_path):
    now = time.time()
    stale_running = task_run(
        task_run_id="taskrun:stale-running",
        session_id="session-stale-running",
        status="running",
        created_at=now - 900,
        updated_at=now - 700,
        diagnostics={"title": "停滞运行任务", "executor_status": "running"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([stale_running]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=60.0)

    monitor = service.collect_global_runtime_monitor(limit=20)
    signal = monitor["signals"][0]
    actions = {item["action"]: item for item in signal["actions"]}

    assert signal["state"] == "stale"
    assert signal["activity_state"] == "stale"
    assert signal["is_running"] is False
    assert monitor["summary"]["active"] == 0
    assert actions["pause_task"]["enabled"] is False
    assert "resume_task" not in actions
    assert actions["stop_task"]["enabled"] is False
    assert actions["close_runtime"]["enabled"] is True


def test_runtime_monitor_management_omits_stale_graph_from_monitor(tmp_path):
    now = time.time()
    stale_graph = task_run(
        task_run_id="taskrun:stale-graph",
        session_id="session-stale-graph",
        task_id="task.graph.writing",
        execution_runtime_kind="",
        status="running",
        created_at=now - 900,
        updated_at=now - 700,
        diagnostics={
            "graph_id": "graph.writing",
            "graph_run_id": "grun:stale-graph",
            "graph_harness_config_id": "ghcfg:stale-graph",
            "workspace_view": "task_environment",
            "task_environment_id": "env.office.file_search",
            "project_id": "project.creation.writing",
        },
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([stale_graph]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=60.0)

    monitor = service.collect_global_runtime_monitor(limit=20)

    assert monitor["signals"] == []
    assert monitor["summary"]["active"] == 0
    assert monitor["summary"]["projects"] == 0
    assert monitor["management"]["lanes"]["projects"] == []


def test_runtime_monitor_close_runtime_stops_and_hides_signal(tmp_path, monkeypatch):
    now = time.time()
    stale_waiting = task_run(
        task_run_id="taskrun:stale-close",
        session_id="session-stale-close",
        status="waiting_executor",
        created_at=now - 900,
        updated_at=now - 700,
        diagnostics={"title": "可关闭停滞任务"},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([stale_waiting]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=60.0)
    runtime = SimpleNamespace(
        base_dir=tmp_path / "backend",
        harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host),
    )
    action_service = RuntimeMonitorActionService(runtime=runtime, monitor_service=service)
    stop_calls = []

    def fake_stop_task_run(host, task_run_id, *, reason="", requested_by="user"):
        stop_calls.append((host, task_run_id, reason, requested_by))
        return {"ok": True, "accepted": True, "task_run_id": task_run_id, "reason": reason}

    monkeypatch.setattr("harness.loop.task_executor.stop_task_run", fake_stop_task_run)

    result = asyncio.run(
        action_service.execute(
            {
                "action": "close_runtime",
                "signal_id": "taskrun:stale-close",
                "source_revision": "rtmon:1:stale",
            }
        )
    )

    assert result["accepted"] is True
    assert result["effects"]["stop"]["accepted"] is True
    assert stop_calls == [(runtime_host, "taskrun:stale-close", "runtime_monitor_close_runtime", "user")]
    hidden = result["monitor"]["management"]["lanes"]["hidden"]
    assert [item["signal_id"] for item in hidden] == ["taskrun:stale-close"]


def test_runtime_monitor_resume_action_is_not_a_backend_control_path(tmp_path, monkeypatch):
    paused = task_run(
        task_run_id="taskrun:paused-resume",
        session_id="session-paused-resume",
        status="waiting_executor",
        created_at=120.0,
        updated_at=150.0,
        diagnostics={"runtime_control": {"state": "paused"}},
    )
    runtime_host = SimpleNamespace(
        state_index=StateIndexStub([paused]),
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)

    class HarnessRuntimeStub:
        single_agent_runtime_host = runtime_host

        def schedule_task_run_executor(self, task_run_id, *, scheduler="", max_steps=12):
            return {
                "ok": True,
                "scheduled": False,
                "reason": "already_running",
                "task_run_id": task_run_id,
                "scheduler": scheduler,
                "max_steps": max_steps,
            }

    runtime = SimpleNamespace(
        base_dir=tmp_path / "backend",
        harness_runtime=HarnessRuntimeStub(),
    )
    action_service = RuntimeMonitorActionService(runtime=runtime, monitor_service=service)
    schedule_calls = []

    def fake_resume_paused_task_run(host, task_run_id, *, reason="", requested_by="user"):
        raise AssertionError("monitor resume should not call task resume")

    monkeypatch.setattr("harness.loop.task_executor.resume_paused_task_run", fake_resume_paused_task_run)
    runtime.harness_runtime.schedule_task_run_executor = lambda *args, **kwargs: schedule_calls.append((args, kwargs))

    result = asyncio.run(action_service.execute({"action": "resume_task", "signal_id": "taskrun:paused-resume"}))

    assert result["accepted"] is False
    assert result["disabled_reason"] == "action_not_available"
    assert schedule_calls == []


def test_runtime_monitor_delete_action_queues_physical_cleanup_and_hides_signal(tmp_path):
    completed = task_run(
        task_run_id="taskrun:completed",
        status="completed",
        terminal_reason="completed",
        updated_at=140.0,
        diagnostics={"title": "已完成任务"},
    )
    state_index = StateIndexStub([completed])
    spawned_names = []

    async def cancel_background_tasks(*, names, reason="", timeout_seconds=0.0):
        return {
            "authority": "single_agent_runtime_host.cancel_background_tasks",
            "requested_names": sorted(names),
            "reason": reason,
            "timeout_seconds": timeout_seconds,
        }

    def spawn_background_task(coro, *, name=""):
        spawned_names.append(name)
        coro.close()
        return SimpleNamespace(done=lambda: False)

    runtime_host = SimpleNamespace(
        state_index=state_index,
        event_log=EventLogStub(),
        backend_dir=tmp_path / "backend",
        active_turn_registry=SimpleNamespace(complete_bound_task=lambda **_kwargs: {}),
        cancel_background_tasks=cancel_background_tasks,
        spawn_background_task=spawn_background_task,
    )
    service = RuntimeMonitorService(runtime_host=runtime_host, freshness_seconds=300.0)
    runtime = SimpleNamespace(
        base_dir=tmp_path / "backend",
        harness_runtime=SimpleNamespace(single_agent_runtime_host=runtime_host),
    )
    action_service = RuntimeMonitorActionService(runtime=runtime, monitor_service=service)

    result = asyncio.run(action_service.execute({"action": "delete_record", "signal_id": "taskrun:completed"}))

    assert result["accepted"] is True
    assert result["effects"]["mode"] == "queued_cleanup"
    assert result["effects"]["cleanup_queued"] is True
    assert state_index.deleted_task_run_ids == ["taskrun:completed"]
    assert spawned_names == ["runtime-monitor-delete-record:taskrun:completed"]
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


def test_monitor_keeps_step_summary_as_monitor_state_without_public_projection_fields():
    event = EventStub(
        event_type="step_summary_recorded",
        created_at=125.0,
        payload={"step": "tool_result", "status": "completed", "summary": "已读取文件。"},
    )
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}))

    item = projector.project_task_run(task_run(), now=150.0)

    assert item["latest_step_summary"] == "已读取文件。"
    assert item["latest_progress"]["summary"] == "已读取文件。"
    assert item["latest_step_name"] == "tool_result"
    assert "public_projection_status" not in item
    assert "public_timeline" not in item
    assert "task_projection" not in item


def test_project_task_run_exposes_monitor_progress_without_backend_public_timeline():
    event = EventStub(
        event_type="step_summary_recorded",
        created_at=125.0,
        payload={
            "step": "model_action_received:1",
            "status": "running",
            "summary": "我先确认当前反馈链路，再收敛到单一页面投影。",
            "public_progress_note": "我先确认当前反馈链路，再收敛到单一页面投影。",
        },
    )
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}))

    item = projector.project_task_run(task_run(), now=150.0)

    assert item["latest_public_progress_note"] == "我先确认当前反馈链路，再收敛到单一页面投影。"
    assert item["latest_progress"]["summary"] == "我先确认当前反馈链路，再收敛到单一页面投影。"
    assert "public_timeline" not in item
    assert "task_projection" not in item


def test_system_tool_status_does_not_become_monitor_public_progress():
    event = EventStub(
        event_type="step_summary_recorded",
        created_at=125.0,
        payload={
            "step": "task_tool_batch_started:1",
            "status": "running",
            "summary": "执行 2 个工具调用：搜索文件 mario、读取文件 mario.html。",
            "presentation_source": "system.tool_call_status",
            "tool_status": "执行 2 个工具调用：搜索文件 mario、读取文件 mario.html。",
        },
    )
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": [event]}))

    item = projector.project_task_run(task_run(), now=150.0)

    assert item["latest_public_progress_note"] == ""
    assert item["latest_step_summary"] == ""
    assert item["latest_progress"]["summary"] == ""
    assert item["latest_progress"]["tool_status"] == "执行 2 个工具调用：搜索文件 mario、读取文件 mario.html。"
    assert item["latest_step"]["summary"] == "执行 2 个工具调用：搜索文件 mario、读取文件 mario.html。"
    assert item["latest_step"]["presentation_source"] == "system.tool_call_status"



def test_project_task_run_exposes_session_output_commit_ack_from_event_log():
    events = [
        EventStub(
            event_type="session_output_commit_checked",
            created_at=128.0,
            offset=8,
            payload={
                "session_id": "session-a",
                "turn_id": "turn:session-a:1",
                "task_run_id": "taskrun:turn:session-a:1:abc",
                "task_id": "task:turn:session-a:1",
                "commit_allowed": True,
                "reason": "allowed",
            },
        ),
        EventStub(
            event_type="session_output_commit_ack",
            created_at=129.0,
            offset=9,
            payload={
                "session_id": "session-a",
                "turn_id": "turn:session-a:1",
                "task_run_id": "taskrun:turn:session-a:1:abc",
                "task_id": "task:turn:session-a:1",
                "state": "committed",
                "reason": "committed",
                "anchor_message_id": "history-message:turn:session-a:1:assistant",
                "content_sha256": "sha256:final-answer",
                "checked_event_offset": 8,
            },
        ),
    ]
    projector = RuntimeMonitorProjector(EventLogStub({"taskrun:turn:session-a:1:abc": events}))

    item = projector.project_task_run(task_run(status="completed", updated_at=130.0), now=150.0)

    assert item["session_output_commit"] == {
        "authority": "runtime_monitor.session_output_commit",
        "state": "committed",
        "session_id": "session-a",
        "turn_id": "turn:session-a:1",
        "task_run_id": "taskrun:turn:session-a:1:abc",
        "task_id": "task:turn:session-a:1",
        "anchor_message_id": "history-message:turn:session-a:1:assistant",
        "content_sha256": "sha256:final-answer",
        "reason": "committed",
        "commit_event_offset": 9,
        "checked_event_offset": 8,
        "created_at": 129.0,
    }


def test_project_task_run_exposes_session_output_commit_from_diagnostics_without_detail_fetch():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(
        status="completed",
        updated_at=130.0,
        diagnostics={
            "turn_id": "turn:session-a:1",
            "output_commit": {
                "state": "committed",
                "session_id": "session-a",
                "turn_id": "turn:session-a:1",
                "task_run_id": "taskrun:turn:session-a:1:abc",
                "task_id": "task:turn:session-a:1",
                "anchor_message_id": "history-message:turn:session-a:1:assistant",
                "content_sha256": "sha256:from-diagnostics",
                "reason": "committed",
                "event_offset": 12,
            },
        },
    )

    item = projector.project_task_run(run, now=150.0, include_runtime_details=False)

    assert item["session_output_commit"]["state"] == "committed"
    assert item["session_output_commit"]["content_sha256"] == "sha256:from-diagnostics"
    assert item["session_output_commit"]["commit_event_offset"] == 12
    assert projector.event_log.list_recent_event_calls == []


def test_project_task_run_does_not_infer_session_output_commit_from_completed_final_answer():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(
        status="completed",
        updated_at=130.0,
        diagnostics={
            "turn_id": "turn:session-a:1",
            "final_answer": "This text exists on the task run, but it is not a commit receipt.",
        },
    )

    item = projector.project_task_run(run, now=150.0)

    assert "session_output_commit" not in item


def test_project_task_run_does_not_infer_session_output_commit_from_status_only():
    projector = RuntimeMonitorProjector(EventLogStub())
    run = task_run(
        status="completed",
        updated_at=130.0,
        diagnostics={
            "turn_id": "turn:session-a:1",
            "output_commit_status": "committed",
        },
    )

    item = projector.project_task_run(run, now=150.0, include_runtime_details=False)

    assert "session_output_commit" not in item


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

    assert item["latest_step_summary"] == "我已确认产物存在，下一步做最终验收。"
    assert "task_projection" not in item
    assert item["latest_progress"]["observation"] == ""
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
            "task_environment_id": "env.office.file_search",
            "project_id": "project.creation.writing.honghuang",
            "session_scope": {
                "workspace_view": "task_environment",
                "task_environment_id": "env.office.file_search",
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
            "task_environment_id": "env.office.file_search",
            "project_id": "project.creation.writing.honghuang",
            "session_scope": {
                "workspace_view": "task_environment",
                "task_environment_id": "env.office.file_search",
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
            "task_environment_id": "env.coding.vibe_workspace",
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
        "task_environment_id": "env.coding.vibe_workspace",
        "project_id": "",
    }
    assert item["navigation_target"] == {
        "target_kind": "session",
        "workspace_view": "task_environment",
        "task_environment_id": "env.coding.vibe_workspace",
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
    assert item["latest_progress"]["summary"] == "静态任务摘要"
    assert "public_projection_status" not in item
    assert "public_timeline" not in item
    assert "task_projection" not in item
    assert item["child_runtime_refs"] == []
    assert item["graph_status"]["active_node_id"] == ""
    assert event_log.list_recent_event_calls == []
    assert event_log.event_count_calls == []
    assert resolver.graph_monitor_calls == []


def test_task_monitor_detail_keeps_technical_trace_deferred_by_default():
    event_log = EventLogStub({
        "taskrun:turn:session-a:1:abc": [
            EventStub(
                event_type="step_summary_recorded",
                created_at=121.0,
                payload={
                    "step": "model_action_received:1",
                    "status": "running",
                    "summary": "正在整理公开投影。",
                    "provider_protocol_messages": [{"role": "system", "content": "large prompt"}],
                    "prompt_slots": [{"slot": "debug"}],
                },
            )
        ]
    })
    projector = RuntimeMonitorProjector(event_log, freshness_seconds=60.0)

    detail = projector.build_task_monitor(task_run(), now=130.0)
    visible = str(detail)

    assert detail["scope"] == "task_run"
    assert detail["trace_summary"]["authority"] == "runtime_monitor.trace_summary"
    assert "events" not in detail
    assert "provider_protocol_messages" not in visible
    assert "prompt_slots" not in visible


def test_project_task_run_marks_stale_graph_root_without_fetching_graph_detail():
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

    item = projector.project_task_run(run, now=300.0, include_runtime_details=False, include_graph_runtime=False)

    assert item["bucket"] == "diagnostics"
    assert item["lifecycle"] == "stale"
    assert item["activity_state"] == "stale"
    assert item["stale"] is True
    assert item["graph_status"]["active_node_id"] == ""
    assert projector.resource_resolver.graph_monitor_calls == []


def test_global_monitor_omits_stale_graph_root_without_fetching_graph_detail():
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

    assert monitor["task_runs"] == []
    assert monitor["summary"]["total"] == 0
    assert projector.resource_resolver.graph_monitor_calls == []


def test_task_graph_detail_uses_active_graph_loop_to_avoid_false_stale_diagnostic():
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

    item = projector.project_task_run(run, now=300.0, include_runtime_details=False, include_graph_runtime=True)

    assert item["bucket"] == "running"
    assert item["lifecycle"] == "running"
    assert item["stale"] is False
    assert item["graph_status"]["active_node_id"] == "world_design"
    assert projector.resource_resolver.graph_monitor_calls == [("grun:main", "ghcfg:existing", 80)]


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
