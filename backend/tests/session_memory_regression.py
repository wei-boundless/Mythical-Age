from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import tempfile
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from structured_memory import DialogueState, Message, SessionMemoryManager, TurnUnderstandingAnalyzer
from structured_memory.session_processor import SessionUnderstandingProcessor


@dataclass(slots=True)
class _ProjectionCandidate:
    source_kind: str
    canonical_statement: str


def _collect_projection_candidates(
    *,
    active_goal: str,
    convention_items: list[str],
    decision_items: list[str],
    correction_items: list[str] | None = None,
    max_items: int,
) -> list[_ProjectionCandidate]:
    preference_markers = (
        "喜欢",
        "偏好",
        "习惯",
        "默认",
        "先给结论",
        "回答方式",
        "reply style",
        "response style",
        "answer style",
        "conclusion first",
        "give the conclusion first",
        "prefer",
        "preference",
    )
    convention_markers = (
        "powershell",
        "workflow",
        "流程",
        "约定",
        "规范",
        "默认",
        "terminal commands",
        "by default",
        "default to",
    )
    project_markers = (
        "记忆系统",
        "memory",
        "rag",
        "架构",
        "项目",
        "长期",
        "project focus",
        "project direction",
        "architecture",
    )

    def _normalize(text: object) -> str:
        return " ".join(str(text or "").strip().split())

    def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
        lowered = _normalize(text).lower()
        return any(marker in lowered for marker in markers)

    candidates: list[_ProjectionCandidate] = []
    seen: set[tuple[str, str]] = set()

    def _append(source_kind: str, text: str) -> None:
        normalized = _normalize(text)
        key = (source_kind, normalized.lower())
        if not normalized or key in seen:
            return
        seen.add(key)
        candidates.append(_ProjectionCandidate(source_kind=source_kind, canonical_statement=normalized))

    if _contains_any(active_goal, preference_markers):
        _append("user_preference", active_goal)
    for item in list(correction_items or []):
        if _contains_any(item, preference_markers):
            _append("user_preference", item)
    for item in convention_items:
        if _contains_any(item, convention_markers):
            _append("session_convention", item)
    for item in decision_items:
        if _contains_any(item, project_markers):
            _append("project_decision", item)

    return candidates[:max_items]


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
            Message(role="assistant", content="已修复显式多任务编排，并通过 query_planner_regression.py 测试。"),
        ]

        summary = manager.update_from_messages(messages)

        _assert("我是**河伯**" not in summary, "identity intro should be filtered from session summary")
        _assert('"results"' not in summary, "raw JSON payloads should be filtered from session summary")
        _assert("backend/graph/agent.py" in summary, "important file hints should be preserved")
        _assert("复合问题拆分" in summary, "current goal should be preserved")
        _assert("已修复显式多任务编排" in summary, "useful assistant result should be preserved")


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
        _assert(
            "# Current Task State" not in compact,
            "compact view should stop exposing governance-heavy current-task sections by default",
        )
        _assert("# Next Step" not in compact, "compact view should stop exposing orchestration-only next-step guidance")
        _assert("# Workflow and Constraints" not in compact, "compact view should stop rendering the legacy workflow section name")
        _assert("What flow is currently active" in compact, "compact view should use the canonical flow description")
        _assert("What workflow is currently active" not in compact, "compact view should stop rendering the legacy workflow prompt")
        _assert("session hygiene" in compact or "session state" in compact, "compact view should preserve restore-relevant content")


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


def test_session_memory_no_longer_synthesizes_durable_candidates_from_state() -> None:
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

        _assert(not hasattr(state, "durable_candidates"), "working-memory state should no longer expose durable-candidate fields")
        _assert("# Durable Candidates" not in summary, "working-memory summary should stop rendering durable candidate sections")


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
        debug_view = manager.load_debug_view()

        _assert("# Risk Watch" not in summary, "model-visible summary should not expose risk watch section")
        _assert("# Risk Watch" in debug_view, "debug session view should retain risk watch section")
        _assert(state.risk_flags, "state should persist at least one risk flag in repeated-failure cases")
        _assert(
            any(flag in {"unresolved_error_loop", "low_flow_confidence"} for flag in state.risk_flags),
            "risk flags should include loop or confidence risk signals",
        )


