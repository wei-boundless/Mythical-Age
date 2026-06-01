from __future__ import annotations

from pathlib import Path

from task_system.projects.project_lifecycle_models import ProjectLifecycleRun, project_lifecycle_run_from_dict
from task_system.storage import TaskSystemStorage


class ProjectLifecycleRunRepository:
    def __init__(self, base_dir: Path) -> None:
        self.storage = TaskSystemStorage(Path(base_dir))

    def list(self) -> list[ProjectLifecycleRun]:
        payload = self.storage.read_object("project_lifecycle_runs.json", {"runs": []})
        return [
            project_lifecycle_run_from_dict(item)
            for item in list(payload.get("runs") or [])
            if isinstance(item, dict)
        ]

    def list_for_project(self, project_id: str) -> list[ProjectLifecycleRun]:
        target = str(project_id or "").strip()
        return [item for item in self.list() if item.project_id == target]

    def get(self, run_id: str) -> ProjectLifecycleRun | None:
        target = str(run_id or "").strip()
        return next((item for item in self.list() if item.run_id == target), None)

    def require(self, run_id: str) -> ProjectLifecycleRun:
        run = self.get(run_id)
        if run is None:
            raise KeyError(f"project lifecycle run not found: {run_id}")
        return run

    def upsert(self, run: ProjectLifecycleRun) -> ProjectLifecycleRun:
        runs = [item for item in self.list() if item.run_id != run.run_id]
        runs.append(run)
        self.storage.write_object("project_lifecycle_runs.json", {"runs": [item.to_dict() for item in sorted(runs, key=lambda item: item.run_id)]})
        return run
