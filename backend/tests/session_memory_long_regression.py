from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from structured_memory import Message, SessionMemoryManager


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sections(manager: SessionMemoryManager) -> dict[str, list[str]]:
    return manager._parse_sections(manager.load())  # noqa: SLF001


def _run_batches(manager: SessionMemoryManager, batches: list[list[Message]]) -> str:
    transcript: list[Message] = []
    summary = ""
    for batch in batches:
        transcript.extend(batch)
        summary = manager.update_from_messages(transcript)
    return summary


def test_follow_up_keeps_same_task_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        _run_batches(
            manager,
            [
                [
                    Message(role="user", content="帮我重构 session memory，让它变成 task/state 工作记忆"),
                    Message(role="assistant", content="结论：session memory 不应该等于历史会话，而应该是当前任务状态。"),
                ],
                [
                    Message(role="user", content="那下一步继续把它做成弹性状态层"),
                    Message(role="assistant", content="已完成第一版 Hot/Warm 结构设计。"),
                ],
            ],
        )

        summary = manager.load()
        sections = _sections(manager)
        warm = "\n".join(sections.get("# Warm Context", []))
        state = "\n".join(sections.get("# Current Task State", []))

        _assert("上一阶段目标" not in warm, "follow-up should not be treated as a hard task switch")
        _assert("延续状态" in warm or "近期结论" in warm, "same-task follow-up should preserve prior context")
        _assert("Hot/Warm" in warm or "Hot/Warm" in state or "Hot/Warm" in summary, "recent design state should stay visible")


def test_explicit_switch_demotes_old_state_into_warm_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        _run_batches(
            manager,
            [
                [
                    Message(role="user", content="帮我继续优化记忆系统的 session memory"),
                    Message(role="assistant", content="结论：先把 session memory 和 session log 的职责分开。"),
                ],
                [
                    Message(role="user", content="换个问题，帮我查黄金价格"),
                    Message(role="assistant", content="结果：当前国际黄金现货约 1034 元/克。"),
                ],
            ],
        )

        sections = _sections(manager)
        active_goal = "\n".join(sections.get("# Active Goal", []))
        warm = "\n".join(sections.get("# Warm Context", []))

        _assert("黄金价格" in active_goal, "new active goal should reflect the switched task")
        _assert("上一阶段目标" in warm, "previous task should be demoted into warm context on explicit switch")
        _assert("session memory" in warm, "previous important task should not be forgotten after switching")


def test_returning_to_previous_task_keeps_both_current_and_recent_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        _run_batches(
            manager,
            [
                [
                    Message(role="user", content="帮我改 session memory，让它不要变成长时档案"),
                    Message(role="assistant", content="结论：session memory 只保留当前对话处理层需要的状态。"),
                ],
                [
                    Message(role="user", content="换个问题，帮我查黄金价格"),
                    Message(role="assistant", content="结果：当前国际黄金现货约 1034 元/克。"),
                ],
                [
                    Message(role="user", content="回到刚才的 session memory，继续补安全保护"),
                    Message(role="assistant", content="已补关键状态保留和任务切换降级规则。"),
                ],
            ],
        )

        summary = manager.load()
        sections = _sections(manager)
        warm = "\n".join(sections.get("# Warm Context", []))
        active_goal = "\n".join(sections.get("# Active Goal", []))

        _assert("session memory" in active_goal, "active goal should return to the resumed task")
        _assert("黄金价格" in warm or "1034 元/克" in warm, "brief diversion should remain available as warm context")
        _assert("当前对话处理层" in summary, "original core decision should survive a diversion and return")


def test_long_running_session_retains_key_points_without_unbounded_growth() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        batches = [
            [
                Message(role="user", content="我们先设计 session memory 的职责边界"),
                Message(role="assistant", content="结论：session log archival，session memory operational。"),
            ],
            [
                Message(role="user", content="继续，把它做成 Hot/Warm 双层"),
                Message(role="assistant", content="已确定 Hot State 和 Warm Context 两层结构。"),
            ],
            [
                Message(role="user", content="再补任务切换检测"),
                Message(role="assistant", content="已补任务切换检测，显式切换优先，短跟进不切换。"),
            ],
            [
                Message(role="user", content="还要补记忆可观测性"),
                Message(role="assistant", content="已增加 memory_context 事件，能看到本轮读了哪些记忆。"),
            ],
            [
                Message(role="user", content="最后别忘了安全性，不能重点遗忘"),
                Message(role="assistant", content="已补关键状态保留规则，重点不会因为压缩直接丢失。"),
            ],
        ]

        _run_batches(manager, batches)
        sections = _sections(manager)
        worklog_lines = [line for line in sections.get("# Worklog", []) if line.startswith("- ")]
        warm = "\n".join(sections.get("# Warm Context", []))
        summary = manager.load()

        _assert(len(worklog_lines) <= 6, "worklog should stay compact instead of becoming archival")
        _assert("Hot State" in summary or "Warm Context" in summary, "key structural concepts should survive long-running work")
        _assert("任务切换检测" in warm or "memory_context" in warm, "important near-term milestones should remain in warm context")
        _assert("重点不会因为压缩直接丢失" in summary, "latest safety guarantee should remain visible")


