from __future__ import annotations

from pathlib import Path

from task_system.projects.project_instance import ProjectInstance
from task_system.repositories.project_instance_repository import ProjectInstanceRepository


def test_default_project_instances_are_scoped_to_task_environments(tmp_path: Path) -> None:
    repository = ProjectInstanceRepository(tmp_path)

    writing_projects = repository.list_for_environment("env.creation.writing")
    code_projects = repository.list_for_environment("env.development.sandbox")

    assert [item.project_id for item in writing_projects] == ["project.creation.writing.honghuang"]
    assert writing_projects[0].library_id == "library.project.creation.writing.honghuang"
    assert writing_projects[0].project_kind == "long_novel"
    assert [item.project_id for item in code_projects] == ["project.development.codebase.langchain_agent"]


def test_project_instance_rejects_unknown_environment(tmp_path: Path) -> None:
    repository = ProjectInstanceRepository(tmp_path)
    project = ProjectInstance(
        project_id="project.unknown.bad",
        environment_id="env.unknown",
        title="Bad",
        library_id="library.project.unknown.bad",
    )

    try:
        repository.validate(project)
    except KeyError:
        pass
    else:
        raise AssertionError("project instance must reject unknown environments")
