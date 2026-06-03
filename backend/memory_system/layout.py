from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from project_layout import ProjectLayout


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
    layout = ProjectLayout.from_backend_dir(base_dir)
    return DurableMemoryLayout(layout.durable_memory_dir)


def environment_durable_memory_scope_from_backend_dir(
    base_dir: str | Path,
    task_environment_id: str,
) -> EnvironmentDurableMemoryScope:
    layout = ProjectLayout.from_backend_dir(base_dir)
    normalized = str(task_environment_id or "").strip()
    if not normalized:
        normalized = "env.general.workspace"
    safe_id = safe_memory_namespace_id(normalized)
    root = layout.durable_memory_dir / "environments" / safe_id
    return EnvironmentDurableMemoryScope(
        namespace_id=durable_memory_namespace_id_for_task_environment(normalized),
        task_environment_id=normalized,
        storage_root=root,
    )


def durable_memory_namespace_id_for_task_environment(task_environment_id: str) -> str:
    return f"env:{safe_memory_namespace_id(task_environment_id)}"


def safe_memory_namespace_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = normalized.replace("..", ".").strip(".-_")
    return normalized[:120] or "env-general-workspace"


