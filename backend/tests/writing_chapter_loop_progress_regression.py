from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.loop import GraphLoop
from harness.graph.models import GraphNodeWorkOrder
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
    assert advance.node_work_orders[0].node_id == "chapter_outline"


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
