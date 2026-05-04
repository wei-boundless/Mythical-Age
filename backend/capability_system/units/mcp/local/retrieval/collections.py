from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from memory_layout import durable_memory_layout_from_backend_dir
from project_layout import ProjectLayout


@dataclass(frozen=True, slots=True)
class CollectionConfig:
    name: str
    source_dirs: tuple[Path, ...]
    storage_dir: Path
    description: str
    weight: float = 1.0
    file_extensions: tuple[str, ...] = field(default_factory=tuple)
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    allow_chat_queries: bool = True


def build_default_collections(base_dir: Path) -> dict[str, CollectionConfig]:
    layout = ProjectLayout.from_backend_dir(base_dir)
    indexes_dir = layout.storage_root / "indexes"
    knowledge_dir = base_dir / "knowledge"
    benchmark_dir = base_dir / "knowledge-benchmark"
    durable_memory_layout = durable_memory_layout_from_backend_dir(base_dir)
    session_memory_dir = layout.session_memory_dir

    collections = {
        "knowledge": CollectionConfig(
            name="knowledge",
            source_dirs=(knowledge_dir,),
            storage_dir=indexes_dir / "knowledge",
            description="Knowledge base documents of all modalities. Modality stays in metadata.",
            weight=1.0,
            allowed_roots=(knowledge_dir,),
            allow_chat_queries=True,
            file_extensions=(
                ".md",
                ".txt",
                ".json",
                ".csv",
                ".pdf",
                ".docx",
                ".pptx",
                ".xlsx",
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".tiff",
                ".tif",
                ".gif",
                ".webp",
            ),
        ),
        "durable_memory": CollectionConfig(
            name="durable_memory",
            source_dirs=(durable_memory_layout.notes_dir, durable_memory_layout.index_dir),
            storage_dir=indexes_dir / "durable_memory",
            description="Durable long-term memory documents only.",
            weight=1.2,
            allowed_roots=(durable_memory_layout.notes_dir, durable_memory_layout.index_dir),
            allow_chat_queries=True,
            file_extensions=(".md", ".txt"),
        ),
        "session_memory": CollectionConfig(
            name="session_memory",
            source_dirs=(session_memory_dir,),
            storage_dir=indexes_dir / "session_memory",
            description="Per-session working-memory views kept separate from durable memory.",
            weight=0.7,
            allowed_roots=(session_memory_dir,),
            allow_chat_queries=False,
            file_extensions=(".md", ".txt"),
        ),
    }
    if benchmark_dir.exists():
        collections["benchmark"] = CollectionConfig(
            name="benchmark",
            source_dirs=(benchmark_dir,),
            storage_dir=indexes_dir / "benchmark",
            description="Dedicated benchmark/test knowledge collection.",
            weight=1.0,
            allowed_roots=(benchmark_dir,),
            allow_chat_queries=False,
            file_extensions=(".md", ".txt", ".json", ".csv"),
        )
    return collections
