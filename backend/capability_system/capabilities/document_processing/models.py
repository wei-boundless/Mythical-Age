from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge_system.conversion.models import ConversionResult, SourceFileRecord, build_conversion_doc_id

DOCUMENT_KERNEL_VERSION = "document_processing_kernel_v1"


def stable_document_id(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(str(part).encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def build_document_bundle_id(record: SourceFileRecord) -> str:
    conversion_doc_id = build_conversion_doc_id(record.collection, record.source_path, record.version_digest)
    return f"docbundle:{conversion_doc_id}"


@dataclass(frozen=True, slots=True)
class DetectedDocumentFormat:
    family: str
    container: str
    extension: str
    confidence: float
    signals: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    declared_type: str = ""

    @property
    def is_office_family(self) -> bool:
        return self.family in {"word", "excel", "powerpoint"}

    def to_metadata(self) -> dict[str, Any]:
        return {
            "detected_family": self.family,
            "detected_container": self.container,
            "detected_extension": self.extension,
            "detected_confidence": self.confidence,
            "format_signals": list(self.signals),
            "format_limitations": list(self.limitations),
            "declared_type": self.declared_type,
        }


@dataclass(frozen=True, slots=True)
class DocumentDiagnostic:
    code: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(slots=True)
class DocumentParserChunk:
    text: str
    source: str
    modality: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentLocation:
    page: int | None = None
    slide_index: int | None = None
    sheet_name: str = ""
    cell_ref: str = ""
    paragraph_index: int | None = None
    shape_id: str = ""
    bbox: tuple[float, float, float, float] | None = None
    source_part: str = ""

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.page is not None:
            payload["page"] = self.page
        if self.slide_index is not None:
            payload["slide_index"] = self.slide_index
        if self.sheet_name:
            payload["sheet_name"] = self.sheet_name
        if self.cell_ref:
            payload["cell_ref"] = self.cell_ref
        if self.paragraph_index is not None:
            payload["paragraph_index"] = self.paragraph_index
        if self.shape_id:
            payload["shape_id"] = self.shape_id
        if self.bbox is not None:
            payload["bbox"] = list(self.bbox)
        if self.source_part:
            payload["source_part"] = self.source_part
        return payload


@dataclass(frozen=True, slots=True)
class DocumentAnchor:
    anchor_id: str
    anchor_type: str
    target_id: str
    value: str
    confidence: float
    stability: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "anchor_type": self.anchor_type,
            "anchor_target_id": self.target_id,
            "anchor_confidence": self.confidence,
            "anchor_stability": self.stability,
            **dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class DocumentPart:
    part_id: str
    part_type: str
    name: str
    order: int
    location: DocumentLocation = field(default_factory=DocumentLocation)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    block_id: str
    part_id: str
    block_type: str
    text: str
    normalized_text: str
    location: DocumentLocation = field(default_factory=DocumentLocation)
    anchors: tuple[DocumentAnchor, ...] = ()
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentTable:
    table_id: str
    part_id: str
    source_kind: str
    rows: int = 0
    columns: int = 0
    location: DocumentLocation = field(default_factory=DocumentLocation)
    cells: tuple[dict[str, Any], ...] = ()
    header_rows: tuple[int, ...] = ()
    inferred_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OfficeDocumentIR:
    document_id: str
    source_path: str
    detected_format: DetectedDocumentFormat
    parts: tuple[DocumentPart, ...] = ()
    blocks: tuple[DocumentBlock, ...] = ()
    tables: tuple[DocumentTable, ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    anchors: tuple[DocumentAnchor, ...] = ()
    styles: tuple[dict[str, Any], ...] = ()
    layout: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[DocumentDiagnostic, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RagProjection:
    conversion_result: ConversionResult
    normalized_document_hint: dict[str, Any] = field(default_factory=dict)
    index_quality_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OfficeProjection:
    office_ir: OfficeDocumentIR
    editable: bool
    supported_actions: tuple[str, ...] = ()
    unsupported_actions: tuple[str, ...] = ()
    preservation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceProjection:
    source_object: dict[str, Any]
    object_refs: tuple[dict[str, Any], ...] = ()
    artifact_candidates: tuple[dict[str, Any], ...] = ()
    binding_candidates: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentProcessingBundle:
    bundle_id: str
    source_record: SourceFileRecord
    detected_format: DetectedDocumentFormat
    office_ir: OfficeDocumentIR
    rag_projection: RagProjection
    office_projection: OfficeProjection
    evidence_projection: EvidenceProjection
    diagnostics: tuple[DocumentDiagnostic, ...] = ()
    parser_route: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()

    @property
    def absolute_path(self) -> Path:
        return self.source_record.absolute_path
