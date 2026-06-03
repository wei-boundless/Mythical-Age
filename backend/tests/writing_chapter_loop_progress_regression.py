from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.loop import GraphLoop
from harness.graph.models import GraphHarnessConfig, GraphNodeWorkOrder
from harness.graph.work_order_executor import GraphNodeWorkOrderExecutor
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition
from tests.graph_harness_api_regression import _runtime_with_graph_harness


def _chapter_loop_config():
    graph = TaskGraphDefinition(
        graph_id="graph.test.writing_chapter_receipt_loop",
        title="Writing Chapter Receipt Loop",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="chapter_outline",
        output_node_id="volume_review",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        loop_frames=(
            {
                "frame_id": "loop.chapter_batch",
                "scope_id": "loop.chapter_batch",
                "entry_node_id": "chapter_outline",
                "router_node_id": "chapter_progress_router",
                "continue_node_id": "chapter_outline",
                "exit_node_id": "volume_review",
                "initial_inputs": {
                    "volume_index": 1,
                    "chapter_index": 1,
                    "batch_start_index": 1,
                    "batch_end_index": 10,
                    "batch_chapter_range": "001-010",
                    "active_chapter_start_index": 1,
                    "active_chapter_end_index": 10,
                    "active_chapter_range": "001-010",
                    "units_per_batch": 10,
                    "unit_target_measure": 2000,
                    "batch_target_measure": 20000,
                    "group_current_measure": 0,
                    "group_target_measure": 200000,
                    "total_current_measure": 0,
                    "target_measure_units": 1000000,
                },
                "derived_fields": _chapter_derived_fields(),
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="chapter_outline",
                node_type="agent",
                title="Outline",
                task_id="task.test.chapter.outline",
                agent_id="agent:0",
                loop={"scope_id": "loop.chapter_batch"},
            ),
            TaskGraphNodeDefinition(
                node_id="memory_commit_chapter",
                node_type="agent",
                title="Commit",
                task_id="task.test.chapter.commit",
                agent_id="agent:0",
                metadata={"progress_receipt_policy": {"progress_receipt_key": "chapter_progress_receipt"}},
                loop={"scope_id": "loop.chapter_batch"},
            ),
            TaskGraphNodeDefinition(
                node_id="chapter_progress_router",
                node_type="agent",
                title="Router",
                task_id="task.test.chapter.router",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.chapter_batch",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.chapter_batch",
                        "continue_node_id": "chapter_outline",
                        "exit_node_id": "volume_review",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["memory_commit_chapter"],
                        "current_key": "group_current_measure",
                        "target_key": "group_target_measure",
                        "last_metric_key": "last_batch_words",
                        "secondary_counters": [{"current_key": "total_current_measure"}],
                        "derived_fields": _chapter_derived_fields(),
                    },
                },
            ),
            TaskGraphNodeDefinition(
                node_id="volume_review",
                node_type="agent",
                title="Volume Review",
                task_id="task.test.volume.review",
                agent_id="agent:0",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.outline.commit", source_node_id="chapter_outline", target_node_id="memory_commit_chapter", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.commit.router", source_node_id="memory_commit_chapter", target_node_id="chapter_progress_router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.router.exit", source_node_id="chapter_progress_router", target_node_id="volume_review", edge_type="handoff"),
        ),
    )
    return build_graph_harness_config_from_graph(graph=graph)


