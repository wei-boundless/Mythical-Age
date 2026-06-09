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
from task_system.runtime_semantics.chapter_progress import normalize_chapter_progress_receipt
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


def test_chapter_progress_receipt_cannot_override_runtime_volume_index() -> None:
    receipt = normalize_chapter_progress_receipt(
        {
            "authority": "harness.writing.chapter_progress_receipt",
            "volume_index": 1,
            "batch_start_index": 51,
            "batch_end_index": 60,
            "expected_chapter_indexes": list(range(51, 61)),
            "committed_chapter_indexes": list(range(51, 61)),
            "missing_chapter_indexes": [],
            "unexpected_chapter_indexes": [],
            "committed_words": 35000,
            "next_chapter_index": 61,
            "batch_complete": True,
            "volume_complete": False,
            "commit_allowed": True,
        },
        initial_inputs={"volume_index": 2, "batch_start_index": 51, "batch_end_index": 60},
    )

    assert receipt["volume_index"] == 2


def test_chapter_progress_receipt_accepts_cumulative_committed_prefix_for_current_batch() -> None:
    receipt = normalize_chapter_progress_receipt(
        {
            "authority": "harness.writing.chapter_progress_receipt",
            "volume_index": 1,
            "batch_start_index": 11,
            "batch_end_index": 20,
            "expected_chapter_indexes": list(range(11, 21)),
            "committed_chapter_indexes": list(range(1, 12)),
            "missing_chapter_indexes": list(range(12, 21)),
            "unexpected_chapter_indexes": [],
            "committed_words": 3600,
            "next_chapter_index": 12,
            "batch_complete": False,
            "volume_complete": False,
            "commit_allowed": True,
        },
        initial_inputs={"volume_index": 1, "batch_start_index": 11, "batch_end_index": 20},
    )

    assert receipt["committed_chapter_indexes"] == [11]
    assert receipt["missing_chapter_indexes"] == list(range(12, 21))
    assert receipt["next_chapter_index"] == 12
    assert receipt["batch_complete"] is False


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