def test_session_memory_accepts_summary_first_context_projection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        summary = manager.update_from_context_state(
            {
                "active_goal": "只展开第二个子任务，给我 inventory.xlsx 里最缺货的前三个仓库。",
                "active_work_item": "explicit_fanout",
                "active_constraints": {"top_n": 3, "group_by": "仓库", "response_style": "brief"},
                "latest_correction": "不是按地区，按仓库。",
                "next_step": "follow_up_or_refine_subtask_results",
            },
            task_summaries=[
                {
                    "task_id": "task-2",
                    "query": "给我 inventory.xlsx 里最缺货的前三个仓库",
                    "summary": "武汉仓缺口 404，上海仓缺口 392，深圳仓缺口 392。",
                    "key_points": ["top_n=3", "dataset=inventory.xlsx"],
                }
            ],
            corrections=["不是按地区，按仓库。"],
        )

        state = manager.load_state()

        _assert("inventory.xlsx" in state.active_goal, "summary-first refresh should preserve the active goal")
        _assert(
            any("武汉仓缺口 404" in item for item in state.key_results),
            "summary-first refresh should project task summaries into key results",
        )
        _assert(
            "不是按地区，按仓库。" in summary,
            "summary-first refresh should preserve explicit corrections in the rendered view",
        )
        _assert(
            any("top_n=3" in item or "group_by=仓库" in item for item in state.conventions_and_constraints),
            "summary-first refresh should surface active constraints without needing raw transcript replay",
        )


def test_summary_first_context_projection_does_not_reenter_message_processor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))

        def _fail_process(*_args, **_kwargs):
            raise AssertionError("summary-first context projection should not go back through message processing")

        manager.processor.process = _fail_process  # type: ignore[method-assign]
        summary = manager.update_from_context_state(
            {
                "active_goal": "继续分析 report.pdf 第二部分第3页的结论。",
                "active_work_item": "pdf_analysis",
                "active_constraints": {
                    "page": 3,
                    "source_kind": "pdf",
                    "pdf_mode": "section",
                    "pdf_section": "第二部分",
                    "pdf_focus_pages": [3, 4],
                },
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "继续分析 report.pdf 第二部分第3页的结论。",
                    "summary": "第三页主要在讨论供应链风险和现金流压力。",
                    "key_points": ["page=3", "pdf=report.pdf", "pdf_mode=section", "pdf_section=第二部分", "pdf_pages=3,4"],
                }
            ],
        )

        state = manager.load_state()
        _assert("report.pdf" in summary, "summary-first context projection should still render the projected goal")
        _assert(state.context_slots.active_pdf == "report.pdf", "summary-first projection should rebuild slots directly from context state")
        _assert(state.context_slots.active_pdf_mode == "section", "summary-first projection should rebuild the PDF read mode")
        _assert(state.context_slots.active_pdf_section == "第二部分", "summary-first projection should rebuild the PDF section focus")
        _assert(state.context_slots.active_pdf_pages == [3, 4], "summary-first projection should rebuild the focused PDF pages")
        _assert("PDF 查询范围：section" in summary, "model-visible summary should expose the active PDF mode")
        _assert("PDF 当前章节：第二部分" in summary, "model-visible summary should expose the active PDF section")
        _assert(not hasattr(state, "durable_candidates"), "summary-first context projection should not restore the removed durable-candidate field")


def test_summary_first_context_projection_prefers_committed_binding_over_text_scan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "只展开第二个子任务，给我仓库和缺货量。",
                "active_work_item": "structured_data_followup",
                "active_constraints": {
                    "source_kind": "dataset",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                },
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "task-2",
                    "query": "给我 inventory.xlsx 最缺货的前三个仓库",
                    "summary": "当前结果里顺带提到了 employees.xlsx，但当前绑定不应被它覆盖。",
                    "key_points": ["dataset=knowledge/E-commerce Data/inventory.xlsx"],
                }
            ],
        )

        state = manager.load_state()

        _assert(
            state.context_slots.active_dataset == "knowledge/E-commerce Data/inventory.xlsx",
            "summary-first projection should take the committed dataset binding instead of rescanning incidental filenames",
        )
        _assert(
            state.context_slots.active_binding_identity.endswith("inventory.xlsx"),
            "summary-first projection should persist the committed binding identity alongside the dataset slot",
        )
        _assert(
            state.context_slots.active_binding_owner_task_id == "task-2",
            "summary-first projection should preserve the concrete owner task for the committed binding",
        )


