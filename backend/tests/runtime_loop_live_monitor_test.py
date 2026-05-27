from __future__ import annotations

import asyncio
import json
import threading

from harness.loop.checkpoint_store import HarnessCheckpointStore
from harness.loop.state import HarnessLoopState
from runtime.shared.models import CoordinationNodeRun, CoordinationRun, TaskRun
from runtime.memory.state_index import RuntimeStateIndex
from harness.observability import HarnessTraceReader
from runtime.shared.event_log import RuntimeEventLog
from harness.loop.graph_coordination.checkpoint_adapter import GraphCoordinationCheckpointStore


def test_global_live_monitor_uses_real_runtime_and_hides_old_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("harness.observability.time.time", lambda: 1000.0)
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = HarnessTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

    live = TaskRun(
        task_run_id="taskrun:test:live",
        session_id="session:test",
        task_id="task.live",
        status="running",
        created_at=900.0,
        updated_at=980.0,
    )
    recent_completed = TaskRun(
        task_run_id="taskrun:test:recent-completed",
        session_id="session:test",
        task_id="task.recent",
        status="completed",
        created_at=800.0,
        updated_at=930.0,
        terminal_reason="completed",
    )
    old_completed = TaskRun(
        task_run_id="taskrun:test:old-completed",
        session_id="session:test",
        task_id="task.old",
        status="completed",
        created_at=10.0,
        updated_at=20.0,
        terminal_reason="completed",
    )
    state_index.upsert_task_run(live)
    state_index.upsert_task_run(recent_completed)
    state_index.upsert_task_run(old_completed)

    monitor = reader.list_global_live_monitor(limit=20)
    items = {item["task_run_id"]: item for item in monitor["task_runs"]}

    assert list(items) == ["taskrun:test:live", "taskrun:test:recent-completed"]
    assert items["taskrun:test:live"]["is_live"] is True
    assert items["taskrun:test:live"]["display_bucket"] == "live"
    assert items["taskrun:test:live"]["runtime_seconds"] == 100.0
    assert items["taskrun:test:recent-completed"]["is_live"] is False
    assert items["taskrun:test:recent-completed"]["display_bucket"] == "recent"
    assert items["taskrun:test:recent-completed"]["runtime_seconds"] == 130.0
    assert monitor["summary"]["running"] == 1
    assert monitor["summary"]["recent"] == 1
    assert monitor["summary"]["completed"] == 1


def test_global_live_monitor_marks_inactive_running_task_as_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("harness.observability.time.time", lambda: 1000.0)
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = HarnessTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

    stale = TaskRun(
        task_run_id="taskrun:test:stale-running",
        session_id="session:test",
        task_id="task.stale",
        status="running",
        created_at=100.0,
        updated_at=200.0,
    )
    state_index.upsert_task_run(stale)

    monitor = reader.list_global_live_monitor(limit=20)
    item = monitor["task_runs"][0]

    assert item["task_run_id"] == stale.task_run_id
    assert item["is_live"] is False
    assert item["display_bucket"] == "stale"
    assert item["runtime_seconds"] == 100.0
    assert item["last_activity_age_seconds"] == 800.0
    assert monitor["summary"]["running"] == 0
    assert monitor["summary"]["stale"] == 1


def test_global_live_monitor_hides_task_graph_child_node_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("harness.observability.time.time", lambda: 1000.0)
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = HarnessTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

    root = TaskRun(
        task_run_id="taskrun:test:graph-root",
        session_id="session:test",
        task_id="task.graph",
        status="running",
        created_at=900.0,
        updated_at=990.0,
        diagnostics={
            "task_graph_run": True,
            "task_graph_title": "章节写作任务图",
        },
    )
    child = TaskRun(
        task_run_id="taskrun:test:graph-node-draft",
        session_id=root.session_id,
        task_id="task.graph.chapter_draft",
        task_contract_ref="task.graph.chapter_draft",
        status="running",
        created_at=930.0,
        updated_at=995.0,
        diagnostics={
            "coordination_run_id": "coordrun:test:graph-root:primary",
            "coordination_stage_id": "chapter_draft",
            "stage_id": "chapter_draft",
            "node_id": "chapter_draft",
            "stage_request_id": "nodeexec:chapter_draft",
            "stage_idempotency_key": "idem:chapter_draft",
        },
    )
    state_index.upsert_task_run(root)
    state_index.upsert_task_run(child)
    state_index.upsert_coordination_run(
        CoordinationRun(
            coordination_run_id="coordrun:test:graph-root:primary",
            task_run_id=root.task_run_id,
            coordinator_agent_id="agent:coordinator",
            graph_ref="graph.chapter",
            status="running",
            created_at=901.0,
            updated_at=996.0,
        )
    )

    monitor = reader.list_global_live_monitor(limit=20)

    assert [item["task_run_id"] for item in monitor["task_runs"]] == [root.task_run_id]
    assert monitor["task_runs"][0]["title"] == "章节写作任务图"
    assert monitor["task_runs"][0]["graph_id"] == "graph.chapter"
    assert monitor["summary"]["total"] == 1
    assert monitor["summary"]["running"] == 1


