from __future__ import annotations

import hashlib
import re

from normalized_ingestion.models import IndexableUnit, NormalizedBlock, NormalizedDocument, NormalizedObjectRef
from normalized_ingestion.summaries import summarize_page_blocks, summarize_text_fragments

_OBJECT_BLOCK_TYPES = {"table", "figure", "sheet_region", "json_field_group"}
_LEAF_ELIGIBLE_BLOCK_TYPES = {"heading", "title", "paragraph", "list_item", "section_block"}
_MIN_TOKENS = 96
_TARGET_TOKENS = 220
_SOFT_MAX_TOKENS = 320
_HARD_MAX_TOKENS = 420


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

    section_units = _build_leaf_and_parent_units(document, blocks)
    units.extend(section_units)

    for block in blocks:
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
                        node_kind="leaf",
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
                node_kind="page",
                page=page,
                block_type="page_summary",
                metadata={
                    "page": page,
                    "parser_backend": document.parser_backend,
                    "source_type": document.source_type,
                    "structure_contract_version": document.structure_contract_version,
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
                node_kind="leaf",
                object_ref_id=object_ref.object_ref_id,
                page=object_ref.page,
                block_type=object_ref.object_type,
                section_path=object_ref.section_path,
                metadata={
                    **dict(object_ref.metadata),
                    "parser_backend": document.parser_backend,
                    "source_type": document.source_type,
                    "structure_contract_version": document.structure_contract_version,
                    "unit_view": "object_anchor",
                },
                quality_flags=document.quality_flags,
            )
        )
    return units


def _build_leaf_and_parent_units(
    document: NormalizedDocument,
    blocks: list[NormalizedBlock],
) -> list[IndexableUnit]:
    units: list[IndexableUnit] = []
    eligible_blocks = [
        block
        for block in blocks
        if block.eligibility != "drop"
        and (
            "dense_main" in block.index_profiles
            or "lexical_main" in block.index_profiles
            or block.block_type in _LEAF_ELIGIBLE_BLOCK_TYPES
        )
    ]
    if not eligible_blocks:
        return units

    section_groups = _group_blocks_by_section(eligible_blocks)
    parent_unit_ids: list[str] = []
    leaf_units: list[IndexableUnit] = []

    for section_key, section_blocks in section_groups:
        leaf_chunks = _build_leaf_chunks(section_blocks)
        if not leaf_chunks:
            continue
        parent_unit_id = _stable_id(document.doc_id, "parent_section", section_key)
        parent_unit_ids.append(parent_unit_id)
        section_texts: list[str] = []
        section_block_ids: list[str] = []
        for index, chunk_blocks in enumerate(leaf_chunks, start=1):
            leaf_text = _compose_leaf_text(chunk_blocks)
            if not leaf_text:
                continue
            section_texts.append(leaf_text)
            section_block_ids.extend(block.block_id for block in chunk_blocks)
            primary = chunk_blocks[0]
            leaf_unit_id = _stable_id(document.doc_id, "leaf_block", section_key, str(index))
            leaf_units.append(
                IndexableUnit(
                    unit_id=leaf_unit_id,
                    unit_type="content_block",
                    collection=document.collection,
                    doc_id=document.doc_id,
                    source_path=document.source_path,
                    text=leaf_text,
                    modality=primary.modality,
                    node_kind="leaf",
                    parent_unit_id=parent_unit_id,
                    block_id=primary.block_id,
                    object_ref_id=primary.object_ref_ids[0] if primary.object_ref_ids else None,
                    page=primary.page,
                    block_type=primary.block_type,
                    section_path=primary.section_path,
                    metadata=_chunk_metadata(
                        document,
                        primary,
                        chunk_blocks,
                        unit_view="leaf_block",
                    ),
                    quality_flags=document.quality_flags,
                )
            )
        if section_texts:
            parent_primary = section_blocks[0]
            units.append(
                IndexableUnit(
                    unit_id=parent_unit_id,
                    unit_type="parent_section",
                    collection=document.collection,
                    doc_id=document.doc_id,
                    source_path=document.source_path,
                    text=summarize_text_fragments(section_texts, max_chars=900, max_fragments=5),
                    modality="text",
                    node_kind="parent",
                    page=parent_primary.page,
                    block_type="parent_section",
                    section_path=parent_primary.section_path,
                    metadata={
                        **_unit_metadata(document, parent_primary, unit_view="parent_section"),
                        "index_profiles": ["context_only"],
                        "child_unit_ids": [
                            unit.unit_id
                            for unit in leaf_units
                            if unit.parent_unit_id == parent_unit_id
                        ],
                        "merged_block_ids": section_block_ids,
                        "token_count": sum(_estimate_token_count(text) for text in section_texts),
                    },
                    quality_flags=document.quality_flags,
                )
            )

    units.extend(leaf_units)

    if leaf_units:
        units.append(
            IndexableUnit(
                unit_id=_stable_id(document.doc_id, "document_summary"),
                unit_type="document_summary",
                collection=document.collection,
                doc_id=document.doc_id,
                source_path=document.source_path,
                text=summarize_text_fragments([unit.text for unit in leaf_units], max_chars=1200, max_fragments=6),
                modality="text",
                node_kind="document",
                block_type="document_summary",
                metadata={
                    "title": document.title,
                    "parser_backend": document.parser_backend,
                    "source_type": document.source_type,
                    "structure_contract_version": document.structure_contract_version,
                    "unit_view": "document_summary",
                    "index_profiles": ["context_only"],
                    "child_unit_ids": parent_unit_ids,
                    "fallback_used": document.fallback_used,
                },
                quality_flags=document.quality_flags,
            )
        )

    return units


