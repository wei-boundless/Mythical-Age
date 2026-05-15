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
    memory_operations = [
        _memory_operation(dict(item))
        for item in list(state.get("working_memory_operations") or [])
        if isinstance(item, dict)
    ][-50:]
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
            ),
        },
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
        "current_stage_execution_request": dict(state.get("stage_execution_request") or {}),
        "health": {
            "valid": not any(issue.get("severity") == "error" for issue in issues),
            "issues": issues,
        },
    }


def _monitor_node(node: dict[str, Any], statuses: dict[str, str]) -> dict[str, Any]:
    node_id = str(node.get("node_id") or node.get("id") or "")
    return {
        "node_id": node_id,
        "title": str(node.get("title") or node.get("label") or node_id),
        "node_type": str(node.get("node_type") or ""),
        "task_id": str(node.get("task_id") or ""),
        "agent_id": str(node.get("agent_id") or ""),
        "phase_id": str(node.get("phase_id") or ""),
        "sequence_index": int(node.get("sequence_index") or 0),
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
    if not dict(state.get("stage_execution_request") or {}) and not str(state.get("terminal_status") or ""):
        issues.append(_issue("warning", "stage_execution_request_missing", "Current stage execution request is missing.", "stage_execution_request"))
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
