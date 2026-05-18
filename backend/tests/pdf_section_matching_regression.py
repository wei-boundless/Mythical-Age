from __future__ import annotations

from capability_system.units.mcp.local.pdf.agent.models import PDFPreparedDocument, PDFPreparedPage
from capability_system.units.mcp.local.pdf.agent.runtime import PDFReadAgentRuntime


def _page(page_number: int, text: str) -> PDFPreparedPage:
    return PDFPreparedPage(
        page_number=page_number,
        text=text,
        body_text=text,
        page_state="body_content",
        quality_score=0.9,
        page_has_text=True,
        dominant_element_type="body_text",
        excluded_ratio=0.0,
        body_chars=len(text),
        usable=True,
    )


def test_section_matcher_falls_back_to_implicit_anchor_ordinal() -> None:
    runtime = PDFReadAgentRuntime()
    prepared = PDFPreparedDocument(
        source="demo.pdf",
        total_pages=60,
        pages=[
            _page(25, "数据既是 AI 运行的基础原料，也是治理体系中的关键支点之一。问题主要为数据从何而来。"),
            _page(27, "围绕数据供给与使用边界，报告进一步展开。"),
            _page(35, "模型作为 AI 的关键底座，其争议主要为治理支点是否应当直接指向模型本身。"),
            _page(38, "围绕模型的技术特性，报告继续讨论可操作的制度抓手。"),
            _page(48, "与模型、数据等要素治理相比，AI应用治理的难点在于强情境性与逐层外溢。"),
            _page(50, "应用风险还会延伸到 Agent 与具身智能场景。"),
        ],
        readable_pages=6,
        usable_pages=6,
    )

    pages = runtime._match_section_pages(prepared=prepared, target_section="第二部分")

    assert [page.page_number for page in pages] == [35, 38]


def test_section_matcher_falls_back_to_implicit_anchor_topic() -> None:
    runtime = PDFReadAgentRuntime()
    prepared = PDFPreparedDocument(
        source="demo.pdf",
        total_pages=60,
        pages=[
            _page(25, "数据既是 AI 运行的基础原料，也是治理体系中的关键支点之一。"),
            _page(35, "模型作为 AI 的关键底座，其争议主要为治理支点是否应当直接指向模型本身。"),
            _page(48, "与模型、数据等要素治理相比，AI应用治理的难点在于强情境性。"),
        ],
        readable_pages=3,
        usable_pages=3,
    )

    pages = runtime._match_section_pages(prepared=prepared, target_section="模型")

    assert [page.page_number for page in pages] == [35]
