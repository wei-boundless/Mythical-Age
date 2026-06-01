from __future__ import annotations

from pathlib import Path

from artifact_system.artifact_repository_models import ArtifactRecord
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository
from task_system.writing.artifact_projection_service import ArtifactProjectionService


def test_writing_artifact_projection_maps_known_artifact_type_to_design_section(tmp_path: Path) -> None:
    manifest = ProjectLibraryManifestRepository(tmp_path).require_for_project("project.creation.writing.honghuang")
    artifact = ArtifactRecord(
        artifact_id="artifact.world.1",
        artifact_ref="artifact:world.md",
        path="world.md",
        repository_id="repo",
        collection_id="default",
        output_contract_id="contract.writing.world_design.output",
        artifact_kind="file",
        metadata={"artifact_type": "world_design_candidate"},
    )

    decision = ArtifactProjectionService(tmp_path).decide(artifact=artifact, manifest=manifest, project_kind="long_novel")

    assert decision.projection_state == "candidate"
    assert decision.target_repository_id == "repo.writing.memory_repository"
    assert decision.target_section_id == "worldbuilding"


def test_writing_artifact_projection_quarantines_unmapped_artifact_type(tmp_path: Path) -> None:
    manifest = ProjectLibraryManifestRepository(tmp_path).require_for_project("project.creation.writing.honghuang")
    artifact = ArtifactRecord(
        artifact_id="artifact.unknown.1",
        artifact_ref="artifact:unknown.md",
        path="unknown.md",
        repository_id="repo",
        collection_id="default",
        artifact_kind="file",
        metadata={"artifact_type": "unknown_candidate"},
    )

    decision = ArtifactProjectionService(tmp_path).decide(artifact=artifact, manifest=manifest, project_kind="long_novel")

    assert decision.projection_state == "quarantined"
    assert "no projection rule" in decision.reason
