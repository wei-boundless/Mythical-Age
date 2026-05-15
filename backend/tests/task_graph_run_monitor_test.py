from __future__ import annotations

from orchestration.runtime_loop.task_graph_run_monitor import build_task_graph_run_monitor_view


def _base_task_run() -> dict[str, object]:
    return {
        "task_run_id": "taskrun:test:graph",
        "session_id": "session:test",
        "task_id": "task.test.graph",
        "status": "running",
        "graph_ref": "graph.test",
        "updated_at": 100.0,
    }


def _base_coordination_run() -> dict[str, object]:
    return {
        "coordination_run_id": "coordrun:test:graph",
        "task_run_id": "taskrun:test:graph",
        "graph_ref": "graph.test",
        "status": "running",
        "updated_at": 101.0,
    }


def _graph_spec() -> dict[str, object]:
    return {
        "graph_id": "graph.test",
        "title": "测试任务图",
        "nodes": [
            {"node_id": "world", "title": "世界观", "agent_id": "agent:world", "sequence_index": 1},
            {"node_id": "outline", "title": "大纲", "agent_id": "agent:outline", "sequence_index": 2},
            {"node_id": "chapter", "title": "章节", "agent_id": "agent:chapter", "sequence_index": 3},
        ],
        "edges": [
            {"edge_id": "edge:world-outline", "source_node_id": "world", "target_node_id": "outline", "edge_type": "handoff"},
            {"edge_id": "edge:outline-chapter", "source_node_id": "outline", "target_node_id": "chapter", "edge_type": "handoff"},
        ],
    }


def test_monitor_topology_comes_from_graph_spec_even_without_flow_stages() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {
                "coordination_graph_spec": _graph_spec(),
            },
            "active_stage_id": "outline",
            "completed_nodes": ["world"],
            "blocked_nodes": ["chapter"],
        },
        event_count=7,
    )

    assert view["authority"] == "task_graph.run_monitor"
    assert view["graph"]["graph_id"] == "graph.test"
    assert view["graph"]["node_count"] == 3
    assert view["graph"]["edge_count"] == 2
    assert [node["node_id"] for node in view["topology"]["nodes"]] == ["world", "outline", "chapter"]
    assert [edge["edge_id"] for edge in view["topology"]["edges"]] == ["edge:world-outline", "edge:outline-chapter"]
    assert view["state"]["node_statuses"]["world"] == "completed"
    assert view["state"]["node_statuses"]["outline"] == "running"
    assert view["state"]["node_statuses"]["chapter"] == "blocked"
    assert view["health"]["valid"] is True


def test_monitor_preserves_artifact_and_memory_operation_producers() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "stage_results": {
                "world": {
                    "status": "completed",
                    "accepted": True,
                    "artifact_refs": ["artifact:world.md"],
                    "task_result_ref": "taskresult:world",
                    "working_memory_refs": ["wm:world"],
                }
            },
            "working_memory_operations": [
                {
                    "operation": "read",
                    "stage_id": "outline",
                    "node_id": "outline",
                    "status": "completed",
                    "selected_working_memory_refs": ["wm:world"],
                },
                {
                    "operation": "write",
                    "stage_id": "world",
                    "node_id": "world",
                    "status": "completed",
                    "created_working_memory_refs": ["wm:world"],
                },
            ],
        },
    )

    assert view["artifacts"] == [
        {
            "artifact_ref": "artifact:world.md",
            "producer_node_id": "world",
            "kind": "artifact_ref",
        }
    ]
    assert view["stage_results"][0]["node_id"] == "world"
    assert view["stage_results"][0]["working_memory_refs"] == ["wm:world"]
    assert [item["operation"] for item in view["memory_operations"]] == ["read", "write"]
    assert view["memory_operations"][0]["refs"] == ["wm:world"]


def test_monitor_health_reports_invalid_edge_endpoints() -> None:
    graph_spec = _graph_spec()
    graph_spec["edges"] = [
        {"edge_id": "edge:missing", "source_node_id": "world", "target_node_id": "missing"}
    ]
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {
                "coordination_graph_spec": graph_spec,
            },
        },
    )

    assert view["health"]["valid"] is False
    assert any(issue["code"] == "edge_endpoint_missing" for issue in view["health"]["issues"])


def test_monitor_includes_failure_details_from_task_diagnostics() -> None:
    task_run = _base_task_run()
    task_run["status"] = "failed"
    task_run["terminal_reason"] = "executor_failed"
    task_run["diagnostics"] = {
        "last_error": {
            "message": "模型配置有误，请检查提供商和密钥设置。",
            "detail": "401 Unauthorized from upstream provider",
            "code": "configuration",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "step_id": "understand_request",
        }
    }
    view = build_task_graph_run_monitor_view(
        task_run=task_run,
        coordination_run=_base_coordination_run(),
        coordination_state={"diagnostics": {"coordination_graph_spec": _graph_spec()}},
    )

    assert view["runtime"]["failure"]["message"] == "模型配置有误，请检查提供商和密钥设置。"
    assert view["runtime"]["failure"]["detail"] == "401 Unauthorized from upstream provider"
    assert view["runtime"]["failure"]["provider"] == "deepseek"
