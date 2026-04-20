from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from structured_memory import Message, SessionMemoryManager
from structured_memory.session_processor import SessionUnderstandingProcessor


def _load_build_default_collections():
    module_path = BACKEND_DIR / "RAG" / "collections.py"
    module_name = "test_rag_collections"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load RAG collections module for testing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.build_default_collections


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_session_memory_hygiene() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        messages = [
            Message(role="user", content="你是谁？"),
            Message(
                role="assistant",
                content="我是**河伯**，一个本地优先的 AI Agent。基础定位：冷静、直接、工程化。核心能力：本地文件分析、RAG、联网搜索……",
            ),
            Message(
                role="assistant",
                content='{"ok": true, "query": "我要实时的黄金价格", "results": [{"title": "foo", "content": "bar"}]}',
            ),
            Message(role="user", content="帮我修复 backend/graph/agent.py 里的复合问题拆分"),
            Message(role="assistant", content="已修复复合问题拆分，并通过 compound_query_regression.py 测试。"),
        ]

        summary = manager.update_from_messages(messages)

        _assert("我是**河伯**" not in summary, "identity intro should be filtered from session summary")
        _assert('"results"' not in summary, "raw JSON payloads should be filtered from session summary")
        _assert("backend/graph/agent.py" in summary, "important file hints should be preserved")
        _assert("复合问题拆分" in summary, "current goal should be preserved")
        _assert("已修复复合问题拆分" in summary, "useful assistant result should be preserved")


def test_session_memory_compact_view_uses_state_sections() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [
                Message(role="user", content="请继续优化记忆系统的 session state"),
                Message(role="assistant", content="建议先做 session hygiene，再加 memory observability。"),
            ]
        )

        compact = manager.compact_view()
        _assert("# Active Goal" in compact, "compact view should expose Active Goal section")
        _assert("# Current Task State" in compact, "compact view should expose Current Task State section")
        _assert("# Next Step" in compact, "compact view should expose Next Step section")
        _assert("# Conventions and Constraints" in compact, "compact view should expose the canonical conventions section")
        _assert("# Workflow and Constraints" not in compact, "compact view should stop rendering the legacy workflow section name")
        _assert("What flow is currently active" in compact, "compact view should use the canonical flow description")
        _assert("What workflow is currently active" not in compact, "compact view should stop rendering the legacy workflow prompt")
        _assert("session hygiene" in compact or "session state" in compact, "compact view should preserve task state content")


def test_session_memory_persists_dialogue_state_separately_from_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [
                Message(role="user", content="帮我重构 session memory，让它先维护状态再渲染摘要"),
                Message(role="assistant", content="结论：先引入 dialogue state，再让 summary.md 只做视图。"),
            ]
        )

        state = manager.load_state()
        summary = manager.load()

        _assert(state.active_goal, "dialogue state should persist the current active goal")
        _assert(state.current_task_state, "dialogue state should persist current task state items")
        _assert(state.turn_trace, "dialogue state should persist turn classifications")
        _assert(state.turn_trace[-1].turn_type in {"result_delivery", "decision_or_plan"}, "assistant turn should be classified in state")
        _assert("# Active Goal" in summary, "summary should remain a rendered markdown view")
        _assert(state.active_goal in summary, "summary should be rendered from persisted dialogue state")


def test_session_memory_surfaces_durable_candidates_from_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        summary = manager.update_from_messages(
            [
                Message(role="user", content="以后默认先给结论，再展开解释。"),
                Message(role="assistant", content="结论：我会默认先给结论，再展开解释。"),
                Message(role="user", content="终端命令优先用 PowerShell。"),
            ]
        )

        state = manager.load_state()

        _assert(state.durable_candidates, "dialogue state should persist durable candidates")
        _assert("# Durable Candidates" in summary, "summary should expose the durable candidate section")
        _assert(
            any(candidate.memory_class in {"preference", "work"} for candidate in state.durable_candidates),
            "durable candidates should preserve candidate memory classes",
        )
        _assert(
            all(
                candidate.source_kind in {"user_preference", "session_convention", "project_decision", "user_request"}
                for candidate in state.durable_candidates
            ),
            "durable candidate source kinds should use the canonical post-refactor names",
        )


