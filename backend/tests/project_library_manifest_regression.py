from __future__ import annotations

from pathlib import Path

from task_system.projects.project_library_manifest import ProjectLibraryManifest, ProjectRepositoryBinding
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository


def test_default_project_library_manifest_declares_project_repositories(tmp_path: Path) -> None:
    repository = ProjectLibraryManifestRepository(tmp_path)

    manifest = repository.require_for_project("project.creation.writing.honghuang")

    assert manifest.library_id == "library.project.creation.writing.honghuang"
    assert manifest.file_profile_id == "file_profile.writing_manuscript"
    assert manifest.repository("repo.writing.artifact_repository") is not None
    assert manifest.repository("repo.writing.artifact_repository").root_ref == "environment://artifacts"  # type: ignore[union-attr]


def test_project_library_manifest_rejects_repository_outside_file_profile(tmp_path: Path) -> None:
    repository = ProjectLibraryManifestRepository(tmp_path)
    manifest = ProjectLibraryManifest(
        library_id="library.project.creation.writing.honghuang",
        project_id="project.creation.writing.honghuang",
        environment_id="env.creation.writing",
        file_profile_id="file_profile.writing_manuscript",
        schema_version="writing_library.v1",
        repositories=(
            ProjectRepositoryBinding("repo.writing.draft_workspace", "draft_workspace", "project://drafts"),
            ProjectRepositoryBinding("repo.managed_project.project_workspace", "bad", "workspace://project"),
        ),
    )

    try:
        repository.validate(manifest)
    except ValueError as exc:
        assert "repository not in file profile" in str(exc)
    else:
        raise AssertionError("manifest must reject repositories outside the project file profile")
