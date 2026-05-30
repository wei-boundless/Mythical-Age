from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from runtime.shared.models import TaskRun
from harness.loop.task_steering import (
    create_active_task_steer,
    list_pending_task_steers,
    list_task_steers,
    mark_task_steers_consumed,
    mark_task_steers_included,
)
from tests.support.runtime_stubs import build_query_runtime


def test_active_task_steer_records_submission_and_lifecycle_events() -> None:
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:steer-protocol"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-steer-protocol",
            task_id="task:steer-protocol",
            execution_runtime_kind="single_agent_task",
            status="running",
        )
    )

    result = create_active_task_steer(
        host,
        task_run_id,
        content="优先修复资源加载。",
        turn_id="turn:steer-protocol:1",
    )
    steer_id = result["steer"]["steer_id"]

    events = host.event_log.list_events(task_run_id)
    event_types = [event.event_type for event in events]
    submission_event = next(event for event in events if event.event_type == "user_submission_recorded")
    steer_event = next(event for event in events if event.event_type == "active_task_steer_recorded")

    assert result["ok"] is True
    assert event_types.index("user_submission_recorded") < event_types.index("active_task_steer_recorded")
    assert submission_event.refs["submission_ref"] == result["submission"]["submission_id"]
    assert steer_event.refs["steer_ref"] == steer_id
    assert list_pending_task_steers(host, task_run_id)[0]["steer_id"] == steer_id


def test_consumed_steer_cannot_be_reopened_by_late_include_transition() -> None:
    runtime = build_query_runtime()
    host = runtime.single_agent_runtime_host
    task_run_id = "taskrun:steer-terminal-state"
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id="session-steer-terminal-state",
            task_id="task:steer-terminal-state",
            execution_runtime_kind="single_agent_task",
            status="running",
        )
    )
    steer = create_active_task_steer(host, task_run_id, content="不要直接完成。")["steer"]
    steer_id = steer["steer_id"]

    included = mark_task_steers_included(host, task_run_id, steer_ids=[steer_id], packet_ref="rtpacket:one")
    consumed = mark_task_steers_consumed(host, task_run_id, steer_ids=[steer_id], action_ref="model-action:one")
    reopened = mark_task_steers_included(host, task_run_id, steer_ids=[steer_id], packet_ref="rtpacket:late")
    final_steer = list_task_steers(host, task_run_id)[0]

    assert included[0]["consumption_state"] == "included_in_packet"
    assert consumed[0]["consumption_state"] == "consumed"
    assert reopened == []
    assert final_steer["consumption_state"] == "consumed"
    assert list_pending_task_steers(host, task_run_id) == []
