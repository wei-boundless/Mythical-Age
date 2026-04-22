from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade, format_memory_manifest, scan_memory_headers
from structured_memory import MemoryNote
from understanding.memory_intent import analyze_memory_intent


def _seed_notes(facade: MemoryFacade) -> None:
    facade.memory_manager.save_note(
        MemoryNote(
            slug="project-focus",
            title="项目当前重点是优化 Memory 和 RAG",
            summary="当前主线是优化记忆系统与 RAG。",
            canonical_statement="项目当前重点是优化 Memory 和 RAG。",
            body="Canonical: 项目当前重点是优化 Memory 和 RAG。\nWhy: 这是当前阶段的主线。\nHow to apply: 系统设计优先围绕 memory 和 rag。",
            memory_type="project",
            memory_class="work",
            retrieval_hints=["项目重点", "主线", "memory", "rag"],
        )
    )
    facade.memory_manager.save_note(
        MemoryNote(
            slug="answer-style",
            title="复杂问题先给结论",
            summary="复杂问题先讲结论再展开。",
            canonical_statement="复杂问题先讲结论再展开。",
            body="Canonical: 复杂问题先讲结论再展开。\nWhy: 用户偏好结论优先。\nHow to apply: 复杂回答先给 summary。",
            memory_type="user",
            memory_class="preference",
            retrieval_hints=["先给结论", "回答方式", "偏好"],
        )
    )


def test_manifest_scan_reads_headers_without_loading_index_body() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        headers = scan_memory_headers(root / "durable_memory")
        manifest = format_memory_manifest(headers)

        assert len(headers) == 2
        assert all(header.filename.endswith(".md") for header in headers)
        assert "project-focus.md" in manifest
        assert "[work/project]" in manifest


def test_recall_request_marks_inventory_queries_as_manifest_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        intent = analyze_memory_intent("你都长期记了什么？")
        result = facade.recall_durable_memories(query="你都长期记了什么？", memory_intent=intent)

        assert result.selection.manifest_only is True
        assert result.selection.should_recall is False
        assert result.selected_notes == []


def test_inventory_query_with_session_marker_still_routes_to_manifest_inventory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        intent = analyze_memory_intent("你刚才帮我长期记住了什么？")
        result = facade.recall_durable_memories(query="你刚才帮我长期记住了什么？", memory_intent=intent)

        assert intent.intent == "durable_memory_query"
        assert intent.explicit_read_inventory is True
        assert result.selection.manifest_only is True
        assert result.selection.should_recall is False
        assert result.selected_notes == []


def test_inventory_query_with_long_term_keep_phrase_routes_to_manifest_inventory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        intent = analyze_memory_intent("你刚刚让我长期保留了哪几件事？")
        result = facade.recall_durable_memories(query="你刚刚让我长期保留了哪几件事？", memory_intent=intent)

        assert intent.intent == "durable_memory_query"
        assert intent.explicit_read_inventory is True
        assert result.selection.manifest_only is True
        assert result.selected_notes == []


def test_recall_request_selects_small_relevant_note_subset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        intent = analyze_memory_intent("我们项目当前重点是什么？")
        result = facade.recall_durable_memories(query="我们项目当前重点是什么？", memory_intent=intent)

        assert result.selection.reason in {"manifest_overlap_fallback", "preselected_notes"}
        assert len(result.selected_notes) <= 3
        assert any(note["filename"] == "project-focus.md" for note in result.selected_notes)


def test_answer_style_query_infers_preference_recall_hints() -> None:
    intent = analyze_memory_intent("以后我问复杂问题时，你应该先怎么回答？")

    assert intent.intent == "memory_read_signal"
    assert intent.preferred_types == ["user"]
    assert intent.preferred_memory_classes == ["preference"]


def test_ignore_memory_instruction_short_circuits_recall() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        intent = analyze_memory_intent("这次不要用记忆，直接按当前文件状态回答。")
        result = facade.recall_durable_memories(query="这次不要用记忆，直接按当前文件状态回答。", memory_intent=intent)

        assert result.selection.ignore_memory is True
        assert result.selection.should_recall is False
        assert result.selected_notes == []


def test_async_recall_uses_subagent_without_event_loop_conflict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        _seed_notes(facade)

        async def _invoke(_messages: list[dict[str, str]]):
            return SimpleNamespace(
                content='{"should_recall": true, "selected_note_ids": ["project-focus"], '
                '"reason": "model_selected", "confidence": 0.9, "needs_verification": false, '
                '"manifest_only": false, "ignore_memory": false}'
            )

        facade.set_model_invoker(_invoke)
        intent = analyze_memory_intent("我们项目当前重点是什么？")

        async def _run():
            return await facade.arecall_durable_memories(query="我们项目当前重点是什么？", memory_intent=intent)

        result = asyncio.run(_run())

        assert result.selection.reason == "model_selected"
        assert any(note["filename"] == "project-focus.md" for note in result.selected_notes)
