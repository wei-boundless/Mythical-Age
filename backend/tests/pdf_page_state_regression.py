from __future__ import annotations

from pathlib import Path

from capability_system.units.mcp.local.pdf.agent.models import PDFReadRequest
from capability_system.units.mcp.local.pdf.agent.runtime import PDFReadAgentRuntime
from capability_system.units.mcp.local.pdf.analysis.parser import PdfPageSnapshot, PdfSegment
from evidence.pdf_worker import _degraded_pdf_answer


class _FakePageAwareParser:
    def extract_pages(self, _file_path: Path):
        return [
            (1, "封面"),
            (3, "回归现实主义\n2025年AI治理报告"),
        ]

    def extract_segments(self, _file_path: Path):
        return [
            PdfSegment(text="封面", page=1, modality="text", metadata={"parser": "fake"}),
            PdfSegment(text="回归现实主义", page=3, modality="text", element_type="section_heading", metadata={"parser": "fake"}),
            PdfSegment(text="2025年AI治理报告", page=3, modality="text", element_type="section_heading", metadata={"parser": "fake"}),
        ]

    def extract_page_snapshots(self, _file_path: Path):
        return [
            PdfPageSnapshot(page_number=1, raw_text="封面", text_block_count=1, has_text=True, has_usable_text=False, likely_page_state="cover_or_copyright", state_confidence=0.8),
            PdfPageSnapshot(page_number=2, raw_text="", text_block_count=0, has_text=False, has_usable_text=False, likely_page_state="page_structure_missing", state_confidence=0.95),
            PdfPageSnapshot(page_number=3, raw_text="回归现实主义\n2025年AI治理报告", text_block_count=2, has_text=True, has_usable_text=False, likely_page_state="transition_title_only", state_confidence=0.9),
            PdfPageSnapshot(page_number=4, raw_text="", text_block_count=0, has_text=False, has_usable_text=False, likely_page_state="page_structure_missing", state_confidence=0.95),
        ]

    def document_total_pages(self, _file_path: Path) -> int:
        return 4

    def looks_unusable_text(self, text: str) -> bool:
        return "隠㚵" in text


def test_pdf_runtime_marks_transition_title_page() -> None:
    runtime = PDFReadAgentRuntime(root_dir=Path("."), parser=_FakePageAwareParser())

    result = runtime.run(
        request=PDFReadRequest(query="请读取第3页", mode="page"),
        file_path=Path("fake.pdf"),
    )

    assert result.status == "degraded"
    assert result.degraded_reason == "target_page_transition_title_only"
    assert result.metadata["target_page_state"] == "transition_title_only"


def test_pdf_runtime_marks_structure_missing_page() -> None:
    runtime = PDFReadAgentRuntime(root_dir=Path("."), parser=_FakePageAwareParser())

    result = runtime.run(
        request=PDFReadRequest(query="请读取第4页", mode="page"),
        file_path=Path("fake.pdf"),
    )

    assert result.status == "degraded"
    assert result.degraded_reason == "target_page_structure_missing"
    assert result.metadata["target_page_state"] == "page_structure_missing"


def test_pdf_degraded_answer_distinguishes_transition_and_structure_missing() -> None:
    runtime = PDFReadAgentRuntime(root_dir=Path("."), parser=_FakePageAwareParser())
    transition = runtime.run(
        request=PDFReadRequest(query="请读取第3页", mode="page"),
        file_path=Path("fake.pdf"),
    )
    structure_missing = runtime.run(
        request=PDFReadRequest(query="请读取第4页", mode="page"),
        file_path=Path("fake.pdf"),
    )

    transition_answer = _degraded_pdf_answer(transition)
    missing_answer = _degraded_pdf_answer(structure_missing)

    assert "标题过渡页" in transition_answer
    assert "结构化结果缺失" in missing_answer