def test_chapter_unit_receipt_route_advances_only_from_router_receipt(tmp_path: Path) -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.writing_chapter_unit_receipt_loop",
        title="Writing Chapter Unit Receipt Loop",
        graph_kind="coordination",
        publish_state="published",
        enabled=True,
        entry_node_id="chapter_draft",
        output_node_id="chapter_batch_assemble",
        runtime_policy={"coordinator_agent_id": "agent:0"},
        loop_frames=(
            {
                "frame_id": "loop.chapter_unit",
                "scope_id": "loop.chapter_unit",
                "entry_node_id": "chapter_draft",
                "router_node_id": "chapter_unit_router",
                "continue_node_id": "chapter_draft",
                "exit_node_id": "chapter_batch_assemble",
                "cursor_key": "chapter_index",
                "start_key": "batch_start_index",
                "end_key": "batch_end_index",
                "step": 1,
                "iteration_identity_template": "chapter-{chapter_index}",
                "initial_inputs": {"volume_index": 1, "chapter_index": 1, "batch_start_index": 1, "batch_end_index": 2},
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="chapter_draft",
                node_type="agent",
                title="Draft",
                task_id="task.test.chapter.draft",
                agent_id="agent:0",
                loop={"scope_id": "loop.chapter_unit"},
            ),
            TaskGraphNodeDefinition(
                node_id="chapter_unit_router",
                node_type="agent",
                title="Unit Router",
                task_id="task.test.chapter.unit_router",
                agent_id="agent:0",
                metadata={"progress_receipt_policy": {"progress_receipt_key": "chapter_progress_receipt"}},
                loop={
                    "scope_id": "loop.chapter_unit",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.chapter_unit",
                        "continue_node_id": "chapter_draft",
                        "exit_node_id": "chapter_batch_assemble",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["chapter_unit_router"],
                        "receipt_complete_key": "batch_complete",
                        "receipt_to_input_mappings": [
                            {"source_key": "next_chapter_index", "target_key": "chapter_index", "apply_on": ["continue"]},
                            {"source_key": "batch_start_index", "target_key": "batch_start_index"},
                            {"source_key": "batch_end_index", "target_key": "batch_end_index"},
                        ],
                        "current_key": "chapter_index",
                        "target_key": "batch_end_index",
                    },
                },
            ),
            TaskGraphNodeDefinition(
                node_id="chapter_batch_assemble",
                node_type="agent",
                title="Assemble",
                task_id="task.test.chapter.assemble",
                agent_id="agent:0",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.draft.router", source_node_id="chapter_draft", target_node_id="chapter_unit_router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.router.assemble", source_node_id="chapter_unit_router", target_node_id="chapter_batch_assemble", edge_type="handoff"),
        ),
    )
    graph_config = build_graph_harness_config_from_graph(graph=graph)
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
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
    assert order.node_id == "chapter_draft"

    advance = _accept(loop, graph_config, state, order, {"draft": "第1章正文"})
    state = advance.loop_state
    order = advance.node_work_orders[0]
    assert order.node_id == "chapter_unit_router"

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
                "batch_end_index": 2,
                "expected_chapter_indexes": [1, 2],
                "committed_chapter_indexes": [1],
                "missing_chapter_indexes": [2],
                "unexpected_chapter_indexes": [],
                "committed_words": 2200,
                "next_chapter_index": 2,
                "batch_complete": False,
                "volume_complete": False,
                "commit_allowed": True,
            }
        },
    )
    state = advance.loop_state
    order = advance.node_work_orders[0]
    assert order.node_id == "chapter_draft"
    assert state.initial_inputs["chapter_index"] == 2

    advance = _accept(loop, graph_config, state, order, {"draft": "第2章正文"})
    state = advance.loop_state
    order = advance.node_work_orders[0]
    assert order.node_id == "chapter_unit_router"

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
                "batch_end_index": 2,
                "expected_chapter_indexes": [1, 2],
                "committed_chapter_indexes": [1, 2],
                "missing_chapter_indexes": [],
                "unexpected_chapter_indexes": [],
                "committed_words": 4300,
                "next_chapter_index": 3,
                "batch_complete": True,
                "volume_complete": False,
                "commit_allowed": True,
            }
        },
    )

    assert advance.node_work_orders[0].node_id == "chapter_batch_assemble"
    assert advance.loop_state.initial_inputs["chapter_index"] == 2
    assert [item["action"] for item in advance.loop_state.loop_state["route_history"]] == ["continue", "exit"]


