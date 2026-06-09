from __future__ import annotations

from pathlib import Path

from task_system.projects.project_instance import ProjectInstance, project_instance_from_dict
from task_system.storage import TaskSystemStorage


class ProjectInstanceRepository:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = TaskSystemStorage(self.base_dir)

    def list(self) -> list[ProjectInstance]:
        defaults = [item.to_dict() for item in self._default_projects()]
        payload = self.storage.read_object("project_instances.json", {"projects": defaults})
        projects = [
            project_instance_from_dict(item)
            for item in list(payload.get("projects") or [])
            if isinstance(item, dict)
        ]
        merged = {item.project_id: item for item in self._default_projects()}
        merged.update({item.project_id: item for item in projects})
        normalized = [item.to_dict() for item in sorted(merged.values(), key=lambda item: item.project_id)]
        if payload.get("projects") != normalized:
            self.storage.write_object("project_instances.json", {"projects": normalized})
        result = [project_instance_from_dict(item) for item in normalized]
        for project in result:
            self.validate(project)
        return result

    def list_for_environment(self, environment_id: str) -> list[ProjectInstance]:
        target = str(environment_id or "").strip()
        return [item for item in self.list() if item.environment_id == target]

    def get(self, project_id: str) -> ProjectInstance | None:
        target = str(project_id or "").strip()
        return next((item for item in self.list() if item.project_id == target), None)

    def require(self, project_id: str) -> ProjectInstance:
        project = self.get(project_id)
        if project is None:
            raise KeyError(f"project instance not found: {project_id}")
        return project

    def upsert(self, project: ProjectInstance) -> ProjectInstance:
        self.validate(project)
        projects = [item for item in self.list() if item.project_id != project.project_id]
        projects.append(project)
        self.storage.write_object("project_instances.json", {"projects": [item.to_dict() for item in sorted(projects, key=lambda item: item.project_id)]})
        return project

    def validate(self, project: ProjectInstance) -> None:
        if not project.project_id:
            raise ValueError("project instance requires project_id")
        if not project.environment_id:
            raise ValueError("project instance requires environment_id")
        if not project.library_id:
            raise ValueError("project instance requires library_id")

    def _default_projects(self) -> tuple[ProjectInstance, ...]:
        return (
            ProjectInstance(
                project_id="project.development.codebase.langchain_agent",
                environment_id="env.coding.vibe_workspace",
                title="langchain-agent",
                project_kind="code_project",
                template_id="development.template.codebase",
                library_id="library.project.development.codebase.langchain_agent",
                schema_version="code_project_library.v1",
                metadata={"default_project": True},
            ),
        )
