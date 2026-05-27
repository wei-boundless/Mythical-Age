from __future__ import annotations

from pathlib import Path

from project_layout import ProjectLayout


class RetrievalLayout:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.root = ProjectLayout.from_backend_dir(base_dir).indexes_dir

    def ensure(self, *, collections: tuple[str, ...] = ()) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for collection in collections:
            self.collection_dir(collection).mkdir(parents=True, exist_ok=True)

    def collection_dir(self, name: str) -> Path:
        return self.root / name

    def dense_dir(self, name: str) -> Path:
        return self.collection_dir(name) / "dense"

    def sparse_dir(self, name: str) -> Path:
        return self.collection_dir(name) / "sparse"

    def lexical_dir(self, name: str) -> Path:
        return self.collection_dir(name) / "lexical"

    def metadata_path(self, name: str) -> Path:
        return self.collection_dir(name) / "meta.json"

    def units_path(self, name: str) -> Path:
        return self.collection_dir(name) / "units.json"


