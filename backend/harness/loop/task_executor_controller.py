from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

from .task_run_execution_control import ExecutorControlSignal, ensure_executor_control_signal
from .task_run_recovery_state import recovery_state_for_task_run, should_auto_continue_task_run
from .work_rollout import append_work_rollout_item


class TaskExecutorController:
    """Owns TaskRun executor scheduling and recovery for the single-agent harness."""

    def __init__(
        self,
        *,
        runtime_host: Any,
        execute_task_run_callback: Any,
    ) -> None:
        self.runtime_host = runtime_host
        self.execute_task_run_callback = execute_task_run_callback

    def schedule(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        turn_id: str = "",
        max_steps: int = 50,
        recovered_from: str = "",
    ) -> dict[str, Any]:
        runtime_host = self.runtime_host
        task_run = runtime_host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="task_run_not_found",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if _is_session_deleted(runtime_host, task_run):
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="session_deleted",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if str(scheduler or "").strip() == "runtime_start_recovery":
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="runtime_start_recovery_does_not_auto_schedule",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if _is_task_run_executor_claimed(task_run):
            return _schedule_result(
                ok=True,
                scheduled=False,
                task_run_id=task_run_id,
                reason="already_running",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if not _is_task_run_executable(task_run):
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason=f"not_executable:{getattr(task_run, 'status', '')}",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        def _commit_scheduled(scope: Any, worker_backend: str) -> None:
            current = runtime_host.state_index.get_task_run(task_run_id) or task_run
            scope_payload = scope.to_dict() if hasattr(scope, "to_dict") else dict(scope or {})
            self._mark_scheduled(
                current,
                task_run_id=task_run_id,
                scheduler=scheduler,
                turn_id=turn_id,
                max_steps=max_steps,
                recovered_from=recovered_from,
                agent_scope=scope_payload,
                agent_run_id=str(scope_payload.get("agent_run_id") or ""),
                run_cell_id=str(scope_payload.get("run_cell_id") or ""),
                worker_backend=worker_backend,
            )

        supervisor_result = _agent_run_supervisor(runtime_host).schedule_task_run(
            task_run_id=task_run_id,
            work_factory=lambda: self._runner(task_run_id=task_run_id, scheduler=scheduler, max_steps=max_steps),
            scheduler=scheduler,
            max_steps=max_steps,
            recovered_from=recovered_from,
            turn_id=turn_id,
            on_scheduled=_commit_scheduled,
        )
        supervisor_reason = str(supervisor_result.get("reason") or "scheduled")
        if not bool(supervisor_result.get("ok")) and supervisor_reason == "worker_start_failed":
            self._mark_scheduled_task_failed(
                task_run_id=task_run_id,
                error=str(supervisor_result.get("error") or supervisor_reason),
                scheduler=scheduler,
                agent_run_id=str(supervisor_result.get("agent_run_id") or ""),
                run_cell_id=str(supervisor_result.get("run_cell_id") or ""),
                worker_backend=str(supervisor_result.get("worker_backend") or ""),
            )
        return _schedule_result(
            ok=bool(supervisor_result.get("ok")),
            scheduled=bool(supervisor_result.get("scheduled")),
            task_run_id=task_run_id,
            reason=supervisor_reason,
            scheduler=scheduler,
            agent_run_id=str(supervisor_result.get("agent_run_id") or ""),
            run_cell_id=str(supervisor_result.get("run_cell_id") or ""),
            worker_backend=str(supervisor_result.get("worker_backend") or ""),
            error=str(supervisor_result.get("error") or ""),
            recovered_from=recovered_from,
        )

    def recover_scheduled(
        self,
        task_run_id: str,
        *,
        scheduler: str,
        max_steps: int = 50,
        recovered_from: str = "scheduled_executor_claim",
    ) -> dict[str, Any]:
        runtime_host = self.runtime_host
        task_run = runtime_host.state_index.get_task_run(task_run_id)
        if task_run is None:
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="task_run_not_found",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if _is_session_deleted(runtime_host, task_run):
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="session_deleted",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if str(scheduler or "").strip() == "runtime_start_recovery":
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="runtime_start_recovery_does_not_auto_schedule",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        if not _is_task_run_executor_claimed(task_run):
            return self.schedule(
                task_run_id,
                scheduler=scheduler,
                max_steps=max_steps,
                recovered_from="",
            )
        executor_status = str(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_status") or "")
        if executor_status != "scheduled":
            return _schedule_result(
                ok=False,
                scheduled=False,
                task_run_id=task_run_id,
                reason="already_running",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        active_cell = _agent_run_supervisor(runtime_host).active_cell_for_task_run(task_run_id)
        if active_cell is not None:
            return _schedule_result(
                ok=True,
                scheduled=False,
                task_run_id=task_run_id,
                reason="already_running",
                scheduler=scheduler,
                agent_run_id=active_cell.scope.agent_run_id,
                run_cell_id=active_cell.scope.run_cell_id,
                worker_backend=active_cell.worker_backend.backend_name,
                recovered_from=recovered_from,
            )
        supervisor_result = _agent_run_supervisor(runtime_host).schedule_task_run(
            task_run_id=task_run_id,
            work_factory=lambda: self._runner(task_run_id=task_run_id, scheduler=scheduler, max_steps=max_steps),
            scheduler=scheduler,
            max_steps=max_steps,
            recovered_from=recovered_from,
        )
        return _schedule_result(
            ok=bool(supervisor_result.get("ok")),
            scheduled=bool(supervisor_result.get("scheduled")),
            task_run_id=task_run_id,
            reason=str(supervisor_result.get("reason") or "recovered_scheduled_executor"),
            scheduler=scheduler,
            agent_run_id=str(supervisor_result.get("agent_run_id") or ""),
            run_cell_id=str(supervisor_result.get("run_cell_id") or ""),
            worker_backend=str(supervisor_result.get("worker_backend") or ""),
            recovered_from=recovered_from,
        )

    def recover_interrupted_executor_leases(self) -> dict[str, Any]:
        recovered: list[str] = []
        skipped_graph_node_task_run_ids: list[str] = []
        user_controlled_interruption_task_run_ids: list[str] = []
        for task_run in self.runtime_host.state_index.list_task_runs():
            task_run_id = str(getattr(task_run, "task_run_id", "") or "")
            if _is_session_deleted(self.runtime_host, task_run):
                continue
            if not _is_single_agent_task_run(task_run):
                continue
            if _origin_kind(task_run) == "graph_node_assigned":
                skipped_graph_node_task_run_ids.append(task_run_id)
                continue
            diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
            runtime_control = diagnostics.get("runtime_control")
            control_state = str(runtime_control.get("state") or "").strip() if isinstance(runtime_control, dict) else ""
            if control_state in {"pause_requested", "paused", "stop_requested", "stopped", "replan_requested", "interrupted_for_replan"}:
                _ensure_user_controlled_interruption_signal_on_gateway(
                    self.runtime_host,
                    task_run=task_run,
                    control_state=control_state,
                    runtime_control=dict(runtime_control or {}) if isinstance(runtime_control, dict) else {},
                )
                user_controlled_interruption_task_run_ids.append(task_run_id)
                continue
            if not _is_task_run_executor_claimed(task_run):
                continue
            event = self.runtime_host.event_log.append(
                task_run_id,
                "task_run_executor_recovered_after_runtime_start",
                payload={
                    "task_run_id": task_run_id,
                    "previous_status": str(getattr(task_run, "status", "") or ""),
                    "previous_executor_status": str(dict(getattr(task_run, "diagnostics", {}) or {}).get("executor_status") or ""),
                },
                refs={"task_run_ref": task_run_id},
            )
            recovered_task = replace(
                task_run,
                status="waiting_executor",
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                terminal_reason="",
                diagnostics={
                    **_strip_terminal_diagnostics(diagnostics),
                    "executor_status": "waiting_executor",
                    "wait_reason": "task_executor_interrupted_by_runtime_restart",
                    "latest_step": "task_executor_recovered_after_runtime_start",
                    "latest_step_status": "waiting_executor",
                    "latest_step_summary": "后端运行时已重启，当前工作已恢复为可继续状态。",
                    "latest_public_progress_note": "后端运行时已重启，当前工作已恢复为可继续状态。",
                    "recoverable_error": {
                        "error_code": "task_executor_interrupted_by_runtime_restart",
                        "retryable": True,
                        "user_message": "后端运行时已重启，任务可以继续续跑。",
                    },
                    "recovery_action": "rerun_task_executor",
                },
            )
            self.runtime_host.state_index.upsert_task_run(recovered_task)
            append_work_rollout_item(
                self.runtime_host,
                task_run=recovered_task,
                item_type="interrupted_boundary",
                title="恢复断点",
                status="waiting_executor",
                summary="后端运行时已重启，当前工作已恢复为可继续状态。",
                event_offset=event.offset,
                refs={"task_run_ref": task_run_id},
                payload={"terminal_reason": "task_executor_interrupted_by_runtime_restart"},
            )
            recovered.append(task_run_id)
        return {
            "recovered_count": len(recovered),
            "task_run_ids": recovered,
            "skipped_graph_node_task_run_ids": skipped_graph_node_task_run_ids,
            "user_controlled_interruption_task_run_ids": user_controlled_interruption_task_run_ids,
            "authority": "harness.loop.task_executor_controller.runtime_start_recovery",
        }

    async def _runner(self, *, task_run_id: str, scheduler: str, max_steps: int) -> None:
        try:
            while True:
                result = await self.execute_task_run_callback(task_run_id, max_steps=max_steps)
                payload = dict(result or {}) if isinstance(result, dict) else {}
                if not _should_auto_continue(self.runtime_host, task_run_id=task_run_id, result=payload):
                    return
                self.runtime_host.event_log.append(
                    task_run_id,
                    "task_run_executor_rescheduled",
                    payload={
                        "task_run_id": task_run_id,
                        "reason": str(payload.get("error") or "waiting_executor"),
                        "scheduler": scheduler,
                    },
                    refs={"task_run_ref": task_run_id},
                )
                await asyncio.sleep(0)
        except Exception as exc:
            self._mark_scheduled_task_failed(
                task_run_id=task_run_id,
                error=str(exc) or exc.__class__.__name__,
                scheduler=scheduler,
            )

    def _mark_scheduled(
        self,
        task_run: Any,
        *,
        task_run_id: str,
        scheduler: str,
        turn_id: str,
        max_steps: int,
        recovered_from: str,
        agent_scope: dict[str, Any] | None = None,
        agent_run_id: str = "",
        run_cell_id: str = "",
        worker_backend: str = "",
    ) -> None:
        scope_payload = dict(agent_scope or {}) if isinstance(agent_scope, dict) else {}
        normalized_agent_run_id = str(agent_run_id or scope_payload.get("agent_run_id") or "").strip()
        normalized_run_cell_id = str(run_cell_id or scope_payload.get("run_cell_id") or "").strip()
        normalized_worker_backend = str(worker_backend or "").strip()
        identity_payload = {
            **({"agent_scope": scope_payload} if scope_payload else {}),
            **({"agent_run_id": normalized_agent_run_id} if normalized_agent_run_id else {}),
            **({"run_cell_id": normalized_run_cell_id} if normalized_run_cell_id else {}),
            **({"worker_backend": normalized_worker_backend} if normalized_worker_backend else {}),
        }
        identity_refs = {
            **({"agent_run_ref": normalized_agent_run_id} if normalized_agent_run_id else {}),
            **({"run_cell_ref": normalized_run_cell_id} if normalized_run_cell_id else {}),
        }
        scheduled_event = self.runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_scheduled",
            payload={
                "task_run_id": task_run_id,
                "max_steps": max_steps,
                "scheduler": scheduler,
                **({"turn_id": turn_id} if turn_id else {}),
                **({"recovered_from": recovered_from} if recovered_from else {}),
                **identity_payload,
            },
            refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {}), **identity_refs},
        )
        progress_summary = ""
        progress_event = self.runtime_host.event_log.append(
            task_run_id,
            "step_summary_recorded",
            payload={
                "step": "task_executor_scheduled",
                "status": "running",
                "summary": progress_summary,
                "visibility": "internal",
                "presentation_source": "conversation_task_schedule",
                **identity_payload,
            },
            refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {}), **identity_refs},
        )
        self.runtime_host.state_index.upsert_task_run(
            replace(
                task_run,
                status="running",
                updated_at=progress_event.created_at or scheduled_event.created_at or time.time(),
                latest_event_offset=progress_event.offset,
                terminal_reason="",
                diagnostics={
                    **dict(task_run.diagnostics or {}),
                    "executor_status": "scheduled",
                    "executor_lease_state": "scheduled",
                    "latest_step": "task_executor_scheduled",
                    "latest_step_status": "running",
                    "latest_step_summary": progress_summary,
                    "latest_public_progress_note": progress_summary,
                    **({"latest_interaction_turn_id": turn_id} if turn_id else {}),
                    **({"executor_scheduler": scheduler} if scheduler else {}),
                    **({"executor_recovered_from": recovered_from} if recovered_from else {}),
                    **({"agent_run_scope": scope_payload} if scope_payload else {}),
                    **({"agent_run_id": normalized_agent_run_id} if normalized_agent_run_id else {}),
                    **({"run_cell_id": normalized_run_cell_id} if normalized_run_cell_id else {}),
                    **({"agent_cell_worker_backend": normalized_worker_backend} if normalized_worker_backend else {}),
                },
            )
        )

    def _mark_scheduled_task_failed(
        self,
        *,
        task_run_id: str,
        error: str,
        scheduler: str,
        agent_run_id: str = "",
        run_cell_id: str = "",
        worker_backend: str = "",
    ) -> None:
        identity_payload = {
            **({"agent_run_id": agent_run_id} if agent_run_id else {}),
            **({"run_cell_id": run_cell_id} if run_cell_id else {}),
            **({"worker_backend": worker_backend} if worker_backend else {}),
        }
        identity_refs = {
            **({"agent_run_ref": agent_run_id} if agent_run_id else {}),
            **({"run_cell_ref": run_cell_id} if run_cell_id else {}),
        }
        event = self.runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_schedule_failed",
            payload={"task_run_id": task_run_id, "error": error, "scheduler": scheduler, **identity_payload},
            refs={"task_run_ref": task_run_id, **identity_refs},
        )
        current = self.runtime_host.state_index.get_task_run(task_run_id)
        if current is None:
            return
        diagnostics = dict(current.diagnostics or {})
        for stale_key in (
            "agent_run_scope",
            "agent_run_id",
            "run_cell_id",
            "agent_cell_status",
            "agent_cell_scheduler",
            "agent_cell_max_steps",
            "agent_cell_recovered_from",
            "agent_cell_worker_backend",
        ):
            diagnostics.pop(stale_key, None)
        self.runtime_host.state_index.upsert_task_run(
            replace(
                current,
                status="blocked",
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                terminal_reason="task_executor_schedule_failed",
                diagnostics={
                    **diagnostics,
                    "executor_status": "blocked",
                    "executor_lease_state": "blocked",
                    "latest_step": "task_executor_schedule_failed",
                    "latest_step_status": "blocked",
                    "latest_step_summary": f"继续处理时遇到调度失败：{error}",
                    "recoverable_error": {
                        "error_code": "task_executor_schedule_failed",
                        "retryable": True,
                        "detail": error,
                    },
                    "recovery_action": "rerun_task_executor",
                },
            )
        )


