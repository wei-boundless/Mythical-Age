from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from document_conversion.models import ConversionBlock, ConversionResult
from normalized_ingestion import NormalizedDocumentBuilder, build_cleaning_manifest, build_indexable_units


def test_cleaning_pipeline_drops_placeholders_and_projects_object_blocks() -> None:
    conversion = ConversionResult(
        doc_id="doc-1",
        collection="knowledge",
        source_path="knowledge/sample.pdf",
        source_type="pdf",
        version_digest="digest-1",
        parser_backend="docling",
        blocks=(
            ConversionBlock(block_id="b1", block_type="paragraph", text="<!-- image -->", page=1),
            ConversionBlock(block_id="b2", block_type="heading", text="第一章", page=1),
            ConversionBlock(block_id="b3", block_type="paragraph", text="AI 治理里最常见的风险包括合规、误用和安全。", page=1),
            ConversionBlock(block_id="b4", block_type="paragraph", text="管理层通常最关心责任边界、业务损失和监管暴露。", page=1),
            ConversionBlock(block_id="b5", block_type="figure", text="风险分类总览图", page=1),
        ),
    )

    builder = NormalizedDocumentBuilder()
    document, blocks, object_refs = builder.build(conversion)
    units = build_indexable_units(document, blocks, object_refs)
    manifest = build_cleaning_manifest(blocks)

    dropped_blocks = {block.block_id for block in blocks if block.eligibility == "drop"}
    content_units = [unit for unit in units if unit.unit_type == "content_block"]
    object_units = [unit for unit in units if unit.unit_type == "object_block"]
    summary_units = [unit for unit in units if unit.unit_type == "page_summary"]

    assert dropped_blocks == {"b1", "b2"}
    assert [unit.block_id for unit in content_units] == ["b3", "b4"]
    assert any(unit.block_id == "b5" for unit in object_units)
    assert summary_units
    assert "<!-- image -->" not in summary_units[0].text
    assert "第一章" not in summary_units[0].text
    assert manifest["eligible_block_count"] == 3
    assert manifest["dropped_block_count"] == 2
    assert manifest["drop_reason_counts"]["placeholder_block"] == 1
    assert manifest["drop_reason_counts"]["decorative_heading"] == 1
