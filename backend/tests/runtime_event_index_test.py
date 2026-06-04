from __future__ import annotations

import json

from runtime.shared.event_log import RuntimeEventLog
from runtime.shared import event_index
from runtime.shared.models import TaskRun
from harness.runtime.single_agent_host import SingleAgentRuntimeHost


def test_runtime_event_log_uses_cursor_after_initial_index_build(tmp_path, monkeypatch) -> None:
    log = RuntimeEventLog(tmp_path)
    path = log._event_path("taskrun:test")
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "event_id": f"evt:{index}",
                    "task_run_id": "taskrun:test",
                    "event_type": "step_summary_recorded",
                    "offset": index,
                    "created_at": float(index),
                    "payload": {"summary": f"step {index}"},
                    "refs": {},
                    "authority": "orchestration.runtime_event",
                }
            )
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )

    assert log.next_offset("taskrun:test") == 3

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("cursor-backed next_offset must not rebuild from full event file")

    monkeypatch.setattr(event_index, "rebuild_event_index", fail_rebuild)
    event = log.append("taskrun:test", "step_summary_recorded", payload={"summary": "step 3"})

    assert event.offset == 3
    assert event.run_id == "taskrun:test"
    assert log.next_offset("taskrun:test") == 4


def test_runtime_event_log_recent_events_and_count_use_index(tmp_path) -> None:
    log = RuntimeEventLog(tmp_path)
    for index in range(5):
        log.append("taskrun:test", "step_summary_recorded", payload={"summary": f"step {index}"})

    recent = log.list_recent_events("taskrun:test", limit=2)

    assert [item.offset for item in recent] == [3, 4]
    assert log.event_count("taskrun:test") == 5


def test_runtime_event_index_atomic_write_retries_windows_replace_lock(tmp_path, monkeypatch) -> None:
    target = tmp_path / "tail.json"
    calls = {"count": 0}
    original_replace = event_index.os.replace

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("target is temporarily locked")
        return original_replace(src, dst)

    monkeypatch.setattr(event_index.os, "replace", flaky_replace)
    monkeypatch.setattr(event_index.time, "sleep", lambda _seconds: None)

    event_index._atomic_write_json(target, {"ok": True})

    assert calls["count"] == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_runtime_event_log_recent_events_can_read_tail_without_full_index_rebuild(tmp_path, monkeypatch) -> None:
    log = RuntimeEventLog(tmp_path)
    path = log._event_path("taskrun:test")
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "event_id": f"evt:{index}",
                    "task_run_id": "taskrun:test",
                    "event_type": "step_summary_recorded",
                    "offset": index,
                    "created_at": float(index),
                    "payload": {"summary": f"step {index}"},
                    "refs": {},
                    "authority": "orchestration.runtime_event",
                }
            )
            for index in range(12)
        )
        + "\n",
        encoding="utf-8",
    )

    def fail_rebuild(*_args, **_kwargs):
        raise AssertionError("recent monitor reads must not rebuild from the full event file")

    monkeypatch.setattr(event_index, "rebuild_event_index", fail_rebuild)

    recent = log.list_recent_events("taskrun:test", limit=3)

    assert [item.offset for item in recent] == [9, 10, 11]
    assert log.estimated_event_count("taskrun:test") == 12


def test_runtime_event_log_externalizes_large_payloads_and_hydrates_full_reads(tmp_path) -> None:
    log = RuntimeEventLog(tmp_path)
    large_text = "x" * (40 * 1024)

    event = log.append(
        "taskrun:test",
        "bounded_observation_recorded",
        payload={
            "summary": "读取了长输出。",
            "observation": {
                "source": "tool:shell",
                "summary": "工具输出较长。",
                "payload": {"result": large_text},
            },
        },
    )

    raw_line = log._event_path("taskrun:test").read_text(encoding="utf-8").strip()
    stored_row = json.loads(raw_line)
    assert stored_row["run_id"] == "taskrun:test"
    assert "task_run_id" not in stored_row
    assert stored_row["payload"]["payload_externalized"] is True
    assert stored_row["payload"]["summary"] == "读取了长输出。"
    assert large_text not in raw_line
    assert stored_row["refs"]["payload_ref"].startswith("rtpayload:")
    assert (tmp_path / stored_row["refs"]["payload_path"]).exists()
    envelope = json.loads((tmp_path / stored_row["refs"]["payload_path"]).read_text(encoding="utf-8"))
    assert envelope["run_id"] == "taskrun:test"
    assert "safe_task_run_id" not in envelope

    recent = log.list_recent_events("taskrun:test", limit=1)[0]
    assert recent.payload["payload_externalized"] is True
    assert "result" not in dict(recent.payload.get("observation") or {})

    hydrated = log.list_events("taskrun:test")[0]
    assert hydrated.event_id == event.event_id
    assert hydrated.payload["observation"]["payload"]["result"] == large_text


def test_default_trace_uses_tail_without_full_event_scan(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:test",
            session_id="session:test",
            task_id="task:test",
            execution_runtime_kind="single_agent_task",
            status="running",
        )
    )
    for index in range(6):
        host.event_log.append("taskrun:test", "step_summary_recorded", payload={"summary": f"step {index}"})

    def fail_full_read(_task_run_id):
        raise AssertionError("default trace must not full-scan the runtime event JSONL")

    monkeypatch.setattr(host.event_log, "list_events", fail_full_read)

    trace = host.get_trace("taskrun:test", include_payloads=False, event_limit=3)

    assert trace is not None
    assert trace["event_count"] == 6
    assert trace["event_window"] == {"kind": "tail", "limit": 3, "returned": 3, "include_payloads": False}
    assert [item["offset"] for item in trace["events"]] == [3, 4, 5]


def test_bounded_payload_trace_reads_tail_and_hydrates_without_full_scan(tmp_path, monkeypatch) -> None:
    host = SingleAgentRuntimeHost(tmp_path)
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id="taskrun:test",
            session_id="session:test",
            task_id="task:test",
            execution_runtime_kind="single_agent_task",
            status="running",
        )
    )
    large_text = "payload" * 8000
    for index in range(4):
        payload = {"summary": f"step {index}"}
        if index == 3:
            payload = {"summary": "large", "observation": {"payload": {"result": large_text}}}
        host.event_log.append("taskrun:test", "step_summary_recorded", payload=payload)

    def fail_full_read(_task_run_id):
        raise AssertionError("bounded payload trace must not full-scan the runtime event JSONL")

    monkeypatch.setattr(host.event_log, "list_events", fail_full_read)

    trace = host.get_trace("taskrun:test", include_payloads=True, event_limit=2)

    assert trace is not None
    assert trace["event_count"] == 4
    assert trace["event_window"]["kind"] == "bounded_full_payload_tail"
    assert [item["offset"] for item in trace["events"]] == [2, 3]
    assert trace["events"][-1]["payload"]["observation"]["payload"]["result"] == large_text
