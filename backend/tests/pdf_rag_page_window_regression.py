from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.parser_adapter import MultimodalParserAdapter
from pdf_analysis.parser import PdfSegment


class StubPdfParser:
    def available(self) -> bool:
        return True

    def extract_segments(self, path: Path) -> list[PdfSegment]:
        return [
            PdfSegment(text="page 1 summary", page=1, metadata={"parser": "stub"}),
            PdfSegment(text="page 1 table", page=1, modality="table", metadata={"parser": "stub"}),
            PdfSegment(text="page 2 summary", page=2, metadata={"parser": "stub"}),
            PdfSegment(text="page 2 table", page=2, modality="table", metadata={"parser": "stub"}),
            PdfSegment(text="page 3 summary", page=3, metadata={"parser": "stub"}),
        ]


def main() -> None:
    backend = ROOT
    pdf = backend / "knowledge" / "stub.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n")

    adapter = MultimodalParserAdapter(repo_root=backend.parent, max_pdf_pages=2)
    adapter._pdf_parser = StubPdfParser()
    chunks = adapter.parse_file(pdf)

    assert len(chunks) == 4
    assert [chunk.page for chunk in chunks] == [1, 1, 2, 2]
    assert all(chunk.page in {1, 2} for chunk in chunks)

    print("ALL PASSED (pdf rag page window regression)")


if __name__ == "__main__":
    main()
