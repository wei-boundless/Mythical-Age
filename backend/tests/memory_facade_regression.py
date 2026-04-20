from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from memory import MemoryFacade
from structured_memory import MemoryNote
from understanding.memory_intent import analyze_memory_intent


def test_memory_facade_builds_layered_context_package() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "memory-facade-session"
        history = [
            {"role": "user", "content": "继续分析 report.pdf 第三页的结论。"},
            {"role": "assistant", "content": "第三页主要在讨论供应链风险。"},
        ]

        facade.refresh_session_memory(session_id, history)
        package = facade.build_context_package(
            session_id,
            history=history,
            pending_user_message="继续沿着之前的报告分析往下讲。",
            retrieval_results=[
                {
                    "source": "knowledge/report.md",
                    "collection": "knowledge",
                    "text": "报告的核心矛盾在供应链和现金流之间。",
                }
            ],
        )
        block = facade.build_session_memory_block(
            session_id,
            history=history,
            pending_user_message="继续沿着之前的报告分析往下讲。",
            retrieval_results=[
                {
                    "source": "knowledge/report.md",
                    "collection": "knowledge",
                    "text": "报告的核心矛盾在供应链和现金流之间。",
                }
            ],
        )

        assert package.sections["active_process_context"]
        assert "retrieval_evidence" in package.selected_sections
        assert "# Active Goal" in block
        assert "## Retrieval Evidence" in block
        assert "# Risk Watch" not in block
        assert "# Next Step" not in block
        assert not any("# Risk Watch" in item for item in package.sections["active_process_context"])
        assert not any("# Next Step" in item for item in package.sections["active_process_context"])


def test_memory_facade_durable_prefetch_avoids_exact_match_duplication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        facade.memory_manager.save_note(
            MemoryNote(
                slug="project-focus",
                title="项目当前重点是优化 Memory 和 RAG",
                summary="当前主线是优化记忆系统和 RAG。",
                canonical_statement="项目当前重点是优化 Memory 和 RAG。",
                body="后续所有系统设计默认围绕 Memory 和 RAG 主线推进。",
                memory_type="project",
                memory_class="work",
                tags=["project", "memory", "rag"],
            )
        )
        facade.memory_manager.save_note(
            MemoryNote(
                slug="answer-style",
                title="用户偏好先讲结论",
                summary="复杂问题先讲结论再展开。",
                canonical_statement="复杂问题先讲结论。",
                body="复杂问题先讲结论，再逐层展开。",
                memory_type="user",
                memory_class="preference",
                tags=["user-preference", "style"],
            )
        )

        query = "我们项目当前重点是什么？"
        intent = analyze_memory_intent(query)
        relevant_notes = facade.prefetch_relevant_notes(query, intent, limit=3)
        block = facade.build_persistent_memory_block(
            query=query,
            memory_intent=intent,
            relevant_notes=relevant_notes,
        )

        assert relevant_notes
        assert relevant_notes[0].memory_class == "work"
        assert block.count("### 项目当前重点是优化 Memory 和 RAG") == 1
        assert block.count("项目当前重点是优化 Memory 和 RAG") >= 1


def test_memory_facade_exposes_context_trace_without_legacy_bridge() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "memory-facade-trace"
        history = [
            {"role": "user", "content": "继续优化 memory architecture。"},
            {"role": "assistant", "content": "优先把 session working memory 和 durable memory 分层。"},
        ]

        compacted, trace = facade.compact_history_for_query(session_id, history)
        inspection = facade.inspect_query_context(
            session_id,
            history=history,
            pending_user_message="下一步应该先改哪一层？",
            context_compaction=trace,
        )

        assert compacted
        assert inspection["context_management"]["pressure_level"] in {
            "normal",
            "warning",
            "microcompact",
            "full_compact",
        }
        assert "budget" in inspection["context_management"]
        assert inspection["session_memory"]["storage"]["primary_state_path"].endswith("process_state.json")


def test_memory_facade_refreshes_session_memory_from_context_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "memory-facade-summary-first"

        rendered = facade.refresh_session_memory_from_context_state(
            session_id,
            {
                "active_goal": "继续分析 report.pdf 第三页的结论。",
                "active_work_item": "pdf_analysis",
                "active_constraints": {"page": 3, "source_kind": "pdf"},
                "latest_correction": "不要展开全文，只说结论。",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "继续分析 report.pdf 第三页的结论。",
                    "summary": "第三页主要在讨论供应链风险和现金流压力。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                }
            ],
            corrections=["不要展开全文，只说结论。"],
        )

        stored = facade.session_memory.manager(session_id).load()
        debug_stored = facade.session_memory.manager(session_id).load_debug_view()
        assert "report.pdf" in rendered
        assert "供应链风险和现金流压力" in stored
        assert "不要展开全文，只说结论。" in stored
        assert "# Risk Watch" not in stored
        assert "# Next Step" not in stored
        assert "# Next Step" in debug_stored
