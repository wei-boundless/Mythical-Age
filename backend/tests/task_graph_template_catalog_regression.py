from __future__ import annotations

from task_system.editor.graph_template_catalog import build_task_graph_template_catalog


def test_task_graph_template_catalog_declares_generic_foundation_layers() -> None:
    catalog = build_task_graph_template_catalog()

    assert catalog["authority"] == "task_system.task_graph_template_catalog"
    assert catalog["summary"]["foundation_layers"] == ["structure", "roles", "memory", "artifacts", "validation"]
    assert catalog["summary"]["enabled_template_count"] == len(catalog["templates"])


def test_long_project_template_uses_repository_layers_and_commit_node() -> None:
    catalog = build_task_graph_template_catalog()
    templates = {item["template_id"]: item for item in catalog["templates"]}
    template = templates["long_project_cycle"]

    memory_layers = {item["layer_id"]: item for item in template["memory_layers"]}
    assert set(memory_layers) == {
        "memory.baseline",
        "memory.mutable",
        "memory.issue_ledger",
        "memory.artifact_index",
    }
    assert memory_layers["memory.baseline"]["mutable"] is False
    assert memory_layers["memory.mutable"]["write_policy"] == "post_review_delta_commit"
    baseline_specs = {item["collection_id"]: item for item in memory_layers["memory.baseline"]["collection_specs"]}
    artifact_specs = {item["collection_id"]: item for item in memory_layers["memory.artifact_index"]["collection_specs"]}
    assert set(baseline_specs) == set(memory_layers["memory.baseline"]["collections"])
    assert baseline_specs["facts"]["content_requirement"]["canonical_text_required"] is True
    assert baseline_specs["facts"]["content_requirement"]["artifact_ref_only_allowed"] is False
    assert artifact_specs["candidate_refs"]["content_requirement"]["canonical_text_required"] is False
    assert artifact_specs["candidate_refs"]["content_requirement"]["artifact_ref_only_allowed"] is True

    slots = {item["slot_id"]: item for item in template["slots"]}
    assert slots["memory_steward"]["default_node_type"] == "memory_commit"
    assert "memory_resource" not in {item["default_node_type"] for item in template["slots"]}


def test_template_catalog_does_not_bake_writing_domain_boundaries_into_foundation() -> None:
    catalog_text = repr(build_task_graph_template_catalog())

    for forbidden in ("novel", "worldview", "chapter", "洪荒", "世界观", "章节"):
        assert forbidden not in catalog_text


