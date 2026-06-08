from __future__ import annotations

from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .formal_memory_service import FormalMemoryService
from .storage_layout import MemoryStorageLayout
from .working_memory_finalizer import WorkingMemoryFinalizer
from .working_memory_service import WorkingMemoryService


class MemoryRuntimeServices:
    """Owns construction of runtime-facing memory services."""

    def __init__(self, layout: MemoryStorageLayout | Path) -> None:
        if isinstance(layout, MemoryStorageLayout):
            self.layout = layout
        else:
            self.layout = MemoryStorageLayout.from_storage_root(Path(layout))
        self.layout.ensure_dirs()
        self.storage_root = self.layout.root
        self.working_memory = WorkingMemoryService(self.layout.working_root)
        self.formal_memory = FormalMemoryService(self.layout.formal_root)
        self.working_memory_finalizer = WorkingMemoryFinalizer(self.working_memory)

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "MemoryRuntimeServices":
        return cls(MemoryStorageLayout.from_project_layout(ProjectLayout.from_backend_dir(base_dir)))

    @classmethod
    def from_runtime_root(cls, root_dir: Any) -> "MemoryRuntimeServices":
        runtime_root = Path(root_dir).resolve()
        if runtime_root.name == "runtime_state" and runtime_root.parent.name == "storage":
            return cls(runtime_root.parent)
        if runtime_root.name == "storage":
            return cls(runtime_root)
        if runtime_root.name == "backend" or (runtime_root / "app.py").exists():
            return cls.from_backend_dir(runtime_root)
        return cls(runtime_root)