def test_summary_first_projection_does_not_carry_forward_stale_dataset_slot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "先看 inventory.xlsx 的缺货情况。",
                "active_work_item": "structured_data_analysis",
                "active_constraints": {
                    "source_kind": "dataset",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                },
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "inventory-task",
                    "query": "先看 inventory.xlsx 的缺货情况。",
                    "summary": "inventory.xlsx 里华东仓库缺货最严重。",
                    "key_points": ["dataset=knowledge/E-commerce Data/inventory.xlsx"],
                }
            ],
        )

        summary = manager.update_from_context_state(
            {
                "active_goal": "那下一步继续整理成汇报结构，不用再看表。",
                "active_work_item": "report_structuring",
                "active_constraints": {"response_style": "outline"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "outline-task",
                    "query": "整理成汇报结构",
                    "summary": "先按结论、风险、建议三个部分组织。",
                }
            ],
        )

        state = manager.load_state()

        _assert(
            not state.context_slots.active_dataset,
            "summary-first projection should not inherit a stale dataset slot when the current turn has no committed owner",
        )
        _assert(
            "当前数据集：" not in summary,
            "model-visible summary should stop exposing stale dataset bindings as current context",
        )


def test_summary_first_model_view_hides_active_rule_and_next_step_prose() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "把第一个和第三个子任务各压成一句话，不要重复第二个。",
                "active_work_item": "followup_task_subset_assembly",
                "active_constraints": {"response_style": "one_sentence", "dedupe": True},
                "next_step": "answer_selected_task_results",
            },
            task_summaries=[
                {
                    "task_id": "task-1",
                    "query": "总结 PDF 第三页",
                    "summary": "第三页主要讨论供应链风险。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                },
                {
                    "task_id": "task-3",
                    "query": "补一句北京天气",
                    "summary": "北京当前阴天，12.4°C。",
                    "key_points": [],
                },
            ],
        )

        model_view = manager.load()
        debug_view = manager.load_debug_view()

        _assert("当前规则：" not in model_view, "model-visible session view should hide active_rule prose")
        _assert("当前下一步：" not in model_view, "model-visible session view should hide next-step prose")
        _assert(
            "当前规则：" in debug_view or "# Next Step" in debug_view,
            "debug view should retain governance-only fields",
        )


def test_summary_first_projection_state_strips_governance_prose_at_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "把第一个和第三个子任务各压成一句话，不要重复第二个。",
                "active_work_item": "followup_task_subset_assembly",
                "active_constraints": {"response_style": "one_sentence", "dedupe": True},
                "latest_correction": "不要重复第二个。",
                "next_step": "answer_selected_task_results",
            },
            task_summaries=[
                {
                    "task_id": "task-1",
                    "query": "总结 PDF 第三页",
                    "summary": "第三页主要讨论供应链风险。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                },
                {
                    "task_id": "task-3",
                    "query": "补一句北京天气",
                    "summary": "北京当前阴天，12.4°C。",
                    "key_points": [],
                },
            ],
            corrections=["不要重复第二个。"],
        )

        state = manager.load_state()

        _assert(
            state.context_slots.active_rule == "",
            "summary-first projection should stop materializing active_rule control prose in state",
        )
        _assert(
            not state.next_step and state.task_state.next_step == "",
            "summary-first projection should not persist orchestration next-step prose in working state",
        )
        _assert(
            all(
                not item.startswith(("当前工作项：", "当前下一步：", "最新纠正："))
                for item in state.current_task_state
            ),
            "summary-first projection should keep current-task state to goal/constraint/result facts only",
        )
        _assert(
            state.task_state.current_step.startswith(("整理结果：", "当前目标：", "围绕当前目标回答：")),
            "summary-first projection should keep task_state.current_step as control-truth, not workflow logging",
        )


