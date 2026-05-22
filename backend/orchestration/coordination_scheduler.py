from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from runtime import TaskRun
from runtime.coordination_runtime.runtime import LangGraphCoordinationRuntimeResult
from runtime.subruntime import start_graph_module_stage_request
from understanding import analyze_memory_intent

from orchestration.coordination_rewind import _stage_id_from_task_run


_STAGE_EXECUTION_SCHEDULE_LOCK = threading.RLock()
_STAGE_EXECUTION_INFLIGHT: dict[str, dict[str, Any]] = {}

async def _execute_stage_request_in_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    node_work_order: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> None:
    if str(getattr(stage_execution_request, "executor_type", "") or "") == "graph_module":
        _start_graph_module_stage_request(
            runtime=runtime,
            session_id=session_id,
            source=source,
            stage_execution_request=stage_execution_request,
            node_work_order=node_work_order,
            current_turn_context=current_turn_context,
        )
        return
    continuation_payload = LangGraphCoordinationRuntimeResult(
        stage_execution_request=stage_execution_request,
        node_work_order=dict(node_work_order or {}),
    ).continuation_payload(
        session_id=session_id,
        current_turn_context=dict(current_turn_context or {}),
    )
    if not continuation_payload:
        return
    async for _event in runtime.query_runtime.task_run_loop._continue_coordination_delivery_stream(
        session_id=session_id,
        history=runtime.query_runtime.session_manager.load_session_for_agent(
            session_id,
            include_compressed_context=False,
        ),
        source=source,
        agent_runtime_chain=runtime.query_runtime.agent_runtime_chain,
        model_response_executor=runtime.query_runtime.model_response_executor,
        runtime_context_manager=runtime.query_runtime.runtime_context_manager,
        stage_projection_cycle=None,
        memory_intent=analyze_memory_intent(stage_execution_request.message),
        assistant_message_committer=lambda _payload: None,
        tool_runtime_executor=runtime.query_runtime.tool_runtime_executor,
        tool_instances=runtime.query_runtime._all_tool_instances(),
        agent_runtime_profile=runtime.query_runtime.agent_runtime_registry.get_profile(stage_execution_request.agent_id),
        continuation_payload=continuation_payload,
    ):
        pass


