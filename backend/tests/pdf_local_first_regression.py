from __future__ import annotations

from pathlib import Path

from capability_system.units.mcp.local.pdf.analysis.parser import PdfSegment, PdfTextParser


class _FailingMinerUClient:
    def available(self) -> bool:
        return True

    def parse_pdf(self, file_path: Path):  # pragma: no cover - defensive only
        raise AssertionError("remote MinerU path should not be used when local text is available")


def test_pdf_parser_prefers_local_text_over_remote_mineru(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    parser = PdfTextParser(
        root_dir=tmp_path,
        mineru_client=_FailingMinerUClient(),  # type: ignore[arg-type]
        ocr_reader=lambda _path, _page: "OCR fallback should not be used",
    )
    parser._extract_pages_with_pdfplumber = lambda _path: [(1, "这是稳定的 PDF 正文，包含模型治理和应用治理。")]  # type: ignore[method-assign]
    parser._extract_segments_with_pdfplumber = lambda _path: [  # type: ignore[method-assign]
        PdfSegment(
            text="这是稳定的 PDF 正文，包含模型治理和应用治理。",
            page=1,
            element_type="body_text",
            metadata={"parser": "pdfplumber_text"},
        )
    ]
    parser._load_remote_result = lambda _path: (_ for _ in ()).throw(AssertionError("remote MinerU should not be called"))  # type: ignore[method-assign]
    parser._count_pages_with_pdfplumber = lambda _path: 1  # type: ignore[method-assign]

    assert parser.extract_pages(pdf_path) == [(1, "这是稳定的 PDF 正文，包含模型治理和应用治理。")]
    assert parser.extract_segments(pdf_path)[0].metadata["parser"] == "pdfplumber_text"


def test_pdf_parser_uses_ocr_when_local_text_is_unusable(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    ocr_calls: list[int] = []

    def _ocr(_path: Path, page: int) -> str:
        ocr_calls.append(page)
        return "模型作为AI的关键底座，其争议主要为治理支点。"

    parser = PdfTextParser(
        root_dir=tmp_path,
        mineru_client=_FailingMinerUClient(),  # type: ignore[arg-type]
        ocr_reader=_ocr,
    )
    parser._extract_pages_with_pdfplumber = lambda _path: [(1, "隠㚵蔠裮䅳熱閔")]  # type: ignore[method-assign]
    parser._extract_segments_with_pdfplumber = lambda _path: [  # type: ignore[method-assign]
        PdfSegment(
            text="隠㚵蔠裮䅳熱閔",
            page=1,
            element_type="diagnostic_only",
            diagnostic_only=True,
            metadata={"parser": "pdfplumber_text", "quality_flags": ["unusable_text"]},
        )
    ]
    parser._count_pages_with_pdfplumber = lambda _path: 1  # type: ignore[method-assign]

    pages = parser.extract_pages(pdf_path)
    segments = parser.extract_segments(pdf_path)

    assert pages == [(1, "模型作为AI的关键底座，其争议主要为治理支点。")]
    assert len(segments) == 1
    assert segments[0].metadata["parser"] == "rapidocr_page"
    assert ocr_calls == [1]


def test_pdf_parser_chooses_better_local_page_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    parser = PdfTextParser(root_dir=tmp_path, mineru_client=_FailingMinerUClient())  # type: ignore[arg-type]
    parser._extract_pages_with_pdfplumber = lambda _path: [(1, "乱序\n文\n本\nA")]  # type: ignore[method-assign]
    parser._extract_pages_with_pypdf = lambda _path: [(1, "这是更完整的正文，包含模型治理和应用治理。")]  # type: ignore[method-assign]
    parser._extract_segments_with_pdfplumber = lambda _path: []  # type: ignore[method-assign]
    parser._count_pages_with_pdfplumber = lambda _path: 1  # type: ignore[method-assign]

    assert parser.extract_pages(pdf_path) == [(1, "这是更完整的正文，包含模型治理和应用治理。")]


