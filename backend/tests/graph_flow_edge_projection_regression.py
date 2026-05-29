from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from harness.graph.context_materializer import GraphContextMaterializer
from harness.graph.models import GraphLoopState
from harness.graph.models import GraphHarnessConfig
from harness.graph.scheduler_view import build_scheduler_view


def _config(edges: tuple[dict, ...]) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id="ghcfg:test:flow_edges",
        graph_id="graph.test.flow_edges",
        graph_title="Flow Edges",
        publish_version="published",
        content_hash="hash",
        nodes=(
            {"node_id": "plan", "node_type": "agent", "title": "计划"},
            {"node_id": "draft", "node_type": "agent", "title": "起草"},
            {"node_id": "review", "node_type": "agent", "title": "审核"},
        ),
        edges=edges,
    )


def test_scheduler_dependency_without_handoff_contract_does_not_become_flow_edge() -> None:
    graph_config = _config(
        (
            {
                "edge_id": "edge.plan.draft.control",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "edge_type": "control",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
            {
                "edge_id": "edge.draft.review.handoff",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
        )
    )

    scheduler = build_scheduler_view(graph_config)
    draft_flow_edges = build_inbound_flow_edges(graph_config, "draft")
    review_flow_edges = build_inbound_flow_edges(graph_config, "review")

    assert [item["edge_id"] for item in scheduler.dependency_edges] == [
        "edge.plan.draft.control",
        "edge.draft.review.handoff",
    ]
    assert draft_flow_edges == ()
    assert [item["edge_id"] for item in review_flow_edges] == ["edge.draft.review.handoff"]


def test_context_edge_becomes_flow_edge_without_affecting_scheduler_readiness() -> None:
    graph_config = _config(
        (
            {
                "edge_id": "edge.plan.draft.dependency",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "edge_type": "control",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
            {
                "edge_id": "edge.plan.review.artifact",
                "source_node_id": "plan",
                "target_node_id": "review",
                "edge_type": "artifact_context",
                "semantic_role": "artifact",
                "scheduler_role": "context",
            },
        )
    )

    scheduler = build_scheduler_view(graph_config)
    review_inbound = build_inbound_flow_edges(graph_config, "review")
    plan_outbound = build_outbound_flow_edges(graph_config, "plan")

    assert [item["edge_id"] for item in scheduler.dependency_edges] == ["edge.plan.draft.dependency"]
    assert [item["edge_id"] for item in review_inbound] == ["edge.plan.review.artifact"]
    assert [item["edge_id"] for item in plan_outbound] == ["edge.plan.review.artifact"]


def test_resource_flow_edges_materialize_as_view_requests_not_result_context() -> None:
    graph_config = _config(
        (
            {
                "edge_id": "edge.plan.draft.memory",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "edge_type": "memory_read",
                "semantic_role": "memory",
                "scheduler_role": "context",
                "metadata": {"repository": "memory.project"},
            },
            {
                "edge_id": "edge.plan.draft.artifact",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "edge_type": "artifact_context",
                "semantic_role": "artifact",
                "scheduler_role": "context",
                "artifact_ref_policy": {"max_refs": 3},
            },
            {
                "edge_id": "edge.plan.draft.file",
                "source_node_id": "plan",
                "target_node_id": "draft",
                "edge_type": "file_read",
                "semantic_role": "file",
                "scheduler_role": "context",
            },
        )
    )
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        status="running",
        node_states={"draft": {"node_id": "draft", "status": "ready"}},
    )
    node = {"node_id": "draft", "node_type": "agent", "title": "起草"}

    order = GraphContextMaterializer(services=None).build_work_order(graph_config=graph_config, state=state, node=node)

    assert order.input_package["inbound_context"] == []
    assert [item["edge_id"] for item in order.memory_view_request["graph_memory_policy"]["read_rules"]] == ["edge.plan.draft.memory"]
    assert [item["edge_id"] for item in order.artifact_view_request["graph_artifact_policy"]["context_edges"]] == ["edge.plan.draft.artifact"]
    assert [item["edge_id"] for item in order.file_view_request["graph_resource_policy"]["file_context_edges"]] == ["edge.plan.draft.file"]
