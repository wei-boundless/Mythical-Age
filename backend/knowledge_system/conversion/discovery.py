from __future__ import annotations

from pathlib import Path

from knowledge_system.conversion.models import SourceFileRecord
from capability_system.capabilities.retrieval.collections import CollectionConfig


def discover_source_files(
    config: CollectionConfig,
    *,
    backend_dir: Path,
) -> list[SourceFileRecord]:
    allowed_exts = {ext.lower() for ext in config.file_extensions}
    allowed_roots = tuple(path.resolve() for path in (config.allowed_roots or config.source_dirs))
    records: list[SourceFileRecord] = []

    def containing_allowed_root(path: Path) -> Path | None:
        resolved = path.resolve()
        matches: list[Path] = []
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                matches.append(root)
            except ValueError:
                continue
        if not matches:
            return None
        return max(matches, key=lambda item: len(item.parts))

    def source_root_label(root: Path) -> str:
        label = root.name.strip()
        return label or config.name

    for source_dir in config.source_dirs:
        if not source_dir.exists():
            continue
        resolved_source = source_dir.resolve()
        if containing_allowed_root(resolved_source) is None:
            continue
        for path in resolved_source.rglob("*"):
            if not path.is_file():
                continue
            if allowed_exts and path.suffix.lower() not in allowed_exts:
                continue
            root = containing_allowed_root(path)
            if root is None:
                continue
            records.append(
                SourceFileRecord.from_path(
                    path,
                    collection=config.name,
                    root_dir=root,
                    source_root_label=source_root_label(root) if len(allowed_roots) > 1 else "",
                )
            )
    records.sort(key=lambda item: item.source_path.lower())
    return records


