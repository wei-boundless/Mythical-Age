from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from harness.runtime.control_events import RuntimeSignalScope, signal_scope_from_agent_scope
from harness.runtime.runtime_gateway import CONTROL_SIGNAL_PUBLISHED_EVENT
from runtime.tool_runtime.tool_invocation_control import registry_for


RuntimeCellSignalKind = Literal["pause", "stop", "replan"]


@dataclass(frozen=True, slots=True)
class RuntimeCellControlSignal:
    kind: RuntimeCellSignalKind
    task_run_id: str
    reason: str
    requested_by: str
    requested_at: float
    steer_ref: str = ""
    signal_id: str = ""
    control_event_ref: str = ""


def runtime_cell_control_signal_effect(signal: RuntimeCellControlSignal) -> dict[str, Any]:
    return {
        "task_run_id": signal.task_run_id,
        "signal_kind": signal.kind,
        "runtime_control_signal_ref": signal.signal_id,
        "control_event_ref": signal.control_event_ref,
        "requested_by": signal.requested_by,
        "reason": signal.reason,
        "authority": "harness.loop.runtime_cell_control",
    }


def request_runtime_cell_control_signal(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: RuntimeCellSignalKind,
    reason: str = "",
    requested_by: str = "user",
    steer_ref: str = "",
    unavailable_reason: str = "target_cell_unavailable",
) -> RuntimeCellControlSignal | None:
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
    if task_run is None:
        return None
    requested_at = time.time()
    signal_id, control_event_ref = _publish_runtime_cell_control_signal_requested(
        runtime_host,
        task_run_id=task_run_id,
        kind=kind,
        reason=reason,
        requested_by=requested_by,
        requested_at=requested_at,
        steer_ref=steer_ref,
    )
    if not signal_id:
        return None
    signal = RuntimeCellControlSignal(
        kind=kind,
        task_run_id=task_run_id,
        reason=reason,
        requested_by=requested_by or "user",
        requested_at=requested_at,
        steer_ref=steer_ref,
        signal_id=signal_id,
        control_event_ref=control_event_ref,
    )
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    active_cell = _active_cell_for_task_run(runtime_host, task_run_id=task_run_id, session_id=session_id)
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
        return signal

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
    _publish_runtime_cell_control_signal_target_unavailable(
        runtime_host,
        task_run_id=task_run_id,
        scope=target_scope,
        signal_id=signal_id,
        control_event_ref=control_event_ref,
        kind=kind,
        reason=reason,
        requested_by=requested_by,
        requested_at=requested_at,
        steer_ref=steer_ref,
        unavailable_reason=unavailable_reason,
        host_registry_cancel_count=host_registry_cancel_count,
    )
    return signal


def _publish_runtime_cell_control_signal_requested(
    runtime_host: Any,
    *,
    task_run_id: str,
    kind: RuntimeCellSignalKind,
    reason: str,
    requested_by: str,
    requested_at: float,
    steer_ref: str = "",
) -> tuple[str, str]:
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    if not callable(getattr(runtime_gateway, "publish", None)):
        return "", ""
    scope = _runtime_signal_scope_for_task_run(runtime_host, task_run_id=task_run_id)
    try:
        event = runtime_gateway.publish(
            task_run_id,
            signal_type="control.signal.requested",
            scope=scope,
            source_authority="harness.loop.runtime_cell_control",
            payload={
                "signal_kind": kind,
                "task_run_id": task_run_id,
                "reason": str(reason or ""),
                "requested_by": str(requested_by or "user"),
                "requested_at": float(requested_at or 0.0),
                "steer_ref": str(steer_ref or ""),
                "adapter": "runtime_cell",
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


def _publish_runtime_cell_control_signal_target_unavailable(
    runtime_host: Any,
    *,
    task_run_id: str,
    scope: RuntimeSignalScope,
    signal_id: str,
    control_event_ref: str,
    kind: RuntimeCellSignalKind,
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
    runtime_gateway = getattr(runtime_host, "runtime_gateway", None)
    if not callable(getattr(runtime_gateway, "publish", None)):
        return None
    try:
        return runtime_gateway.publish(
            task_run_id,
            signal_type="control.signal.target_unavailable",
            scope=scope,
            source_authority="harness.loop.runtime_cell_control",
            payload={
                "requested_signal_id": normalized_signal_id,
                "requested_control_event_ref": str(control_event_ref or ""),
                "signal_kind": kind,
                "task_run_id": task_run_id,
                "reason": str(reason or ""),
                "requested_by": str(requested_by or "user"),
                "requested_at": float(requested_at or 0.0),
                "steer_ref": str(steer_ref or ""),
                "unavailable_reason": str(unavailable_reason or "target_cell_unavailable"),
                "target_agent_run_id": scope.agent_run_id,
                "target_run_cell_id": scope.run_cell_id,
                "host_registry_cancel_count": int(host_registry_cancel_count or 0),
                "pending_signal_remains_replayable": True,
                "adapter": "runtime_cell",
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


def _active_cell_for_task_run(runtime_host: Any, *, task_run_id: str, session_id: str) -> Any | None:
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    getter = getattr(supervisor, "active_cell_for_task_run", None)
    if not callable(getter):
        return None
    try:
        return getter(task_run_id, session_id=str(session_id or "").strip())
    except Exception:
        return None


def _runtime_signal_scope_for_task_run(runtime_host: Any, *, task_run_id: str) -> RuntimeSignalScope:
    task_run = getattr(getattr(runtime_host, "state_index", None), "get_task_run", lambda _task_run_id: None)(task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip() if task_run is not None else ""
    active_cell = _active_cell_for_task_run(runtime_host, task_run_id=task_run_id, session_id=session_id)
    if active_cell is not None:
        return signal_scope_from_agent_scope(active_cell.scope)
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
        if str(getattr(event, "event_type", "") or "") != CONTROL_SIGNAL_PUBLISHED_EVENT:
            continue
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