def test_self_sourced_chapter_unit_router_executes_without_agent_model(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="ghcfg:test.deterministic.chapter_unit_router",
        graph_id="graph.test.deterministic.chapter_unit_router",
        graph_title="Deterministic Chapter Unit Router",
        publish_version="test",
        content_hash="",
        control={
            "start_node_ids": ["chapter_draft"],
            "terminal_node_ids": ["chapter_batch_assemble"],
            "max_active_nodes": 1,
        },
        loop_frames=(
            {
                "frame_id": "loop.chapter_unit",
                "scope_id": "loop.chapter_unit",
                "entry_node_id": "chapter_draft",
                "router_node_id": "chapter_unit_router",
                "continue_node_id": "chapter_draft",
                "exit_node_id": "chapter_batch_assemble",
                "scope_node_ids": ["chapter_draft", "chapter_unit_router"],
                "cursor_key": "chapter_index",
                "start_key": "batch_start_index",
                "end_key": "batch_end_index",
                "step": 1,
                "reset_scope_on_continue": True,
                "preserve_iteration_results": True,
                "initial_inputs": {"volume_index": 1, "chapter_index": 1, "batch_start_index": 1, "batch_end_index": 2},
            },
        ),
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent",
                "task_ref": "task.test.chapter.draft",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "loop": {"scope_id": "loop.chapter_unit"},
            },
            {
                "node_id": "chapter_unit_router",
                "node_type": "agent",
                "task_ref": "task.test.chapter.unit_router",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "metadata": {"progress_receipt_policy": {"progress_receipt_key": "chapter_progress_receipt"}},
                "loop": {
                    "scope_id": "loop.chapter_unit",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.chapter_unit",
                        "continue_node_id": "chapter_draft",
                        "exit_node_id": "chapter_batch_assemble",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["chapter_unit_router"],
                        "receipt_complete_key": "batch_complete",
                        "receipt_to_input_mappings": [
                            {"source_key": "next_chapter_index", "target_key": "chapter_index", "apply_on": ["continue"]},
                            {"source_key": "batch_start_index", "target_key": "batch_start_index"},
                            {"source_key": "batch_end_index", "target_key": "batch_end_index"},
                        ],
                        "current_key": "chapter_index",
                        "target_key": "batch_end_index",
                    },
                },
            },
            {
                "node_id": "chapter_batch_assemble",
                "node_type": "agent",
                "task_ref": "task.test.chapter.assemble",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
            },
        ),
        edges=(
            {
                "edge_id": "edge.draft.router",
                "source_node_id": "chapter_draft",
                "target_node_id": "chapter_unit_router",
                "edge_type": "structured_handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
            {
                "edge_id": "edge.router.assemble",
                "source_node_id": "chapter_unit_router",
                "target_node_id": "chapter_batch_assemble",
                "edge_type": "structured_handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
        ),
    )
    graph_harness = runtime.harness_runtime.graph_harness
    loop = graph_harness.graph_loop
    missing_artifact_start = graph_harness.start_run(
        session_id="session-missing-artifact",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    missing_draft_order = missing_artifact_start.node_work_orders[0]
    missing_advance = _accept(loop, graph_config, missing_artifact_start.loop_state, missing_draft_order, {"draft": "第1章正文"})
    missing_execution = asyncio.run(
        graph_harness.execute_work_order(
            graph_config=graph_config,
            work_order=missing_advance.node_work_orders[0],
            accept_result=False,
        )
    )

    assert missing_execution["node_result"]["status"] == "failed"
    assert missing_execution["node_result"]["error"]["reason"] == "deterministic_progress_receipt_invalid"
    assert (
        missing_execution["node_result"]["error"]["recoverable_error"]["error_code"]
        == "chapter_progress_receipt_upstream_artifact_missing"
    )

    started = graph_harness.start_run(
        session_id="session-with-artifact",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    draft_order = started.node_work_orders[0]
    advance = _accept(
        loop,
        graph_config,
        started.loop_state,
        draft_order,
        {"draft": "第1章正文"},
        artifact_refs=("artifact://chapter_001/draft.md",),
    )
    router_order = advance.node_work_orders[0]

    execution = asyncio.run(
        graph_harness.execute_work_order(
            graph_config=graph_config,
            work_order=router_order,
            accept_result=True,
        )
    )
    state = loop.get_state(started.graph_run.graph_run_id)

    assert execution["executor_result"]["ok"] is True
    assert execution["node_result"]["status"] == "completed"
    assert execution["node_executor_task_run"]["task_run_id"].startswith("system:")
    assert execution["node_result"]["progress_receipts"][0]["next_chapter_index"] == 2
    assert state is not None
    assert state.initial_inputs["chapter_index"] == 2
    assert execution["node_work_orders"][0]["node_id"] == "chapter_draft"


def test_resume_requeues_progress_router_without_synthetic_receipt(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="ghcfg:test.resume.progress_router.no_synthetic",
        graph_id="graph.test.resume.progress_router.no_synthetic",
        graph_title="Resume Progress Router Without Synthetic Receipt",
        publish_version="test",
        content_hash="",
        control={"start_node_ids": ["chapter_unit_router"], "max_active_nodes": 1},
        loop_frames=(
            {
                "frame_id": "loop.chapter_unit",
                "scope_id": "loop.chapter_unit",
                "entry_node_id": "chapter_unit_router",
                "router_node_id": "chapter_unit_router",
                "continue_node_id": "chapter_unit_router",
                "exit_node_id": "chapter_done",
                "scope_node_ids": ["chapter_unit_router"],
                "cursor_key": "chapter_index",
                "start_key": "batch_start_index",
                "end_key": "batch_end_index",
                "initial_inputs": {"volume_index": 1, "chapter_index": 1, "batch_start_index": 1, "batch_end_index": 1},
            },
        ),
        nodes=(
            {
                "node_id": "chapter_unit_router",
                "node_type": "agent",
                "task_ref": "task.test.chapter.unit_router",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
                "metadata": {"progress_receipt_policy": {"progress_receipt_key": "chapter_progress_receipt"}},
                "loop": {
                    "scope_id": "loop.chapter_unit",
                    "route_policy": {
                        "mode": "progress_receipt",
                        "scope_id": "loop.chapter_unit",
                        "continue_node_id": "chapter_unit_router",
                        "exit_node_id": "chapter_done",
                        "progress_receipt_key": "chapter_progress_receipt",
                        "receipt_source_node_ids": ["chapter_unit_router"],
                        "receipt_complete_key": "batch_complete",
                    },
                },
            },
            {
                "node_id": "chapter_done",
                "node_type": "agent",
                "task_ref": "task.test.chapter.done",
                "agent_id": "agent:0",
                "executor": {"executor_type": "agent"},
            },
        ),
        edges=(),
    )
    graph_harness = runtime.harness_runtime.graph_harness
    started = graph_harness.start_run(
        session_id="session-resume-router",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={},
        dispatch_ready=True,
    )
    router_order = started.node_work_orders[0]
    blocked = graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=started.graph_run.graph_run_id,
        result={
            "result_id": "nresult:chapter_unit_router:blocked",
            "graph_run_id": started.graph_run.graph_run_id,
            "task_run_id": started.task_run.task_run_id,
            "node_id": "chapter_unit_router",
            "work_order_id": router_order.work_order_id,
            "status": "blocked",
            "error": {
                "reason": "model_action_protocol_repair_required",
                "recoverable_error": {
                    "error_code": "model_action_invalid",
                    "retryable": True,
                    "recovery_action": "requeue_graph_node",
                },
            },
        },
    )

    assert blocked.loop_state.status == "blocked"
    resumed = graph_harness.resume_run(
        graph_config=graph_config,
        graph_run_id=started.graph_run.graph_run_id,
    )

    assert resumed.reason == "blocked_nodes_requeued"
    assert resumed.node_work_orders
    assert resumed.node_work_orders[0].node_id == "chapter_unit_router"
    assert resumed.loop_state is not None
    assert resumed.loop_state.node_states["chapter_unit_router"]["status"] == "running"
    assert not dict(resumed.loop_state.result_index.get("chapter_unit_router") or {}).get("progress_receipts")
    assert all("synthetic_progress_receipt" not in str(event.get("event_type") or event.get("payload") or "") for event in resumed.events)


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


def test_progress_receipt_can_be_extracted_from_final_answer_json_block(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = _chapter_loop_config()
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:text-receipt",
        work_kind="agent",
        graph_run_id="grun:text-receipt",
        task_run_id="taskrun:text-receipt",
        node_id="memory_commit_chapter",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.commit",
        input_package={"initial_inputs": {"batch_start_index": 1, "batch_end_index": 10, "chapter_index": 1}},
    )
    executor = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime)

    result = executor._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=work_order,
        task_run_id="node-taskrun",
        executor_result={
            "ok": True,
            "final_answer": """
### chapter_progress_receipt

```json
{
  "authority": "harness.writing.chapter_progress_receipt",
  "batch_start_index": 1,
  "batch_end_index": 10,
  "expected_chapter_indexes": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  "committed_chapter_indexes": [1],
  "missing_chapter_indexes": [2, 3, 4, 5, 6, 7, 8, 9, 10],
  "next_chapter_index": 2,
  "batch_complete": false,
  "commit_allowed": true
}
```
""",
            "task_run": {
                "task_run_id": "node-taskrun",
                "status": "completed",
                "diagnostics": {"final_action_diagnostics": {"structured_output": {}}},
            },
        },
    )

    assert result.status == "completed"
    assert result.progress_receipts[0]["next_chapter_index"] == 2
    assert result.progress_receipts[0]["committed_words"] == 0


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


