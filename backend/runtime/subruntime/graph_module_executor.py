from __future__ import annotations

import time
from typing import Any, Callable

from task_system import TaskFlowRegistry
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec

from ..shared.models import TaskRun
from task_system.runtime_semantics.protocol_boundary import is_internal_protocol_input_key
from runtime.agent_assembly import build_runtime_control_payload, runtime_control_ref_summary
from .graph_module_runtime import build_graph_module_runtime_handle_from_request, build_graph_module_runtime_handle_from_work_order
from .models import GraphModuleStartResult


def start_graph_module_stage_request(
    *,
    runtime: Any,
    session_id: str,
    source: str,
    stage_execution_request: Any,
    identity: dict[str, Any],
    schedule_stage_execution_background: Callable[..., dict[str, Any]],
    node_work_order: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_task_runtime = runtime.query_runtime.graph_task_runtime
    request_payload = (
        stage_execution_request.to_dict()
        if hasattr(stage_execution_request, "to_dict")
        else dict(stage_execution_request or {})
    )
    work_order_payload = dict(node_work_order or {})
    handle = (
        build_graph_module_runtime_handle_from_work_order(work_order_payload)
        if work_order_payload
        else build_graph_module_runtime_handle_from_request(request_payload)
    )
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
    runtime_control_summary = runtime_control_ref_summary(
        build_runtime_control_payload(
            stage_execution_request=request_payload,
            node_work_order=work_order_payload,
            standard_input_package=dict(
                handle.get("standard_input_package")
                or work_order_payload.get("input_package")
                or request_payload.get("standard_input_package")
                or {}
            ),
        )
    )
    imported_initial_inputs = {
        str(key): value
        for key, value in dict(handle.get("explicit_inputs") or {}).items()
        if not is_internal_protocol_input_key(str(key))
    }
    diagnostics = {
        "source": "runtime.subruntime.graph_module_stage_request",
        "graph_module_imported_run": True,
        "graph_module_runtime_handle_id": str(handle.get("handle_id") or ""),
        "importing_graph_module_runtime_handle": importing_runtime_handle,
        "importing_stage_execution_request_ref": str(request_payload.get("request_id") or request_payload.get("idempotency_key") or ""),
        "importing_runtime_control_summary": runtime_control_summary,
        "importing_node_work_order_ref": str(runtime_control_summary.get("work_order_id") or ""),
        "importing_standard_input_package": dict(
            handle.get("standard_input_package")
            or work_order_payload.get("input_package")
            or request_payload.get("standard_input_package")
            or {}
        ),
        "linked_graph_id": linked_graph_id,
        "importing_graph_id": str(handle.get("importing_graph_id") or ""),
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or work_order_payload.get("root_task_run_id") or request_payload.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(work_order_payload.get("task_ref") or request_payload.get("task_ref") or identity.get("task_ref") or ""),
        "importing_work_order_id": str(work_order_payload.get("work_order_id") or ""),
        "importing_stage_request_ref": str(identity.get("request_id") or identity.get("idempotency_key") or ""),
        "importing_dispatch_event_id": str(identity.get("dispatch_event_id") or ""),
        "importing_source": source,
        "stage_id": str(identity.get("stage_id") or ""),
        "coordination_stage_id": str(identity.get("stage_id") or ""),
        "coordination_run_id": str(identity.get("coordination_run_id") or ""),
        "stage_request_id": str(identity.get("request_id") or ""),
        "stage_idempotency_key": str(identity.get("idempotency_key") or ""),
        "current_turn_context": dict(current_turn_context or {}),
    }
    start = graph_task_runtime.start_run(
        session_id=session_id,
        task_id=f"task_graph.graph_module.{linked_graph_id}",
        graph=graph,
        runtime_spec=runtime_spec,
        initial_inputs=imported_initial_inputs,
        diagnostics=diagnostics,
    )
    imported_coordination_run_id = start.coordination_run.coordination_run_id if start.coordination_run is not None else ""
    imported_request = dict(start.loop_state.diagnostics.get("stage_execution_request") or {})
    attach_graph_module_imported_run_identity(
        graph_task_runtime=graph_task_runtime,
        imported_task_run=start.task_run,
        imported_coordination_run_id=imported_coordination_run_id,
        handle=handle,
        identity=identity,
    )
    graph_task_runtime.append_event(
        str(work_order_payload.get("root_task_run_id") or request_payload.get("root_task_run_id") or ""),
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
            "imported_initial_stage_execution_request_ref": str(imported_request.get("request_id") or imported_request.get("idempotency_key") or ""),
        },
        refs={
            "coordination_run_ref": str(identity.get("coordination_run_id") or ""),
            "stage_id": str(identity.get("stage_id") or ""),
            "imported_task_run_ref": start.task_run.task_run_id,
            "imported_coordination_run_ref": imported_coordination_run_id,
        },
    )
    auto_start = bool(dict(work_order_payload.get("executor_binding") or request_payload.get("executor_binding") or {}).get("auto_start_imported_initial_stage", False) is True)
    auto_start = bool(dict(handle.get("executor_policy") or {}).get("auto_start_imported_initial_stage", auto_start) is not False)
    if auto_start and imported_request:
        from runtime.execution.node_execution_request import NodeExecutionRequest

        schedule_stage_execution_background(
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
    return GraphModuleStartResult(
        imported_task_run_id=start.task_run.task_run_id,
        imported_coordination_run_id=imported_coordination_run_id,
        linked_graph_id=linked_graph_id,
        graph_module_runtime_handle_id=str(handle.get("handle_id") or ""),
        imported_stage_execution_request_ref=str(imported_request.get("request_id") or imported_request.get("idempotency_key") or ""),
    ).to_dict()


def attach_graph_module_imported_run_identity(
    *,
    graph_task_runtime: Any,
    imported_task_run: TaskRun,
    imported_coordination_run_id: str,
    handle: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    current = graph_task_runtime.get_task_run(imported_task_run.task_run_id) or imported_task_run
    diagnostics = {
        **dict(current.diagnostics or {}),
        "imported_coordination_run_id": imported_coordination_run_id,
        "imported_task_run_id": current.task_run_id,
        "importing_coordination_run_id": str(handle.get("importing_coordination_run_id") or identity.get("coordination_run_id") or ""),
        "importing_root_task_run_id": str(handle.get("importing_root_task_run_id") or identity.get("root_task_run_id") or ""),
        "importing_stage_id": str(handle.get("importing_stage_id") or identity.get("stage_id") or ""),
        "importing_node_id": str(handle.get("importing_node_id") or identity.get("node_id") or ""),
        "importing_task_ref": str(identity.get("task_ref") or ""),
        "importing_work_order_id": str(identity.get("request_id") or ""),
        "importing_stage_request_ref": str(identity.get("request_id") or identity.get("idempotency_key") or ""),
    }
    graph_task_runtime.upsert_task_run(
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
