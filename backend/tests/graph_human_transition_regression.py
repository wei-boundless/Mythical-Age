from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from harness.graph.checkpoint_store import GraphCheckpointRecord
from harness.graph.loop import GraphLoop
from harness.graph.models import GraphHarnessConfig, GraphLoopState, NodeResultEnvelope
from harness.graph.runtime_objects import store_node_result
from harness.graph.state_machine import GraphStateMachine


class _ObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def put_object(self, kind: str, key: str, payload: dict[str, Any]) -> str:
        ref = f"rtobj:{kind}:{key}"
        self.objects[ref] = dict(payload)
        return ref

    def get_object(self, ref: str) -> dict[str, Any] | None:
        return self.objects.get(str(ref))


class _CheckpointStore:
    def __init__(self) -> None:
        self.records: list[GraphCheckpointRecord] = []

    def put_checkpoint(self, *, state: GraphLoopState, metadata: dict[str, Any] | None = None) -> GraphCheckpointRecord:
        record = GraphCheckpointRecord(
            checkpoint_id=f"checkpoint:{len(self.records) + 1}",
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            config_id=state.config_id,
            config_hash=state.config_hash,
            event_cursor=state.event_cursor,
            state=state.to_dict(),
            metadata=dict(metadata or {}),
        )
        self.records.append(record)
        return record

    def get_latest_state(self, graph_run_id: str) -> dict[str, Any] | None:
        for record in reversed(self.records):
            if record.graph_run_id == graph_run_id:
                return dict(record.state)
        return None

    def get_latest_checkpoint(self, graph_run_id: str) -> GraphCheckpointRecord | None:
        for record in reversed(self.records):
            if record.graph_run_id == graph_run_id:
                return record
        return None

    def list_checkpoints(self, graph_run_id: str, *, limit: int | None = None) -> tuple[GraphCheckpointRecord, ...]:
        records = tuple(record for record in self.records if record.graph_run_id == graph_run_id)
        return records[-limit:] if limit else records

    def put_pending_writes(self, *, graph_run_id: str, task_id: str, writes: tuple[tuple[str, Any], ...]) -> None:
        del graph_run_id, task_id, writes


class _Event:
    def __init__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.event_type = event_type
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return {"event_type": self.event_type, "payload": self.payload}


class _EventLog:
    def append(self, _task_run_id: str, event_type: str, *, payload: dict[str, Any], refs: dict[str, Any]) -> _Event:
        del refs
        return _Event(event_type, payload)


def _services() -> SimpleNamespace:
    return SimpleNamespace(
        graph_checkpoint_store=_CheckpointStore(),
        runtime_objects=_ObjectStore(),
        event_log=_EventLog(),
        state_index=SimpleNamespace(get_task_run=lambda _task_run_id: None),
    )


def _edge(edge_id: str, source: str, target: str, edge_type: str = "handoff") -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_type": edge_type,
        "semantic_role": "revision" if edge_type == "revision_request" else "control",
        "scheduler_role": "conditional_dependency" if edge_type == "revision_request" else "dependency",
        "payload_contract_id": "contract.payload",
    }


def _config(*, include_revision_edge: bool) -> GraphHarnessConfig:
    edges = []
    if include_revision_edge:
        edges.append(_edge("edge.revision.review.revise", "review", "revise", "revision_request"))
    return GraphHarnessConfig(
        config_id="config:human",
        graph_id="graph:human",
        graph_title="Human Gate",
        publish_version="test",
        control={"start_node_ids": ["review"], "max_active_nodes": 1},
        nodes=(
            {"node_id": "review", "node_type": "agent"},
            {"node_id": "revise", "node_type": "agent"},
        ),
        edges=tuple(edges),
    ).with_content_identity(config_id="config:human")


def _waiting_human_gate_state(config: GraphHarnessConfig, services: SimpleNamespace) -> GraphLoopState:
    result = NodeResultEnvelope(
        result_id="result:review",
        graph_run_id="grun:human",
        task_run_id="taskrun:human",
        node_id="review",
        work_order_id="work:review",
        outputs={"verdict": "revise"},
        handoff_summary="verdict: revise",
    )
    result_ref = store_node_result(services, result)
    machine = GraphStateMachine()
    node_states = machine.initial_node_states(config)
    node_states["review"] = {
        **dict(node_states["review"]),
        "status": "waiting_human_gate",
        "result_ref": result_ref,
        "human_gate": {"source_result_ref": result_ref},
    }
    state = GraphLoopState(
        state_id="gstate:human",
        graph_run_id="grun:human",
        task_run_id="taskrun:human",
        session_id="session:human",
        config_id=config.config_id,
        config_hash=config.content_hash,
        graph_id=config.graph_id,
        structure_hash=config.expected_structural_hash(),
        config_snapshot_id=config.config_id,
        config_snapshot_hash=config.content_hash,
        status="waiting_human_gate",
        node_states=node_states,
        edge_states=machine.initial_edge_states(config),
        terminal_reason="waiting_human_gate:review",
    )
    services.graph_checkpoint_store.put_checkpoint(state=state)
    return state


def test_human_gate_revision_requires_declared_edge_and_dispatches_via_readiness() -> None:
    services = _services()
    config = _config(include_revision_edge=True)
    _waiting_human_gate_state(config, services)

    advance = GraphLoop(services=services).apply_human_gate_decision_and_checkpoint(
        graph_config=config,
        graph_run_id="grun:human",
        decision={"node_id": "review", "human_action": "request_revision", "route_target_node_id": "revise"},
    )

    edge_state = advance.loop_state.edge_states["edge.revision.review.revise"]
    assert edge_state["status"] == "ready"
    assert edge_state["decision_ref"] == "human_gate_decision:review:request_revision:revise"
    assert advance.node_work_orders[0].node_id == "revise"
    assert advance.loop_state.node_states["revise"]["status"] == "running"


def test_human_gate_revision_without_declared_edge_blocks_instead_of_readying_target() -> None:
    services = _services()
    config = _config(include_revision_edge=False)
    _waiting_human_gate_state(config, services)

    advance = GraphLoop(services=services).apply_human_gate_decision_and_checkpoint(
        graph_config=config,
        graph_run_id="grun:human",
        decision={"node_id": "review", "human_action": "request_revision", "route_target_node_id": "revise"},
    )

    assert advance.loop_state.status == "blocked"
    assert advance.loop_state.node_states["review"]["blocked_reason"] == "route_edge_not_declared"
    assert advance.loop_state.node_states["revise"]["status"] == "pending"
    assert advance.node_work_orders == ()