def test_chapter_progress_receipt_partial_commit_continues_from_next_missing_chapter(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = replace(_chapter_loop_config(), control={"max_active_nodes": 2}, content_hash="")
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    state = started.loop_state
    order = started.node_work_orders[0]
    assert order.node_id == "chapter_outline"

    advance = _accept(loop, graph_config, state, order, {"ok": True})
    state = advance.loop_state
    order = advance.node_work_orders[0]
    assert order.node_id == "memory_commit_chapter"

    advance = _accept(
        loop,
        graph_config,
        state,
        order,
        {
            "chapter_progress_receipt": {
                "authority": "harness.writing.chapter_progress_receipt",
                "volume_index": 1,
                "batch_start_index": 1,
                "batch_end_index": 10,
                "expected_chapter_indexes": list(range(1, 11)),
                "committed_chapter_indexes": [1, 2, 3],
                "missing_chapter_indexes": [4, 5, 6, 7, 8, 9, 10],
                "unexpected_chapter_indexes": [],
                "committed_words": 6600,
                "next_chapter_index": 4,
                "batch_complete": False,
                "volume_complete": False,
                "commit_allowed": True,
            }
        },
    )
    state = advance.loop_state
    order = advance.node_work_orders[0]
    assert order.node_id == "chapter_progress_router"

    advance = _accept(
        loop,
        graph_config,
        state,
        order,
        {"router_summary": "继续当前批次，从第4章开始。"},
    )

    state = advance.loop_state
    assert state.initial_inputs["chapter_index"] == 4
    assert state.initial_inputs["batch_start_index"] == 1
    assert state.initial_inputs["batch_end_index"] == 10
    assert state.initial_inputs["batch_chapter_range"] == "001-010"
    assert state.initial_inputs["active_chapter_start_index"] == 4
    assert state.initial_inputs["active_chapter_end_index"] == 10
    assert state.initial_inputs["active_chapter_count"] == 7
    assert state.initial_inputs["active_chapter_range"] == "004-010"
    assert state.initial_inputs["group_current_measure"] == 6600
    assert state.initial_inputs["total_current_measure"] == 6600
    assert "volume_review" not in state.ready_node_ids
    assert advance.node_work_orders[0].node_id == "chapter_outline"
    assert [order.node_id for order in advance.node_work_orders] == ["chapter_outline"]


def test_progress_receipt_route_policy_preserves_explicit_receipt_source() -> None:
    graph_config = _chapter_loop_config()
    router = next(item for item in graph_config.nodes if item["node_id"] == "chapter_progress_router")
    route_policy = router["loop"]["route_policy"]

    assert route_policy["mode"] == "progress_receipt"
    assert route_policy["progress_receipt_key"] == "chapter_progress_receipt"
    assert route_policy["receipt_source_node_ids"] == ["memory_commit_chapter"]
    assert "fallback_increment_key" not in route_policy
    assert "default_increment" not in route_policy


def test_chapter_progress_receipt_route_blocks_when_receipt_missing(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = _chapter_loop_config()
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    state = started.loop_state
    order = started.node_work_orders[0]
    advance = _accept(loop, graph_config, state, order, {"ok": True})
    state = advance.loop_state
    order = advance.node_work_orders[0]
    advance = _accept(loop, graph_config, state, order, {"ok": True})
    state = advance.loop_state
    order = advance.node_work_orders[0]

    advance = _accept(loop, graph_config, state, order, {"chapter_words": 20000})

    assert advance.loop_state.status == "blocked"
    assert advance.loop_state.node_states["chapter_progress_router"]["blocked_reason"] == "loop_route_progress_receipt_missing"
    assert advance.loop_state.initial_inputs["chapter_index"] == 1
    assert advance.node_work_orders == ()


def test_progress_receipt_route_uses_explicit_source_over_router_output(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = _chapter_loop_config()
    loop = runtime.harness_runtime.graph_harness.graph_loop
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    state = started.loop_state
    order = started.node_work_orders[0]
    advance = _accept(loop, graph_config, state, order, {"ok": True})
    state = advance.loop_state
    order = advance.node_work_orders[0]
    advance = _accept(
        loop,
        graph_config,
        state,
        order,
        {
            "chapter_progress_receipt": {
                "authority": "harness.writing.chapter_progress_receipt",
                "volume_index": 1,
                "batch_start_index": 1,
                "batch_end_index": 10,
                "expected_chapter_indexes": list(range(1, 11)),
                "committed_chapter_indexes": [1, 2, 3],
                "missing_chapter_indexes": [4, 5, 6, 7, 8, 9, 10],
                "unexpected_chapter_indexes": [],
                "committed_words": 6600,
                "next_chapter_index": 4,
                "batch_complete": False,
                "volume_complete": False,
                "commit_allowed": True,
            }
        },
    )
    state = advance.loop_state
    order = advance.node_work_orders[0]

    advance = _accept(
        loop,
        graph_config,
        state,
        order,
        {
            "chapter_progress_receipt": {
                "authority": "harness.writing.chapter_progress_receipt",
                "volume_index": 1,
                "batch_start_index": 1,
                "batch_end_index": 10,
                "expected_chapter_indexes": list(range(1, 11)),
                "committed_chapter_indexes": list(range(1, 11)),
                "missing_chapter_indexes": [],
                "unexpected_chapter_indexes": [],
                "committed_words": 22000,
                "next_chapter_index": 11,
                "batch_complete": True,
                "volume_complete": False,
                "commit_allowed": True,
            }
        },
    )

    assert advance.loop_state.initial_inputs["chapter_index"] == 4
    assert advance.loop_state.initial_inputs["active_chapter_start_index"] == 4
    assert advance.loop_state.initial_inputs["active_chapter_end_index"] == 10
    assert advance.loop_state.initial_inputs["active_chapter_count"] == 7
    assert advance.loop_state.initial_inputs["active_chapter_range"] == "004-010"


def test_memory_commit_node_requires_structured_chapter_progress_receipt(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = _chapter_loop_config()
    node = next(item for item in graph_config.nodes if item["node_id"] == "memory_commit_chapter")
    assert node["progress_receipt_policy"]["progress_receipt_key"] == "chapter_progress_receipt"
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:missing-receipt",
        work_kind="agent",
        graph_run_id="grun:missing-receipt",
        task_run_id="taskrun:missing-receipt",
        node_id="memory_commit_chapter",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.commit",
        input_package={"initial_inputs": {"batch_start_index": 1, "batch_end_index": 10}},
    )
    executor = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)

    result = executor._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=work_order,
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": "提交回执：已提交。",
            "task_run": {
                "task_run_id": "node-taskrun",
                "status": "completed",
                "diagnostics": {
                    "final_answer": "提交回执：已提交。",
                    "final_action_diagnostics": {"structured_output": {"commit_allowed": True}},
                },
            },
        },
    )

    assert result.status == "failed"
    assert result.error["reason"] == "chapter_progress_receipt_missing"


