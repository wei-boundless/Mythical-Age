from __future__ import annotations

from pathlib import Path

from task_system.projects.project_file_service import ProjectFileService


def test_project_file_service_reads_project_artifact_repository(tmp_path: Path) -> None:
    artifact = tmp_path / "storage" / "task_environments" / "creation" / "writing" / "artifacts" / "honghuang-era-restart" / "project_brief.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("Honghuang project brief", encoding="utf-8")

    service = ProjectFileService(tmp_path)
    tree = service.tree("project.creation.writing.honghuang", "repo.writing.artifact_repository", max_depth=3)
    file_payload = service.read_file("project.creation.writing.honghuang", "repo.writing.artifact_repository", "honghuang-era-restart/project_brief.md")

    assert tree["project_id"] == "project.creation.writing.honghuang"
    assert tree["library_id"] == "library.project.creation.writing.honghuang"
    assert file_payload["content"] == "Honghuang project brief"
    assert file_payload["metadata"]["project_root_ref"] == "environment://artifacts"


def test_project_file_service_rejects_traversal_and_project_external_repository(tmp_path: Path) -> None:
    service = ProjectFileService(tmp_path)

    try:
        service.read_file("project.creation.writing.honghuang", "repo.writing.artifact_repository", "../secret.md")
    except ValueError as exc:
        assert "traversal" in str(exc)
    else:
        raise AssertionError("project file read must reject traversal")

    try:
        service.tree("project.creation.writing.honghuang", "repo.coding.project_workspace")
    except PermissionError as exc:
        assert "not part of the project library" in str(exc)
    else:
        raise AssertionError("project file tree must reject repositories outside the project library")
