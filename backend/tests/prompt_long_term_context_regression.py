from __future__ import annotations

from prompting.long_term_context import _strip_leading_markdown_title


def test_strip_leading_markdown_title_keeps_section_heading() -> None:
    content = "## 执行优先级\n\n- 共同契约优先。"

    assert _strip_leading_markdown_title(content).startswith("## 执行优先级")


def test_strip_leading_markdown_title_removes_document_title() -> None:
    content = "# Soul Seed\n\n## 身份锚点\n\n- 你是河伯。"

    assert _strip_leading_markdown_title(content).startswith("## 身份锚点")
