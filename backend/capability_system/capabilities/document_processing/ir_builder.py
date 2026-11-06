from __future__ import annotations

import re

from knowledge_system.conversion.models import ConversionBlock, ConversionResult, SourceFileRecord

from capability_system.capabilities.document_processing.models import (
    DOCUMENT_KERNEL_VERSION,
    DetectedDocumentFormat,
    DocumentAnchor,
    DocumentBlock,
    DocumentDiagnostic,
    DocumentLocation,
    DocumentPart,
    DocumentTable,
    OfficeDocumentIR,
    stable_document_id,
)


def build_office_ir_from_conversion(
    *,
    bundle_id: str,
    record: SourceFileRecord,
    detected_format: DetectedDocumentFormat,
    conversion: ConversionResult,
    diagnostics: tuple[DocumentDiagnostic, ...],
) -> OfficeDocumentIR:
    parts = tuple(_parts_from_conversion(bundle_id, detected_format, conversion))
    part_by_page = {part.location.page: part.part_id for part in parts if part.location.page is not None}
    default_part_id = parts[0].part_id if parts else f"{bundle_id}:part:document"
    anchors: list[DocumentAnchor] = []
    blocks: list[DocumentBlock] = []
    tables: list[DocumentTable] = []
    for index, block in enumerate(conversion.blocks):
        part_id = part_by_page.get(block.page, default_part_id)
        ir_block_id = _ir_block_id(bundle_id, block)
        anchor = _anchor_for_block(bundle_id, block, ir_block_id)
        anchors.append(anchor)
        blocks.append(
            DocumentBlock(
                block_id=ir_block_id,
                part_id=part_id,
                block_type=block.block_type,
                text=block.text,
                normalized_text=_normalize_text(block.text),
                location=DocumentLocation(
                    page=block.page,
                    paragraph_index=index if detected_format.family == "word" else None,
                    bbox=block.bbox,
                    source_part=part_id,
                ),
                anchors=(anchor,),
                confidence=0.72 if conversion.fallback_used else 0.86,
                metadata={
                    "conversion_block_id": block.block_id,
                    "modality": block.modality,
                    "reading_order": block.reading_order,
                    "section_path": list(block.section_path),
                    "projection_source": "rag_conversion",
                },
            )
        )
        if block.block_type in {"table", "sheet_region", "json_field_group"} or block.modality == "table":
            tables.append(
                DocumentTable(
                    table_id=f"{bundle_id}:table:{len(tables)}",
                    part_id=part_id,
                    source_kind=_table_source_kind(detected_format.family),
                    rows=0,
                    columns=0,
                    location=DocumentLocation(page=block.page, bbox=block.bbox, source_part=part_id),
                    metadata={
                        "conversion_block_id": block.block_id,
                        "anchor_id": anchor.anchor_id,
                        "table_structure": "text_projection_only",
                    },
                )
            )
    lineage = {
        "document_kernel_version": DOCUMENT_KERNEL_VERSION,
        "document_bundle_id": bundle_id,
        "conversion_doc_id": conversion.doc_id,
        "conversion_parser_backend": conversion.metadata.get("source_parser_backend") or conversion.parser_backend,
        "conversion_parser_route": list(conversion.metadata.get("source_parser_route") or conversion.parser_route),
    }
    return OfficeDocumentIR(
        document_id=bundle_id,
        source_path=record.source_path,
        detected_format=detected_format,
        parts=parts,
        blocks=tuple(blocks),
        tables=tuple(tables),
        anchors=tuple(anchors),
        lineage=lineage,
        diagnostics=diagnostics,
        metadata={
            "source_path": record.source_path,
            "source_type": record.source_type,
            "version_digest": record.version_digest,
            "ir_source": "rag_projection",
        },
    )


def _parts_from_conversion(
    bundle_id: str,
    detected_format: DetectedDocumentFormat,
    conversion: ConversionResult,
) -> list[DocumentPart]:
    pages = sorted({block.page for block in conversion.blocks if block.page is not None})
    if pages:
        return [
            DocumentPart(
                part_id=f"{bundle_id}:part:page:{page}",
                part_type=_part_type_for_family(detected_format.family),
                name=f"Page {page}",
                order=index,
                location=DocumentLocation(page=page),
                metadata={"page": page},
            )
            for index, page in enumerate(pages)
        ]
    return [
        DocumentPart(
            part_id=f"{bundle_id}:part:document",
            part_type=_part_type_for_family(detected_format.family),
            name=conversion.title or conversion.source_path.rsplit("/", 1)[-1],
            order=0,
            metadata={"source_path": conversion.source_path},
        )
    ]


def _part_type_for_family(family: str) -> str:
    if family == "excel":
        return "sheet"
    if family == "powerpoint":
        return "slide"
    if family == "pdf":
        return "page"
    return "body"


def _table_source_kind(family: str) -> str:
    if family == "excel":
        return "excel_range"
    if family == "powerpoint":
        return "ppt_table"
    if family == "pdf":
        return "pdf_table"
    return "word_table"


def _ir_block_id(bundle_id: str, block: ConversionBlock) -> str:
    return f"{bundle_id}:block:{stable_document_id(block.block_id, str(block.reading_order))[:16]}"


def _anchor_for_block(bundle_id: str, block: ConversionBlock, ir_block_id: str) -> DocumentAnchor:
    normalized_text = _normalize_text(block.text)
    text_digest = stable_document_id(normalized_text)[:16] if normalized_text else "empty"
    value = f"{block.page or 'doc'}:{block.reading_order}:{text_digest}"
    return DocumentAnchor(
        anchor_id=f"{bundle_id}:anchor:{stable_document_id(block.block_id, value)[:16]}",
        anchor_type="text_hash",
        target_id=ir_block_id,
        value=value,
        confidence=0.70 if normalized_text else 0.35,
        stability="medium" if normalized_text else "low",
        metadata={"conversion_block_id": block.block_id},
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()
