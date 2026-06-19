from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.checkpoint_store import GraphCheckpointRecord
from harness.graph.flow_edges import build_inbound_flow_edges, build_outbound_flow_edges
from harness.graph.context_materializer import GraphContextMaterializer
from harness.graph.flow_packet import build_flow_packet, flow_packet_inbound_projection
from harness.graph.loop import GraphLoop
from harness.graph.models import GraphLoopState
from harness.graph.models import GraphHarnessConfig, NodeResultEnvelope
from harness.graph.scheduler_view import build_scheduler_view
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


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


def _graph_loop_services() -> SimpleNamespace:
    return SimpleNamespace(
        graph_checkpoint_store=_CheckpointStore(),
        event_log=SimpleNamespace(append=lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: {})),
        runtime_objects=SimpleNamespace(get_object=lambda _ref: None, put_object=lambda *_args, **_kwargs: ""),
        state_index=SimpleNamespace(get_task_run=lambda _task_run_id: None),
    )


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


def test_flow_packet_preserves_edge_contract_target_slot() -> None:
    graph_config = _config(
        (
            {
                "edge_id": "edge.draft.review.structured",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "structured_handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
                "result_delivery_policy": "contract_payload_and_refs",
                "payload_contract_id": "contract.draft.review.payload",
                "contract_bindings": {
                    "handoff": {
                        "packet_contract_id": "packet.contract.draft.review",
                        "target_context_key": "draft_packet",
                        "target_input_slot": "review_inputs.draft",
                    }
                },
                "context_filter_policy": {"include_output_keys": ["public"], "max_chars": 64},
            },
        )
    )
    state = GraphLoopState(
        state_id="gstate:test:flow_packet",
        graph_run_id="grun:test:flow_packet",
        task_run_id="taskrun:test:flow_packet",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        status="running",
    )
    result = NodeResultEnvelope(
        result_id="nresult:test:draft",
        graph_run_id=state.graph_run_id,
        task_run_id=state.task_run_id,
        node_id="draft",
        work_order_id="gwork:test:draft",
        outputs={"public": "visible", "secret": "hidden"},
    )

    packet = build_flow_packet(
        graph_config=graph_config,
        state=state,
        edge=dict(graph_config.edges[0]),
        result=result,
        result_ref="rtobj:nresult:test:draft",
    )
    inbound = flow_packet_inbound_projection(packet, packet_ref="rtobj:flowpkt:test")

    assert packet.packet_contract_id == "packet.contract.draft.review"
    assert packet.target_context_key == "draft_packet"
    assert packet.target_input_slot == "review_inputs.draft"
    assert inbound["packet_contract_id"] == "packet.contract.draft.review"
    assert inbound["target_context_key"] == "draft_packet"
    assert inbound["target_input_slot"] == "review_inputs.draft"
    assert inbound["payload"]["bounded_outputs"] == {"public": "visible"}


def test_flow_packet_ids_preserve_long_result_identity() -> None:
    graph_config = _config(
        (
            {
                "edge_id": "edge.draft.review.structured",
                "source_node_id": "draft",
                "target_node_id": "review",
                "edge_type": "structured_handoff",
                "semantic_role": "control",
                "scheduler_role": "dependency",
            },
        )
    )
    state = GraphLoopState(
        state_id="gstate:test:flow_packet_long",
        graph_run_id="grun:test:flow_packet_long",
        task_run_id="taskrun:test:flow_packet_long",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        status="running",
    )
    common_prefix = "nresult:" + "x" * 180
    first = build_flow_packet(
        graph_config=graph_config,
        state=state,
        edge=dict(graph_config.edges[0]),
        result=NodeResultEnvelope(
            result_id=f"{common_prefix}:first",
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            node_id="draft",
            work_order_id="gwork:test:draft:first",
            outputs={"public": "first"},
        ),
        result_ref="rtobj:nresult:first",
    )
    second = build_flow_packet(
        graph_config=graph_config,
        state=state,
        edge=dict(graph_config.edges[0]),
        result=NodeResultEnvelope(
            result_id=f"{common_prefix}:second",
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            node_id="draft",
            work_order_id="gwork:test:draft:second",
            outputs={"public": "second"},
        ),
        result_ref="rtobj:nresult:second",
    )

    assert first.packet_id != second.packet_id
    assert flow_packet_inbound_projection(first)["context_id"] != flow_packet_inbound_projection(second)["context_id"]


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
    ).with_content_identity(config_id="ghcfg:test:flow_edges")
    state = GraphLoopState(
        state_id="gstate:test",
        graph_run_id="grun:test",
        task_run_id="taskrun:test",
        session_id="session:test",
        config_id=graph_config.config_id,
        config_hash=graph_config.content_hash,
        graph_id=graph_config.graph_id,
        status="running",
        node_states={
            "plan": {"node_id": "plan", "status": "completed"},
            "draft": {"node_id": "draft", "status": "ready"},
        },
    )
    node = {"node_id": "draft", "node_type": "agent", "title": "起草"}

    materializer = GraphContextMaterializer(services=None)
    inbound_context = materializer.inbound_context_for_node(graph_config=graph_config, state=state, node_id="draft")
    package = materializer.build_input_package(
        graph_config=graph_config,
        state=state,
        node=node,
        inbound_context=inbound_context,
    )

    assert package["inbound_context"] == []
    assert [item["edge_id"] for item in package["memory_view"]["graph_memory_policy"]["read_rules"]] == ["edge.plan.draft.memory"]
    assert [item["edge_id"] for item in package["artifact_view"]["graph_artifact_policy"]["context_edges"]] == ["edge.plan.draft.artifact"]
    assert [item["edge_id"] for item in package["file_view"]["graph_resource_policy"]["file_context_edges"]] == ["edge.plan.draft.file"]

    services = _graph_loop_services()
    services.graph_checkpoint_store.put_checkpoint(state=state)

    dispatch = GraphLoop(services=services).dispatch_ready_and_checkpoint(
        graph_config=graph_config,
        graph_run_id=state.graph_run_id,
    )

    blocked = dispatch.loop_state.node_states["draft"]
    assert dispatch.node_work_orders == ()
    assert dispatch.loop_state.status == "blocked"
    assert dispatch.loop_state.blocked_node_ids == ("draft",)
    assert blocked["blocked_reason"] == "memory_context:formal_memory_service_unavailable"


