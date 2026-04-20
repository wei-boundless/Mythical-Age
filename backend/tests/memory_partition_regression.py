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
            slug="answer-style",
            title="用户偏好先讲结论",
            summary="复杂问题先讲结论再展开。",
            body="当问题较复杂时，先给结论，再给展开说明，避免一开始铺得太长。",
            memory_type="user",
            memory_class="preference",
            tags=["user-preference", "style"],
        )
    )
    return manager


def test_memory_intent_routing() -> None:
    work_intent = analyze_memory_intent("我们项目当前重点是什么？")
    _assert(work_intent.intent == "memory_read_signal", "work query should become a weak durable-memory signal")
    _assert(work_intent.memory_read_mode == "none", "semantic work recall should no longer force durable read mode in memory_intent")
    _assert(work_intent.should_skip_rag is False, "semantic work recall should not bypass retrieval by default")
    _assert(work_intent.preferred_memory_classes == ["work"], "work query should prefer work memory")

    mainline_intent = analyze_memory_intent("我们项目现在优先做什么？")
    _assert(mainline_intent.intent == "memory_read_signal", "mainline query should become a weak durable-memory signal")
    _assert(mainline_intent.preferred_types == ["project"], "mainline query should prefer project durable notes")

    pref_intent = analyze_memory_intent("你知道我喜欢你怎么回答吗？")
    _assert(pref_intent.intent == "memory_read_signal", "preference recall should become a weak durable-memory signal")
    _assert(pref_intent.preferred_memory_classes == ["preference"], "preference query should prefer preference memory")

    manual_memory_query = analyze_memory_intent("你都长期记了什么？")
    _assert(manual_memory_query.intent == "durable_memory_query", "explicit long-term memory inventory query should stay a strong durable route")
    _assert(manual_memory_query.should_skip_rag is True, "explicit long-term memory inventory query should bypass retrieval")

    file_followup = analyze_memory_intent("回到 inventory.xlsx，哪个仓库现在最需要优先补货？")
    _assert(file_followup.intent == "general", "explicit file follow-up should not be hijacked by durable memory intent")

    negative = analyze_memory_intent("我今天有点焦虑，但这不是要你长期记住的偏好。")
    _assert(negative.intent == "general", "negative durable write instruction should not become a durable write intent")