def _should_auto_continue(runtime_host: Any, *, task_run_id: str, result: dict[str, Any]) -> bool:
    if str(result.get("error") or "") not in {"task_execution_step_budget_exhausted", "user_interrupt_replan_required"}:
        return False
    if not bool(result.get("retryable")):
        return False
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        return False
    return should_auto_continue_task_run(task_run)


def _is_task_run_executable(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).executable


def _is_task_run_executor_claimed(task_run: Any) -> bool:
    return recovery_state_for_task_run(task_run).running_claimed


def _is_single_agent_task_run(task_run: Any) -> bool:
    return str(getattr(task_run, "execution_runtime_kind", "") or "") in {"single_agent_task", "subagent_task"}


def _is_session_deleted(runtime_host: Any, task_run: Any) -> bool:
    checker = getattr(getattr(runtime_host, "state_index", None), "is_session_deleted", None)
    if not callable(checker):
        return False
    try:
        return bool(checker(str(getattr(task_run, "session_id", "") or "")))
    except Exception:
        return False


def _agent_run_supervisor(runtime_host: Any) -> Any:
    supervisor = getattr(runtime_host, "agent_run_supervisor", None)
    if supervisor is None:
        raise RuntimeError("TaskExecutorController requires AgentRunSupervisor")
    return supervisor


