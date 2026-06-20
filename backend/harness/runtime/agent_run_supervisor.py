from __future__ import annotations

from dataclasses import replace
import threading
import time
from typing import Any, Callable, Coroutine

from .agent_runtime_cell import AgentRuntimeCell
from .agent_scope import AgentRunScope, agent_scope_from_task_run
from .agent_worker_backend import AgentWorkerHandle, ThreadAgentWorkerBackend
from .runtime_gateway import RuntimeGateway
from .control_events import signal_scope_from_agent_scope


AsyncWorkFactory = Callable[[], Coroutine[Any, Any, Any]]
ScheduleCommittedCallback = Callable[[AgentRunScope, str], None]


class AgentRunSupervisor:
    """Owns AgentRuntimeCell lifecycle and isolation.

    The supervisor routes work to cells and records lifecycle events. It does
    not decide user intent, authorize tools, execute tool bodies, or commit
    assistant output.
    """

    def __init__(
        self,
        *,
        runtime_host: Any,
        runtime_gateway: RuntimeGateway,
        worker_backend: Any | None = None,
        max_active_cells: int = 8,
    ) -> None:
        self.runtime_host = runtime_host
        self.runtime_gateway = runtime_gateway
        self.worker_backend = worker_backend or ThreadAgentWorkerBackend()
        self.max_active_cells = max(1, int(max_active_cells or 8))
        self._cells_by_id: dict[str, AgentRuntimeCell] = {}
        self._task_run_cells: dict[str, str] = {}
        self._lock = threading.RLock()

    def schedule_task_run(
        self,
        *,
        task_run_id: str,
        work_factory: AsyncWorkFactory,
        scheduler: str,
        max_steps: int,
        recovered_from: str = "",
        turn_id: str = "",
        on_scheduled: ScheduleCommittedCallback | None = None,
    ) -> dict[str, Any]:
        task_run = self.runtime_host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return _supervisor_result(ok=False, scheduled=False, reason="task_run_not_found", task_run_id=task_run_id)
        with self._lock:
            self.supervise_cells()
            existing = self.active_cell_for_task_run(task_run_id)
            if existing is not None:
                return _supervisor_result(
                    ok=True,
                    scheduled=False,
                    reason="already_running",
                    task_run_id=task_run_id,
                    scope=existing.scope,
                    worker_backend=existing.worker_backend.backend_name,
                )
            active_count = len([cell for cell in self._cells_by_id.values() if _counts_against_active_limit(cell)])
            if active_count >= self.max_active_cells:
                scope = agent_scope_from_task_run(task_run, turn_id=turn_id)
                self._publish_cell_event(
                    "agent_runtime_cell_backpressure",
                    scope,
                    payload={
                        "reason": "max_active_cells_reached",
                        "active_count": active_count,
                        "max_active_cells": self.max_active_cells,
                    },
                )
                return _supervisor_result(
                    ok=False,
                    scheduled=False,
                    reason="max_active_cells_reached",
                    task_run_id=task_run_id,
                    scope=scope,
                    worker_backend=self.worker_backend.backend_name,
                )
            scope = agent_scope_from_task_run(task_run, turn_id=turn_id)
            cell = AgentRuntimeCell(
                scope=scope,
                worker_backend=self.worker_backend,
                mailbox_overflow_handler=self._record_mailbox_overflow,
            )
            self._cells_by_id[scope.run_cell_id] = cell
            self._task_run_cells[task_run_id] = scope.run_cell_id
            self._record_scope_on_task_run(
                task_run,
                scope,
                scheduler=scheduler,
                max_steps=max_steps,
                recovered_from=recovered_from,
                turn_id=turn_id,
            )
            self._publish_cell_event(
                "agent_runtime_cell_created",
                scope,
                payload={"scheduler": scheduler, "max_steps": max_steps, "recovered_from": recovered_from},
            )
            if callable(on_scheduled):
                on_scheduled(scope, cell.worker_backend.backend_name)

            def _done(handle: AgentWorkerHandle) -> None:
                self._on_cell_done(cell, handle)

            try:
                cell.start(work_factory, on_done=_done)
            except Exception as exc:
                if self._task_run_cells.get(task_run_id) == scope.run_cell_id:
                    self._task_run_cells.pop(task_run_id, None)
                self._cells_by_id.pop(scope.run_cell_id, None)
                cell.status = "failed"
                cell.completed_at = time.time()
                error = str(exc) or exc.__class__.__name__
                self._publish_cell_event(
                    "agent_runtime_cell_start_failed",
                    scope,
                    payload={"scheduler": scheduler, "worker_backend": cell.worker_backend.backend_name, "error": error},
                )
                return _supervisor_result(
                    ok=False,
                    scheduled=False,
                    reason="worker_start_failed",
                    task_run_id=task_run_id,
                    scope=scope,
                    worker_backend=cell.worker_backend.backend_name,
                    error=error,
                )
            self._publish_cell_event(
                "agent_runtime_cell_started",
                scope,
                payload={"scheduler": scheduler, "worker_backend": cell.worker_backend.backend_name},
            )
        return _supervisor_result(
            ok=True,
            scheduled=True,
            reason="scheduled",
            task_run_id=task_run_id,
            scope=scope,
            worker_backend=cell.worker_backend.backend_name,
        )

    def active_cell_for_task_run(self, task_run_id: str) -> AgentRuntimeCell | None:
        run_cell_id = self._task_run_cells.get(str(task_run_id or ""))
        if not run_cell_id:
            return None
        cell = self._cells_by_id.get(run_cell_id)
        if cell is None or not cell.is_running():
            return None
        return cell

    def cell_by_id(self, run_cell_id: str) -> AgentRuntimeCell | None:
        return self._cells_by_id.get(str(run_cell_id or ""))

    def current_scope_status_for_task_run(
        self,
        task_run_id: str,
        *,
        agent_run_id: str = "",
        run_cell_id: str = "",
    ) -> dict[str, Any]:
        normalized_task_run_id = str(task_run_id or "").strip()
        normalized_agent_run_id = str(agent_run_id or "").strip()
        normalized_run_cell_id = str(run_cell_id or "").strip()
        if not normalized_task_run_id:
            return _scope_status(accepted=False, reason="task_run_id_missing")
        if not normalized_run_cell_id:
            return _scope_status(accepted=True, reason="run_cell_scope_unscoped")
        with self._lock:
            active_run_cell_id = self._task_run_cells.get(normalized_task_run_id)
            active_cell = self._cells_by_id.get(str(active_run_cell_id or "")) if active_run_cell_id else None
            active_scope = active_cell.scope if active_cell is not None and active_cell.is_running() else None
        if active_scope is None:
            return _scope_status(
                accepted=False,
                reason="active_cell_missing",
                rejected_scope={
                    "task_run_id": normalized_task_run_id,
                    "agent_run_id": normalized_agent_run_id,
                    "run_cell_id": normalized_run_cell_id,
                },
            )
        active_scope_payload = active_scope.to_dict()
        if normalized_run_cell_id and normalized_run_cell_id != active_scope.run_cell_id:
            return _scope_status(
                accepted=False,
                reason="stale_run_cell",
                active_scope=active_scope_payload,
                rejected_scope={
                    "task_run_id": normalized_task_run_id,
                    "agent_run_id": normalized_agent_run_id,
                    "run_cell_id": normalized_run_cell_id,
                },
            )
        if normalized_agent_run_id and normalized_agent_run_id != active_scope.agent_run_id:
            return _scope_status(
                accepted=False,
                reason="stale_agent_run",
                active_scope=active_scope_payload,
                rejected_scope={
                    "task_run_id": normalized_task_run_id,
                    "agent_run_id": normalized_agent_run_id,
                    "run_cell_id": normalized_run_cell_id,
                },
            )
        return _scope_status(
            accepted=True,
            reason="current_agent_cell",
            active_scope=active_scope_payload,
            rejected_scope={
                "task_run_id": normalized_task_run_id,
                "agent_run_id": normalized_agent_run_id,
                "run_cell_id": normalized_run_cell_id,
            },
        )

    def record_late_event_rejected(
        self,
        *,
        task_run_id: str,
        agent_run_id: str = "",
        run_cell_id: str = "",
        event_kind: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
        scope_status: dict[str, Any] | None = None,
    ) -> Any | None:
        normalized_task_run_id = str(task_run_id or "").strip()
        if not normalized_task_run_id:
            return None
        status = dict(scope_status or self.current_scope_status_for_task_run(
            normalized_task_run_id,
            agent_run_id=agent_run_id,
            run_cell_id=run_cell_id,
        ))
        task_run = self.runtime_host.state_index.get_task_run(normalized_task_run_id)
        session_id = str(getattr(task_run, "session_id", "") or "")
        rejected_scope = {
            "session_id": session_id,
            "task_run_id": normalized_task_run_id,
            "agent_run_id": str(agent_run_id or "").strip(),
            "run_cell_id": str(run_cell_id or "").strip(),
        }
        event_payload = {
            "task_run_id": normalized_task_run_id,
            "event_kind": str(event_kind or "agent_runtime_cell_event").strip(),
            "reason": str(reason or status.get("reason") or "stale_agent_cell").strip(),
            "scope_status": status,
            "rejected_scope": rejected_scope,
            "payload": dict(payload or {}),
            "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
        }
        return self.runtime_host.event_log.append(
            normalized_task_run_id,
            "agent_runtime_cell_late_event_rejected",  # type: ignore[arg-type]
            payload=event_payload,
            refs={
                **dict(refs or {}),
                "task_run_ref": normalized_task_run_id,
                "agent_run_ref": rejected_scope["agent_run_id"],
                "run_cell_ref": rejected_scope["run_cell_id"],
            },
        )

    def cancel_task_run(self, task_run_id: str, *, reason: str = "task_run_cancelled") -> bool:
        with self._lock:
            cell = self.active_cell_for_task_run(task_run_id)
        if cell is None:
            return False
        self._publish_cell_event("agent_runtime_cell_cancel_requested", cell.scope, payload={"reason": reason})
        return cell.request_cancel(reason)

    def supervise_cells(self, *, max_age_seconds: float = 0.0, now: float | None = None) -> dict[str, Any]:
        checked_at = time.time() if now is None else float(now or 0.0)
        timeout_seconds = max(0.0, float(max_age_seconds or 0.0))
        cancelled: list[dict[str, Any]] = []
        with self._lock:
            cells = list(self._cells_by_id.values())
        for cell in cells:
            if not cell.is_running() or cell.status != "running":
                continue
            reason = _cell_supervision_cancel_reason(
                self.runtime_host,
                cell,
                now=checked_at,
                max_age_seconds=timeout_seconds,
            )
            if not reason:
                continue
            self._publish_cell_event(
                "agent_runtime_cell_supervision_cancel_requested",
                cell.scope,
                payload={
                    "reason": reason,
                    "max_age_seconds": timeout_seconds,
                    "age_seconds": max(0.0, checked_at - float(cell.started_at or checked_at)),
                },
            )
            delivered = cell.request_cancel(reason)
            cancelled.append(
                {
                    "agent_run_id": cell.scope.agent_run_id,
                    "run_cell_id": cell.scope.run_cell_id,
                    "task_run_id": cell.scope.task_run_id,
                    "reason": reason,
                    "delivered": bool(delivered),
                }
            )
        return {
            "checked_at": checked_at,
            "max_age_seconds": timeout_seconds,
            "cancelled_count": len(cancelled),
            "cancelled": cancelled,
            "authority": "harness.runtime.agent_run_supervisor",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cells = [cell.to_dict() for cell in self._cells_by_id.values()]
        return {
            "authority": "harness.runtime.agent_run_supervisor",
            "max_active_cells": self.max_active_cells,
            "cells": cells,
        }

    def _on_cell_done(self, cell: AgentRuntimeCell, handle: AgentWorkerHandle) -> None:
        cell.mark_done(handle)
        event_type = "agent_runtime_cell_completed"
        payload: dict[str, Any] = {"worker_backend": cell.worker_backend.backend_name}
        if handle.cancelled or handle.cancel_delivered:
            event_type = "agent_runtime_cell_cancelled"
            payload["reason"] = handle.cancel_reason
        elif handle.error is not None:
            event_type = "agent_runtime_cell_failed"
            payload["error"] = str(handle.error or handle.error.__class__.__name__)
        self._publish_cell_event(event_type, cell.scope, payload=payload)
        with self._lock:
            if self._task_run_cells.get(cell.scope.task_run_id) == cell.scope.run_cell_id:
                self._task_run_cells.pop(cell.scope.task_run_id, None)

    def _publish_cell_event(self, event_type: str, scope: AgentRunScope, *, payload: dict[str, Any] | None = None) -> None:
        self.runtime_host.event_log.append(
            scope.task_run_id or scope.turn_run_id or scope.session_id,
            event_type,  # type: ignore[arg-type]
            payload={
                "agent_scope": scope.to_dict(),
                **dict(payload or {}),
            },
            refs={
                "agent_run_ref": scope.agent_run_id,
                "run_cell_ref": scope.run_cell_id,
                **({"task_run_ref": scope.task_run_id} if scope.task_run_id else {}),
            },
        )
        self.runtime_gateway.publish(
            scope.task_run_id or scope.turn_run_id or scope.session_id,
            signal_type=event_type,
            scope=signal_scope_from_agent_scope(scope),
            source_authority="harness.runtime.agent_run_supervisor",
            payload=payload or {},
            refs={"agent_run_ref": scope.agent_run_id, "run_cell_ref": scope.run_cell_id},
        )

    def _record_mailbox_overflow(self, scope: AgentRunScope, item: Any, details: dict[str, Any]) -> None:
        payload = {
            "reason": "mailbox_full",
            "dropped_item_type": str(getattr(item, "item_type", "") or ""),
            "dropped_item_id": str(getattr(item, "item_id", "") or ""),
            "queue_size": int(dict(details or {}).get("queue_size") or 0),
            "maxsize": int(dict(details or {}).get("maxsize") or 0),
            "dropped_count": int(dict(details or {}).get("dropped_count") or 0),
        }
        self._publish_cell_event(
            "agent_runtime_cell_mailbox_overloaded",
            scope,
            payload=payload,
        )

    def _record_scope_on_task_run(
        self,
        task_run: Any,
        scope: AgentRunScope,
        *,
        scheduler: str,
        max_steps: int,
        recovered_from: str,
        turn_id: str,
    ) -> None:
        current = self.runtime_host.state_index.get_task_run(scope.task_run_id) or task_run
        diagnostics = dict(getattr(current, "diagnostics", {}) or {})
        self.runtime_host.state_index.upsert_task_run(
            replace(
                current,
                diagnostics={
                    **diagnostics,
                    "agent_run_scope": scope.to_dict(),
                    "agent_run_id": scope.agent_run_id,
                    "run_cell_id": scope.run_cell_id,
                    "agent_cell_status": "scheduled",
                    "agent_cell_scheduler": scheduler,
                    "agent_cell_max_steps": max_steps,
                    **({"latest_interaction_turn_id": turn_id} if turn_id else {}),
                    **({"agent_cell_recovered_from": recovered_from} if recovered_from else {}),
                },
            )
        )

def _supervisor_result(
    *,
    ok: bool,
    scheduled: bool,
    reason: str,
    task_run_id: str,
    scope: AgentRunScope | None = None,
    worker_backend: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "scheduled": bool(scheduled),
        "task_run_id": str(task_run_id or ""),
        "reason": str(reason or ""),
        **({"agent_run_id": scope.agent_run_id, "run_cell_id": scope.run_cell_id, "agent_scope": scope.to_dict()} if scope is not None else {}),
        **({"worker_backend": worker_backend} if worker_backend else {}),
        **({"error": error} if error else {}),
        "authority": "harness.runtime.agent_run_supervisor",
    }


def _counts_against_active_limit(cell: AgentRuntimeCell) -> bool:
    return bool(cell.is_running() and cell.status == "running")


def _cell_supervision_cancel_reason(
    runtime_host: Any,
    cell: AgentRuntimeCell,
    *,
    now: float,
    max_age_seconds: float,
) -> str:
    task_run_id = str(cell.scope.task_run_id or "").strip()
    task_run = runtime_host.state_index.get_task_run(task_run_id) if task_run_id else None
    if task_run_id and task_run is None:
        return "task_run_missing"
    status = str(getattr(task_run, "status", "") or "").strip().lower() if task_run is not None else ""
    if status in {"completed", "failed", "blocked", "aborted", "cancelled", "canceled", "stopped"}:
        return f"task_run_terminal:{status}"
    if max_age_seconds > 0 and cell.started_at and float(now or 0.0) - float(cell.started_at or 0.0) > max_age_seconds:
        return "agent_cell_timeout"
    return ""


def _scope_status(
    *,
    accepted: bool,
    reason: str,
    active_scope: dict[str, Any] | None = None,
    rejected_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "accepted": bool(accepted),
        "reason": str(reason or ""),
        "active_scope": dict(active_scope or {}),
        "rejected_scope": dict(rejected_scope or {}),
        "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
    }