def test_session_memory_surfaces_risk_watch_and_flags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        summary = manager.update_from_messages(
            [
                Message(role="user", content="Please continue the task."),
                Message(role="assistant", content="error: failed to load source"),
                Message(role="assistant", content="exception: failed again while parsing"),
            ]
        )

        state = manager.load_state()

        _assert("# Risk Watch" in summary, "summary should include risk watch section")
        _assert(state.risk_flags, "state should persist at least one risk flag in repeated-failure cases")
        _assert(
            any(flag in {"unresolved_error_loop", "low_flow_confidence"} for flag in state.risk_flags),
            "risk flags should include loop or confidence risk signals",
        )


def test_session_memory_persists_process_state_and_view_mirrors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = SessionMemoryManager(root)
        rendered = manager.update_from_messages(
            [
                Message(role="user", content="Refactor the session memory runtime into a process-state-driven design."),
                Message(role="assistant", content="Conclusion: process state should be authoritative and markdown should stay a view."),
            ]
        )

        process_state_path = root / "process_state.json"
        state_path = root / "state.json"
        agent_view_path = root / "views" / "agent_view.md"
        compaction_view_path = root / "views" / "compaction_view.md"
        summary_path = root / "summary.md"

        _assert(process_state_path.exists(), "process-state authority file should be created")
        _assert(state_path.exists(), "state mirror should still be emitted during migration")
        _assert(agent_view_path.exists(), "agent view should be written as the primary rendered view")
        _assert(compaction_view_path.exists(), "compaction view should be written as a dedicated restore-oriented view")
        _assert(summary_path.exists(), "summary view mirror should still be emitted during migration")
        _assert(
            process_state_path.read_text(encoding="utf-8") == state_path.read_text(encoding="utf-8"),
            "state.json should mirror process_state.json during migration",
        )
        _assert(
            agent_view_path.read_text(encoding="utf-8") == summary_path.read_text(encoding="utf-8"),
            "summary.md should mirror the primary agent view during migration",
        )
        _assert(
            "# Active Goal" in compaction_view_path.read_text(encoding="utf-8"),
            "compaction view should preserve rendered state sections needed for restore",
        )
        _assert("# Conventions and Constraints" in rendered, "agent view should render the canonical conventions section")
        _assert("# Workflow and Constraints" not in rendered, "agent view should not render the legacy workflow section name")
        _assert("What flow is currently active" in rendered, "agent view should use the canonical flow prompt")
        _assert("What workflow is currently active" not in rendered, "agent view should not use the legacy workflow prompt")

        persisted_payload = json.loads(process_state_path.read_text(encoding="utf-8"))
        persisted_state = manager.load_state()

        _assert(
            persisted_payload["active_goal"] == persisted_state.active_goal,
            "loading state should read from the process-state authority payload",
        )
        _assert(
            "conventions_and_constraints" in persisted_payload,
            "process state should persist the canonical conventions field",
        )
        _assert(
            "workflow_and_constraints" not in persisted_payload,
            "process state should stop persisting the legacy workflow field name",
        )
        storage = manager.describe_storage()
        _assert("state_mirror_path" in storage, "storage description should expose mirror paths with canonical names")
        _assert("view_mirror_path" in storage, "storage description should expose mirror view paths with canonical names")
        _assert("compatibility_state_path" not in storage, "storage description should stop exposing compatibility-era field names")
        _assert("compatibility_view_path" not in storage, "storage description should stop exposing compatibility-era field names")


