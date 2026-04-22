from __future__ import annotations

import hashlib

from normalized_ingestion.models import IndexableUnit, NormalizedBlock, NormalizedDocument, NormalizedObjectRef
from normalized_ingestion.summaries import summarize_page_blocks

_OBJECT_BLOCK_TYPES = {"table", "figure", "sheet_region", "json_field_group"}


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def build_indexable_units(
    document: NormalizedDocument,
    blocks: list[NormalizedBlock],
    object_refs: list[NormalizedObjectRef],
) -> list[IndexableUnit]:
    units: list[IndexableUnit] = []
    for block in blocks:
        if "dense_main" in block.index_profiles or "lexical_main" in block.index_profiles:
            units.append(
                IndexableUnit(
                    unit_id=_stable_id(document.doc_id, "content_block", block.block_id),
                    unit_type="content_block",
                    collection=document.collection,
                    doc_id=document.doc_id,
                    source_path=document.source_path,
                    text=block.clean_text or block.normalized_text or block.text,
                    modality=block.modality,
                    block_id=block.block_id,
                    object_ref_id=block.object_ref_ids[0] if block.object_ref_ids else None,
                    page=block.page,
                    block_type=block.block_type,
                    section_path=block.section_path,
                    metadata=_unit_metadata(document, block, unit_view="content_block"),
                    quality_flags=document.quality_flags,
                )
            )
        if "object_anchor" in block.index_profiles:
            object_ref_id = block.object_ref_ids[0] if block.object_ref_ids else None
            object_text = block.clean_text or block.normalized_text or block.text
            if object_text.strip():
                units.append(
                    IndexableUnit(
                        unit_id=_stable_id(document.doc_id, "object_block", block.block_id),
                        unit_type="object_block",
                        collection=document.collection,
                        doc_id=document.doc_id,
                        source_path=document.source_path,
                        text=object_text,
                        modality=block.modality,
                        block_id=block.block_id,
                        object_ref_id=object_ref_id,
                        page=block.page,
                        block_type=block.block_type,
                        section_path=block.section_path,
                        metadata=_unit_metadata(document, block, unit_view="object_block"),
                        quality_flags=document.quality_flags,
                    )
                )

    for page in sorted({block.page for block in blocks if block.page is not None}):
        summary = summarize_page_blocks(page, blocks)
        if not summary:
            continue
        units.append(
            IndexableUnit(
                unit_id=_stable_id(document.doc_id, "page_summary", str(page)),
                unit_type="page_summary",
                collection=document.collection,
                doc_id=document.doc_id,
                source_path=document.source_path,
                text=summary,
                modality="text",
                page=page,
                block_type="page_summary",
                metadata={
                    "page": page,
                    "parser_backend": document.parser_backend,
                    "unit_view": "page_summary",
                },
                quality_flags=document.quality_flags,
            )
        )

    known_object_ids = {unit.object_ref_id for unit in units if unit.object_ref_id}
    for object_ref in object_refs:
        if object_ref.object_ref_id in known_object_ids:
            continue
        units.append(
            IndexableUnit(
                unit_id=_stable_id(document.doc_id, "object_block", object_ref.object_ref_id),
                unit_type="object_block",
                collection=document.collection,
                doc_id=document.doc_id,
                source_path=document.source_path,
                text=object_ref.label,
                modality="text",
                object_ref_id=object_ref.object_ref_id,
                page=object_ref.page,
                block_type=object_ref.object_type,
                section_path=object_ref.section_path,
                metadata={
                    **dict(object_ref.metadata),
                    "parser_backend": document.parser_backend,
                    "unit_view": "object_anchor",
                },
                quality_flags=document.quality_flags,
            )
        )
    return units


def _unit_metadata(document: NormalizedDocument, block: NormalizedBlock, *, unit_view: str) -> dict[str, object]:
    return {
        **dict(block.metadata),
        "title": document.title,
        "section": " > ".join(str(item) for item in block.section_path if str(item).strip()),
        "parser_backend": document.parser_backend,
        "cleaning_flags": list(block.cleaning_flags),
        "eligibility": block.eligibility,
        "drop_reasons": list(block.drop_reasons),
        "index_profiles": list(block.index_profiles),
        "unit_view": unit_view,
    }
