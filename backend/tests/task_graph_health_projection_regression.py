from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api import health_system as health_api
from runtime import TaskRunLoop
from runtime.graph_runtime.batch_runtime import (
    attach_batch_execution_request,
    bootstrap_batch_lifecycle_runtime_state,
    select_batch_for_stage,
    transition_batch_after_stage_result,
)
from runtime.graph_runtime.run_monitor import build_task_graph_run_monitor_view
from health_system.maintenance.test_system.task_graph_health import build_task_graph_health_projection
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphNodeDefinition


def _task_run() -> dict[str, object]:
    return {
        "task_run_id": "taskrun:health:graph",
        "session_id": "session:health",
        "status": "running",
        "graph_ref": "graph.health",
        "updated_at": 100.0,
    }


def _coordination_run() -> dict[str, object]:
    return {
        "coordination_run_id": "coordrun:health:graph",
        "task_run_id": "taskrun:health:graph",
        "graph_ref": "graph.health",
        "status": "running",
        "updated_at": 101.0,
    }


def _graph_spec() -> dict[str, object]:
    return {
        "graph_id": "graph.health",
        "title": "健康测试图",
        "nodes": [
            {"node_id": "draft", "title": "执行节点", "node_type": "agent"},
            {"node_id": "review", "title": "审核节点", "node_type": "review_gate"},
        ],
        "edges": [
            {"edge_id": "draft_review", "source_node_id": "draft", "target_node_id": "review"},
        ],
    }


def _parallel_batch_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.health.parallel_batch",
        title="健康批次图",
        graph_kind="multi_agent",
        publish_state="published",
        entry_node_id="produce",
        output_node_id="produce",
        runtime_policy={"coordinator_agent_id": "agent:coordinator"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="produce",
                node_type="agent",
                title="批次生产",
                task_id="task.health.produce",
                agent_id="agent:producer",
                contract_bindings={
                    "unit_batch": {"unit_kind": "item", "requested_count": 4, "range_start": 1},
                    "runtime": {
                        "split_policy": {
                            "mode": "static_batch",
                            "batch_size": 2,
                            "child_execution_mode": "parallel",
                            "max_parallel_batches": 1,
                        },
                        "batch_acceptance_policy": {"mode": "review_then_commit", "max_repair_rounds": 1},
                        "merge_policy": {"mode": "wait_all_committed"},
                    },
                },
            ),
        ),
    )


def test_task_graph_health_projection_promotes_monitor_issues_to_evidence_packet() -> None:
    monitor = build_task_graph_run_monitor_view(
        task_run=_task_run(),
        coordination_run=_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "active_stage_id": "draft",
            "running_nodes": ["draft"],
        },
        coordination_checkpoint={"checkpoint_id": "coordchk:health", "created_at": 101.0},
        task_checkpoint={"checkpoint_id": "taskchk:health", "created_at": 100.0},
    )

    projection = build_task_graph_health_projection(monitor)

    codes = {item["code"] for item in projection["issues"]}
    assert projection["authority"] == "health_system.task_graph_health_projection"
    assert projection["status"] == "failed"
    assert "node_running_without_execution_permit" in codes
    assert projection["evidence_packet"]["authority"] == "health_system.evidence_packet"
    assert any(item["event_type"] == "node_running_without_execution_permit" for item in projection["evidence_packet"]["selected_evidence"])
    assert any(item["kind"] == "coordination_checkpoint" for item in projection["recovery_handles"])


def test_task_graph_health_projection_reports_ignored_batch_execution_identity() -> None:
    spec = compile_task_graph_definition_runtime_spec(graph=_parallel_batch_graph())
    runtime_state = bootstrap_batch_lifecycle_runtime_state(runtime_spec_payload=spec.to_dict())
    runtime_state, first = select_batch_for_stage(runtime_state=runtime_state, stage_id="produce", node_id="produce")
    runtime_state = attach_batch_execution_request(
        runtime_state=runtime_state,
        batch_execution_id=str(first["active_execution_id"]),
        request_id="nodeexec:first",
        dispatch_event_id="tlevent:first",
    )
    runtime_state = transition_batch_after_stage_result(
        runtime_state=runtime_state,
        stage_id="produce",
        node_id="produce",
        accepted=True,
        task_result_ref="taskresult:stale",
        request_id="nodeexec:unknown",
    )
    monitor = build_task_graph_run_monitor_view(
        task_run=_task_run(),
        coordination_run=_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": spec.to_dict()},
            "batch_lifecycle_runtime_state": runtime_state,
            "stage_execution_request": {
                "request_id": "nodeexec:first",
                "stage_id": "produce",
                "node_id": "produce",
                "dispatch_context": {
                    "activation_id": "activation:first",
                    "execution_permit_id": "permit:first",
                    "dispatch_event_id": "tlevent:first",
                },
            },
        },
    )

    projection = build_task_graph_health_projection(monitor)

    issue = next(item for item in projection["issues"] if item["code"] == "batch_execution_identity_ignored")
    assert issue["severity"] == "error"
    assert issue["subject_type"] == "task_graph_execution"
    assert "nodeexec:unknown" in issue["evidence_refs"]
    assert projection["batch_health"]["diagnostics"]["last_transition_ignored"]["reason"] == "batch_execution_identity_not_found"


def test_health_api_exposes_task_graph_health_projection_from_runtime_loop(tmp_path: Path) -> None:
    graph = _parallel_batch_graph()
    loop = TaskRunLoop(tmp_path, backend_dir=Path("backend"))
    start = loop.start_task_graph_run(
        session_id="session:health-api",
        graph=graph,
        runtime_spec=compile_task_graph_definition_runtime_spec(graph=graph),
    )
    assert start.coordination_run is not None
    runtime = SimpleNamespace(base_dir=Path("backend"), query_runtime=SimpleNamespace(task_run_loop=loop))
    original = health_api.require_runtime
    health_api.require_runtime = lambda: runtime  # type: ignore[assignment]
    try:
        payload = asyncio.run(health_api.get_health_task_graph_run_health(start.task_run.task_run_id))
    finally:
        health_api.require_runtime = original  # type: ignore[assignment]

    assert payload["authority"] == "health_system.task_graph_health_projection"
    assert payload["task_run_id"] == start.task_run.task_run_id
    assert payload["coordination_run_id"] == start.coordination_run.coordination_run_id
    assert payload["graph"]["graph_id"] == graph.graph_id
    assert payload["batch_health"]["available"] is True
    assert payload["evidence_packet"]["authority"] == "health_system.evidence_packet"
