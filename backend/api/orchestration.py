from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_runtime
from orchestration.coordination_recovery import (
    _latest_unconsumed_stage_task_result,
    _recover_active_stage_completed_checkpoint,
)
from orchestration.coordination_replay import sanitize_replayed_stage_request_payload
from orchestration.coordination_rewind import (
    _coordination_downstream_stage_ids,
    _coordination_stage_artifact_paths,
    _mark_invalidated_stage_task_runs,
    _mark_rewound_task_run_running,
    _move_invalidated_artifacts,
    _stage_request_matches_active_stage,
)
from orchestration.coordination_scheduler import _schedule_stage_execution_background
from runtime.subruntime.result_packets import (
    latest_unconsumed_graph_module_imported_result,
    mark_graph_module_imported_output_packet_committed,
)
from runtime.agent_assembly import (
    node_work_order_from_runtime_control,
    stage_execution_request_from_runtime_control,
)
from runtime.execution.node_execution_request import NodeExecutionRequest
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system import TaskFlowRegistry
from sessions import InvalidSessionId, validate_session_id

router = APIRouter()


class CoordinationRunResumeRequest(BaseModel):
    resume_payload: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunContinueRequest(BaseModel):
    source: str = Field(default="orchestration.coordination_run_continue_api", max_length=180)
    current_turn_context: dict[str, Any] = Field(default_factory=dict)


class CoordinationRunDispatchReadyBatchesRequest(BaseModel):
    source: str = Field(default="orchestration.coordination_run_dispatch_ready_batches_api", max_length=180)
    current_turn_context: dict[str, Any] = Field(default_factory=dict)
    max_requests: int = Field(default=4, ge=1, le=32)
    include_current_request: bool = True
    execute_background: bool = False


class CoordinationRunRewindRequest(BaseModel):
    stage_id: str = Field(..., min_length=1, max_length=180)
    reason: str = Field(default="stage_output_invalid", max_length=180)
    source: str = Field(default="orchestration.coordination_run_rewind_api", max_length=180)
    artifact_root: str = Field(default="", max_length=500)
    include_downstream: bool = True
    move_artifacts: bool = True
    refresh_graph_spec: bool = True
    continue_after_rewind: bool = True
    current_turn_context: dict[str, Any] = Field(default_factory=dict)


class TaskGraphRunStartRequest(BaseModel):
    session_id: str = Field(default="task_graph_studio", max_length=180)
    task_id: str = Field(default="", max_length=180)
    initial_inputs: dict[str, Any] = Field(default_factory=dict)
    require_published: bool = True
    include_trace: bool = True
    execute_initial_stage: bool = True


