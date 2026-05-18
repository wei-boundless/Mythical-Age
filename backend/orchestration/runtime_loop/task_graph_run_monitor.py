from __future__ import annotations

from typing import Any


def build_task_graph_run_monitor_view(
    *,
    task_run: dict[str, Any],
    coordination_run: dict[str, Any] | None,
    coordination_state: dict[str, Any],
    coordination_checkpoint: dict[str, Any] | None = None,
    task_checkpoint: dict[str, Any] | None = None,
    event_count: int = 0,
    source: str = "task_run",
    project_ledger: dict[str, Any] | None = None,
    project_status: dict[str, Any] | None = None,
    supervision_records: list[dict[str, Any]] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the canonical TaskGraph run monitor view.

    Topology always comes from the TaskGraph runtime spec stored in the
    coordination checkpoint. Runtime status overlays that topology; it never
    replaces it.
    """

    task = dict(task_run or {})
    coord = dict(coordination_run or {})
    state = dict(coordination_state or {})
    diagnostics = dict(state.get("diagnostics") or {})
    graph_spec = dict(
        diagnostics.get("coordination_graph_spec")
        or dict(coord.get("diagnostics") or {}).get("coordination_graph_spec")
        or {}
    )
    scheduler_state = dict(
        state.get("task_graph_scheduler_state")
        or diagnostics.get("task_graph_scheduler_state")
        or dict(coord.get("diagnostics") or {}).get("task_graph_scheduler_state")
        or {}
    )
    node_statuses = _node_statuses_from_state(state=state, scheduler_state=scheduler_state)
    topology_nodes = [_monitor_node(dict(item), node_statuses) for item in list(graph_spec.get("nodes") or [])]
    node_ids = {str(item.get("node_id") or "") for item in topology_nodes if str(item.get("node_id") or "")}
    topology_edges = [
        _monitor_edge(dict(item), node_statuses=node_statuses)
        for item in list(graph_spec.get("edges") or [])
    ]
    stage_results = _stage_results(dict(state.get("stage_results") or {}))
    artifacts = _artifact_refs(stage_results)
    memory_operations = sorted(
        [
        _memory_operation(dict(item))
        for item in list(state.get("working_memory_operations") or [])
        if isinstance(item, dict)
        ],
        key=lambda item: (
            float(item.get("created_at") or 0.0),
            int(item.get("sequence_index") or 0),
            str(item.get("stage_id") or ""),
        ),
    )[-50:]
    failure = _failure_details(task=task, coord=coord, state=state)
    active_node_id = str(state.get("active_stage_id") or state.get("active_node_id") or "")
    issues = _health_issues(
        graph_spec=graph_spec,
        node_ids=node_ids,
        edges=topology_edges,
        active_node_id=active_node_id,
        state=state,
    )
    graph_id = str(graph_spec.get("graph_id") or graph_spec.get("graph_ref") or coord.get("graph_ref") or task.get("graph_ref") or "")
    checkpoint_payload = dict(coordination_checkpoint or {})
    task_checkpoint_payload = dict(task_checkpoint or {})
    project_progress = dict(project_ledger or {})
    project_runtime_status = dict(project_status or {})
    target_metric_total = int(
        project_progress.get("target_metric_total")
        or project_progress.get("target_words")
        or project_runtime_status.get("target_metric_total")
        or project_runtime_status.get("target_words")
        or 0
    )
    completed_metric_total = int(
        project_progress.get("committed_metric_total")
        or project_progress.get("committed_words_total")
        or project_runtime_status.get("completed_metric_total")
        or project_runtime_status.get("completed_words_total")
        or 0
    )
    committed_unit_count = int(
        project_progress.get("committed_unit_count")
        or project_progress.get("committed_chapter_count")
        or project_runtime_status.get("committed_unit_count")
        or project_runtime_status.get("committed_chapter_count")
        or 0
    )
    last_committed_unit_index = int(
        project_progress.get("last_committed_unit_index")
        or project_progress.get("last_committed_chapter_index")
        or project_runtime_status.get("last_committed_unit_index")
        or project_runtime_status.get("last_committed_chapter_index")
        or 0
    )
    supervision_items = [dict(item) for item in list(supervision_records or []) if isinstance(item, dict)]
    latest_supervision = dict(supervision_items[-1] or {}) if supervision_items else {}
    stage_request = dict(state.get("node_execution_request") or state.get("stage_execution_request") or {})
    active_node = next(
        (
            dict(item)
            for item in list(graph_spec.get("nodes") or [])
            if str(item.get("node_id") or "") == active_node_id
        ),
        {},
    )
    runtime_assembly = dict(stage_request.get("runtime_assembly") or {})
    runtime_assembly_metadata = dict(runtime_assembly.get("metadata") or {})
    runtime_assembly_diagnostics = dict(runtime_assembly.get("diagnostics") or {})
    timeline = _timeline_view(dict(state.get("timeline") or {}))
    dispatch_context = dict(stage_request.get("dispatch_context") or {})
    node_execution_boundary = _node_execution_boundary_from_request(stage_request)
    context_packets = {
        "memory_snapshot": dict(stage_request.get("memory_snapshot") or {}),
        "artifact_context_packet": dict(stage_request.get("artifact_context_packet") or {}),
        "revision_packet": dict(stage_request.get("revision_packet") or {}),
        "handoff_packet_refs": _string_list(stage_request.get("handoff_packet_refs")),
        "standard_input_package": dict(stage_request.get("standard_input_package") or {}),
        "human_work_packet": dict(stage_request.get("human_work_packet") or {}),
    }
    if not dict(stage_request.get("stream_policy") or {}):
        synthesized_stream_policy = (
            dict(runtime_assembly_metadata.get("stream_policy") or {})
            or dict(runtime_assembly_diagnostics.get("stream_policy") or {})
            or dict(active_node.get("stream_policy") or {})
        )
        if synthesized_stream_policy:
            stage_request["stream_policy"] = synthesized_stream_policy
    stream_preview = _stream_preview(
        recent_events or [],
        configured_policy=dict(stage_request.get("stream_policy") or {}),
    )
    return {
        "authority": "task_graph.run_monitor",
        "source": source,
        "session_id": str(task.get("session_id") or ""),
        "task_run_id": str(task.get("task_run_id") or ""),
        "coordination_run_id": str(coord.get("coordination_run_id") or state.get("coordination_run_id") or ""),
        "graph": {
            "graph_id": graph_id,
            "title": str(graph_spec.get("title") or graph_spec.get("graph_title") or graph_id),
            "node_count": len(topology_nodes),
            "edge_count": len(topology_edges),
        },
        "runtime": {
            "status": str(coord.get("status") or task.get("status") or state.get("terminal_status") or "unknown"),
            "terminal_status": str(state.get("terminal_status") or ""),
            "terminal_reason": str(task.get("terminal_reason") or dict(coord.get("diagnostics") or {}).get("terminal_reason") or ""),
            "failure": failure,
            "active_node_id": active_node_id,
            "active_task_ref": str(state.get("active_task_ref") or ""),
            "last_event_offset": int(task.get("latest_event_offset") or task_checkpoint_payload.get("event_offset") or event_count or 0),
            "event_count": int(event_count or 0),
            "checkpoint_ref": str(checkpoint_payload.get("checkpoint_id") or coord.get("latest_checkpoint_ref") or ""),
            "checkpoint_updated_at": float(checkpoint_payload.get("created_at") or 0.0),
            "task_checkpoint_ref": str(task_checkpoint_payload.get("checkpoint_id") or task.get("latest_checkpoint_ref") or ""),
            "updated_at": max(
                float(task.get("updated_at") or 0.0),
                float(coord.get("updated_at") or 0.0),
                float(checkpoint_payload.get("created_at") or 0.0),
                float(stream_preview.get("latest_chunk_at") or 0.0),
            ),
        },
        "project": {
            "project_id": str(project_progress.get("project_id") or project_runtime_status.get("project_id") or dict(task.get("diagnostics") or {}).get("project_id") or ""),
            "project_title": str(project_progress.get("project_title") or project_runtime_status.get("project_title") or ""),
            "graph_id": str(project_progress.get("graph_id") or project_runtime_status.get("graph_id") or graph_id),
        },
        "progress": {
            "metric_label": str(project_progress.get("metric_label") or project_runtime_status.get("metric_label") or "units"),
            "target_metric_total": target_metric_total,
            "completed_metric_total": completed_metric_total,
            "committed_unit_count": committed_unit_count,
            "last_committed_unit_index": last_committed_unit_index,
            "remaining_metric_total": max(
                target_metric_total - completed_metric_total,
                0,
            ),
        },
        "supervision": {
            "project_runtime_status": str(project_runtime_status.get("project_runtime_status") or ""),
            "active_run_status": str(project_runtime_status.get("active_run_status") or ""),
            "latest_artifact_root": str(project_runtime_status.get("latest_artifact_root") or ""),
            "latest_event_at": float(project_runtime_status.get("latest_event_at") or 0.0),
            "last_effective_output_at": float(project_runtime_status.get("last_effective_output_at") or 0.0),
            "latest_record": latest_supervision,
            "record_count": len(supervision_items),
        },
        "blocker": dict(project_runtime_status.get("active_blocker") or {}),
        "repair": dict(project_runtime_status.get("recovery_state") or {}),
        "topology": {
            "nodes": topology_nodes,
            "edges": topology_edges,
        },
        "state": {
            "node_statuses": node_statuses,
            "edge_statuses": {str(edge.get("edge_id") or ""): str(edge.get("status") or "") for edge in topology_edges},
            "ready_node_ids": _string_list(state.get("ready_nodes") or scheduler_state.get("ready_nodes")),
            "running_node_ids": _string_list(state.get("running_nodes") or scheduler_state.get("running_nodes")),
            "completed_node_ids": _string_list(state.get("completed_nodes") or scheduler_state.get("completed_nodes")),
            "failed_node_ids": _string_list(state.get("failed_nodes") or scheduler_state.get("failed_nodes")),
            "blocked_node_ids": _string_list(state.get("blocked_nodes") or scheduler_state.get("blocked_nodes")),
            "waiting_node_ids": _string_list(state.get("waiting_nodes") or scheduler_state.get("waiting_nodes")),
        },
        "artifacts": artifacts,
        "memory_operations": memory_operations,
        "stage_results": stage_results,
        "current_node_execution_request": stage_request,
        "current_stage_execution_request": stage_request,
        "current_node_execution_boundary": node_execution_boundary,
        "current_dispatch_context": dispatch_context,
        "current_context_packets": context_packets,
        "current_standard_input_package": dict(stage_request.get("standard_input_package") or {}),
        "current_human_work_packet": dict(stage_request.get("human_work_packet") or {}),
        "timeline_result_records": _timeline_result_records(state),
        "timeline": timeline,
        "temporal": {
            "active_node_id": active_node_id,
            "active_activation_id": str(node_execution_boundary.get("activation_id") or ""),
            "active_execution_permit_id": str(node_execution_boundary.get("execution_permit_id") or ""),
            "active_request_id": str(node_execution_boundary.get("request_id") or ""),
            "boundary_valid": bool(node_execution_boundary.get("valid") is True),
            "violations": _temporal_violations(state=state, boundary=node_execution_boundary),
            "authority": "task_graph.temporal_monitor_view",
        },
        "current_stage_timeline": dict(runtime_assembly_metadata.get("execution_timeline") or {}),
        "streaming": stream_preview,
        "health": {
            "valid": not any(issue.get("severity") == "error" for issue in issues),
            "issues": issues,
        },
    }


def _monitor_node(node: dict[str, Any], statuses: dict[str, str]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or node.get("id") or "")
    metadata = dict(node.get("metadata") or {})
    return {
        "node_id": node_id,
        "title": str(node.get("title") or node.get("label") or node_id),
        "node_type": str(node.get("node_type") or ""),
        "task_id": str(node.get("task_id") or ""),
        "agent_id": str(node.get("agent_id") or ""),
        "execution_mode": str(node.get("execution_mode") or ""),
        "phase_id": str(node.get("phase_id") or ""),
        "sequence_index": int(node.get("sequence_index") or 0),
        "monitor_policy": dict(node.get("monitor_policy") or metadata.get("monitor_policy") or {}),
        "background_policy": dict(node.get("background_policy") or metadata.get("background_policy") or {}),
        "notification_policy": dict(node.get("notification_policy") or metadata.get("notification_policy") or {}),
        "metadata": metadata,
        "status": statuses.get(node_id, "pending"),
        "artifact_refs": [],
        "last_result_ref": "",
    }


def _monitor_edge(edge: dict[str, Any], *, node_statuses: dict[str, str]) -> dict[str, Any]:
    source = str(edge.get("source_node_id") or edge.get("from_node_id") or edge.get("from") or edge.get("source") or "")
    target = str(edge.get("target_node_id") or edge.get("to_node_id") or edge.get("to") or edge.get("target") or "")
    return {
        "edge_id": str(edge.get("edge_id") or f"{source}->{target}"),
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": str(edge.get("edge_type") or edge.get("mode") or ""),
        "payload_contract_id": str(edge.get("payload_contract_id") or ""),
        "status": _edge_status(node_statuses.get(source, ""), node_statuses.get(target, "")),
    }


def _node_statuses_from_state(*, state: dict[str, Any], scheduler_state: dict[str, Any]) -> dict[str, str]:
    statuses = {str(key): str(value) for key, value in dict(scheduler_state.get("node_statuses") or {}).items() if str(key)}
    for node_id in _string_list(state.get("ready_nodes") or scheduler_state.get("ready_nodes")):
        statuses[node_id] = "ready"
    for node_id in _string_list(state.get("blocked_nodes") or scheduler_state.get("blocked_nodes")):
        statuses[node_id] = "blocked"
    for node_id in _string_list(state.get("waiting_nodes") or scheduler_state.get("waiting_nodes")):
        statuses[node_id] = "waiting"
    for node_id in _string_list(state.get("completed_nodes") or scheduler_state.get("completed_nodes")):
        statuses[node_id] = "completed"
    for node_id in _string_list(state.get("failed_nodes") or scheduler_state.get("failed_nodes")):
        statuses[node_id] = "failed"
    active = str(state.get("active_stage_id") or state.get("active_node_id") or "")
    if active and statuses.get(active) not in {"completed", "failed"}:
        statuses[active] = "running"
    return statuses


def _edge_status(source_status: str, target_status: str) -> str:
    if source_status == "failed" or target_status == "failed":
        return "failed"
    if source_status == "completed" and target_status == "completed":
        return "completed"
    if source_status == "running" or target_status == "running":
        return "running"
    if source_status == "blocked" or target_status == "blocked":
        return "blocked"
    if source_status == "ready" or target_status == "ready":
        return "ready"
    return "idle"


def _stage_results(results: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for stage_id, raw in results.items():
        item = dict(raw or {})
        payloads.append(
            {
                "node_id": str(stage_id),
                "status": str(item.get("status") or "completed"),
                "accepted": bool(item.get("accepted") is True),
                "artifact_refs": _string_list(item.get("artifact_refs")),
                "task_result_ref": str(item.get("task_result_ref") or ""),
                "agent_run_result_ref": str(item.get("agent_run_result_ref") or ""),
                "working_memory_refs": _string_list(item.get("working_memory_refs")),
                "timeline_result_record": dict(item.get("timeline_result_record") or {}),
                "diagnostics": dict(item.get("diagnostics") or {}),
            }
        )
    return payloads


def _artifact_refs(stage_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for result in stage_results:
        producer = str(result.get("node_id") or "")
        for ref in _string_list(result.get("artifact_refs")):
            key = (producer, ref)
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(
                {
                    "artifact_ref": ref,
                    "producer_node_id": producer,
                    "kind": "artifact_ref",
                }
            )
    return artifacts


def _failure_details(*, task: dict[str, Any], coord: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(task.get("diagnostics") or {})
    state_diagnostics = dict(state.get("diagnostics") or {})
    coord_diagnostics = dict(coord.get("diagnostics") or {})
    stage_results = dict(state.get("stage_results") or {})
    failed_stage_errors: list[dict[str, Any]] = []
    for stage_id in _string_list(state.get("failed_nodes")):
        result = dict(stage_results.get(stage_id) or {})
        result_diagnostics = dict(result.get("diagnostics") or {})
        stage_error = dict(result_diagnostics.get("last_error") or {})
        if stage_error:
            stage_error.setdefault("step_id", str(stage_error.get("step_id") or ""))
            stage_error.setdefault("source", str(stage_error.get("source") or ""))
            stage_error["stage_id"] = stage_id
            failed_stage_errors.append(stage_error)
    last_error = dict(
        (failed_stage_errors[0] if failed_stage_errors else {})
        or diagnostics.get("last_error")
        or state_diagnostics.get("last_error")
        or coord_diagnostics.get("last_error")
        or {}
    )
    if not last_error and str(task.get("terminal_reason") or "") != "executor_failed":
        return {}
    return {
        "message": str(last_error.get("message") or ""),
        "detail": str(last_error.get("detail") or ""),
        "code": str(last_error.get("code") or ""),
        "provider": str(last_error.get("provider") or ""),
        "model": str(last_error.get("model") or ""),
        "source": str(last_error.get("source") or ""),
        "stage_id": str(last_error.get("stage_id") or ""),
        "step_id": str(last_error.get("step_id") or state.get("current_step_id") or ""),
        "observation_ref": str(last_error.get("observation_ref") or ""),
    }


def _memory_operation(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": str(operation.get("operation") or ""),
        "stage_id": str(operation.get("stage_id") or ""),
        "node_id": str(operation.get("node_id") or ""),
        "edge_id": str(operation.get("edge_id") or ""),
        "status": str(operation.get("status") or "completed"),
        "refs": _string_list(operation.get("created_working_memory_refs"))
        + _string_list(operation.get("selected_working_memory_refs"))
        + _string_list(operation.get("accepted_working_memory_refs")),
        "transaction_ref": str(operation.get("handoff_transaction_ref") or ""),
        "finalization_ref": str(operation.get("finalization_ref") or ""),
        "created_at": float(operation.get("created_at") or 0.0),
        "sequence_index": int(operation.get("sequence_index") or 0),
        "timeline_kind": str(operation.get("timeline_kind") or ""),
    }


def _timeline_result_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = [dict(item) for item in list(state.get("timeline_result_records") or []) if isinstance(item, dict)]
    if explicit:
        return explicit[-80:]
    records: list[dict[str, Any]] = []
    for item in list(dict(state.get("stage_results") or {}).values()):
        record = dict(dict(item or {}).get("timeline_result_record") or {})
        if record:
            records.append(record)
    return records[-80:]


def _timeline_view(timeline: dict[str, Any]) -> dict[str, Any]:
    events = [dict(item) for item in list(timeline.get("recent_events") or []) if isinstance(item, dict)]
    return {
        "ledger_id": str(timeline.get("ledger_id") or ""),
        "coordination_run_id": str(timeline.get("coordination_run_id") or ""),
        "root_task_run_id": str(timeline.get("root_task_run_id") or ""),
        "graph_id": str(timeline.get("graph_id") or ""),
        "current_clock_seq": int(timeline.get("current_clock_seq") or 0),
        "event_count": int(timeline.get("event_count") or len(events)),
        "recent_events": events[-80:],
        "updated_at": float(timeline.get("updated_at") or 0.0),
        "authority": str(timeline.get("authority") or "task_graph.timeline_ledger"),
    }


def _health_issues(
    *,
    graph_spec: dict[str, Any],
    node_ids: set[str],
    edges: list[dict[str, Any]],
    active_node_id: str,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not graph_spec:
        issues.append(_issue("error", "graph_spec_missing", "Coordination graph spec is missing.", "coordination_graph_spec"))
    if not node_ids:
        issues.append(_issue("error", "topology_nodes_missing", "TaskGraph monitor has no topology nodes.", "topology.nodes"))
    if graph_spec and list(graph_spec.get("edges") or []) and not edges:
        issues.append(_issue("error", "topology_edges_missing", "TaskGraph spec has edges, but monitor topology has none.", "topology.edges"))
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source not in node_ids or target not in node_ids:
            issues.append(_issue("error", "edge_endpoint_missing", "Edge endpoint is not present in topology nodes.", edge_id))
    if active_node_id and active_node_id not in node_ids:
        issues.append(_issue("error", "active_node_missing", "Active node is not present in topology nodes.", active_node_id))
    current_request = dict(state.get("node_execution_request") or state.get("stage_execution_request") or {})
    if not current_request and not str(state.get("terminal_status") or ""):
        issues.append(_issue("warning", "node_execution_request_missing", "Current node execution request is missing.", "node_execution_request"))
    boundary = _node_execution_boundary_from_request(current_request)
    issues.extend(_temporal_violations(state=state, boundary=boundary))
    issues.extend(_timeline_integrity_issues(state))
    return issues


def _node_execution_boundary_from_request(request: dict[str, Any]) -> dict[str, Any]:
    payload = dict(request or {})
    dispatch_context = dict(payload.get("dispatch_context") or {})
    standard_input = dict(payload.get("standard_input_package") or {})
    activation_id = _first_string(dispatch_context.get("activation_id"), standard_input.get("activation_id"), payload.get("activation_id"))
    execution_permit_id = _first_string(dispatch_context.get("execution_permit_id"), standard_input.get("execution_permit_id"), payload.get("execution_permit_id"))
    request_id = _first_string(payload.get("request_id"), standard_input.get("request_id"))
    node_id = _first_string(payload.get("node_id"), dispatch_context.get("node_id"), standard_input.get("node_id"), payload.get("stage_id"))
    missing = [
        key
        for key, value in {
            "activation_id": activation_id,
            "execution_permit_id": execution_permit_id,
            "request_id": request_id,
            "node_id": node_id,
        }.items()
        if not value
    ]
    return {
        "activation_id": activation_id,
        "execution_permit_id": execution_permit_id,
        "request_id": request_id,
        "node_id": node_id,
        "stage_id": _first_string(payload.get("stage_id"), dispatch_context.get("stage_id"), standard_input.get("stage_id")),
        "dispatch_event_id": _first_string(payload.get("dispatch_event_id"), dispatch_context.get("dispatch_event_id")),
        "valid": not missing,
        "missing": missing,
        "authority": "task_graph.node_execution_boundary",
    }


def _temporal_violations(*, state: dict[str, Any], boundary: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    terminal_status = str(state.get("terminal_status") or "")
    running_nodes = set(_string_list(state.get("running_nodes")))
    node_statuses = {str(key): str(value) for key, value in dict(state.get("node_statuses") or {}).items() if str(key)}
    running_nodes.update(node_id for node_id, status in node_statuses.items() if status == "running")
    active = str(state.get("active_stage_id") or state.get("active_node_id") or "")
    if active and not terminal_status:
        running_nodes.add(active)
    if running_nodes and boundary.get("valid") is not True and not terminal_status:
        violations.append(
            _issue(
                "error",
                "node_running_without_execution_permit",
                "Running node has no valid activation and execution permit boundary.",
                ",".join(sorted(running_nodes)),
            )
        )
    boundary_node = str(boundary.get("node_id") or "")
    if boundary_node and running_nodes and boundary_node not in running_nodes and not terminal_status:
        violations.append(
            _issue(
                "warning",
                "execution_permit_node_mismatch",
                "Active execution permit belongs to a node outside the current running node set.",
                boundary_node,
            )
        )
    return violations


def _timeline_integrity_issues(state: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    node_statuses = {str(key): str(value) for key, value in dict(state.get("node_statuses") or {}).items() if str(key)}
    stage_results = dict(state.get("stage_results") or {})
    records = [dict(item) for item in list(state.get("timeline_result_records") or []) if isinstance(item, dict)]
    result_record_index = {
        str(key): dict(value)
        for key, value in dict(state.get("result_record_index") or {}).items()
        if str(key) and isinstance(value, dict)
    }
    for node_id, status in node_statuses.items():
        if status != "completed":
            continue
        result = dict(stage_results.get(node_id) or {})
        record = dict(result.get("timeline_result_record") or {})
        if not record:
            issues.append(_issue("error", "completed_without_timeline_result", "Completed node has no accepted timeline result record.", node_id))
            continue
        if record.get("accepted") is not True:
            issues.append(_issue("error", "completed_with_unaccepted_timeline_result", "Completed node points to a non-accepted timeline result record.", node_id))
    for record in records:
        record_id = str(record.get("result_record_id") or "")
        if record_id and record_id not in result_record_index:
            issues.append(_issue("warning", "timeline_result_not_indexed", "Timeline result record is not present in result_record_index.", record_id))
        if record.get("accepted") is True and int(record.get("effective_from_clock_seq") or 0) <= 0:
            issues.append(_issue("error", "accepted_timeline_result_not_effective", "Accepted timeline result has no effective clock.", record_id))
        coordinate = dict(record.get("timeline_coordinate") or {})
        if not str(coordinate.get("dispatch_event_id") or record.get("dispatch_event_id") or ""):
            issues.append(_issue("error", "timeline_result_without_dispatch", "Timeline result record is missing dispatch identity.", record_id))
    scheduler_state = dict(dict(state.get("diagnostics") or {}).get("task_graph_scheduler_state") or {})
    for node_state in list(scheduler_state.get("node_states") or []):
        if not isinstance(node_state, dict):
            continue
        for reason in _string_list(node_state.get("blocked_reasons")):
            if reason.startswith("timeline_result_"):
                issues.append(_issue("error", reason.split(":", 1)[0], reason, str(node_state.get("node_id") or "")))
    artifact_packet = dict(dict(state.get("stage_execution_request") or {}).get("artifact_context_packet") or {})
    for missing in _string_list(artifact_packet.get("missing_required_artifacts")):
        if missing.startswith("timeline_result:"):
            issues.append(_issue("error", "artifact_context_missing_timeline_result", "Current context packet is missing a required timeline result.", missing))
    return issues


def _issue(severity: str, code: str, message: str, target_id: str) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "target_id": target_id,
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


def _first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stream_preview(
    events: list[dict[str, Any]],
    *,
    configured_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured = dict(configured_policy or {})
    chunks = [
        dict(item)
        for item in list(events or [])
        if str(dict(item).get("event_type") or "") == "model_item_received"
    ]
    if not chunks:
        tool_call_previews = []
        for item in list(events or []):
            event = dict(item)
            if str(event.get("event_type") or "") != "tool_call_requested":
                continue
            action_request = dict(dict(event.get("payload") or {}).get("action_request") or {})
            payload = dict(action_request.get("payload") or {})
            preview = str(payload.get("assistant_content_preview") or payload.get("assistant_reasoning_preview") or "").strip()
            if preview:
                tool_call_previews.append(
                    {
                        "preview": preview,
                        "created_at": float(event.get("created_at") or 0.0),
                        "request_ref": str(action_request.get("request_id") or ""),
                    }
                )
        if tool_call_previews:
            preview_text = "".join(item["preview"] for item in tool_call_previews[-4:])
            if len(preview_text) > 4000:
                preview_text = preview_text[-4000:]
            latest = tool_call_previews[-1]
            return {
                "enabled": bool(configured.get("enabled") is True),
                "mode": str(configured.get("mode") or "model_text_stream"),
                "monitor_visibility": str(configured.get("monitor_visibility") or "task_graph_monitor"),
                "chunk_count": len(tool_call_previews),
                "accumulated_chars": len(preview_text),
                "latest_chunk_at": float(latest.get("created_at") or 0.0),
                "preview_text": preview_text,
                "active_stream_ref": str(latest.get("request_ref") or ""),
            }
        return {
            "enabled": bool(configured.get("enabled") is True),
            "mode": str(configured.get("mode") or "disabled"),
            "monitor_visibility": str(configured.get("monitor_visibility") or "none"),
            "chunk_count": 0,
            "accumulated_chars": 0,
            "latest_chunk_at": 0.0,
            "preview_text": "",
            "active_stream_ref": "",
        }
    latest = chunks[-1]
    previews = [str(dict(item.get("payload") or {}).get("delta_preview") or "") for item in chunks[-12:]]
    preview_text = "".join(previews)
    if len(preview_text) > 4000:
        preview_text = preview_text[-4000:]
    latest_payload = dict(latest.get("payload") or {})
    return {
        "enabled": True,
        "mode": str(configured.get("mode") or "model_text_stream"),
        "monitor_visibility": str(configured.get("monitor_visibility") or "task_graph_monitor"),
        "chunk_count": len(chunks),
        "accumulated_chars": int(latest_payload.get("accumulated_chars") or 0),
        "latest_chunk_at": float(latest.get("created_at") or 0.0),
        "preview_text": preview_text,
        "active_stream_ref": str(latest_payload.get("stream_ref") or ""),
    }
