from __future__ import annotations

from pathlib import Path
from typing import Any

from json_file_store import JsonFilePayloadCorrupt, JsonFileStoreError, read_json_dict, write_json_dict
from project_layout import ProjectLayout


class TaskSystemStorageError(RuntimeError):
    pass


class TaskSystemStoragePayloadCorrupt(TaskSystemStorageError):
    pass


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
        try:
            loaded = read_json_dict(path, label=f"task storage object {filename}", missing_factory=lambda: dict(fallback))
        except JsonFilePayloadCorrupt as exc:
            raise TaskSystemStoragePayloadCorrupt(str(exc)) from exc
        except JsonFileStoreError as exc:
            raise TaskSystemStorageError(str(exc)) from exc
        return loaded if isinstance(loaded, dict) else fallback

    def write_object(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.path(filename)
        try:
            write_json_dict(path, payload, label=f"task storage object {filename}")
        except JsonFileStoreError as exc:
            raise TaskSystemStorageError(str(exc)) from exc

    def read_snapshot(self, bucket: str, filename: str, fallback: dict[str, Any]) -> dict[str, Any]:
        path = self.snapshot_path(bucket, filename)
        try:
            loaded = read_json_dict(
                path,
                label=f"task storage snapshot {bucket}/{filename}",
                missing_factory=lambda: dict(fallback),
            )
        except JsonFilePayloadCorrupt as exc:
            raise TaskSystemStoragePayloadCorrupt(str(exc)) from exc
        except JsonFileStoreError as exc:
            raise TaskSystemStorageError(str(exc)) from exc
        return loaded if isinstance(loaded, dict) else fallback

    def write_snapshot(self, bucket: str, filename: str, payload: dict[str, Any]) -> None:
        path = self.snapshot_path(bucket, filename)
        try:
            write_json_dict(path, payload, label=f"task storage snapshot {bucket}/{filename}")
        except JsonFileStoreError as exc:
            raise TaskSystemStorageError(str(exc)) from exc


def _normalize_filename(filename: str) -> Path:
    raw = str(filename or "").replace("\\", "/").strip().lstrip("/")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe task storage path: {filename}")
    return path


