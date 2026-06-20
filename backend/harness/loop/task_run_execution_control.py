from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from harness.runtime.control_events import RuntimeSignalScope, signal_scope_from_agent_scope
from runtime.tool_runtime.tool_invocation_control import registry_for


ExecutorSignalKind = Literal["pause", "stop", "replan"]


@dataclass(frozen=True, slots=True)
class ExecutorControlSignal:
    kind: ExecutorSignalKind
    task_run_id: str
    executor_epoch: int
    reason: str
    requested_by: str
    requested_at: float
    steer_ref: str = ""
    signal_id: str = ""
    control_event_ref: str = ""


@dataclass(slots=True)
class ExecutorEpochRecord:
    task_run_id: str
    executor_epoch: int
    model_task: asyncio.Task[Any] | None = None
    model_loop: asyncio.AbstractEventLoop | None = None
    signal: ExecutorControlSignal | None = None
    created_at: float = 0.0


def register_executor_epoch(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorEpochRecord:
    registry = _registry(runtime_host)
    record = ExecutorEpochRecord(
        task_run_id=task_run_id,
        executor_epoch=int(executor_epoch or 0),
        created_at=time.time(),
    )
    registry[task_run_id] = record
    return record


def attach_model_task(runtime_host: Any, *, task_run_id: str, executor_epoch: int, model_task: asyncio.Task[Any]) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None:
        record = register_executor_epoch(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    record.model_task = model_task
    try:
        record.model_loop = asyncio.get_running_loop()
    except RuntimeError:
        record.model_loop = None
    if record.signal is not None and not model_task.done():
        _cancel_model_task(record, reason=record.signal.reason or record.signal.kind)


def request_executor_pause(runtime_host: Any, *, task_run_id: str, reason: str = "", requested_by: str = "user") -> bool:
    return _request_signal(runtime_host, task_run_id=task_run_id, kind="pause", reason=reason, requested_by=requested_by)


def request_executor_stop(runtime_host: Any, *, task_run_id: str, reason: str = "", requested_by: str = "user") -> bool:
    return _request_signal(runtime_host, task_run_id=task_run_id, kind="stop", reason=reason, requested_by=requested_by)


def request_executor_replan(
    runtime_host: Any,
    *,
    task_run_id: str,
    reason: str = "",
    requested_by: str = "user",
    steer_ref: str = "",
) -> bool:
    return _request_signal(
        runtime_host,
        task_run_id=task_run_id,
        kind="replan",
        reason=reason,
        requested_by=requested_by,
        steer_ref=steer_ref,
    )


def ensure_executor_control_signal_requested(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: ExecutorSignalKind,
    reason: str = "",
    requested_by: str = "system",
    steer_ref: str = "",
    unavailable_reason: str = "target_cell_unavailable",
) -> bool:
    existing = _latest_requested_control_signal(
        runtime_host,
        task_run_id=task_run_id,
        kind=kind,
        steer_ref=steer_ref,
    )
    if existing is not None:
        signal_id = str(existing.get("signal_id") or "")
        control_event_ref = str(existing.get("control_event_ref") or "")
        if _control_signal_is_closed(runtime_host, task_run_id=task_run_id, signal_id=signal_id):
            return bool(signal_id)
        scope = _runtime_signal_scope_for_task_run(runtime_host, task_run_id=task_run_id)
        _publish_executor_control_signal_target_unavailable(
            runtime_host,
            task_run_id=task_run_id,
            scope=scope,
            signal_id=signal_id,
            control_event_ref=control_event_ref,
            kind=kind,
            executor_epoch=_executor_epoch_from_task_run(
                getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
            ),
            reason=reason or str(dict(existing.get("payload") or {}).get("reason") or ""),
            requested_by=requested_by or str(dict(existing.get("payload") or {}).get("requested_by") or "system"),
            requested_at=float(dict(existing.get("payload") or {}).get("requested_at") or time.time()),
            steer_ref=steer_ref or str(dict(existing.get("payload") or {}).get("steer_ref") or ""),
            unavailable_reason=unavailable_reason,
            host_registry_cancel_count=0,
        )
        return bool(signal_id)
    return _request_signal(
        runtime_host,
        task_run_id=task_run_id,
        kind=kind,
        reason=reason,
        requested_by=requested_by,
        steer_ref=steer_ref,
        unavailable_reason=unavailable_reason,
    )


def peek_executor_signal(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorControlSignal | None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    return record.signal if record is not None else None


def clear_executor_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    executor_epoch: int,
    signal: ExecutorControlSignal | None = None,
) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None or record.signal is None:
        return
    if signal is not None and record.signal != signal:
        return
    record.signal = None


def clear_model_task(runtime_host: Any, *, task_run_id: str, executor_epoch: int, model_task: asyncio.Task[Any]) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is not None and record.model_task is model_task:
        record.model_task = None


def clear_executor_epoch(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> None:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is not None:
        _registry(runtime_host).pop(task_run_id, None)


def executor_epoch_is_live(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> bool:
    record = _current_record(runtime_host, task_run_id=task_run_id, executor_epoch=executor_epoch)
    if record is None:
        return False
    model_live = record.model_task is not None and not record.model_task.done()
    return model_live or record.model_task is None


def _request_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: ExecutorSignalKind,
    reason: str,
    requested_by: str,
    steer_ref: str = "",
    unavailable_reason: str = "target_cell_unavailable",
) -> bool:
    record = _registry(runtime_host).get(task_run_id)
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
    if record is None and task_run is None:
        return False
    executor_epoch = record.executor_epoch if record is not None else _executor_epoch_from_task_run(task_run)
    requested_at = time.time()
    signal_id, control_event_ref = _publish_executor_control_signal_requested(
        runtime_host,
        task_run_id=task_run_id,
        executor_epoch=executor_epoch,
        kind=kind,
        reason=reason,
        requested_by=requested_by,
        requested_at=requested_at,
        steer_ref=steer_ref,
    )
    signal = ExecutorControlSignal(
        kind=kind,
        task_run_id=task_run_id,
        executor_epoch=executor_epoch,
        reason=reason,
        requested_by=requested_by or "user",
        requested_at=requested_at,
        steer_ref=steer_ref,
        signal_id=signal_id,
        control_event_ref=control_event_ref,
    )
    if record is not None:
        record.signal = signal
        if record.model_task is not None and not record.model_task.done():
            _cancel_model_task(record, reason=reason or kind)
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    active_cell = supervisor.active_cell_for_task_run(task_run_id) if supervisor is not None else None
    if active_cell is not None:
        active_cell.tool_invocation_registry.cancel_by_caller(
            task_run_id=task_run_id,
            agent_run_id=active_cell.scope.agent_run_id,
            run_cell_id=active_cell.scope.run_cell_id,
            kind=kind,
            reason=reason,
            requested_by=requested_by,
            steer_ref=steer_ref,
        )
    else:
        host_registry_cancel_count = 0
        registry = registry_for(runtime_host)
        target_scope = _runtime_signal_scope_for_task_run(runtime_host, task_run_id=task_run_id)
        if registry is not None:
            host_registry_cancel_count = registry.cancel_by_caller(
                task_run_id=task_run_id,
                agent_run_id=target_scope.agent_run_id,
                run_cell_id=target_scope.run_cell_id,
                kind=kind,
                reason=reason,
                requested_by=requested_by,
                steer_ref=steer_ref,
            )
        if record is None and signal_id:
            _publish_executor_control_signal_target_unavailable(
                runtime_host,
                task_run_id=task_run_id,
                scope=target_scope,
                signal_id=signal_id,
                control_event_ref=control_event_ref,
                kind=kind,
                executor_epoch=executor_epoch,
                reason=reason,
                requested_by=requested_by,
                requested_at=requested_at,
                steer_ref=steer_ref,
                unavailable_reason=unavailable_reason,
                host_registry_cancel_count=host_registry_cancel_count,
            )
    return bool(signal_id or record is not None)


def _publish_executor_control_signal_requested(
    runtime_host: Any,
    *,
    task_run_id: str,
    executor_epoch: int,
    kind: ExecutorSignalKind,
    reason: str,
    requested_by: str,
    requested_at: float,
    steer_ref: str = "",
) -> tuple[str, str]:
    control_bus = getattr(runtime_host, "control_bus", None)
    if control_bus is None or not hasattr(control_bus, "publish"):
        return "", ""
    scope = _runtime_signal_scope_for_task_run(runtime_host, task_run_id=task_run_id)
    try:
        event = control_bus.publish(
            task_run_id,
            signal_type="control.signal.requested",
            scope=scope,
            source_authority="harness.loop.task_run_execution_control",
            payload={
                "signal_kind": kind,
                "task_run_id": task_run_id,
                "executor_epoch": int(executor_epoch or 0),
                "reason": str(reason or ""),
                "requested_by": str(requested_by or "user"),
                "requested_at": float(requested_at or 0.0),
                "steer_ref": str(steer_ref or ""),
                "adapter": "task_run_executor",
            },
            visibility="runtime_private",
            refs={
                "task_run_ref": task_run_id,
                **({"steer_ref": str(steer_ref)} if str(steer_ref or "").strip() else {}),
            },
        )
    except Exception:
        return "", ""
    signal_payload = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
    return str(signal_payload.get("signal_id") or ""), str(getattr(event, "event_id", "") or "")


def _publish_executor_control_signal_target_unavailable(
    runtime_host: Any,
    *,
    task_run_id: str,
    scope: RuntimeSignalScope,
    signal_id: str,
    control_event_ref: str,
    kind: ExecutorSignalKind,
    executor_epoch: int,
    reason: str,
    requested_by: str,
    requested_at: float,
    steer_ref: str = "",
    unavailable_reason: str = "target_cell_unavailable",
    host_registry_cancel_count: int = 0,
) -> Any | None:
    normalized_signal_id = str(signal_id or "").strip()
    if not normalized_signal_id:
        return None
    if _target_unavailable_already_recorded(
        runtime_host,
        task_run_id=task_run_id,
        requested_signal_id=normalized_signal_id,
        unavailable_reason=unavailable_reason,
    ):
        return None
    control_bus = getattr(runtime_host, "control_bus", None)
    if control_bus is None or not hasattr(control_bus, "publish"):
        return None
    try:
        return control_bus.publish(
            task_run_id,
            signal_type="control.signal.target_unavailable",
            scope=scope,
            source_authority="harness.loop.task_run_execution_control",
            payload={
                "requested_signal_id": normalized_signal_id,
                "requested_control_event_ref": str(control_event_ref or ""),
                "signal_kind": kind,
                "task_run_id": task_run_id,
                "executor_epoch": int(executor_epoch or 0),
                "reason": str(reason or ""),
                "requested_by": str(requested_by or "user"),
                "requested_at": float(requested_at or 0.0),
                "steer_ref": str(steer_ref or ""),
                "unavailable_reason": str(unavailable_reason or "target_cell_unavailable"),
                "target_agent_run_id": scope.agent_run_id,
                "target_run_cell_id": scope.run_cell_id,
                "host_registry_cancel_count": int(host_registry_cancel_count or 0),
                "pending_signal_remains_replayable": True,
                "adapter": "task_run_executor",
            },
            visibility="runtime_private",
            refs={
                "task_run_ref": task_run_id,
                "requested_signal_ref": normalized_signal_id,
                **({"steer_ref": str(steer_ref)} if str(steer_ref or "").strip() else {}),
            },
        )
    except Exception:
        return None


def _runtime_signal_scope_for_task_run(runtime_host: Any, *, task_run_id: str) -> RuntimeSignalScope:
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    active_cell = supervisor.active_cell_for_task_run(task_run_id) if supervisor is not None else None
    if active_cell is not None:
        return signal_scope_from_agent_scope(active_cell.scope)
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
    scope = diagnostics.get("agent_run_scope")
    scope_payload = dict(scope or {}) if isinstance(scope, dict) else {}
    return RuntimeSignalScope(
        session_id=str(getattr(task_run, "session_id", "") or scope_payload.get("session_id") or ""),
        task_run_id=str(task_run_id or ""),
        agent_run_id=str(scope_payload.get("agent_run_id") or diagnostics.get("agent_run_id") or ""),
        run_cell_id=str(scope_payload.get("run_cell_id") or diagnostics.get("run_cell_id") or ""),
        turn_id=str(scope_payload.get("turn_id") or diagnostics.get("turn_id") or diagnostics.get("latest_interaction_turn_id") or ""),
        turn_run_id=str(scope_payload.get("turn_run_id") or diagnostics.get("turn_run_id") or ""),
    )


def _current_record(runtime_host: Any, *, task_run_id: str, executor_epoch: int) -> ExecutorEpochRecord | None:
    record = _registry(runtime_host).get(task_run_id)
    if record is None:
        return None
    if record.executor_epoch != int(executor_epoch or 0):
        return None
    return record


def _registry(runtime_host: Any) -> dict[str, ExecutorEpochRecord]:
    registry = getattr(runtime_host, "_task_run_execution_control", None)
    if isinstance(registry, dict):
        return registry
    registry = {}
    setattr(runtime_host, "_task_run_execution_control", registry)
    return registry


def _executor_epoch_from_task_run(task_run: Any) -> int:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
    try:
        return int(diagnostics.get("executor_epoch") or 0)
    except (TypeError, ValueError):
        return 0


def _latest_requested_control_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: ExecutorSignalKind,
    steer_ref: str = "",
) -> dict[str, Any] | None:
    event_log = getattr(runtime_host, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return None
    try:
        events = list_events(task_run_id)
    except Exception:
        return None
    expected_steer_ref = str(steer_ref or "").strip()
    for event in reversed(list(events or [])):
        signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
        if str(signal.get("signal_type") or "") != "control.signal.requested":
            continue
        payload = dict(signal.get("payload") or {})
        if str(payload.get("signal_kind") or "") != str(kind or ""):
            continue
        if expected_steer_ref and str(payload.get("steer_ref") or "") != expected_steer_ref:
            continue
        return {
            "signal_id": str(signal.get("signal_id") or ""),
            "control_event_ref": str(getattr(event, "event_id", "") or ""),
            "payload": payload,
        }
    return None


def _target_unavailable_already_recorded(
    runtime_host: Any,
    *,
    task_run_id: str,
    requested_signal_id: str,
    unavailable_reason: str,
) -> bool:
    event_log = getattr(runtime_host, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return False
    try:
        events = list_events(task_run_id)
    except Exception:
        return False
    normalized_signal_id = str(requested_signal_id or "").strip()
    normalized_reason = str(unavailable_reason or "").strip()
    for event in events or []:
        signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
        if str(signal.get("signal_type") or "") != "control.signal.target_unavailable":
            continue
        payload = dict(signal.get("payload") or {})
        if str(payload.get("requested_signal_id") or "") != normalized_signal_id:
            continue
        if normalized_reason and str(payload.get("unavailable_reason") or "") != normalized_reason:
            continue
        return True
    return False


def _control_signal_is_closed(runtime_host: Any, *, task_run_id: str, signal_id: str) -> bool:
    event_log = getattr(runtime_host, "event_log", None)
    list_events = getattr(event_log, "list_events", None)
    if not callable(list_events):
        return False
    normalized_signal_id = str(signal_id or "").strip()
    if not normalized_signal_id:
        return False
    try:
        events = list_events(task_run_id)
    except Exception:
        return False
    for event in events or []:
        if str(getattr(event, "event_type", "") or "") not in {
            "runtime_control_signal_observed",
            "runtime_control_signal_consumed",
        }:
            continue
        signal = dict(dict(getattr(event, "payload", {}) or {}).get("signal") or {})
        if str(signal.get("signal_id") or "") == normalized_signal_id:
            return True
    return False


def _cancel_model_task(record: ExecutorEpochRecord, *, reason: str) -> None:
    task = record.model_task
    if task is None or task.done():
        return
    loop = record.model_loop
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(task.cancel, reason)
        return
    task.cancel()
