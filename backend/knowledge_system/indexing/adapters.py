from __future__ import annotations

from capability_system.units.mcp.local.retrieval.models import RetrievalHit
from knowledge_system.ingestion.models import IndexableUnit


def to_retrieval_hit(
    unit: IndexableUnit,
    *,
    score: float,
    retrieval_modes: tuple[str, ...] = (),
    parser_backend: str = "",
) -> RetrievalHit:
    metadata = {
        **dict(unit.metadata),
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "collection": unit.collection,
        "doc_id": unit.doc_id,
        "source_path": unit.source_path,
        "modality": unit.modality,
    }
    if unit.block_id is not None:
        metadata["block_id"] = unit.block_id
    if unit.object_ref_id is not None:
        metadata["object_ref_id"] = unit.object_ref_id
    if unit.page is not None:
        metadata["page"] = unit.page
    if unit.block_type is not None:
        metadata["block_type"] = unit.block_type
    if unit.section_path:
        metadata["section_path"] = list(unit.section_path)
    if unit.quality_flags:
        metadata["quality_flags"] = list(unit.quality_flags)
    return RetrievalHit(
        text=unit.text,
        source=unit.source_path,
        modality=unit.modality,
        score=float(score),
        page=unit.page,
        metadata=metadata,
        hit_id=unit.unit_id,
        doc_id=unit.doc_id,
        block_id=unit.block_id,
        object_ref_id=unit.object_ref_id,
        block_type=unit.block_type,
        section_path=unit.section_path,
        score_breakdown={"final": float(score)},
        retrieval_modes=retrieval_modes,
        parser_backend=parser_backend,
        quality_flags=unit.quality_flags,
    )


