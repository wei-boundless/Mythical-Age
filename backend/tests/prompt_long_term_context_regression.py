from __future__ import annotations

from prompting.long_term_context import _strip_leading_markdown_title


def test_strip_leading_markdown_title_keeps_section_heading() -> None:
    content = "## 执行优先级\n\n- 项目规范优先。"

    assert _strip_leading_markdown_title(content).startswith("## 执行优先级")


def test_strip_leading_markdown_title_removes_document_title() -> None:
    content = "# PROJECT_GUIDE.md\n\n## 执行边界\n\n- 项目规范优先。"

    assert _strip_leading_markdown_title(content).startswith("## 执行边界")


