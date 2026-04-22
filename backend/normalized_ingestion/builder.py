from __future__ import annotations

import hashlib

from document_conversion.models import ConversionResult
from normalized_ingestion.eligibility import clean_block
from normalized_ingestion.models import NormalizedBlock, NormalizedDocument, NormalizedObjectRef

_OBJECT_BLOCK_TYPES = {"table", "figure", "sheet_region", "json_field_group"}


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


class NormalizedDocumentBuilder:
    def build(
        self,
        result: ConversionResult,
    ) -> tuple[NormalizedDocument, list[NormalizedBlock], list[NormalizedObjectRef]]:
        document = NormalizedDocument(
            doc_id=result.doc_id,
            source_path=result.source_path,
            source_type=result.source_type,
            collection=result.collection,
            version_digest=result.version_digest,
            title=result.title or result.source_path.rsplit("/", 1)[-1],
            language=result.language,
            page_count=result.page_count,
            structure_contract_version=result.structure_contract_version,
            parser_route=result.parser_route,
            fallback_used=result.fallback_used,
            parser_backend=result.parser_backend,
            quality_flags=result.quality_flags,
            metadata={
                **dict(result.metadata),
                "source_type": result.source_type,
                "source_path": result.source_path,
                "parser_route": list(result.parser_route),
                "fallback_used": result.fallback_used,
            },
        )
        blocks: list[NormalizedBlock] = []
        object_refs: list[NormalizedObjectRef] = []
        for block in result.blocks:
            object_ref_ids: list[str] = []
            if block.block_type in _OBJECT_BLOCK_TYPES:
                object_ref_id = _stable_id(result.doc_id, block.block_id, block.block_type)
                object_ref_ids.append(object_ref_id)
                object_refs.append(
                    NormalizedObjectRef(
                        object_ref_id=object_ref_id,
                        doc_id=result.doc_id,
                        object_type=block.block_type,
                        page=block.page,
                        section_path=block.section_path,
                        label=(block.text[:80].strip() or block.block_type),
                        anchor_block_ids=(block.block_id,),
                        metadata=dict(block.metadata),
                    )
                )
            raw_block = NormalizedBlock(
                block_id=block.block_id,
                doc_id=result.doc_id,
                block_type=block.block_type,
                text=block.text,
                normalized_text=_normalize_text(block.text),
                source_type=result.source_type,
                parser_backend=result.parser_backend,
                section_label=block.section_label or " > ".join(str(item) for item in block.section_path if str(item).strip()),
                structure_role=block.structure_role,
                quality_flags=result.quality_flags,
                page=block.page,
                section_path=block.section_path,
                reading_order=block.reading_order,
                modality=block.modality,
                bbox=block.bbox,
                object_ref_ids=tuple(object_ref_ids),
                metadata={
                    **dict(block.metadata),
                    "source_type": result.source_type,
                    "source_path": result.source_path,
                    "parser_backend": result.parser_backend,
                    "section_label": block.section_label,
                    "structure_role": block.structure_role,
                },
            )
            blocks.append(clean_block(raw_block))
        return document, blocks, object_refs
