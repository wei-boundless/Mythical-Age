from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STRUCTURE_CONTRACT_VERSION = "structure_contract_v2"


def _stable_digest(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def build_conversion_doc_id(collection: str, source_path: str, version_digest: str) -> str:
    return _stable_digest(collection, source_path, version_digest)


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    collection: str
    absolute_path: Path
    source_path: str
    source_type: str
    version_digest: str
    size_bytes: int
    modified_ns: int

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        collection: str,
        root_dir: Path,
        source_root_label: str = "",
    ) -> "SourceFileRecord":
        resolved = path.resolve()
        root = root_dir.resolve()
        stat = resolved.stat()
        try:
            source_path = str(resolved.relative_to(root)).replace("\\", "/")
        except ValueError:
            source_path = resolved.name
        label = str(source_root_label or "").strip().replace("\\", "/").strip("/")
        if label and not source_path.startswith(f"{label}/") and source_path != label:
            source_path = f"{label}/{source_path}"
        version_digest = _stable_digest(
            source_path,
            str(stat.st_mtime_ns),
            str(stat.st_size),
        )
        return cls(
            collection=collection,
            absolute_path=resolved,
            source_path=source_path,
            source_type=resolved.suffix.lower().lstrip(".") or "file",
            version_digest=version_digest,
            size_bytes=int(stat.st_size),
            modified_ns=int(stat.st_mtime_ns),
        )


@dataclass(frozen=True, slots=True)
class ConversionBlock:
    block_id: str
    block_type: str
    text: str
    modality: str = "text"
    section_label: str = ""
    structure_role: str = "content"
    page: int | None = None
    section_path: tuple[str, ...] = ()
    reading_order: int = 0
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConversionPage:
    page_number: int
    raw_text: str = ""
    text_block_count: int = 0
    table_block_count: int = 0
    image_block_count: int = 0
    diagnostic_block_count: int = 0
    has_text: bool = False
    has_usable_text: bool = False
    page_state: str = ""
    state_confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConversionResult:
    doc_id: str
    collection: str
    source_path: str
    source_type: str
    version_digest: str
    parser_backend: str
    title: str = ""
    language: str | None = None
    page_count: int = 0
    structure_contract_version: str = STRUCTURE_CONTRACT_VERSION
    parser_route: tuple[str, ...] = ()
    fallback_used: bool = False
    quality_flags: tuple[str, ...] = ()
    pages: tuple[ConversionPage, ...] = ()
    blocks: tuple[ConversionBlock, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        record: SourceFileRecord,
        *,
        parser_backend: str,
        quality_flags: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> "ConversionResult":
        doc_id = build_conversion_doc_id(record.collection, record.source_path, record.version_digest)
        return cls(
            doc_id=doc_id,
            collection=record.collection,
            source_path=record.source_path,
            source_type=record.source_type,
            version_digest=record.version_digest,
            parser_backend=parser_backend,
            structure_contract_version=STRUCTURE_CONTRACT_VERSION,
            parser_route=(parser_backend,),
            fallback_used=parser_backend != "docling",
            quality_flags=quality_flags,
            metadata=dict(metadata or {}),
        )
