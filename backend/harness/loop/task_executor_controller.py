from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

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
        self._mark_scheduled(
            task_run,
            task_run_id=task_run_id,
            scheduler=scheduler,
            turn_id=turn_id,
            max_steps=max_steps,
            recovered_from=recovered_from,
        )
        background_task_name = f"task-run-executor:{task_run_id}"
        runtime_host.spawn_background_task(
            self._runner(task_run_id=task_run_id, scheduler=scheduler, max_steps=max_steps),
            name=background_task_name,
        )
        return _schedule_result(
            ok=True,
            scheduled=True,
            task_run_id=task_run_id,
            reason="scheduled",
            scheduler=scheduler,
            background_task_name=background_task_name,
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
        if _background_task_running(runtime_host, f"task-run-executor:{task_run_id}") or _background_task_running(
            runtime_host,
            f"task-run-executor-recover:{task_run_id}",
        ):
            return _schedule_result(
                ok=True,
                scheduled=False,
                task_run_id=task_run_id,
                reason="already_running",
                scheduler=scheduler,
                recovered_from=recovered_from,
            )
        background_task_name = f"task-run-executor-recover:{task_run_id}"
        runtime_host.spawn_background_task(
            self._runner(task_run_id=task_run_id, scheduler=scheduler, max_steps=max_steps),
            name=background_task_name,
        )
        return _schedule_result(
            ok=True,
            scheduled=True,
            task_run_id=task_run_id,
            reason="recovered_scheduled_executor",
            scheduler=scheduler,
            background_task_name=background_task_name,
            recovered_from=recovered_from,
        )

    def recover_interrupted_executor_leases(self) -> dict[str, Any]:
        recovered: list[str] = []
        skipped_graph_node_task_run_ids: list[str] = []
        for task_run in self.runtime_host.state_index.list_task_runs():
            task_run_id = str(getattr(task_run, "task_run_id", "") or "")
            if _is_session_deleted(self.runtime_host, task_run):
                continue
            if not _is_single_agent_task_run(task_run):
                continue
            if _origin_kind(task_run) == "graph_node_assigned":
                skipped_graph_node_task_run_ids.append(task_run_id)
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
                terminal_reason="waiting_executor",
                diagnostics={
                    **_strip_terminal_diagnostics(dict(getattr(task_run, "diagnostics", {}) or {})),
                    "executor_status": "waiting_executor",
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
            "authority": "harness.loop.task_executor_controller.runtime_start_recovery",
        }

    def schedule_runtime_start_recovered_executors(
        self,
        task_run_ids: list[str] | tuple[str, ...] | set[str] | None = None,
        *,
        scheduler: str = "runtime_start_recovery",
        max_steps: int = 50,
    ) -> dict[str, Any]:
        requested_ids = [str(item or "").strip() for item in list(task_run_ids or []) if str(item or "").strip()]
        candidate_ids = _dedupe_preserving_order(
            [
                *requested_ids,
                *[
                    str(getattr(task_run, "task_run_id", "") or "").strip()
                    for task_run in self.runtime_host.state_index.list_task_runs()
                    if _is_runtime_start_recovery_breakpoint(task_run)
                ],
            ]
        )
        scheduled: list[str] = []
        skipped: list[dict[str, str]] = []
        schedule_results: list[dict[str, Any]] = []
        for task_run_id in candidate_ids:
            result = self.schedule(
                task_run_id,
                scheduler=scheduler,
                max_steps=max_steps,
                recovered_from="runtime_start_recovery",
            )
            schedule_results.append(result)
            if bool(result.get("ok")) and bool(result.get("scheduled")):
                scheduled.append(task_run_id)
            else:
                skipped.append(
                    {
                        "task_run_id": task_run_id,
                        "reason": str(result.get("reason") or "not_scheduled"),
                    }
                )
        return {
            "scheduled_count": len(scheduled),
            "scheduled_task_run_ids": scheduled,
            "skipped": skipped,
            "schedule_results": schedule_results,
            "authority": "harness.loop.task_executor_controller.runtime_start_scheduler",
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
    ) -> None:
        scheduled_event = self.runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_scheduled",
            payload={
                "task_run_id": task_run_id,
                "max_steps": max_steps,
                "scheduler": scheduler,
                **({"turn_id": turn_id} if turn_id else {}),
                **({"recovered_from": recovered_from} if recovered_from else {}),
            },
            refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {})},
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
            },
            refs={"task_run_ref": task_run_id, **({"turn_ref": turn_id} if turn_id else {})},
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
                    "latest_step": "task_executor_scheduled",
                    "latest_step_status": "running",
                    "latest_step_summary": progress_summary,
                    "latest_public_progress_note": progress_summary,
                    **({"latest_interaction_turn_id": turn_id} if turn_id else {}),
                    **({"executor_scheduler": scheduler} if scheduler else {}),
                    **({"executor_recovered_from": recovered_from} if recovered_from else {}),
                },
            )
        )

    def _mark_scheduled_task_failed(self, *, task_run_id: str, error: str, scheduler: str) -> None:
        event = self.runtime_host.event_log.append(
            task_run_id,
            "task_run_executor_schedule_failed",
            payload={"task_run_id": task_run_id, "error": error, "scheduler": scheduler},
            refs={"task_run_ref": task_run_id},
        )
        current = self.runtime_host.state_index.get_task_run(task_run_id)
        if current is None:
            return
        self.runtime_host.state_index.upsert_task_run(
            replace(
                current,
                status="blocked",
                updated_at=event.created_at,
                latest_event_offset=event.offset,
                terminal_reason="task_executor_schedule_failed",
                diagnostics={
                    **dict(current.diagnostics or {}),
                    "executor_status": "blocked",
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


def _is_runtime_start_recovery_breakpoint(task_run: Any) -> bool:
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    recoverable_error = diagnostics.get("recoverable_error")
    if not isinstance(recoverable_error, dict):
        recoverable_error = {}
    return (
        str(getattr(task_run, "status", "") or "") == "waiting_executor"
        and str(diagnostics.get("executor_status") or "") == "waiting_executor"
        and str(diagnostics.get("recovery_action") or "") == "rerun_task_executor"
        and str(recoverable_error.get("error_code") or "") == "task_executor_interrupted_by_runtime_restart"
    )


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


def _background_task_running(runtime_host: Any, name: str) -> bool:
    tasks_by_name = getattr(runtime_host, "_background_tasks_by_name", {})
    if not isinstance(tasks_by_name, dict):
        return False
    tasks = tasks_by_name.get(name, set())
    return any(not getattr(task, "done", lambda: True)() for task in list(tasks or []))


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


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _schedule_result(
    *,
    ok: bool,
    scheduled: bool,
    task_run_id: str,
    reason: str,
    scheduler: str,
    background_task_name: str = "",
    recovered_from: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "scheduled": scheduled,
        "task_run_id": task_run_id,
        "reason": reason,
        "scheduler": scheduler,
        "background_task_name": background_task_name,
        "recovered_from": recovered_from,
    }