@router.post("/orchestration/runtime-loop/task-graphs/{graph_id}/start")
async def start_task_graph_runtime_loop_run(
    graph_id: str,
    payload: TaskGraphRunStartRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(graph_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="TaskGraph not found")
    if payload.require_published and graph.publish_state != "published":
        raise HTTPException(status_code=409, detail="TaskGraph must be published before run start")
    protocol = registry.get_task_communication_protocol(
        str(graph.default_protocol_id or dict(graph.metadata or {}).get("protocol_id") or "")
    )
    runtime_spec = compile_task_graph_definition_runtime_spec(
        graph=graph,
        specific_tasks=tuple(registry.list_specific_task_records()),
        communication_protocol=protocol,
    )
    blocking_issues = [issue.to_dict() for issue in runtime_spec.issues if issue.severity == "error"]
    if blocking_issues:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "TaskGraph runtime spec has blocking issues",
                "issues": blocking_issues,
            },
        )
    session_id = payload.session_id.strip() or "task_graph_studio"
    try:
        session_id = validate_session_id(session_id or "task_graph_studio")
    except InvalidSessionId as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    start = runtime.query_runtime.task_run_loop.start_task_graph_run(
        session_id=session_id,
        task_id=payload.task_id.strip(),
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=dict(payload.initial_inputs or {}),
        diagnostics={
            "source": "runtime.task_graph_start_api",
            "require_published": payload.require_published,
        },
    )
    stage_execution_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    node_work_order = dict(start.loop_state.diagnostics.get("node_work_order") or {})
    initial_stage_execution_events: list[dict[str, Any]] = []
    initial_stage_execution_error: dict[str, Any] | None = None
    initial_stage_execution_background = False
    initial_stage_execution_schedule: dict[str, Any] = {}
    if payload.execute_initial_stage and stage_execution_request:
        request = NodeExecutionRequest.from_dict(stage_execution_request)
        try:
            initial_stage_execution_schedule = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source="runtime.task_graph_start_api",
                stage_execution_request=request,
                node_work_order=node_work_order,
                current_turn_context={
                    "authority": "context.task_graph_start",
                    "task_graph_id": graph.graph_id,
                    "selected_graph_id": graph.graph_id,
                    "explicit_inputs": dict(payload.initial_inputs or {}),
                },
            )
            initial_stage_execution_background = bool(initial_stage_execution_schedule.get("background_started"))
        except Exception as exc:
            initial_stage_execution_error = {
                "error": str(exc),
                "type": exc.__class__.__name__,
            }
    return {
        "authority": "orchestration.task_graph_run_start",
        "graph_id": graph.graph_id,
        "task_run_id": start.task_run.task_run_id,
        "coordination_run_id": start.coordination_run.coordination_run_id if start.coordination_run is not None else "",
        "task_run": start.task_run.to_dict(),
        "coordination_run": start.coordination_run.to_dict() if start.coordination_run is not None else None,
        "checkpoint": start.checkpoint.to_dict(),
        "runtime_spec": runtime_spec.to_dict(),
        "stage_execution_request": stage_execution_request or None,
        "node_work_order": node_work_order or None,
        "initial_stage_execution_events": initial_stage_execution_events,
        "initial_stage_execution_event_count": len(initial_stage_execution_events),
        "initial_stage_execution_error": initial_stage_execution_error,
        "initial_stage_execution_background": initial_stage_execution_background,
        "initial_stage_execution_schedule": initial_stage_execution_schedule,
        "trace": (
            runtime.query_runtime.task_run_loop.get_trace(start.task_run.task_run_id)
            if payload.include_trace
            else None
        ),
        "events": [dict(item) for item in start.events],
    }


@router.get("/orchestration/coordination-runs/{coordination_run_id}/task-graph-monitor")
async def get_coordination_run_task_graph_monitor(coordination_run_id: str) -> dict[str, Any]:
    runtime = require_runtime()
    monitor = runtime.query_runtime.task_run_loop.get_coordination_run_monitor(coordination_run_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="CoordinationRun task graph monitor not found")
    return monitor


