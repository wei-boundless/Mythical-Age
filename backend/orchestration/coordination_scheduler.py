from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from runtime import TaskRun
from runtime.coordination_runtime.runtime import LangGraphCoordinationRuntimeResult
from runtime.execution.graph_module_runtime import build_graph_module_runtime_handle_from_request
from runtime.shared.protocol_boundary import is_internal_protocol_input_key
from task_system import TaskFlowRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
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
    current_turn_context: dict[str, Any] | None = None,
) -> None:
    if str(getattr(stage_execution_request, "executor_type", "") or "") == "graph_module":
        _start_graph_module_stage_request(
            runtime=runtime,
            session_id=session_id,
            source=source,
            stage_execution_request=stage_execution_request,
            current_turn_context=current_turn_context,
        )
        return
    continuation_payload = LangGraphCoordinationRuntimeResult(
        stage_execution_request=stage_execution_request,
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
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_run_loop = runtime.query_runtime.task_run_loop
    request_payload = (
        stage_execution_request.to_dict()
        if hasattr(stage_execution_request, "to_dict")
        else dict(stage_execution_request or {})
    )
    identity = _stage_execution_schedule_identity(stage_execution_request)
    handle = build_graph_module_runtime_handle_from_request(request_payload)
    linked_graph_id = str(handle.get("linked_graph_id") or "").strip()
    if not linked_graph_id:
        raise ValueError("GraphModule stage request requires linked_graph_id")
    registry = TaskFlowRegistry(runtime.base_dir)
    graph = registry.get_task_graph(linked_graph_id)
    if graph is None:
        raise ValueError(f"GraphModule linked TaskGraph not found: {linked_graph_id}")
    if str(graph.publish_state or "") != "published":
        raise ValueError(f"GraphModule linked TaskGraph must be published before run start: {linked_graph_id}")
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
        raise ValueError(f"GraphModule imported runtime spec has blocking issues: {blocking_issues}")
    importing_runtime_handle = {
        key: value
        for key, value in dict(handle).items()
        if key not in {"explicit_inputs", "standard_input_package"}
    }
    imported_initial_inputs = {
        str(key): value
        for key, value in dict(handle.get("explicit_inputs") or {}).items()
        if not is_internal_protocol_input_key(str(key))
    }
    diagnostics = {
        "source": "orchestration.graph_module_stage_request",
        "graph_module_imported_run": True,
        "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
        "importing_graph_module_runtime_handle": importing_runtime_handle,
        "importing_stage_execution_request": request_payload,
        "importing_standard_input_package": dict(
            handle.get("standard_input_package")
            or request_payload.get("standard_input_package")
            or {}
        ),
        "linked_graph_id": linked_graph_id,
        "importing_graph_id": str(handle.get("importing_graph_id") or ""),
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or request_payload.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(request_payload.get("task_ref") or identity.get("task_ref") or ""),
        "importing_stage_request_id": str(identity.get("request_id") or ""),
        "importing_stage_idempotency_key": str(identity.get("idempotency_key") or ""),
        "importing_dispatch_event_id": str(identity.get("dispatch_event_id") or ""),
        "importing_source": source,
        "stage_id": str(identity.get("stage_id") or ""),
        "coordination_stage_id": str(identity.get("stage_id") or ""),
        "coordination_run_id": str(identity.get("coordination_run_id") or ""),
        "stage_request_id": str(identity.get("request_id") or ""),
        "stage_idempotency_key": str(identity.get("idempotency_key") or ""),
        "current_turn_context": dict(current_turn_context or {}),
    }
    start = task_run_loop.start_task_graph_run(
        session_id=session_id,
        task_id=f"task_graph.graph_module.{linked_graph_id}",
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=imported_initial_inputs,
        diagnostics=diagnostics,
    )
    imported_coordination_run_id = start.coordination_run.coordination_run_id if start.coordination_run is not None else ""
    imported_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    _attach_graph_module_imported_run_identity(
        task_run_loop=task_run_loop,
        imported_task_run=start.task_run,
        imported_coordination_run_id=imported_coordination_run_id,
        handle=handle,
        identity=identity,
    )
    task_run_loop.event_log.append(
        str(request_payload.get("root_task_run_id") or ""),
        "coordination_graph_module_imported_run_started",
        payload={
            "source": source,
            "importing_coordination_run_id": str(identity.get("coordination_run_id") or ""),
            "importing_stage_id": str(identity.get("stage_id") or ""),
            "importing_node_id": str(identity.get("node_id") or ""),
            "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
            "linked_graph_id": linked_graph_id,
            "imported_task_run_id": start.task_run.task_run_id,
            "imported_coordination_run_id": imported_coordination_run_id,
            "imported_initial_stage_execution_request": imported_request,
        },
        refs={
            "coordination_run_ref": str(identity.get("coordination_run_id") or ""),
            "stage_id": str(identity.get("stage_id") or ""),
            "imported_task_run_ref": start.task_run.task_run_id,
            "imported_coordination_run_ref": imported_coordination_run_id,
        },
    )
    auto_start = bool(dict(request_payload.get("executor_binding") or {}).get("auto_start_imported_initial_stage", False) is True)
    auto_start = bool(dict(handle.get("executor_policy") or {}).get("auto_start_imported_initial_stage", auto_start) is not False)
    if auto_start and imported_request:
        from runtime.execution.node_execution_request import NodeExecutionRequest

        _schedule_stage_execution_background(
            runtime=runtime,
            session_id=session_id,
            source=f"{source}:graph_module_imported_initial_stage",
            stage_execution_request=NodeExecutionRequest.from_dict(imported_request),
            current_turn_context={
                "authority": "context.graph_module_imported_run",
                "importing_coordination_run_id": str(identity.get("coordination_run_id") or ""),
                "importing_stage_id": str(identity.get("stage_id") or ""),
                "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
                "task_graph_id": linked_graph_id,
                "selected_graph_id": linked_graph_id,
            },
        )
    return {
        "imported_task_run_id": start.task_run.task_run_id,
        "imported_coordination_run_id": imported_coordination_run_id,
        "linked_graph_id": linked_graph_id,
        "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
        "imported_stage_execution_request": imported_request,
    }


def _attach_graph_module_imported_run_identity(
    *,
    task_run_loop: Any,
    imported_task_run: TaskRun,
    imported_coordination_run_id: str,
    handle: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    current = task_run_loop.state_index.get_task_run(imported_task_run.task_run_id) or imported_task_run
    diagnostics = {
        **dict(current.diagnostics or {}),
        "imported_coordination_run_id": imported_coordination_run_id,
        "imported_task_run_id": current.task_run_id,
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or identity.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(identity.get("task_ref") or ""),
        "importing_stage_request_id": str(identity.get("request_id") or ""),
        "importing_stage_idempotency_key": str(identity.get("idempotency_key") or ""),
    }
    task_run_loop.state_index.upsert_task_run(
        TaskRun(
            task_run_id=current.task_run_id,
            session_id=current.session_id,
            task_id=current.task_id,
            task_contract_ref=current.task_contract_ref,
            owner_agent_seat_id=current.owner_agent_seat_id,
            agent_id=current.agent_id,
            agent_profile_id=current.agent_profile_id,
            runtime_lane=current.runtime_lane,
            status=current.status,
            created_at=current.created_at,
            updated_at=time.time(),
            latest_event_offset=current.latest_event_offset,
            latest_checkpoint_ref=current.latest_checkpoint_ref,
            terminal_reason=current.terminal_reason,
            diagnostics=diagnostics,
        )
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