def test_published_graph_includes_node_and_edge_protocol_indexes() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.protocol_indexes",
        title="Protocol Indexes",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="起草",
                contract_bindings={"schema": {"output_contract_id": "contract.draft.out", "output_keys": ["public"]}},
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                contract_bindings={"schema": {"input_contract_id": "contract.draft.out", "required_inputs": ["上游交接包"]}},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="structured_handoff",
                payload_contract_id="contract.draft.out",
                context_filter_policy={"include_output_keys": ["public"], "max_chars": 32},
                metadata={"input_alias": "上游交接包"},
            ),
        ),
    )

    config = build_graph_harness_config_from_graph(graph=graph)
    contracts = dict(config.contracts)

    assert contracts["node_protocol_index"]["draft"]["produced_payload_contract_ids"] == ["contract.draft.out"]
    assert contracts["node_protocol_index"]["review"]["accepted_payload_contract_ids"] == ["contract.draft.out"]
    assert contracts["edge_protocol_index"]["edge.draft.review"]["source_output_keys"] == ["public"]
    assert contracts["edge_protocol_index"]["edge.draft.review"]["target_input_keys"] == ["上游交接包"]


def test_publish_fails_when_edge_references_unknown_source_output_key() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.bad_source_output_key",
        title="Bad Source Output Key",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="起草",
                contract_bindings={"schema": {"output_contract_id": "contract.draft.out", "output_keys": ["public"]}},
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                contract_bindings={"schema": {"input_contract_id": "contract.draft.out"}},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="structured_handoff",
                payload_contract_id="contract.draft.out",
                context_filter_policy={"include_output_keys": ["secret"], "max_chars": 32},
            ),
        ),
    )

    try:
        build_graph_harness_config_from_graph(graph=graph)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "edge_source_output_key_not_declared" in str(raised)


def test_publish_fails_when_edge_payload_is_not_accepted_by_target_without_alias() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.test.bad_target_contract",
        title="Bad Target Contract",
        graph_kind="multi_agent",
        entry_node_id="draft",
        output_node_id="review",
        publish_state="published",
        enabled=True,
        nodes=(
            TaskGraphNodeDefinition(
                node_id="draft",
                node_type="agent",
                title="起草",
                contract_bindings={"schema": {"output_contract_id": "contract.draft.out"}},
            ),
            TaskGraphNodeDefinition(
                node_id="review",
                node_type="agent",
                title="审核",
                contract_bindings={"schema": {"input_contract_id": "contract.review.in"}},
            ),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.draft.review",
                source_node_id="draft",
                target_node_id="review",
                edge_type="structured_handoff",
                payload_contract_id="contract.draft.out",
            ),
        ),
    )

    try:
        build_graph_harness_config_from_graph(graph=graph)
        raised = None
    except ValueError as exc:
        raised = exc

    assert raised is not None
    assert "edge_payload_not_accepted_by_target" in str(raised)
