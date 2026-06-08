from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage_layout import (
    MemoryStorageLayout,
    durable_memory_namespace_id_for_task_environment,
    safe_memory_namespace_id,
)


@dataclass(frozen=True, slots=True)
class DurableMemoryLayout:
    root_dir: Path

    @property
    def notes_dir(self) -> Path:
        return self.root_dir / "notes"

    @property
    def index_dir(self) -> Path:
        return self.root_dir / "index"

    @property
    def meta_dir(self) -> Path:
        return self.root_dir / "meta"

    @property
    def index_path(self) -> Path:
        return self.index_dir / "MEMORY.md"

    @property
    def schema_path(self) -> Path:
        return self.meta_dir / "SCHEMA.md"

    def ensure_dirs(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class EnvironmentDurableMemoryScope:
    namespace_id: str
    task_environment_id: str
    storage_root: Path
    scope_kind: str = "environment"
    authority: str = "memory_system.environment_durable_memory_scope"

    def to_dict(self) -> dict[str, str]:
        return {
            "namespace_id": self.namespace_id,
            "task_environment_id": self.task_environment_id,
            "storage_root": str(self.storage_root),
            "scope_kind": self.scope_kind,
            "authority": self.authority,
        }


def durable_memory_layout_from_backend_dir(base_dir: str | Path) -> DurableMemoryLayout:
    storage_layout = MemoryStorageLayout.from_backend_dir(base_dir)
    storage_layout.ensure_dirs()
    return DurableMemoryLayout(storage_layout.durable_global_root)


def environment_durable_memory_scope_from_backend_dir(
    base_dir: str | Path,
    task_environment_id: str,
) -> EnvironmentDurableMemoryScope:
    layout = MemoryStorageLayout.from_backend_dir(base_dir)
    layout.ensure_dirs()
    normalized = str(task_environment_id or "").strip()
    if not normalized:
        normalized = "env.general.workspace"
    safe_id = safe_memory_namespace_id(normalized)
    root = layout.durable_environment_root(normalized)
    return EnvironmentDurableMemoryScope(
        namespace_id=durable_memory_namespace_id_for_task_environment(normalized),
        task_environment_id=normalized,
        storage_root=root,
    )