def _ensure_user_controlled_interruption_signal_on_gateway(
    runtime_host: Any,
    *,
    task_run: Any,
    control_state: str,
    runtime_control: dict[str, Any],
) -> None:
    task_run_id = str(getattr(task_run, "task_run_id", "") or "")
    if not task_run_id:
        return
    if control_state in {"stop_requested", "stopped"}:
        kind = "stop"
    elif control_state in {"pause_requested", "paused"}:
        kind = "pause"
    elif control_state in {"replan_requested", "interrupted_for_replan"}:
        kind = "replan"
    else:
        return
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    signal = ensure_executor_control_signal(
        runtime_host,
        task_run_id=task_run_id,
        kind=kind,  # type: ignore[arg-type]
        reason=str(runtime_control.get("reason") or "runtime_start_recovery_user_controlled_interruption"),
        requested_by=str(runtime_control.get("requested_by") or "user"),
        steer_ref=str(runtime_control.get("steer_ref") or diagnostics.get("latest_user_steer_ref") or ""),
        unavailable_reason="runtime_start_recovery_user_controlled_interruption",
    )
    if signal is not None:
        _record_runtime_control_signal_ref(runtime_host, task_run=task_run, signal=signal)


def _record_runtime_control_signal_ref(runtime_host: Any, *, task_run: Any, signal: ExecutorControlSignal) -> None:
    signal_ref = str(getattr(signal, "signal_id", "") or "").strip()
    if not signal_ref:
        return
    task_run_id = str(getattr(task_run, "task_run_id", "") or getattr(signal, "task_run_id", "") or "").strip()
    if not task_run_id:
        return
    state_index = getattr(runtime_host, "state_index", None)
    get_task_run = getattr(state_index, "get_task_run", None)
    upsert_task_run = getattr(state_index, "upsert_task_run", None)
    if not callable(get_task_run) or not callable(upsert_task_run):
        return
    current = get_task_run(task_run_id) or task_run
    diagnostics = dict(getattr(current, "diagnostics", {}) or {})
    control = dict(diagnostics.get("runtime_control") or {}) if isinstance(diagnostics.get("runtime_control"), dict) else {}
    if str(control.get("runtime_control_signal_ref") or "").strip() == signal_ref:
        return
    event_ref = str(getattr(signal, "control_event_ref", "") or "").strip()
    diagnostics["runtime_control"] = {
        **control,
        "runtime_control_signal_ref": signal_ref,
        **({"runtime_control_event_ref": event_ref} if event_ref else {}),
    }
    upsert_task_run(replace(current, diagnostics=diagnostics))


def _origin_kind(task_run: Any) -> str:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    origin = dict(diagnostics.get("origin") or {})
    return str(origin.get("origin_kind") or diagnostics.get("origin_kind") or "").strip()


def _strip_terminal_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    for key in (
        "observation",
        "latest_step",
        "latest_step_status",
        "latest_step_summary",
        "terminal_reason",
        "action_request",
        "admission",
        "diagnostics",
        "recoverable_error",
        "recovery_action",
        "user_question",
    ):
        payload.pop(key, None)
    return payload


def _schedule_result(
    *,
    ok: bool,
    scheduled: bool,
    task_run_id: str,
    reason: str,
    scheduler: str,
    agent_run_id: str = "",
    run_cell_id: str = "",
    worker_backend: str = "",
    error: str = "",
    recovered_from: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "scheduled": scheduled,
        "task_run_id": task_run_id,
        "reason": reason,
        "scheduler": scheduler,
        "agent_run_id": agent_run_id,
        "run_cell_id": run_cell_id,
        "worker_backend": worker_backend,
        "error": error,
        "recovered_from": recovered_from,
    }
