from __future__ import annotations

from artifact_system import ArtifactInventoryService
from health_system.artifact_governance_view import HealthArtifactGovernanceViewBuilder


def test_artifact_inventory_classifies_runtime_facts_and_diagnostics(tmp_path) -> None:
    project = tmp_path
    (project / "backend").mkdir()
    events = project / "storage" / "runtime_state" / "events"
    sandbox_cache = project / "storage" / "runtime_cache" / "sandboxes" / "taskrun-demo"
    traces = project / "output" / "local_traces" / "20260530"
    chapter = (
        project
        / "storage"
        / "graph_task_instances"
        / "project_creation_writing_honghuang"
        / "runs"
        / "grun_graph_writing_modular_novel_master_1781549483839"
        / "artifacts"
        / "volume_002"
        / "chapters"
        / "chapter_107"
        / "draft_round_107.md"
    )
    events.mkdir(parents=True)
    sandbox_cache.mkdir(parents=True)
    traces.mkdir(parents=True)
    chapter.parent.mkdir(parents=True)
    (events / "taskrun-test.jsonl").write_text("{}\n", encoding="utf-8")
    (sandbox_cache / "scratch.txt").write_text("cache\n", encoding="utf-8")
    (traces / "local-test.json").write_text("{}", encoding="utf-8")
    chapter.write_text("# Chapter 107\n", encoding="utf-8")

    inventory = ArtifactInventoryService(project).build_inventory()
    ports = {item["port_id"]: item for item in inventory["ports"]}

    assert ports["runtime.events"]["artifact_class"] == "runtime_fact"
    assert ports["runtime.events"]["protected"] is True
    assert ports["runtime.sandbox_cache"]["artifact_class"] == "sandbox_cache"
    assert ports["runtime.sandbox_cache"]["protected"] is False
    assert ports["diagnostics.local_traces"]["artifact_class"] == "diagnostic_trace"
    assert "rebuildable_or_diagnostic" in ports["diagnostics.local_traces"]["protection_reasons"]
    assert ports["graph_task_instances.project_artifacts"]["durability_class"] == "project_artifact"
    assert ports["graph_task_instances.project_artifacts"]["retention_tier"] == "durable_protected"
    assert ports["graph_task_instances.project_artifacts"]["protected"] is True


def test_health_artifact_governance_view_is_read_only(tmp_path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (tmp_path / "storage" / "runtime_state" / "events").mkdir(parents=True)
    (tmp_path / "storage" / "runtime_state" / "events" / "taskrun-test.jsonl").write_text("{}\n", encoding="utf-8")

    view = HealthArtifactGovernanceViewBuilder(backend).build_view()

    assert view["mode"] == "read_only"
    assert view["maintenance_policy"]["runtime_fact_delete_forbidden"] is True
    assert view["summary"]["port_count"] > 0