def _schedule_stage_execution_background(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    node_work_order: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    identity = _stage_execution_schedule_identity(stage_execution_request)
    schedule_key = str(identity.get("schedule_key") or "")
    with _STAGE_EXECUTION_SCHEDULE_LOCK:
        existing = _matching_stage_execution_task_run(
            task_run_loop=task_run_loop,
            session_id=session_id,
            identity=identity,
        )
        if existing is not None:
            if _stale_running_task_run_reason(task_run_loop=task_run_loop, task_run=existing):
                _invalidate_stale_stage_execution_task_run(
                    task_run_loop=task_run_loop,
                    task_run=existing,
                    identity=identity,
                    source=source,
                )
                current_turn_context = {
                    **dict(current_turn_context or {}),
                    "stale_stage_execution_retry": {
                        "previous_task_run_id": existing.task_run_id,
                        "previous_status": existing.status,
                        "reason": "stale_running_task_run",
                    },
                }
            else:
                result = {
                    "background_started": False,
                    "reason": "stage_execution_already_has_effective_task_run",
                    "existing_task_run_id": existing.task_run_id,
                    "existing_status": existing.status,
                    "stage_execution_identity": identity,
                }
                _append_stage_execution_schedule_event(
                    task_run_loop=task_run_loop,
                    root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
                    event_type="coordination_stage_background_execution_skipped",
                    payload={**result, "source": source},
                    identity=identity,
                )
                return result
        if schedule_key and schedule_key in _STAGE_EXECUTION_INFLIGHT:
            inflight = dict(_STAGE_EXECUTION_INFLIGHT.get(schedule_key) or {})
            if _inflight_stage_execution_is_stale(inflight):
                _STAGE_EXECUTION_INFLIGHT.pop(schedule_key, None)
                _append_stage_execution_schedule_event(
                    task_run_loop=task_run_loop,
                    root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
                    event_type="coordination_stage_background_execution_invalidated",
                    payload={
                        "reason": "stale_inflight_schedule",
                        "inflight": inflight,
                        "source": source,
                    },
                    identity=identity,
                )
            else:
                result = {
                    "background_started": False,
                    "reason": "stage_execution_already_scheduled",
                    "existing_task_run_id": str(inflight.get("task_run_id") or ""),
                    "existing_status": "scheduled",
                    "stage_execution_identity": identity,
                }
                _append_stage_execution_schedule_event(
                    task_run_loop=task_run_loop,
                    root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
                    event_type="coordination_stage_background_execution_skipped",
                    payload={**result, "source": source},
                    identity=identity,
                )
                return result
        if schedule_key:
            _STAGE_EXECUTION_INFLIGHT[schedule_key] = {
                "coordination_run_id": identity.get("coordination_run_id"),
                "stage_id": identity.get("stage_id"),
                "request_id": identity.get("request_id"),
                "idempotency_key": identity.get("idempotency_key"),
                "scheduled_at": time.time(),
                "source": source,
            }

    def runner() -> None:
        try:
            asyncio.run(
                _execute_stage_request_in_background(
                    runtime=runtime,
                    session_id=session_id,
                    source=source,
                    stage_execution_request=stage_execution_request,
                    node_work_order=node_work_order,
                    current_turn_context=current_turn_context,
                )
            )
        except Exception as exc:
            task_run_loop.event_log.append(
                stage_execution_request.root_task_run_id,
                "coordination_stage_background_execution_failed",
                payload={
                    "coordination_run_id": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                    "task_ref": stage_execution_request.task_ref,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "source": source,
                },
                refs={
                    "coordination_run_ref": stage_execution_request.coordination_run_id,
                    "stage_id": stage_execution_request.stage_id,
                },
            )
        finally:
            if schedule_key:
                with _STAGE_EXECUTION_SCHEDULE_LOCK:
                    _STAGE_EXECUTION_INFLIGHT.pop(schedule_key, None)

    thread = threading.Thread(
        target=runner,
        name=f"taskgraph-node-{str(stage_execution_request.stage_id or 'unknown')}",
        daemon=True,
    )
    thread.start()
    result = {
        "background_started": True,
        "reason": "scheduled",
        "existing_task_run_id": "",
        "existing_status": "",
        "stage_execution_identity": identity,
    }
    _append_stage_execution_schedule_event(
        task_run_loop=task_run_loop,
        root_task_run_id=str(stage_execution_request.root_task_run_id or ""),
        event_type="coordination_stage_background_execution_scheduled",
        payload={**result, "source": source},
        identity=identity,
    )
    return result


def _stage_execution_schedule_identity(stage_execution_request: Any) -> dict[str, Any]:
    from runtime.execution.node_execution_request import build_node_execution_idempotency_key

    payload = (
        stage_execution_request.to_dict()
        if hasattr(stage_execution_request, "to_dict")
        else dict(stage_execution_request or {})
    )
    stage_id = str(payload.get("stage_id") or payload.get("node_id") or "").strip()
    node_id = str(payload.get("node_id") or stage_id).strip()
    coordination_run_id = str(payload.get("coordination_run_id") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if not idempotency_key:
        idempotency_key = build_node_execution_idempotency_key(
            coordination_run_id=coordination_run_id,
            node_id=node_id,
            explicit_inputs=dict(payload.get("explicit_inputs") or {}),
            dispatch_context=dict(payload.get("dispatch_context") or {}),
        )
    schedule_key = "|".join(
        [
            coordination_run_id,
            stage_id,
            idempotency_key or request_id,
        ]
    )
    return {
        "coordination_run_id": coordination_run_id,
        "root_task_run_id": str(payload.get("root_task_run_id") or "").strip(),
        "stage_id": stage_id,
        "node_id": node_id,
        "task_ref": str(payload.get("task_ref") or "").strip(),
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "dispatch_event_id": str(dict(payload.get("dispatch_context") or {}).get("dispatch_event_id") or "").strip(),
        "schedule_key": schedule_key,
    }


def _start_graph_module_stage_request(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    node_work_order: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = _stage_execution_schedule_identity(stage_execution_request)
    return start_graph_module_stage_request(
        runtime=runtime,
        session_id=session_id,
        source=source,
        stage_execution_request=stage_execution_request,
        identity=identity,
        schedule_stage_execution_background=_schedule_stage_execution_background,
        node_work_order=dict(node_work_order or {}),
        current_turn_context=current_turn_context,
    )


def _matching_stage_execution_task_run(
    *,
    task_run_loop: Any,
    session_id: str,
    identity: dict[str, Any],
) -> TaskRun | None:
    coordination_run_id = str(identity.get("coordination_run_id") or "").strip()
    stage_id = str(identity.get("stage_id") or "").strip()
    request_id = str(identity.get("request_id") or "").strip()
    idempotency_key = str(identity.get("idempotency_key") or "").strip()
    effective_statuses = {"created", "running", "waiting_approval", "blocked", "completed"}
    candidates = task_run_loop.state_index.list_session_task_runs(session_id) if session_id else task_run_loop.state_index.list_task_runs()
    matches: list[TaskRun] = []
    for task_run in candidates:
        status = str(task_run.status or "")
        if status not in effective_statuses:
            continue
        diagnostics = dict(task_run.diagnostics or {})
        if status == "completed" and diagnostics.get("invalidated_by_coordination_rewind"):
            continue
        run_coordination_id = str(diagnostics.get("coordination_run_id") or "").strip()
        if coordination_run_id and run_coordination_id and run_coordination_id != coordination_run_id:
            continue
        run_stage_id = str(
            diagnostics.get("stage_id")
            or diagnostics.get("coordination_stage_id")
            or _stage_id_from_task_run(task_run)
        ).strip()
        if stage_id and run_stage_id and run_stage_id != stage_id:
            continue
        run_idempotency_key = str(diagnostics.get("stage_idempotency_key") or "").strip()
        run_request_id = str(diagnostics.get("stage_request_id") or "").strip()
        if idempotency_key and run_idempotency_key == idempotency_key:
            matches.append(task_run)
            continue
        if request_id and run_request_id == request_id:
            matches.append(task_run)
            continue
    if not matches:
        return None
    return sorted(matches, key=lambda item: float(item.updated_at or item.created_at or 0.0), reverse=True)[0]


def _stale_running_task_run_reason(*, task_run_loop: Any, task_run: TaskRun) -> str:
    if str(task_run.status or "") != "running":
        return ""
    diagnostics = dict(task_run.diagnostics or {})
    limits = dict(diagnostics.get("effective_loop_limits") or diagnostics.get("loop_limits") or {})
    max_runtime_seconds = _safe_float(limits.get("max_runtime_seconds"), 0.0)
    if max_runtime_seconds <= 0:
        return ""
    latest_activity_at = max(float(task_run.updated_at or 0.0), float(task_run.created_at or 0.0))
    try:
        events = list(task_run_loop.event_log.list_events(task_run.task_run_id))
    except Exception:
        events = []
    if events:
        latest_activity_at = max(
            latest_activity_at,
            max(float(getattr(event, "created_at", 0.0) or 0.0) for event in events),
        )
    stale_after = max(max_runtime_seconds + 30.0, max_runtime_seconds * 1.25)
    if time.time() - latest_activity_at <= stale_after:
        return ""
    latest_event_type = str(getattr(events[-1], "event_type", "") or "") if events else ""
    if latest_event_type in {"task_run_completed", "task_run_failed", "task_run_stopped"}:
        return ""
    return "running_task_exceeded_runtime_limit_without_trace_progress"


def _invalidate_stale_stage_execution_task_run(
    *,
    task_run_loop: Any,
    task_run: TaskRun,
    identity: dict[str, Any],
    source: str,
) -> None:
    reason = _stale_running_task_run_reason(task_run_loop=task_run_loop, task_run=task_run)
    if not reason:
        return
    now = time.time()
    diagnostics = {
        **dict(task_run.diagnostics or {}),
        "invalidated_by_stage_scheduler": {
            "reason": reason,
            "source": source,
            "coordination_run_id": str(identity.get("coordination_run_id") or ""),
            "stage_id": str(identity.get("stage_id") or ""),
            "invalidated_at": now,
        },
    }
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=task_run.task_run_id,
            session_id=task_run.session_id,
            task_id=task_run.task_id,
            task_contract_ref=task_run.task_contract_ref,
            owner_agent_seat_id=task_run.owner_agent_seat_id,
            agent_id=task_run.agent_id,
            agent_profile_id=task_run.agent_profile_id,
            runtime_lane=task_run.runtime_lane,
            status="failed",
            created_at=task_run.created_at,
            updated_at=now,
            latest_event_offset=task_run.latest_event_offset,
            latest_checkpoint_ref=task_run.latest_checkpoint_ref,
            terminal_reason="internal_error",
            diagnostics=diagnostics,
        )
    )
    for agent_run in task_run_loop.state_index.list_task_agent_runs(task_run.task_run_id):
        if str(agent_run.status or "") not in {"pending", "running"}:
            continue
        task_run_loop.state_index.upsert_agent_run(
            type(agent_run)(
                agent_run_id=agent_run.agent_run_id,
                task_run_id=agent_run.task_run_id,
                agent_id=agent_run.agent_id,
                agent_profile_id=agent_run.agent_profile_id,
                role=agent_run.role,
                spawn_mode=agent_run.spawn_mode,
                context_scope=agent_run.context_scope,
                runtime_lane=agent_run.runtime_lane,
                parent_agent_run_ref=agent_run.parent_agent_run_ref,
                coordination_run_ref=agent_run.coordination_run_ref,
                status="failed",
                latest_checkpoint_ref=agent_run.latest_checkpoint_ref,
                result_ref=agent_run.result_ref,
                created_at=agent_run.created_at,
                updated_at=now,
                diagnostics={
                    **dict(agent_run.diagnostics or {}),
                    "invalidated_by_stage_scheduler": {
                        "reason": reason,
                        "task_run_id": task_run.task_run_id,
                        "invalidated_at": now,
                    },
                },
            )
        )
    _append_stage_execution_schedule_event(
        task_run_loop=task_run_loop,
        root_task_run_id=str(identity.get("root_task_run_id") or task_run.task_run_id),
        event_type="coordination_stage_background_execution_invalidated",
        payload={
            "reason": reason,
            "invalidated_task_run_id": task_run.task_run_id,
            "source": source,
            "stage_execution_identity": identity,
        },
        identity=identity,
    )


def _inflight_stage_execution_is_stale(inflight: dict[str, Any]) -> bool:
    scheduled_at = _safe_float(inflight.get("scheduled_at"), 0.0)
    if scheduled_at <= 0:
        return False
    return time.time() - scheduled_at > 330.0


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _append_stage_execution_schedule_event(
    *,
    task_run_loop: Any,
    root_task_run_id: str,
    event_type: str,
    payload: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    if not root_task_run_id:
        return
    try:
        task_run_loop.event_log.append(
            root_task_run_id,
            event_type,
            payload=payload,
            refs={
                "coordination_run_ref": str(identity.get("coordination_run_id") or ""),
                "stage_id": str(identity.get("stage_id") or ""),
                "node_execution_request_ref": str(identity.get("request_id") or ""),
                "idempotency_key": str(identity.get("idempotency_key") or ""),
            },
        )
    except Exception:
        return

