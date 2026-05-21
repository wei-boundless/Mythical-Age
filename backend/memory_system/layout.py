from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def durable_memory_layout_from_backend_dir(base_dir: str | Path) -> DurableMemoryLayout:
    layout = ProjectLayout.from_backend_dir(base_dir)
    return DurableMemoryLayout(layout.durable_memory_dir)