def _group_blocks_by_section(blocks: list[NormalizedBlock]) -> list[tuple[str, list[NormalizedBlock]]]:
    sorted_blocks = sorted(
        blocks,
        key=lambda item: (
            int(item.page or 0),
            tuple(item.section_path or ()),
            int(item.reading_order or 0),
        ),
    )
    grouped: dict[str, list[NormalizedBlock]] = {}
    for block in sorted_blocks:
        section_key = _section_key(block)
        grouped.setdefault(section_key, []).append(block)
    return list(grouped.items())


def _build_leaf_chunks(blocks: list[NormalizedBlock]) -> list[list[NormalizedBlock]]:
    chunks: list[list[NormalizedBlock]] = []
    current: list[NormalizedBlock] = []
    current_tokens = 0
    for block in blocks:
        text = block.clean_text or block.normalized_text or block.text
        if not text:
            continue
        block_tokens = _estimate_token_count(text)
        if block_tokens > _SOFT_MAX_TOKENS and block.block_type not in _OBJECT_BLOCK_TYPES:
            if current:
                chunks.append(current)
                current = []
                current_tokens = 0
            for split_text in _split_long_text(text):
                pseudo = NormalizedBlock(
                    block_id=block.block_id,
                    doc_id=block.doc_id,
                    block_type=block.block_type,
                    text=block.text,
                    normalized_text=block.normalized_text,
                    source_type=block.source_type,
                    parser_backend=block.parser_backend,
                    section_label=block.section_label,
                    structure_role=block.structure_role,
                    quality_flags=block.quality_flags,
                    clean_text=split_text,
                    cleaning_flags=block.cleaning_flags,
                    eligibility=block.eligibility,
                    drop_reasons=block.drop_reasons,
                    index_profiles=block.index_profiles,
                    page=block.page,
                    section_path=block.section_path,
                    reading_order=block.reading_order,
                    modality=block.modality,
                    bbox=block.bbox,
                    parent_block_id=block.parent_block_id,
                    object_ref_ids=block.object_ref_ids,
                    metadata=dict(block.metadata),
                )
                chunks.append([pseudo])
            continue
        if not current:
            current = [block]
            current_tokens = block_tokens
            continue
        if _can_merge_blocks(current[-1], block, current_tokens=current_tokens, block_tokens=block_tokens):
            current.append(block)
            current_tokens += block_tokens
            continue
        chunks.append(current)
        current = [block]
        current_tokens = block_tokens
    if current:
        chunks.append(current)
    return chunks