@router.post("/orchestration/coordination-runs/{coordination_run_id}/dispatch-ready-batches")
async def dispatch_coordination_ready_batches(
    coordination_run_id: str,
    payload: CoordinationRunDispatchReadyBatchesRequest,
) -> dict[str, Any]:
    from runtime.execution.node_execution_request import NodeExecutionRequest

    runtime = require_runtime()
    task_run_loop = runtime.query_runtime.task_run_loop
    coordination_run = task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")
    result = task_run_loop.langgraph_coordination_runtime.dispatch_ready_batch_requests(
        coordination_run=coordination_run,
        max_requests=payload.max_requests,
        include_current_request=payload.include_current_request,
        checkpoint_reason="dispatch_ready_batches_api",
    )
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    requests = [dict(item) for item in list(result.diagnostics.get("stage_execution_requests") or []) if isinstance(item, dict)]
    schedule_results: list[dict[str, Any]] = []
    if payload.execute_background:
        for request_payload in requests:
            request = NodeExecutionRequest.from_dict(request_payload)
            schedule_results.append(
                _schedule_stage_execution_background(
                    runtime=runtime,
                    session_id=session_id,
                    source=payload.source,
                    stage_execution_request=request,
                    node_work_order=dict(result.node_work_order or {}),
                    current_turn_context={
                        "authority": "context.coordination_run_dispatch_ready_batches",
                        "coordination_run_id": coordination_run_id,
                        "task_graph_id": coordination_run.graph_ref,
                        "selected_graph_id": coordination_run.graph_ref,
                        "explicit_inputs": dict(request_payload.get("explicit_inputs") or {}),
                        **dict(payload.current_turn_context or {}),
                    },
                )
            )
    return {
        "authority": "orchestration.coordination_run_dispatch_ready_batches",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "checkpoint_ref": result.checkpoint_ref,
        "stage_execution_requests": requests,
        "request_count": len(requests),
        "execute_background": payload.execute_background,
        "background_started_count": sum(1 for item in schedule_results if bool(item.get("background_started"))),
        "stage_execution_schedules": schedule_results,
        "batch_dispatcher": dict(result.diagnostics.get("batch_dispatcher") or {}),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in result.events
        ],
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/resume")
async def resume_coordination_run(
    coordination_run_id: str,
    payload: CoordinationRunResumeRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_human_gate(
        coordination_run_id=coordination_run_id,
        resume_payload=dict(payload.resume_payload or {}),
    )
    if result.diagnostics.get("reason") == "missing_coordination_run":
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    return {
        "authority": "orchestration.coordination_run_resume",
        "coordination_run_id": coordination_run_id,
        "checkpoint_ref": result.checkpoint_ref,
        "diagnostics": dict(result.diagnostics),
        "stage_execution_request": (
            result.stage_execution_request.to_dict()
            if result.stage_execution_request is not None
            else None
        ),
        "events": [
            event.to_dict() if hasattr(event, "to_dict") else dict(event)
            for event in result.events
        ],
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/continue-current-stage")
async def continue_coordination_current_stage(
    coordination_run_id: str,
    payload: CoordinationRunContinueRequest,
) -> dict[str, Any]:
    from runtime.execution.node_execution_request import NodeExecutionRequest, NodeResultReadyEvent

    runtime = require_runtime()
    coordination_run = runtime.query_runtime.task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    state = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run_id,
    )
    if not state:
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    task_run = runtime.query_runtime.task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    if not session_id:
        raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")

    current_event = dict(state.get("current_event") or {})
    current_stage_payload = dict(state.get("stage_execution_request") or {})
    active_stage_id = str(
        state.get("active_stage_id")
        or current_stage_payload.get("stage_id")
        or ""
    ).strip()
    current_event_stage_id = str(current_event.get("stage_id") or "").strip()
    current_event_task_run_id = str(current_event.get("task_run_id") or "").strip()
    current_stage_result_task_run_id = str(
        dict(dict(state.get("stage_results") or {}).get(active_stage_id) or {}).get("task_run_id") or ""
    ).strip()
    current_event_is_active_stage_result = bool(
        str(current_event.get("event_type") or "") == "task_result_ready"
        and active_stage_id
        and current_event_stage_id == active_stage_id
        and current_event_task_run_id
        and current_event_task_run_id == current_stage_result_task_run_id
    )
    graph_module_imported_result = latest_unconsumed_graph_module_imported_result(
        runtime=runtime,
        session_id=session_id,
        state=state,
        active_stage_id=active_stage_id,
        coordination_run_id=coordination_run_id,
    )
    if graph_module_imported_result:
        resume_event = NodeResultReadyEvent(**graph_module_imported_result["event"])
        result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=resume_event,
            current_task_result=dict(graph_module_imported_result.get("task_result") or {}),
            inherited_inputs=dict(graph_module_imported_result.get("explicit_inputs") or {}),
            artifact_root=str(graph_module_imported_result.get("artifact_root") or ""),
        )
        consumption = mark_graph_module_imported_output_packet_committed(
            task_run_loop=runtime.query_runtime.task_run_loop,
            imported_task_run_id=str(graph_module_imported_result.get("task_run_id") or ""),
            packet_ref=str(graph_module_imported_result.get("packet_ref") or ""),
            packet=dict(graph_module_imported_result.get("packet") or {}),
        )
        request = result.stage_execution_request
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api",
                stage_execution_request=request,
                node_work_order=dict(result.node_work_order or {}),
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "resumed_from_graph_module_imported_output_packet",
            "consumed_task_run_id": str(graph_module_imported_result.get("task_run_id") or ""),
            "packet_ref": str(graph_module_imported_result.get("packet_ref") or ""),
            "packet_consumption_ref": str(consumption.get("consumption_ref") or ""),
        }
    recovered_stage_result = _recover_active_stage_completed_checkpoint(
        runtime=runtime,
        session_id=session_id,
        state=state,
        active_stage_id=active_stage_id,
        coordination_run_id=coordination_run_id,
        current_turn_context=dict(payload.current_turn_context or {}),
    )
    if recovered_stage_result.get("recovered"):
        continuation_payload = dict(recovered_stage_result.get("continuation_payload") or {})
        request_payload = stage_execution_request_from_runtime_control(continuation_payload)
        request = NodeExecutionRequest.from_dict(request_payload) if request_payload else None
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api:completed_checkpoint_recovery",
                stage_execution_request=request,
                node_work_order=node_work_order_from_runtime_control(continuation_payload),
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(continuation_payload.get("current_turn_context") or {}),
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "recovered_completed_checkpoint_stage_task_run",
            "consumed_task_run_id": str(recovered_stage_result.get("task_run_id") or ""),
            "recovery": recovered_stage_result,
        }
    latest_unconsumed_stage_result = (
        {}
        if current_event_is_active_stage_result
        else _latest_unconsumed_stage_task_result(
            runtime=runtime,
            session_id=session_id,
            state=state,
            active_stage_id=active_stage_id,
            coordination_run_id=coordination_run_id,
        )
    )
    if latest_unconsumed_stage_result:
        resume_event = NodeResultReadyEvent(**latest_unconsumed_stage_result["event"])
        result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
            coordination_run=coordination_run,
            event=resume_event,
            current_task_result=dict(latest_unconsumed_stage_result.get("task_result") or {}),
            inherited_inputs=dict(latest_unconsumed_stage_result.get("explicit_inputs") or {}),
            artifact_root=str(latest_unconsumed_stage_result.get("artifact_root") or ""),
        )
        request = result.stage_execution_request
        schedule_result: dict[str, Any] = {}
        if request is not None:
            schedule_result = _schedule_stage_execution_background(
                runtime=runtime,
                session_id=session_id,
                source=payload.source or "orchestration.coordination_run_continue_api",
                stage_execution_request=request,
                node_work_order=dict(result.node_work_order or {}),
                current_turn_context={
                    "authority": "context.coordination_run_continue",
                    "coordination_run_id": coordination_run_id,
                    "task_graph_id": coordination_run.graph_ref,
                    "selected_graph_id": coordination_run.graph_ref,
                    **dict(payload.current_turn_context or {}),
                },
            )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict() if request is not None else None,
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "resumed_from_unconsumed_stage_task_result",
            "consumed_task_run_id": str(latest_unconsumed_stage_result.get("task_run_id") or ""),
        }
    if current_stage_payload and _stage_request_matches_active_stage(
        state=state,
        request_payload=current_stage_payload,
        active_stage_id=active_stage_id,
    ):
        request = NodeExecutionRequest.from_dict(
            sanitize_replayed_stage_request_payload(current_stage_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            node_work_order=dict(state.get("node_work_order") or {}),
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "replayed_active_stage_request",
        }
    if str(current_event.get("event_type") or "") != "task_result_ready":
        request_payload = current_stage_payload
        if not request_payload:
            raise HTTPException(status_code=409, detail="CoordinationRun has no resumable stage result or current stage execution request")
        request = NodeExecutionRequest.from_dict(
            sanitize_replayed_stage_request_payload(request_payload)
        )
        current_turn_context = {
            "authority": "context.coordination_run_continue",
            "coordination_run_id": coordination_run_id,
            "task_graph_id": coordination_run.graph_ref,
            "selected_graph_id": coordination_run.graph_ref,
            **dict(payload.current_turn_context or {}),
        }
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            node_work_order=dict(state.get("node_work_order") or {}),
            current_turn_context=current_turn_context,
        )
        return {
            "authority": "orchestration.coordination_run_continue_current_stage",
            "coordination_run_id": coordination_run_id,
            "task_run_id": coordination_run.task_run_id,
            "session_id": session_id,
            "stage_execution_request": request.to_dict(),
            "background_started": bool(schedule_result.get("background_started")),
            "stage_execution_schedule": schedule_result,
            "mode": "replayed_current_stage_request",
        }

    if not current_stage_payload and active_stage_id and active_stage_id != str(current_event.get("stage_id") or "").strip():
        repaired_state = dict(state)
        repaired_statuses = dict(repaired_state.get("node_statuses") or {})
        if repaired_statuses.get(active_stage_id) == "running":
            repaired_statuses[active_stage_id] = "pending"
            repaired_state["node_statuses"] = repaired_statuses
            repaired_state["terminal_status"] = ""
            repaired_state["stage_execution_request"] = {}
            repaired_state["diagnostics"] = {
                **dict(repaired_state.get("diagnostics") or {}),
                "continue_current_stage_repaired_pending_active_stage": active_stage_id,
            }
            runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.checkpoints.put_state(
                thread_id=coordination_run_id,
                state=repaired_state,
                metadata={"event": "continue_current_stage_repair_pending_active_stage", "stage_id": active_stage_id},
            )

    current_task_result = dict(dict(state.get("stage_results") or {}).get(str(current_event.get("stage_id") or "")) or {})
    artifact_root = str(
        dict(payload.current_turn_context or {}).get("artifact_root")
        or dict(state.get("pending_inputs") or {}).get("artifact_root")
        or ""
    )
    resume_event = NodeResultReadyEvent(
        event_type=str(current_event.get("event_type") or "task_result_ready"),
        coordination_run_id=str(current_event.get("coordination_run_id") or coordination_run_id),
        task_run_id=str(current_event.get("task_run_id") or coordination_run.task_run_id),
        stage_id=str(current_event.get("stage_id") or ""),
        task_ref=str(current_event.get("task_ref") or ""),
        task_result_ref=str(current_event.get("task_result_ref") or ""),
        artifact_refs=tuple(str(item) for item in list(current_event.get("artifact_refs") or []) if str(item)),
        accepted=bool(current_event.get("accepted") is True),
        agent_run_result_ref=str(current_event.get("agent_run_result_ref") or ""),
        diagnostics=dict(current_event.get("diagnostics") or {}),
    )
    result = runtime.query_runtime.task_run_loop.langgraph_coordination_runtime.resume_from_task_result(
        coordination_run=coordination_run,
        event=resume_event,
        current_task_result=current_task_result,
        inherited_inputs=dict(payload.current_turn_context or {}),
        artifact_root=artifact_root,
    )
    request = result.stage_execution_request
    schedule_result: dict[str, Any] = {}
    if request is not None:
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source or "orchestration.coordination_run_continue_api",
            stage_execution_request=request,
            node_work_order=dict(result.node_work_order or {}),
            current_turn_context={
                "authority": "context.coordination_run_continue",
                "coordination_run_id": coordination_run_id,
                "task_graph_id": coordination_run.graph_ref,
                "selected_graph_id": coordination_run.graph_ref,
                **dict(payload.current_turn_context or {}),
            },
        )
    return {
        "authority": "orchestration.coordination_run_continue_current_stage",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "stage_execution_request": request.to_dict() if request is not None else None,
        "background_started": bool(schedule_result.get("background_started")),
        "stage_execution_schedule": schedule_result,
        "mode": "resumed_from_task_result",
    }