def test_chapter_draft_result_fails_closed_when_quality_gate_under_length(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="config:quality-gate",
        graph_id="graph:test.quality_gate",
        graph_title="Quality Gate",
        publish_version="test",
        content_hash="hash:test",
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent_role",
                "contracts": {
                    "contract_bindings": {
                        "runtime": {
                            "length_budget": {
                                "enabled": True,
                                "budget_scope": "batch",
                                "measurement_mode": "text_units",
                                "target_units": 20000,
                                "min_units": 18000,
                                "max_units": 40000,
                                "batch_unit_count": 10,
                                "metric_section_keys": ["章节正文候选"],
                            }
                        }
                    }
                },
                "retry": {
                    "acceptance_policies": ["sectioned_text_batch_quality"],
                    "unit_start_key": "batch_start_index",
                    "unit_end_key": "batch_end_index",
                    "unit_count_key": "units_per_batch",
                    "target_metric_key": "batch_target_measure",
                    "unit_target_metric_key": "unit_target_measure",
                    "minimum_metric_ratio": 0.9,
                    "minimum_metric_per_unit": 1800,
                    "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
                    "heading_match_scope": "formal_heading",
                    "metric_section_keys": ["章节正文候选"],
                },
            },
        ),
        edges=(),
    )
    body = "# 【章节正文候选】\n\n" + "\n\n".join(
        f"### 第{index}章\n" + ("泽" * 700)
        for index in range(1, 11)
    )
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:quality-gate",
        work_kind="agent",
        graph_run_id="grun:quality-gate",
        task_run_id="taskrun:quality-gate",
        node_id="chapter_draft",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.draft",
        input_package={
            "initial_inputs": {
                "batch_start_index": 1,
                "batch_end_index": 10,
                "units_per_batch": 10,
                "unit_target_measure": 2000,
                "batch_target_measure": 20000,
            }
        },
    )

    result = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=work_order,
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": body,
            "task_run": {"task_run_id": "node-taskrun", "status": "completed", "diagnostics": {"final_answer": body}},
        },
    )

    assert result.status == "failed"
    assert result.error["reason"] == "quality_gate_failed"
    assert any(str(issue).startswith("insufficient_unit_metric:1:") for issue in result.error["issues"])
    assert result.diagnostics["quality_acceptance"]["business_accepted"] is False


