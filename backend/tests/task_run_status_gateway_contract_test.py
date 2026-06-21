from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness.runtime.control_events import RuntimeSignalScope
from harness.runtime.runtime_gateway import RuntimeGateway
from harness.loop.task_run_recovery_state import recovery_state_for_task_run
from harness.loop.task_lifecycle import current_session_task_run
from harness.task_run_state_view import task_run_state_view
from harness.task_run_status import (
    is_stopped_or_terminal_task_run,
    runtime_control_state_from_task_run,
)
from runtime.shared.event_log import RuntimeEventLog
from runtime.shared.models import TaskRun


def _runtime_host(root_dir: Path):
    event_log = RuntimeEventLog(root_dir)
    return SimpleNamespace(
        event_log=event_log,
        runtime_gateway=RuntimeGateway(event_log),
    )


class _StateIndex:
    def __init__(self, task_runs: list[TaskRun]) -> None:
        self._task_runs = list(task_runs)

    def list_session_task_runs(self, session_id: str) -> list[TaskRun]:
        return [item for item in self._task_runs if item.session_id == session_id]


def _task_run(
    task_run_id: str,
    *,
    status: str = "running",
    terminal_reason: str = "",
    diagnostics: dict | None = None,
) -> TaskRun:
    return TaskRun(
        task_run_id=task_run_id,
        session_id=f"session:{task_run_id}",
        task_id=f"task:{task_run_id}",
        execution_runtime_kind="single_agent_task",
        status=status,  # type: ignore[arg-type]
        created_at=100.0,
        updated_at=120.0,
        terminal_reason=terminal_reason,  # type: ignore[arg-type]
        diagnostics=dict(diagnostics or {}),
    )


