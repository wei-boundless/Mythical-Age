from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from structured_memory import MemoryManager, MemoryNote, Message
from structured_memory.consolidation import DurableMemoryConsolidator
from understanding.memory_intent import analyze_memory_intent
from understanding.memory_policy import evaluate_memory_write


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _save_seed_notes(root: Path) -> MemoryManager:
    manager = MemoryManager(root / "durable_memory")
    manager.save_note(
        MemoryNote(
            slug="project-focus",
            title="项目当前重点是优化 Memory 和 RAG",
            summary="当前主线是优化记忆系统与 RAG。",
            body="后续讨论系统设计时，应默认把 Memory 和 RAG 架构优化视为主线任务。",
            memory_type="project",
            memory_class="work",
            tags=["project", "memory", "rag"],
        )
    )
    manager.save_note(
        MemoryNote(
            slug="powershell-rule",
            title="终端命令优先使用 PowerShell 语法",
            summary="当前环境下默认使用 PowerShell 风格命令。",
            body="在终端操作中，优先使用 PowerShell 风格命令，例如 Get-ChildItem、Get-Content、Select-String。",
            memory_type="workflow",
            memory_class="work",
            tags=["workflow", "terminal", "powershell"],
        )
    )
    manager.save_note(
        MemoryNote(
            slug="answer-style",
            title="用户偏好先讲结论",
            summary="复杂问题先讲结论再展开。",
            body="当问题较复杂时，先给结论，再给展开说明，避免一开始铺得太长。",
            memory_type="preference",
            memory_class="preference",
            tags=["preference", "style"],
        )
    )
    return manager


def test_memory_intent_routing() -> None:
    work_intent = analyze_memory_intent("我们项目当前重点是什么？")
    _assert(work_intent.intent == "durable_memory_query", "work query should route to durable memory")
    _assert(work_intent.memory_read_mode == "durable_exact", "work query should use durable exact read mode")
    _assert(work_intent.preferred_memory_classes == ["work"], "work query should prefer work memory")

    pref_intent = analyze_memory_intent("你知道我喜欢你怎么回答吗？")
    _assert(pref_intent.intent == "durable_memory_query", "preference query should route to durable memory")
    _assert(pref_intent.preferred_memory_classes == ["preference"], "preference query should prefer preference memory")


def test_memory_policy_partitioning() -> None:
    pref = evaluate_memory_write("记住我以后喜欢你先讲结论。")
    _assert(pref.action == "durable_fact", "stable preference should be durable")
    _assert(pref.memory_class == "preference", "stable preference should map to preference")
    _assert(pref.memory_type == "preference", "stable preference should map to preference type")

    work = evaluate_memory_write("记住我们以后所有终端命令优先用 PowerShell。")
    _assert(work.action == "durable_fact", "workflow convention should be durable")
    _assert(work.memory_class == "work", "workflow convention should map to work")
    _assert(work.memory_type == "workflow", "workflow convention should map to workflow type")

    emotion = evaluate_memory_write("我今天很难过。")
    _assert(emotion.action == "session_only", "transient emotion should remain session-only")

    attachment = evaluate_memory_write("我爱上你了。")
    _assert(attachment.action == "session_only", "attachment expression should remain session-only")


def test_extractor_uses_policy_classes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        messages = [
            Message(role="user", content="记住我以后喜欢你先讲结论。"),
            Message(role="user", content="记住我们以后所有终端命令优先用 PowerShell。"),
        ]
        saved = facade.extractor.save_extracted(messages)
        classes = {note.memory_class for note in saved}

        _assert("preference" in classes, "extractor should save a preference note")
        _assert("work" in classes, "extractor should save a work note")
        _assert(
            all(note.created_by == "memory_extractor" for note in saved),
            "extractor-created durable notes should record their creation source",
        )
        _assert(
            all(note.confidence in {"high", "medium"} for note in saved),
            "extractor-created durable notes should record confidence",
        )
        _assert(
            all(note.source_message_excerpt for note in saved),
            "extractor-created durable notes should retain a source message excerpt",
        )
        _assert(
            all(note.schema_version == "durable-memory.v2" for note in saved),
            "extractor-created durable notes should record the durable schema version",
        )
        _assert(
            all(note.canonical_statement for note in saved),
            "extractor-created durable notes should store a canonical statement",
        )
        _assert(
            all(note.retrieval_hints for note in saved),
            "extractor-created durable notes should store retrieval hints",
        )


def test_prefetch_respects_partitions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _save_seed_notes(root)
        facade = MemoryFacade(root)

        work_query = "我们项目当前重点是什么？"
        work_notes = facade.prefetch_relevant_notes(work_query, analyze_memory_intent(work_query), limit=2)
        _assert(work_notes, "work prefetch should return notes")
        _assert(work_notes[0].memory_class == "work", "work query should surface work memory first")
        _assert(work_notes[0].filename == "project-focus.md", "project focus should surface first for project query")

        pref_query = "你知道我喜欢你怎么回答吗？"
        pref_notes = facade.prefetch_relevant_notes(pref_query, analyze_memory_intent(pref_query), limit=2)
        _assert(pref_notes, "preference prefetch should return notes")
        _assert(pref_notes[0].memory_class == "preference", "preference query should surface preference memory first")
        _assert(pref_notes[0].filename == "answer-style.md", "answer style should surface first for preference query")

        unrelated_notes = facade.prefetch_relevant_notes("今天天气怎么样？", analyze_memory_intent("今天天气怎么样？"), limit=2)
        _assert(not unrelated_notes, "unrelated generic query should not surface durable notes")


