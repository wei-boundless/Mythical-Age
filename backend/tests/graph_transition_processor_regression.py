from __future__ import annotations

from harness.graph.models import (
    GraphHarnessConfig,
    GraphLoopState,
    GraphTransitionInput,
    NodeResultEnvelope,
)
from harness.graph.state_machine import GraphStateMachine
from harness.graph.transition_processor import (
    GraphTransitionProcessor,
    apply_transition_plan_to_edge_states,
)


def _edge(edge_id: str, source: str, target: str, edge_type: str = "handoff") -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "semantic_role": "revision" if edge_type == "revision_request" else "control",
        "scheduler_role": "conditional_dependency" if edge_type == "revision_request" else "dependency",
        "metadata": {
            "transition_policy": {"edge_status": {"initial": "pending"}},
            "readiness_policy": {"ack_required": True, "ack_policy": "explicit_ack"},
        },
    }


def _config(edges: tuple[dict[str, object], ...]) -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id="config:transition",
        graph_id="graph:transition",
        graph_title="Transition",
        publish_version="test",
        content_hash="hash:transition",
        control={"start_node_ids": ["review"]},
        nodes=(
            {"node_id": "review", "node_type": "agent"},
            {"node_id": "commit", "node_type": "agent"},
            {"node_id": "revise", "node_type": "agent"},
        ),
        edges=edges,
    )


def _state(config: GraphHarnessConfig) -> GraphLoopState:
    machine = GraphStateMachine()
    return GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session:test",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        node_states=machine.initial_node_states(config),
        edge_states=machine.initial_edge_states(config),
    )


def _result(status: str = "completed", handoff_summary: str = "verdict: pass") -> NodeResultEnvelope:
    return NodeResultEnvelope(
        result_id=f"result:{status}",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        node_id="review",
        work_order_id="work:review",
        status=status,
        outputs={"verdict": "pass"} if status == "completed" else {},
        handoff_summary=handoff_summary if status == "completed" else "",
        error={"reason": "boom"} if status == "failed" else {},
    )


def _trigger(state: GraphLoopState, result: NodeResultEnvelope) -> GraphTransitionInput:
    return GraphTransitionInput(
        trigger_type="node_result",
        graph_run_id=state.graph_run_id,
        config_id=state.config_id,
        config_hash=state.config_hash,
        graph_clock_seq=7,
        payload={"result": result.to_dict(), "result_ref": "rtobj:result:review"},
    )


def test_node_result_transition_marks_outgoing_edge_ready_with_decision_ref() -> None:
    config = _config((_edge("edge.review.commit", "review", "commit"),))
    state = _state(config)

    plan = GraphTransitionProcessor().plan(
        graph_config=config,
        state=state,
        trigger=_trigger(state, _result()),
    )

    assert len(plan.edge_updates) == 1
    update = plan.edge_updates[0]
    assert update["edge_id"] == "edge.review.commit"
    assert update["status"] == "ready"
    assert update["decision_ref"] == "rtobj:result:review"
    assert update["graph_clock_seq"] == 7
    assert update["policy_snapshot"]["readiness_policy"]["ack_policy"] == "explicit_ack"


def test_failed_node_result_marks_outgoing_edges_source_failed() -> None:
    config = _config((_edge("edge.review.commit", "review", "commit"),))
    state = _state(config)

    plan = GraphTransitionProcessor().plan(
        graph_config=config,
        state=state,
        trigger=_trigger(state, _result(status="failed")),
    )

    assert plan.edge_updates[0]["status"] == "source_failed"
    assert plan.edge_updates[0]["reason"] == "source_result_failed"


def test_review_revision_route_sets_revision_ready_and_pass_edge_skipped() -> None:
    config = _config(
        (
            _edge("edge.review.commit", "review", "commit"),
            _edge("edge.revision.review.revise", "review", "revise", edge_type="revision_request"),
        )
    )
    state = _state(config)

    plan = GraphTransitionProcessor().plan(
        graph_config=config,
        state=state,
        trigger=_trigger(state, _result(handoff_summary="verdict: revise")),
    )
    edge_states = apply_transition_plan_to_edge_states(edge_states=state.edge_states, plan=plan)

    assert edge_states["edge.review.commit"]["status"] == "skipped"
    assert edge_states["edge.revision.review.revise"]["status"] == "ready"
    assert edge_states["edge.revision.review.revise"]["review_verdict_gate"]["routed_to_revision"] is True
