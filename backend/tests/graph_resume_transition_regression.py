from __future__ import annotations

from harness.graph.checkpoint_store import GraphCheckpointRecord
from harness.graph.context_materializer import GraphContextMaterializer
from harness.graph.models import GraphHarnessConfig, GraphLoopState
from harness.graph.resume import GraphResumeService


class _LoopStub:
    def __init__(self, state: GraphLoopState) -> None:
        self.state = state
        self.checkpoint = GraphCheckpointRecord(
            checkpoint_id="checkpoint:resume",
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            config_id=state.config_id,
            config_hash=state.config_hash,
            event_cursor=state.event_cursor,
            state=state.to_dict(),
        )

    def get_latest_checkpoint(self, graph_run_id: str) -> GraphCheckpointRecord | None:
        return self.checkpoint if graph_run_id == self.state.graph_run_id else None

    def get_state(self, graph_run_id: str) -> GraphLoopState | None:
        return self.state if graph_run_id == self.state.graph_run_id else None


def _config() -> GraphHarnessConfig:
    return GraphHarnessConfig(
        config_id="config:resume",
        graph_id="graph:resume",
        graph_title="Resume",
        publish_version="test",
        control={"start_node_ids": ["a"]},
        nodes=(
            {"node_id": "a", "node_type": "agent"},
            {"node_id": "b", "node_type": "agent"},
        ),
        edges=(
            {
                "edge_id": "edge.a.b",
                "source_node_id": "a",
                "target_node_id": "b",
                "edge_type": "handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
        ),
    ).with_content_identity(config_id="config:resume")


def test_resume_requires_canonical_edge_state_in_checkpoint() -> None:
    config = _config()
    state = GraphLoopState(
        state_id="gstate:resume",
        graph_run_id="grun:resume",
        task_run_id="taskrun:resume",
        session_id="session:resume",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        structure_hash=config.expected_structural_hash(),
        config_snapshot_id=config.config_id,
        config_snapshot_hash=config.content_hash,
        status="running",
        node_states={
            "a": {"node_id": "a", "status": "completed"},
            "b": {"node_id": "b", "status": "pending"},
        },
        edge_states={},
    )

    try:
        GraphResumeService(graph_loop=_LoopStub(state)).resume(
            graph_config=config,
            graph_run_id=state.graph_run_id,
        )
    except ValueError as exc:
        assert "canonical_edge_state_missing" in str(exc)
    else:
        raise AssertionError("resume accepted checkpoint without canonical edge state")


def test_work_order_idempotency_key_includes_inbound_transition_ref() -> None:
    config = _config()
    base_state = {
        "state_id": "gstate:resume",
        "graph_run_id": "grun:resume",
        "task_run_id": "taskrun:resume",
        "session_id": "session:resume",
        "config_id": config.config_id,
        "config_hash": config.content_hash,
        "graph_id": config.graph_id,
        "structure_hash": config.expected_structural_hash(),
        "config_snapshot_id": config.config_id,
        "config_snapshot_hash": config.content_hash,
        "status": "running",
        "node_states": {
            "a": {"node_id": "a", "status": "completed"},
            "b": {"node_id": "b", "status": "pending"},
        },
    }
    first_state = GraphLoopState(
        **base_state,
        edge_states={
            "edge.a.b": {
                "edge_id": "edge.a.b",
                "source_node_id": "a",
                "target_node_id": "b",
                "status": "ready",
                "decision_ref": "node_result:first",
                "source_result_ref": "rtobj:result:first",
            }
        },
    )
    second_state = GraphLoopState(
        **base_state,
        edge_states={
            "edge.a.b": {
                "edge_id": "edge.a.b",
                "source_node_id": "a",
                "target_node_id": "b",
                "status": "ready",
                "decision_ref": "node_result:second",
                "source_result_ref": "rtobj:result:second",
            }
        },
    )
    node = next(dict(item) for item in config.nodes if dict(item).get("node_id") == "b")

    first_order = GraphContextMaterializer().build_work_order(graph_config=config, state=first_state, node=node)
    second_order = GraphContextMaterializer().build_work_order(graph_config=config, state=second_state, node=node)

    assert first_order.explicit_inputs == second_order.explicit_inputs
    assert first_order.idempotency_key != second_order.idempotency_key
