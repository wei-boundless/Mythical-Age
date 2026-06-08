from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryStorageLayout:
    storage_root: Path

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "MemoryStorageLayout":
        from project_layout import ProjectLayout

        return cls(ProjectLayout.from_backend_dir(base_dir).storage_root)

    @classmethod
    def from_project_layout(cls, layout: Any) -> "MemoryStorageLayout":
        return cls(Path(layout.storage_root))

    @classmethod
    def from_storage_root(cls, storage_root: str | Path) -> "MemoryStorageLayout":
        return cls(Path(storage_root))

    @property
    def root(self) -> Path:
        return Path(self.storage_root).resolve()

    @property
    def memory_root(self) -> Path:
        return self.root / "memory"

    @property
    def durable_root(self) -> Path:
        return self.memory_root / "durable"

    @property
    def durable_global_root(self) -> Path:
        return self.durable_root / "global_common"

    @property
    def durable_environments_root(self) -> Path:
        return self.durable_root / "environments"

    def durable_environment_root(self, task_environment_id: str) -> Path:
        return self.durable_environments_root / safe_memory_namespace_id(task_environment_id)

    @property
    def session_root(self) -> Path:
        return self.memory_root / "session"

    @property
    def working_root(self) -> Path:
        return self.memory_root / "working"

    @property
    def formal_root(self) -> Path:
        return self.memory_root / "formal"

    @property
    def runtime_root(self) -> Path:
        return self.memory_root / "runtime"

    @property
    def maintenance_root(self) -> Path:
        return self.runtime_root / "maintenance"

    @property
    def durable_governance_root(self) -> Path:
        return self.runtime_root / "durable_governance"

    def ensure_dirs(self) -> None:
        for path in (
            self.memory_root,
            self.durable_root,
            self.durable_global_root,
            self.durable_environments_root,
            self.session_root,
            self.working_root,
            self.formal_root,
            self.runtime_root,
            self.maintenance_root,
            self.durable_governance_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

def durable_memory_namespace_id_for_task_environment(task_environment_id: str) -> str:
    return f"env:{safe_memory_namespace_id(task_environment_id)}"


def safe_memory_namespace_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = normalized.replace("..", ".").strip(".-_")
    return normalized[:120] or "env-general-workspace"


__all__ = [
    "MemoryStorageLayout",
    "durable_memory_namespace_id_for_task_environment",
    "safe_memory_namespace_id",
]