def _can_merge_blocks(
    previous: NormalizedBlock,
    current: NormalizedBlock,
    *,
    current_tokens: int,
    block_tokens: int,
) -> bool:
    if previous.doc_id != current.doc_id:
        return False
    if previous.block_type in _OBJECT_BLOCK_TYPES or current.block_type in _OBJECT_BLOCK_TYPES:
        return False
    if previous.section_path != current.section_path:
        return False
    if previous.page != current.page:
        return False
    reading_gap = int(current.reading_order or 0) - int(previous.reading_order or 0)
    if reading_gap not in {0, 1}:
        return False
    if current_tokens + block_tokens > _SOFT_MAX_TOKENS:
        return False
    return current_tokens < _MIN_TOKENS or block_tokens < _MIN_TOKENS


def _compose_leaf_text(blocks: list[NormalizedBlock]) -> str:
    return "\n\n".join(
        str(block.clean_text or block.normalized_text or block.text).strip()
        for block in blocks
        if str(block.clean_text or block.normalized_text or block.text).strip()
    ).strip()


def _chunk_metadata(
    document: NormalizedDocument,
    primary: NormalizedBlock,
    chunk_blocks: list[NormalizedBlock],
    *,
    unit_view: str,
) -> dict[str, object]:
    block_ids = [block.block_id for block in chunk_blocks]
    token_count = sum(_estimate_token_count(block.clean_text or block.normalized_text or block.text) for block in chunk_blocks)
    metadata = _unit_metadata(document, primary, unit_view=unit_view)
    metadata["block_ids"] = block_ids
    metadata["token_count"] = token_count
    metadata["index_profiles"] = ["dense_main", "lexical_main"]
    return metadata


def _section_key(block: NormalizedBlock) -> str:
    section = " > ".join(str(item) for item in block.section_path if str(item).strip())
    if section:
        return f"section::{section}"
    if block.page is not None:
        return f"page::{int(block.page)}"
    return f"doc::{block.doc_id}"


def _estimate_token_count(text: str) -> int:
    chunks = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", str(text or ""))
    return len(chunks)


def _split_long_text(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    parts = [
        piece.strip()
        for piece in re.split(r"(?<=[。！？；;.!?])\s+|(?<=:)\s+|\s*\n+\s*", normalized)
        if piece.strip()
    ]
    if len(parts) <= 1:
        return [normalized]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for part in parts:
        part_tokens = _estimate_token_count(part)
        if current and current_tokens + part_tokens > _TARGET_TOKENS:
            chunks.append(" ".join(current).strip())
            current = [part]
            current_tokens = part_tokens
            continue
        current.append(part)
        current_tokens += part_tokens
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _unit_metadata(document: NormalizedDocument, block: NormalizedBlock, *, unit_view: str) -> dict[str, object]:
    return {
        **dict(block.metadata),
        "title": document.title,
        "section": block.section_label or " > ".join(str(item) for item in block.section_path if str(item).strip()),
        "section_label": block.section_label,
        "structure_role": block.structure_role,
        "source_type": block.source_type or document.source_type,
        "parser_backend": block.parser_backend or document.parser_backend,
        "structure_contract_version": document.structure_contract_version,
        "parser_route": list(document.parser_route),
        "fallback_used": document.fallback_used,
        "cleaning_flags": list(block.cleaning_flags),
        "eligibility": block.eligibility,
        "drop_reasons": list(block.drop_reasons),
        "index_profiles": list(block.index_profiles),
        "unit_view": unit_view,
    }
