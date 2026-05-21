from __future__ import annotations

from task_system.compiler.coordination_graph_compiler import compile_task_graph_definition_runtime_spec
from task_system.graphs.task_graph_models import task_graph_from_dict
from task_system.runtime_semantics import compile_runtime_semantics_manifest


def test_runtime_semantics_manifest_is_generic_and_keeps_step_runtime_only() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.runtime_semantics",
            "title": "Runtime Semantics",
            "graph_kind": "multi_agent",
            "metadata": {"timeline_policy": {"scheduling_mode": "phase_then_sequence_index"}},
            "nodes": [
                {
                    "node_id": "draft",
                    "node_type": "agent",
                    "title": "Draft",
                    "phase_id": "phase.work",
                    "sequence_index": 1,
                    "timeline_group_id": "phase.work",
                },
                {
                    "node_id": "validate",
                    "node_type": "review_gate",
                    "title": "Validate",
                    "review_gate_policy": {"is_review_gate": True},
                    "phase_id": "phase.work",
                    "sequence_index": 2,
                },
                {
                    "node_id": "publish",
                    "node_type": "agent",
                    "title": "Publish",
                    "memory_writeback_policy": {"write_mode": "commit"},
                    "phase_id": "phase.publish",
                    "sequence_index": 3,
                },
            ],
            "edges": [
                {"edge_id": "draft_validate", "source_node_id": "draft", "target_node_id": "validate"},
                {"edge_id": "validate_publish", "source_node_id": "validate", "target_node_id": "publish"},
            ],
        }
    )

    manifest = compile_runtime_semantics_manifest(graph).to_dict()

    assert manifest["authority"] == "task_system.runtime_semantics_manifest"
    assert manifest["step_policy"]["editor_visible"] is False
    assert manifest["step_policy"]["runtime_role"] == "dispatch_wave_checkpoint_boundary"
    node_roles = {item["node_id"]: item["semantic_role"] for item in manifest["node_semantics"]}
    assert node_roles == {"draft": "producer", "validate": "validator", "publish": "publisher"}
    edge_roles = {item["edge_id"]: item["semantic_role"] for item in manifest["edge_semantics"]}
    assert edge_roles == {"draft_validate": "validation_input", "validate_publish": "publish_input"}
    diagnostic_codes = {item["code"] for item in manifest["diagnostics"]}
    assert "legacy_timeline_policy_not_runtime_semantics" in diagnostic_codes
    assert "sequence_index_legacy_timing_gate" in diagnostic_codes
    assert "timeline_group_duplicates_phase" in diagnostic_codes

    serialized = str(manifest)
    forbidden_domain_words = ("worldview", "character_design", "chapter", "世界观", "人设", "章节")
    assert not any(word in serialized for word in forbidden_domain_words)


def test_runtime_spec_exposes_runtime_semantics_manifest() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.runtime_spec_semantics",
            "title": "Runtime Spec Semantics",
            "graph_kind": "multi_agent",
            "nodes": [
                {"node_id": "a", "node_type": "agent", "title": "A"},
                {"node_id": "b", "node_type": "barrier", "title": "B", "join_policy": "coordinator_decides"},
            ],
            "edges": [{"edge_id": "a_b", "source_node_id": "a", "target_node_id": "b"}],
        }
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    manifest = spec.diagnostics["runtime_semantics"]

    assert manifest["authority"] == "task_system.runtime_semantics_manifest"
    assert manifest["summary"]["node_count"] == 2
    assert manifest["summary"]["edge_count"] == 1
    assert manifest["summary"]["step_editor_visible"] is False
    node_roles = {item["node_id"]: item["semantic_role"] for item in manifest["node_semantics"]}
    assert node_roles["a"] == "producer"
    assert node_roles["b"] == "aggregator"


def test_runtime_semantics_errors_become_runtime_spec_issues() -> None:
    graph = task_graph_from_dict(
        {
            "graph_id": "graph.test.runtime_semantics_issue",
            "title": "Runtime Semantics Issue",
            "graph_kind": "multi_agent",
            "nodes": [
                {"node_id": "a", "node_type": "agent", "title": "A"},
            ],
            "edges": [
                {"edge_id": "a_missing", "source_node_id": "a", "target_node_id": "missing"},
            ],
        }
    )

    spec = compile_task_graph_definition_runtime_spec(graph=graph)
    issue_codes = {issue.code for issue in spec.issues}

    assert "runtime_semantics_semantic_edge_missing_target" in issue_codes
    assert spec.valid is False
