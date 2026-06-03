from __future__ import annotations

from pathlib import Path
from typing import Any

from project_layout import ProjectLayout

from .formal_memory_service import FormalMemoryService
from .working_memory_finalizer import WorkingMemoryFinalizer
from .working_memory_service import WorkingMemoryService


class MemoryRuntimeServices:
    """Owns construction of runtime-facing memory services."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.working_memory = WorkingMemoryService(self.storage_root / "working_memory")
        self.formal_memory = FormalMemoryService(self.storage_root / "formal_memory")
        self.working_memory_finalizer = WorkingMemoryFinalizer(self.working_memory)

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "MemoryRuntimeServices":
        return cls(ProjectLayout.from_backend_dir(base_dir).storage_root)

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


