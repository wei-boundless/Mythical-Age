from __future__ import annotations

from pathlib import Path

from prompting import (
    build_static_prompt_with_cache_report,
    build_system_prompt_with_manifest,
    reset_prompt_caches,
)
from prompting.builder import SYSTEM_PROMPT_ASSEMBLY_ORDER
from prompting.long_term_context import LongTermContextBundle


def test_static_prompt_cache_reuses_byte_stable_prefix(tmp_path: Path) -> None:
    reset_prompt_caches()
    bundle = LongTermContextBundle(
        static_sections=[("稳定原则", "你是一名可靠的执行代理。")],
        memory_block="动态记忆不应进入静态前缀缓存。",
    )

    first_prompt, first_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=False,
        long_term_context_bundle=bundle,
    )
    second_prompt, second_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=False,
        long_term_context_bundle=bundle,
    )

    assert first_prompt == second_prompt
    assert first_cache.status == "miss"
    assert second_cache.status == "hit"
    assert second_cache.key == first_cache.key
    assert "动态记忆不应进入静态前缀缓存" not in second_prompt


def test_static_prompt_cache_invalidates_when_rag_mode_changes(tmp_path: Path) -> None:
    reset_prompt_caches()
    bundle = LongTermContextBundle(
        static_sections=[("稳定原则", "你会优先使用可靠证据。")],
        memory_block="",
    )

    _prompt, first_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=False,
        long_term_context_bundle=bundle,
    )
    rag_prompt, rag_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=True,
        long_term_context_bundle=bundle,
    )

    assert first_cache.status == "miss"
    assert rag_cache.status == "miss"
    assert rag_cache.key != first_cache.key
    assert "当检索证据可用时" in rag_prompt


def test_static_prompt_cache_invalidates_when_static_source_changes(tmp_path: Path) -> None:
    reset_prompt_caches()
    first_bundle = LongTermContextBundle(
        static_sections=[("稳定原则", "版本 A。")],
        memory_block="",
    )
    second_bundle = LongTermContextBundle(
        static_sections=[("稳定原则", "版本 B。")],
        memory_block="",
    )

    first_prompt, first_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=False,
        long_term_context_bundle=first_bundle,
    )
    second_prompt, second_cache = build_static_prompt_with_cache_report(
        tmp_path,
        rag_mode=False,
        long_term_context_bundle=second_bundle,
    )

    assert first_prompt != second_prompt
    assert first_cache.status == "miss"
    assert second_cache.status == "miss"
    assert second_cache.key != first_cache.key
    assert "版本 B" in second_prompt


def test_system_prompt_keeps_static_prefix_first_and_marks_dynamic_sections_uncached(tmp_path: Path) -> None:
    reset_prompt_caches()
    bundle = LongTermContextBundle(
        static_sections=[("稳定原则", "静态前缀必须位于 prompt 开头。")],
        memory_block="",
    )

    prompt, manifest = build_system_prompt_with_manifest(
        tmp_path,
        rag_mode=False,
        persistent_memory="本轮相关事实，只能在 turn 层出现。",
        session_memory="当前会话状态，只能在 session 层出现。",
        long_term_context_bundle=bundle,
        session_id="session:test",
        turn_id="turn:test",
    )
    payload = manifest.to_dict()

    assert SYSTEM_PROMPT_ASSEMBLY_ORDER == ("static_prompt", "session_prompt", "turn_prompt")
    assert prompt.index("静态前缀必须位于 prompt 开头") < prompt.index("当前会话状态")
    assert prompt.index("当前会话状态") < prompt.index("本轮相关事实")

    sections = {section["id"]: section for section in payload["sections"]}
    assert sections["static_context_1"]["cache"]["scope"] == "static_prompt"
    assert sections["static_context_1"]["cache"]["status"] == "miss"
    assert sections["session_context"]["cache"]["status"] == "bypassed"
    assert sections["turn_relevant_memory"]["cache"]["status"] == "bypassed"
