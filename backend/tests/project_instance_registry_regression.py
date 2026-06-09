from __future__ import annotations

from pathlib import Path

from task_system.projects.project_instance import ProjectInstance
from task_system.repositories.project_instance_repository import ProjectInstanceRepository


def test_default_project_instances_are_scoped_to_task_environments(tmp_path: Path) -> None:
    repository = ProjectInstanceRepository(tmp_path)

    office_projects = repository.list_for_environment("env.office.file_search")
    code_projects = repository.list_for_environment("env.coding.vibe_workspace")

    assert office_projects == []
    assert [item.project_id for item in code_projects] == ["project.development.codebase.langchain_agent"]


def test_project_instance_preserves_environment_metadata_without_registry_lookup(tmp_path: Path) -> None:
    repository = ProjectInstanceRepository(tmp_path)
    project = ProjectInstance(
        project_id="project.retired.environment",
        environment_id="env.retired.workspace",
        title="Retired Environment Project",
        library_id="library.project.retired.environment",
    )

    repository.upsert(project)

    loaded = repository.require("project.retired.environment")
    assert loaded.environment_id == "env.retired.workspace"
