from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout


class TaskSystemStorage:
    """Narrow JSON storage adapter for task-system repositories."""

    SNAPSHOT_BUCKETS = {"run_snapshots", "debug_snapshots"}

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.root = ProjectLayout.from_backend_dir(self.base_dir).tasks_dir

    def path(self, filename: str) -> Path:
        return self.root / _normalize_filename(filename)

    def snapshot_path(self, bucket: str, filename: str) -> Path:
        normalized_bucket = str(bucket or "").strip()
        if normalized_bucket not in self.SNAPSHOT_BUCKETS:
            raise ValueError(f"Unsupported task snapshot bucket: {bucket}")
        return self.root / normalized_bucket / _normalize_filename(filename)

    def read_object(self, filename: str, fallback: dict[str, Any]) -> dict[str, Any]:
        path = self.path(filename)
        if not path.exists():
            return fallback
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback
        return loaded if isinstance(loaded, dict) else fallback

    def write_object(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_snapshot(self, bucket: str, filename: str, fallback: dict[str, Any]) -> dict[str, Any]:
        path = self.snapshot_path(bucket, filename)
        if not path.exists():
            return fallback
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return fallback
        return loaded if isinstance(loaded, dict) else fallback

    def write_snapshot(self, bucket: str, filename: str, payload: dict[str, Any]) -> None:
        path = self.snapshot_path(bucket, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_filename(filename: str) -> Path:
    raw = str(filename or "").replace("\\", "/").strip().lstrip("/")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe task storage path: {filename}")
    return path


