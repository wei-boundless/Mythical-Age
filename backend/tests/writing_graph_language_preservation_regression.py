from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from harness.graph.scheduler_view import build_scheduler_view
from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.compiler.graph_harness_config_publisher import build_graph_harness_config_from_runtime_spec
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
    runtime_spec = compile_task_graph_definition_runtime_spec(graph=graph)
    return build_graph_harness_config_from_runtime_spec(
        graph=graph,
        runtime_spec=runtime_spec,
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


def test_scheduler_view_uses_only_dependency_edges() -> None:
    graph_config = _graph_harness_config()
    scheduler = build_scheduler_view(graph_config)

    dependency_edge_ids = {str(edge.get("edge_id")) for edge in scheduler.dependency_edges}

    assert scheduler.executable_node_ids == ("draft", "review", "memory.commit")
    assert dependency_edge_ids == {"edge.draft.review", "edge.draft.memory_commit"}
    assert scheduler.start_node_ids == ("draft",)
    assert set(scheduler.terminal_node_ids) == {"review", "memory.commit"}