def test_persistent_memory_block_combines_exact_and_relevant_without_duplication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _save_seed_notes(root)
        facade = MemoryFacade(root)
        query = "我们项目当前重点是什么？"
        intent = analyze_memory_intent(query)
        relevant = facade.prefetch_relevant_notes(query, intent, limit=2)
        block = facade.build_persistent_memory_block(query=query, memory_intent=intent, relevant_notes=relevant)

        _assert("## Exact Durable Memory Matches" in block, "block should contain exact matches section")
        _assert("## Relevant Durable Memories" in block, "block should contain relevant memory section")
        _assert("Schema: durable-memory.v2" in block, "block should expose durable schema version")
        _assert("Canonical:" in block, "block should expose canonical statement metadata")
        _assert(block.count("### 项目当前重点是优化 Memory 和 RAG") == 1, "exact match should not be duplicated in the relevant section")


def test_memory_manifest_exposes_note_health_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = _save_seed_notes(root)
        manifest = manager.build_manifest(limit=5)

        _assert("[work/project]" in manifest or "[work/workflow]" in manifest, "manifest should still expose note partitioning")
        _assert("[medium/active]" in manifest, "manifest should include confidence and status metadata for durable notes")


def test_archived_durable_notes_are_hidden_from_runtime_reads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = MemoryManager(root / "durable_memory")
        manager.save_note(
            MemoryNote(
                slug="active-rule",
                title="Active PowerShell Rule",
                summary="Prefer PowerShell in terminal commands.",
                canonical_statement="Prefer PowerShell in terminal commands.",
                body="## Canonical Memory\nPrefer PowerShell in terminal commands.",
                memory_type="workflow",
                memory_class="work",
                tags=["workflow", "powershell"],
                retrieval_hints=["PowerShell", "terminal"],
                status="active",
            )
        )
        manager.save_note(
            MemoryNote(
                slug="archived-rule",
                title="Archived Bash Rule",
                summary="Prefer bash in terminal commands.",
                canonical_statement="Prefer bash in terminal commands.",
                body="## Canonical Memory\nPrefer bash in terminal commands.",
                memory_type="workflow",
                memory_class="work",
                tags=["workflow", "bash"],
                retrieval_hints=["bash", "terminal"],
                status="archived",
            )
        )

        visible = manager.load_relevant_notes(limit=5)
        surfaced = manager.select_relevant_notes("terminal powershell", preferred_classes=["work"], limit=5)

        _assert(all(note.status != "archived" for note in visible), "archived notes should not appear in default loaded durable notes")
        _assert(all(note.status != "archived" for note in surfaced), "archived notes should not surface in relevant durable retrieval")


def test_durable_extraction_prefers_session_state_candidates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-state-durable"
        messages = [
            {"role": "user", "content": "以后默认先给结论，再展开解释。"},
            {"role": "assistant", "content": "结论：我会默认先给结论，再展开解释。"},
            {"role": "user", "content": "终端命令优先用 PowerShell。"},
        ]

        facade.refresh_session_memory(session_id, messages)
        saved = facade.extract_durable_memories(session_id, messages)
        notes = facade.memory_manager.list_notes()

        _assert(saved >= 1, "state-driven durable extraction should save at least one durable note")
        _assert(
            any(note.created_by == "session_state_extractor" for note in notes),
            "durable extraction should record that notes came from session state",
        )


def test_consolidation_report_keeps_partition_signal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = _save_seed_notes(root)
        manager.save_note(
            MemoryNote(
                slug="answer-style-copy",
                title="用户偏好先讲结论",
                summary="复杂问题先讲结论再展开。",
                body="当问题较复杂时，先给结论，再给展开说明，避免一开始铺得太长。",
                memory_type="preference",
                memory_class="preference",
                tags=["preference", "style"],
            )
        )
        report = DurableMemoryConsolidator(root / "durable_memory").run()

        _assert(report.class_counts.get("work") == 2, "report should count work notes correctly")
        _assert(report.class_counts.get("preference") == 2, "report should count preference notes correctly")
        _assert(report.duplicate_candidates, "report should find duplicate candidates")
        _assert(report.merge_candidates, "report should generate merge candidates")
        _assert(
            report.merge_candidates[0].primary_filename in {"answer-style.md", "answer-style-copy.md"},
            "merge plan should select one preference note as primary",
        )


def main() -> None:
    tests = [
        test_memory_intent_routing,
        test_memory_policy_partitioning,
        test_extractor_uses_policy_classes,
        test_prefetch_respects_partitions,
        test_persistent_memory_block_combines_exact_and_relevant_without_duplication,
        test_memory_manifest_exposes_note_health_metadata,
        test_archived_durable_notes_are_hidden_from_runtime_reads,
        test_durable_extraction_prefers_session_state_candidates,
        test_consolidation_report_keeps_partition_signal,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
