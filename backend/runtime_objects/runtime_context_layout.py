from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeContextStorageLayout:
    storage_root: Path

    @classmethod
    def from_backend_dir(cls, base_dir: str | Path) -> "RuntimeContextStorageLayout":
        from core.project_layout import ProjectLayout

        return cls(ProjectLayout.from_backend_dir(base_dir).storage_root)

    @classmethod
    def from_project_layout(cls, layout: Any) -> "RuntimeContextStorageLayout":
        return cls(Path(layout.storage_root))

    @classmethod
    def from_storage_root(cls, storage_root: str | Path) -> "RuntimeContextStorageLayout":
        return cls(Path(storage_root))

    @property
    def root(self) -> Path:
        return Path(self.storage_root).resolve() / "runtime_context"

    @property
    def dynamic_context_root(self) -> Path:
        return self.root / "dynamic_context"

    @property
    def tool_results_root(self) -> Path:
        return self.root / "tool_results"

    @property
    def deepsearch_root(self) -> Path:
        return self.root / "deepsearch"

    @property
    def deepsearch_tool_results_root(self) -> Path:
        return self.deepsearch_root / "tool_results"

    def ensure_dirs(self) -> None:
        for path in (
            self.root,
            self.dynamic_context_root,
            self.tool_results_root,
            self.deepsearch_root,
            self.deepsearch_tool_results_root,
        ):
            path.mkdir(parents=True, exist_ok=True)


__all__ = ["RuntimeContextStorageLayout"]