def test_requeued_chapter_draft_receives_quality_feedback_and_previous_text(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="config:quality-gate-requeue-feedback",
        graph_id="graph:test.quality_gate.requeue_feedback",
        graph_title="Quality Gate Requeue Feedback",
        publish_version="test",
        content_hash="",
        control={"start_node_ids": ["chapter_draft"]},
        environment={"storage_space": {"artifact_root": "storage/test_artifacts"}},
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent_role",
                "executor": {"executor_type": "agent"},
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
                    "minimum_metric_ratio": 0.0,
                    "minimum_metric_per_unit": 1800,
                    "forbid_unexpected_unit_indexes": True,
                    "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
                    "heading_match_scope": "formal_heading",
                    "metric_section_keys": ["章节正文候选"],
                    "carry_current_output_as": "previous_chapter_draft_ref",
                    "requirements_input_key": "chapter_revision_requirements",
                    "requirements_template": "质量门统计：{quality_issue_summary}。必须完整重交当前第{chapter_index}章正文。",
                },
            },
        ),
        edges=(),
    )
    started = runtime.harness_runtime.graph_harness.start_run(
        session_id="session",
        task_id="task.test",
        graph_config=graph_config,
        initial_inputs={"chapter_index": 2, "unit_count": 1, "unit_target_measure": 2000},
        dispatch_ready=True,
    )
    first_body = "# 【章节正文候选】\n\n### 第2章\n上一版短章正文。" + ("泽" * 900)
    first_artifact = tmp_path / "previous_chapter_002.md"
    first_artifact.write_text(first_body, encoding="utf-8")
    first_result = GraphNodeWorkOrderExecutor(services=runtime.harness_runtime.graph_harness._services)._node_result_from_agent_execution(
        graph_config=graph_config,
        work_order=started.node_work_orders[0],
        task_run_id="node-taskrun:first",
        executor_result={
            "ok": True,
            "final_answer": first_body,
            "artifact_refs": [{"path": str(first_artifact)}],
            "task_run": {"task_run_id": "node-taskrun:first", "status": "completed", "diagnostics": {"final_answer": first_body}},
        },
    )

    assert first_result.status == "blocked"
    advance = runtime.harness_runtime.graph_harness.accept_node_result(
        graph_config=graph_config,
        graph_run_id=started.graph_run.graph_run_id,
        result=first_result,
    )
    requeued = runtime.harness_runtime.graph_harness.graph_loop.requeue_blocked_nodes_and_checkpoint(
        state=advance.loop_state,
        node_ids=("chapter_draft",),
    )
    dispatched = runtime.harness_runtime.graph_harness.graph_loop.dispatch_ready_and_checkpoint(
        graph_config=graph_config,
        graph_run_id=requeued.loop_state.graph_run_id,
    )

    retry_inputs = dispatched.node_work_orders[0].input_package["initial_inputs"]
    retry_context = dispatched.node_work_orders[0].input_package["inbound_context"]
    previous_output = retry_inputs["previous_chapter_draft_ref"]

    assert "quality_gate_feedback" in retry_inputs
    assert retry_inputs["quality_gate_feedback"]["source_error"]["reason"] == "quality_gate_failed"
    assert "质量门统计" in retry_inputs["chapter_revision_requirements"]
    assert previous_output["artifact_refs"]
    assert "上一版短章正文" in previous_output["artifact_payloads"][0]["content"]
    assert any(item["packet_type"] == "quality_retry_feedback" for item in retry_context)


