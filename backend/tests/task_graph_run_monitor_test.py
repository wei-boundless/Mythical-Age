from __future__ import annotations

from runtime.graph_runtime.run_monitor import build_task_graph_run_monitor_view


def _base_task_run() -> dict[str, object]:
    return {
        "task_run_id": "taskrun:test:graph",
        "session_id": "session:test",
        "task_id": "task.test.graph",
        "status": "running",
        "graph_ref": "graph.test",
        "updated_at": 100.0,
        "diagnostics": {"project_id": "project:test"},
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
            "stage_execution_request": {
                "request_id": "nodeexec:outline",
                "stage_id": "outline",
                "node_id": "outline",
                "dispatch_context": {
                    "activation_id": "activation:outline",
                    "execution_permit_id": "permit:outline",
                    "dispatch_event_id": "tlevent:outline",
                },
            },
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
                    "created_at": 10.0,
                    "sequence_index": 1,
                },
                {
                    "operation": "write",
                    "stage_id": "world",
                    "node_id": "world",
                    "status": "completed",
                    "created_working_memory_refs": ["wm:world"],
                    "created_at": 20.0,
                    "sequence_index": 2,
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
    assert view["memory_operations"][0]["sequence_index"] == 1
    assert view["memory_operations"][1]["created_at"] == 20.0


def test_monitor_exposes_timeline_dispatch_packets_and_result_records() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "timeline": {
                "ledger_id": "tlledger:test",
                "current_clock_seq": 3,
                "event_count": 3,
                "recent_events": [
                    {"event_id": "tlevent:1", "clock_seq": 1, "event_type": "run_started", "scope_path": ["run"]},
                    {"event_id": "tlevent:2", "clock_seq": 2, "event_type": "node_dispatch_requested", "scope_path": ["run", "phase.plan"], "node_id": "world"},
                ],
            },
            "stage_execution_request": {
                "dispatch_context": {"dispatch_event_id": "tlevent:2", "clock_seq": 2, "scope_path": ["run", "phase.plan"]},
                "memory_snapshot": {"snapshot_id": "memsnap:test", "resolved_record_refs": ["wm:a"]},
                "artifact_context_packet": {"packet_id": "artctx:test", "artifact_refs": ["artifact:a.md"]},
                "revision_packet": {},
                "handoff_packet_refs": ["handoff:test"],
            },
            "timeline_result_records": [
                {"result_record_id": "tlresult:test", "stage_id": "world", "accepted": True},
            ],
        },
    )

    assert view["timeline"]["current_clock_seq"] == 3
    assert view["timeline"]["recent_events"][1]["event_type"] == "node_dispatch_requested"
    assert view["current_dispatch_context"]["dispatch_event_id"] == "tlevent:2"
    assert view["current_context_packets"]["memory_snapshot"]["snapshot_id"] == "memsnap:test"
    assert view["timeline_result_records"][0]["result_record_id"] == "tlresult:test"


def test_monitor_reports_completed_node_without_timeline_result() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "node_statuses": {"world": "completed", "outline": "pending"},
            "stage_results": {"world": {"accepted": True}},
        },
    )

    codes = {issue["code"] for issue in view["health"]["issues"]}
    assert "completed_without_timeline_result" in codes


def test_monitor_reports_running_node_without_execution_permit() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "active_stage_id": "outline",
            "running_nodes": ["outline"],
        },
    )

    codes = {issue["code"] for issue in view["health"]["issues"]}
    assert "node_running_without_execution_permit" in codes
    assert view["temporal"]["boundary_valid"] is False
    assert view["temporal"]["violations"][0]["code"] == "node_running_without_execution_permit"


def test_monitor_uses_tool_call_preview_when_stream_chunks_are_absent() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "stage_execution_request": {
                "stream_policy": {
                    "enabled": True,
                    "mode": "model_text_stream",
                    "monitor_visibility": "task_graph_monitor",
                }
            },
        },
        recent_events=[
            {
                "event_type": "tool_call_requested",
                "created_at": 123.0,
                "payload": {
                    "action_request": {
                        "request_id": "rtact:test",
                        "payload": {
                            "assistant_content_preview": "先整理世界观主干，再调用写入工具。",
                        },
                    }
                },
            }
        ],
    )

    assert view["streaming"]["enabled"] is True
    assert view["streaming"]["chunk_count"] == 1
    assert "世界观主干" in view["streaming"]["preview_text"]


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


def test_monitor_includes_project_progress_and_supervision_status() -> None:
    view = build_task_graph_run_monitor_view(
        task_run=_base_task_run(),
        coordination_run=_base_coordination_run(),
        coordination_state={"diagnostics": {"coordination_graph_spec": _graph_spec()}},
        project_ledger={
            "project_id": "project:test",
            "project_title": "洪荒时代",
            "graph_id": "graph.test",
            "metric_label": "words",
            "target_metric_total": 1000000,
            "committed_metric_total": 12000,
            "committed_unit_count": 3,
            "last_committed_unit_index": 3,
        },
        project_status={
            "project_id": "project:test",
            "project_runtime_status": "watching",
            "active_run_status": "running",
            "latest_event_at": 100.0,
            "last_effective_output_at": 99.0,
            "active_blocker": {"kind": "", "summary": ""},
            "recovery_state": {"summary": "none"},
        },
        supervision_records=[
            {
                "supervision_record_id": "supervision:test",
                "issue_type": "chapter_committed",
                "repair_action": "",
            }
        ],
    )

    assert view["project"]["project_id"] == "project:test"
    assert view["progress"]["completed_metric_total"] == 12000
    assert view["progress"]["remaining_metric_total"] == 988000
    assert view["supervision"]["project_runtime_status"] == "watching"


def test_monitor_prefers_failed_stage_error_details() -> None:
    task_run = _base_task_run()
    task_run["status"] = "failed"
    task_run["terminal_reason"] = "executor_failed"
    task_run["diagnostics"] = {}
    view = build_task_graph_run_monitor_view(
        task_run=task_run,
        coordination_run=_base_coordination_run(),
        coordination_state={
            "diagnostics": {"coordination_graph_spec": _graph_spec()},
            "failed_nodes": ["world"],
            "stage_results": {
                "world": {
                    "status": "failed",
                    "accepted": False,
                    "artifact_refs": [],
                    "task_result_ref": "taskresult:world",
                    "diagnostics": {
                        "last_error": {
                            "message": "upstream model timeout",
                            "detail": "request exceeded 300s",
                            "code": "timeout",
                            "provider": "deepseek",
                            "model": "deepseek-v4-pro",
                            "step_id": "understand_request",
                        }
                    },
                }
            },
        },
    )

    assert view["runtime"]["failure"]["message"] == "upstream model timeout"
    assert view["runtime"]["failure"]["detail"] == "request exceeded 300s"
    assert view["runtime"]["failure"]["stage_id"] == "world"
    assert view["runtime"]["failure"]["step_id"] == "understand_request"
