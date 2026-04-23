from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from RAG.parser_adapter import MultimodalParserAdapter
from pdf_agent import PDFReadAgentRuntime, PDFReadRequest
from pdf_analysis.mineru_client import MinerUApiClient, MinerUApiConfig, MinerUBlock, MinerUParseResult
from pdf_analysis.parser import PdfTextParser
from tools import get_all_tools


class StubMinerUClient(MinerUApiClient):
    def __init__(self, result: MinerUParseResult) -> None:
        super().__init__(
            MinerUApiConfig(
                enabled=True,
                base_url="http://127.0.0.1:8000",
                parse_path="/file_parse",
                api_key=None,
                timeout_seconds=30,
            )
        )
        self._result = result

    def parse_pdf(self, file_path: Path) -> MinerUParseResult:
        return self._result


class FailingMinerUClient(MinerUApiClient):
    def __init__(self) -> None:
        super().__init__(
            MinerUApiConfig(
                enabled=True,
                base_url="http://127.0.0.1:8000",
                parse_path="/file_parse",
                api_key=None,
                timeout_seconds=30,
            )
        )

    def parse_pdf(self, file_path: Path) -> MinerUParseResult:
        raise RuntimeError("simulated remote failure")


def _write_dummy_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% stub pdf for regression\n")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        backend_root = repo_root / "backend"
        pdf_path = backend_root / "knowledge" / "report.pdf"
        _write_dummy_pdf(pdf_path)

        result = MinerUParseResult(
            pages=[
                (1, "Executive summary page about supply chain risk."),
                (2, "Revenue table on page 2 with margin pressure details."),
            ],
            blocks=[
                MinerUBlock(
                    text="Executive summary page about supply chain risk.",
                    page=1,
                    kind="text",
                    section="Summary",
                    metadata={"parser": "mineru_api"},
                ),
                MinerUBlock(
                    text="Revenue | Margin\n2025Q1 | 18%",
                    page=2,
                    kind="table",
                    section="Financial Table",
                    metadata={"parser": "mineru_api"},
                ),
            ],
        )

        parser = PdfTextParser(root_dir=backend_root, mineru_client=StubMinerUClient(result))
        adapter = MultimodalParserAdapter(repo_root=repo_root)
        adapter._pdf_parser = parser

        chunks = adapter.parse_file(pdf_path)
        assert len(chunks) == 2
        assert chunks[0].page == 1
        assert chunks[0].section == "Summary"
        assert chunks[0].metadata["parser"] == "mineru_api"
        assert chunks[1].modality == "table"
        assert chunks[1].page == 2
        assert "Revenue" in chunks[1].text

        runtime = PDFReadAgentRuntime(root_dir=backend_root, parser=parser)
        result = runtime.run(
            request=PDFReadRequest(
                query="Please explain page 2 of the report.",
                mode="page",
            ),
            file_path=pdf_path,
        )
        assert result.effective_mode == "page"
        assert result.pages == [2]
        assert "Revenue table" in result.summary or "Revenue | Margin" in result.summary

        fallback_parser = PdfTextParser(root_dir=backend_root, mineru_client=FailingMinerUClient())
        fallback_parser._extract_pages_locally = lambda file_path: [(1, "Local fallback page content.")]
        fallback_pages = fallback_parser.extract_pages(pdf_path)
        assert fallback_pages == [(1, "Local fallback page content.")]

        tool_names = {tool.name for tool in get_all_tools(backend_root)}
        assert "pdf_analysis" in tool_names

    print("ALL PASSED (pdf mineru integration regression)")


if __name__ == "__main__":
    main()
