from __future__ import annotations

import pytest

from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_graph
from task_system.compiler.writing_graph_config_migrator import (
    WRITING_GRAPH_MIGRATION_VERSION,
    normalize_writing_graph_for_transition_runtime,
)
from task_system.graphs.task_graph_models import (
    TaskGraphDefinition,
    TaskGraphEdgeDefinition,
    TaskGraphNodeDefinition,
)


def _design_graph(*, include_revision_edge: bool = True) -> TaskGraphDefinition:
    edges = [
        TaskGraphEdgeDefinition(
            edge_id="edge.world_design.world_review",
            source_node_id="world_design",
            target_node_id="world_review",
            edge_type="handoff",
            payload_contract_id="contract.writing.draft_artifact.draft",
        )
    ]
    if include_revision_edge:
        edges.append(
            TaskGraphEdgeDefinition(
                edge_id="edge.revision.world_review.world_design",
                source_node_id="world_review",
                target_node_id="world_design",
                edge_type="revision_request",
                payload_contract_id="contract.writing.revision_request.revise",
                metadata={"trigger": {"verdict": "revise"}, "carry": ["issues", "revision_request"]},
            )
        )
    return TaskGraphDefinition(
        graph_id="graph.writing.modular_novel.design_init",
        title="Writing Design Init",
        graph_kind="multi_agent",
        entry_node_id="world_design",
        output_node_id="world_review",
        nodes=(
            TaskGraphNodeDefinition(
                node_id="world_design",
                node_type="agent",
                title="World Design",
                output_contract_id="contract.writing.draft_artifact.draft",
            ),
            TaskGraphNodeDefinition(
                node_id="world_review",
                node_type="review_gate",
                title="World Review",
                input_contract_id="contract.writing.draft_artifact.draft",
                output_contract_id="contract.writing.review_verdict.pass",
                review_gate_policy={
                    "allowed_verdicts": ["pass", "revise"],
                    "revision_stage_id": "world_design",
                    "approved_slice_schema": {"required": ["world_bible"]},
                    "revision_packet_schema": {"required": ["issues", "revision_request"]},
                },
            ),
        ),
        edges=tuple(edges),
    )


def test_writing_graph_migration_preserves_ids_and_publishes_transition_contracts() -> None:
    graph = _design_graph()
    migrated = normalize_writing_graph_for_transition_runtime(graph)

    assert migrated.graph_id == graph.graph_id
    assert [node.node_id for node in migrated.nodes] == [node.node_id for node in graph.nodes]
    assert [edge.edge_id for edge in migrated.edges] == [edge.edge_id for edge in graph.edges]
    assert migrated.metadata["migration"]["version"] == WRITING_GRAPH_MIGRATION_VERSION

    review_node = next(node for node in migrated.nodes if node.node_id == "world_review")
    assert review_node.metadata["transition_policy"]["review_gate"]["revision_stage_id"] == "world_design"

    revision_edge = next(edge for edge in migrated.edges if edge.edge_id == "edge.revision.world_review.world_design")
    assert revision_edge.metadata["transition_policy"]["revision"]["trigger"] == {"verdict": "revise"}
    assert revision_edge.metadata["readiness_policy"]["ack_policy"] == "explicit_ack"

    config = build_graph_harness_config_from_graph(graph=graph)
    contract = config.contracts["edge_contract_index"]["edge.revision.world_review.world_design"]
    assert contract["transition_policy"]["revision"]["target_node_id"] == "world_design"
    assert contract["readiness_policy"]["ack_required"] is True


def test_writing_graph_migration_fails_when_review_revision_edge_is_missing() -> None:
    with pytest.raises(ValueError, match="revision edge not found"):
        normalize_writing_graph_for_transition_runtime(_design_graph(include_revision_edge=False))


def test_chapter_cycle_migration_requires_and_preserves_loop_frames() -> None:
    graph = TaskGraphDefinition(
        graph_id="graph.writing.modular_novel.chapter_cycle",
        title="Writing Chapter Cycle",
        graph_kind="multi_agent",
        entry_node_id="chapter_unit_router",
        output_node_id="chapter_progress_router",
        nodes=(
            TaskGraphNodeDefinition(node_id="chapter_unit_router", node_type="agent", title="Chapter Unit Router"),
            TaskGraphNodeDefinition(node_id="chapter_draft", node_type="agent", title="Chapter Draft"),
            TaskGraphNodeDefinition(node_id="chapter_progress_router", node_type="agent", title="Chapter Progress Router"),
        ),
        edges=(
            TaskGraphEdgeDefinition(
                edge_id="edge.chapter_unit_router.chapter_draft",
                source_node_id="chapter_unit_router",
                target_node_id="chapter_draft",
                edge_type="handoff",
            ),
            TaskGraphEdgeDefinition(
                edge_id="edge.chapter_draft.chapter_progress_router",
                source_node_id="chapter_draft",
                target_node_id="chapter_progress_router",
                edge_type="handoff",
            ),
        ),
        loop_frames=(
            {"frame_id": "loop.chapter_unit", "entry_node_id": "chapter_draft", "progress_receipt_key": "chapter_progress_receipt"},
            {"frame_id": "loop.chapter_batch", "entry_node_id": "chapter_unit_router"},
            {"frame_id": "loop.volume", "entry_node_id": "chapter_unit_router"},
        ),
    )

    migrated = normalize_writing_graph_for_transition_runtime(graph)

    assert [frame["frame_id"] for frame in migrated.loop_frames] == [
        "loop.chapter_unit",
        "loop.chapter_batch",
        "loop.volume",
    ]
    assert all(frame["transition_policy"]["canonical"] is True for frame in migrated.loop_frames)