def test_bare_stop_requested_diagnostics_does_not_terminalize_running_task(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:bare-stop-requested",
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "stop_requested",
                "requested_by": "test",
                "reason": "shadow diagnostic",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == ""
    assert is_stopped_or_terminal_task_run(task_run, runtime_host=host) is False
    assert view["task_work_state"] == "pending_executor"
    assert view["control_state"] == ""


def test_unpublished_stop_signal_ref_does_not_terminalize_running_task(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:fake-stop-ref",
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "stop_requested",
                "requested_by": "test",
                "reason": "fake ref",
                "runtime_control_signal_ref": "rtsig:missing",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == ""
    assert is_stopped_or_terminal_task_run(task_run, runtime_host=host) is False
    assert view["task_work_state"] == "pending_executor"
    assert view["control_state"] == ""


def test_gateway_published_stop_signal_terminalizes_control_state(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run_id = "taskrun:gateway-stop-ref"
    signal_id = "rtsig:gateway-stop-ref"
    host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=RuntimeSignalScope(task_run_id=task_run_id),
        source_authority="test.task_run_status_gateway_contract",
        payload={"signal_kind": "stop", "task_run_id": task_run_id},
    )
    task_run = _task_run(
        task_run_id,
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "stop_requested",
                "requested_by": "test",
                "reason": "gateway ref",
                "runtime_control_signal_ref": signal_id,
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == "stop_requested"
    assert is_stopped_or_terminal_task_run(task_run, runtime_host=host) is True
    assert view["task_work_state"] == "stopped"
    assert view["control_state"] == "stop_requested"


def test_gateway_signal_lookup_uses_recent_raw_tail_without_hydrating_payloads(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run_id = "taskrun:gateway-signal-fast-path"
    signal_id = "rtsig:gateway-signal-fast-path"
    host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=RuntimeSignalScope(task_run_id=task_run_id),
        source_authority="test.task_run_status_gateway_contract",
        payload={"signal_kind": "stop", "task_run_id": task_run_id},
    )

    def fail_hydration(_payload):
        raise AssertionError("signal_by_id should not hydrate full event payloads for recent signals")

    host.event_log.payload_store.hydrate_event_payload = fail_hydration

    signal = host.runtime_gateway.signal_by_id(task_run_id, signal_id=signal_id)

    assert signal is not None
    assert signal.signal_id == signal_id


def test_durable_aborted_lifecycle_remains_terminal_without_gateway_ref(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:durable-aborted",
        status="aborted",
        terminal_reason="user_aborted",
        diagnostics={
            "runtime_control": {
                "state": "stopped",
                "requested_by": "user",
                "reason": "user stop",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == "stopped"
    assert is_stopped_or_terminal_task_run(task_run, runtime_host=host) is True
    assert view["task_work_state"] == "stopped"


def test_bare_pause_request_diagnostics_does_not_pause_running_task(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:bare-pause-requested",
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "pause_requested",
                "requested_by": "test",
                "reason": "shadow pause",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)
    recovery = recovery_state_for_task_run(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == ""
    assert view["task_work_state"] == "pending_executor"
    assert view["control_state"] == ""
    assert recovery.control_state == ""
    assert recovery.paused is False


def test_gateway_pause_request_controls_running_task_state(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run_id = "taskrun:gateway-pause-requested"
    signal_id = "rtsig:gateway-pause-requested"
    host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=RuntimeSignalScope(task_run_id=task_run_id),
        source_authority="test.task_run_status_gateway_contract",
        payload={"signal_kind": "pause", "task_run_id": task_run_id},
    )
    task_run = _task_run(
        task_run_id,
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "pause_requested",
                "requested_by": "test",
                "reason": "gateway pause",
                "runtime_control_signal_ref": signal_id,
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)
    recovery = recovery_state_for_task_run(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == "pause_requested"
    assert view["task_work_state"] == "paused"
    assert view["control_state"] == "pause_requested"
    assert recovery.control_state == "pause_requested"
    assert recovery.paused is True


def test_durable_paused_waiting_executor_remains_paused_without_gateway_ref(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:durable-paused",
        status="waiting_executor",
        diagnostics={
            "executor_status": "waiting_executor",
            "runtime_control": {
                "state": "paused",
                "requested_by": "user",
                "reason": "user pause",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)
    recovery = recovery_state_for_task_run(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == "paused"
    assert view["task_work_state"] == "paused"
    assert view["can_resume"] is True
    assert recovery.paused is True


def test_bare_recovery_action_does_not_make_task_executable(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:bare-recovery-action",
        status="waiting_executor",
        diagnostics={
            "executor_status": "waiting_executor",
            "recovery_action": "resume_task_run",
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)
    recovery = recovery_state_for_task_run(task_run, runtime_host=host)

    assert view["task_work_state"] == "ready_to_continue"
    assert recovery.recoverable is False
    assert recovery.same_run_resumable is False
    assert recovery.executable is False
    assert recovery.reason == "not_resumable"


def test_shadow_paused_running_task_does_not_affect_state_view_or_lease(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:shadow-paused-running",
        diagnostics={
            "executor_status": "",
            "runtime_control": {
                "state": "paused",
                "requested_by": "test",
                "reason": "shadow pause",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)
    recovery = recovery_state_for_task_run(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == ""
    assert view["control_state"] == ""
    assert view["task_work_state"] == "pending_executor"
    assert view["executor_lease_state"] == "none"
    assert recovery.paused is False


def test_bare_replan_request_diagnostics_does_not_enter_control_state(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:bare-replan-requested",
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "replan_requested",
                "requested_by": "test",
                "reason": "shadow replan",
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == ""
    assert view["task_work_state"] == "pending_executor"
    assert view["control_state"] == ""


def test_gateway_replan_request_preserves_control_state(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run_id = "taskrun:gateway-replan-requested"
    signal_id = "rtsig:gateway-replan-requested"
    host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=RuntimeSignalScope(task_run_id=task_run_id),
        source_authority="test.task_run_status_gateway_contract",
        payload={"signal_kind": "replan", "task_run_id": task_run_id},
    )
    task_run = _task_run(
        task_run_id,
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "replan_requested",
                "requested_by": "test",
                "reason": "gateway replan",
                "runtime_control_signal_ref": signal_id,
            },
        },
    )

    view = task_run_state_view(task_run, runtime_host=host)

    assert runtime_control_state_from_task_run(task_run, runtime_host=host) == "replan_requested"
    assert view["task_work_state"] == "pending_executor"
    assert view["control_state"] == "replan_requested"


def test_current_session_task_run_keeps_bare_stop_shadow_candidate(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run = _task_run(
        "taskrun:current-shadow-stop",
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "stop_requested",
                "requested_by": "test",
                "reason": "shadow diagnostic",
            },
        },
    )
    host.state_index = _StateIndex([task_run])

    current = current_session_task_run(host, session_id=task_run.session_id)

    assert current is task_run


def test_current_session_task_run_excludes_gateway_stop_candidate(tmp_path: Path) -> None:
    host = _runtime_host(tmp_path / "runtime_state")
    task_run_id = "taskrun:current-gateway-stop"
    signal_id = "rtsig:current-gateway-stop"
    host.runtime_gateway.publish(
        task_run_id,
        signal_type="control.signal.requested",
        signal_id=signal_id,
        scope=RuntimeSignalScope(task_run_id=task_run_id),
        source_authority="test.task_run_status_gateway_contract",
        payload={"signal_kind": "stop", "task_run_id": task_run_id},
    )
    task_run = _task_run(
        task_run_id,
        diagnostics={
            "executor_status": "running",
            "runtime_control": {
                "state": "stop_requested",
                "requested_by": "test",
                "reason": "gateway stop",
                "runtime_control_signal_ref": signal_id,
            },
        },
    )
    host.state_index = _StateIndex([task_run])

    assert current_session_task_run(host, session_id=task_run.session_id) is None
