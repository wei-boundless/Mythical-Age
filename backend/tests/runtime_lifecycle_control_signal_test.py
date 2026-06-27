from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.runtime.session_lifecycle import SessionRuntimeLifecycleManager
from harness.runtime.single_agent_host import SingleAgentRuntimeHost
from harness.runtime.task_record_lifecycle import TaskRecordLifecycleManager
from runtime.shared.models import TaskRun


def test_session_lifecycle_executor_stop_returns_gateway_signal_refs(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=BACKEND_DIR)
    session_id = "session:lifecycle-stop"
    task_run_ids = {"taskrun:lifecycle-stop:a", "taskrun:lifecycle-stop:b"}
    for task_run_id in task_run_ids:
        _insert_task_run(host, task_run_id=task_run_id, session_id=session_id)
    runtime = _runtime_stub(tmp_path, host=host)

    result = asyncio.run(
        SessionRuntimeLifecycleManager(runtime).detach_session_runtime(
            session_id,
            session_history={},
        )
    )
    effect = dict(result["effects"]["executor_stop"])

    assert set(effect["accepted_task_run_ids"]) == task_run_ids
    assert effect["failed_task_run_ids"] == []
    assert {item["task_run_id"] for item in effect["control_signals"]} == task_run_ids
    for signal in effect["control_signals"]:
        task_run_id = signal["task_run_id"]
        signal_ref = signal["runtime_control_signal_ref"]
        event_signal = _published_signal_by_id(host, task_run_id=task_run_id, signal_id=signal_ref)
        assert event_signal["signal_type"] == "control.signal.requested"
        assert event_signal["payload"]["signal_kind"] == "stop"
        assert event_signal["payload"]["reason"] == "session_deleted"
        assert event_signal["payload"]["requested_by"] == "session_lifecycle"


def test_session_lifecycle_executor_stop_reports_missing_gateway_without_shadow_control(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=BACKEND_DIR)
    session_id = "session:lifecycle-no-gateway"
    task_run_id = "taskrun:lifecycle-no-gateway"
    _insert_task_run(host, task_run_id=task_run_id, session_id=session_id)
    host.runtime_gateway = None
    runtime = _runtime_stub(tmp_path, host=host)

    result = asyncio.run(
        SessionRuntimeLifecycleManager(runtime).detach_session_runtime(
            session_id,
            session_history={},
        )
    )
    effect = dict(result["effects"]["executor_stop"])

    assert effect["accepted_task_run_ids"] == []
    assert effect["control_signals"] == []
    assert effect["failed_task_run_ids"] == [task_run_id]
    assert _published_control_signals(host, task_run_id=task_run_id) == []


def test_task_record_lifecycle_deletion_mark_returns_gateway_signal_ref(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=BACKEND_DIR)
    task_run_id = "taskrun:record-delete"
    _insert_task_run(host, task_run_id=task_run_id, session_id="session:record-delete")
    runtime = _runtime_stub(tmp_path, host=host)

    _task_run, effect = asyncio.run(
        TaskRecordLifecycleManager(runtime).prepare_single_task_record_deletion(
            task_run_id,
            cancel_timeout_seconds=0.1,
        )
    )
    executor_stop = dict(effect["executor_stop"])
    signal = dict(executor_stop["control_signals"][0])
    event_signal = _published_signal_by_id(
        host,
        task_run_id=task_run_id,
        signal_id=signal["runtime_control_signal_ref"],
    )

    assert executor_stop["accepted_task_run_ids"] == [task_run_id]
    assert executor_stop["failed_task_run_ids"] == []
    assert signal["signal_kind"] == "stop"
    assert signal["reason"] == "task_record_deleted"
    assert event_signal["signal_type"] == "control.signal.requested"
    assert event_signal["payload"]["requested_by"] == "task_record_lifecycle"
    assert event_signal["payload"]["reason"] == "task_record_deleted"


def test_task_record_lifecycle_deletion_mark_reports_missing_gateway(tmp_path: Path) -> None:
    host = SingleAgentRuntimeHost(tmp_path, backend_dir=BACKEND_DIR)
    task_run_id = "taskrun:record-delete-no-gateway"
    _insert_task_run(host, task_run_id=task_run_id, session_id="session:record-delete-no-gateway")
    host.runtime_gateway = None
    runtime = _runtime_stub(tmp_path, host=host)

    _task_run, effect = asyncio.run(
        TaskRecordLifecycleManager(runtime).prepare_single_task_record_deletion(
            task_run_id,
            cancel_timeout_seconds=0.1,
        )
    )
    executor_stop = dict(effect["executor_stop"])

    assert executor_stop["accepted_task_run_ids"] == []
    assert executor_stop["control_signals"] == []
    assert executor_stop["failed_task_run_ids"] == [task_run_id]
    assert _published_control_signals(host, task_run_id=task_run_id) == []


def _runtime_stub(tmp_path: Path, *, host: SingleAgentRuntimeHost) -> SimpleNamespace:
    return SimpleNamespace(
        base_dir=tmp_path,
        harness_runtime=SimpleNamespace(
            single_agent_runtime_host=host,
            graph_system=None,
        ),
        session_manager=SimpleNamespace(get_history=lambda _session_id: {}),
    )


def _insert_task_run(host: SingleAgentRuntimeHost, *, task_run_id: str, session_id: str) -> None:
    now = time.time()
    host.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run_id,
            session_id=session_id,
            task_id=f"task:{task_run_id}",
            status="running",
            created_at=now,
            updated_at=now,
        )
    )


def _published_signal_by_id(
    host: SingleAgentRuntimeHost,
    *,
    task_run_id: str,
    signal_id: str,
) -> dict[str, object]:
    for signal in _published_control_signals(host, task_run_id=task_run_id):
        if str(signal.get("signal_id") or "") == signal_id:
            return signal
    raise AssertionError(f"missing published signal {signal_id}")


def _published_control_signals(host: SingleAgentRuntimeHost, *, task_run_id: str) -> list[dict[str, object]]:
    return [
        dict(dict(event.payload or {}).get("signal") or {})
        for event in host.event_log.list_events(task_run_id)
        if event.event_type == "runtime_control_signal_published"
    ]
