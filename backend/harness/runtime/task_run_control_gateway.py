from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from harness.loop.task_executor import (
    approve_task_run_tool_call,
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
)
from harness.loop.task_run_recovery_state import recovery_state_for_task_run
from harness.loop.task_tool_approval import matching_approval_grant_for_pending


ScheduleTaskRunExecutor = Callable[..., dict[str, Any]]


class TaskRunControlGateway:
    """Single entry point for user-facing TaskRun control intents."""

    authority = "harness.runtime.task_run_control_gateway"

    def __init__(
        self,
        *,
        runtime_host: Any,
        schedule_task_run_executor: ScheduleTaskRunExecutor | None,
    ) -> None:
        self.runtime_host = runtime_host
        self.schedule_task_run_executor = schedule_task_run_executor

    def resume_task_run(
        self,
        task_run_id: str,
        *,
        reason: str = "",
        requested_by: str = "user",
        turn_id: str = "",
        max_steps: int = 12,
        scheduler: str = "task_run_resume_api",
    ) -> dict[str, Any]:
        task_run = self._task_run(task_run_id)
        if task_run is None:
            return _not_found(task_run_id)
        preflight = self._preflight_user_control(task_run)
        if not preflight.get("ok"):
            return preflight
        recovery_state = recovery_state_for_task_run(task_run, runtime_host=self.runtime_host)
        if not recovery_state.same_run_resumable:
            return _conflict(
                task_run_id,
                f"task_run_not_resumable:{recovery_state.status or getattr(task_run, 'status', '')}",
                recovery_state=recovery_state,
            )
        if recovery_state.status == "waiting_approval" and matching_approval_grant_for_pending(task_run) is None:
            return _conflict(task_run_id, "task_run_waiting_approval_requires_grant", recovery_state=recovery_state)
        resume_result = resume_paused_task_run(
            self.runtime_host,
            task_run_id,
            reason=reason,
            requested_by=requested_by,
            turn_id=turn_id,
        )
        if not resume_result.get("ok"):
            return _from_worker_rejection(task_run_id, resume_result, phase="resume", recovery_state=recovery_state)
        return self._schedule_resumed_task_run(
            task_run_id,
            max_steps=max_steps,
            scheduler=scheduler,
            turn_id=turn_id,
            resume_result=resume_result,
        )

    def approve_tool_call_and_resume(
        self,
        task_run_id: str,
        *,
        reason: str = "",
        requested_by: str = "user",
        turn_id: str = "",
        max_steps: int = 12,
        scheduler: str = "task_run_approval_resume_api",
    ) -> dict[str, Any]:
        task_run = self._task_run(task_run_id)
        if task_run is None:
            return _not_found(task_run_id)
        preflight = self._preflight_user_control(task_run)
        if not preflight.get("ok"):
            return preflight
        approval_result = approve_task_run_tool_call(
            self.runtime_host,
            task_run_id,
            reason=reason,
            requested_by=requested_by,
            turn_id=turn_id,
        )
        if not approval_result.get("ok"):
            return _from_worker_rejection(task_run_id, approval_result, phase="approval")
        approved_task_run = self._task_run(task_run_id)
        if approved_task_run is None:
            return _not_found(task_run_id)
        recovery_state = recovery_state_for_task_run(approved_task_run, runtime_host=self.runtime_host)
        if matching_approval_grant_for_pending(approved_task_run) is None:
            return _conflict(task_run_id, "approval_grant_missing_after_approval", approval_result=approval_result)
        if not recovery_state.same_run_resumable:
            return _conflict(
                task_run_id,
                f"task_run_not_resumable:{recovery_state.status or getattr(approved_task_run, 'status', '')}",
                approval_result=approval_result,
                recovery_state=recovery_state,
            )
        resume_result = resume_paused_task_run(
            self.runtime_host,
            task_run_id,
            reason=reason or "approved_tool_call",
            requested_by=requested_by,
            turn_id=turn_id,
        )
        if not resume_result.get("ok"):
            return _from_worker_rejection(
                task_run_id,
                resume_result,
                phase="resume",
                approval_result=approval_result,
                recovery_state=recovery_state,
            )
        return self._schedule_resumed_task_run(
            task_run_id,
            max_steps=max_steps,
            scheduler=scheduler,
            turn_id=turn_id,
            resume_result=resume_result,
            approval_result=approval_result,
        )

    def pause_task_run(
        self,
        task_run_id: str,
        *,
        reason: str = "",
        requested_by: str = "user",
    ) -> dict[str, Any]:
        task_run = self._task_run(task_run_id)
        if task_run is None:
            return _not_found(task_run_id)
        preflight = self._preflight_user_control(task_run)
        if not preflight.get("ok"):
            return preflight
        result = request_task_run_pause(
            self.runtime_host,
            task_run_id,
            reason=reason,
            requested_by=requested_by,
        )
        if not result.get("ok"):
            return _from_worker_rejection(task_run_id, result, phase="pause")
        return {
            **dict(result or {}),
            "authority": self.authority,
        }

    def stop_task_run(
        self,
        task_run_id: str,
        *,
        reason: str = "",
        requested_by: str = "user",
    ) -> dict[str, Any]:
        task_run = self._task_run(task_run_id)
        if task_run is None:
            return _not_found(task_run_id)
        preflight = self._preflight_user_control(task_run)
        if not preflight.get("ok"):
            return preflight
        result = stop_task_run(
            self.runtime_host,
            task_run_id,
            reason=reason,
            requested_by=requested_by,
        )
        if not result.get("ok"):
            return _from_worker_rejection(task_run_id, result, phase="stop")
        return {
            **dict(result or {}),
            "authority": self.authority,
        }

    def _preflight_user_control(self, task_run: Any) -> dict[str, Any]:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        if str(getattr(task_run, "execution_runtime_kind", "") or "") not in {"single_agent_task", "subagent_task"}:
            return _conflict(task_run_id, "not_single_agent_task_run")
        recovery_state = recovery_state_for_task_run(task_run, runtime_host=self.runtime_host)
        if recovery_state.graph_controlled:
            return _conflict(task_run_id, "graph_node_task_run_controlled_by_graph_runtime", recovery_state=recovery_state)
        if recovery_state.stopped or recovery_state.completed_iteration:
            return _conflict(task_run_id, f"task_run_terminal:{recovery_state.reason}", recovery_state=recovery_state)
        return {"ok": True, "task_run_id": task_run_id, "recovery_state": _recovery_payload(recovery_state)}

    def _schedule_resumed_task_run(
        self,
        task_run_id: str,
        *,
        max_steps: int,
        scheduler: str,
        turn_id: str,
        resume_result: dict[str, Any],
        approval_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not callable(self.schedule_task_run_executor):
            return {
                **dict(resume_result or {}),
                "ok": False,
                "accepted": False,
                "task_run_id": task_run_id,
                "error": "task_run_scheduler_unavailable",
                "authority": self.authority,
                **({"approval": approval_result} if approval_result is not None else {}),
            }
        schedule_result = self.schedule_task_run_executor(
            task_run_id,
            scheduler=scheduler,
            turn_id=turn_id,
            max_steps=max_steps,
        )
        if not _schedule_result_allows_progress(schedule_result):
            return {
                **dict(resume_result or {}),
                "ok": False,
                "accepted": False,
                "task_run_id": task_run_id,
                "error": _schedule_rejection_detail(schedule_result),
                "schedule": dict(schedule_result or {}),
                "authority": self.authority,
                **({"approval": approval_result} if approval_result is not None else {}),
            }
        task_run = self._task_run(task_run_id)
        return {
            **dict(resume_result or {}),
            "ok": True,
            "accepted": True,
            "task_run_id": task_run_id,
            "status": str(getattr(task_run, "status", "") or ""),
            "background_started": bool(schedule_result.get("scheduled")),
            "schedule": dict(schedule_result or {}),
            "authority": self.authority,
            **({"executor_already_running": True} if _schedule_result_already_running(schedule_result) else {}),
            **({"approval": approval_result} if approval_result is not None else {}),
        }

    def _task_run(self, task_run_id: str) -> Any | None:
        return self.runtime_host.state_index.get_task_run(task_run_id)


def _from_worker_rejection(
    task_run_id: str,
    result: dict[str, Any],
    *,
    phase: str,
    approval_result: dict[str, Any] | None = None,
    recovery_state: Any | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "accepted": False,
        "task_run_id": task_run_id,
        "error": str(result.get("error") or f"task_run_{phase}_rejected"),
        phase: dict(result or {}),
        "authority": TaskRunControlGateway.authority,
        **({"approval": approval_result} if approval_result is not None else {}),
        **({"recovery_state": _recovery_payload(recovery_state)} if recovery_state is not None else {}),
    }


def _not_found(task_run_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "accepted": False,
        "task_run_id": task_run_id,
        "error": "task_run_not_found",
        "authority": TaskRunControlGateway.authority,
    }


def _conflict(task_run_id: str, error: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "accepted": False,
        "task_run_id": task_run_id,
        "error": error,
        "authority": TaskRunControlGateway.authority,
        **{
            key: (_recovery_payload(value) if key == "recovery_state" else value)
            for key, value in dict(extra or {}).items()
            if value is not None
        },
    }


def _recovery_payload(recovery_state: Any) -> dict[str, Any]:
    try:
        return asdict(recovery_state)
    except Exception:
        return {}


def _schedule_rejection_detail(result: dict[str, Any]) -> str:
    reason = str(dict(result or {}).get("reason") or "task_run_schedule_rejected")
    if reason == "already_running":
        return "task_run_executor_already_running"
    if reason.startswith("not_executable:"):
        status = reason.split(":", 1)[1]
        return f"task_run_not_executable:{status}"
    return reason


def _schedule_result_allows_progress(result: dict[str, Any]) -> bool:
    payload = dict(result or {})
    if not payload.get("ok"):
        return False
    if payload.get("scheduled"):
        return True
    return _schedule_result_already_running(payload)


def _schedule_result_already_running(result: dict[str, Any]) -> bool:
    return str(dict(result or {}).get("reason") or "").strip() == "already_running"