def test_session_memory_can_fallback_to_legacy_state_file_when_process_state_is_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = SessionMemoryManager(root)
        manager.update_from_messages(
            [
                Message(role="user", content="Keep the legacy state file readable during the migration."),
                Message(role="assistant", content="Conclusion: process-state rollout should keep old readers alive."),
            ]
        )

        process_state_path = root / "process_state.json"
        state_path = root / "state.json"
        legacy_payload = json.loads(state_path.read_text(encoding="utf-8"))

        process_state_path.unlink()
        loaded_state = manager.load_state()

        _assert(
            loaded_state.active_goal == legacy_payload["active_goal"],
            "loading should fall back to state.json when process_state.json is absent",
        )


def test_process_state_can_read_legacy_workflow_field_but_rewrite_canonical_field() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = SessionMemoryManager(root)
        state_path = root / "state.json"
        process_state_path = root / "process_state.json"

        legacy_payload = {
            "version": 1,
            "active_goal": "Keep the old state readable during migration.",
            "workflow_and_constraints": ["Terminal commands default to PowerShell."],
        }
        state_path.write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        loaded_state = manager.load_state()
        manager.state_manager.overwrite(loaded_state)
        rewritten_payload = json.loads(process_state_path.read_text(encoding="utf-8"))

        _assert(
            loaded_state.conventions_and_constraints == ["Terminal commands default to PowerShell."],
            "legacy workflow field should still hydrate the canonical conventions field",
        )
        _assert(
            "conventions_and_constraints" in rewritten_payload,
            "rewritten process state should persist the canonical conventions field",
        )
        _assert(
            "workflow_and_constraints" not in rewritten_payload,
            "rewritten process state should not re-emit the legacy workflow field",
        )


def test_session_memory_collection_excludes_process_state_json_from_retrieval_sources() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_default_collections = _load_build_default_collections()
        collection = build_default_collections(root)["session_memory"]

        _assert(
            ".json" not in collection.file_extensions,
            "session-memory retrieval collection should not index internal process-state json files",
        )
        _assert(
            ".md" in collection.file_extensions,
            "session-memory retrieval collection should continue indexing rendered markdown views",
        )


def test_session_processor_exposes_split_understanding_and_process_collaborators() -> None:
    processor = SessionUnderstandingProcessor()
    messages = [
        Message(role="user", content="Continue refactoring the session memory pipeline."),
        Message(role="assistant", content="Conclusion: split understanding, reconciliation, and process assembly."),
    ]
    empty_state = SessionMemoryManager(Path(tempfile.gettempdir())).load_state()
    snapshot = processor.turn_analyzer.analyze(messages, empty_state)
    reconciled = processor.reconciler.review(snapshot, empty_state)
    assembled = processor.process_engine.assemble(reconciled.snapshot, empty_state, decision=reconciled.decision)
    direct_state = processor.process(messages, empty_state)

    _assert(
        processor.process_engine.turn_analyzer is processor.turn_analyzer,
        "process-state assembly should consume the dedicated turn-understanding analyzer",
    )
    _assert(
        assembled.active_goal == direct_state.active_goal,
        "direct pipeline assembly should match the end-to-end processor result for active goal",
    )
    _assert(
        processor.reconciler is not None,
        "session processor should expose a reconciliation gate between understanding and process commit",
    )
    _assert(
        list(assembled.current_task_state) == list(direct_state.current_task_state),
        "direct pipeline assembly should match the end-to-end processor result for current task state",
    )


def test_correction_feedback_clears_stale_slots_and_blocks_wrong_result_promotion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [
                Message(role="user", content="请分析 report.pdf 第3页的结论"),
                Message(role="assistant", content="结论：report.pdf 第3页主要讲的是市场份额持续增长。"),
                Message(role="user", content="你查的不对"),
            ]
        )

        state = manager.load_state()
        summary = manager.load()

        _assert(
            "report.pdf 第3页" in state.active_goal,
            "repair-state commit should preserve the prior active goal after explicit correction",
        )
        _assert(not state.context_slots.active_pdf, "explicit correction should clear the stale active_pdf slot")
        _assert(not state.context_slots.active_entity, "explicit correction should clear the stale active_entity slot")
        _assert(
            all("市场份额持续增长" not in item for item in state.key_results),
            "wrong assistant result should be blocked from key_results after correction",
        )
        _assert(
            any(flag == "state_repair_pending" for flag in state.risk_flags),
            "repair-state commit should surface an explicit repair risk flag",
        )
        _assert(
            "你查的不对" in summary,
            "rendered summary should continue surfacing the latest user correction",
        )