def test_chapter_draft_quality_gate_can_requeue_same_node(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="config:quality-gate-retry-same-node",
        graph_id="graph:test.quality_gate.retry_same_node",
        graph_title="Quality Gate Retry Same Node",
        publish_version="test",
        content_hash="hash:test",
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent_role",
                "contracts": {
                    "contract_bindings": {
                        "runtime": {
                            "length_budget": {
                                "enabled": True,
                                "budget_scope": "unit",
                                "measurement_mode": "text_units",
                                "target_units": 2000,
                                "min_units": 1800,
                                "max_units": 4000,
                                "target_enforcement": "advisory",
                                "batch_unit_count": 1,
                                "metric_section_keys": ["章节正文候选"],
                            }
                        }
                    }
                },
                "retry": {
                    "acceptance_policies": ["sectioned_text_batch_quality"],
                    "quality_failure_mode": "retry_same_node",
                    "unit_start_key": "chapter_index",
                    "unit_end_key": "chapter_index",
                    "unit_count_key": "unit_count",
                    "target_metric_key": "unit_target_measure",
                    "unit_target_metric_key": "unit_target_measure",
                    "minimum_metric_ratio": 0.9,
                    "minimum_metric_per_unit": 1800,
                    "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
                    "heading_match_scope": "formal_heading",
                    "metric_section_keys": ["章节正文候选"],
                },
            },
        ),
        edges=(),
    )
    body = "# 【章节正文候选】\n\n### 第2章\n" + ("泽" * 1200)
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:quality-gate-retry-same-node",
        work_kind="agent",
        graph_run_id="grun:quality-gate-retry-same-node",
        task_run_id="taskrun:quality-gate-retry-same-node",
        node_id="chapter_draft",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.draft",
        input_package={"initial_inputs": {"chapter_index": 2, "unit_count": 1, "unit_target_measure": 2000}},
    )

    result = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=work_order,
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": body,
            "task_run": {"task_run_id": "node-taskrun", "status": "completed", "diagnostics": {"final_answer": body}},
        },
    )

    assert result.status == "blocked"
    assert result.error["reason"] == "quality_gate_failed"
    assert result.error["recoverable_error"]["retryable"] is True
    assert result.diagnostics["quality_acceptance"]["below_target_advisory"] is True


def test_quality_failed_draft_with_explicit_repair_route_passes_metric_feedback_to_repair(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    retry = {
        "acceptance_policies": ["sectioned_text_batch_quality"],
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "units_per_batch",
        "target_metric_key": "batch_target_measure",
        "unit_target_metric_key": "unit_target_measure",
        "minimum_metric_ratio": 0.9,
        "minimum_metric_per_unit": 1800,
        "unit_summary_template": "第{index}章",
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "heading_match_scope": "formal_heading",
        "metric_section_keys": ["章节正文候选"],
        "requirements_input_key": "chapter_revision_requirements",
        "requirements_template": "质量门统计：{quality_issue_summary}。第{start}章至第{end}章，每章最低1800字。",
    }
    graph_config = GraphHarnessConfig(
        config_id="ghcfg:test.quality.repair",
        graph_id="graph.test.quality.repair",
        graph_title="Quality Repair",
        publish_version="v1",
        control={"start_node_ids": ["chapter_draft"]},
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent",
                "task_ref": "task.test.chapter.draft",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "contracts": {"contract_bindings": {"runtime": {"length_budget": {"configured": True, "min_units": 18000, "target_units": 20000}}}},
                "retry": retry,
            },
            {
                "node_id": "chapter_draft_repair",
                "node_type": "agent",
                "task_ref": "task.test.chapter.draft.repair",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "retry": retry,
            },
        ),
        edges=(
            {
                "edge_id": "edge.draft.repair",
                "source_node_id": "chapter_draft",
                "target_node_id": "chapter_draft_repair",
                "edge_type": "repair_route",
                "scheduler_role": "dependency",
                "semantic_role": "control",
                "metadata": {"dependency_role": "repair_route"},
                "result_delivery_policy": "contract_payload_and_refs",
            },
        ),
    )
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={
            "batch_start_index": 1,
            "batch_end_index": 10,
            "units_per_batch": 10,
            "unit_target_measure": 2000,
            "batch_target_measure": 20000,
        },
        dispatch_ready=True,
    )
    body = "# 【章节正文候选】\n\n" + "\n\n".join(f"### 第{index}章\n" + ("泽" * 700) for index in range(1, 11))
    draft_result = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=started.node_work_orders[0],
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": body,
            "task_run": {"task_run_id": "node-taskrun", "status": "completed", "diagnostics": {"final_answer": body}},
        },
    )

    assert draft_result.status == "completed"
    assert draft_result.error["reason"] == "quality_gate_failed"

    advance = runtime.harness_runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=started.graph_run.graph_run_id,
        result=draft_result,
    )

    assert advance.node_work_orders[0].node_id == "chapter_draft_repair"
    repair_inputs = advance.node_work_orders[0].input_package["initial_inputs"]
    assert "chapter_revision_requirements" in repair_inputs
    assert "质量门统计" in repair_inputs["chapter_revision_requirements"]
    assert "第1章约" in repair_inputs["chapter_revision_requirements"]
    assert repair_inputs["quality_gate_feedback"]["source_error"]["reason"] == "quality_gate_failed"


