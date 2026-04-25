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
        assert package.model_visible_sections["active_process_context"]
        assert package.sections == package.model_visible_sections
        assert package.debug_sections["active_process_context"]
        assert "debug_session_trace" in package.debug_selected_sections
        assert "retrieval_evidence" in package.selected_sections
        assert "# Active Goal" in block
        assert "# Flow State" not in block
        assert "# Current Task State" not in block
        assert "## Retrieval Evidence" in block
        assert "## Debug Session Trace" not in block
        assert "# Risk Watch" not in block
        assert "# Next Step" not in block
        assert not any("# Risk Watch" in item for item in package.sections["active_process_context"])
        assert not any("# Next Step" in item for item in package.sections["active_process_context"])
        assert not any("# Flow State" in item for item in package.sections["active_process_context"])
        assert not any("# Current Task State" in item for item in package.sections["active_process_context"])
        assert any("# Next Step" in item for item in package.debug_sections["debug_session_trace"])


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
        assert inspection["session_memory"]["preview"]
        assert inspection["session_memory"]["model_preview"]
        assert "## Debug Session Trace" in inspection["session_memory"]["preview"]
        assert "# Next Step" not in inspection["session_memory"]["model_preview"]
        assert "当前规则：" not in inspection["session_memory"]["model_preview"]
        assert "active_rule" not in inspection["session_memory"]["model_visible"]["context_slots"]
        assert "active_rule" in inspection["session_memory"]["debug_visible"]["context_slots"]
        assert inspection["session_memory"]["preview"] != inspection["session_memory"]["model_preview"]


def test_memory_facade_isolates_explicit_durable_turn_from_process_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "memory-facade-durable-isolation"
        history = [
            {"role": "user", "content": "回到 report.pdf 第二部分，继续分析约束重点。"},
            {"role": "assistant", "content": "第二部分主要收紧了模型部署和审计要求。"},
        ]

        facade.refresh_session_memory(session_id, history)
        intent = analyze_memory_intent("记住：回答我时可以直接称呼我岩。")
        package = facade.build_context_package(
            session_id,
            history=history,
            pending_user_message="记住：回答我时可以直接称呼我岩。",
            memory_intent=intent,
        )

        assert not package.model_visible_sections["active_process_context"]
        assert not package.model_visible_sections["hot_truth_window"]
        assert not package.sections["active_process_context"]
        assert "# Active Goal" in "\n".join(package.debug_sections["active_process_context"])


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


def test_session_memory_model_view_masks_bindings_and_handles() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facade = MemoryFacade(root)
        session_id = "memory-facade-binding-mask"
        facade.refresh_session_memory_from_context_state(
            session_id,
            {
                "active_goal": "继续分析 report.pdf。",
                "active_work_item": "pdf_analysis",
                "active_binding_identity": "knowledge/reports/report.pdf",
                "active_object_handle_id": "source:pdf:secret",
                "active_result_handle_id": "result:pdf_summary:secret",
                "active_constraints": {
                    "active_pdf": "knowledge/reports/report.pdf",
                    "source_kind": "pdf",
                    "pdf_mode": "document",
                },
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "继续分析 report.pdf。",
                    "summary": "PDF 结论已经形成。",
                    "key_points": ["pdf=knowledge/reports/report.pdf"],
                }
            ],
        )

        manager = facade.session_memory.manager(session_id)
        model_preview = manager.load()
        debug_preview = manager.load_debug_view()

        assert "当前 PDF：available" in model_preview
        assert "knowledge/reports/report.pdf" not in model_preview
        assert "source:pdf:secret" not in model_preview
        assert "result:pdf_summary:secret" not in model_preview
        assert "knowledge/reports/report.pdf" in debug_preview
        assert "source:pdf:secret" in debug_preview