def test_summary_first_projection_warm_context_uses_results_not_previous_task_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "总结 PDF 第三页。",
                "active_work_item": "pdf_analysis",
                "active_constraints": {"page": 3, "source_kind": "pdf"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "task-1",
                    "query": "总结 PDF 第三页",
                    "summary": "第三页主要讨论供应链风险。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "补一句北京天气。",
                "active_work_item": "weather_lookup",
                "active_constraints": {"source_kind": "weather"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "task-2",
                    "query": "补一句北京天气",
                    "summary": "北京当前晴朗，12.4°C。",
                    "key_points": [],
                }
            ],
        )

        state = manager.load_state()

        _assert(
            all("延续状态：" not in item and "上一阶段状态：" not in item for item in state.warm_context),
            "summary-first warm context should stop rehydrating prior task-state prose",
        )
        _assert(
            any("上一阶段结果：" in item for item in state.warm_context),
            "summary-first warm context should retain prior result summaries as restore hints",
        )


def test_projection_candidate_pipeline_stays_conservative_and_preference_first() -> None:
    preference_candidates = _collect_projection_candidates(
        active_goal="以后默认先给结论，再展开解释。",
        convention_items=["response_style=brief"],
        decision_items=[],
        correction_items=[],
        max_items=6,
    )
    task_candidates = _collect_projection_candidates(
        active_goal="给我 inventory.xlsx 里最缺货的前三个仓库。",
        convention_items=["top_n=3", "group_by=仓库"],
        decision_items=["武汉仓缺口 404，上海仓缺口 392，深圳仓缺口 392。"],
        correction_items=["不是按地区，按仓库。"],
        max_items=6,
    )

    _assert(
        any(candidate.source_kind == "user_preference" for candidate in preference_candidates),
        "projection candidate pipeline should still promote stable user preferences",
    )
    _assert(
        all("inventory.xlsx" not in candidate.canonical_statement for candidate in task_candidates),
        "projection candidate pipeline should stay conservative about task-local dataset requests",
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
        debug_view_path = root / "views" / "debug_view.md"
        compaction_view_path = root / "views" / "compaction_view.md"
        summary_path = root / "summary.md"

        _assert(process_state_path.exists(), "process-state authority file should be created")
        _assert(state_path.exists(), "state mirror should still be emitted during migration")
        _assert(agent_view_path.exists(), "agent view should be written as the primary rendered view")
        _assert(debug_view_path.exists(), "debug view should be written as a dedicated verbose session view")
        _assert(compaction_view_path.exists(), "compaction view should be written as a dedicated restore-oriented view")
        _assert(summary_path.exists(), "summary view mirror should still be emitted during migration")
        _assert(
            process_state_path.read_text(encoding="utf-8") == state_path.read_text(encoding="utf-8"),
            "state.json should mirror process_state.json during migration",
        )
        _assert(
            agent_view_path.read_text(encoding="utf-8") == debug_view_path.read_text(encoding="utf-8"),
            "agent_view.md should mirror the verbose debug session view",
        )
        _assert(
            agent_view_path.read_text(encoding="utf-8") != summary_path.read_text(encoding="utf-8"),
            "summary.md should now be the narrowed model-visible restore view, not a mirror of the debug view",
        )
        _assert(
            "# Active Goal" in compaction_view_path.read_text(encoding="utf-8"),
            "compaction view should preserve rendered state sections needed for restore",
        )
        _assert("# Workflow and Constraints" not in rendered, "agent view should not render the legacy workflow section name")
        _assert("What flow is currently active" in rendered, "agent view should use the canonical flow prompt")
        _assert("What workflow is currently active" not in rendered, "agent view should not use the legacy workflow prompt")
        _assert("# Next Step" not in rendered, "model-visible session view should not include orchestration-only next-step guidance")

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
        _assert(
            "durable_candidates" not in persisted_payload,
            "process state should stop persisting empty durable-candidate payloads on the main working-memory path",
        )
        storage = manager.describe_storage()
        _assert("state_mirror_path" in storage, "storage description should expose mirror paths with canonical names")
        _assert("debug_view_path" in storage, "storage description should expose the debug session view path")
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


def test_turn_understanding_keeps_workspace_owner_out_of_understanding_snapshot() -> None:
    analyzer = TurnUnderstandingAnalyzer()
    snapshot = analyzer.analyze(
        [Message(role="user", content="Continue refactoring the session memory pipeline.")],
        DialogueState(),
    )

    _assert(
        snapshot.active_understanding.understanding.target_object is None,
        "turn understanding should not invent a workspace owner from coding-language heuristics",
    )
    _assert(
        snapshot.turn_trace[-1].target_object == "",
        "turn trace should no longer persist inferred target_object owner truth",
    )


def test_flow_id_uses_goal_slug_instead_of_inferred_owner_token() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_messages(
            [Message(role="user", content="Continue refactoring the session memory pipeline.")]
        )

        state = manager.load_state()

        _assert(
            state.flow_state.flow_type == "coding_change_flow",
            "coding-oriented requests should still resolve to the coding flow",
        )
        _assert(
            not state.flow_state.flow_id.endswith(":session-memory"),
            "flow id should be derived from the active goal slug, not an inferred target_object token",
        )
        _assert(
            "continue-refactoring-the-session-memory-pipeline" in state.flow_state.flow_id,
            "flow id should preserve the active goal slug after removing inferred owner synthesis",
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


def test_message_pipeline_does_not_carry_forward_stale_pdf_slot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        messages = [
            Message(role="user", content="请分析 report.pdf 第3页的结论"),
            Message(role="assistant", content="结论：report.pdf 第3页主要讲供应链风险。"),
        ]
        manager.update_from_messages(messages)

        messages.append(Message(role="user", content="那下一步继续整理输出结构，不用再看文件。"))
        summary = manager.update_from_messages(messages)
        state = manager.load_state()

        _assert(
            not state.context_slots.active_pdf,
            "message pipeline should not inherit a stale pdf slot when the latest turn no longer commits an active file owner",
        )
        _assert(
            "当前 PDF：" not in summary,
            "model-visible summary should stop exposing stale pdf bindings as current context",
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


def test_summary_first_projection_clears_binding_owner_when_no_committed_handle_survives() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "先看 inventory.xlsx 的缺货情况。",
                "active_work_item": "structured_data_analysis",
                "active_constraints": {
                    "source_kind": "dataset",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                    "active_binding_identity": "knowledge/e-commerce data/inventory.xlsx",
                },
                "followup_target_task_id": "dataset-task",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "dataset-task",
                    "query": "先看 inventory.xlsx 的缺货情况",
                    "summary": "库存里武汉仓和上海仓缺货最多。",
                    "key_points": ["dataset=knowledge/E-commerce Data/inventory.xlsx"],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "那下一步继续整理成汇报结构，不用再看表。",
                "active_work_item": "report_structuring",
                "active_constraints": {"response_style": "outline"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "outline-task",
                    "query": "整理成汇报结构",
                    "summary": "先按结论、风险、建议三个部分组织。",
                }
            ],
        )

        state = manager.load_state()

        _assert(
            not state.context_slots.active_binding_identity,
            "when the current turn no longer commits a binding owner, the restore layer should clear binding identity with the stale slot",
        )
        _assert(
            not state.context_slots.active_binding_owner_task_id,
            "when the current turn no longer commits a binding owner, the restore layer should clear the stale owner task",
        )


def test_summary_first_projection_preserves_committed_dataset_binding_across_external_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "切到 knowledge/E-commerce Data/inventory.xlsx，先看哪些仓库缺货。",
                "active_work_item": "structured_data_analysis",
                "active_constraints": {
                    "source_kind": "dataset",
                    "active_dataset": "knowledge/E-commerce Data/inventory.xlsx",
                },
                "followup_target_task_id": "dataset-task",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "dataset-task",
                    "query": "切到 knowledge/E-commerce Data/inventory.xlsx，先看哪些仓库缺货。",
                    "summary": "inventory.xlsx 里武汉仓缺口最高。",
                    "key_points": ["dataset=knowledge/E-commerce Data/inventory.xlsx"],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "顺便查一下黄金价格。",
                "active_work_item": "gold_price_query",
                "active_constraints": {"source_kind": "web"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "gold-task",
                    "query": "顺便查一下黄金价格。",
                    "summary": "现货黄金处于高位。",
                }
            ],
        )

        state = manager.load_state()

        _assert(
            not state.context_slots.active_dataset,
            "cross-flow projection should stop exposing the dataset as the active slot after switching to external lookup",
        )
        _assert(
            state.context_slots.committed_dataset == "knowledge/E-commerce Data/inventory.xlsx",
            "cross-flow projection should retain the latest committed dataset binding for later follow-up recovery",
        )
        _assert(
            state.context_slots.committed_dataset_owner_task_id == "dataset-task",
            "cross-flow projection should retain the committed dataset owner task for later follow-up recovery",
        )


