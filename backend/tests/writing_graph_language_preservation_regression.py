from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.models import NodeResultEnvelope, graph_harness_config_from_dict
from harness.graph.scheduler_view import build_scheduler_view
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)


def _writing_like_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        graph_id="graph.test.writing_language_preservation",
        title="Writing Language Preservation",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="memory.commit",
        publish_state="published",
        enabled=True,
        runtime_policy={"coordinator_agent_id": "agent:0"},
        nodes=(
            TaskGraphNodeDefinition(
                node_id="memory.world",
                node_type="memory_repository",
                title="世界观记忆库",
                metadata={
                    "memory_repository": {
                        "repository_id": "repo.world",
                        "collections": [{"collection_id": "world_setting"}],
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="issue.ledger",
                node_type="issue_ledger",
                title="问题账本",
            ),
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent_role",
                title="起草",
                agent_id="agent:0",
                metadata={
                    "prompt_contract": {
                        "role_prompt": "你是一名长篇小说设定起草员。",
                        "task_instruction": "请根据输入材料起草可审核的世界观设定。",
                    }
                },
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="review_gate",
                title="审核",
                agent_id="agent:0",
            ),
            TaskGraphNodeDefinition(
                node_id="memory.commit",
                node_type="memory_commit",
                title="记忆提交",
                agent_id="agent:0",
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.memory.read",
                source_node_id="memory.world",
                target_node_id="draft",
                edge_type="memory_read",
                metadata={"repository": "repo.world", "collection": "world_setting", "on_missing": "warn"},
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="structured_handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.review.revise",
                source_node_id="review",
                target_node_id="draft",
                edge_type="revision_request",
                metadata={"trigger": {"verdict": "revise"}, "carry": ["review_notes"]},
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.memory_commit",
                source_node_id="draft",
                target_node_id="memory.commit",
                edge_type="memory_commit",
                metadata={
                    "repository": "repo.world",
                    "collection": "world_setting",
                    "source_output_key": "world_setting",
                },
            ),
        ),
    )


def _graph_harness_config():
    graph = _writing_like_graph()
    return build_graph_harness_config_from_graph(
        graph=graph,
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )


def test_graph_harness_config_preserves_full_graph_language() -> None:
    graph_config = _graph_harness_config()

    node_types = {str(node.get("node_id")): str(node.get("node_type")) for node in graph_config.nodes}
    edge_types = {str(edge.get("edge_id")): str(edge.get("edge_type")) for edge in graph_config.edges}

    assert len(graph_config.nodes) == 5
    assert len(graph_config.edges) == 4
    assert node_types["memory.world"] == "memory_repository"
    assert node_types["issue.ledger"] == "issue_ledger"
    assert node_types["memory.commit"] == "memory_commit"
    assert edge_types["edge.memory.read"] == "memory_read"
    assert edge_types["edge.draft.memory_commit"] == "memory_commit"
    assert edge_types["edge.review.revise"] == "revision_request"


def test_graph_module_expansion_scopes_imported_loop_contracts() -> None:
    child = TaskGraphDefinition(
        graph_id="graph.test.child_loop",
        title="Child Loop",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        loop_frames=(
            {
                "frame_id": "loop.units",
                "scope_id": "loop.units",
                "kind": "bounded_metric_iteration",
                "entry_node_id": "draft",
                "router_node_id": "router",
                "continue_node_id": "draft",
                "exit_node_id": "review",
                "initial_inputs": {"target_unit_count": 2, "unit_index": 1},
            },
        ),
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="起草",
                agent_id="agent:0",
                loop={"scope_id": "loop.units", "kind": "bounded_metric_iteration"},
            ),
            TaskGraphNodeDefinition(
                node_id="router",
                node_type="agent",
                title="路由",
                agent_id="agent:0",
                loop={
                    "scope_id": "loop.units",
                    "kind": "bounded_metric_iteration",
                    "route_policy": {
                        "scope_id": "loop.units",
                        "continue_node_id": "draft",
                        "exit_node_id": "review",
                        "current_key": "unit_index",
                        "target_key": "target_unit_count",
                    },
                },
            ),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(edge_id="edge.draft.router", source_node_id="draft", target_node_id="router", edge_type="handoff"),
            TaskGraphEdgeDefinition(edge_id="edge.router.review", source_node_id="router", target_node_id="review", edge_type="handoff"),
        ),
    )
    parent = TaskGraphDefinition(
        graph_id="graph.test.parent_loop_composition",
        title="Parent Loop Composition",
        graph_kind="multi_agent",
        entry_node_id="graph_module.child",
        output_node_id="graph_module.child",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="graph_module.child",
                node_type="graph_module",
                title="导入子图",
                metadata={"linked_graph_id": child.graph_id},
            ),
        ),
    )

    graph_config = build_graph_harness_config_from_graph(
        graph=parent,
        graph_lookup={child.graph_id: child},
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )

    frame = graph_config.loop_frames[0]
    router = next(node for node in graph_config.nodes if node["node_id"] == "graph_module.child::router")
    route_policy = dict(dict(router["loop"]).get("route_policy") or {})

    assert frame["frame_id"] == "graph_module.child::loop.units"
    assert frame["scope_id"] == "graph_module.child::loop.units"
    assert frame["entry_node_id"] == "graph_module.child::draft"
    assert frame["router_node_id"] == "graph_module.child::router"
    assert frame["continue_node_id"] == "graph_module.child::draft"
    assert frame["exit_node_id"] == "graph_module.child::review"
    assert router["loop"]["scope_id"] == "graph_module.child::loop.units"
    assert route_policy["scope_id"] == "graph_module.child::loop.units"
    assert route_policy["continue_node_id"] == "graph_module.child::draft"
    assert route_policy["exit_node_id"] == "graph_module.child::review"