def test_runtime_event_log_publishes_appended_events_to_subscribers(tmp_path) -> None:
    event_log = RuntimeEventLog(tmp_path)
    all_events = event_log.subscribe()
    scoped_events = event_log.subscribe(task_run_id="taskrun:test:target")

    ignored = event_log.append(
        "taskrun:test:other",
        "task_run_started",
        payload={"status": "running"},
    )
    target = event_log.append(
        "taskrun:test:target",
        "task_run_ledger_updated",
        payload={"status": "running", "step": "draft"},
    )

    assert all_events.queue.get_nowait().event_id == ignored.event_id
    assert all_events.queue.get_nowait().event_id == target.event_id
    assert scoped_events.queue.get_nowait().event_id == target.event_id

    event_log.unsubscribe(all_events)
    event_log.unsubscribe(scoped_events)
    event_log.append("taskrun:test:target", "checkpoint_written")

    assert all_events.queue.empty()
    assert scoped_events.queue.empty()


def test_runtime_event_log_skips_corrupt_lines_and_keeps_offsets_monotonic(tmp_path) -> None:
    event_log = RuntimeEventLog(tmp_path)
    first = event_log.append("taskrun:test:corrupt", "task_run_started")
    path = event_log._event_path("taskrun:test:corrupt")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{not-json\n")

    assert [event.offset for event in event_log.list_events("taskrun:test:corrupt")] == [first.offset]

    resumed = event_log.append("taskrun:test:corrupt", "checkpoint_written")

    assert resumed.offset == 2
    assert [event.offset for event in event_log.list_events("taskrun:test:corrupt")] == [0, 2]


def test_runtime_event_log_wakes_async_subscriber_from_background_thread(tmp_path) -> None:
    async def collect_published_event() -> str:
        event_log = RuntimeEventLog(tmp_path)
        subscription = event_log.subscribe()
        ready = threading.Event()

        def publish_from_worker() -> None:
            ready.wait(timeout=2.0)
            event_log.append(
                "taskrun:test:threaded",
                "task_run_ledger_updated",
                payload={"status": "running", "source": "worker_thread"},
            )

        thread = threading.Thread(target=publish_from_worker)
        thread.start()
        try:
            ready.set()
            event = await asyncio.wait_for(subscription.queue.get(), timeout=2.0)
            return event.task_run_id
        finally:
            event_log.unsubscribe(subscription)
            thread.join(timeout=2.0)

    assert asyncio.run(collect_published_event()) == "taskrun:test:threaded"


def test_trace_reader_builds_live_monitor_from_latest_runtime_state(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = HarnessTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

    task_run = TaskRun(
        task_run_id="taskrun:test:coordination",
        session_id="session:test",
        task_id="task.longform.live",
        status="running",
        created_at=100.0,
        updated_at=130.0,
    )
    state_index.upsert_task_run(task_run)

    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:test:coordination",
        task_run_id=task_run.task_run_id,
        coordinator_agent_id="agent:showrunner",
        graph_ref="graph.longform.live",
        status="running",
        created_at=101.0,
        updated_at=131.0,
        diagnostics={
            "coordination_flow": {
                "current_stage_id": "world_design",
                "stages": [
                    {"stage_id": "world_design", "node_id": "world_design", "task_ref": "task.world", "status": "running"},
                    {"stage_id": "world_review", "node_id": "world_review", "task_ref": "task.review", "status": "pending"},
                ],
                "ready_nodes": ["world_review"],
            },
            "graph_coordination_state": {
                "ready_nodes": ["world_review"],
                "running_nodes": ["world_design"],
                "blocked_nodes": [],
                "waiting_nodes": [],
                "completed_nodes": [],
                "failed_nodes": [],
                "handoff_packets": [
                    {
                        "source_node_id": "world_design",
                        "target_node_id": "world_review",
                        "message_type": "draft_handoff",
                        "status": "running",
                    }
                ],
                "working_memory_operations": [
                    {
                        "operation": "write_candidate",
                        "stage_id": "world_design",
                        "status": "completed",
                        "created_working_memory_refs": ["wm:1"],
                    }
                ],
                "contract_status": {
                    "valid": True,
                    "node_status": {
                        "world_design": {"status": "running"},
                        "world_review": {"status": "pending"},
                    },
                },
            },
            "coordination_graph_spec": {
                "graph_id": "graph.longform.live",
                "coordination_task_id": "coord.longform.live",
                "nodes": [
                    {"node_id": "world_design", "title": "世界观设计", "role": "participant", "agent_id": "agent:world_builder", "metadata": {}},
                    {"node_id": "world_review", "title": "世界观审核", "role": "reviewer", "agent_id": "agent:world_reviewer", "metadata": {}},
                ],
                "edges": [
                    {"edge_id": "edge-1", "from_node_id": "world_design", "to_node_id": "world_review", "label": "交接"}
                ],
            },
        },
    )
    state_index.upsert_coordination_run(coordination_run)
    state_index.upsert_coordination_node_run(
        CoordinationNodeRun(
            node_run_id="coordnode:test:world_design",
            coordination_run_id=coordination_run.coordination_run_id,
            task_run_id=task_run.task_run_id,
            node_id="world_design",
            role="participant",
            status="running",
            created_at=102.0,
            updated_at=132.0,
            diagnostics={"stage_status": "running"},
        )
    )

    checkpoints.write(
        HarnessLoopState(
            task_run_id=task_run.task_run_id,
            status="waiting_approval",
            turn_count=1,
            step_count=1,
            terminal_reason="waiting_approval",
            pending_approval_state={"status": "pending", "stage_id": "world_design"},
            diagnostics={"checkpoint_marker": "live"},
        ),
        event_offset=12,
    )

    state_index.read_snapshot = lambda: (_ for _ in ()).throw(AssertionError("full snapshot should not be used"))  # type: ignore[method-assign]
    monitor = reader.get_session_live_monitor("session:test")

    assert monitor["latest_task_run_id"] == task_run.task_run_id
    assert monitor["latest_coordination_task_run_id"] == task_run.task_run_id
    assert monitor["latest_coordination_run_id"] == coordination_run.coordination_run_id
    assert monitor["monitor"] is not None
    assert monitor["monitor"]["has_coordination"] is True
    assert monitor["monitor"]["coordination_run"]["coordination_flow"]["current_stage_id"] == "world_design"
    assert monitor["monitor"]["coordination_run"]["graph_coordination_state"]["running_nodes"] == ["world_design"]
    assert monitor["monitor"]["coordination_run"]["coordination_graph_spec"]["coordination_task_id"] == "coord.longform.live"
    assert monitor["monitor"]["coordination_run"]["node_runs"][0]["node_id"] == "world_design"
    assert monitor["monitor"]["latest_checkpoint"]["resume_state"]["decision"] == "wait_for_human"
    assert monitor["monitor"]["loop_state"]["checkpoint_resume_state"]["reason"] == "human_gate_pending"


def test_session_live_view_preserves_coordination_pointer_after_root_task_update(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    task_run = TaskRun(
        task_run_id="taskrun:test:root",
        session_id="sessiontest",
        task_id="task.longform.live",
        status="running",
        created_at=100.0,
        updated_at=110.0,
    )
    state_index.upsert_task_run(task_run)
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:test:root",
        task_run_id=task_run.task_run_id,
        coordinator_agent_id="agent:showrunner",
        graph_ref="graph.longform.live",
        status="running",
        created_at=101.0,
        updated_at=111.0,
    )
    state_index.upsert_coordination_run(coordination_run)
    state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run.task_run_id,
            session_id=task_run.session_id,
            task_id=task_run.task_id,
            status="aborted",
            created_at=task_run.created_at,
            updated_at=120.0,
            terminal_reason="user_aborted",
        )
    )

    live_view = state_index._read_session_live_view("sessiontest")
    assert live_view["latest_task_run_id"] == "taskrun:test:root"
    assert live_view["latest_coordination_task_run_id"] == "taskrun:test:root"
    assert live_view["latest_coordination_run_id"] == "coordrun:test:root"