def test_requeued_chapter_draft_soft_passes_metric_only_failure_after_feedback(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="config:quality-gate-soft-pass",
        graph_id="graph:test.quality_gate.soft_pass",
        graph_title="Quality Gate Soft Pass",
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
                    "max_quality_retries": 1,
                    "unit_start_key": "chapter_index",
                    "unit_end_key": "chapter_index",
                    "unit_count_key": "unit_count",
                    "target_metric_key": "unit_target_measure",
                    "unit_target_metric_key": "unit_target_measure",
                    "minimum_metric_ratio": 0.0,
                    "minimum_metric_per_unit": 1800,
                    "forbid_unexpected_unit_indexes": True,
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
        work_order_id="gwork:quality-gate-soft-pass",
        work_kind="agent",
        graph_run_id="grun:quality-gate-soft-pass",
        task_run_id="taskrun:quality-gate-soft-pass",
        node_id="chapter_draft",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.draft",
        input_package={
            "initial_inputs": {
                "chapter_index": 2,
                "unit_count": 1,
                "unit_target_measure": 2000,
                "quality_gate_feedback": {"source_error": {"reason": "quality_gate_failed"}},
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

    assert result.status == "completed"
    assert result.error == {}
    assert result.diagnostics["quality_gate_soft_pass"] is True
    assert result.diagnostics["quality_acceptance"]["accepted"] is True
    assert result.diagnostics["quality_acceptance"]["quality_gate_soft_pass"] is True


def test_requeued_chapter_draft_does_not_soft_pass_non_metric_failure(tmp_path: Path) -> None:
    runtime = _runtime_with_graph_harness(base_dir=tmp_path / "backend", runtime_root=tmp_path / "runtime_state")
    graph_config = GraphHarnessConfig(
        config_id="config:quality-gate-non-metric",
        graph_id="graph:test.quality_gate.non_metric",
        graph_title="Quality Gate Non Metric",
        publish_version="test",
        content_hash="hash:test",
        nodes=(
            {
                "node_id": "chapter_draft",
                "node_type": "agent_role",
                "contracts": {"contract_bindings": {"runtime": {"length_budget": {"enabled": True, "min_units": 1800, "target_enforcement": "advisory", "metric_section_keys": ["章节正文候选"]}}}},
                "retry": {
                    "acceptance_policies": ["sectioned_text_batch_quality"],
                    "quality_failure_mode": "retry_same_node",
                    "max_quality_retries": 1,
                    "unit_start_key": "chapter_index",
                    "unit_end_key": "chapter_index",
                    "unit_count_key": "unit_count",
                    "target_metric_key": "unit_target_measure",
                    "unit_target_metric_key": "unit_target_measure",
                    "minimum_metric_ratio": 0.0,
                    "minimum_metric_per_unit": 1800,
                    "forbid_unexpected_unit_indexes": True,
                    "required_heading_patterns": [r"第\s*(?P<index>[0-9一二三四五六七八九十百零〇两]+)\s*[章节回]"],
                    "heading_match_scope": "formal_heading",
                    "metric_section_keys": ["章节正文候选"],
                },
            },
        ),
        edges=(),
    )
    body = "# 【章节正文候选】\n\n### 第3章\n" + ("泽" * 2200)
    work_order = GraphNodeWorkOrder(
        work_order_id="gwork:quality-gate-non-metric",
        work_kind="agent",
        graph_run_id="grun:quality-gate-non-metric",
        task_run_id="taskrun:quality-gate-non-metric",
        node_id="chapter_draft",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        task_ref="task.test.chapter.draft",
        input_package={
            "initial_inputs": {
                "chapter_index": 2,
                "unit_count": 1,
                "unit_target_measure": 2000,
                "quality_gate_feedback": {"source_error": {"reason": "quality_gate_failed"}},
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

    assert result.status == "blocked"
    assert result.error["reason"] == "quality_gate_failed"
    assert any(str(issue).startswith("unexpected_unit_indexes:") for issue in result.error["issues"])


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


def _accept(loop: GraphLoop, graph_config, state, order, outputs: dict, artifact_refs: tuple[str, ...] = ()):
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
            "artifact_refs": list(artifact_refs),
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
