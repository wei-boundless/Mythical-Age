from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdf_agent import PDFCanonicalResult, PDFReadAgentRuntime, PDFReadRequest
from pdf_analysis.parser import PdfSegment
from query.output_classifier import classify_output_candidate
from tools.pdf_analysis_tool import PdfAnalysisTool


class _FakeParser:
    def __init__(
        self,
        *,
        pages: list[tuple[int, str]],
        segments: list[PdfSegment] | None = None,
    ) -> None:
        self._pages = pages
        self._segments = list(segments or [])

    def extract_pages(self, _file_path: Path) -> list[tuple[int, str]]:
        return list(self._pages)

    def extract_segments(self, _file_path: Path) -> list[PdfSegment]:
        return list(self._segments)

    def document_total_pages(self, _file_path: Path) -> int:
        observed_pages = [int(page) for page, _text in self._pages if int(page) > 0]
        observed_segments = [int(segment.page) for segment in self._segments if int(segment.page or 0) > 0]
        return max([*observed_pages, *observed_segments], default=0)

    def looks_unusable_text(self, text: str) -> bool:
        normalized = str(text or "").strip()
        return len(normalized) < 20


class _StubRuntime:
    def __init__(self, result: PDFCanonicalResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run(self, *, request: PDFReadRequest, file_path: Path) -> PDFCanonicalResult:
        self.calls.append(
            {
                "query": request.query,
                "mode": request.mode,
                "max_chunks": request.max_chunks,
                "file_path": str(file_path),
            }
        )
        return self.result


def test_pdf_agent_runtime_routes_overview_query_to_document_scope() -> None:
    parser = _FakeParser(
        pages=[
            (1, "封面。"),
            (2, "第一部分 行业背景。本报告讨论 AI 治理框架、责任边界与风险控制。"),
            (3, "第二部分 核心结论。报告建议先建立规则，再补充审计，再明确责任归口。"),
        ],
        segments=[
            PdfSegment(text="第一部分 行业背景", page=2, section="第一部分 行业背景"),
            PdfSegment(text="第二部分 核心结论", page=3, section="第二部分 核心结论"),
        ],
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="现在打开这份 PDF，给我一个全文总览。",
            mode="document",
            max_chunks=4,
        ),
        file_path=ROOT / "knowledge" / "test.pdf",
    )

    assert result.ok
    assert result.effective_mode == "document"
    assert result.metadata["route_reason"] == "overview_hint"
    assert any(page in result.pages for page in [2, 3])
    assert "文档要点" in result.summary


def test_pdf_agent_runtime_routes_section_query_to_section_scope() -> None:
    parser = _FakeParser(
        pages=[
            (1, "第一部分 背景介绍。本页主要说明背景。"),
            (2, "第二部分 约束条件。本部分强调权限边界、审计要求和执行约束。"),
            (3, "第二部分 约束条件。继续说明责任归口与例外流程。"),
        ],
        segments=[
            PdfSegment(text="第一部分 背景介绍", page=1, section="第一部分 背景介绍"),
            PdfSegment(text="第二部分 约束条件", page=2, section="第二部分 约束条件"),
            PdfSegment(text="第二部分 约束条件", page=3, section="第二部分 约束条件"),
        ],
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="回到刚才 PDF，第二部分强调的约束是什么？",
            mode="document",
            max_chunks=4,
        ),
        file_path=ROOT / "knowledge" / "test.pdf",
    )

    assert result.ok
    assert result.effective_mode == "section"
    assert result.metadata["target_section"].startswith("第")
    assert result.pages[:2] == [2, 3]
    assert "第二部分" in result.summary


def test_pdf_agent_runtime_quality_gate_suppresses_reference_pages() -> None:
    parser = _FakeParser(
        pages=[
            (1, "参考文献 References Smith 2024; Brown 2023; bibliography and references list."),
            (2, "核心结论。本报告指出 AI 治理应优先建立制度、流程和审计闭环。"),
            (3, "附录。"),
        ]
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="给我这份 PDF 的核心结论。",
            mode="document",
            max_chunks=3,
        ),
        file_path=ROOT / "knowledge" / "test.pdf",
    )

    assert result.ok
    assert result.pages
    assert result.pages[0] == 2
    assert 1 not in result.pages[:1]


def test_output_classifier_accepts_pdf_canonical_result() -> None:
    result = PDFCanonicalResult(
        status="ok",
        source="AI治理报告.pdf",
        requested_mode="document",
        effective_mode="document",
        summary="这是稳定摘要。",
        pages=[3, 5],
    )
    candidate = classify_output_candidate(
        text=result.to_tool_output(),
        route="tool",
        source="tool.pdf_analysis.output",
        tool_name="pdf_analysis",
        allow_unlabeled_answer=False,
    )

    assert candidate is not None
    assert candidate.channel == "tool_visible_summary"
    assert candidate.text == "这是稳定摘要。"
    assert candidate.metadata["pdf_pages"] == [3, 5]


