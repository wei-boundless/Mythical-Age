from __future__ import annotations

from normalized_ingestion.models import IndexableUnit
from normalized_ingestion.policy import ChunkingPolicy
from retrieval_core.bootstrap import build_index_quality_report, merge_index_quality_reports


def _unit(
    unit_id: str,
    *,
    unit_type: str = "content_block",
    text: str = "检索系统需要稳定证据",
    modality: str = "text",
    page: int | None = 1,
    metadata: dict | None = None,
    parent_unit_id: str | None = None,
) -> IndexableUnit:
    return IndexableUnit(
        unit_id=unit_id,
        unit_type=unit_type,
        collection="knowledge",
        doc_id="doc-1",
        source_path="sample.md",
        text=text,
        modality=modality,
        parent_unit_id=parent_unit_id,
        page=page,
        metadata=dict(metadata or {}),
    )


def test_index_quality_report_tracks_chunk_shape() -> None:
    policy = ChunkingPolicy(target_tokens=16, soft_max_tokens=24, hard_max_tokens=32, min_tokens=4, overlap_tokens=2)
    units = [
        _unit("u1", metadata={"token_count": 5}),
        _unit("u2", unit_type="table_row_window", modality="table", metadata={"token_count": 8}),
        _unit("u3", unit_type="page_summary", metadata={"token_count": 3}, page=None),
        _unit("u4", unit_type="parent_section", metadata={"token_count": 40, "child_unit_ids": ["u1", "u2"]}),
        _unit("u5", parent_unit_id="u4", metadata={"token_count": 6}),
    ]

    report = build_index_quality_report(units, chunking_policy=policy)

    assert report["chunk_count"] == 5
    assert report["table_row_window_count"] == 1
    assert report["table_unit_count"] == 1
    assert report["missing_page_count"] == 1
    assert report["overlong_chunk_count"] == 1
    assert report["tiny_chunk_count"] == 1
    assert report["parent_child_link_count"] == 3
    assert report["unit_type_counts"]["parent_section"] == 1


def test_index_quality_reports_merge_counts() -> None:
    policy = ChunkingPolicy()
    first = build_index_quality_report([_unit("u1", metadata={"token_count": 10})], chunking_policy=policy)
    second = build_index_quality_report(
        [_unit("u2", unit_type="table_row_window", modality="table", metadata={"token_count": 12})],
        chunking_policy=policy,
    )

    merged = merge_index_quality_reports(first, second)

    assert merged["chunk_count"] == 2
    assert merged["table_row_window_count"] == 1
    assert merged["unit_type_counts"]["content_block"] == 1
    assert merged["unit_type_counts"]["table_row_window"] == 1
