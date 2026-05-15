from __future__ import annotations

import json

from orchestration.runtime_loop.checkpoint import RuntimeCheckpointStore
from orchestration.runtime_loop.models import CoordinationNodeRun, CoordinationRun, RuntimeLoopState, TaskRun
from orchestration.runtime_loop.state_index import RuntimeStateIndex
from orchestration.runtime_loop.trace_reader import RuntimeLoopTraceReader
from orchestration.runtime_loop.event_log import RuntimeEventLog


def test_trace_reader_builds_live_monitor_from_latest_runtime_state(tmp_path) -> None:
    state_index = RuntimeStateIndex(tmp_path)
    checkpoints = RuntimeCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = RuntimeLoopTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

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
            "langgraph_runtime_state": {
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
        RuntimeLoopState(
            task_run_id=task_run.task_run_id,
            status="running",
            turn_count=1,
            step_count=1,
            diagnostics={"checkpoint_marker": "live"},
        ),
        event_offset=12,
    )

    state_index.read_snapshot = lambda: (_ for _ in ()).throw(AssertionError("full snapshot should not be used"))  # type: ignore[method-assign]
    monitor = reader.get_session_live_monitor("session:test")

    assert monitor["latest_task_run_id"] == task_run.task_run_id
    assert monitor["monitor"] is not None
    assert monitor["monitor"]["has_coordination"] is True
    assert monitor["monitor"]["coordination_run"]["coordination_flow"]["current_stage_id"] == "world_design"
    assert monitor["monitor"]["coordination_run"]["langgraph_runtime_state"]["running_nodes"] == ["world_design"]
    assert monitor["monitor"]["coordination_run"]["coordination_graph_spec"]["coordination_task_id"] == "coord.longform.live"
    assert monitor["monitor"]["coordination_run"]["node_runs"][0]["node_id"] == "world_design"


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
    checkpoints = RuntimeCheckpointStore(tmp_path)
    event_log = RuntimeEventLog(tmp_path)
    reader = RuntimeLoopTraceReader(state_index=state_index, event_log=event_log, checkpoints=checkpoints)

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
    assert monitor["monitor"] is not None
    assert monitor["monitor"]["status"] == "completed"