def test_session_live_monitor_prefers_freshest_task_run_over_stale_live_view_pointer(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = HarnessTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

    stale = TaskRun(
        task_run_id="taskrun:test:stale",
        session_id="session:test",
        task_id="task.old",
        status="running",
        created_at=100.0,
        updated_at=110.0,
    )
    fresh = TaskRun(
        task_run_id="taskrun:test:fresh",
        session_id="session:test",
        task_id="task.new",
        status="completed",
        created_at=120.0,
        updated_at=220.0,
        terminal_reason="done",
    )
    state_index.upsert_task_run(stale)
    state_index.upsert_task_run(fresh)

    session_view = state_index._read_session_live_view("session:test")
    session_view["latest_task_run_id"] = stale.task_run_id
    session_view["latest_coordination_task_run_id"] = stale.task_run_id
    state_index._session_live_view_path("session:test").write_text(
        json.dumps(session_view, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monitor = reader.get_session_live_monitor("session:test")

    assert monitor["latest_task_run_id"] == fresh.task_run_id
    assert monitor["latest_coordination_task_run_id"] == ""
    assert monitor["latest_coordination_run_id"] == ""
    assert monitor["monitor"] is not None
    assert monitor["monitor"]["status"] == "completed"


def test_task_graph_monitor_reads_stream_chunks_from_active_node_task_run(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = HarnessCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    coordination_checkpoints = GraphCoordinationCheckpointStore(tmp_path)
    reader = HarnessTraceReader(
        state_index=state_index,
        event_log=event_log,
        checkpoints=checkpoints,
        coordination_checkpoints=coordination_checkpoints,
    )

    root = TaskRun(
        task_run_id="taskrun:test:writing-root",
        session_id="session:test-writing",
        task_id="task.writing.long_run",
        status="running",
        created_at=100.0,
        updated_at=200.0,
    )
    state_index.upsert_task_run(root)
    coordination_run = CoordinationRun(
        coordination_run_id="coordrun:test:writing-root:primary",
        task_run_id=root.task_run_id,
        coordinator_agent_id="agent:coordinator",
        graph_ref="graph.writing",
        status="running",
        created_at=101.0,
        updated_at=201.0,
    )
    state_index.upsert_coordination_run(coordination_run)

    stale_child = TaskRun(
        task_run_id="taskrun:test:child:newer-index",
        session_id=root.session_id,
        task_id="taskinst:turn:session:test:newer:chapter_draft",
        task_contract_ref="taskinst:turn:session:test:newer:chapter_draft",
        status="running",
        created_at=120.0,
        updated_at=260.0,
    )
    active_child = TaskRun(
        task_run_id="taskrun:test:child:active-stream",
        session_id=root.session_id,
        task_id="taskinst:turn:session:test:older:chapter_draft",
        task_contract_ref="taskinst:turn:session:test:older:chapter_draft",
        status="running",
        created_at=110.0,
        updated_at=150.0,
    )
    state_index.upsert_task_run(stale_child)
    state_index.upsert_task_run(active_child)
    event_log.append(
        active_child.task_run_id,
        "model_item_received",
        payload={
            "stream_ref": "stream:chapter",
            "delta_index": 1,
            "delta_chars": 4,
            "accumulated_chars": 4,
            "delta_preview": "正文片段",
        },
    )
    coordination_checkpoints.put_state(
        thread_id=coordination_run.coordination_run_id,
        state={
            "coordination_run_id": coordination_run.coordination_run_id,
            "root_task_run_id": root.task_run_id,
            "active_stage_id": "chapter_draft",
            "active_node_id": "chapter_draft",
            "running_nodes": ["chapter_draft"],
            "diagnostics": {
                "coordination_graph_spec": {
                    "graph_id": "graph.writing",
                    "nodes": [{"node_id": "chapter_draft", "title": "章节正文"}],
                    "edges": [],
                }
            },
            "stage_execution_request": {
                "request_id": "nodeexec:chapter_draft",
                "stage_id": "chapter_draft",
                "node_id": "chapter_draft",
                "dispatch_context": {
                    "activation_id": "activation:chapter_draft",
                    "execution_permit_id": "permit:chapter_draft",
                    "dispatch_event_id": "tlevent:chapter_draft",
                },
                "task_ref": "task.writing.chapter_draft",
                "stream_policy": {
                    "enabled": True,
                    "mode": "model_text_stream",
                    "monitor_visibility": "task_graph_monitor",
                },
            },
        },
    )

    monitor = reader.get_coordination_run_monitor(coordination_run.coordination_run_id)

    assert monitor is not None
    assert monitor["runtime"]["active_node_id"] == "chapter_draft"
    assert monitor["streaming"]["chunk_count"] == 1
    assert monitor["streaming"]["accumulated_chars"] == 4
    assert "正文片段" in monitor["streaming"]["preview_text"]


