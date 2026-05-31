from __future__ import annotations

import asyncio
from pathlib import Path

from api import task_system as tasks_api
from task_system import TaskFlowRegistry, build_task_graph_standard_view, list_semantic_relation_presets, resolve_semantic_relation, semantic_relation_catalog
from task_system.compiler.layered_graph_normalizer import normalize_task_graph_layers
from tests.support.runtime_stubs import RuntimeBaseDirStub


def test_semantic_relation_catalog_includes_writing_and_memory_edges() -> None:
    presets = list_semantic_relation_presets()
    catalog = semantic_relation_catalog()
    relation_ids = {item.relation_id for item in presets}

    assert "writing.draft_to_review" in relation_ids
    assert "writing.review_revise_to_writer" in relation_ids
    assert "memory.read_required" in relation_ids
    assert "memory.write_candidate" in relation_ids
    assert "memory.commit_after_review" in relation_ids
    assert sum(1 for item in presets if item.category == "memory") == 3
    assert catalog["summary"]["semantic_relation_count"] == len(presets)
    assert any(item["relation_id"] == "memory.commit_after_review" for item in catalog["relations"])


def test_task_system_overview_exposes_task_graph_semantic_relation_catalog(tmp_path: Path) -> None:
    original = tasks_api.require_runtime
    tasks_api.require_runtime = lambda: RuntimeBaseDirStub(tmp_path)  # type: ignore[assignment]
    try:
        payload = asyncio.run(tasks_api.task_system_overview())
    finally:
        tasks_api.require_runtime = original  # type: ignore[assignment]

    graph_management = payload["task_graph_management"]
    catalog = graph_management["semantic_relation_catalog"]

    assert catalog["authority"] == "task_system.task_graph_semantic_relations"
    assert any(item["relation_id"] == "memory.write_candidate" for item in graph_management["semantic_relations"])


def test_resolve_memory_read_relation_outputs_runtime_edge_payload() -> None:
    resolved = resolve_semantic_relation(
        "memory.read_required",
        {
            "repository_id": "memory.world",
            "collection_id": "world_bible",
            "record_kind": "world_fact",
            "usage_instruction": "你只能使用已审核通过的世界观资料。",
        },
    )

    assert resolved["edge_type"] == "memory_read"
    assert resolved["metadata"]["repository"] == "memory.world"
    assert resolved["metadata"]["collection"] == "world_bible"
    assert resolved["metadata"]["selector"]["record_kind"] == "world_fact"
    assert resolved["metadata"]["usage_instruction"] == "你只能使用已审核通过的世界观资料。"
    assert resolved["metadata"]["semantic_relation_id"] == "memory.read_required"
    assert resolved["contract_bindings"]["semantic"]["relation_id"] == "memory.read_required"
    assert resolved["contract_bindings"]["memory"]["operation"] == "read"


def test_resolved_semantic_relations_are_visible_in_layered_and_standard_views(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    read_relation = resolve_semantic_relation(
        "memory.read_required",
        {
            "repository_id": "memory.world",
            "collection_id": "world_bible",
            "record_kind": "world_fact",
        },
    )
    review_relation = resolve_semantic_relation(
        "writing.review_revise_to_writer",
        {"verdict_key": "review_verdict", "required_verdict": "revise"},
    )
    registry.upsert_task_graph(
        graph_id="graph.test.semantic_relations",
        title="语义关系图",
        graph_kind="coordination",
        entry_node_id="writer",
        output_node_id="reviewer",
        nodes=(
            {"node_id": "writer", "node_type": "agent", "title": "写手", "agent_id": "agent:writer"},
            {"node_id": "reviewer", "node_type": "review_gate", "title": "审核员", "agent_id": "agent:reviewer"},
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "title": "世界观记忆",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [
                            {
                                "collection_id": "world_bible",
                                "record_kinds": ["world_fact"],
                                "content_requirement": {"canonical_text_required": True},
                            }
                        ],
                    }
                },
            },
        ),
        edges=(
            {
                "edge_id": "edge.memory.world.writer",
                "source_node_id": "memory.world",
                "target_node_id": "writer",
                "edge_type": read_relation["edge_type"],
                "payload_contract_id": read_relation["payload_contract_id"],
                "metadata": read_relation["metadata"],
                "contract_bindings": read_relation["contract_bindings"],
            },
            {
                "edge_id": "edge.review.revise",
                "source_node_id": "reviewer",
                "target_node_id": "writer",
                "edge_type": review_relation["edge_type"],
                "payload_contract_id": review_relation["payload_contract_id"],
                "metadata": review_relation["metadata"],
                "contract_bindings": review_relation["contract_bindings"],
            },
        ),
    )
    graph = registry.get_task_graph("graph.test.semantic_relations")
    assert graph is not None

    layered = normalize_task_graph_layers(graph)
    standard = build_task_graph_standard_view(graph=graph, graph_lookup=registry).to_dict()

    assert layered["summary"]["semantic_relation_count"] == 2
    assert any(item["relation_id"] == "memory.read_required" for item in layered["semantic_relations"])
    assert any(item["edge_id"] == "edge.memory.world.writer" for item in layered["memory_protocol"]["read_edges"])
    assert any(item["relation_id"] == "writing.review_revise_to_writer" for item in layered["semantic_relations"])
    review_edge = next(item for item in standard["edges"] if item["edge_id"] == "edge.review.revise")
    assert review_edge["semantic"]["contract_family_id"] == "writing.revision_request"
    assert review_edge["revision"]["trigger"] == {"review_verdict": "revise"}


