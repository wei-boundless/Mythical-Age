from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from harness.loop.task_executor import (
    approve_task_run_tool_call,
    request_task_run_pause,
    resume_paused_task_run,
    stop_task_run,
)
from harness.runtime.task_record_lifecycle import (
    TaskRecordLifecycleConflict,
    TaskRecordLifecycleManager,
    TaskRecordLifecycleNotFound,
)

router = APIRouter()


class TaskRunExecuteRequest(BaseModel):
    max_steps: int = Field(default=12, ge=1, le=50)
    expected_active_turn_id: str = Field(default="", max_length=300)


class TaskRunControlRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    expected_active_turn_id: str = Field(default="", max_length=300)


class TaskRunApprovalRequest(TaskRunExecuteRequest):
    reason: str = Field(default="", max_length=500)


@router.get("/orchestration/harness/sessions/{session_id}/task-runs")
async def list_harness_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.list_session_traces(session_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}")
async def get_harness_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.harness_runtime.single_agent_runtime_host.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/orchestration/harness/turn-runs/{turn_run_id}")
async def get_harness_turn_trace(
    turn_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
    event_limit: int | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.harness_runtime.single_agent_runtime_host.get_turn_trace(
        turn_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
        event_limit=event_limit,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TurnRun trace not found")
    return trace


@router.post("/orchestration/harness/task-runs/{task_run_id}/execute")
async def execute_harness_task_run(
    task_run_id: str,
    payload: TaskRunExecuteRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if str(getattr(task_run, "execution_runtime_kind", "") or "") not in {"single_agent_task", "subagent_task"}:
        raise HTTPException(status_code=409, detail="not_single_agent_task_run")
    _assert_expected_active_turn(runtime_host, task_run_id, payload.expected_active_turn_id if payload is not None else "")
    max_steps = payload.max_steps if payload is not None else 12
    schedule_result = runtime.harness_runtime.schedule_or_recover_task_run_executor(
        task_run_id,
        scheduler="task_run_execute_api",
        max_steps=max_steps,
        recovered_from="scheduled_executor_claim",
    )
    if not _schedule_result_allows_progress(schedule_result):
        raise HTTPException(status_code=409, detail=_schedule_rejection_detail(schedule_result, fallback_status=str(getattr(task_run, "status", "") or "")))
    updated_task_run = runtime_host.state_index.get_task_run(task_run_id) or task_run
    return {
        "ok": True,
        "accepted": True,
        "background_started": bool(schedule_result.get("scheduled")),
        "task_run_id": task_run_id,
        "status": updated_task_run.status,
        "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
        "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
        **({"executor_already_running": True} if _schedule_result_already_running(schedule_result) else {}),
        **({"recovered_from": schedule_result.get("recovered_from")} if schedule_result.get("recovered_from") else {}),
    }


@router.post("/orchestration/harness/task-runs/{task_run_id}/pause")
async def pause_harness_task_run(
    task_run_id: str,
    payload: TaskRunControlRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    _assert_expected_active_turn(runtime_host, task_run_id, payload.expected_active_turn_id if payload is not None else "")
    result = request_task_run_pause(
        runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "",
        requested_by="user",
    )
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_pause_rejected"))
    return result


@router.post("/orchestration/harness/task-runs/{task_run_id}/resume")
async def resume_harness_task_run(
    task_run_id: str,
    payload: TaskRunExecuteRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    _assert_expected_active_turn(runtime_host, task_run_id, payload.expected_active_turn_id if payload is not None else "")
    result = resume_paused_task_run(runtime_host, task_run_id, requested_by="user")
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_resume_rejected"))
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    max_steps = payload.max_steps if payload is not None else 12
    schedule_result = runtime.harness_runtime.schedule_task_run_executor(
        task_run_id,
        scheduler="task_run_resume_api",
        max_steps=max_steps,
    )
    if not _schedule_result_allows_progress(schedule_result):
        raise HTTPException(status_code=409, detail=_schedule_rejection_detail(schedule_result, fallback_status=str(getattr(task_run, "status", "") or "")))
    updated_task_run = runtime_host.state_index.get_task_run(task_run_id) or task_run
    return {
        **result,
        "background_started": bool(schedule_result.get("scheduled")),
        **({"executor_already_running": True} if _schedule_result_already_running(schedule_result) else {}),
        "task_run_id": task_run_id,
        "status": updated_task_run.status,
        "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
        "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
    }


@router.post("/orchestration/harness/task-runs/{task_run_id}/approve-tool-call")
async def approve_harness_task_run_tool_call(
    task_run_id: str,
    payload: TaskRunApprovalRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    _assert_expected_active_turn(runtime_host, task_run_id, payload.expected_active_turn_id if payload is not None else "")
    approval_result = approve_task_run_tool_call(
        runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "",
        requested_by="user",
    )
    if approval_result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not approval_result.get("ok"):
        raise HTTPException(status_code=409, detail=str(approval_result.get("error") or "task_run_approval_rejected"))
    resume_result = resume_paused_task_run(
        runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "approved_tool_call",
        requested_by="user",
    )
    if not resume_result.get("ok"):
        raise HTTPException(status_code=409, detail=str(resume_result.get("error") or "task_run_resume_rejected"))
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    max_steps = payload.max_steps if payload is not None else 12
    schedule_result = runtime.harness_runtime.schedule_task_run_executor(
        task_run_id,
        scheduler="task_run_approval_resume_api",
        max_steps=max_steps,
    )
    if not _schedule_result_allows_progress(schedule_result):
        raise HTTPException(status_code=409, detail=_schedule_rejection_detail(schedule_result, fallback_status=str(getattr(task_run, "status", "") or "")))
    updated_task_run = runtime_host.state_index.get_task_run(task_run_id) or task_run
    return {
        **resume_result,
        "approval": approval_result,
        "background_started": bool(schedule_result.get("scheduled")),
        **({"executor_already_running": True} if _schedule_result_already_running(schedule_result) else {}),
        "task_run_id": task_run_id,
        "status": updated_task_run.status,
        "monitor_url": f"/api/orchestration/runtime-monitor/task-runs/{task_run_id}",
        "trace_url": f"/api/orchestration/harness/task-runs/{task_run_id}",
    }


@router.post("/orchestration/harness/task-runs/{task_run_id}/stop")
async def stop_harness_task_run(
    task_run_id: str,
    payload: TaskRunControlRequest | None = None,
) -> dict[str, Any]:
    runtime = require_runtime()
    runtime_host = runtime.harness_runtime.single_agent_runtime_host
    _assert_expected_active_turn(runtime_host, task_run_id, payload.expected_active_turn_id if payload is not None else "")
    result = stop_task_run(
        runtime_host,
        task_run_id,
        reason=payload.reason if payload is not None else "",
        requested_by="user",
    )
    if result.get("error") == "task_run_not_found":
        raise HTTPException(status_code=404, detail="TaskRun not found")
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "task_run_stop_rejected"))
    return result


@router.delete("/orchestration/harness/task-runs/{task_run_id}")
async def delete_harness_task_run(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        return await TaskRecordLifecycleManager(runtime).delete_task_record(task_run_id)
    except TaskRecordLifecycleNotFound as exc:
        raise HTTPException(status_code=404, detail="TaskRun not found") from exc
    except TaskRecordLifecycleConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": exc.reason,
                "task_run_id": exc.task_run_id,
                "graph_run_id": exc.graph_run_id,
            },
        ) from exc


def _assert_expected_active_turn(runtime_host: Any, task_run_id: str, expected_active_turn_id: str) -> None:
    expected = str(expected_active_turn_id or "").strip()
    if not expected:
        return
    active_turn = runtime_host.active_turn_registry.snapshot(_task_run_session_id(runtime_host, task_run_id))
    if active_turn is None:
        return
    if active_turn.turn_id != expected:
        raise HTTPException(status_code=409, detail="active_turn_mismatch")
    if active_turn.bound_task_run_id != task_run_id:
        raise HTTPException(status_code=409, detail="active_turn_task_run_mismatch")


def _task_run_session_id(runtime_host: Any, task_run_id: str) -> str:
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None:
        raise HTTPException(status_code=404, detail="TaskRun not found")
    return str(getattr(task_run, "session_id", "") or "")


def _schedule_rejection_detail(result: dict[str, Any], *, fallback_status: str = "") -> str:
    reason = str(result.get("reason") or "task_run_schedule_rejected")
    if reason == "already_running":
        return "task_run_executor_already_running"
    if reason.startswith("not_executable:"):
        status = reason.split(":", 1)[1] or fallback_status
        return f"task_run_not_executable:{status}"
    return reason


def _schedule_result_allows_progress(result: dict[str, Any]) -> bool:
    if not result.get("ok"):
        return False
    if result.get("scheduled"):
        return True
    return _schedule_result_already_running(result)


def _schedule_result_already_running(result: dict[str, Any]) -> bool:
    return str(result.get("reason") or "").strip() == "already_running"


@router.get("/orchestration/harness/task-runs/{task_run_id}/artifacts")
async def get_harness_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/harness/task-runs/{task_run_id}/memory-receipts")
async def get_harness_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.harness_runtime.single_agent_runtime_host.get_task_run_memory_receipts(task_run_id)


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.harness_runtime.single_agent_runtime_host.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status