def test_output_classifier_rejects_degraded_pdf_canonical_summary() -> None:
    result = PDFCanonicalResult(
        status="degraded",
        source="AI治理报告.pdf",
        requested_mode="page",
        effective_mode="page",
        degraded_reason="target_page_text_quality_low",
        pages=[7],
    )
    candidate = classify_output_candidate(
        text=result.to_tool_output(),
        route="tool",
        source="tool.pdf_analysis.output",
        tool_name="pdf_analysis",
        allow_unlabeled_answer=False,
    )

    assert candidate is not None
    assert candidate.channel == "tool_raw_output"
    assert candidate.metadata["pdf_status"] == "degraded"
    assert candidate.metadata["pdf_pages"] == [7]


def test_pdf_agent_runtime_uses_true_total_pages_for_blank_target_page() -> None:
    parser = _FakeParser(
        pages=[
            (1, "封面。"),
            (3, "第三页有稳定正文，说明本文件的主要背景和问题定义。"),
        ]
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="请阅读第2页",
            mode="page",
            max_chunks=2,
        ),
        file_path=ROOT / "knowledge" / "test.pdf",
    )

    assert result.status == "degraded"
    assert result.summary == ""
    assert result.error == ""
    assert result.degraded_reason == "target_page_has_no_stable_text"
    assert result.metadata["document_total_pages"] == 3


def test_pdf_analysis_tool_returns_canonical_protocol() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root_dir = Path(temp_dir)
        pdf_path = root_dir / "knowledge" / "demo.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")

        tool = PdfAnalysisTool(root_dir=root_dir)
        tool._runtime = _StubRuntime(
            PDFCanonicalResult(
                status="ok",
                source="demo.pdf",
                requested_mode="document",
                effective_mode="document",
                summary="结构化结果已生成。",
                pages=[2, 4],
            )
        )

        output = tool._run(
            query="打开 demo.pdf，给我一个全文总览。",
            path="knowledge/demo.pdf",
            mode="document",
            max_chunks=4,
        )

        parsed = PDFCanonicalResult.from_tool_output(output)
        assert parsed is not None
        assert parsed.summary == "结构化结果已生成。"
        assert parsed.pages == [2, 4]


def test_pdf_agent_runtime_cleans_dirty_body_text_before_stable_summary() -> None:
    parser = _FakeParser(
        pages=[
            (
                7,
                "2025 AI 杂芤 灭拇诈励 如果说前两年全球对AI的态度还夹杂着末日恐惧，那么2025年风向已彻底改变。",
            ),
            (
                13,
                "2025 幌唄 AI 杂芤 拼褒捧悼 从整体方向看，当前更多国家将产业发展置于优先位置。",
            ),
            (
                23,
                "AI 杂芤]醭髫櫪 唤纈=凌钨 Al治理主要面向三大领域：数据、模型与应用。",
            ),
        ]
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="打开这份 PDF，给我一个全文总览。",
            mode="document",
            max_chunks=4,
        ),
        file_path=ROOT / "knowledge" / "dirty.pdf",
    )

    assert result.ok
    assert "杂芤" not in result.summary
    assert "幌唄" not in result.summary
    assert "拼褒捧悼" not in result.summary
    assert "唤纈=凌钨" not in result.summary
    assert "2025 AI 如果说" not in result.summary
    assert "AI AI治理" not in result.summary
    assert "风向已彻底改变" in result.summary


def test_pdf_agent_runtime_degrades_when_cleaned_document_text_is_empty() -> None:
    parser = _FakeParser(
        pages=[
            (5, "杂芤 灭拇诈励 幌唄 拼褒捧悼"),
            (6, "AI 杂芤]醭髫櫪 唤纈=凌钨"),
        ]
    )
    runtime = PDFReadAgentRuntime(root_dir=ROOT, parser=parser)
    result = runtime.run(
        request=PDFReadRequest(
            query="打开这份 PDF，给我一个全文总览。",
            mode="document",
            max_chunks=4,
        ),
        file_path=ROOT / "knowledge" / "dirty-empty.pdf",
    )

    assert result.status == "degraded"
    assert result.summary == ""
    assert result.degraded_reason in {"no_stable_document_evidence", "document_summary_text_quality_low"}


def main() -> None:
    test_pdf_agent_runtime_routes_overview_query_to_document_scope()
    test_pdf_agent_runtime_routes_section_query_to_section_scope()
    test_pdf_agent_runtime_quality_gate_suppresses_reference_pages()
    test_output_classifier_accepts_pdf_canonical_result()
    test_output_classifier_rejects_degraded_pdf_canonical_summary()
    test_pdf_agent_runtime_uses_true_total_pages_for_blank_target_page()
    test_pdf_analysis_tool_returns_canonical_protocol()
    test_pdf_agent_runtime_cleans_dirty_body_text_before_stable_summary()
    test_pdf_agent_runtime_degrades_when_cleaned_document_text_is_empty()
    print("ALL PASSED (pdf agent runtime regression)")


if __name__ == "__main__":
    main()
