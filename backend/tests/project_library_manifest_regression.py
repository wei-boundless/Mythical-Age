from __future__ import annotations

from pathlib import Path

from task_system.projects.project_library_manifest import ProjectLibraryManifest, ProjectRepositoryBinding
from task_system.repositories.project_library_manifest_repository import ProjectLibraryManifestRepository


def test_default_project_library_manifest_declares_project_repositories(tmp_path: Path) -> None:
    repository = ProjectLibraryManifestRepository(tmp_path)

    manifest = repository.require_for_project("project.development.codebase.langchain_agent")

    assert manifest.library_id == "library.project.development.codebase.langchain_agent"
    assert manifest.file_profile_id == "file_profile.managed_project_workspace"
    assert manifest.repository("repo.managed_project.project_workspace") is not None
    assert manifest.repository("repo.managed_project.project_workspace").root_ref == "workspace://project"  # type: ignore[union-attr]


def test_project_library_manifest_rejects_repository_outside_file_profile(tmp_path: Path) -> None:
    repository = ProjectLibraryManifestRepository(tmp_path)
    manifest = ProjectLibraryManifest(
        library_id="library.project.development.codebase.langchain_agent",
        project_id="project.development.codebase.langchain_agent",
        environment_id="env.coding.vibe_workspace",
        file_profile_id="file_profile.managed_project_workspace",
        schema_version="code_project_library.v1",
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