def test_scheduler_view_uses_only_dependency_edges() -> None:
    graph_config = _graph_harness_config()
    scheduler = build_scheduler_view(graph_config)

    dependency_edge_ids = {str(edge.get("edge_id")) for edge in scheduler.dependency_edges}

    assert scheduler.executable_node_ids == ("draft", "review", "memory.commit")
    assert dependency_edge_ids == {"edge.draft.review", "edge.draft.memory_commit"}
    assert scheduler.start_node_ids == ("draft",)
    assert set(scheduler.terminal_node_ids) == {"review", "memory.commit"}


def test_graph_harness_config_rejects_unknown_scheduler_role() -> None:
    graph_config = _graph_harness_config()
    payload = graph_config.to_dict()
    payload["edges"][0]["scheduler_role"] = "unsupported_scheduler_role"

    try:
        graph_harness_config_from_dict(payload)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "scheduler_role" in str(raised)


def test_graph_harness_config_rejects_unknown_edge_type_without_explicit_extension_role() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.unknown_edge_type",
        title="Unknown Edge Type",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(node_id="draft", node_type="agent", title="起草", agent_id="agent:0"),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="custom_payload",
            ),
        ),
    )

    try:
        build_graph_harness_config_from_graph(
            graph=graph,
            contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
        )
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "unknown graph edge_type" in str(raised)


def test_explicit_extension_edge_is_preserved_but_not_scheduled() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.extension_edge",
        title="Extension Edge",
        graph_kind="multi_agent",
        entry_node_id="",
        output_node_id="",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(node_id="draft", node_type="agent", title="起草", agent_id="agent:0"),
            TaskGraphNodeDefinition(node_id="review", node_type="agent", title="审核", agent_id="agent:0"),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review.note",
                source_node_id="draft",
                target_node_id="review",
                edge_type="custom_payload",
                metadata={"harness_semantic_role": "extension", "scheduler_role": "none"},
            ),
        ),
    )

    graph_config = build_graph_harness_config_from_graph(
        graph=graph,
        contract_manifest={"manifest_id": "contract-manifest:test", "valid": True},
    )
    edge = graph_config.edges[0]
    scheduler = build_scheduler_view(graph_config)

    assert edge["semantic_role"] == "extension"
    assert edge["scheduler_role"] == "none"
    assert scheduler.dependency_edges == ()
    assert scheduler.start_node_ids == ("draft", "review")


def test_graph_loop_completion_counts_executable_nodes_not_resource_nodes(tmp_path: Path) -> None:
    from harness import AgentRuntimeServices, GraphHarness
    from harness.runtime import SingleAgentRuntimeHost

    graph_config = _graph_harness_config()
    host = SingleAgentRuntimeHost(tmp_path / "runtime_state", backend_dir=BACKEND_DIR)
    services = AgentRuntimeServices.from_runtime_host(host)
    graph_harness = GraphHarness(services=services)
    start = graph_harness.start_run(
        session_id="session:test",
        task_id="",
        graph_config=graph_config,
        dispatch_ready=True,
    )

    state = start.loop_state
    pending_orders = list(start.node_work_orders)
    for node_id in ("draft", "review", "memory.commit"):
        order = next(item for item in pending_orders if item.node_id == node_id)
        advance = graph_harness.accept_node_result(
            graph_config=graph_config,
            graph_run_id=start.graph_run.graph_run_id,
            result=NodeResultEnvelope(
                result_id=f"nresult:test:{node_id}",
                graph_run_id=start.graph_run.graph_run_id,
                task_run_id=start.task_run.task_run_id,
                node_id=node_id,
                work_order_id=order.work_order_id,
                outputs={"ok": node_id},
            ),
        )
        state = advance.loop_state
        pending_orders = list(advance.node_work_orders)

    assert state.status == "completed"
    assert set(state.completed_node_ids) == {"draft", "review", "memory.commit"}
    assert "memory.world" not in state.completed_node_ids
    assert "issue.ledger" not in state.completed_node_ids
