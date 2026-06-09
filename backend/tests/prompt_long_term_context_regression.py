from __future__ import annotations

from memory_system.layout import durable_memory_layout_from_backend_dir
from prompting.builder import build_turn_prompt
from prompting.long_term_context import _strip_leading_markdown_title, build_long_term_context_bundle


def test_strip_leading_markdown_title_keeps_section_heading() -> None:
    content = "## 执行优先级\n\n- 项目规范优先。"

    assert _strip_leading_markdown_title(content).startswith("## 执行优先级")


def test_strip_leading_markdown_title_removes_document_title() -> None:
    content = "# PROJECT_GUIDE.md\n\n## 执行边界\n\n- 项目规范优先。"

    assert _strip_leading_markdown_title(content).startswith("## 执行边界")


def test_long_term_context_does_not_default_to_durable_memory_index(tmp_path) -> None:
    backend_dir = tmp_path / "backend"
    layout = durable_memory_layout_from_backend_dir(backend_dir)
    layout.ensure_dirs()
    layout.index_path.write_text("# Memory Index\n\n- 不应默认进入 prompt。\n", encoding="utf-8")

    bundle = build_long_term_context_bundle(backend_dir)

    assert bundle.memory_block == ""
    assert "不应默认进入 prompt" not in build_turn_prompt(long_term_context_bundle=bundle)


def test_turn_prompt_uses_only_explicit_persistent_memory() -> None:
    prompt = build_turn_prompt(persistent_memory="只允许显式传入的本轮相关记忆。")



