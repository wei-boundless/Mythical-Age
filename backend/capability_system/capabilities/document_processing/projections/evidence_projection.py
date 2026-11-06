from __future__ import annotations

from knowledge_system.conversion.models import ConversionResult, SourceFileRecord

from capability_system.capabilities.document_processing.models import DetectedDocumentFormat, EvidenceProjection


def build_evidence_projection(
    *,
    bundle_id: str,
    record: SourceFileRecord,
    detected_format: DetectedDocumentFormat,
    conversion: ConversionResult,
) -> EvidenceProjection:
    object_refs: list[dict[str, object]] = []
    binding_candidates: list[dict[str, object]] = []
    for block in conversion.blocks:
        metadata = dict(block.metadata)
        anchor_id = str(metadata.get("anchor_id", "") or "")
        ir_block_id = str(metadata.get("ir_block_id", "") or "")
        if block.block_type in {"table", "figure", "sheet_region", "json_field_group"} or block.modality in {"table", "image"}:
            object_refs.append(
                {
                    "source_object_id": str(metadata.get("source_object_id", "") or ""),
                    "ir_block_id": ir_block_id,
                    "anchor_id": anchor_id,
                    "object_type": block.block_type,
                    "modality": block.modality,
                    "page": block.page,
                    "label": block.text[:120],
                }
            )
        if anchor_id and ir_block_id:
            binding_candidates.append(
                {
                    "anchor_id": anchor_id,
                    "ir_block_id": ir_block_id,
                    "page": block.page,
                    "section_path": list(block.section_path),
                    "reading_order": block.reading_order,
                }
            )
    return EvidenceProjection(
        source_object={
            "document_bundle_id": bundle_id,
            "source_path": record.source_path,
            "source_type": record.source_type,
            "detected_family": detected_format.family,
            "detected_container": detected_format.container,
            "conversion_doc_id": conversion.doc_id,
        },
        object_refs=tuple(object_refs),
        artifact_candidates=(),
        binding_candidates=tuple(binding_candidates),
    )
