from __future__ import annotations

from pathlib import Path

import fsspec

from .models import normalize_logical_path


class FsspecLocalFileAdapter:
    """Repository-relative local filesystem adapter backed by fsspec."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.fs = fsspec.filesystem("file")

    def resolve(self, logical_path: str) -> Path:
        normalized = normalize_logical_path(logical_path)
        candidate = (self.root / normalized).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("logical_path escapes repository root")
        return candidate

    def write_text(self, logical_path: str, content: str) -> str:
        target = self.resolve(logical_path)
        self.fs.makedirs(str(target.parent), exist_ok=True)
        with self.fs.open(str(target), "w", encoding="utf-8") as stream:
            stream.write(str(content or ""))
        return target.relative_to(self.root).as_posix()

    def read_text(self, logical_path: str) -> str:
        target = self.resolve(logical_path)
        with self.fs.open(str(target), "r", encoding="utf-8") as stream:
            return stream.read()

    def exists(self, logical_path: str) -> bool:
        return bool(self.fs.exists(str(self.resolve(logical_path))))
