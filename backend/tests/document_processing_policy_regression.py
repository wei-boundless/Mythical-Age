from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from capability_system.units.mcp.local.pdf.analysis.parser import PdfPageSnapshot, PdfSegment
from capability_system.units.mcp.local.retrieval.parser_adapter import MultimodalParserAdapter
from knowledge_system.conversion.docling_converter import DoclingConverter
from knowledge_system.conversion.models import ConversionBlock, ConversionResult, SourceFileRecord
from knowledge_system.ingestion import NormalizedDocumentBuilder, build_indexable_units
from knowledge_system.ingestion.policy import ChunkingPolicy


class _FakePdfParser:
    def extract_page_snapshots(self, path: Path):
        return [
            PdfPageSnapshot(page_number=1, raw_text="第一页证据", text_block_count=1, has_text=True, has_usable_text=True, likely_page_state="body_content", state_confidence=0.9),
            PdfPageSnapshot(page_number=2, raw_text="第二页证据", text_block_count=1, has_text=True, has_usable_text=True, likely_page_state="body_content", state_confidence=0.9),
        ]

    def extract_segments(self, path: Path):
        return [
            PdfSegment(text="第一页证据", page=1, modality="text", section="开头", metadata={"parser": "fake_pdf"}),
            PdfSegment(text="第二页证据", page=2, modality="text", section="结论", metadata={"parser": "fake_pdf"}),
        ]

    def looks_unusable_text(self, text: str) -> bool:
        return False


class _BadPdfParser(_FakePdfParser):
    def extract_page_snapshots(self, path: Path):
        return [
            PdfPageSnapshot(
                page_number=1,
                raw_text="隠㚵蔠裮䅳熱閔",
                text_block_count=1,
                has_text=True,
                has_usable_text=False,
                likely_page_state="text_corrupted",
                state_confidence=0.9,
            )
        ]

    def extract_segments(self, path: Path):
        return [
            PdfSegment(
                text="隠㚵蔠裮䅳熱閔",
                page=1,
                modality="text",
                metadata={"parser": "bad_pdf"},
            )
        ]

    def looks_unusable_text(self, text: str) -> bool:
        return True


def _record(path: Path, *, collection: str = "knowledge") -> SourceFileRecord:
    return SourceFileRecord.from_path(path, collection=collection, root_dir=path.parent)


def test_pdf_conversion_prefers_page_aware_parser(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    converter = DoclingConverter(enabled=False, pdf_parser=_FakePdfParser())

    result = converter.convert(_record(pdf_path))

    assert result.parser_backend == "mineru_pdf"
    assert result.parser_route == ("mineru_pdf",)
    assert result.metadata["page_aware"] is True
    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.pages[0].page_state == "body_content"
    assert [block.page for block in result.blocks] == [1, 2]


def test_pdf_conversion_rejects_unusable_page_aware_result_and_falls_back(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    converter = DoclingConverter(enabled=False, pdf_parser=_BadPdfParser(), repo_root=tmp_path)
    record = _record(pdf_path)
    fallback_result = replace(
        ConversionResult.empty(
            record,
            parser_backend="local_fallback",
            quality_flags=("fallback_parser",),
            metadata={"fallback_used": True},
        ),
        blocks=(
            ConversionBlock(
                block_id=f"{record.version_digest}:fallback:0",
                block_type="paragraph",
                text="这是 fallback 提取出的稳定正文。",
                metadata={"parser": "fallback_stub"},
            ),
        ),
    )

    converter._convert_with_fallback = lambda _record: fallback_result  # type: ignore[method-assign]

    result = converter.convert(record)

    assert result.parser_backend == "local_fallback"
    assert result.blocks[0].text == "这是 fallback 提取出的稳定正文。"


def test_csv_parser_emits_table_row_windows(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    csv_path = backend_root / "orders.csv"
    rows = "\n".join(f"{index},name-{index}" for index in range(1, 13))
    csv_path.write_text(f"id,name\n{rows}\n", encoding="utf-8")
    adapter = MultimodalParserAdapter(repo_root=tmp_path, max_xlsx_rows_per_chunk=2)

    chunks = adapter.parse_file(csv_path)

    assert len(chunks) == 3
    assert all(chunk.modality == "table" for chunk in chunks)
    assert all(chunk.metadata["unit_view"] == "table_row_window" for chunk in chunks)
    assert chunks[0].metadata["row_start"] == 1
    assert chunks[-1].metadata["row_end"] == 12


def test_table_row_window_survives_normalized_ingestion(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    csv_path = backend_root / "orders.csv"
    csv_path.write_text("id,name\n1,alpha\n2,beta\n3,gamma\n", encoding="utf-8")
    record = SourceFileRecord.from_path(csv_path, collection="knowledge", root_dir=backend_root)
    converter = DoclingConverter(enabled=False, repo_root=tmp_path)
    result = converter.convert(record)
    document, blocks, object_refs = NormalizedDocumentBuilder().build(result)

    units = build_indexable_units(
        document,
        blocks,
        object_refs,
        chunking_policy=ChunkingPolicy(target_tokens=64, soft_max_tokens=96, hard_max_tokens=128, overlap_tokens=0),
    )

    table_units = [unit for unit in units if unit.unit_type == "table_row_window"]
    assert table_units
    assert table_units[0].metadata["unit_view"] == "table_row_window"
    assert table_units[0].metadata["row_start"] == 1


