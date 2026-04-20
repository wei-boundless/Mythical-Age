from __future__ import annotations

import tempfile
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from structured_memory import MemoryNote
from understanding.memory_intent import analyze_memory_intent


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        facade.memory_manager.save_note(
            MemoryNote(
                slug="project-focus",
                title="项目当前重点是优化 Memory 和 RAG",
                summary="项目主线是优化记忆系统与RAG。",
                body="后续讨论系统设计时，应默认把 Memory 和 RAG 架构优化视为主线任务。",
                memory_type="project",
                memory_class="work",
                tags=["project", "memory", "rag"],
            )
        )
        facade.memory_manager.save_note(
            MemoryNote(
                slug="answer-style",
                title="用户偏好先讲结论",
                summary="回答复杂问题时先讲结论再展开。",
                body="当问题较复杂时，先给结论，再给展开说明。",
                memory_type="preference",
                memory_class="preference",
                tags=["preference", "style"],
            )
        )

        history = [
            {"role": "user", "content": "请继续优化记忆系统"},
            {"role": "assistant", "content": "建议先做 session hygiene。"},
        ]

        query = "我们项目当前重点是什么"
        intent = analyze_memory_intent(query)
        relevant = facade.prefetch_relevant_notes(query, intent, limit=3)
        _compacted_history, context_compaction = facade.compact_history_for_query(
            "session-1",
            history,
        )
        trace = facade.inspect_query_context(
            "session-1",
            history=history,
            pending_user_message=query,
            memory_intent=intent,
            relevant_notes=relevant,
            context_compaction=context_compaction,
        )
        loaded_notes = facade.memory_manager.list_notes()
        session_block = facade.build_session_memory_block(
            "session-1",
            history=history,
            pending_user_message=query,
            memory_intent=intent,
            relevant_notes=loaded_notes,
            include_durable_context=True,
        )

        _assert(trace["memory_intent"]["read_mode"] == "durable_exact", "trace should expose durable exact read mode")
        _assert(trace["memory_intent"]["preferred_memory_classes"] == ["work"], "trace should expose preferred work class")
        _assert(trace["session_memory"]["present"] is True, "trace should show session memory presence")
        _assert("# Active Goal" in trace["session_memory"]["preview"], "session preview should expose session-state sections")
        _assert(trace["context_management"]["pressure_level"] in {"normal", "warning", "microcompact", "full_compact"}, "trace should expose context pressure level")
        _assert("estimated_tokens_before" in trace["context_management"], "trace should expose context token estimates")
        _assert("budget" in trace["context_management"], "trace should expose context-package budget details")
        _assert("active_process_context" in trace["context_management"]["selected_sections"], "trace should expose active-process section selection")
        _assert(trace["durable_memory"]["exact_matches"], "trace should expose exact durable matches")
        _assert(
            trace["durable_memory"]["exact_matches"][0]["title"] == "项目当前重点是优化 Memory 和 RAG",
            "trace should include exact match title",
        )
        _assert(
            all(
                item["filename"] != trace["durable_memory"]["exact_matches"][0]["filename"]
                for item in trace["durable_memory"]["relevant_notes"]
            ),
            "relevant notes should not duplicate exact match filenames",
        )
        _assert("## Exact Durable Context" in session_block, "session block should surface exact durable context when requested")
        _assert("## Relevant Durable Context" in session_block, "session block should surface relevant durable context separately")
        _assert(
            session_block.index("## Exact Durable Context") < session_block.index("## Relevant Durable Context"),
            "exact durable context should be ordered ahead of relevant durable context",
        )

    print("ALL PASSED (memory observability)")


if __name__ == "__main__":
    main()