def test_memory_policy_partitioning() -> None:
    pref = evaluate_memory_write("记住我以后喜欢你先讲结论。")
    _assert(pref.action == "durable_fact", "stable preference should be durable")
    _assert(pref.memory_class == "preference", "stable preference should map to preference")
    _assert(pref.memory_type == "user", "stable preference should map to user durable type")

    work = evaluate_memory_write("记住我们以后所有终端命令优先用 PowerShell。")
    _assert(work.action == "ignore", "workflow convention should stay out of dynamic durable memory")
    _assert(work.reason == "static_profile_rule", "workflow convention should be treated as a static profile rule")

    emotion = evaluate_memory_write("我今天很难过。")
    _assert(emotion.action == "session_only", "transient emotion should remain session-only")

    attachment = evaluate_memory_write("我爱上你了。")
    _assert(attachment.action == "session_only", "attachment expression should remain session-only")

    negative = evaluate_memory_write("这不是要你长期记住的偏好。")
    _assert(negative.action == "ignore", "negative durable write instruction should be ignored")
    _assert(negative.reason == "negative_memory_instruction", "negative durable write should record the correct reason")

    task_local = evaluate_memory_write("回到 inventory.xlsx，给我最缺货的前三个仓库。")
    _assert(task_local.action == "ignore", "task-local file request should stay out of durable memory")
    _assert(task_local.reason == "task_local_or_runtime_state", "task-local file request should be marked as runtime/task-local noise")


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
        _assert("work" not in classes, "static profile rules should not be saved into dynamic durable memory")
        _assert(
            all(note.created_by == "durable_write_agent" for note in saved),
            "extractor-created durable notes should record the new write-agent creation source",
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
            all(note.schema_version == "durable-memory.v3" for note in saved),
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


def test_extractor_uses_projection_first_and_only_falls_back_to_messages_when_needed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        notes = facade.extractor.extract(
            [
                Message(
                    role="assistant",
                    content="projection",
                    meta={
                        "session_id": "projection-first-session",
                        "projection": "durable_context_state",
                        "main_context": {
                            "active_goal": "以后默认先给结论，再展开解释。",
                            "latest_correction": "",
                        },
                        "corrections": [],
                    },
                ),
                Message(
                    role="user",
                    content="记住我以后喜欢你先讲结论。",
                    meta={"session_id": "projection-first-session"},
                ),
            ]
        )

        _assert(notes, "projection-first extraction should still emit durable notes")
        _assert(
            all(note.created_by != "memory_extractor" for note in notes),
            "explicit transcript fallback should stay inactive when projection/state candidates already exist",
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
        _assert("Kind: work / project" in block, "block should expose semantic durable type metadata")
        _assert("Canonical:" in block, "block should expose canonical statement metadata")
        _assert(block.count("### 项目当前重点是优化 Memory 和 RAG") == 1, "exact match should not be duplicated in the relevant section")


def test_persistent_memory_block_uses_manifest_fallback_when_no_note_matches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _save_seed_notes(root)
        facade = MemoryFacade(root)
        query = "你都长期记了什么？"
        intent = analyze_memory_intent(query)
        block = facade.build_persistent_memory_block(query=query, memory_intent=intent, relevant_notes=[])

        _assert("## Durable Memory Manifest" in block, "manifest should be used as a lightweight fallback when no durable note matches")
        _assert("[work/project]" in block, "manifest fallback should expose durable partition metadata")


def test_persistent_memory_block_stays_empty_for_generic_queries_without_memory_signal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _save_seed_notes(root)
        facade = MemoryFacade(root)
        query = "今天天气怎么样？"
        intent = analyze_memory_intent(query)
        block = facade.build_persistent_memory_block(query=query, memory_intent=intent, relevant_notes=[])

        _assert(block == "", "generic queries should not receive durable manifest fallback or other durable prompt noise")


def test_persistent_memory_block_hides_internal_storage_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        facade.memory_manager.save_note(
            MemoryNote(
                slug="powershell-terminal-preference",
                title="终端命令优先使用 PowerShell 语法",
                summary="默认终端命令使用 PowerShell 语法。",
                canonical_statement="默认终端命令使用 PowerShell 语法。",
                body=(
                    "## Canonical Memory\n默认终端命令使用 PowerShell 语法。\n\n"
                    "## Source Evidence\n已写入长期记忆：`durable_memory/work/workflow/powershell-terminal-preference.md`"
                ),
                memory_type="project",
                memory_class="work",
                tags=["workflow", "powershell"],
                retrieval_hints=["PowerShell", "terminal"],
                source_message_excerpt="已写入长期记忆：`durable_memory/work/workflow/powershell-terminal-preference.md`",
            )
        )

        query = "默认终端命令应该用什么？"
        intent = analyze_memory_intent(query)
        relevant = facade.prefetch_relevant_notes(query, intent, limit=2)
        block = facade.build_persistent_memory_block(query=query, memory_intent=intent, relevant_notes=relevant)

        _assert("PowerShell" in block, "block should preserve user-facing semantic content")
        _assert("durable_memory/" not in block, "block should not expose internal durable storage paths")
        _assert(".md" not in block, "block should not expose note filenames")


def test_memory_manifest_exposes_note_health_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = _save_seed_notes(root)
        manifest = manager.build_manifest(limit=5)

        _assert("[work/project]" in manifest, "manifest should still expose note partitioning")
        _assert("[medium/active/stable]" in manifest, "manifest should include confidence, status, and stability metadata for durable notes")


def test_memory_manager_confirms_equivalent_note_instead_of_duplicating() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = MemoryManager(root / "durable_memory")
        manager.save_note(
            MemoryNote(
                slug="answer-style",
                title="用户偏好先讲结论",
                summary="复杂问题先讲结论再展开。",
                canonical_statement="复杂问题先讲结论。",
                body="先讲结论，再展开说明。",
                memory_type="user",
                memory_class="preference",
                retrieval_hints=["结论优先"],
            )
        )
        manager.save_note(
            MemoryNote(
                slug="answer-style-new",
                title="用户偏好先讲结论",
                summary="复杂问题先讲结论再展开解释。",
                canonical_statement="复杂问题先讲结论。",
                body="先讲结论，再展开解释，避免一开始铺太长。",
                memory_type="user",
                memory_class="preference",
                retrieval_hints=["结论优先", "先给结论"],
            )
        )

        notes = manager.list_notes()
        _assert(len(notes) == 1, "equivalent durable notes should be confirmed instead of duplicated")
        _assert(notes[0].last_confirmed_at, "equivalent note confirmation should record last_confirmed_at")
        _assert("先给结论" in notes[0].retrieval_hints, "equivalent note confirmation should merge retrieval hints")


def test_memory_manager_supersedes_conflicting_note_and_hides_old_one() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        facade.memory_manager.save_note(
            MemoryNote(
                slug="project-focus-old",
                title="项目当前重点",
                summary="当前重点是优化 Memory。",
                canonical_statement="项目当前重点是优化 Memory。",
                body="项目当前重点是优化 Memory。",
                memory_type="project",
                memory_class="work",
            )
        )
        facade.memory_manager.save_note(
            MemoryNote(
                slug="project-focus-new",
                title="项目当前重点",
                summary="当前重点是优化 RAG。",
                canonical_statement="项目当前重点是优化 RAG。",
                body="项目当前重点是优化 RAG。",
                memory_type="project",
                memory_class="work",
            )
        )

        notes = {note.filename: note for note in facade.memory_manager.list_notes()}
        _assert(notes["project-focus-old.md"].status == "deprecated", "superseded durable note should be deprecated")
        _assert(notes["project-focus-old.md"].eligible_for_injection == "false", "superseded durable note should stop participating in injection")
        _assert(notes["project-focus-new.md"].supersedes == "project-focus-old", "new durable note should record which note it supersedes")
        surfaced = facade.prefetch_relevant_notes("我们项目当前重点是什么？", analyze_memory_intent("我们项目当前重点是什么？"), limit=5)
        _assert(
            all(note.filename != "project-focus-old.md" for note in surfaced),
            "superseded durable note should be hidden from runtime relevant retrieval",
        )


def test_memory_manager_governance_normalizes_instruction_wrapper_and_deprecates_duplicates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = MemoryManager(root / "durable_memory")
        manager.save_note(
            MemoryNote(
                slug="memory-note",
                title="记住：我们项目当前主线是优化 Memory 和 RAG。",
                summary="记住：我们项目当前主线是优化 Memory 和 RAG。",
                canonical_statement="记住：我们项目当前主线是优化 Memory 和 RAG。",
                body="## Canonical Memory\n记住：我们项目当前主线是优化 Memory 和 RAG。",
                memory_type="project",
                memory_class="work",
                retrieval_hints=["记住：我们项目当前主线是优化 Memory 和 RAG。"],
                created_by="memory_extractor",
                source_role="user",
                source_message_excerpt="记住：我们项目当前主线是优化 Memory 和 RAG。",
            )
        )
        manager.save_note(
            MemoryNote(
                slug="memory-rag",
                title="我们项目当前主线是优化 Memory 和 RAG。",
                summary="我们项目当前主线是优化 Memory 和 RAG。",
                canonical_statement="我们项目当前主线是优化 Memory 和 RAG。",
                body="## Canonical Memory\n我们项目当前主线是优化 Memory 和 RAG。",
                memory_type="project",
                memory_class="work",
                retrieval_hints=["Memory", "RAG"],
                created_by="session_state_extractor",
                source_role="user",
                source_message_excerpt="我们项目当前主线是优化 Memory 和 RAG。",
            )
        )

        report = manager.govern_note_store()
        notes = {note.filename: note for note in manager.list_notes()}

        _assert(report["updated"] >= 1, "governance should rewrite old instruction-wrapper durable notes")
        _assert(
            notes["memory-note.md"].canonical_statement == "我们项目当前主线是优化 Memory 和 RAG。",
            "governance should strip explicit memory-write wrappers from canonical durable facts",
        )
        _assert(
            notes["memory-rag.md"].status == "deprecated",
            "governance should deprecate duplicate durable notes after normalization",
        )
        _assert(
            notes["memory-rag.md"].eligible_for_injection == "false",
            "duplicate durable notes should stop participating in injection after governance",
        )


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
                memory_type="project",
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
                memory_type="project",
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


def test_durable_extraction_prefers_context_state_projection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-state-durable"
        main_context = {
            "active_goal": "以后默认先给结论，再展开解释。",
            "active_work_item": "response_preference",
            "latest_correction": "",
            "next_step": "answer_current_request",
        }

        facade.refresh_session_memory_from_context_state(session_id, main_context)
        saved = facade.commit_durable_memory_extraction_from_context_state(session_id, main_context)
        notes = facade.memory_manager.list_notes()

        _assert(saved >= 1, "projection-driven durable extraction should save at least one durable note")
        _assert(
            any(note.created_by == "durable_write_agent" for note in notes),
            "projection-driven durable extraction should record the write-agent source",
        )


def test_summary_first_durable_commit_uses_session_projection_and_blocks_task_local_noise() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)

        preference_session = "summary-first-durable-pref"
        preference_context = {
            "active_goal": "以后默认先给结论，再展开解释。",
            "active_work_item": "response_preference",
            "next_step": "answer_current_request",
        }
        facade.refresh_session_memory_from_context_state(preference_session, preference_context)
        saved_pref = facade.commit_durable_memory_extraction_from_context_state(
            preference_session,
            preference_context,
        )
        notes = facade.memory_manager.list_notes()

        _assert(saved_pref >= 1, "summary-first durable commit should still preserve stable preferences")
        _assert(
            any("先给结论" in note.canonical_statement for note in notes),
            "summary-first durable commit should write stable preference facts from projected state",
        )

        task_session = "summary-first-durable-task"
        task_context = {
            "active_goal": "给我 inventory.xlsx 里最缺货的前三个仓库。",
            "active_work_item": "compound_query",
            "active_constraints": {"top_n": 3, "group_by": "仓库"},
            "next_step": "answer_current_request",
        }
        facade.refresh_session_memory_from_context_state(
            task_session,
            task_context,
            task_summaries=[
                {
                    "task_id": "task-1",
                    "query": "给我 inventory.xlsx 里最缺货的前三个仓库。",
                    "summary": "武汉仓缺口 404，上海仓缺口 392，深圳仓缺口 392。",
                }
            ],
        )
        saved_task = facade.commit_durable_memory_extraction_from_context_state(
            task_session,
            task_context,
            task_summaries=[
                {
                    "task_id": "task-1",
                    "query": "给我 inventory.xlsx 里最缺货的前三个仓库。",
                    "summary": "武汉仓缺口 404，上海仓缺口 392，深圳仓缺口 392。",
                }
            ],
        )

        _assert(saved_task == 0, "task-local projected results should not be promoted into durable memory")
        _assert(
            all("inventory.xlsx" not in note.canonical_statement for note in facade.memory_manager.list_notes()),
            "task-local dataset requests should stay out of durable memory after summary-first commit",
        )


def test_explicit_durable_commit_filters_synthetic_state_noise_and_keeps_project_type() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "session-state-commit"
        messages = [
            {"role": "user", "content": "记住：默认终端命令用 PowerShell。"},
            {"role": "assistant", "content": "已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`"},
            {"role": "user", "content": "记住：我们项目当前主线是优化 Memory 和 RAG。"},
            {"role": "assistant", "content": "已写入长期记忆：`durable_memory/work/project/memory-rag-mainline.md`"},
            {"role": "user", "content": "以后终端命令默认用什么？"},
        ]

        facade.refresh_session_memory(session_id, messages)
        saved = facade.commit_durable_memory_extraction(session_id, messages)
        notes = facade.memory_manager.list_notes()

        _assert(saved >= 1, "explicit durable commit should save session-state notes immediately")
        _assert(
            any(note.memory_type == "project" and "主线" in note.canonical_statement for note in notes),
            "project mainline note should be committed as a project durable memory",
        )
        _assert(
            all("PowerShell" not in note.canonical_statement for note in notes),
            "static profile rules should not be promoted into dynamic durable memory",
        )
        _assert(
            all("已写入长期记忆" not in note.title for note in notes),
            "synthetic assistant write receipts should not be committed as durable notes",
        )
        _assert(
            all(not note.canonical_statement.endswith(("?", "？")) for note in notes),
            "question-form state noise should not be committed as durable notes",
        )


def test_runtime_reads_hide_assistant_generated_memory_receipts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        facade.memory_manager.save_note(
            MemoryNote(
                slug="assistant-receipt",
                title="已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`",
                summary="已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`",
                canonical_statement="已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`",
                body="## Canonical Memory\n已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`",
                memory_type="project",
                memory_class="work",
                tags=["workflow", "powershell"],
                retrieval_hints=["workflow", "powershell"],
                created_by="session_state_extractor",
                source_role="assistant",
                source_message_excerpt="已写入长期记忆：`durable_memory/work/workflow/powershell-default.md`",
                confidence="high",
            )
        )
        facade.memory_manager.save_note(
            MemoryNote(
                slug="powershell-terminal-preference",
                title="终端命令优先使用 PowerShell 语法",
                summary="默认终端命令使用 PowerShell 语法。",
                canonical_statement="默认终端命令使用 PowerShell 语法。",
                body="## Canonical Memory\n默认终端命令使用 PowerShell 语法。",
                memory_type="project",
                memory_class="work",
                tags=["workflow", "powershell"],
                retrieval_hints=["PowerShell", "terminal"],
                created_by="manual",
                source_role="user",
                source_message_excerpt="默认终端命令使用 PowerShell 语法。",
                confidence="high",
            )
        )

        query = "默认终端命令应该用什么？"
        intent = analyze_memory_intent(query)
        exact_matches = facade.durable_memory.find_exact_matches(query, intent, note_limit=3)
        relevant_notes = facade.prefetch_relevant_notes(query, intent, limit=3)

        _assert(exact_matches, "exact runtime lookup should still return the valid workflow note")
        _assert(
            exact_matches[0].filename == "powershell-terminal-preference.md",
            "assistant receipt should not outrank the valid workflow note",
        )
        _assert(
            all(match.filename != "assistant-receipt.md" for match in exact_matches),
            "assistant receipt should be hidden from exact runtime lookup",
        )
        _assert(
            all(note.filename != "assistant-receipt.md" for note in relevant_notes),
            "assistant receipt should be hidden from relevant runtime lookup",
        )


def test_explicit_durable_commit_ignores_assistant_acknowledgement_notes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "assistant-ack-commit"
        messages = [
            {"role": "user", "content": "记住：以后复杂问题先给结论。"},
            {
                "role": "assistant",
                "content": "收到，岩。 **结论：** 已记住，以后复杂问题我会先给结论，再展开说明。",
            },
        ]

        facade.refresh_session_memory(session_id, messages)
        facade.commit_durable_memory_extraction(session_id, messages)
        notes = facade.memory_manager.list_notes()

        _assert(notes, "user durable preference should still be committed")
        _assert(
            all(note.source_role != "assistant" for note in notes),
            "assistant acknowledgement notes should not be committed into durable memory",
        )
        _assert(
            all("收到，岩" not in note.title for note in notes),
            "assistant acknowledgement wording should not survive as a durable note title",
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
                memory_type="user",
                memory_class="preference",
                tags=["user-preference", "style"],
            )
        )
        report = DurableMemoryConsolidator(root / "durable_memory").run()

        _assert(report.class_counts.get("work") == 1, "report should count work notes correctly")
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
        test_extractor_uses_projection_first_and_only_falls_back_to_messages_when_needed,
        test_prefetch_respects_partitions,
        test_persistent_memory_block_combines_exact_and_relevant_without_duplication,
        test_persistent_memory_block_uses_manifest_fallback_when_no_note_matches,
        test_persistent_memory_block_stays_empty_for_generic_queries_without_memory_signal,
        test_persistent_memory_block_hides_internal_storage_paths,
        test_memory_manifest_exposes_note_health_metadata,
        test_memory_manager_confirms_equivalent_note_instead_of_duplicating,
        test_memory_manager_supersedes_conflicting_note_and_hides_old_one,
        test_memory_manager_governance_normalizes_instruction_wrapper_and_deprecates_duplicates,
        test_archived_durable_notes_are_hidden_from_runtime_reads,
        test_durable_extraction_prefers_session_state_candidates,
        test_summary_first_durable_commit_uses_session_projection_and_blocks_task_local_noise,
        test_explicit_durable_commit_filters_synthetic_state_noise_and_keeps_project_type,
        test_runtime_reads_hide_assistant_generated_memory_receipts,
        test_explicit_durable_commit_ignores_assistant_acknowledgement_notes,
        test_consolidation_report_keeps_partition_signal,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
