from __future__ import annotations

import re

from document_conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
from document_conversion.quality import infer_quality_flags


def build_markdown_blocks(markdown: str, record: SourceFileRecord) -> tuple[ConversionBlock, ...]:
    normalized = (markdown or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ()

    parts = [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    blocks: list[ConversionBlock] = []
    current_section = ""
    for idx, part in enumerate(parts):
        stripped = part.strip()
        if not stripped:
            continue
        first_line = stripped.splitlines()[0].strip()
        block_type = "heading" if first_line.startswith("#") else "paragraph"
        modality = "table" if "|" in stripped and "\n" in stripped else "text"
        section_label = current_section
        structure_role = "content"
        section_path: tuple[str, ...] = ()
        if block_type == "heading":
            section_label = re.sub(r"^#+\s*", "", first_line).strip()
            current_section = section_label
            structure_role = "heading"
            section_path = (section_label,) if section_label else ()
        else:
            if current_section:
                section_path = (current_section,)
            if modality == "table":
                structure_role = "object"
        blocks.append(
            ConversionBlock(
                block_id=f"{record.version_digest}:{idx}",
                block_type=block_type if modality != "table" else "table",
                text=stripped,
                modality=modality,
                section_label=section_label,
                structure_role=structure_role,
                section_path=section_path,
                reading_order=idx,
                metadata={
                    "source_type": record.source_type,
                    "source_path": record.source_path,
                },
            )
        )
    return tuple(blocks)


def build_markdown_conversion_result(
    record: SourceFileRecord,
    markdown: str,
    *,
    parser_backend: str,
    title: str = "",
    language: str | None = None,
    page_count: int = 0,
    parser_route: tuple[str, ...] | None = None,
    fallback_used: bool = False,
    metadata: dict[str, object] | None = None,
    doc_id: str | None = None,
) -> ConversionResult:
    empty = ConversionResult.empty(record, parser_backend=parser_backend)
    blocks = build_markdown_blocks(markdown, record)
    if not blocks:
        return ConversionResult.empty(
            record,
            parser_backend=parser_backend,
            quality_flags=("empty_conversion",),
            metadata=dict(metadata or {}),
        )
    quality_flags = infer_quality_flags(blocks, parser_backend=parser_backend)
    return ConversionResult(
        doc_id=str(doc_id or empty.doc_id),
        collection=record.collection,
        source_path=record.source_path,
        source_type=record.source_type,
        version_digest=record.version_digest,
        parser_backend=parser_backend,
        title=title,
        language=language,
        page_count=int(page_count or 0),
        structure_contract_version=empty.structure_contract_version,
        parser_route=tuple(parser_route or (parser_backend,)),
        fallback_used=bool(fallback_used),
        quality_flags=quality_flags,
        blocks=blocks,
        metadata=dict(metadata or {}),
    )
