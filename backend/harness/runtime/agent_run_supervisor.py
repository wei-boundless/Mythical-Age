from __future__ import annotations

from dataclasses import replace
import logging
import threading
import time
from typing import Any, Callable, Coroutine

from .agent_runtime_cell import AgentRuntimeCell
from .agent_scope import AgentInvocationKind, AgentRunScope, agent_scope_from_task_run, build_agent_run_scope
from .agent_worker_backend import AgentWorkerHandle, ThreadAgentWorkerBackend
from .runtime_gateway import RuntimeGateway
from .control_events import signal_scope_from_agent_scope


AsyncWorkFactory = Callable[[], Coroutine[Any, Any, Any]]
ScheduleCommittedCallback = Callable[[AgentRunScope, str], None]
logger = logging.getLogger(__name__)


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
        # This is intentionally a per-session ceiling. A busy session must not
        # consume the scheduler in a way that prevents another session from
        # receiving its own isolated runtime cell.
        self.max_active_cells = max(1, int(max_active_cells or 8))
        self._cells_by_id: dict[str, AgentRuntimeCell] = {}
        self._task_run_cells: dict[str, str] = {}
        self._runtime_run_cells: dict[str, str] = {}
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
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        with self._lock:
            self.supervise_cells()
            existing = self.active_cell_for_task_run(task_run_id, session_id=session_id)
            if existing is not None:
                return _supervisor_result(
                    ok=True,
                    scheduled=False,
                    reason="already_running",
                    task_run_id=task_run_id,
                    scope=existing.scope,
                    worker_backend=existing.worker_backend.backend_name,
                )
            scope = self._scope_for_task_run(task_run, turn_id=turn_id)
            if _is_primary_session_task_run(task_run):
                active_primary = self._active_primary_cell_for_session(
                    session_id,
                    excluding_task_run_id=task_run_id,
                )
                if active_primary is not None and not _is_current_turn_task_handoff(
                    self.runtime_host,
                    active_primary,
                    session_id=session_id,
                    task_run_id=task_run_id,
                    turn_id=turn_id or scope.turn_id,
                ):
                    self._publish_cell_event(
                        "agent_runtime_cell_backpressure",
                        scope,
                        payload={
                            "reason": "session_primary_task_active",
                            "active_task_run_id": active_primary.scope.task_run_id,
                            "active_agent_run_id": active_primary.scope.agent_run_id,
                            "active_run_cell_id": active_primary.scope.run_cell_id,
                            "session_id": session_id,
                        },
                    )
                    return _supervisor_result(
                        ok=False,
                        scheduled=False,
                        reason="session_primary_task_active",
                        task_run_id=task_run_id,
                        scope=scope,
                        worker_backend=self.worker_backend.backend_name,
                    )
            active_count = len(
                [
                    cell
                    for cell in self._cells_by_id.values()
                    if cell.scope.session_id == session_id and _counts_against_active_limit(cell)
                ]
            )
            if active_count >= self.max_active_cells:
                self._publish_cell_event(
                    "agent_runtime_cell_backpressure",
                    scope,
                    payload={
                        "reason": "max_session_active_cells_reached",
                        "session_id": session_id,
                        "active_count": active_count,
                        "max_active_cells_per_session": self.max_active_cells,
                    },
                )
                return _supervisor_result(
                    ok=False,
                    scheduled=False,
                    reason="max_session_active_cells_reached",
                    task_run_id=task_run_id,
                    scope=scope,
                    worker_backend=self.worker_backend.backend_name,
                )
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
                try:
                    self._on_cell_done(cell, handle)
                except Exception:
                    logger.exception(
                        "failed to finalize agent runtime cell",
                        extra={"run_cell_id": cell.scope.run_cell_id, "task_run_id": cell.scope.task_run_id},
                    )

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

    def schedule_single_turn(
        self,
        *,
        session_id: str,
        stream_run_id: str,
        work_factory: AsyncWorkFactory,
        scheduler: str,
        invocation_kind: AgentInvocationKind = "single_turn",
        primary: bool = True,
        turn_id: str = "",
        turn_run_id: str = "",
        on_done: Callable[[AgentRunScope, AgentWorkerHandle], None] | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        normalized_stream_run_id = str(stream_run_id or "").strip()
        if not normalized_session_id:
            return _supervisor_result(ok=False, scheduled=False, reason="session_id_missing", task_run_id="", stream_run_id=normalized_stream_run_id)
        if not normalized_stream_run_id:
            return _supervisor_result(ok=False, scheduled=False, reason="stream_run_id_missing", task_run_id="", stream_run_id="")
        with self._lock:
            self.supervise_cells()
            existing = self.active_cell_for_stream_run(normalized_stream_run_id, session_id=normalized_session_id)
            if existing is not None:
                return _supervisor_result(
                    ok=True,
                    scheduled=False,
                    reason="already_running",
                    task_run_id="",
                    stream_run_id=normalized_stream_run_id,
                    scope=existing.scope,
                    worker_backend=existing.worker_backend.backend_name,
                )
            scope = self._scope_for_single_turn_run(
                session_id=normalized_session_id,
                stream_run_id=normalized_stream_run_id,
                invocation_kind=invocation_kind,
                turn_id=turn_id,
                turn_run_id=turn_run_id,
            )
            if primary:
                active_primary = self._active_primary_cell_for_session(normalized_session_id)
                if active_primary is not None:
                    self._publish_cell_event(
                        "agent_runtime_cell_backpressure",
                        scope,
                        payload={
                            "reason": "session_primary_task_active",
                            "active_invocation_kind": active_primary.scope.invocation_kind,
                            "active_task_run_id": active_primary.scope.task_run_id,
                            "active_turn_run_id": active_primary.scope.turn_run_id,
                            "active_agent_run_id": active_primary.scope.agent_run_id,
                            "active_run_cell_id": active_primary.scope.run_cell_id,
                            "session_id": normalized_session_id,
                            "stream_run_id": normalized_stream_run_id,
                        },
                    )
                    return _supervisor_result(
                        ok=False,
                        scheduled=False,
                        reason="session_primary_task_active",
                        task_run_id="",
                        stream_run_id=normalized_stream_run_id,
                        scope=scope,
                        worker_backend=self.worker_backend.backend_name,
                    )
            active_count = len(
                [
                    cell
                    for cell in self._cells_by_id.values()
                    if cell.scope.session_id == normalized_session_id and _counts_against_active_limit(cell)
                ]
            )
            if active_count >= self.max_active_cells:
                self._publish_cell_event(
                    "agent_runtime_cell_backpressure",
                    scope,
                    payload={
                        "reason": "max_session_active_cells_reached",
                        "session_id": normalized_session_id,
                        "active_count": active_count,
                        "max_active_cells_per_session": self.max_active_cells,
                        "stream_run_id": normalized_stream_run_id,
                    },
                )
                return _supervisor_result(
                    ok=False,
                    scheduled=False,
                    reason="max_session_active_cells_reached",
                    task_run_id="",
                    stream_run_id=normalized_stream_run_id,
                    scope=scope,
                    worker_backend=self.worker_backend.backend_name,
                )
            cell = AgentRuntimeCell(
                scope=scope,
                worker_backend=self.worker_backend,
                mailbox_overflow_handler=self._record_mailbox_overflow,
            )
            self._cells_by_id[scope.run_cell_id] = cell
            self._runtime_run_cells[normalized_stream_run_id] = scope.run_cell_id
            self._record_scope_on_runtime_run(
                stream_run_id=normalized_stream_run_id,
                scope=scope,
                scheduler=scheduler,
                primary=primary,
            )
            self._publish_cell_event(
                "agent_runtime_cell_created",
                scope,
                payload={"scheduler": scheduler, "stream_run_id": normalized_stream_run_id, "primary": bool(primary)},
            )

            def _done(handle: AgentWorkerHandle) -> None:
                try:
                    self._on_cell_done(cell, handle)
                except Exception:
                    logger.exception(
                        "failed to finalize agent runtime cell",
                        extra={"run_cell_id": cell.scope.run_cell_id, "stream_run_id": normalized_stream_run_id},
                    )
                if callable(on_done):
                    try:
                        on_done(cell.scope, handle)
                    except Exception:
                        logger.exception(
                            "failed to run agent runtime cell done callback",
                            extra={"run_cell_id": cell.scope.run_cell_id, "stream_run_id": normalized_stream_run_id},
                        )

            try:
                cell.start(work_factory, on_done=_done)
            except Exception as exc:
                if self._runtime_run_cells.get(normalized_stream_run_id) == scope.run_cell_id:
                    self._runtime_run_cells.pop(normalized_stream_run_id, None)
                self._cells_by_id.pop(scope.run_cell_id, None)
                cell.status = "failed"
                cell.completed_at = time.time()
                error = str(exc) or exc.__class__.__name__
                self._publish_cell_event(
                    "agent_runtime_cell_start_failed",
                    scope,
                    payload={"scheduler": scheduler, "worker_backend": cell.worker_backend.backend_name, "error": error, "stream_run_id": normalized_stream_run_id},
                )
                return _supervisor_result(
                    ok=False,
                    scheduled=False,
                    reason="worker_start_failed",
                    task_run_id="",
                    stream_run_id=normalized_stream_run_id,
                    scope=scope,
                    worker_backend=cell.worker_backend.backend_name,
                    error=error,
                )
            self._publish_cell_event(
                "agent_runtime_cell_started",
                scope,
                payload={"scheduler": scheduler, "worker_backend": cell.worker_backend.backend_name, "stream_run_id": normalized_stream_run_id},
            )
        return _supervisor_result(
            ok=True,
            scheduled=True,
            reason="scheduled",
            task_run_id="",
            stream_run_id=normalized_stream_run_id,
            scope=scope,
            worker_backend=cell.worker_backend.backend_name,
        )

    def active_cell_for_task_run(self, task_run_id: str, *, session_id: str) -> AgentRuntimeCell | None:
        run_cell_id = self._task_run_cells.get(str(task_run_id or ""))
        if not run_cell_id:
            return None
        cell = self._cells_by_id.get(run_cell_id)
        if cell is None or not cell.is_running():
            return None
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        if cell.scope.session_id != normalized_session_id:
            return None
        return cell

    def active_cell_for_stream_run(self, stream_run_id: str, *, session_id: str) -> AgentRuntimeCell | None:
        run_cell_id = self._runtime_run_cells.get(str(stream_run_id or ""))
        if not run_cell_id:
            return None
        cell = self._cells_by_id.get(run_cell_id)
        if cell is None or not cell.is_running():
            return None
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        if cell.scope.session_id != normalized_session_id:
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

    def current_scope_status_for_stream_run(
        self,
        stream_run_id: str,
        *,
        session_id: str,
        agent_run_id: str = "",
        run_cell_id: str = "",
    ) -> dict[str, Any]:
        normalized_stream_run_id = str(stream_run_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_agent_run_id = str(agent_run_id or "").strip()
        normalized_run_cell_id = str(run_cell_id or "").strip()
        if not normalized_stream_run_id:
            return _scope_status(accepted=False, reason="stream_run_id_missing")
        if not normalized_run_cell_id:
            return _scope_status(accepted=True, reason="run_cell_scope_unscoped")
        with self._lock:
            active_run_cell_id = self._runtime_run_cells.get(normalized_stream_run_id)
            active_cell = self._cells_by_id.get(str(active_run_cell_id or "")) if active_run_cell_id else None
            active_scope = active_cell.scope if active_cell is not None and active_cell.is_running() else None
        rejected_scope = {
            "session_id": normalized_session_id,
            "stream_run_id": normalized_stream_run_id,
            "agent_run_id": normalized_agent_run_id,
            "run_cell_id": normalized_run_cell_id,
        }
        if active_scope is None:
            return _scope_status(
                accepted=False,
                reason="active_cell_missing",
                rejected_scope=rejected_scope,
            )
        active_scope_payload = active_scope.to_dict()
        if normalized_session_id and normalized_session_id != active_scope.session_id:
            return _scope_status(
                accepted=False,
                reason="active_cell_missing_or_session_mismatch",
                active_scope=active_scope_payload,
                rejected_scope=rejected_scope,
            )
        if normalized_run_cell_id and normalized_run_cell_id != active_scope.run_cell_id:
            return _scope_status(
                accepted=False,
                reason="stale_run_cell",
                active_scope=active_scope_payload,
                rejected_scope=rejected_scope,
            )
        if normalized_agent_run_id and normalized_agent_run_id != active_scope.agent_run_id:
            return _scope_status(
                accepted=False,
                reason="stale_agent_run",
                active_scope=active_scope_payload,
                rejected_scope=rejected_scope,
            )
        return _scope_status(
            accepted=True,
            reason="current_agent_cell",
            active_scope=active_scope_payload,
            rejected_scope=rejected_scope,
        )

    def record_late_event_rejected(
        self,
        *,
        task_run_id: str = "",
        stream_run_id: str = "",
        session_id: str,
        event_log_run_id: str = "",
        agent_run_id: str = "",
        run_cell_id: str = "",
        event_kind: str = "agent_runtime_cell_event",
        reason: str = "stale_agent_cell",
        payload: dict[str, Any] | None = None,
        refs: dict[str, Any] | None = None,
        scope_status: dict[str, Any] | None = None,
    ) -> Any | None:
        normalized_task_run_id = str(task_run_id or "").strip()
        normalized_stream_run_id = str(stream_run_id or "").strip()
        normalized_event_log_run_id = str(event_log_run_id or "").strip()
        if not normalized_task_run_id and not normalized_stream_run_id and not normalized_event_log_run_id:
            return None
        if scope_status is not None:
            status = dict(scope_status or {})
        elif normalized_task_run_id:
            status = dict(
                self.current_scope_status_for_task_run(
                    normalized_task_run_id,
                    agent_run_id=agent_run_id,
                    run_cell_id=run_cell_id,
                )
            )
        else:
            status = dict(
                self.current_scope_status_for_stream_run(
                    normalized_stream_run_id,
                    session_id=session_id,
                    agent_run_id=agent_run_id,
                    run_cell_id=run_cell_id,
                )
            )
        task_run = self.runtime_host.state_index.get_task_run(normalized_task_run_id) if normalized_task_run_id else None
        normalized_session_id = str(session_id or getattr(task_run, "session_id", "") or "")
        rejected_scope = {
            "session_id": normalized_session_id,
            "task_run_id": normalized_task_run_id,
            "stream_run_id": normalized_stream_run_id,
            "agent_run_id": str(agent_run_id or "").strip(),
            "run_cell_id": str(run_cell_id or "").strip(),
        }
        event_payload = {
            "task_run_id": normalized_task_run_id,
            "stream_run_id": normalized_stream_run_id,
            "event_kind": str(event_kind or "agent_runtime_cell_event").strip(),
            "reason": str(reason or status.get("reason") or "stale_agent_cell").strip(),
            "scope_status": status,
            "rejected_scope": rejected_scope,
            "payload": dict(payload or {}),
            "authority": "harness.runtime.agent_run_supervisor.current_cell_gate",
        }
        event_run_id = normalized_event_log_run_id or normalized_task_run_id or normalized_stream_run_id
        return self.runtime_host.event_log.append(
            event_run_id,
            "agent_runtime_cell_late_event_rejected",  # type: ignore[arg-type]
            payload=event_payload,
            refs={
                **dict(refs or {}),
                **({"task_run_ref": normalized_task_run_id} if normalized_task_run_id else {}),
                **({"stream_run_ref": normalized_stream_run_id} if normalized_stream_run_id else {}),
                "agent_run_ref": rejected_scope["agent_run_id"],
                "run_cell_ref": rejected_scope["run_cell_id"],
            },
        )

    def cancel_task_run(
        self,
        task_run_id: str,
        *,
        session_id: str = "",
        reason: str = "task_run_cancelled",
    ) -> bool:
        with self._lock:
            cell = self.active_cell_for_task_run(task_run_id, session_id=session_id)
        if cell is None:
            return False
        self._publish_cell_event("agent_runtime_cell_cancel_requested", cell.scope, payload={"reason": reason})
        return cell.request_cancel(reason)

    def cancel_stream_run(
        self,
        stream_run_id: str,
        *,
        session_id: str = "",
        reason: str = "stream_run_cancelled",
    ) -> bool:
        with self._lock:
            cell = self.active_cell_for_stream_run(stream_run_id, session_id=session_id)
        if cell is None:
            return False
        self._publish_cell_event(
            "agent_runtime_cell_cancel_requested",
            cell.scope,
            payload={"reason": reason, "stream_run_id": str(stream_run_id or "").strip()},
        )
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
            "max_active_cells_per_session": self.max_active_cells,
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
            stream_run_id = _stream_run_id_from_scope(cell.scope)
            if stream_run_id and self._runtime_run_cells.get(stream_run_id) == cell.scope.run_cell_id:
                self._runtime_run_cells.pop(stream_run_id, None)

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

    def _record_scope_on_runtime_run(
        self,
        *,
        stream_run_id: str,
        scope: AgentRunScope,
        scheduler: str,
        primary: bool,
    ) -> None:
        registry = getattr(self.runtime_host, "run_registry", None)
        if registry is None:
            return
        update = getattr(registry, "update_run", None)
        if not callable(update):
            return
        try:
            update(
                str(stream_run_id or "").strip(),
                diagnostics={
                    "agent_run_scope": scope.to_dict(),
                    "agent_run_id": scope.agent_run_id,
                    "run_cell_id": scope.run_cell_id,
                    "agent_cell_status": "scheduled",
                    "agent_cell_scheduler": scheduler,
                    "agent_cell_primary": bool(primary),
                    "runtime_turn_run_id": scope.turn_run_id,
                },
            )
        except Exception:
            return

    def _scope_for_task_run(self, task_run: Any, *, turn_id: str = "") -> AgentRunScope:
        agent_run = _canonical_agent_run_for_task_run(self.runtime_host, task_run)
        return agent_scope_from_task_run(
            task_run,
            turn_id=turn_id,
            agent_run_id=_scope_agent_run_id(task_run, agent_run=agent_run),
            parent_agent_run_id=_scope_parent_agent_run_id(task_run, agent_run=agent_run),
            invocation_kind=_scope_invocation_kind(task_run, agent_run=agent_run),
        )

    def _scope_for_single_turn_run(
        self,
        *,
        session_id: str,
        stream_run_id: str,
        invocation_kind: AgentInvocationKind,
        turn_id: str = "",
        turn_run_id: str = "",
    ) -> AgentRunScope:
        normalized_stream_run_id = str(stream_run_id or "").strip()
        normalized_invocation_kind = invocation_kind if invocation_kind in {"single_turn", "background"} else "single_turn"
        normalized_turn_run_id = str(turn_run_id or "").strip() or f"turnrun:{normalized_stream_run_id}"
        return build_agent_run_scope(
            session_id=session_id,
            invocation_kind=normalized_invocation_kind,
            turn_id=turn_id,
            turn_run_id=normalized_turn_run_id,
            agent_run_id=f"agrun:{normalized_invocation_kind}:{normalized_stream_run_id}",
        )

    def _active_primary_cell_for_session(
        self,
        session_id: str,
        *,
        excluding_task_run_id: str = "",
    ) -> AgentRuntimeCell | None:
        normalized_session_id = str(session_id or "").strip()
        excluded = str(excluding_task_run_id or "").strip()
        if not normalized_session_id:
            return None
        for cell in self._cells_by_id.values():
            if cell.scope.session_id != normalized_session_id:
                continue
            if excluded and cell.scope.task_run_id == excluded:
                continue
            if not cell.is_running():
                continue
            if _is_primary_runtime_cell(self.runtime_host, cell):
                return cell
        return None

def _supervisor_result(
    *,
    ok: bool,
    scheduled: bool,
    reason: str,
    task_run_id: str,
    stream_run_id: str = "",
    scope: AgentRunScope | None = None,
    worker_backend: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "scheduled": bool(scheduled),
        "task_run_id": str(task_run_id or ""),
        **({"stream_run_id": str(stream_run_id or "")} if str(stream_run_id or "").strip() else {}),
        "reason": str(reason or ""),
        **({"agent_run_id": scope.agent_run_id, "run_cell_id": scope.run_cell_id, "agent_scope": scope.to_dict()} if scope is not None else {}),
        **({"worker_backend": worker_backend} if worker_backend else {}),
        **({"error": error} if error else {}),
        "authority": "harness.runtime.agent_run_supervisor",
    }


def _is_current_turn_task_handoff(
    runtime_host: Any,
    active_primary: AgentRuntimeCell,
    *,
    session_id: str,
    task_run_id: str,
    turn_id: str,
) -> bool:
    scope = active_primary.scope
    normalized_session_id = str(session_id or "").strip()
    normalized_task_run_id = str(task_run_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if scope.invocation_kind != "single_turn":
        return False
    if not normalized_session_id or scope.session_id != normalized_session_id:
        return False
    if not normalized_turn_id or scope.turn_id != normalized_turn_id:
        return False
    if str(scope.task_run_id or "").strip():
        return False
    registry = getattr(runtime_host, "active_turn_registry", None)
    snapshot = getattr(registry, "snapshot", None)
    if not callable(snapshot):
        return False
    try:
        active_turn = snapshot(normalized_session_id)
    except Exception:
        return False
    if active_turn is None:
        return False
    return (
        str(getattr(active_turn, "turn_id", "") or "").strip() == normalized_turn_id
        and str(getattr(active_turn, "bound_task_run_id", "") or "").strip() == normalized_task_run_id
    )


def _counts_against_active_limit(cell: AgentRuntimeCell) -> bool:
    return bool(cell.is_running() and cell.status == "running")


def _canonical_agent_run_for_task_run(runtime_host: Any, task_run: Any) -> Any | None:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    if not task_run_id:
        return None
    list_runs = getattr(getattr(runtime_host, "state_index", None), "list_task_agent_runs", None)
    if not callable(list_runs):
        return None
    try:
        runs = list(list_runs(task_run_id) or [])
    except Exception:
        return None
    expected_id = f"agrun:{task_run_id}:main"
    for item in runs:
        if str(getattr(item, "agent_run_id", "") or "") == expected_id:
            return item
    if str(getattr(task_run, "execution_runtime_kind", "") or "") == "subagent_task":
        for item in runs:
            if str(getattr(item, "spawn_mode", "") or "") == "subagent":
                return item
    return runs[0] if runs else None


def _scope_agent_run_id(task_run: Any, *, agent_run: Any | None) -> str:
    explicit = str(getattr(agent_run, "agent_run_id", "") or "").strip() if agent_run is not None else ""
    if explicit:
        return explicit
    task_run_id = str(getattr(task_run, "task_run_id", "") or "").strip()
    return f"agrun:{task_run_id}:main" if task_run_id else ""


def _scope_parent_agent_run_id(task_run: Any, *, agent_run: Any | None) -> str:
    explicit = str(getattr(agent_run, "parent_agent_run_ref", "") or "").strip() if agent_run is not None else ""
    if explicit:
        return explicit
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    subagent_control = dict(diagnostics.get("subagent_control") or {}) if isinstance(diagnostics.get("subagent_control"), dict) else {}
    origin = dict(diagnostics.get("origin") or {}) if isinstance(diagnostics.get("origin"), dict) else {}
    return str(
        subagent_control.get("parent_agent_run_ref")
        or origin.get("parent_agent_run_ref")
        or diagnostics.get("parent_agent_run_ref")
        or ""
    ).strip()


def _scope_invocation_kind(task_run: Any, *, agent_run: Any | None) -> AgentInvocationKind:
    if (
        str(getattr(task_run, "execution_runtime_kind", "") or "") == "subagent_task"
        or str(getattr(agent_run, "spawn_mode", "") or "") == "subagent"
    ):
        return "subagent"
    return "task_run"


def _is_primary_session_task_run(task_run: Any) -> bool:
    if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    origin = dict(diagnostics.get("origin") or {}) if isinstance(diagnostics.get("origin"), dict) else {}
    origin_kind = str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()
    if origin_kind == "graph_node_assigned":
        return False
    if diagnostics.get("graph_run_id") or diagnostics.get("graph_config_id") or diagnostics.get("graph_node_id"):
        return False
    if diagnostics.get("subagent_control"):
        return False
    return True


def _is_primary_runtime_cell(runtime_host: Any, cell: AgentRuntimeCell) -> bool:
    if cell.scope.invocation_kind == "single_turn":
        return True
    if cell.scope.invocation_kind != "task_run":
        return False
    task_run = runtime_host.state_index.get_task_run(cell.scope.task_run_id)
    return bool(task_run is not None and _is_primary_session_task_run(task_run))


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
    if status in {"completed", "failed", "blocked", "aborted"}:
        return f"task_run_terminal:{status}"
    if cell.scope.invocation_kind in {"single_turn", "background"}:
        stream_run_id = _stream_run_id_from_scope(cell.scope)
        run = runtime_host.run_registry.get_run(stream_run_id) if stream_run_id else None
        if stream_run_id and run is None:
            return "runtime_run_missing"
        run_status = str(getattr(run, "status", "") or "").strip() if run is not None else ""
        if run_status in {"completed", "failed", "stopped", "orphaned"}:
            return f"runtime_run_terminal:{run_status}"
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


def _stream_run_id_from_scope(scope: AgentRunScope) -> str:
    turn_run_id = str(scope.turn_run_id or "").strip()
    if turn_run_id.startswith("turnrun:"):
        candidate = turn_run_id[len("turnrun:"):]
        if candidate.startswith("strun:"):
            return candidate
    return ""