@router.post("/orchestration/coordination-runs/{coordination_run_id}/rewind-from-stage")
async def rewind_coordination_run_from_stage(
    coordination_run_id: str,
    payload: CoordinationRunRewindRequest,
) -> dict[str, Any]:
    runtime = require_runtime()
    task_run_loop = runtime.query_runtime.task_run_loop
    coordination_run = task_run_loop.state_index.get_coordination_run(coordination_run_id)
    if coordination_run is None:
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    previous_state = task_run_loop.langgraph_coordination_runtime.checkpoints.get_state(
        thread_id=coordination_run_id,
    )
    if not previous_state:
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")

    stage_id = payload.stage_id.strip()
    invalidated_stage_ids = _coordination_downstream_stage_ids(
        state=previous_state,
        stage_id=stage_id,
        include_downstream=payload.include_downstream,
    )
    artifact_root = str(
        payload.artifact_root
        or payload.current_turn_context.get("artifact_root")
        or dict(previous_state.get("pending_inputs") or {}).get("artifact_root")
        or ""
    ).strip()
    invalidated_artifacts = _coordination_stage_artifact_paths(
        state=previous_state,
        stage_ids=invalidated_stage_ids,
    )
    invalidated_task_runs = _mark_invalidated_stage_task_runs(
        task_run_loop=task_run_loop,
        coordination_run=coordination_run,
        stage_ids=invalidated_stage_ids,
        reason=payload.reason,
    )
    moved_artifacts = []
    if payload.move_artifacts and artifact_root:
        moved_artifacts = _move_invalidated_artifacts(
            artifact_refs=invalidated_artifacts,
            artifact_root=artifact_root,
            stage_id=stage_id,
            reason=payload.reason,
        )

    result = task_run_loop.langgraph_coordination_runtime.rewind_from_stage(
        coordination_run_id=coordination_run_id,
        stage_id=stage_id,
        reason=payload.reason,
        inherited_inputs={
            **dict(payload.current_turn_context or {}),
            "artifact_root": artifact_root,
            "rewind_invalidated_artifacts": moved_artifacts,
        },
        refresh_graph_spec=payload.refresh_graph_spec,
    )
    if result.diagnostics.get("reason") == "missing_coordination_run":
        raise HTTPException(status_code=404, detail="CoordinationRun not found")
    if result.diagnostics.get("reason") == "missing_checkpoint":
        raise HTTPException(status_code=409, detail="CoordinationRun has no LangGraph checkpoint")
    if result.diagnostics.get("reason") == "stage_not_in_order":
        raise HTTPException(status_code=409, detail="Stage is not part of this CoordinationRun")

    request = result.stage_execution_request
    background_started = False
    task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    if task_run is not None and str(task_run.status or "") in {"aborted", "failed", "completed"}:
        _mark_rewound_task_run_running(
            task_run_loop=task_run_loop,
            task_run=task_run,
            coordination_run=coordination_run,
            checkpoint_ref=result.checkpoint_ref,
            reason=payload.reason,
            stage_id=stage_id,
        )
        task_run = task_run_loop.state_index.get_task_run(coordination_run.task_run_id)
    session_id = str(getattr(task_run, "session_id", "") or "").strip()
    schedule_result: dict[str, Any] = {}
    if payload.continue_after_rewind and request is not None:
        if not session_id:
            raise HTTPException(status_code=409, detail="CoordinationRun root TaskRun has no session_id")
        schedule_result = _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=payload.source,
            stage_execution_request=request,
            node_work_order=dict(result.node_work_order or {}),
            current_turn_context={
                "authority": "context.coordination_run_rewind",
                "coordination_run_id": coordination_run_id,
                "task_graph_id": coordination_run.graph_ref,
                "selected_graph_id": coordination_run.graph_ref,
                "artifact_root": artifact_root,
                **dict(payload.current_turn_context or {}),
            },
        )
        background_started = bool(schedule_result.get("background_started"))

    return {
        "authority": "orchestration.coordination_run_rewind_from_stage",
        "coordination_run_id": coordination_run_id,
        "task_run_id": coordination_run.task_run_id,
        "session_id": session_id,
        "stage_id": stage_id,
        "reason": payload.reason,
        "invalidated_stage_ids": invalidated_stage_ids,
        "invalidated_task_runs": invalidated_task_runs,
        "invalidated_artifact_refs": invalidated_artifacts,
        "moved_artifacts": moved_artifacts,
        "checkpoint_ref": result.checkpoint_ref,
        "stage_execution_request": request.to_dict() if request is not None else None,
        "background_started": background_started,
        "stage_execution_schedule": schedule_result,
        "diagnostics": dict(result.diagnostics),
    }