def test_summary_first_projection_preserves_committed_pdf_binding_across_summary_turn() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "请分析 report.pdf 第二部分的约束。",
                "active_work_item": "pdf_analysis",
                "active_constraints": {
                    "source_kind": "pdf",
                    "active_pdf": "knowledge/reports/report.pdf",
                    "pdf_mode": "section",
                    "pdf_section": "第二部分",
                },
                "followup_target_task_id": "pdf-task",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "请分析 report.pdf 第二部分的约束。",
                    "summary": "第二部分强调了权限边界和审计责任。",
                    "key_points": [
                        "pdf=knowledge/reports/report.pdf",
                        "pdf_mode=section",
                        "pdf_section=第二部分",
                    ],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。",
                "active_work_item": "session_summary",
                "active_constraints": {"response_style": "brief"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "summary-task",
                    "query": "把库存、员工、黄金和天气这四块信息分开给我一个运营摘要。",
                    "summary": "已整理为四块运营摘要。",
                }
            ],
        )

        state = manager.load_state()

        _assert(
            not state.context_slots.active_pdf,
            "summary projection should not keep the PDF as the active slot when the current turn is no longer reading the document",
        )
        _assert(
            state.context_slots.committed_pdf == "knowledge/reports/report.pdf",
            "summary projection should retain the latest committed PDF binding for later follow-up recovery",
        )
        _assert(
            state.context_slots.committed_pdf_owner_task_id == "pdf-task",
            "summary projection should retain the committed PDF owner task for later follow-up recovery",
        )