def test_meta_dialogue_and_correction_do_not_replace_active_goal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        _run_batches(
            manager,
            [
                [
                    Message(role="user", content="帮我分析 memory bridge 和 session memory 的关系"),
                    Message(role="assistant", content="结论：先看 session state，再看 summary 渲染链路。"),
                ],
                [
                    Message(role="user", content="你在干什么啊"),
                    Message(role="assistant", content="我在梳理 memory bridge 到 session memory 的状态流。"),
                ],
                [
                    Message(role="user", content="你查的不对"),
                    Message(role="assistant", content="我会回到刚才的 memory bridge 链路重新核对。"),
                ],
            ],
        )

        state = manager.load_state()
        summary = manager.load()

        _assert(
            "memory bridge" in state.active_goal or "session memory" in state.active_goal,
            "meta dialogue and correction should not overwrite the main active goal",
        )
        _assert(
            "你查的不对" in summary,
            "correction feedback should remain visible in the rendered summary",
        )


def test_task_switch_persists_warm_flow_snapshots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = SessionMemoryManager(root)
        _run_batches(
            manager,
            [
                [
                    Message(role="user", content="帮我分析 report.pdf 第3页的结论"),
                    Message(role="assistant", content="结论：第3页主要讲供应链风险。"),
                ],
                [
                    Message(role="user", content="换个问题，帮我查黄金价格"),
                    Message(role="assistant", content="结果：当前国际黄金现货约 1034 元/克。"),
                ],
            ],
        )

        snapshot_path = root / "flow_snapshots.json"
        snapshots = manager.load_flow_snapshots()
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

        _assert(snapshot_path.exists(), "task switch should persist warm flow snapshots to disk")
        _assert(snapshots, "task switch should create at least one warm flow snapshot")
        _assert(
            any(snapshot.flow_type == "pdf_analysis_flow" for snapshot in snapshots),
            "previous PDF flow should be preserved as a warm snapshot after switching away",
        )
        _assert(
            any("report.pdf" in json.dumps(item, ensure_ascii=False) for item in payload),
            "persisted flow snapshot payload should preserve the prior flow slot context",
        )


def test_summary_first_task_switch_persists_restore_candidate_binding_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = SessionMemoryManager(root)
        manager.update_from_context_state(
            {
                "active_goal": "请分析 report.pdf 第3页的结论",
                "active_work_item": "pdf_analysis",
                "active_binding_identity": "report.pdf",
                "followup_target_task_id": "pdf-task",
                "active_constraints": {"page": 3, "source_kind": "pdf"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "请分析 report.pdf 第3页的结论",
                    "summary": "第3页主要讲供应链风险和成本压力。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "换个问题，帮我查黄金价格",
                "active_work_item": "finance_lookup",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "price-task",
                    "query": "帮我查黄金价格",
                    "summary": "当前国际黄金现货约 1034 元/克。",
                }
            ],
        )

        snapshots = manager.load_flow_snapshots()

        _assert(snapshots, "summary-first task switch should still persist warm snapshots")
        pdf_snapshot = next((snapshot for snapshot in snapshots if snapshot.flow_type == "pdf_analysis_flow"), None)
        _assert(pdf_snapshot is not None, "warm snapshots should retain the prior pdf flow")
        _assert(
            pdf_snapshot.binding_identity == "report.pdf",
            "warm snapshots should persist binding identity as restore metadata instead of relying only on raw key slots",
        )
        _assert(
            pdf_snapshot.binding_owner_task_id == "pdf-task",
            "warm snapshots should retain the owner task handle for the suspended binding lineage",
        )


def test_summary_first_projection_preserves_warm_context_on_task_switch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manager = SessionMemoryManager(Path(tmp))
        manager.update_from_context_state(
            {
                "active_goal": "请分析 report.pdf 第3页的结论",
                "active_work_item": "pdf_analysis",
                "active_constraints": {"page": 3, "source_kind": "pdf"},
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "pdf-task",
                    "query": "请分析 report.pdf 第3页的结论",
                    "summary": "第3页主要讲供应链风险和成本压力。",
                    "key_points": ["page=3", "pdf=report.pdf"],
                }
            ],
        )
        manager.update_from_context_state(
            {
                "active_goal": "换个问题，帮我查黄金价格",
                "active_work_item": "finance_lookup",
                "next_step": "answer_current_request",
            },
            task_summaries=[
                {
                    "task_id": "price-task",
                    "query": "帮我查黄金价格",
                    "summary": "当前国际黄金现货约 1034 元/克。",
                }
            ],
        )

        summary = manager.load()
        sections = _sections(manager)
        warm = "\n".join(sections.get("# Warm Context", []))

        _assert("黄金价格" in "\n".join(sections.get("# Active Goal", [])), "summary-first switch should update the active goal")
        _assert("report.pdf" in warm or "供应链风险" in warm, "summary-first switch should demote prior flow into warm context")
        _assert("1034 元/克" in summary, "latest summary-first result should remain visible after the switch")


def main() -> None:
    tests = [
        test_follow_up_keeps_same_task_context,
        test_explicit_switch_demotes_old_state_into_warm_context,
        test_returning_to_previous_task_keeps_both_current_and_recent_context,
        test_long_running_session_retains_key_points_without_unbounded_growth,
        test_meta_dialogue_and_correction_do_not_replace_active_goal,
        test_task_switch_persists_warm_flow_snapshots,
        test_summary_first_task_switch_persists_restore_candidate_binding_metadata,
        test_summary_first_projection_preserves_warm_context_on_task_switch,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"ALL PASSED ({len(tests)} tests)")


if __name__ == "__main__":
    main()