def test_task_graph_edge_model_resolves_semantic_relation_from_minimal_payload(tmp_path: Path) -> None:
    registry = TaskFlowRegistry(tmp_path)
    registry.upsert_task_graph(
        graph_id="graph.test.semantic_minimal",
        title="最小语义边图",
        graph_kind="coordination",
        entry_node_id="writer",
        output_node_id="reviewer",
        nodes=(
            {"node_id": "writer", "node_type": "agent", "title": "写手"},
            {"node_id": "reviewer", "node_type": "review_gate", "title": "审核员"},
            {
                "node_id": "memory.world",
                "node_type": "memory_repository",
                "title": "世界观记忆",
                "metadata": {
                    "memory_repository": {
                        "repository_id": "memory.world",
                        "collections": [{"collection_id": "world_bible", "record_kinds": ["world_fact"]}],
                    }
                },
            },
        ),
        edges=(
            {
                "edge_id": "edge.memory.semantic",
                "source_node_id": "memory.world",
                "target_node_id": "writer",
                "metadata": {
                    "semantic_relation_id": "memory.read_required",
                    "semantic_parameters": {
                        "repository_id": "memory.world",
                        "collection_id": "world_bible",
                        "record_kind": "world_fact",
                    },
                },
            },
            {
                "edge_id": "edge.memory.write_candidate",
                "source_node_id": "writer",
                "target_node_id": "memory.world",
                "metadata": {
                    "semantic_relation_id": "memory.write_candidate",
                    "semantic_parameters": {
                        "repository_id": "memory.world",
                        "collection_id": "world_bible",
                        "record_kind": "world_fact",
                        "record_key": "memory.world.world_bible.current",
                        "source_output_key": "world_memory_candidate",
                    },
                },
            },
            {
                "edge_id": "edge.memory.commit",
                "source_node_id": "reviewer",
                "target_node_id": "memory.world",
                "metadata": {
                    "semantic_relation_id": "memory.commit_after_review",
                    "semantic_parameters": {
                        "repository_id": "memory.world",
                        "collection_id": "world_bible",
                        "record_kind": "world_fact",
                        "approval_source_node_id": "reviewer",
                        "visible_after": "next_clock",
                    },
                },
            },
        ),
    )
    graph = registry.get_task_graph("graph.test.semantic_minimal")
    assert graph is not None
    edges = {edge.edge_id: edge for edge in graph.edges}
    read_edge = edges["edge.memory.semantic"]
    write_edge = edges["edge.memory.write_candidate"]
    commit_edge = edges["edge.memory.commit"]

    assert read_edge.edge_type == "memory_read"
    assert read_edge.payload_contract_id == "contract.memory.read"
    assert read_edge.metadata["collection"] == "world_bible"
    assert read_edge.contract_bindings["semantic"]["relation_id"] == "memory.read_required"
    assert write_edge.edge_type == "memory_write_candidate"
    assert write_edge.metadata["source_output_key"] == "world_memory_candidate"
    assert write_edge.contract_bindings["memory"]["operation"] == "write_candidate"
    assert commit_edge.edge_type == "memory_commit"
    assert commit_edge.metadata["approval_source_node_id"] == "reviewer"
    assert commit_edge.metadata["commit_visibility_policy"] == {"required_status": "committed", "visible_after": "next_clock"}
    assert commit_edge.contract_bindings["memory"]["operation"] == "commit"

    layered = normalize_task_graph_layers(graph)
    assert layered["memory_protocol"]["summary"]["read_edge_count"] == 1
    assert layered["memory_protocol"]["summary"]["write_edge_count"] == 1
    assert layered["memory_protocol"]["summary"]["commit_edge_count"] == 1
