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
    parent_units = [unit for unit in units if unit.unit_type == "parent_section"]
    document_units = [unit for unit in units if unit.unit_type == "document_summary"]

    assert dropped_blocks == {"b1", "b2"}
    assert len(content_units) == 1
    assert content_units[0].metadata["block_ids"] == ["b3", "b4"]
    assert content_units[0].node_kind == "leaf"
    assert content_units[0].parent_unit_id
    assert any(unit.block_id == "b5" for unit in object_units)
    assert parent_units
    assert document_units
    assert summary_units
    assert "<!-- image -->" not in summary_units[0].text
    assert "第一章" not in summary_units[0].text
    assert all(block.parser_backend == "docling" for block in blocks)
    assert all(block.source_type == "pdf" for block in blocks)
    assert content_units[0].metadata["parser_backend"] == "docling"
    assert content_units[0].metadata["source_type"] == "pdf"
    assert content_units[0].metadata["structure_contract_version"] == document.structure_contract_version
    assert manifest["eligible_block_count"] == 3
    assert manifest["dropped_block_count"] == 2
    assert manifest["drop_reason_counts"]["placeholder_block"] == 1
    assert manifest["drop_reason_counts"]["decorative_heading"] == 1


def test_dynamic_chunking_splits_long_block_and_emits_hierarchy_units() -> None:
    long_text = " ".join(
        [
            "This section explains retrieval quality, document structure, dense recall, sparse recall, reranking, and grounding."
            for _ in range(30)
        ]
    )
    conversion = ConversionResult(
        doc_id="doc-2",
        collection="knowledge",
        source_path="knowledge/sample.md",
        source_type="md",
        version_digest="digest-2",
        parser_backend="docling",
        blocks=(
            ConversionBlock(block_id="h1", block_type="heading", text="# Retrieval Design", section_label="Retrieval Design", section_path=("Retrieval Design",)),
            ConversionBlock(block_id="p1", block_type="paragraph", text=long_text, section_label="Retrieval Design", section_path=("Retrieval Design",)),
        ),
    )

    builder = NormalizedDocumentBuilder()
    document, blocks, object_refs = builder.build(conversion)
    units = build_indexable_units(document, blocks, object_refs)

    content_units = [unit for unit in units if unit.unit_type == "content_block"]
    parent_units = [unit for unit in units if unit.unit_type == "parent_section"]
    document_units = [unit for unit in units if unit.unit_type == "document_summary"]

    assert len(content_units) >= 2
    assert all(unit.node_kind == "leaf" for unit in content_units)
    assert parent_units
    assert document_units
    assert all(unit.parent_unit_id == parent_units[0].unit_id for unit in content_units)
