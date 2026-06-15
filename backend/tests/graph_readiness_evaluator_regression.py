from __future__ import annotations

from harness.graph.models import GraphHarnessConfig
from harness.graph.readiness_evaluator import GraphReadinessEvaluator


def _edge(edge_id: str, source: str, target: str) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": "handoff",
        "semantic_role": "control",
        "scheduler_role": "dependency",
    }


def _config(
    *,
    nodes: tuple[dict[str, object], ...] | None = None,
    edges: tuple[dict[str, object], ...] | None = None,
) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id="config:readiness",
        graph_id="graph:readiness",
        graph_title="Readiness",
        publish_version="test",
        content_hash="hash:readiness",
        control={"start_node_ids": ["a"]},
        nodes=nodes
        or (
            {"node_id": "a", "node_type": "agent"},
            {"node_id": "b", "node_type": "agent"},
        ),
        edges=edges or (_edge("edge.a.b", "a", "b"),),
    )


def _node_states(**statuses: str) -> dict[str, dict[str, object]]:
    return {node_id: {"node_id": node_id, "status": status} for node_id, status in statuses.items()}


def _edge_states(**statuses: str) -> dict[str, dict[str, object]]:
    return {edge_id.replace("_", "."): {"edge_id": edge_id.replace("_", "."), "status": status} for edge_id, status in statuses.items()}


def test_completed_upstream_does_not_make_target_ready_without_ready_edge() -> None:
    decision = GraphReadinessEvaluator().evaluate(
        graph_config=_config(),
        node_states=_node_states(a="completed", b="pending"),
        edge_states=_edge_states(edge_a_b="pending"),
    )

    assert "b" not in decision.ready_node_ids
    assert decision.reasons["b"]["decision"] == "waiting"
    assert decision.reasons["b"]["edge_statuses"] == {"edge.a.b": "pending"}


def test_ready_edge_makes_pending_target_ready() -> None:
    decision = GraphReadinessEvaluator().evaluate(
        graph_config=_config(),
        node_states=_node_states(a="completed", b="pending"),
        edge_states=_edge_states(edge_a_b="ready"),
    )

    assert decision.ready_node_ids == ("b",)
    assert decision.reasons["b"]["reason"] == "all_required_incoming_edges_ready"


def test_all_skipped_incoming_edges_skip_target_instead_of_readiness_fallback() -> None:
    decision = GraphReadinessEvaluator().evaluate(
        graph_config=_config(),
        node_states=_node_states(a="completed", b="pending"),
        edge_states=_edge_states(edge_a_b="skipped"),
    )

    assert decision.ready_node_ids == ()
    assert decision.skipped_node_ids == ("b",)
    assert decision.reasons["b"]["reason"] == "all_incoming_edges_skipped"


def test_source_failed_blocks_all_success_join() -> None:
    decision = GraphReadinessEvaluator().evaluate(
        graph_config=_config(),
        node_states=_node_states(a="failed", b="pending"),
        edge_states=_edge_states(edge_a_b="source_failed"),
    )

    assert decision.ready_node_ids == ()
    assert decision.blocked_node_ids == ("b",)
    assert decision.reasons["b"]["reason"] == "incoming_edge_source_failed"


def test_wait_any_allows_ready_when_one_incoming_edge_is_ready() -> None:
    config = _config(
        nodes=(
            {"node_id": "a", "node_type": "agent"},
            {"node_id": "c", "node_type": "agent"},
            {
                "node_id": "b",
                "node_type": "agent",
                "execution": {"wait_policy": "wait_any_upstream_completed", "join_policy": "any_success"},
            },
        ),
        edges=(
            _edge("edge.a.b", "a", "b"),
            _edge("edge.c.b", "c", "b"),
        ),
    )
    decision = GraphReadinessEvaluator().evaluate(
        graph_config=config,
        node_states=_node_states(a="completed", c="pending", b="pending"),
        edge_states={
            "edge.a.b": {"edge_id": "edge.a.b", "status": "ready"},
            "edge.c.b": {"edge_id": "edge.c.b", "status": "pending"},
        },
    )

    assert decision.ready_node_ids == ("b",)
    assert decision.reasons["b"]["reason"] == "any_incoming_edge_ready"
