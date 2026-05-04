from __future__ import annotations

from pathlib import Path

from document_conversion.models import SourceFileRecord
from capability_system.units.mcp.local.retrieval.collections import CollectionConfig


def discover_source_files(
    config: CollectionConfig,
    *,
    backend_dir: Path,
) -> list[SourceFileRecord]:
    allowed_exts = {ext.lower() for ext in config.file_extensions}
    allowed_roots = tuple(path.resolve() for path in (config.allowed_roots or config.source_dirs))
    records: list[SourceFileRecord] = []

    def within_allowed_roots(path: Path) -> bool:
        resolved = path.resolve()
        for root in allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    for source_dir in config.source_dirs:
        if not source_dir.exists():
            continue
        resolved_source = source_dir.resolve()
        if not within_allowed_roots(resolved_source):
            continue
        for path in resolved_source.rglob("*"):
            if not path.is_file():
                continue
            if allowed_exts and path.suffix.lower() not in allowed_exts:
                continue
            if not within_allowed_roots(path):
                continue
            records.append(
                SourceFileRecord.from_path(
                    path,
                    collection=config.name,
                    root_dir=backend_dir,
                )
            )
    records.sort(key=lambda item: item.source_path.lower())
    return records