def test_low_confidence_flow_switch_stays_on_previous_flow_until_clarified() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [
                Message(role="user", content="请分析 report.pdf 第3页的结论"),
                Message(role="assistant", content="结论：第3页主要讲供应链风险。"),
            ]
        )
        manager.update_from_messages(
            [
                Message(role="user", content="请分析 report.pdf 第3页的结论"),
                Message(role="assistant", content="结论：第3页主要讲供应链风险。"),
                Message(role="user", content="我想看看这个该怎么弄"),
            ]
        )

        state = manager.load_state()
        summary = manager.load()

        _assert(
            "report.pdf 第3页" in state.active_goal,
            "low-confidence switch should preserve the previous goal instead of committing the ambiguous new one",
        )
        _assert(
            state.flow_state.flow_type == "pdf_analysis_flow",
            "low-confidence switch should keep the previous flow active",
        )
        _assert(
            state.flow_state.confidence <= 0.54,
            "preserved flow should be downgraded to a conservative confidence level",
        )
        _assert(
            any(flag in {"clarification_required", "low_flow_confidence"} for flag in state.risk_flags),
            "downgraded flow switch should surface clarification or low-confidence risks",
        )
        _assert(
            any("澄清" in item for item in state.next_step),
            "next-step planning should ask for clarification before switching the flow",
        )
        _assert(
            "上一阶段目标" not in summary,
            "downgraded flow switch should not demote the existing flow into warm context as if a hard switch happened",
        )


def test_corrected_assistant_reply_can_reenter_state_after_user_correction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [
                Message(role="user", content="请分析 report.pdf 第3页的结论"),
                Message(role="assistant", content="结论：report.pdf 第3页主要讲的是市场份额持续增长。"),
                Message(role="user", content="你查的不对"),
                Message(role="assistant", content="结论：我重新核对后，第3页主要讲的是成本压力和利润收缩。"),
            ]
        )

        state = manager.load_state()
        summary = manager.load()

        _assert(
            any("成本压力和利润收缩" in item for item in state.key_results),
            "assistant recovery reply should be allowed back into key_results after the correction turn",
        )
        _assert(
            all("市场份额持续增长" not in item for item in state.key_results),
            "the contradicted earlier result should remain blocked after recovery",
        )
        _assert(
            state.context_slots.active_pdf == "report.pdf",
            "once the assistant recovers after correction, valid slots should be rebuilt from the surviving context",
        )
        _assert(
            "成本压力和利润收缩" in summary,
            "rendered summary should expose the corrected assistant result instead of the blocked one",
        )


def main() -> None:
    tests = [
        test_session_memory_hygiene,
        test_session_memory_compact_view_uses_state_sections,
        test_session_memory_persists_dialogue_state_separately_from_summary,
        test_session_memory_surfaces_durable_candidates_from_state,
        test_session_memory_surfaces_risk_watch_and_flags,
        test_session_memory_persists_process_state_and_view_mirrors,
        test_session_memory_can_fallback_to_legacy_state_file_when_process_state_is_missing,
        test_process_state_can_read_legacy_workflow_field_but_rewrite_canonical_field,
        test_session_memory_collection_excludes_process_state_json_from_retrieval_sources,
        test_session_processor_exposes_split_understanding_and_process_collaborators,
        test_correction_feedback_clears_stale_slots_and_blocks_wrong_result_promotion,
        test_low_confidence_flow_switch_stays_on_previous_flow_until_clarified,
        test_corrected_assistant_reply_can_reenter_state_after_user_correction,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
