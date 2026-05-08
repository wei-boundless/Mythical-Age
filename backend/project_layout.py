from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    backend_dir: Path
    project_root: Path
    storage_root: Path

    @classmethod
    def from_backend_dir(cls, backend_dir: str | Path) -> "ProjectLayout":
        resolved_backend = Path(backend_dir).resolve()
        if resolved_backend.name == "backend" or (resolved_backend / "app.py").exists():
            project_root = resolved_backend.parent
        else:
            project_root = resolved_backend
        return cls(
            backend_dir=resolved_backend,
            project_root=project_root,
            storage_root=project_root / "storage",
        )

    @property
    def durable_memory_dir(self) -> Path:
        return self.storage_root / "durable_memory"

    @property
    def session_memory_dir(self) -> Path:
        return self.storage_root / "session_memory"

    @property
    def working_memory_dir(self) -> Path:
        return self.storage_root / "working_memory"

    @property
    def task_durable_memory_dir(self) -> Path:
        return self.storage_root / "task_durable_memory"

    @property
    def sessions_dir(self) -> Path:
        return self.storage_root / "sessions"

    @property
    def runtime_state_dir(self) -> Path:
        return self.storage_root / "runtime_state"

    @property
    def health_system_dir(self) -> Path:
        return self.storage_root / "health_system"

    @property
    def indexes_dir(self) -> Path:
        return self.storage_root / "indexes"

    @property
    def document_cache_dir(self) -> Path:
        return self.storage_root / "document_cache"

    @property
    def modality_artifacts_dir(self) -> Path:
        return self.storage_root / "modality_artifacts"

    @property
    def capability_system_dir(self) -> Path:
        return self.storage_root / "capability_system"

    @property
    def tasks_dir(self) -> Path:
        return self.storage_root / "tasks"

    @property
    def orchestration_dir(self) -> Path:
        return self.storage_root / "orchestration"

    @property
    def test_system_dir(self) -> Path:
        return self.health_system_dir / "maintenance" / "test_system"

    @property
    def knowledge_storage_dir(self) -> Path:
        return self.storage_root / "knowledge"

    def ensure_storage_dirs(self) -> None:
        self._migrate_storage_dir(self.storage_root / "indexes_v2", self.indexes_dir)
        self._migrate_storage_dir(self.storage_root / "document_cache_v2", self.document_cache_dir)
        for path in (
            self.storage_root,
            self.durable_memory_dir,
            self.session_memory_dir,
            self.working_memory_dir,
            self.task_durable_memory_dir,
            self.sessions_dir,
            self.runtime_state_dir,
            self.health_system_dir,
            self.indexes_dir,
            self.document_cache_dir,
            self.modality_artifacts_dir,
            self.capability_system_dir,
            self.tasks_dir,
            self.orchestration_dir,
            self.test_system_dir,
            self.knowledge_storage_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _migrate_storage_dir(legacy_path: Path, target_path: Path) -> None:
        if target_path.exists() or not legacy_path.exists():
            return
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(target_path))


def ensure_project_storage(backend_dir: str | Path) -> ProjectLayout:
    layout = ProjectLayout.from_backend_dir(backend_dir)
    layout.ensure_storage_dirs()
    return layout