def test_quality_repair_route_requires_explicit_repair_semantics(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    retry = {
        "acceptance_policies": ["sectioned_text_batch_quality"],
        "unit_start_key": "batch_start_index",
        "unit_end_key": "batch_end_index",
        "unit_count_key": "units_per_batch",
        "target_metric_key": "batch_target_measure",
        "unit_target_metric_key": "unit_target_measure",
        "minimum_metric_ratio": 0.9,
        "minimum_metric_per_unit": 1800,
        "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
        "heading_match_scope": "formal_heading",
        "metric_section_keys": ["章节正文候选"],
    }
    graph_config = GraphHarnessConfig(
        config_id="ghcfg:test.quality.no_implicit_repair",
        graph_id="graph.test.quality.no_implicit_repair",
        graph_title="Quality No Implicit Repair",
        publish_version="v1",
        control={"start_node_ids": ["chapter_draft"]},
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent",
                "task_ref": "task.test.chapter.draft",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "contracts": {"contract_bindings": {"runtime": {"length_budget": {"configured": True, "min_units": 18000, "target_units": 20000}}}},
                "retry": retry,
            },
            {
                "node_id": "chapter_draft_self_repair",
                "node_type": "agent",
                "task_ref": "task.test.chapter.draft.repair",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "retry": retry,
            },
        ),
        edges=(
            {
                "edge_id": "edge.draft.named_like_repair",
                "source_node_id": "chapter_draft",
                "target_node_id": "chapter_draft_self_repair",
                "edge_type": "structured_handoff",
                "scheduler_role": "dependency",
                "semantic_role": "control",
                "result_delivery_policy": "contract_payload_and_refs",
            },
        ),
    )
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={
            "batch_start_index": 1,
            "batch_end_index": 10,
            "units_per_batch": 10,
            "unit_target_measure": 2000,
            "batch_target_measure": 20000,
        },
        dispatch_ready=True,
    )
    body = "# 【章节正文候选】\n\n" + "\n\n".join(f"### 第{index}章\n" + ("泽" * 700) for index in range(1, 11))
    draft_result = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=started.node_work_orders[0],
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": body,
            "task_run": {"task_run_id": "node-taskrun", "status": "completed", "diagnostics": {"final_answer": body}},
        },
    )

    assert draft_result.status == "failed"
    assert draft_result.error["reason"] == "quality_gate_failed"


def _accept(loop: GraphLoop, graph_config, state, order, outputs: dict):
    return loop.accept_node_result(
        graph_config=graph_config,
        graph_run_id=state.graph_run_id,
        result={
            "result_id": f"nresult:{order.node_id}:{len(state.result_history.get(order.node_id, ())) + 1}",
            "graph_run_id": state.graph_run_id,
            "task_run_id": state.task_run_id,
            "node_id": order.node_id,
            "work_order_id": order.work_order_id,
            "outputs": outputs,
        },
    )


def _chapter_derived_fields() -> list[dict]:
    return [
        {"key": "batch_start_index_padded", "op": "format", "template": "{batch_start_index:03d}"},
        {"key": "batch_end_index_padded", "op": "format", "template": "{batch_end_index:03d}"},
        {"key": "batch_chapter_range", "op": "format", "template": "{batch_start_index:03d}-{batch_end_index:03d}"},
        {"key": "active_chapter_count", "op": "range_count", "start_key": "active_chapter_start_index", "end_key": "active_chapter_end_index"},
        {"key": "active_chapter_range", "op": "format", "template": "{active_chapter_start_index:03d}-{active_chapter_end_index:03d}"},
    ]
