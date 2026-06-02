from types import SimpleNamespace

from harness.runtime.monitoring import RuntimeMonitorProjector


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


def test_global_monitor_filters_internal_static_history_and_child_runs_and_applies_per_bucket_limit():
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
    assert monitor["buckets"]["completed"] == []
    assert "taskrun:child" not in {item["task_run_id"] for item in monitor["task_runs"]}
    assert "taskrun:completed-1" not in {item["task_run_id"] for item in monitor["task_runs"]}


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


def test_global_monitor_uses_summary_projection_without_graph_detail_fetch():
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
        "node_runtime_views": [{"node_id": "draft", "node_executor_task_run_id": "gtask:draft"}],
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
    assert event_log.list_recent_event_calls == []
    assert event_log.event_count_calls == []
    assert resolver.graph_monitor_calls == []


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