def main() -> None:
    tests = [
        test_session_memory_hygiene,
        test_session_memory_compact_view_uses_state_sections,
        test_session_memory_persists_dialogue_state_separately_from_summary,
        test_session_memory_no_longer_synthesizes_durable_candidates_from_state,
        test_session_memory_surfaces_risk_watch_and_flags,
        test_session_memory_accepts_summary_first_context_projection,
        test_summary_first_context_projection_does_not_reenter_message_processor,
        test_summary_first_context_projection_prefers_committed_binding_over_text_scan,
        test_summary_first_model_view_hides_active_rule_and_next_step_prose,
        test_summary_first_projection_state_strips_governance_prose_at_source,
        test_summary_first_projection_warm_context_uses_results_not_previous_task_state,
        test_projection_candidate_pipeline_stays_conservative_and_preference_first,
        test_session_memory_persists_process_state_and_view_mirrors,
        test_session_memory_can_fallback_to_legacy_state_file_when_process_state_is_missing,
        test_process_state_can_read_legacy_workflow_field_but_rewrite_canonical_field,
        test_session_memory_collection_excludes_process_state_json_from_retrieval_sources,
        test_session_processor_exposes_split_understanding_and_process_collaborators,
        test_turn_understanding_keeps_workspace_owner_out_of_understanding_snapshot,
        test_flow_id_uses_goal_slug_instead_of_inferred_owner_token,
        test_correction_feedback_clears_stale_slots_and_blocks_wrong_result_promotion,
        test_low_confidence_flow_switch_stays_on_previous_flow_until_clarified,
        test_corrected_assistant_reply_can_reenter_state_after_user_correction,
        test_summary_first_projection_clears_binding_owner_when_no_committed_handle_survives,
        test_summary_first_projection_preserves_committed_dataset_binding_across_external_lookup,
        test_summary_first_projection_preserves_committed_pdf_binding_across_summary_turn,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
