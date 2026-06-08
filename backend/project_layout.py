from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    backend_dir: Path
    project_root: Path
    storage_root: Path
    external_data_root: Path

    @classmethod
    def from_backend_dir(cls, backend_dir: str | Path) -> "ProjectLayout":
        resolved_backend = Path(backend_dir).resolve()
        if resolved_backend.name == "backend" or (resolved_backend / "app.py").exists():
            project_root = resolved_backend.parent
        else:
            project_root = resolved_backend
        storage_root = _resolve_path_env(
            "APP_STORAGE_ROOT",
            default=project_root / "storage",
            base_dir=project_root,
        )
        return cls(
            backend_dir=resolved_backend,
            project_root=project_root,
            storage_root=storage_root,
            external_data_root=_resolve_path_env(
                "APP_EXTERNAL_DATA_ROOT",
                default=project_root.parent / f"{project_root.name}-data",
                base_dir=project_root,
            ),
        )

    @classmethod
    def from_runtime_root(cls, runtime_root: str | Path) -> "ProjectLayout":
        resolved_root = Path(runtime_root).resolve()
        if resolved_root.name == "runtime_state" and resolved_root.parent.name == "storage":
            project_root = resolved_root.parent.parent
            return cls(
                backend_dir=project_root / "backend",
                project_root=project_root,
                storage_root=project_root / "storage",
                external_data_root=_resolve_path_env(
                    "APP_EXTERNAL_DATA_ROOT",
                    default=project_root.parent / f"{project_root.name}-data",
                    base_dir=project_root,
                ),
            )
        if resolved_root.name == "storage":
            project_root = resolved_root.parent
            return cls(
                backend_dir=project_root / "backend",
                project_root=project_root,
                storage_root=resolved_root,
                external_data_root=_resolve_path_env(
                    "APP_EXTERNAL_DATA_ROOT",
                    default=project_root.parent / f"{project_root.name}-data",
                    base_dir=project_root,
                ),
            )
        return cls.from_backend_dir(resolved_root)

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
        return _resolve_path_env(
            "APP_INDEXES_ROOT",
            default=self.external_data_root / "indexes",
            base_dir=self.project_root,
        )

    @property
    def document_cache_dir(self) -> Path:
        return _resolve_path_env(
            "APP_DOCUMENT_CACHE_ROOT",
            default=self.external_data_root / "document_cache",
            base_dir=self.project_root,
        )

    @property
    def modality_artifacts_dir(self) -> Path:
        return _resolve_path_env(
            "APP_MODALITY_ARTIFACTS_ROOT",
            default=self.external_data_root / "modality_artifacts",
            base_dir=self.project_root,
        )

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
        return self.storage_root / "test_system"

    @property
    def knowledge_storage_dir(self) -> Path:
        return _resolve_path_env(
            "APP_KNOWLEDGE_ROOT",
            default=self.external_data_root / "knowledge",
            base_dir=self.project_root,
        )

    def ensure_storage_dirs(self) -> None:
        self._migrate_storage_dir(self.storage_root / "indexes_v2", self.indexes_dir)
        self._migrate_storage_dir(self.storage_root / "indexes", self.indexes_dir)
        self._migrate_storage_dir(self.storage_root / "document_cache_v2", self.document_cache_dir)
        self._migrate_storage_dir(self.storage_root / "document_cache", self.document_cache_dir)
        self._migrate_storage_dir(self.storage_root / "modality_artifacts", self.modality_artifacts_dir)
        self._migrate_storage_dir(self.project_root / "knowledge", self.knowledge_storage_dir)
        self._migrate_storage_dir(self.backend_dir / "knowledge", self.knowledge_storage_dir)
        self._migrate_storage_dir(self.storage_root / "knowledge", self.knowledge_storage_dir)
        self._migrate_storage_dir(self.health_system_dir / "maintenance" / "test_system", self.test_system_dir)
        for path in (
            self.storage_root,
            self.external_data_root,
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
    def _migrate_storage_dir(source_path: Path, target_path: Path) -> None:
        source = source_path.resolve()
        target = target_path.resolve()
        if source == target or not source.exists():
            return
        if target in source.parents:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(source), str(target))
            return
        if not source.is_dir() or not target.is_dir():
            return
        if not any(source.iterdir()):
            shutil.rmtree(source)
            return
        if ProjectLayout._merge_directory_without_overwrite(source, target):
            shutil.rmtree(source)

    @staticmethod
    def _merge_directory_without_overwrite(source_dir: Path, target_dir: Path) -> bool:
        for source_item in source_dir.rglob("*"):
            relative = source_item.relative_to(source_dir)
            target_item = target_dir / relative
            if source_item.is_dir():
                continue
            if target_item.exists():
                try:
                    if target_item.read_bytes() == source_item.read_bytes():
                        continue
                except OSError:
                    pass
                return False
        for source_item in source_dir.rglob("*"):
            relative = source_item.relative_to(source_dir)
            target_item = target_dir / relative
            if source_item.is_dir():
                target_item.mkdir(parents=True, exist_ok=True)
                continue
            if target_item.exists():
                continue
            target_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_item), str(target_item))
        return True


def _resolve_path_env(name: str, *, default: Path, base_dir: Path) -> Path:
    raw = os.getenv(name)
    if raw and raw.strip():
        candidate = Path(raw.strip()).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
    return default.resolve()


def ensure_project_storage(backend_dir: str | Path) -> ProjectLayout:
    layout = ProjectLayout.from_backend_dir(backend_dir)
    layout.ensure_storage_dirs()
    return layout


