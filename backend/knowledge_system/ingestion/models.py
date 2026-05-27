from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    doc_id: str
    source_path: str
    source_type: str
    collection: str
    version_digest: str
    title: str
    language: str | None = None
    page_count: int = 0
    structure_contract_version: str = ""
    parser_route: tuple[str, ...] = ()
    fallback_used: bool = False
    parser_backend: str = ""
    quality_flags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedBlock:
    block_id: str
    doc_id: str
    block_type: str
    text: str
    normalized_text: str
    source_type: str = ""
    parser_backend: str = ""
    section_label: str = ""
    structure_role: str = "content"
    quality_flags: tuple[str, ...] = ()
    clean_text: str = ""
    cleaning_flags: tuple[str, ...] = ()
    eligibility: str = "drop"
    drop_reasons: tuple[str, ...] = ()
    index_profiles: tuple[str, ...] = ()
    page: int | None = None
    section_path: tuple[str, ...] = ()
    reading_order: int = 0
    modality: str = "text"
    bbox: tuple[float, float, float, float] | None = None
    parent_block_id: str | None = None
    object_ref_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizedObjectRef:
    object_ref_id: str
    doc_id: str
    object_type: str
    page: int | None = None
    section_path: tuple[str, ...] = ()
    label: str = ""
    anchor_block_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexableUnit:
    unit_id: str
    unit_type: str
    collection: str
    doc_id: str
    source_path: str
    text: str
    modality: str
    node_kind: str = "leaf"
    parent_unit_id: str | None = None
    block_id: str | None = None
    object_ref_id: str | None = None
    page: int | None = None
    block_type: str | None = None
    section_path: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()


