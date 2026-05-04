from __future__ import annotations

import shutil
from pathlib import Path

from project_layout import ProjectLayout


def legacy_runtime_data_paths(backend_dir: str | Path) -> tuple[Path, ...]:
    layout = ProjectLayout.from_backend_dir(backend_dir)
    return (
        layout.backend_dir / "storage",
        layout.backend_dir / "durable_memory",
        layout.backend_dir / "session-memory",
        layout.backend_dir / "runtime-loop",
        layout.backend_dir / "health-system",
        layout.project_root / "runtime-loop",
    )


def cleanup_legacy_runtime_data(backend_dir: str | Path) -> list[Path]:
    removed: list[Path] = []
    for path in legacy_runtime_data_paths(backend_dir):
        if not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    return removed
