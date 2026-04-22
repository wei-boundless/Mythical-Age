from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from document_conversion import DoclingConverter, discover_source_files
from normalized_ingestion import NormalizedDocumentBuilder, build_indexable_units
from pdf_analysis.parser import PdfSegment
from RAG.collections import CollectionConfig


class StubPdfParser:
    def extract_segments(self, _path: Path) -> list[PdfSegment]:
        return [
            PdfSegment(
                text="Executive summary about AI governance and operational risk.",
                page=1,
                section="Summary",
                modality="text",
                metadata={"parser": "mineru_api"},
            ),
            PdfSegment(
                text="Risk | Action\nCompliance | Add policy guardrails",
                page=2,
                section="Table",
                modality="table",
                metadata={"parser": "mineru_api"},
            ),
        ]

    def looks_unusable_text(self, text: str) -> bool:
        return not bool(text.strip())


def test_discover_source_files_respects_extensions_and_roots(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "a.md").write_text("alpha", encoding="utf-8")
    (knowledge_dir / "b.txt").write_text("beta", encoding="utf-8")
    (knowledge_dir / "c.exe").write_text("ignored", encoding="utf-8")

    config = CollectionConfig(
        name="knowledge",
        source_dirs=(knowledge_dir,),
        storage_dir=backend_dir / "storage" / "indexes" / "knowledge",
        description="test",
        allowed_roots=(knowledge_dir,),
        file_extensions=(".md", ".txt"),
    )

    records = discover_source_files(config, backend_dir=backend_dir)

    assert [item.source_path for item in records] == ["knowledge/a.md", "knowledge/b.txt"]


def test_docling_converter_uses_legacy_parser_fallback_and_builds_units(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    sample = knowledge_dir / "sample.md"
    sample.write_text("# Title\n\nParagraph one.\n\nParagraph two.", encoding="utf-8")

    converter = DoclingConverter(enabled=False)
    record = discover_source_files(
        CollectionConfig(
            name="knowledge",
            source_dirs=(knowledge_dir,),
            storage_dir=backend_dir / "storage" / "indexes" / "knowledge",
            description="test",
            allowed_roots=(knowledge_dir,),
            file_extensions=(".md",),
        ),
        backend_dir=backend_dir,
    )[0]

    result = converter.convert(record)
    builder = NormalizedDocumentBuilder()
    document, blocks, object_refs = builder.build(result)
    units = build_indexable_units(document, blocks, object_refs)

    assert result.parser_backend == "legacy_fallback"
    assert result.blocks
    assert any(block.block_type in {"paragraph", "section_block"} for block in blocks)
    assert any(unit.unit_type == "content_block" for unit in units)


def test_docling_converter_uses_pdf_parser_fallback_for_pdfs(tmp_path: Path) -> None:
    backend_dir = tmp_path / "backend"
    knowledge_dir = backend_dir / "knowledge"
    knowledge_dir.mkdir(parents=True)
    sample = knowledge_dir / "report.pdf"
    sample.write_bytes(b"%PDF-1.4\n% stub pdf\n")

    converter = DoclingConverter(enabled=False, pdf_parser=StubPdfParser())
    record = discover_source_files(
        CollectionConfig(
            name="knowledge",
            source_dirs=(knowledge_dir,),
            storage_dir=backend_dir / "storage" / "indexes" / "knowledge",
            description="test",
            allowed_roots=(knowledge_dir,),
            file_extensions=(".pdf",),
        ),
        backend_dir=backend_dir,
    )[0]

    result = converter.convert(record)
    builder = NormalizedDocumentBuilder()
    document, blocks, object_refs = builder.build(result)
    units = build_indexable_units(document, blocks, object_refs)

    assert result.parser_backend == "mineru_pdf"
    assert result.page_count == 2
    assert any(block.block_type == "section_block" for block in blocks)
    assert any(block.block_type == "table" for block in blocks)
    assert any(unit.unit_type == "content_block" for unit in units)
