from __future__ import annotations

from RAG.models import RetrievalHit
from normalized_ingestion.models import IndexableUnit


def to_retrieval_hit(
    unit: IndexableUnit,
    *,
    score: float,
    retrieval_modes: tuple[str, ...] = (),
    parser_backend: str = "",
) -> RetrievalHit:
    return RetrievalHit(
        text=unit.text,
        source=unit.source_path,
        modality=unit.modality,
        score=float(score),
        page=unit.page,
        metadata=dict(unit.metadata),
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
