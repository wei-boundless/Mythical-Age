from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import require_runtime
from runtime import TaskRun
from runtime.memory.project_supervision import make_supervision_record
from runtime.shared.models import CoordinationRun

router = APIRouter()


def _sse(event: str, data: dict[str, Any], *, event_id: str = "") -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


class TaskRunStopRequest(BaseModel):
    reason: str = Field(default="user_aborted", max_length=120)
    message: str = Field(default="", max_length=500)
    coordination_run_id: str = Field(default="", max_length=180)


class TaskRunApprovalRequest(BaseModel):
    decision: str = Field(..., min_length=1, max_length=40)
    message: str = Field(default="", max_length=500)


class TaskGraphMonitorEvaluateRequest(BaseModel):
    monitor_node_id: str = Field(default="", max_length=180)
    monitor_policy: dict[str, Any] = Field(default_factory=dict)


@router.get("/orchestration/runtime-loop/sessions/{session_id}/task-runs")
async def list_runtime_loop_task_runs(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_session_traces(session_id)


@router.get("/orchestration/runtime-loop/live-monitor")
async def list_runtime_loop_global_live_monitor(limit: int = 20) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_global_live_monitor(limit=limit)


@router.get("/orchestration/runtime-loop/monitor-events")
async def stream_runtime_loop_monitor_events(request: Request, limit: int = 40):
    runtime = require_runtime()
    task_run_loop = runtime.query_runtime.task_run_loop
    subscription = task_run_loop.event_log.subscribe()
    requested_limit = max(1, min(int(limit or 40), 100))

    async def event_generator():
        try:
            yield _sse(
                "runtime_monitor_snapshot",
                {
                    "monitor": task_run_loop.list_global_live_monitor(limit=requested_limit),
                    "source": "initial",
                },
            )
            while not await request.is_disconnected():
                try:
                    runtime_event = await asyncio.wait_for(subscription.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield _sse(
                        "runtime_monitor_heartbeat",
                        {
                            "updated_at": time.time(),
                            "source": "heartbeat",
                        },
                    )
                    continue
                monitor = task_run_loop.list_global_live_monitor(limit=requested_limit)
                yield _sse(
                    "runtime_monitor_event",
                    {
                        "runtime_event": runtime_event.to_dict(),
                        "monitor": monitor,
                        "source": "runtime_event_log",
                    },
                    event_id=runtime_event.event_id,
                )
        finally:
            task_run_loop.event_log.unsubscribe(subscription)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/orchestration/runtime-loop/sessions/{session_id}/live-monitor")
async def get_runtime_loop_session_live_monitor(session_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_session_live_monitor(session_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}")
async def get_runtime_loop_trace(
    task_run_id: str,
    include_payloads: bool = False,
    include_model_messages: bool = False,
) -> dict[str, Any]:
    runtime = require_runtime()
    trace = runtime.query_runtime.task_run_loop.get_trace(
        task_run_id,
        include_payloads=include_payloads,
        include_model_messages=include_model_messages,
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="TaskRun trace not found")
    return trace


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/live-monitor")
async def get_runtime_loop_task_run_live_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_run_live_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskRun live monitor not found")
    return monitor


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor")
async def get_runtime_loop_task_graph_run_monitor(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_task_graph_run_monitor(task_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return monitor


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/task-graph-monitor/evaluate")
async def evaluate_runtime_loop_task_graph_monitor(
    task_run_id: str,
    payload: TaskGraphMonitorEvaluateRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    evaluation = runtime.query_runtime.task_run_loop.evaluate_task_graph_monitor(
        task_run_id,
        monitor_node_id=payload.monitor_node_id.strip(),
        monitor_policy=dict(payload.monitor_policy or {}),
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="TaskGraph run monitor not found")
    return evaluation


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/monitor-decisions")
async def list_runtime_loop_task_graph_monitor_decisions(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.list_task_graph_monitor_decisions(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/artifacts")
async def get_runtime_loop_task_run_artifacts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_artifacts(task_run_id)


@router.get("/orchestration/runtime-loop/task-runs/{task_run_id}/memory-receipts")
async def get_runtime_loop_task_run_memory_receipts(task_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    return runtime.query_runtime.task_run_loop.get_task_run_memory_receipts(task_run_id)


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/approval")
async def resolve_runtime_loop_task_run_approval(
    task_run_id: str,
    payload: TaskRunApprovalRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    try:
        task_run = runtime.query_runtime.task_run_loop.state_index.get_task_run(task_run_id)
        result = await runtime.query_runtime.task_run_loop.resolve_pending_approval(
            task_run_id,
            decision=payload.decision,
            message=payload.message,
            tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
        )
        if task_run is not None:
            project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "").strip()
            session_id = str(getattr(task_run, "session_id", "") or "").strip()
            coordination_run_id = str(dict(task_run.diagnostics or {}).get("coordination_run_ref") or "").strip()
            if project_id and session_id:
                runtime.query_runtime.task_run_loop.state_index.upsert_supervision_record(
                    make_supervision_record(
                        project_id=project_id,
                        session_id=session_id,
                        task_run_id=task_run_id,
                        coordination_run_id=coordination_run_id,
                        issue_type="task_approval",
                        issue_summary=f"Task approval resolved as {payload.decision.strip().lower()}",
                        root_cause="approval_api",
                        repair_action=payload.decision.strip().lower(),
                        repair_result=str(result.get("diagnostics", {}).get("approval_resume_result", {}).get("executed") or ""),
                        followup_status="recorded",
                        diagnostics={
                            "message": payload.message.strip(),
                            "checkpoint_ref": str(result.get("checkpoint_ref") or ""),
                            "event_ref": str(result.get("event_ref") or ""),
                        },
                    )
                )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="TaskRun not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/orchestration/projects/{project_id}/runtime-status")
async def get_project_runtime_status(project_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    status = runtime.query_runtime.task_run_loop.get_project_runtime_status(project_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Project runtime status not found")
    return status


@router.post("/orchestration/runtime-loop/task-runs/{task_run_id}/stop")
async def stop_task_run(
    task_run_id: str,
    payload: TaskRunStopRequest,
) -> dict[str, Any]:
    try:
        runtime = require_runtime()
        task_run_loop = runtime.query_runtime.task_run_loop
        state_index = task_run_loop.state_index
        task_run = state_index.get_task_run(task_run_id)
        if task_run is None:
            raise HTTPException(status_code=404, detail="TaskRun not found")
        project_id = str(dict(task_run.diagnostics or {}).get("project_id") or "").strip()
        session_id = str(getattr(task_run, "session_id", "") or "").strip()
        coordination_run_id = payload.coordination_run_id.strip()
        coordination_run = (
            state_index.get_coordination_run(coordination_run_id)
            if coordination_run_id
            else None
        )
        checkpoint = task_run_loop.checkpoints.load_latest(task_run_id)
        if checkpoint is None:
            raise HTTPException(status_code=409, detail="TaskRun has no checkpoint to stop from")
        terminal_reason = "user_aborted" if payload.reason.strip() == "user_aborted" else payload.reason.strip() or "user_aborted"
        loop_state = checkpoint.loop_state.with_status(
            "aborted",
            transition="stop_after_final_output",
            terminal_reason=terminal_reason,
            diagnostics={
                **dict(checkpoint.loop_state.diagnostics),
                "stop_request": {
                    "reason": terminal_reason,
                    "message": payload.message.strip(),
                    "stopped_at": time.time(),
                },
            },
        )
        checkpoint_event = task_run_loop._write_checkpoint_event(loop_state, event_offset=checkpoint.event_offset)
        task_run_event = task_run_loop.event_log.append(
            task_run_id,
            "task_run_stopped",
            payload={
                "task_run_id": task_run_id,
                "reason": terminal_reason,
                "message": payload.message.strip(),
                "coordination_run_id": coordination_run.coordination_run_id if coordination_run is not None else "",
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
            },
            refs={
                "task_run_ref": task_run_id,
                "checkpoint_ref": checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id,
                "coordination_run_ref": coordination_run.coordination_run_id if coordination_run is not None else "",
            },
        )
        state_index.upsert_task_run(
            TaskRun(
                task_run_id=task_run.task_run_id,
                session_id=task_run.session_id,
                task_id=task_run.task_id,
                task_contract_ref=task_run.task_contract_ref,
                owner_agent_seat_id=task_run.owner_agent_seat_id,
                agent_id=task_run.agent_id,
                agent_profile_id=task_run.agent_profile_id,
                runtime_lane=task_run.runtime_lane,
                status="aborted",
                created_at=task_run.created_at,
                updated_at=time.time(),
                latest_event_offset=checkpoint_event.offset,
                latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                terminal_reason=terminal_reason,  # type: ignore[arg-type]
                diagnostics={
                    **dict(task_run.diagnostics),
                    "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                },
            )
        )
        if coordination_run is not None:
            state_index.upsert_coordination_run(
                CoordinationRun(
                    coordination_run_id=coordination_run.coordination_run_id,
                    task_run_id=coordination_run.task_run_id,
                    graph_ref=coordination_run.graph_ref,
                    coordinator_agent_id=coordination_run.coordinator_agent_id,
                    topology_template_id=coordination_run.topology_template_id,
                    communication_protocol_id=coordination_run.communication_protocol_id,
                    handoff_policy=coordination_run.handoff_policy,
                    failure_policy=coordination_run.failure_policy,
                    merge_policy=coordination_run.merge_policy,
                    status="aborted",
                    latest_checkpoint_ref=str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                    latest_merge_result_ref=coordination_run.latest_merge_result_ref,
                    created_at=coordination_run.created_at,
                    updated_at=time.time(),
                    diagnostics={
                        **dict(coordination_run.diagnostics),
                        "stop_request": {"reason": terminal_reason, "message": payload.message.strip()},
                    },
                )
            )
        if project_id and session_id:
            state_index.upsert_supervision_record(
                make_supervision_record(
                    project_id=project_id,
                    session_id=session_id,
                    task_run_id=task_run_id,
                    coordination_run_id=coordination_run.coordination_run_id if coordination_run is not None else "",
                    issue_type="task_stop",
                    issue_summary=f"Task run stopped with reason {terminal_reason}",
                    root_cause=terminal_reason,
                    repair_action="stop_task_run",
                    repair_result="aborted",
                    followup_status="recorded",
                    diagnostics={
                        "message": payload.message.strip(),
                        "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
                        "event_ref": task_run_event.event_id,
                    },
                )
            )
        return {
            "authority": "orchestration.task_run_stop",
            "task_run_id": task_run_id,
            "reason": terminal_reason,
            "checkpoint_ref": str(checkpoint_event.refs.get("checkpoint_ref") or checkpoint.checkpoint_id),
            "event_ref": task_run_event.event_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"task_run_stop_failed: {exc}") from exc
